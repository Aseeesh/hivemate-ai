"""Scheduled worker (EventBridge, every 15 minutes) and on-demand sync (invoked by a verified webhook).

1. Follow-up sweep: deals whose next-due time has passed.
2. Connector sync: connections whose next-sync time has passed.
Both are idempotent, so an overlapping or repeated run is harmless.
"""
import json
import time

from src.connectors import runtime
from src.api import platform
from src.pipeline import followups


def handler(event, _context):
    now = int(time.time())
    if event.get("syncTenant"):  # webhook-triggered
        pk, provider = str(event["syncTenant"]), str(event["provider"])
        if not pk.startswith("TENANT#"):
            return {"error": "bad tenant"}
        out = runtime.sync(pk, provider, now)
        print(json.dumps({"level": "INFO", "event": "webhook_sync", "provider": provider, "result": out}))
        return out
    out = {"followUps": followups.sweep(now), "connectors": runtime.sync_due(now)}
    if now % 3600 < 900:  # once an hour: refresh the platform console rollup (the only table scan, off the request path)
        out["rollup"] = platform.refresh_rollup(now)
    print(json.dumps({"level": "INFO", "event": "sweep", **out}))
    return out
