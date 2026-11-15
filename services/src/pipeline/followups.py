"""Follow-up sweeper and delivery. Runs on a schedule; safe to run twice at once.

Rules (all thresholds come from the tenant policy):
- Customer wrote and nobody answered within noReplyHours  -> "reply overdue" task for a person (never auto-answered here).
- We answered and the customer went quiet                 -> follow-up draft, handled per mode: assist / approve / automate.
- maxFollowUps reached                                    -> lead goes cold and the owner gets one escalation task.
A deal is "claimed" with a compare-and-set before anything is created, so two sweepers cannot act on the same deal.
"""
import re
import time

from botocore.exceptions import ClientError

from src.common import db, events, mailer, policy
from src.pipeline import deals, tasks

CLAIM_SECONDS = 1800
MAX_REMINDERS = 3
BATCH = 100


class Conflict(Exception):
    pass


def _first(name: str) -> str:
    w = re.sub(r"[^A-Za-z' -]", "", name or "").strip().split(" ")[0]
    return w[:30] or "there"


def draft_follow_up(deal: dict, business: str, n: int, quote: bool) -> str:
    """Deterministic wording: a follow-up must never invent prices, dates or promises, so no model is involved."""
    topic = f" about {deal['need']}" if deal.get("need") else ""
    if quote:
        body = f"I wanted to check that you received our quote{topic}. Happy to answer any questions or adjust it if that helps."
    elif n == 0:
        body = f"Just checking in on your enquiry{topic}. Let us know if you'd like to go ahead or if there's anything we can clear up."
    else:
        body = f"A quick final follow-up on your enquiry{topic}. If now isn't the right time, no problem at all, just reply and we'll pick it up whenever suits you."
    return f"Hi {_first(deal.get('name', ''))},\n\n{body}\n\nKind regards,\nthe team at {business}"


def _meta(pk: str) -> tuple[str, str]:
    item = db.table().get_item(Key={"PK": pk, "SK": "META"}).get("Item") or {}
    return item.get("name", "the business"), item.get("timezone", "Pacific/Auckland")


def sweep(now: int | None = None) -> dict:
    now = int(now or time.time())
    out = {"checked": 0, "tasks": 0, "sent": 0, "cold": 0}
    for s in range(deals.SHARDS):
        for row in db.query_index(f"DUE#{s}", f"{now:013d}~", limit=BATCH):
            out["checked"] += 1
            try:
                r = process_due(row["PK"], row["dealId"], now)
            except Exception as exc:  # one bad deal must not stop the others
                print({"level": "ERROR", "deal": row.get("dealId"), "error": repr(exc)[:200]})
                continue
            for k in ("tasks", "sent", "cold"):
                out[k] += r.get(k, 0)
    return out


def process_due(pk: str, deal_id: str, now: int) -> dict:
    res = {"tasks": 0, "sent": 0, "cold": 0}
    deal = deals.get(pk, deal_id)
    if not deal or deal["stage"] in deals.TERMINAL or not deal.get("nextDueAt") or deal["nextDueAt"] > now:
        return res
    pol = policy.get(pk)
    if pol["paused"]["follow_up"]:
        return res
    # Claim: only one worker wins this compare-and-set; it also pushes the deal out so a crash retries later, not instantly.
    if not db.update(deals.key(pk, deal_id), sets={"nextDueAt": now + CLAIM_SECONDS, "GSI1SK": f"{now + CLAIM_SECONDS:013d}#{pk}#{deal_id}"},
                     if_eq={"nextDueAt": deal["nextDueAt"]}):
        return res
    business, tz = _meta(pk)
    cad = pol["cadence"]
    events.record(pk, "follow_up_due", deal_id, at=now, awaiting=deal["awaiting"])

    if deal["awaiting"] == "business":
        created = tasks.create(pk, f"rep-{deal_id}-{deal['lastInboundAt']}-{deal.get('remindCount', 0)}", "reply_overdue",
                               f"{deal.get('name') or 'A customer'} is still waiting for a reply",
                               priority="urgent", deal_id=deal_id, channel=deal.get("channel", ""), to=deal.get("email", ""),
                               detail=f"They wrote {_ago(now - int(deal['lastInboundAt']))} ago and nobody has answered. {deal.get('need', '')}".strip(),
                               subject=deal.get("subject", ""))
        res["tasks"] += bool(created)
        if created:
            events.record(pk, "reply_overdue", deal_id, at=now)
        deal["remindCount"] = deal.get("remindCount", 0) + 1
        deal["nextDueAt"] = now + cad["noReplyHours"] * 3600 if deal["remindCount"] < MAX_REMINDERS else None
        if deal["nextDueAt"] is None:
            deal.pop("nextDueAt")
        deals.save(pk, deal)
        return res

    n = int(deal.get("followUpCount", 0))
    if n >= cad["maxFollowUps"]:
        deal["stage"], deal["coldAt"] = "cold", now
        deal.pop("nextDueAt", None)
        deals.save(pk, deal)
        tasks.create(pk, f"cold-{deal_id}", "cold_lead", f"{deal.get('name') or 'A lead'} has gone quiet",
                     priority="normal", deal_id=deal_id, channel=deal.get("channel", ""),
                     detail=f"{n} follow-up(s) sent with no reply. Call them, or mark the lead lost.", to=deal.get("email", ""))
        events.record(pk, "lead_cold", deal_id, at=now)
        res["cold"], res["tasks"] = 1, 1
        return res

    quote = deal["stage"] == "quote_sent"
    action = "quote_follow_up" if quote else "follow_up"
    mode = pol["modes"][action]
    draft = draft_follow_up(deal, business, n, quote)
    subject = ("Following up on your quote" if quote else "Following up on your enquiry")
    status = "open" if mode == "assist" else "needs_approval"
    created = tasks.create(pk, f"fu-{deal_id}-{n + 1}", "follow_up", f"Follow up with {deal.get('name') or 'this customer'}",
                           status=status, priority="high" if quote else "normal", deal_id=deal_id, draft=draft, subject=subject,
                           to=deal.get("email", ""), channel=deal.get("channel", ""), action=action,
                           detail=("Quote sent, no reply yet." if quote else "No reply since our last message.") + (f" {deal['need']}" if deal.get("need") else ""))
    deal["followUpCount"] = n + 1
    if deal["stage"] in ("new", "responded"):
        deal["stage"] = "followed_up"
    deal["nextDueAt"] = now + cad["followUpAfterHours"] * 3600
    deals.save(pk, deal)
    if created:
        res["tasks"] += 1
        events.record(pk, "follow_up_drafted", deal_id, at=now, n=n + 1, mode=mode, action=action)
        if mode == "automate" and deal.get("email") and policy.in_send_window(pol, tz, now):
            try:
                deliver(pk, created["taskId"], draft, actor="automation", now=now)
                res["sent"] = 1
            except (Conflict, ValueError, ClientError):
                pass  # stays in the queue as needs_approval, with the reason recorded by deliver()
    return res


