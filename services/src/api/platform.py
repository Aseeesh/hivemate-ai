"""Platform console API (super admin). READ-ONLY, metadata only.

Who: members of the Cognito group `platform-admins` (assigned by an operator with the AWS CLI; a browser cannot grant it).
What: tenant list, usage counts, plugin/user/channel status, website origins, document names, daily activity, recent audit actions.
Never: customer messages, conversation text, lead details, email bodies, plugin config values, site keys or API tokens.
Every look at one business is written to THAT business's audit trail (`platform.viewed_tenant`) so operator access is visible to it.
Scale note: counts come from one table scan, fine for a dev/early stage; replace with maintained counters before hundreds of tenants.
"""
import json
import os
import re
import time

import boto3
from botocore.exceptions import ClientError

from src.common import db
from src.common.context import Forbidden, from_event

s3 = boto3.client("s3")
TENANT_ID = re.compile(r"^[a-z0-9]{6,40}$")
MAX_ITEMS = 50_000  # hard stop so a huge table cannot time the Lambda out


def _resp(status: int, body) -> dict:
    return {"statusCode": status, "headers": {"content-type": "application/json"}, "body": json.dumps(body)}


def scan_all() -> tuple[list[dict], bool]:
    """Keys and small attributes only: text fields (messages, turns, summaries) are never requested."""
    items, kw, truncated = [], {
        "ProjectionExpression": "PK, SK, #n, createdAt, #r, email, lastAt, updatedAt, #s, channel, #at, #ac, version, allowedOrigins",
        "ExpressionAttributeNames": {"#n": "name", "#r": "role", "#s": "status", "#at": "at", "#ac": "action"},
    }, False
    while True:
        r = db.table().scan(**kw)
        items += r["Items"]
        if len(items) >= MAX_ITEMS:
            truncated = True
            break
        if "LastEvaluatedKey" not in r:
            break
        kw["ExclusiveStartKey"] = r["LastEvaluatedKey"]
    return [db.clean(i) for i in items], truncated


