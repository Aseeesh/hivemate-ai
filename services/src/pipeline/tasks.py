"""Work queue items. Deterministic ids make creation idempotent: running the same sweep twice never makes two tasks."""
import time

from src.common import db

OPEN = ("open", "needs_approval", "failed", "snoozed")
TYPES = ("follow_up", "reply_overdue", "cold_lead", "invoice_reminder", "document_review", "connection_attention", "handoff")
PRIORITY = {"urgent": 0, "high": 1, "normal": 2}


def key(pk: str, task_id: str) -> dict:
    return {"PK": pk, "SK": f"TASK#{task_id}"}


def create(pk: str, task_id: str, type_: str, title: str, *, status: str = "open", priority: str = "normal", detail: str = "", draft: str = "",
           deal_id: str = "", to: str = "", subject: str = "", channel: str = "", action: str = "", due_at: int | None = None, **extra) -> dict | None:
    """Returns the task, or None if it already existed."""
    assert type_ in TYPES and priority in PRIORITY
    now = int(time.time())
    item = {**key(pk, task_id), "taskId": task_id, "type": type_, "title": title[:200], "status": status, "priority": priority, "detail": detail[:600],
            "draft": draft[:4000], "dealId": deal_id, "to": to, "subject": subject[:200], "channel": channel, "action": action,
            "dueAt": int(due_at or now), "createdAt": now, **extra}
    return item if db.create(item) else None


def get(pk: str, task_id: str) -> dict | None:
    it = db.table().get_item(Key=key(pk, task_id)).get("Item")
    return db.clean(it) if it else None


def list_tasks(pk: str, statuses: tuple | None = None, limit: int = 300) -> list[dict]:
    items = db.query_prefix(pk, "TASK#", limit=limit)
    if statuses:
        items = [i for i in items if i["status"] in statuses]
    return sorted(items, key=lambda t: (PRIORITY.get(t.get("priority", "normal"), 2), t.get("dueAt", 0)))


def set_status(pk: str, task_id: str, status: str, expect: str | None = None, **fields) -> bool:
    return db.update(key(pk, task_id), sets={"status": status, "updatedAt": int(time.time()), **fields}, if_eq={"status": expect} if expect else None)


def resolve_for_deal(pk: str, deal_id: str, types: tuple[str, ...], status: str = "done") -> int:
    """Close open tasks of these types for a deal (e.g. the customer replied, so the follow-up is moot)."""
    n = 0
    for t in list_tasks(pk, OPEN):
        if t.get("dealId") == deal_id and t["type"] in types and set_status(pk, t["taskId"], status, expect=t["status"], resolvedBy="system"):
            n += 1
    return n
