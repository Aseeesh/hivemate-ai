import base64
import hashlib
import hmac
import json
import time
import urllib.parse

import pytest

from src.common import db, mailer
from src.connectors import credstore, http, runtime
from src.connectors.base import AuthExpired
from src.connectors.microsoft365 import Microsoft365
from src.connectors.xero import Xero
from src.pipeline import invoices, tasks

PK = "TENANT#a1"
NOW = 1_794_776_400  # Monday 10:00 NZDT


class Net:
    """Routes fake HTTP calls by (method, url prefix); records requests."""
    def __init__(self):
        self.routes, self.calls = [], []

    def on(self, method, prefix, status=200, body=None, headers=None):
        self.routes.append([method, prefix, status, body if body is not None else {}, headers or {}])

    def __call__(self, req, timeout):
        self.calls.append((req.method, req.full_url, dict(req.headers), req.data))
        for r in self.routes:
            if r[0] == req.method and req.full_url.startswith(r[1]):
                status, body = r[2], r[3]
                if isinstance(body, list):  # sequence of responses
                    status, body = body.pop(0) if len(body) > 1 else body[0]
                return status, r[4], json.dumps(body).encode()
        raise AssertionError(f"unexpected call {req.method} {req.full_url}")


@pytest.fixture
def net(monkeypatch):
    n = Net()
    monkeypatch.setattr(http, "_open", n)
    monkeypatch.setattr(http.time, "sleep", lambda s: None)
    return n


@pytest.fixture
def secrets_store(monkeypatch):
    store = {}
    monkeypatch.setattr(credstore, "put", lambda pk, p, t: store.__setitem__((pk, p), dict(t)))
    monkeypatch.setattr(credstore, "get", lambda pk, p: dict(store[(pk, p)]) if (pk, p) in store else None)
    monkeypatch.setattr(credstore, "delete", lambda pk, p: store.pop((pk, p), None))
    return store


@pytest.fixture
def env(monkeypatch):
    for k, v in {"MS_CLIENT_ID": "msid", "MS_CLIENT_SECRET": "mssecret", "XERO_CLIENT_ID": "xid", "XERO_CLIENT_SECRET": "xsecret",
                 "XERO_WEBHOOK_KEY": "whkey", "OAUTH_REDIRECT_BASE": "https://api.example.nz", "EVENT_BUS": "hivemate"}.items():
        monkeypatch.setenv(k, v)


# ---------------- http ----------------
def test_http_retries_429_then_succeeds_and_honours_retry_after(net, monkeypatch):
    waits = []
    net.on("GET", "https://x.test/a", body=[(429, {}), (200, {"ok": 1})], headers={})
    net.routes[0][4] = {"Retry-After": "2"}
    status, body, _ = http.request("GET", "https://x.test/a", sleep=waits.append)
    assert status == 200 and body == {"ok": 1} and waits == [2.0]


def test_http_gives_up_after_retries_and_4xx_is_not_retried(net):
    net.on("GET", "https://x.test/down", status=503, body={})
    with pytest.raises(http.HttpError):
        http.request("GET", "https://x.test/down", retries=2, sleep=lambda s: None)
    assert len(net.calls) == 3
    net.calls.clear()
    net.on("GET", "https://x.test/bad", status=404, body={"e": 1})
    with pytest.raises(http.HttpError) as e:
        http.request("GET", "https://x.test/bad", sleep=lambda s: None)
    assert e.value.status == 404 and len(net.calls) == 1


def test_http_refuses_non_https():
    with pytest.raises(ValueError):
        http.request("GET", "http://x.test/")


# ---------------- OAuth state + tokens ----------------
def connect_ms(net, secrets_store, env_):
    url = runtime.start_auth(PK, "microsoft365")
    state = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["state"][0]
    net.on("POST", "https://login.microsoftonline.com/common/oauth2/v2.0/token", body={"access_token": "AT", "refresh_token": "RT", "expires_in": 3600})
    net.on("GET", "https://graph.microsoft.com/v1.0/me", body={"mail": "owner@spark.nz", "id": "u-1"})
    return state


