"""Integration Health: list connected systems with their status, start OAuth, retry a failed sync, disconnect."""
import re

from src.common import db
from src.common.context import Ctx
from src.connectors import runtime


def _r(status: int, body):
    return {"statusCode": status, "body": body}


def route(ctx: Ctx, method: str, path: str, body: dict, query: dict):
    if (method, path) == ("GET", "/connections"):
        return _r(200, runtime.health(ctx.pk))
    m = re.fullmatch(r"/connections/([a-z0-9]{3,30})(?:/(start|sync))?", path)
    if not m:
        return None
    provider, action = m.groups()
    ctx.require_admin()
    try:
        runtime.connector(provider)
    except LookupError:
        return _r(404, {"error": "unknown integration"})
    if method == "POST" and action == "start":
        try:
            return _r(200, {"url": runtime.start_auth(ctx.pk, provider)})
        except runtime.NotConfigured as e:
            return _r(409, {"error": str(e)})
    if method == "POST" and action == "sync":
        conn = runtime.get_conn(ctx.pk, provider)
        if not conn:
            return _r(409, {"error": "not connected"})
        if conn["status"] == "needs_reauth":
            return _r(409, {"error": "the connection expired: reconnect it first"})
        out = runtime.sync(ctx.pk, provider, force=True)
        db.audit(ctx.pk, ctx.user_id, "connection.sync_requested", {"provider": provider, "result": "error" if "error" in out else "ok"})
        return _r(200 if "error" not in out else 502, out)
    if method == "DELETE" and not action:
        runtime.disconnect(ctx.pk, provider)
        return _r(200, {"disconnected": provider})
    return None
