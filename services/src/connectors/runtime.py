"""Shared connector runtime: OAuth handshake, token refresh, scheduled sync with checkpoints, idempotent writes, health and alerts.

Connection record  PK=TENANT#id SK=CONN#<provider>
  status: connected | needs_reauth | error     lastSyncAt, lastSyncStatus, lastError, failures, failedEvents, tokenExpiresAt
  checkpoint (provider-defined), lastReconcileAt, nextSyncAt (+ GSI keys SYNC#<shard>)
"""
import hashlib
import json
import os
import secrets
import time

import boto3

from src.common import db, events, mailer, policy
from src.connectors import credstore
from src.connectors.base import AuthExpired, Connector
from src.pipeline import deals

SYNC_EVERY = 900
RECONCILE_EVERY = 86400
REFRESH_MARGIN = 300
BACKOFF_CAP = 6 * 3600
DOWN_AFTER = 3
STATE_TTL = 600
_bus = None


class NotConfigured(Exception):
    pass


class Conflict(Exception):
    pass


def registry() -> dict[str, Connector]:
    from src.connectors.microsoft365 import Microsoft365
    from src.connectors.xero import Xero
    return {c.provider: c for c in (Microsoft365(), Xero())}


def connector(provider: str) -> Connector:
    c = registry().get(provider)
    if not c:
        raise LookupError("unknown provider")
    return c


def redirect_uri(provider: str) -> str:
    return f"{os.environ.get('OAUTH_REDIRECT_BASE', '').rstrip('/')}/oauth/{provider}/callback"