def summarise(items: list[dict]) -> dict[str, dict]:
    """Per-tenant rollup from raw items. Pure function (unit-tested)."""
    out: dict[str, dict] = {}
    for it in items:
        pk, sk = it["PK"], it["SK"]
        if not pk.startswith("TENANT#"):
            continue
        t = out.setdefault(pk[7:], {"tenantId": pk[7:], "name": "", "createdAt": None, "users": 0, "plugins": [], "conversations": 0,
                                    "leads": 0, "leadsComplete": 0, "handoffs": 0, "messages": 0, "messagesHeld": 0, "lastActivity": 0, "channels": [], "origins": []})
        kind = sk.split("#", 1)[0]
        if sk == "META":
            t["name"], t["createdAt"] = it.get("name", ""), it.get("createdAt")
        elif kind == "USER":
            t["users"] += 1
        elif kind == "PLUGIN":
            t["plugins"].append(sk[7:])
        elif kind == "CONV":
            t["conversations"] += 1
            t["lastActivity"] = max(t["lastActivity"], int(it.get("lastAt", 0)))
            t["handoffs"] += it.get("status") == "HANDOFF"
        elif kind == "LEAD":
            t["leads"] += 1
            t["leadsComplete"] += it.get("status") == "COMPLETE"
        elif kind == "MSG":
            t["messages"] += 1
            t["messagesHeld"] += it.get("status") == "PENDING_APPROVAL"
        elif kind == "AUDIT":
            t["lastActivity"] = max(t["lastActivity"], int(it.get("at", 0)) // 1000)
        elif kind == "CHANNEL":
            t["channels"].append(sk[8:])
            t["origins"] = [str(o)[:200] for o in (it.get("allowedOrigins") or [])][:20]
    return out


def daily(items: list[dict], tenant_id: str | None = None, days: int = 14, now: float | None = None) -> list[dict]:
    """Conversations and leads started per UTC day for the last `days` days, oldest first (zeros included so charts have no gaps)."""
    now = now or time.time()
    keys = [time.strftime("%Y-%m-%d", time.gmtime(now - i * 86400)) for i in range(days - 1, -1, -1)]
    out = {k: {"day": k, "conversations": 0, "leads": 0} for k in keys}
    for it in items:
        if tenant_id and it["PK"] != f"TENANT#{tenant_id}":
            continue
        kind = it["SK"].split("#", 1)[0]
        if kind in ("CONV", "LEAD") and it.get("createdAt"):
            day = time.strftime("%Y-%m-%d", time.gmtime(int(it["createdAt"])))
            if day in out:
                out[day]["conversations" if kind == "CONV" else "leads"] += 1
    return list(out.values())


def overview(rollup: dict[str, dict]) -> dict:
    ts = list(rollup.values())
    plugin_counts: dict[str, int] = {}
    for t in ts:
        for p in t["plugins"]:
            plugin_counts[p] = plugin_counts.get(p, 0) + 1
    day_ago = time.time() - 86400
    return {"tenants": len(ts), "users": sum(t["users"] for t in ts), "conversations": sum(t["conversations"] for t in ts),
            "leads": sum(t["leads"] for t in ts), "leadsComplete": sum(t["leadsComplete"] for t in ts), "handoffs": sum(t["handoffs"] for t in ts),
            "messages": sum(t["messages"] for t in ts), "messagesHeld": sum(t["messagesHeld"] for t in ts),
            "activeLast24h": sum(1 for t in ts if t["lastActivity"] > day_ago), "pluginInstalls": plugin_counts}


def detail(tenant_id: str, items: list[dict], rollup: dict) -> dict | None:
    t = rollup.get(tenant_id)
    if not t:
        return None
    mine = [i for i in items if i["PK"] == f"TENANT#{tenant_id}"]
    users = [{"email": u.get("email", ""), "role": u.get("role", "")} for u in mine if u["SK"].startswith("USER#")]
    plugins = [{"pluginId": p["SK"][7:], "version": p.get("version", "")} for p in mine if p["SK"].startswith("PLUGIN#")]
    audit = sorted((a for a in mine if a["SK"].startswith("AUDIT#")), key=lambda a: a.get("at", 0), reverse=True)[:30]
    docs = s3.list_objects_v2(Bucket=os.environ["DOCS_BUCKET"], Prefix=f"tenants/{tenant_id}/docs/", MaxKeys=1000).get("Contents", [])
    docs = [o for o in docs if not o["Key"].endswith(".metadata.json")]
    return {**t, "userList": users, "pluginList": plugins, "documents": {"count": len(docs), "bytes": sum(o["Size"] for o in docs)},
            "documentList": [{"name": o["Key"].rsplit("/", 1)[-1], "size": o["Size"], "modified": o["LastModified"].isoformat() if o.get("LastModified") else ""} for o in docs][:100],
            "daily": daily(items, tenant_id),
            "recentAudit": [{"at": a.get("at"), "action": a.get("action", "")} for a in audit]}  # action names only, no detail payloads


def handler(event, _context):
    method, path = event["requestContext"]["http"]["method"], event["rawPath"]
    if method == "OPTIONS":
        return {"statusCode": 204}
    try:
        ctx = from_event(event)
        ctx.require_platform()
        items, truncated = scan_all()
        rollup = summarise(items)
        if (method, path) == ("GET", "/platform/overview"):
            return _resp(200, {**overview(rollup), "daily": daily(items), "truncated": truncated})
        if (method, path) == ("GET", "/platform/tenants"):
            rows = sorted(rollup.values(), key=lambda t: t["lastActivity"], reverse=True)
            return _resp(200, {"tenants": rows, "truncated": truncated})
        m = re.fullmatch(r"/platform/tenants/([a-z0-9]+)", path)
        if m and method == "GET":
            if not TENANT_ID.match(m.group(1)):
                return _resp(400, {"error": "invalid tenant id"})
            d = detail(m.group(1), items, rollup)
            if not d:
                return _resp(404, {"error": "not found"})
            db.audit(f"TENANT#{m.group(1)}", f"platform:{ctx.email}", "platform.viewed_tenant", {})
            return _resp(200, d)
        return _resp(404, {"error": "not found"})
    except Forbidden as e:
        return _resp(403, {"error": str(e)})
    except ClientError as e:
        print(json.dumps({"level": "ERROR", "error": repr(e)[:300]}))
        return _resp(502, {"error": "temporarily unavailable"})
