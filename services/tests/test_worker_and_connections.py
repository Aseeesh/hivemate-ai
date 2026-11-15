import pytest

from src.api import connections
from src.common import mailer
from src.common.context import Ctx, Forbidden
from src.connectors import runtime
from src.pipeline import deals, tasks
from src.workers import sweeper

PK = "TENANT#a1"
ADMIN = Ctx("a1", "u1", "admin", "o@x.nz")
MEMBER = Ctx("a1", "u2", "member", "m@x.nz")


@pytest.fixture(autouse=True)
def base(fake, monkeypatch):
    fake.seed({"PK": PK, "SK": "META", "name": "SparkClean"})
    monkeypatch.setattr(mailer, "enabled", lambda: False)
    monkeypatch.setattr("src.connectors.runtime.try_send_mail", lambda *a, **k: None)
    monkeypatch.setattr(sweeper.platform, "refresh_rollup", lambda now: {"tenants": 0})


def test_scheduled_worker_runs_followups_and_connector_sync_together(fake):
    import time
    now = int(time.time())
    deals.on_inbound(PK, "d1", "email", "m", now - 2 * 86400, name="Jo", email="jo@x.nz")
    out = sweeper.handler({}, None)
    assert out["followUps"]["checked"] >= 1 and "connectors" in out
    assert tasks.list_tasks(PK)[0]["type"] == "reply_overdue"


def test_webhook_triggered_sync_rejects_a_malformed_tenant(fake):
    assert sweeper.handler({"syncTenant": "NOT-A-TENANT", "provider": "xero"}, None) == {"error": "bad tenant"}
    assert sweeper.handler({"syncTenant": PK, "provider": "xero"}, None) == {"skipped": "not connected"}


def test_connection_routes_are_admin_only_and_report_health(fake, monkeypatch):
    monkeypatch.setenv("XERO_CLIENT_ID", "x")
    monkeypatch.setenv("XERO_CLIENT_SECRET", "y")
    r = connections.route(MEMBER, "GET", "/connections", {}, {})
    assert r["statusCode"] == 200 and {c["provider"] for c in r["body"]} == {"microsoft365", "xero"}
    assert next(c for c in r["body"] if c["provider"] == "xero")["available"] is True
    with pytest.raises(Forbidden):
        connections.route(MEMBER, "POST", "/connections/xero/start", {}, {})
    with pytest.raises(Forbidden):
        connections.route(MEMBER, "DELETE", "/connections/xero", {}, {})
    assert connections.route(ADMIN, "POST", "/connections/nothing/start", {}, {})["statusCode"] == 404
    assert connections.route(ADMIN, "POST", "/connections/xero/sync", {}, {})["statusCode"] == 409  # not connected


def test_unconfigured_provider_reports_a_clear_message_not_a_crash(fake, monkeypatch):
    monkeypatch.delenv("MS_CLIENT_ID", raising=False)
    monkeypatch.setattr("src.connectors.appconfig._cache", {})
    r = connections.route(ADMIN, "POST", "/connections/microsoft365/start", {}, {})
    assert r["statusCode"] == 409 and "not set up" in r["body"]["error"]


def test_sync_now_cannot_be_used_on_an_expired_connection_and_disconnect_deletes_credentials(fake, monkeypatch):
    deleted = []
    monkeypatch.setattr("src.connectors.credstore.delete", lambda pk, p: deleted.append((pk, p)))
    runtime._save_conn(PK, {**runtime.conn_key(PK, "xero"), "provider": "xero", "status": "needs_reauth"})
    assert connections.route(ADMIN, "POST", "/connections/xero/sync", {}, {})["statusCode"] == 409
    assert connections.route(ADMIN, "DELETE", "/connections/xero", {}, {})["statusCode"] == 200
    assert deleted == [(PK, "xero")] and runtime.get_conn(PK, "xero") is None
