"""Invoice and payment follow-up. Xero stays the record; this only coordinates the chasing.

An overdue invoice gets ONE reminder task per severity step (gentle 1-7 days, firm 8-30, final 31+). When Xero shows it paid (or an
outstanding snapshot no longer lists it) every open reminder for it closes by itself.
"""
import re
import time
from datetime import date, datetime, timezone

from src.common import db, events, policy
from src.pipeline import followups, tasks

BUCKETS = (("gentle", 1, 7), ("firm", 8, 30), ("final", 31, 10_000))
CLOSED = ("PAID", "VOIDED", "DELETED")


def bucket(days: int) -> str | None:
    return next((n for n, lo, hi in BUCKETS if lo <= days <= hi), None)


def money(amount: float, currency: str) -> str:
    return f"${amount:,.2f}" if currency == "NZD" else f"{amount:,.2f} {currency}"


def draft(inv: dict, business: str, days: int, b: str) -> str:
    first = (re.sub(r"[^A-Za-z' -]", "", inv.get("contactName", "")).strip().split(" ") or ["there"])[0][:30] or "there"
    ref = f"invoice {inv['number']} for {money(inv['amountDue'], inv.get('currency', 'NZD'))}"
    if b == "gentle":
        body = f"A friendly reminder that {ref}, due on {inv['dueDate']}, still shows as unpaid. If you've already paid, thank you and please ignore this note. Otherwise, could you arrange payment when you can?"
    elif b == "firm":
        body = f"Our records show {ref} is now {days} days overdue. Could you please arrange payment, or let us know if there is anything we need to sort out on our side?"
    else:
        body = f"{ref.capitalize()} is now {days} days overdue and we haven't been able to reach you about it. Please get in touch so we can resolve this promptly."
    return f"Hi {first},\n\n{body}\n\nKind regards,\nthe team at {business}"


def process(pk: str, inv: dict, now: int | None = None) -> None:
    now = int(now or time.time())
    iid, deal_id = inv["invoiceId"], f"inv-{inv['invoiceId']}"
    today = datetime.fromtimestamp(now, timezone.utc).date()
    paid = inv["status"] in CLOSED or inv["amountDue"] <= 0
    key = {"PK": pk, "SK": f"XINV#{iid}"}
    if paid:
        closed = tasks.resolve_for_deal(pk, deal_id, ("invoice_reminder",))
        if inv["status"] == "PAID" and db.table().get_item(Key=key).get("Item", {}).get("status") != "PAID":
            events.record(pk, "invoice_paid", deal_id, at=now, afterReminder=bool(closed))
        db.table().put_item(Item=db.to_ddb({**key, "status": inv["status"], "number": inv["number"], "contactName": inv["contactName"], "amountDue": 0, "updatedAt": now}))
        return
    due = date.fromisoformat(inv["dueDate"]) if inv.get("dueDate") else None
    days = (today - due).days if due else 0
    b = bucket(days)
    db.table().put_item(Item=db.to_ddb({**key, "status": inv["status"], "number": inv["number"], "contactName": inv["contactName"], "contactEmail": inv.get("contactEmail", ""),
                                        "amountDue": inv["amountDue"], "currency": inv.get("currency", "NZD"), "dueDate": inv.get("dueDate", ""),
                                        "daysOverdue": max(days, 0), "bucket": b or "", "updatedAt": now}))
    pol = policy.get(pk)
    if not b or pol["paused"]["invoice_reminder"]:
        return
    meta = db.table().get_item(Key={"PK": pk, "SK": "META"}).get("Item") or {}
    mode = "approve" if b == "final" else pol["modes"]["invoice_reminder"]  # the last step is always a person's decision
    for old in tasks.list_tasks(pk, tasks.OPEN):  # a worse bucket supersedes a milder, unsent one
        if old.get("dealId") == deal_id and old["type"] == "invoice_reminder" and old.get("bucket") != b:
            tasks.set_status(pk, old["taskId"], "dismissed", expect=old["status"], resolvedBy="superseded")
    created = tasks.create(pk, f"inv-{iid}-{b}", "invoice_reminder", f"{inv['contactName'] or 'Customer'}: invoice {inv['number']} is {days} days overdue",
                           status="open" if mode == "assist" else "needs_approval", priority="urgent" if b == "final" else "high" if b == "firm" else "normal",
                           deal_id=deal_id, draft=draft(inv, meta.get("name", "the business"), days, b), to=inv.get("contactEmail", ""),
                           subject=f"Payment reminder: invoice {inv['number']}", channel="email", action="invoice_reminder",
                           detail=f"{money(inv['amountDue'], inv.get('currency', 'NZD'))} due {inv['dueDate']} ({b} reminder)",
                           bucket=b, invoiceId=iid, invoiceNumber=inv["number"])
    if not created:
        return
    events.record(pk, "invoice_reminder_drafted", deal_id, at=now, bucket=b, mode=mode)
    if mode == "automate" and inv.get("contactEmail") and policy.in_send_window(pol, meta.get("timezone", "Pacific/Auckland"), now):
        try:
            followups.deliver(pk, created["taskId"], created["draft"], actor="automation", now=now)
        except Exception:  # noqa: BLE001 - stays in the queue; deliver() recorded why
            pass


def snapshot(pk: str, outstanding_ids: list[str]) -> int:
    """Close reminders for invoices that are no longer outstanding in Xero (paid or voided with no event received)."""
    live, n = set(outstanding_ids), 0
    for t in tasks.list_tasks(pk, tasks.OPEN):
        if t["type"] == "invoice_reminder" and t.get("invoiceId") and t["invoiceId"] not in live:
            n += tasks.set_status(pk, t["taskId"], "done", expect=t["status"], resolvedBy="no longer outstanding")
    return n