def test_oauth_state_is_single_use_and_recovers_tenant_only_from_state(fake, net, secrets_store, env):
    state = connect_ms(net, secrets_store, env)
    assert runtime.complete_auth("microsoft365", state, "code123") == PK
    conn = runtime.get_conn(PK, "microsoft365")
    assert conn["status"] == "connected" and conn["label"] == "owner@spark.nz"
    assert secrets_store[(PK, "microsoft365")]["refresh_token"] == "RT"
    assert not any("refresh_token" in str(v) for v in fake.items.values())  # tokens never reach the table
    with pytest.raises(PermissionError):
        runtime.complete_auth("microsoft365", state, "code123")  # replay


def test_oauth_state_expires_and_is_bound_to_provider(fake, net, secrets_store, env):
    state = connect_ms(net, secrets_store, env)
    with pytest.raises(PermissionError):
        runtime.complete_auth("xero", state, "c", NOW)  # state issued for another provider
    with pytest.raises(PermissionError):
        runtime.complete_auth("microsoft365", state, "c", int(time.time()) + 3600)  # expired
    with pytest.raises(PermissionError):
        runtime.complete_auth("microsoft365", "forged", "c")


def test_unconfigured_provider_cannot_start(fake, monkeypatch):
    monkeypatch.delenv("MS_CLIENT_ID", raising=False)
    with pytest.raises(runtime.NotConfigured):
        runtime.start_auth(PK, "microsoft365")


def test_token_refresh_persists_rotated_refresh_token(fake, net, secrets_store, env):
    runtime._save_conn(PK, {**runtime.conn_key(PK, "xero"), "provider": "xero", "status": "connected", "externalId": "org"})
    now = int(time.time())
    secrets_store[(PK, "xero")] = {"access_token": "old", "refresh_token": "R1", "expires_at": now + 10}
    net.on("POST", "https://identity.xero.com/connect/token", body={"access_token": "new", "refresh_token": "R2", "expires_in": 1800})
    t = runtime.valid_tokens(PK, "xero", now)
    assert t["access_token"] == "new" and secrets_store[(PK, "xero")]["refresh_token"] == "R2"
    assert net.calls[-1][2]["Authorization"].startswith("Basic ")
    assert runtime.valid_tokens(PK, "xero", now)["access_token"] == "new"  # fresh now: no second refresh
    assert len(net.calls) == 1


def test_dead_refresh_token_marks_connection_needs_reauth_and_alerts_once(fake, net, secrets_store, env, monkeypatch):
    fake.seed({"PK": PK, "SK": "USER#1", "email": "owner@spark.nz", "role": "admin"})
    runtime._save_conn(PK, {**runtime.conn_key(PK, "xero"), "provider": "xero", "status": "connected", "externalId": "org", "nextSyncAt": NOW})
    secrets_store[(PK, "xero")] = {"access_token": "old", "refresh_token": "R1", "expires_at": NOW - 5}
    net.on("POST", "https://identity.xero.com/connect/token", status=400, body={"error": "invalid_grant"})
    mails = []
    monkeypatch.setattr(mailer, "enabled", lambda: True)
    monkeypatch.setattr(mailer, "send_reply", lambda **kw: mails.append(kw))
    assert runtime.sync(PK, "xero", NOW) == {"error": "needs_reauth"}
    assert runtime.get_conn(PK, "xero")["status"] == "needs_reauth"
    assert [t["title"] for t in tasks.list_tasks(PK)] == ["Xero needs reconnecting"] and len(mails) == 1
    assert runtime.sync(PK, "xero", NOW + 5) == {"skipped": "not connected"}  # stops hammering a dead connection


