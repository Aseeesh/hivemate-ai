"""Connector contract. A connector knows ONE external system; everything shared (OAuth state, token refresh, checkpoints, retries,
idempotency, health) lives in runtime.py. Connectors both READ (pull) and WRITE (execute)."""
import time


class AuthExpired(Exception):
    """The refresh token no longer works: the owner must reconnect."""


class Connector:
    provider = ""
    label = ""
    # Canonical event types a connector can produce: email.received, invoice.updated
    write_actions: tuple[str, ...] = ()

    def configured(self) -> bool:
        raise NotImplementedError

    def authorize_url(self, state: str, redirect_uri: str) -> str:
        raise NotImplementedError

    def exchange_code(self, code: str, redirect_uri: str) -> dict:
        raise NotImplementedError

    def refresh(self, tokens: dict) -> dict:
        raise NotImplementedError

    def account_info(self, tokens: dict) -> dict:
        """{"label": human name of the connected account, "externalId": id used to route webhooks}"""
        raise NotImplementedError

    def pull(self, tokens: dict, conn: dict, reconcile: bool) -> tuple[list[dict], dict, dict]:
        """Return (canonical events, new checkpoint, extra connection state). `reconcile` re-reads a wider window to repair missed webhooks."""
        raise NotImplementedError

    def execute(self, tokens: dict, conn: dict, action: str, params: dict) -> dict:
        raise NotImplementedError

    def verify_webhook(self, headers: dict, body: bytes, query: dict, conn_lookup) -> tuple[bool, dict]:
        """Return (valid, http_response_overrides). Must be constant-time on secrets."""
        return False, {}


def with_expiry(tok: dict, previous: dict | None = None) -> dict:
    out = {"access_token": tok["access_token"], "refresh_token": tok.get("refresh_token") or (previous or {}).get("refresh_token", ""),
           "expires_at": int(time.time()) + int(tok.get("expires_in", 1800))}
    return out


def envelope(provider: str, event_type: str, event_id: str, external_id: str, occurred_at: str, data: dict) -> dict:
    """The canonical event shape shared by every connector."""
    return {"eventId": event_id, "source": provider, "eventType": event_type, "occurredAt": occurred_at, "externalRecordId": external_id, "data": data}