def _h(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()[:40]


def conn_key(pk: str, provider: str) -> dict:
    return {"PK": pk, "SK": f"CONN#{provider}"}


def get_conn(pk: str, provider: str) -> dict | None:
    it = db.table().get_item(Key=conn_key(pk, provider)).get("Item")
    return db.clean(it) if it else None


def _save_conn(pk: str, conn: dict) -> None:
    conn = {k: v for k, v in conn.items() if k not in ("GSI1PK", "GSI1SK")}
    if conn.get("status") != "needs_reauth" and conn.get("nextSyncAt"):
        conn["GSI1PK"] = f"SYNC#{deals.shard(pk)}"
        conn["GSI1SK"] = f"{int(conn['nextSyncAt']):013d}#{pk}#{conn['provider']}"
    db.table().put_item(Item=db.to_ddb(conn))


# ---------------- OAuth ----------------
def start_auth(pk: str, provider: str) -> str:
    c = connector(provider)
    if not c.configured():
        raise NotConfigured(f"{c.label} is not set up on this Hivemate deployment yet (the operator must register the app)")
    nonce = secrets.token_urlsafe(24)
    db.table().put_item(Item={"PK": pk, "SK": f"OAS#{_h(nonce)}", "GSI1PK": f"OAS#{_h(nonce)}", "GSI1SK": pk, "provider": provider,
                              "ttl": int(time.time()) + STATE_TTL, "createdAt": int(time.time())})
    return c.authorize_url(nonce, redirect_uri(provider))


def complete_auth(provider: str, state: str, code: str, now: int | None = None) -> str:
    """Browser callback. The tenant is recovered ONLY from the one-time state we issued, never from the request."""
    now = int(now or time.time())
    rows = db.query_index(f"OAS#{_h(state)}", "~", limit=1) if state else []
    if not rows or rows[0].get("provider") != provider or int(rows[0].get("ttl", 0)) < now:
        raise PermissionError("this connection link expired or was already used")
    row = rows[0]
    pk = row["GSI1SK"]
    db.table().delete_item(Key={"PK": pk, "SK": row["SK"]})  # single use
    c = connector(provider)
    tokens = c.exchange_code(code, redirect_uri(provider))
    info = c.account_info(tokens)
    credstore.put(pk, provider, tokens)
    conn = {**conn_key(pk, provider), "provider": provider, "status": "connected", "label": info.get("label", provider),
            "externalId": info.get("externalId", ""), "connectedAt": now, "tokenExpiresAt": tokens["expires_at"], "failures": 0, "failedEvents": 0,
            "checkpoint": {}, "nextSyncAt": now, "lastSyncStatus": "pending", "lastError": ""}
    _save_conn(pk, conn)
    if info.get("externalId"):  # lets a webhook that names only the external account find the business
        db.table().put_item(Item={"PK": pk, "SK": f"XMAP#{provider}", "GSI1PK": f"XT#{provider}#{info['externalId']}", "GSI1SK": pk})
    from src.pipeline import tasks
    tasks.resolve_for_deal(pk, f"conn-{provider}", ("connection_attention",))
    db.audit(pk, f"connector:{provider}", "connection.connected", {"label": conn["label"]})
    return pk


def disconnect(pk: str, provider: str) -> None:
    credstore.delete(pk, provider)
    db.table().delete_item(Key=conn_key(pk, provider))
    db.table().delete_item(Key={"PK": pk, "SK": f"XMAP#{provider}"})
    db.audit(pk, "user", "connection.disconnected", {"provider": provider})


def tenant_for_external(provider: str, external_id: str) -> str | None:
    rows = db.query_index(f"XT#{provider}#{external_id}", "~", limit=1)
    return rows[0]["GSI1SK"] if rows else None


# ---------------- tokens ----------------
def valid_tokens(pk: str, provider: str, now: int | None = None) -> dict:
    now = int(now or time.time())
    tokens = credstore.get(pk, provider)
    if not tokens:
        raise AuthExpired("no stored credentials")
    if int(tokens.get("expires_at", 0)) - now > REFRESH_MARGIN:
        return tokens
    try:
        tokens = connector(provider).refresh(tokens)
    except AuthExpired:
        raise
    except Exception as exc:  # a 400 invalid_grant from the provider means the refresh token is dead
        from src.connectors.http import HttpError
        if isinstance(exc, HttpError) and exc.status in (400, 401):
            raise AuthExpired(str(exc)) from exc
        raise
    credstore.put(pk, provider, tokens)
    db.update(conn_key(pk, provider), sets={"tokenExpiresAt": tokens["expires_at"]})
    return tokens


# ---------------- sync ----------------
def _bus_client():
    global _bus
    if _bus is None:
        _bus = boto3.client("events")
    return _bus


def emit_email(pk: str, provider: str, ev: dict) -> None:
    """Hand an inbound email to the existing Email Automation worker (classify, draft, approval gate)."""
    d = ev["data"]
    msg_id = f"{int(time.time() * 1000):013d}{_h(provider + ev['externalRecordId'])[:8]}"
    _bus_client().put_events(Entries=[{
        "EventBusName": os.environ["EVENT_BUS"], "Source": "hivemate.channel", "DetailType": "email.received",
        "Detail": json.dumps({"tenantId": pk[7:], "messageId": msg_id, "from": d["from"], "fromName": d.get("fromName", ""), "subject": d.get("subject", ""),
                              "body": d.get("body", ""), "source": provider, "externalId": ev["externalRecordId"]}),
    }])


def ingest(pk: str, provider: str, evs: list[dict], now: int | None = None) -> int:
    """Idempotent: an event id seen before is skipped, so delayed, duplicated or replayed webhooks and re-syncs change nothing."""
    from src.pipeline import invoices
    n = 0
    for ev in evs:
        if not db.create({"PK": pk, "SK": f"SEEN#{provider}#{_h(ev['eventId'])}", "ttl": int(time.time()) + 30 * 86400}):
            continue
        if ev["eventType"] == "email.received":
            emit_email(pk, provider, ev)
        elif ev["eventType"] == "invoice.updated":
            invoices.process(pk, ev["data"], now)
        elif ev["eventType"] == "invoice.snapshot":
            invoices.snapshot(pk, ev["data"]["outstandingIds"])
        n += 1
    return n


def sync(pk: str, provider: str, now: int | None = None, force: bool = False) -> dict:
    now = int(now or time.time())
    conn = get_conn(pk, provider)
    if not conn or conn["status"] == "needs_reauth":
        return {"skipped": "not connected"}
    if not force and policy.get(pk)["paused"]["connector_sync"]:
        return {"skipped": "paused"}
    reconcile = now - int(conn.get("lastReconcileAt", 0)) > RECONCILE_EVERY
    try:
        tokens = valid_tokens(pk, provider, now)
        evs, checkpoint, extra = connector(provider).pull(tokens, conn, reconcile)
        n = ingest(pk, provider, evs, now)
    except AuthExpired as exc:
        conn.update({"status": "needs_reauth", "lastError": "The connection expired. Please reconnect.", "lastSyncStatus": "failed"})
        conn.pop("nextSyncAt", None)
        _save_conn(pk, conn)
        _attention(pk, provider, conn, "needs reconnecting", str(exc))
        return {"error": "needs_reauth"}
    except Exception as exc:  # noqa: BLE001
        f = int(conn.get("failures", 0)) + 1
        conn.update({"failures": f, "lastError": str(exc)[:300], "lastSyncStatus": "failed", "lastFailedAt": now,
                     "nextSyncAt": now + min(BACKOFF_CAP, SYNC_EVERY * 2 ** f)})
        if f >= DOWN_AFTER:
            conn["status"] = "error"
            _attention(pk, provider, conn, "is failing to sync", str(exc))
        _save_conn(pk, conn)
        events.record(pk, "sync_failed", provider, at=now, error=str(exc)[:120])
        return {"error": str(exc)[:200]}
    conn.update({"status": "connected", "failures": 0, "lastError": "", "lastSyncAt": now, "lastSyncStatus": "ok", "checkpoint": checkpoint,
                 "nextSyncAt": now + SYNC_EVERY, "lastIngested": n, **extra})
    if reconcile:
        conn["lastReconcileAt"] = now
    conn.pop("alerted", None)
    if extra.get("webhookKey"):  # a push subscription that names only its own id must still resolve to this business
        db.table().put_item(Item={"PK": pk, "SK": f"XMAP#{provider}#sub", "GSI1PK": f"XT#{provider}#{extra['webhookKey']}", "GSI1SK": pk})
    _save_conn(pk, conn)
    return {"ingested": n, "reconciled": reconcile}


def sync_due(now: int | None = None) -> dict:
    now = int(now or time.time())
    out = {"synced": 0, "failed": 0}
    for s in range(deals.SHARDS):
        for row in db.query_index(f"SYNC#{s}", f"{now:013d}~", limit=50):
            r = sync(row["PK"], row["provider"], now)
            out["failed" if "error" in r else "synced"] += 1
    return out


def request_sync(pk: str, provider: str, now: int | None = None) -> bool:
    """A webhook arrived: make the connection due immediately (the scheduled worker does the actual pull)."""
    conn = get_conn(pk, provider)
    if not conn or conn["status"] == "needs_reauth":
        return False
    conn["nextSyncAt"] = int(now or time.time())
    _save_conn(pk, conn)
    return True


def note_webhook_failure(pk: str, provider: str) -> None:
    db.update(conn_key(pk, provider), add={"failedEvents": 1})


# ---------------- alerts ----------------
def _owner_emails(pk: str) -> list[str]:
    return [u["email"] for u in db.query_prefix(pk, "USER#", limit=50) if u.get("role") == "admin" and u.get("email")][:3]


def _attention(pk: str, provider: str, conn: dict, what: str, detail: str) -> None:
    from src.pipeline import tasks
    label = connector(provider).label
    tasks.create(pk, f"conn-{provider}-{conn['status']}", "connection_attention", f"{label} {what}", priority="urgent",
                 deal_id=f"conn-{provider}", detail=("Reconnect it from Integrations so automations can continue." if conn["status"] == "needs_reauth" else detail[:300]))
    if conn.get("alerted") == conn["status"]:
        return
    conn["alerted"] = conn["status"]
    if mailer.enabled():
        for to in _owner_emails(pk):
            try:
                mailer.send_reply(business="Hivemate", to=to, subject=f"{label} needs attention",
                                  body=f"Hivemate's connection to {label} {what}. Open Integrations in your dashboard to fix it. Automations that use it are paused until then.")
            except Exception:  # noqa: BLE001 - an alert failure must not hide the original problem
                pass
    db.audit(pk, f"connector:{provider}", "connection.attention", {"status": conn["status"]})


# ---------------- writes ----------------
def execute(pk: str, provider: str, action: str, params: dict, idem_key: str, now: int | None = None) -> dict:
    """Run a write against the external system at most once per idempotency key."""
    now = int(now or time.time())
    c = connector(provider)
    if action not in c.write_actions:
        raise ValueError(f"{provider} cannot {action}")
    key = {"PK": pk, "SK": f"IDEM#{_h(idem_key)}"}
    if not db.create({**key, "status": "started", "startedAt": now, "ttl": now + 7 * 86400}):
        prev = db.clean(db.table().get_item(Key=key).get("Item") or {})
        if prev.get("status") == "done":
            return {**(prev.get("result") or {}), "duplicate": True}
        if now - int(prev.get("startedAt", 0)) < 600:
            raise Conflict("this action is already running")
    conn = get_conn(pk, provider)
    if not conn or conn["status"] != "connected":
        db.table().delete_item(Key=key)
        raise RuntimeError(f"{c.label} is not connected")
    try:
        result = c.execute(valid_tokens(pk, provider, now), conn, action, params)
    except Exception:
        db.table().delete_item(Key=key)  # nothing happened externally, so the key can be retried
        raise
    db.update(key, sets={"status": "done", "result": result or {}})
    return result or {}


def try_send_mail(pk: str, to: str, subject: str, body: str, idem_key: str) -> str | None:
    """Send from the owner's own mailbox if a mail connector is connected; None means 'use the normal route'."""
    conn = get_conn(pk, "microsoft365")
    if not conn or conn["status"] != "connected":
        return None
    execute(pk, "microsoft365", "send_mail", {"to": to, "subject": subject, "body": body}, idem_key)
    return "microsoft365"


# ---------------- health ----------------
def health(pk: str) -> list[dict]:
    out = []
    for p, c in registry().items():
        conn = get_conn(pk, p)
        out.append({"provider": p, "label": c.label, "available": c.configured(), "connected": bool(conn), "status": (conn or {}).get("status", "not_connected"),
                    "account": (conn or {}).get("label", ""), "lastSyncAt": (conn or {}).get("lastSyncAt"), "lastSyncStatus": (conn or {}).get("lastSyncStatus", ""),
                    "lastError": (conn or {}).get("lastError", ""), "failedEvents": int((conn or {}).get("failedEvents", 0)),
                    "tokenExpiresAt": (conn or {}).get("tokenExpiresAt"), "writes": list(c.write_actions)})
    return out