def test_repeated_failures_back_off_then_flag_error(fake, net, secrets_store, env):
    runtime._save_conn(PK, {**runtime.conn_key(PK, "microsoft365"), "provider": "microsoft365", "status": "connected", "label": "o@x.nz", "nextSyncAt": NOW})
    secrets_store[(PK, "microsoft365")] = {"access_token": "a", "refresh_token": "r", "expires_at": NOW + 3000}
    net.on("GET", "https://graph.microsoft.com/v1.0/me/mailFolders", status=500, body={})
    waits = []
    for i in range(3):
        runtime.sync(PK, "microsoft365", NOW + i)
        waits.append(runtime.get_conn(PK, "microsoft365")["nextSyncAt"] - (NOW + i))
    c = runtime.get_conn(PK, "microsoft365")
    assert c["status"] == "error" and waits[0] < waits[1] < waits[2] and c["failures"] == 3 and c["lastSyncStatus"] == "failed"


# ---------------- Microsoft 365 ----------------
MAIL = {"value": [
    {"id": "AAA=", "subject": "Quote please", "receivedDateTime": "2026-11-16T08:00:00Z", "from": {"emailAddress": {"address": "Jo@Client.nz", "name": "Jo"}}, "body": {"content": "How much for a 3 bed?"}},
    {"id": "BBB=", "subject": "News", "receivedDateTime": "2026-11-16T08:05:00Z", "from": {"emailAddress": {"address": "noreply@shop.com", "name": "Shop"}}, "body": {"content": "sale"}},
    {"id": "CCC=", "subject": "me", "receivedDateTime": "2026-11-16T08:06:00Z", "from": {"emailAddress": {"address": "owner@spark.nz"}}, "body": {"content": "x"}},
]}


def test_m365_pull_reads_new_mail_skips_bots_and_self_and_sets_checkpoint(net):
    net.on("GET", "https://graph.microsoft.com/v1.0/me/mailFolders/inbox/messages", body=MAIL)
    evs, cp, _ = Microsoft365().pull({"access_token": "t"}, {"label": "owner@spark.nz", "checkpoint": {}}, False, now=NOW)
    assert [e["data"]["from"] for e in evs] == ["jo@client.nz"] and evs[0]["eventType"] == "email.received"
    assert cp == {"receivedAfter": "2026-11-16T08:06:00Z"}
    url = urllib.parse.unquote(net.calls[0][1])
    assert "receivedDateTime ge 2026-11-14T21:00:00Z" in url  # first sync looks back one day only, not the whole mailbox


def test_m365_write_actions_and_id_is_url_quoted(net):
    net.on("POST", "https://graph.microsoft.com/v1.0/me/sendMail", status=202)
    net.on("POST", "https://graph.microsoft.com/v1.0/me/messages/", body={"id": "D1"})
    m = Microsoft365()
    assert m.execute({"access_token": "t"}, {}, "send_mail", {"to": "a@b.nz", "subject": "S", "body": "B"}) == {"sent": True}
    out = m.execute({"access_token": "t"}, {}, "create_draft_reply", {"messageId": "../../x?y=1", "body": "hi"})
    assert out == {"draftId": "D1"} and "%2F" in net.calls[-1][1] and "?y=1" not in net.calls[-1][1]
    with pytest.raises(ValueError):
        m.execute({"access_token": "t"}, {}, "delete_everything", {})


def test_graph_webhook_validation_handshake_and_client_state(net):
    m = Microsoft365()
    ok, resp = m.verify_webhook({}, b"", {"validationToken": "abc"}, lambda s: None)
    assert ok and resp["body"] == "abc" and resp["headers"]["content-type"] == "text/plain"
    lookup = lambda sub: {"clientState": "secret-state"} if sub == "sub1" else None
    body = lambda cs, sub="sub1": json.dumps({"value": [{"subscriptionId": sub, "clientState": cs}]}).encode()
    assert m.verify_webhook({}, body("secret-state"), {}, lookup)[0]
    assert not m.verify_webhook({}, body("wrong"), {}, lookup)[0]
    assert not m.verify_webhook({}, body("secret-state", "other"), {}, lookup)[0]
    assert not m.verify_webhook({}, b"not json", {}, lookup)[0]


