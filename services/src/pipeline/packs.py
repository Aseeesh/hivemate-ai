"""Automation packs: ready-made bundles over the same engine. A pack is a preset (plugins + policy), never separate code.
Readiness is derived from the real state, so the page can say exactly what is still missing."""
import time

from src.common import db, plugins, policy

PACKS = [
    {"id": "smart-inbox", "name": "Smart Inbox", "blurb": "Categorise, summarise and draft replies to enquiries. Nothing is sent without your approval by default.",
     "plugins": ["email-automation"], "unpause": [], "needs": []},
    {"id": "lead-recovery", "name": "Lead Recovery", "blurb": "Spot unanswered enquiries and quiet leads, draft follow-ups and escalate leads that go cold.",
     "plugins": [], "unpause": ["follow_up"], "needs": ["inbound"]},
    {"id": "invoice-assistant", "name": "Invoice Assistant", "blurb": "Watch Xero for overdue invoices and prepare polite reminders by severity.",
     "plugins": [], "unpause": ["invoice_reminder"], "needs": ["xero"]},
    {"id": "customer-support", "name": "Customer Support", "blurb": "Answer customer questions from your own documents on your website and WhatsApp.",
     "plugins": ["conversation-agent"], "unpause": [], "needs": []},
    {"id": "document-processing", "name": "Document Processing", "blurb": "Read supplier invoices and receipts, flag GST and duplicate problems, send them for approval.",
     "plugins": [], "unpause": [], "needs": []},
    {"id": "smart-scheduling", "name": "Smart Scheduling", "blurb": "Manage availability and appointments. Not built yet: the booking plugin is only a placeholder.",
     "plugins": [], "unpause": [], "needs": [], "planned": True},
]


def _installed(pk: str) -> set[str]:
    return {i["SK"].split("#", 1)[1] for i in db.query_prefix(pk, "PLUGIN#")}


def status(pk: str) -> list[dict]:
    inst, pol = _installed(pk), policy.get(pk)
    xero = db.table().get_item(Key={"PK": pk, "SK": "CONN#xero"}).get("Item")
    inbound = bool(inst & {"email-automation", "conversation-agent"}) or bool(db.table().get_item(Key={"PK": pk, "SK": "CONN#microsoft365"}).get("Item"))
    out = []
    for p in PACKS:
        missing = []
        if "xero" in p["needs"] and not xero:
            missing.append("Connect Xero under Integrations")
        if "inbound" in p["needs"] and not inbound:
            missing.append("Turn on the customer assistant or Smart Inbox first")
        enabled = (not p.get("planned")) and all(x in inst for x in p["plugins"]) and all(not pol["paused"].get(u, False) for u in p["unpause"]) \
            and (bool(p["plugins"]) or bool(p["unpause"]) or p["id"] == "document-processing")
        out.append({"id": p["id"], "name": p["name"], "blurb": p["blurb"], "enabled": enabled and not missing, "planned": bool(p.get("planned")), "missing": missing})
    return out


def enable(pk: str, pack_id: str) -> dict:
    pack = next((p for p in PACKS if p["id"] == pack_id), None)
    if not pack:
        raise LookupError("unknown pack")
    if pack.get("planned"):
        raise ValueError("this pack is not available yet")
    for pid in pack["plugins"]:
        manifest = plugins.registry()[pid]
        if not db.table().get_item(Key={"PK": pk, "SK": f"PLUGIN#{pid}"}).get("Item"):
            db.table().put_item(Item=db.to_ddb({"PK": pk, "SK": f"PLUGIN#{pid}", "version": manifest["version"], "permissions": manifest["permissions"],
                                                "config": plugins.validate_config(manifest, {}), "installedAt": int(time.time())}))
    if pack["unpause"]:
        cur = policy.get(pk)
        for u in pack["unpause"]:
            cur["paused"][u] = False
        policy.save(pk, cur)
    return next(s for s in status(pk) if s["id"] == pack_id)
