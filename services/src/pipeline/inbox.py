"""One inbox across email, website chat and WhatsApp, built from existing records (nothing is copied or migrated)."""
from src.pipeline import deals as deals_mod


def build(convs: list[dict], msgs: list[dict], deal_rows: list[dict], leads: list[dict]) -> list[dict]:
    by_deal = {d["dealId"]: d for d in deal_rows}
    summ = {l["convId"]: l.get("summary", "") for l in leads if l.get("convId")}
    rows = []
    for c in convs:
        d = by_deal.get(c["convId"], {})
        name = (c.get("collected") or {}).get("name") or "Website visitor"
        rows.append({"kind": "conversation", "id": c["convId"], "channel": c["channel"], "title": name, "preview": summ.get(c["convId"]) or (c.get("collected") or {}).get("need", ""),
                     "status": c["status"], "category": "needs a person" if c["status"] == "HANDOFF" else "", "awaiting": d.get("awaiting", ""), "stage": d.get("stage", ""),
                     "assignee": d.get("assignee", ""), "lastAt": int(c.get("lastAt", 0)), "dealId": c["convId"] if d else ""})
    for m in msgs:
        did = deals_mod.email_deal_id(m["from"])
        d = by_deal.get(did, {})
        rows.append({"kind": "email", "id": m["SK"].split("#", 1)[1], "channel": "email", "title": m.get("subject") or "(no subject)", "preview": m["from"],
                     "status": m["status"], "category": m.get("category", ""), "awaiting": d.get("awaiting", ""), "stage": d.get("stage", ""),
                     "assignee": d.get("assignee", ""), "lastAt": int(m.get("createdAt", 0)), "dealId": did if d else ""})
    for r in rows:
        r["unanswered"] = r["awaiting"] == "business" or r["status"] in ("PENDING_APPROVAL", "HANDOFF")
    return sorted(rows, key=lambda r: -r["lastAt"])


def filter_rows(rows: list[dict], channel: str = "", status: str = "", assignee: str = "") -> list[dict]:
    out = rows
    if channel:
        out = [r for r in out if r["channel"] == channel]
    if status == "unanswered":
        out = [r for r in out if r["unanswered"]]
    elif status:
        out = [r for r in out if r["status"].lower() == status.lower()]
    if assignee:
        out = [r for r in out if r["assignee"] == assignee]
    return out