# ---------------- ingest idempotency ----------------
def test_same_event_ingested_twice_emits_one_email(fake, monkeypatch):
    sent = []
    monkeypatch.setattr(runtime, "emit_email", lambda pk, prov, ev: sent.append(ev["eventId"]))
    ev = {"eventId": "AAA=", "source": "microsoft365", "eventType": "email.received", "externalRecordId": "AAA=", "occurredAt": "x", "data": {"from": "a@b.nz"}}
    assert runtime.ingest(PK, "microsoft365", [ev, ev]) == 1
    assert runtime.ingest(PK, "microsoft365", [ev]) == 0 and sent == ["AAA="]


def test_execute_is_idempotent_and_retryable_after_failure(fake, net, secrets_store, env):
    runtime._save_conn(PK, {**runtime.conn_key(PK, "xero"), "provider": "xero", "status": "connected", "externalId": "org"})
    secrets_store[(PK, "xero")] = {"access_token": "a", "refresh_token": "r", "expires_at": NOW + 3000}
    guid = "11111111-2222-3333-4444-555555555555"
    net.on("PUT", f"https://api.xero.com/api.xro/2.0/Invoices/{guid}/History", status=500)
    with pytest.raises(http.HttpError):
        runtime.execute(PK, "xero", "add_history_note", {"invoiceId": guid, "text": "x"}, "k1", NOW)
    net.routes.clear()
    net.on("PUT", f"https://api.xero.com/api.xro/2.0/Invoices/{guid}/History", body={})
    assert runtime.execute(PK, "xero", "add_history_note", {"invoiceId": guid, "text": "x"}, "k1", NOW) == {"noted": True}
    n = len(net.calls)
    again = runtime.execute(PK, "xero", "add_history_note", {"invoiceId": guid, "text": "x"}, "k1", NOW)
    assert again["duplicate"] is True and len(net.calls) == n  # no second external write
    with pytest.raises(ValueError):
        runtime.execute(PK, "xero", "delete_invoice", {}, "k2")


def test_xero_rejects_non_guid_invoice_ids(net):
    with pytest.raises(ValueError):
        Xero().execute({"access_token": "t"}, {"externalId": "o"}, "add_history_note", {"invoiceId": "../Contacts", "text": "x"})


# ---------------- Xero ----------------
CID = "cccccccc-0000-0000-0000-000000000001"


def xinv(i, status="AUTHORISED", due="2026-11-01", due_amt=230.0, cid=CID):
    return {"InvoiceID": i, "InvoiceNumber": f"INV-{i[:2]}", "Status": status, "Total": 230.0, "AmountDue": due_amt, "CurrencyCode": "NZD",
            "DueDateString": f"{due}T00:00:00", "DateString": "2026-10-01T00:00:00", "Contact": {"ContactID": cid, "Name": "Acme Ltd"}}


G1, G2 = "aaaaaaaa-0000-0000-0000-000000000001", "aaaaaaaa-0000-0000-0000-000000000002"


def test_xero_first_pull_reads_outstanding_only_with_contact_emails_and_snapshot(net):
    net.on("GET", "https://api.xero.com/api.xro/2.0/Invoices", body={"Invoices": [xinv(G1), xinv(G2, due="2026-12-30")]})
    net.on("GET", "https://api.xero.com/api.xro/2.0/Contacts", body={"Contacts": [{"ContactID": CID, "EmailAddress": "ap@acme.nz"}]})
    evs, cp, _ = Xero().pull({"access_token": "t"}, {"externalId": "org", "checkpoint": {}}, False, now=NOW)
    inv = [e for e in evs if e["eventType"] == "invoice.updated"]
    assert inv[0]["data"]["contactEmail"] == "ap@acme.nz" and inv[0]["data"]["amountDue"] == 230.0
    assert [e for e in evs if e["eventType"] == "invoice.snapshot"][0]["data"]["outstandingIds"] == [G1, G2]
    q = urllib.parse.unquote(net.calls[0][1])
    assert "Statuses=AUTHORISED&" in q and "if-modified-since" not in {k.lower() for k in net.calls[0][2]}
    assert "modifiedAfter" in cp
    # incremental pull sends If-Modified-Since and asks for paid/voided too
    net.calls.clear()
    Xero().pull({"access_token": "t"}, {"externalId": "org", "checkpoint": cp}, False, now=NOW + 900)
    assert "PAID" in urllib.parse.unquote(net.calls[0][1]) and "If-modified-since" in net.calls[0][2]


