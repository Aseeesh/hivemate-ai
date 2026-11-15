"""Work Queue, deals, policy, inbox, impact and Ask routes. Called by the main handler; returns None when the path is not ours.

Every read and write is keyed by ctx.pk (from the verified JWT). Nothing in a request body can name another tenant.
"""
import time

from botocore.exceptions import ClientError

from src.common import db, events, policy
from src.common.context import Ctx
from src.pipeline import ask, deals, docintel, followups, impact, inbox, tasks

TASK_ID = r"[A-Za-z0-9._-]{3,120}"


def _r(status: int, body):
    return {"statusCode": status, "body": body}


def _users(ctx: Ctx) -> set[str]:
    return {u.get("email", "") for u in db.query_prefix(ctx.pk, "USER#", limit=100)}


def _visible(ts: list[dict], now: float) -> list[dict]:
    return [t for t in ts if int(t.get("hiddenUntil", 0)) <= now]


def work_summary(ts: list[dict]) -> dict:
    return {"open": sum(t["status"] in ("open", "needs_approval", "failed") for t in ts),
            "needsApproval": sum(t["status"] == "needs_approval" for t in ts), "failed": sum(t["status"] == "failed" for t in ts),
            "urgent": sum(t.get("priority") == "urgent" for t in ts), "byType": {k: sum(t["type"] == k for t in ts) for k in tasks.TYPES}}


def impact_for(ctx: Ctx, days: int) -> dict:
    now = time.time()
    return impact.compute(events.since(ctx.pk, now - days * 86400), deals.list_deals(ctx.pk, 500), policy.get(ctx.pk), now, days)


