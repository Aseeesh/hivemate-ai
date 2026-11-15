"""Customer 360: one view of a person assembled from records Hivemate already holds. Each item says which system supplied it."""
import re


def key_for(deal: dict) -> str:
    if deal.get("email"):
        return "e:" + deal["email"].strip().lower()
    digits = re.sub(r"\D", "", deal.get("phone", ""))
    if len(digits) >= 6:
        return "p:" + digits[-9:]
    return "d:" + deal["dealId"]


def group(deal_rows: list[dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for d in deal_rows:
        out.setdefault(key_for(d), []).append(d)
    return out


def summary_row(key: str, ds: list[dict]) -> dict:
    ds = sorted(ds, key=lambda d: -int(d.get("updatedAt", 0)))
    first = ds[0]
    return {"key": key, "name": next((d["name"] for d in ds if d.get("name")), "Unknown"), "email": next((d["email"] for d in ds if d.get("email")), ""),
            "phone": next((d["phone"] for d in ds if d.get("phone")), ""), "stage": first["stage"], "awaiting": first.get("awaiting", ""),
            "deals": len(ds), "lastAt": max(int(d.get("updatedAt", 0)) for d in ds), "channels": sorted({d.get("channel", "") for d in ds if d.get("channel")})}


def list_customers(deal_rows: list[dict], query: str = "") -> list[dict]:
    rows = [summary_row(k, ds) for k, ds in group(deal_rows).items()]
    if query:
        q = query.lower()
        rows = [r for r in rows if q in (r["name"] + " " + r["email"] + " " + r["phone"]).lower()]
    return sorted(rows, key=lambda r: -r["lastAt"])


def detail(key: str, deal_rows: list[dict], convs: list[dict], msgs: list[dict], leads: list[dict], invoices: list[dict], task_rows: list[dict]) -> dict | None:
    ds = group(deal_rows).get(key)
    if not ds:
        return None
    row = summary_row(key, ds)
    ids = {d["dealId"] for d in ds}
    email = row["email"].lower()
    lead_summary = {l["convId"]: l.get("summary", "") for l in leads if l.get("convId")}
    conv_items = [{"source": c["channel"], "id": c["convId"], "status": c["status"], "turns": c.get("turns", 0), "lastAt": int(c.get("lastAt", 0)),
                   "summary": lead_summary.get(c["convId"], "")} for c in convs if c["convId"] in ids]
    mail_items = [{"source": m.get("source") or "email", "id": m["SK"].split("#", 1)[1], "subject": m.get("subject", ""), "status": m["status"], "category": m.get("category", ""),
                   "at": int(m.get("createdAt", 0))} for m in msgs if email and m["from"].strip().lower() == email]
    inv_items = [{"source": "xero", "id": i["SK"].split("#", 1)[1], "number": i.get("number", ""), "amountDue": i.get("amountDue", 0), "dueDate": i.get("dueDate", ""),
                  "status": i.get("status", ""), "daysOverdue": i.get("daysOverdue", 0)} for i in invoices if email and (i.get("contactEmail") or "").lower() == email]
    follow = [{"id": t["taskId"], "type": t["type"], "title": t["title"], "status": t["status"], "priority": t.get("priority", "normal")}
              for t in task_rows if t.get("dealId") in ids and t["status"] in ("open", "needs_approval", "failed")]
    summaries = [c["summary"] for c in sorted(conv_items, key=lambda c: -c["lastAt"]) if c["summary"]]
    return {**row, "deals": [{k: v for k, v in d.items() if k not in ("PK", "SK", "GSI1PK", "GSI1SK")} for d in ds], "conversations": conv_items, "emails": mail_items,
            "invoices": inv_items, "outstandingFollowUps": follow,
            "summary": summaries[0] if summaries else "", "summarySource": "AI summary of the most recent chat" if summaries else "",
            "identity": "Matched on email address" if key.startswith("e:") else "Matched on phone number" if key.startswith("p:") else "Single enquiry"}
