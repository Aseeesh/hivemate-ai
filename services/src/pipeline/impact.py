"""Business impact, computed from recorded events only. Nothing here is estimated by a model.

Two clearly separate groups:
  measured   counts and durations taken straight from event timestamps
  estimated  time saved = completed tasks x the owner's own minutes-per-task assumption (editable in Automations)
Cost per task is NOT reported: per-task AWS and third-party cost is not metered yet, and a made-up number would be worse than none.
"""
import statistics
import time

from src.pipeline import deals as deals_mod

DAY = 86400
# event kind -> minutes key: what a person would have spent doing this by hand
SAVED_BY = {"follow_up_drafted": None, "invoice_reminder_drafted": "invoice_reminder", "email_drafted": "email_drafted", "doc_extracted": "document_extracted"}


def compute(evs: list[dict], deal_rows: list[dict], pol: dict, now: float | None = None, days: int = 30) -> dict:
    now = now or time.time()
    start = now - days * DAY
    ev = [e for e in evs if e["at"] / 1000 >= start]
    by = {}
    for e in ev:
        by.setdefault(e["kind"], []).append(e)
    n = lambda k: len(by.get(k, []))

    secs = [e["meta"].get("seconds", 0) for e in by.get("first_response", [])]
    due, actioned = n("follow_up_due"), n("follow_up_sent") + n("follow_up_manual")
    recovered, cold = n("lead_recovered"), n("lead_cold")
    ok = n("follow_up_sent") + n("invoice_reminder_sent")
    failed = n("send_failed")
    approvals, manual = n("approval_completed"), n("follow_up_manual")

    mins = pol["minutes"]
    basis = {}
    for e in by.get("follow_up_drafted", []):
        a = (e["meta"] or {}).get("action", "follow_up")
        basis[a] = basis.get(a, 0) + 1
    for kind, key in (("invoice_reminder_drafted", "invoice_reminder"), ("email_drafted", "email_drafted"), ("doc_extracted", "document_extracted")):
        if n(kind):
            basis[key] = basis.get(key, 0) + n(kind)
    breakdown = [{"type": k, "count": c, "minutesEach": mins.get(k, 0), "minutes": round(c * mins.get(k, 0), 1)} for k, c in sorted(basis.items())]
    minutes = sum(b["minutes"] for b in breakdown)

    daily = {}
    for e in ev:
        if e["kind"] in ("follow_up_drafted", "invoice_reminder_drafted", "email_drafted", "follow_up_sent", "invoice_reminder_sent", "doc_extracted"):
            d = time.strftime("%Y-%m-%d", time.gmtime(e["at"] / 1000))
            daily[d] = daily.get(d, 0) + 1
    series = [{"day": time.strftime("%Y-%m-%d", time.gmtime(now - i * DAY)), "tasks": 0} for i in range(min(days, 30) - 1, -1, -1)]
    for s in series:
        s["tasks"] = daily.get(s["day"], 0)

    return {
        "periodDays": days,
        "measured": {
            "enquiries": n("enquiry_received"),
            "medianResponseSeconds": int(statistics.median(secs)) if secs else None,
            "averageResponseSeconds": int(sum(secs) / len(secs)) if secs else None,
            "respondedWithinHourPct": round(100 * sum(1 for s in secs if s <= 3600) / len(secs)) if secs else None,
            "followUpsDue": due, "followUpsActioned": actioned,
            "followUpRatePct": round(100 * min(actioned, due) / due) if due else None,
            "leadsRecovered": recovered, "leadsWentCold": cold,
            "recoveryRatePct": round(100 * recovered / (recovered + cold)) if recovered + cold else None,
            "executionsOk": ok, "executionsFailed": failed,
            "executionSuccessPct": round(100 * ok / (ok + failed)) if ok + failed else None,
            "approvalsCompleted": approvals, "manualInterventions": approvals + manual,
            "invoiceRemindersSent": n("invoice_reminder_sent"), "invoicesPaidAfterReminder": sum(1 for e in by.get("invoice_paid", []) if e["meta"].get("afterReminder")),
            "repliesOverdue": n("reply_overdue"),
        },
        "estimated": {"minutesSaved": round(minutes, 1), "hoursSaved": round(minutes / 60, 1), "basis": breakdown,
                      "note": "Estimate: drafts and tasks Hivemate prepared for you x the minutes-per-task you set under Automations. It is not a financial figure."},
        "notMeasured": ["costPerTask"],
        "daily": series,
        "pipeline": deals_mod.stage_counts(deal_rows),
    }
