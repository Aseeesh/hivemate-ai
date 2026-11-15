"""Ask-your-business: a small set of questions answered by fixed queries over real records.
Every answer says how it was calculated and lists the records it used. A question outside the set gets the list of supported ones,
not a guess: an owner must be able to trust the number."""
import re
import time

from src.pipeline import impact

SUPPORTED = ["How many enquiries did we get this month?", "Which customers haven't received a reply?", "How many invoices are overdue?",
             "What are the main customer complaints?", "How many hours did automation save?", "What is our average response time?",
             "How many leads did we recover?", "Which automation saved the most time?"]


def _period(q: str) -> tuple[int, str]:
    if re.search(r"\btoday\b", q):
        return 1, "today"
    if re.search(r"this week|last 7|past week|last week", q):
        return 7, "the last 7 days"
    return 30, "the last 30 days"


def _fmt_secs(s: int | None) -> str:
    if s is None:
        return "n/a"
    return f"{s // 60} min" if s < 3600 else f"{s / 3600:.1f} h"


def answer(question: str, data: dict, now: float | None = None) -> dict:
    """data: events, deals, msgs, invoices (XINV items), policy."""
    now = now or time.time()
    q = question.lower().strip()
    days, label = _period(q)
    m = impact.compute(data["events"], data["deals"], data["policy"], now, days)

    if re.search(r"how many (new )?enquir|how many leads|enquiries (did|have)", q) and "recover" not in q:
        n = m["measured"]["enquiries"]
        src = [{"type": "deal", "id": d["dealId"], "label": d.get("name") or d.get("email") or d["dealId"]} for d in data["deals"] if d["createdAt"] >= now - days * 86400][:50]
        return {"supported": True, "answer": f"{n} enquiries in {label}.", "calculation": f"Count of enquiry_received events in {label}.", "sources": src}
    if re.search(r"(haven'?t|not|without|no) (received )?(a )?repl|unanswered|waiting for (a )?repl|still waiting", q):
        rows = [d for d in data["deals"] if d.get("awaiting") == "business" and d["stage"] not in ("won", "lost")]
        names = ", ".join((d.get("name") or d.get("email") or "unknown") for d in rows[:10]) or "nobody"
        return {"supported": True, "answer": f"{len(rows)} customers are waiting for a reply: {names}.", "calculation": "Deals where the customer wrote last and no reply has been recorded.",
                "sources": [{"type": "deal", "id": d["dealId"], "label": d.get("name") or d.get("email") or d["dealId"]} for d in rows[:50]]}
    if re.search(r"overdue invoice|invoices? (are|is) overdue|unpaid invoice|outstanding invoice", q):
        rows = [i for i in data["invoices"] if i.get("amountDue", 0) > 0 and i.get("daysOverdue", 0) > 0]
        total = sum(i["amountDue"] for i in rows)
        return {"supported": True, "answer": f"{len(rows)} overdue invoices totalling ${total:,.2f}.", "calculation": "Sum of AmountDue across Xero invoices past their due date (as last synced).",
                "sources": [{"type": "invoice", "id": i["SK"].split("#", 1)[1], "label": f"{i.get('number', '')} {i.get('contactName', '')}".strip()} for i in rows[:50]]}
    if re.search(r"complain", q):
        rows = [x for x in data["msgs"] if x.get("category") in ("complaint", "refund")]
        subj = "; ".join((x.get("subject") or "(no subject)")[:60] for x in rows[:5]) or "none"
        return {"supported": True, "answer": f"{len(rows)} emails were classed as complaints or refunds. Subjects: {subj}.", "calculation": "Count of emails whose AI category is complaint or refund.",
                "sources": [{"type": "email", "id": x["SK"].split("#", 1)[1], "label": (x.get("subject") or "")[:80]} for x in rows[:50]]}
    if re.search(r"which automation|most time", q):
        b = sorted(m["estimated"]["basis"], key=lambda x: -x["minutes"])
        top = b[0] if b else None
        return {"supported": True, "answer": f"{top['type'].replace('_', ' ')} saved the most estimated time: {top['minutes']} minutes." if top else "No automated tasks yet.",
                "calculation": "Tasks Hivemate prepared x your minutes-per-task assumption, per automation (an estimate).", "sources": [{"type": "estimate", "id": x["type"], "label": f"{x['count']} x {x['minutesEach']} min"} for x in b]}
    if re.search(r"\bsav(e|ed|ing)\b|time saved|hours saved", q):
        return {"supported": True, "answer": f"About {m['estimated']['hoursSaved']} hours saved in {label} (estimate).", "calculation": m["estimated"]["note"],
                "sources": [{"type": "estimate", "id": x["type"], "label": f"{x['count']} x {x['minutesEach']} min"} for x in m["estimated"]["basis"]]}
    if re.search(r"response time|respond|reply time", q):
        return {"supported": True, "answer": f"Average first response: {_fmt_secs(m['measured']['averageResponseSeconds'])}; median {_fmt_secs(m['measured']['medianResponseSeconds'])} in {label}.",
                "calculation": "Seconds between an enquiry arriving and the first reply, from event timestamps.", "sources": []}
    if re.search(r"recover", q):
        return {"supported": True, "answer": f"{m['measured']['leadsRecovered']} leads recovered in {label}.", "calculation": "Leads that were followed up or gone cold and then replied.",
                "sources": [{"type": "event", "id": e["SK"], "label": e.get("dealId", "")} for e in data["events"] if e["kind"] == "lead_recovered" and e["at"] / 1000 >= now - days * 86400][:50]}
    return {"supported": False, "answer": "I can only answer questions I can calculate from your records. Try one of these.", "calculation": "", "sources": [], "examples": SUPPORTED}