def test_xero_webhook_signature_is_verified_in_constant_time(env):
    body = b'{"events":[]}'
    sig = base64.b64encode(hmac.new(b"whkey", body, hashlib.sha256).digest()).decode()
    x = Xero()
    assert x.verify_webhook({"X-Xero-Signature": sig}, body, {}, None)[0]
    assert not x.verify_webhook({"X-Xero-Signature": sig}, body + b" ", {}, None)[0]
    assert not x.verify_webhook({}, body, {}, None)[0]


# ---------------- invoices ----------------
def inv_event(i=G1, status="AUTHORISED", due="2026-11-01", amt=230.0, email="ap@acme.nz"):
    return {"invoiceId": i, "number": "INV-01", "contactName": "Acme Ltd", "contactEmail": email, "status": status, "total": 230.0,
            "amountDue": amt, "currency": "NZD", "dueDate": due, "date": "2026-10-01"}


def reminders():
    return [t for t in tasks.list_tasks(PK) if t["type"] == "invoice_reminder"]


def test_overdue_invoice_creates_one_gentle_reminder_for_approval(fake):
    fake.seed({"PK": PK, "SK": "META", "name": "SparkClean", "timezone": "Pacific/Auckland"})
    invoices.process(PK, inv_event(due="2026-11-10"), NOW)  # 6 days overdue
    invoices.process(PK, inv_event(due="2026-11-10"), NOW)
    [t] = reminders()
    assert t["bucket"] == "gentle" and t["status"] == "needs_approval" and "$230.00" in t["draft"] and "INV-01" in t["draft"]
    assert "late fee" not in t["draft"].lower() and "penalt" not in t["draft"].lower()


def test_escalation_supersedes_the_milder_reminder_and_final_is_never_automatic(fake):
    fake.seed({"PK": PK, "SK": "META", "name": "SparkClean", "timezone": "Pacific/Auckland"},
              {"PK": PK, "SK": "POLICY", "modes": {"invoice_reminder": "automate"}})
    invoices.process(PK, inv_event(due="2026-11-10"), NOW)                      # gentle -> automatic (no real mail: simulated)
    invoices.process(PK, inv_event(due="2026-09-01"), NOW)                      # 76 days: final
    final = [t for t in tasks.list_tasks(PK) if t.get("bucket") == "final"][0]
    assert final["status"] == "needs_approval" and final["priority"] == "urgent"
    assert tasks.get(PK, "inv-" + G1 + "-gentle")["status"] == "done"  # the gentle one had been sent automatically


def test_paid_invoice_closes_open_reminders_and_is_counted(fake):
    fake.seed({"PK": PK, "SK": "META", "name": "S"})
    invoices.process(PK, inv_event(due="2026-11-10"), NOW)
    invoices.process(PK, inv_event(status="PAID", amt=0), NOW + 60)
    assert reminders()[0]["status"] == "done"
    assert any(i.get("kind") == "invoice_paid" and i["meta"]["afterReminder"] for i in fake.items.values())


def test_snapshot_closes_reminders_for_invoices_no_longer_outstanding(fake):
    fake.seed({"PK": PK, "SK": "META", "name": "S"})
    invoices.process(PK, inv_event(G1, due="2026-11-10"), NOW)
    invoices.process(PK, inv_event(G2, due="2026-11-10"), NOW)
    assert invoices.snapshot(PK, [G2]) == 1
    assert {t["invoiceId"]: t["status"] for t in reminders()} == {G1: "done", G2: "needs_approval"}


def test_not_yet_overdue_creates_no_task_and_paused_creates_none(fake):
    invoices.process(PK, inv_event(due="2026-12-30"), NOW)
    assert reminders() == []
    fake.seed({"PK": PK, "SK": "POLICY", "paused": {"invoice_reminder": True}})
    invoices.process(PK, inv_event(due="2026-11-01"), NOW)
    assert reminders() == []