def _ago(seconds: int) -> str:
    h = max(1, seconds // 3600)
    return f"{h} hour{'s' if h != 1 else ''}" if h < 48 else f"{h // 24} days"


def deliver(pk: str, task_id: str, text: str, actor: str, now: int | None = None) -> dict:
    """Send a follow-up or invoice reminder by email, exactly once. Raises Conflict if someone else already handled it."""
    now = int(now or time.time())
    task = tasks.get(pk, task_id)
    if not task:
        raise LookupError("task not found")
    if task["status"] not in ("open", "needs_approval", "failed"):
        raise Conflict(f"task is {task['status']}")
    text = text.strip()
    if not text:
        raise ValueError("the message is empty")
    if not task.get("to") or not mailer.valid_address(task["to"]):
        raise ValueError("no email address for this customer. Contact them another way, then mark it done")
    if not tasks.set_status(pk, task_id, "sending", expect=task["status"]):
        raise Conflict("someone else is handling this")  # compare-and-set: a double click or a second sweeper loses here
    business, _ = _meta(pk)
    plug = db.table().get_item(Key={"PK": pk, "SK": "PLUGIN#email-automation"}).get("Item") or {}
    try:
        from src.connectors import runtime  # late import: connectors import this module's siblings
        via = runtime.try_send_mail(pk, task["to"], task.get("subject") or "Following up", text, idem_key=f"task-{task_id}")
        if via is None:
            if mailer.enabled():
                mailer.send_reply(business=business, to=task["to"], subject=task.get("subject") or "Following up", body=text,
                                  reply_to=(plug.get("config") or {}).get("sendFrom", ""))
                via = "ses"
            else:
                via = "simulated"
    except (ClientError, ValueError, RuntimeError) as exc:
        tasks.set_status(pk, task_id, "failed", error=str(exc)[:300])
        events.record(pk, "send_failed", task.get("dealId", ""), at=now, task=task_id, error=str(exc)[:120])
        db.audit(pk, actor, "task.send_failed", {"taskId": task_id, "error": str(exc)[:200]})
        raise
    tasks.set_status(pk, task_id, "done", sentAt=now, sentBy=actor, sentVia=via, finalText=text[:4000], error="")
    kind = {"follow_up": "follow_up_sent", "invoice_reminder": "invoice_reminder_sent"}.get(task["type"], "task_completed")
    events.record(pk, kind, task.get("dealId", ""), at=now, via=via, actor=actor, task=task_id)
    if actor != "automation":
        events.record(pk, "approval_completed", task.get("dealId", ""), at=now, task=task_id)
    if task["type"] == "follow_up" and task.get("dealId"):
        # Sending a follow-up is not a new first response and must not restart follow-up counting, only note the time.
        db.update(deals.key(pk, task["dealId"]), sets={"lastOutboundAt": now})
    db.audit(pk, actor, "task.sent", {"taskId": task_id, "via": via})
    if task["type"] == "invoice_reminder" and task.get("invoiceId"):
        _note_in_xero(pk, task, now)
    return {"status": "done", "via": via}


def _note_in_xero(pk: str, task: dict, now: int) -> None:
    """Write back: leave a history note on the Xero invoice so the accounts team can see it was chased. Best effort."""
    try:
        from src.connectors import runtime
        runtime.execute(pk, "xero", "add_history_note", {"invoiceId": task["invoiceId"], "text": f"Payment reminder emailed via Hivemate ({task.get('bucket', '')})."},
                        idem_key=f"note-{task['taskId']}", now=now)
    except Exception as exc:  # noqa: BLE001
        db.audit(pk, "automation", "xero.note_failed", {"taskId": task["taskId"], "error": str(exc)[:160]})