def route(ctx: Ctx, method: str, path: str, body: dict, query: dict):
    import re
    now = time.time()
    q = lambda k, d="": str((query or {}).get(k, d))

    if (method, path) == ("GET", "/work"):
        status = q("status", "open")
        all_open = tasks.list_tasks(ctx.pk, tasks.OPEN)
        if status == "done":
            rows = [t for t in tasks.list_tasks(ctx.pk) if t["status"] in ("done", "dismissed")]
            rows.sort(key=lambda t: -int(t.get("updatedAt", t["createdAt"])))
            rows = rows[:100]
        else:
            rows = _visible(all_open, now)
        for f in ("type", "channel", "assignee", "priority"):
            if q(f):
                rows = [t for t in rows if t.get(f) == q(f)]
        return _r(200, {"tasks": rows, "summary": work_summary(_visible(all_open, now))})

    m = re.fullmatch(rf"/work/({TASK_ID})/(approve|reject|done|snooze|assign)", path)
    if m and method == "POST":
        tid, action = m.groups()
        task = tasks.get(ctx.pk, tid)
        if not task:
            return _r(404, {"error": "not found"})
        if action == "approve" and task["type"] == "document_review":
            if task["status"] not in tasks.OPEN:
                return _r(409, {"error": f"task is {task['status']}"})
            docintel.decide(ctx.pk, task["docId"], True)
            tasks.set_status(ctx.pk, tid, "done", resolvedBy=ctx.user_id)
            events.record(ctx.pk, "approval_completed", task.get("dealId", ""), task=tid)
            db.audit(ctx.pk, ctx.user_id, "document.approved", {"docId": task["docId"]})
            return _r(200, {"status": "done"})
        if action == "approve":
            try:
                out = followups.deliver(ctx.pk, tid, str(body.get("text") or task.get("draft", "")), actor=ctx.user_id)
            except followups.Conflict as e:
                return _r(409, {"error": str(e)})
            except LookupError:
                return _r(404, {"error": "not found"})
            except (ValueError, ClientError, RuntimeError) as e:
                return _r(422, {"error": str(e)[:300]})
            return _r(200, out)
        if task["status"] not in tasks.OPEN:
            return _r(409, {"error": f"task is {task['status']}"})
        if action == "reject":
            tasks.set_status(ctx.pk, tid, "dismissed", resolvedBy=ctx.user_id)
            if task["type"] == "document_review":
                docintel.decide(ctx.pk, task["docId"], False)
            events.record(ctx.pk, "follow_up_dismissed", task.get("dealId", ""), task=tid)
        elif action == "done":  # the owner dealt with it themselves
            tasks.set_status(ctx.pk, tid, "done", resolvedBy=ctx.user_id, sentVia="manual")
            events.record(ctx.pk, "follow_up_manual" if task["type"] in ("follow_up", "invoice_reminder") else "task_completed", task.get("dealId", ""), task=tid)
            if task["type"] in ("follow_up", "reply_overdue", "cold_lead") and task.get("dealId") and deals.get(ctx.pk, task["dealId"]):
                deals.on_outbound(ctx.pk, task["dealId"], "manual")
        elif action == "snooze":
            hours = body.get("hours", 24)
            if isinstance(hours, bool) or not isinstance(hours, (int, float)) or not 1 <= hours <= 24 * 14:
                return _r(400, {"error": "hours must be between 1 and 336"})
            db.update(tasks.key(ctx.pk, tid), sets={"hiddenUntil": int(now + hours * 3600)})
        elif action == "assign":
            who = str(body.get("assignee", ""))
            if who and who not in _users(ctx):
                return _r(400, {"error": "assignee must be a member of this business"})
            db.update(tasks.key(ctx.pk, tid), sets={"assignee": who})
        db.audit(ctx.pk, ctx.user_id, f"task.{action}", {"taskId": tid})
        return _r(200, {"ok": True})

    if (method, path) == ("GET", "/team"):
        return _r(200, {"members": sorted(e for e in _users(ctx) if e)})

    if (method, path) == ("GET", "/deals"):
        rows = deals.list_deals(ctx.pk, 300)
        if q("stage"):
            rows = [d for d in rows if d["stage"] == q("stage")]
        rows.sort(key=lambda d: -int(d.get("updatedAt", 0)))
        return _r(200, {"deals": [{k: v for k, v in d.items() if k not in ("PK", "SK", "GSI1PK", "GSI1SK")} for d in rows], "counts": deals.stage_counts(deals.list_deals(ctx.pk, 500))})

    m = re.fullmatch(r"/deals/([A-Za-z0-9_-]{1,60})/(stage|assign)", path)
    if m and method == "POST":
        did, what = m.groups()
        try:
            if what == "stage":
                d = deals.set_stage(ctx.pk, did, str(body.get("stage", "")))
                tasks.resolve_for_deal(ctx.pk, did, ("follow_up", "reply_overdue", "cold_lead")) if d["stage"] in deals.TERMINAL else None
            else:
                who = str(body.get("assignee", ""))
                if who and who not in _users(ctx):
                    return _r(400, {"error": "assignee must be a member of this business"})
                if not db.update(deals.key(ctx.pk, did), sets={"assignee": who}):
                    return _r(404, {"error": "deal not found"})
        except LookupError:
            return _r(404, {"error": "deal not found"})
        db.audit(ctx.pk, ctx.user_id, f"deal.{what}", {"dealId": did})
        return _r(200, {"ok": True})

    if (method, path) == ("GET", "/policy"):
        return _r(200, policy.get(ctx.pk))
    if (method, path) == ("PUT", "/policy"):
        ctx.require_admin()
        saved = policy.save(ctx.pk, body)
        db.audit(ctx.pk, ctx.user_id, "policy.changed", {"modes": saved["modes"], "paused": saved["paused"]})
        return _r(200, saved)

    if (method, path) == ("GET", "/inbox"):
        convs = db.query_prefix(ctx.pk, "CONV#", limit=100)
        msgs = db.query_prefix(ctx.pk, "MSG#", limit=100, newest_first=True)
        rows = inbox.build(convs, msgs, deals.list_deals(ctx.pk, 300), db.query_prefix(ctx.pk, "LEAD#", limit=100))
        return _r(200, {"items": inbox.filter_rows(rows, q("channel"), q("status"), q("assignee"))[:150]})

    if (method, path) == ("GET", "/impact"):
        try:
            days = int(q("days", "30"))
        except ValueError:
            return _r(400, {"error": "days must be a number"})
        return _r(200, impact_for(ctx, max(1, min(days, 90))))

    if (method, path) == ("POST", "/ask"):
        question = str(body.get("question", ""))[:300]
        if not question.strip():
            return _r(400, {"error": "ask a question"})
        data = {"events": events.since(ctx.pk, now - 90 * 86400), "deals": deals.list_deals(ctx.pk, 500), "policy": policy.get(ctx.pk),
                "msgs": db.query_prefix(ctx.pk, "MSG#", limit=200, newest_first=True), "invoices": db.query_prefix(ctx.pk, "XINV#", limit=300)}
        return _r(200, ask.answer(question, data, now))
    return None
