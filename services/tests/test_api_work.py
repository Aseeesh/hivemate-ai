import json

import pytest

from src.api import workqueue
from src.channels import webhooks
from src.common import events, mailer, policy
from src.common.context import Ctx, Forbidden
from src.connectors import runtime
from src.pipeline import ask, deals, followups, impact, inbox, tasks

PK = "TENANT#a1"
OTHER = "TENANT#b2"
NOW = 1_794_776_400
ADMIN = Ctx("a1", "u1", "admin", "owner@spark.nz")
MEMBER = Ctx("a1", "u2", "member", "staff@spark.nz")


@pytest.fixture(autouse=True)
def base(fake, monkeypatch):
    fake.seed({"PK": PK, "SK": "META", "name": "SparkClean", "timezone": "Pacific/Auckland"},
              {"PK": PK, "SK": "USER#u1", "email": "owner@spark.nz", "role": "admin"}, {"PK": PK, "SK": "USER#u2", "email": "staff@spark.nz", "role": "member"})
    monkeypatch.setattr(mailer, "enabled", lambda: False)
    monkeypatch.setattr("src.connectors.runtime.try_send_mail", lambda *a, **k: None)


def call(ctx, method, path, body=None, query=None):
    return workqueue.route(ctx, method, path, body or {}, query or {})


def make_follow_up():
    deals.on_inbound(PK, "d1", "email", "m1", NOW, name="Jo Smith", email="jo@x.nz", need="deep clean", channel="email")
    deals.on_outbound(PK, "d1", "assistant", NOW + 60)
    followups.sweep(NOW + 60 + 86400 + 1)
    return tasks.list_tasks(PK)[0]


def test_work_list_shows_open_tasks_with_summary_and_filters(fake):
    t = make_follow_up()
    r = call(ADMIN, "GET", "/work")
    assert r["statusCode"] == 200 and r["body"]["tasks"][0]["taskId"] == t["taskId"] and r["body"]["summary"]["needsApproval"] == 1
    assert call(ADMIN, "GET", "/work", query={"type": "invoice_reminder"})["body"]["tasks"] == []
    assert call(ADMIN, "GET", "/work", query={"channel": "email"})["body"]["tasks"][0]["taskId"] == t["taskId"]


def test_approve_sends_edited_text_once_and_second_click_is_a_conflict(fake):
    t = make_follow_up()
    assert call(MEMBER, "POST", f"/work/{t['taskId']}/approve", {"text": "Edited by staff"})["statusCode"] == 200
    assert tasks.get(PK, t["taskId"])["finalText"] == "Edited by staff"
    assert call(MEMBER, "POST", f"/work/{t['taskId']}/approve")["statusCode"] == 409
    assert call(ADMIN, "GET", "/work")["body"]["tasks"] == []


def test_approving_a_task_without_an_email_is_a_clear_error_not_a_crash(fake):
    deals.on_inbound(PK, "d9", "chat", "c", NOW, name="Cy", phone="021 123 456")
    deals.on_outbound(PK, "d9", "assistant", NOW + 5)
    followups.sweep(NOW + 5 + 86400 + 1)
    t = tasks.list_tasks(PK)[0]
    r = call(ADMIN, "POST", f"/work/{t['taskId']}/approve")
    assert r["statusCode"] == 422 and "email" in r["body"]["error"]
    assert call(ADMIN, "POST", f"/work/{t['taskId']}/done")["statusCode"] == 200  # contacted them another way


def test_reject_dismisses_and_does_not_reschedule_that_follow_up(fake):
    t = make_follow_up()
    assert call(ADMIN, "POST", f"/work/{t['taskId']}/reject")["statusCode"] == 200
    assert tasks.get(PK, t["taskId"])["status"] == "dismissed"
    assert call(ADMIN, "POST", f"/work/{t['taskId']}/reject")["statusCode"] == 409


def test_marking_done_by_hand_counts_as_a_reply_and_restarts_the_clock(fake):
    t = make_follow_up()
    call(ADMIN, "POST", f"/work/{t['taskId']}/done")
    d = deals.get(PK, "d1")
    import time
    assert d["awaiting"] == "customer" and d["nextDueAt"] > time.time() + 23 * 3600
    kinds = [i["kind"] for i in fake.items.values() if "kind" in i]
    assert "follow_up_manual" in kinds


def test_snooze_hides_until_later_and_validates_hours(fake):
    t = make_follow_up()
    assert call(ADMIN, "POST", f"/work/{t['taskId']}/snooze", {"hours": 0})["statusCode"] == 400
    assert call(ADMIN, "POST", f"/work/{t['taskId']}/snooze", {"hours": True})["statusCode"] == 400
    assert call(ADMIN, "POST", f"/work/{t['taskId']}/snooze", {"hours": 48})["statusCode"] == 200
    assert call(ADMIN, "GET", "/work")["body"]["tasks"] == []


def test_assign_only_to_members_of_this_business(fake):
    t = make_follow_up()
    assert call(ADMIN, "POST", f"/work/{t['taskId']}/assign", {"assignee": "staff@spark.nz"})["statusCode"] == 200
    assert call(ADMIN, "GET", "/work", query={"assignee": "staff@spark.nz"})["body"]["tasks"][0]["taskId"] == t["taskId"]
    assert call(ADMIN, "POST", f"/work/{t['taskId']}/assign", {"assignee": "stranger@evil.com"})["statusCode"] == 400


def test_policy_roundtrip_admin_only_and_safety_enforced(fake):
    assert call(MEMBER, "GET", "/policy")["body"]["modes"]["follow_up"] == "approve"
    with pytest.raises(Forbidden):
        call(MEMBER, "PUT", "/policy", {"modes": {"follow_up": "automate"}})
    assert call(ADMIN, "PUT", "/policy", {"modes": {"follow_up": "automate"}, "paused": {"invoice_reminder": True}})["body"]["modes"]["follow_up"] == "automate"
    with pytest.raises(ValueError):
        call(ADMIN, "PUT", "/policy", {"modes": {"refund": "automate"}})


def test_stage_change_to_won_closes_open_follow_ups(fake):
    t = make_follow_up()
    assert call(ADMIN, "POST", "/deals/d1/stage", {"stage": "won"})["statusCode"] == 200
    assert tasks.get(PK, t["taskId"])["status"] == "done"
    assert call(ADMIN, "POST", "/deals/nope-x/stage", {"stage": "won"})["statusCode"] == 404
    assert call(ADMIN, "GET", "/deals")["body"]["counts"]["won"] == 1


def test_unknown_routes_fall_through():
    assert call(ADMIN, "GET", "/nothing") is None


# ---------------- tenant isolation (adversarial) ----------------
def test_a_forged_tenant_in_the_body_or_query_never_reaches_another_tenants_data(fake):
    deals.on_inbound(OTHER, "secret1", "email", "m", NOW, name="Victim", email="v@b2.nz")
    fake.seed({"PK": OTHER, "SK": "TASK#t-secret", "taskId": "t-secret", "type": "follow_up", "status": "needs_approval", "priority": "normal", "createdAt": 1, "dueAt": 1, "draft": "x", "to": "v@b2.nz"})
    evil = {"tenantId": "b2", "pk": OTHER, "PK": OTHER, "assignee": "x"}
    for path, method in (("/work", "GET"), ("/deals", "GET"), ("/inbox", "GET"), ("/impact", "GET")):
        r = call(ADMIN, method, path, evil, {"tenantId": "b2", "pk": OTHER})
        assert "Victim" not in json.dumps(r["body"]) and "t-secret" not in json.dumps(r["body"])
    assert call(ADMIN, "POST", "/work/t-secret/approve", evil)["statusCode"] == 404
    assert call(ADMIN, "POST", "/deals/secret1/stage", {"stage": "won", **evil})["statusCode"] == 404
    assert deals.get(OTHER, "secret1")["stage"] == "new"


def test_every_write_from_the_api_stays_inside_the_callers_partition(fake):
    make_follow_up()
    t = tasks.list_tasks(PK)[0]
    before = {k for k in fake.items if k[0] != PK}
    for path, body in ((f"/work/{t['taskId']}/approve", {}), ("/deals/d1/stage", {"stage": "quote_sent"}), ("/policy", {"modes": {"follow_up": "assist"}})):
        call(ADMIN, "POST" if "policy" not in path else "PUT", path, body)
    assert {k for k in fake.items if k[0] != PK} == before


# ---------------- impact ----------------
def ev(kind, at, **meta):
    return {"kind": kind, "at": int(at * 1000), "meta": meta, "dealId": "d"}


def test_impact_is_computed_from_events_and_separates_estimated_from_measured():
    evs = [ev("enquiry_received", NOW - 100), ev("enquiry_received", NOW - 90),
           ev("first_response", NOW - 80, seconds=600), ev("first_response", NOW - 70, seconds=7200),
           ev("follow_up_due", NOW - 60), ev("follow_up_due", NOW - 59), ev("follow_up_drafted", NOW - 58, action="follow_up"),
           ev("follow_up_drafted", NOW - 57, action="quote_follow_up"), ev("follow_up_sent", NOW - 56), ev("send_failed", NOW - 55),
           ev("lead_recovered", NOW - 50), ev("lead_cold", NOW - 49), ev("approval_completed", NOW - 48), ev("follow_up_manual", NOW - 47),
           ev("follow_up_drafted", NOW - 99 * 86400, action="follow_up")]  # outside the window
    m = impact.compute(evs, [], policy.DEFAULTS, NOW, 30)
    me, es = m["measured"], m["estimated"]
    assert me["enquiries"] == 2 and me["medianResponseSeconds"] == 3900 and me["respondedWithinHourPct"] == 50
    assert me["followUpsDue"] == 2 and me["followUpsActioned"] == 2 and me["followUpRatePct"] == 100
    assert me["leadsRecovered"] == 1 and me["recoveryRatePct"] == 50
    assert me["executionsOk"] == 1 and me["executionsFailed"] == 1 and me["executionSuccessPct"] == 50
    assert me["manualInterventions"] == 2
    assert es["minutesSaved"] == 5 + 8 and es["basis"][0]["minutesEach"] in (5, 8)  # 1 follow_up + 1 quote_follow_up
    assert "costPerTask" in m["notMeasured"] and "financial" in es["note"]


def test_owner_minutes_assumption_changes_the_estimate_not_the_measurements():
    evs = [ev("follow_up_drafted", NOW - 10, action="follow_up")] * 3
    p = policy.merge({"minutes": {"follow_up": 10}})
    assert impact.compute(evs, [], p, NOW, 30)["estimated"]["minutesSaved"] == 30
    assert impact.compute(evs, [], policy.DEFAULTS, NOW, 30)["estimated"]["minutesSaved"] == 15


def test_impact_with_no_events_has_nulls_not_invented_numbers():
    m = impact.compute([], [], policy.DEFAULTS, NOW, 30)["measured"]
    assert m["medianResponseSeconds"] is None and m["followUpRatePct"] is None and m["recoveryRatePct"] is None


def test_events_since_reads_only_the_window(fake):
    events.record(PK, "enquiry_received", "d", at=NOW - 10 * 86400)
    events.record(PK, "enquiry_received", "d", at=NOW - 100)
    events.record(OTHER, "enquiry_received", "d", at=NOW - 50)
    assert len(events.since(PK, NOW - 86400)) == 1


# ---------------- ask ----------------
def data(fake_msgs=(), inv=()):
    return {"events": [ev("enquiry_received", NOW - 100), ev("enquiry_received", NOW - 200)], "policy": policy.DEFAULTS, "msgs": list(fake_msgs), "invoices": list(inv),
            "deals": [{"dealId": "d1", "name": "Jo", "awaiting": "business", "stage": "new", "createdAt": NOW - 50},
                      {"dealId": "d2", "name": "Al", "awaiting": "customer", "stage": "responded", "createdAt": NOW - 60}]}


def test_ask_answers_with_calculation_and_sources():
    a = ask.answer("How many enquiries did we get this month?", data(), NOW)
    assert a["supported"] and a["answer"].startswith("2 enquiries") and a["calculation"] and len(a["sources"]) == 2
    a = ask.answer("Which customers haven't received a reply?", data(), NOW)
    assert "Jo" in a["answer"] and "Al" not in a["answer"] and a["sources"][0]["id"] == "d1"
    inv = [{"SK": "XINV#1", "amountDue": 100.5, "daysOverdue": 5, "number": "INV-1", "contactName": "Acme"}, {"SK": "XINV#2", "amountDue": 0, "daysOverdue": 9}]
    a = ask.answer("How many invoices are overdue?", data(inv=inv), NOW)
    assert "1 overdue invoices totalling $100.50" in a["answer"] and a["sources"][0]["id"] == "1"
    msgs = [{"SK": "MSG#1", "category": "complaint", "subject": "Late"}, {"SK": "MSG#2", "category": "faq", "subject": "Hours"}]
    assert ask.answer("What are the main customer complaints?", data(msgs), NOW)["answer"].startswith("1 emails")


def test_ask_refuses_to_guess_unsupported_questions():
    a = ask.answer("Will revenue double next year?", data(), NOW)
    assert a["supported"] is False and a["examples"] and not a["sources"]


# ---------------- inbox ----------------
def test_unified_inbox_merges_channels_and_flags_unanswered():
    convs = [{"convId": "c1", "channel": "web", "status": "HANDOFF", "collected": {"name": "Jo"}, "lastAt": 50}]
    msgs = [{"SK": "MSG#m1", "from": "al@x.nz", "subject": "Quote?", "status": "PENDING_APPROVAL", "category": "pricing", "createdAt": 90}]
    drows = [{"dealId": deals.email_deal_id("al@x.nz"), "awaiting": "business", "stage": "new", "assignee": "staff@spark.nz"}]
    rows = inbox.build(convs, msgs, drows, [])
    assert [r["channel"] for r in rows] == ["email", "web"] and rows[0]["assignee"] == "staff@spark.nz" and all(r["unanswered"] for r in rows)
    assert [r["id"] for r in inbox.filter_rows(rows, channel="web")] == ["c1"]
    assert [r["id"] for r in inbox.filter_rows(rows, assignee="staff@spark.nz")] == ["m1"]


# ---------------- webhooks ----------------
def test_webhook_with_bad_signature_is_401_and_changes_nothing(fake, monkeypatch):
    monkeypatch.setenv("XERO_WEBHOOK_KEY", "k")
    called = []
    monkeypatch.setattr(runtime, "request_sync", lambda *a: called.append(a) or True)
    r = webhooks.webhook("xero", {"x-xero-signature": "nope"}, b'{"events":[{"tenantId":"t"}]}', {})
    assert r["statusCode"] == 401 and r["body"] == "" and not called
    assert webhooks.webhook("unknown", {}, b"", {})["statusCode"] == 404


def test_verified_webhook_marks_only_the_matching_business_due(fake, monkeypatch):
    import base64, hashlib, hmac
    monkeypatch.setenv("XERO_WEBHOOK_KEY", "k")
    runtime._save_conn(PK, {**runtime.conn_key(PK, "xero"), "provider": "xero", "status": "connected", "externalId": "org-1", "nextSyncAt": NOW + 9999})
    fake.seed({"PK": PK, "SK": "XMAP#xero", "GSI1PK": "XT#xero#org-1", "GSI1SK": PK})
    body = json.dumps({"events": [{"tenantId": "org-1", "eventCategory": "INVOICE"}, {"tenantId": "unknown-org"}]}).encode()
    sig = base64.b64encode(hmac.new(b"k", body, hashlib.sha256).digest()).decode()
    assert webhooks.webhook("xero", {"x-xero-signature": sig}, body, {})["statusCode"] == 200
    assert runtime.get_conn(PK, "xero")["nextSyncAt"] <= NOW + 9999 and runtime.get_conn(PK, "xero")["nextSyncAt"] < NOW + 9999
    # Xero's "intent to receive" has an empty events list and must still answer 200
    empty = b'{"events":[]}'
    sig2 = base64.b64encode(hmac.new(b"k", empty, hashlib.sha256).digest()).decode()
    assert webhooks.webhook("xero", {"x-xero-signature": sig2}, empty, {})["statusCode"] == 200


def test_graph_validation_handshake_returns_token_as_plain_text(env_ms=None, monkeypatch=None):
    r = webhooks.webhook("microsoft365", {}, b"", {"validationToken": "tok123"})
    assert r["statusCode"] == 200 and r["body"] == "tok123" and r["headers"]["content-type"] == "text/plain"


def test_oauth_callback_never_trusts_a_tenant_in_the_url(fake):
    r = webhooks.oauth_callback("microsoft365", {"code": "c", "state": "forged", "tenantId": "b2"})
    assert r["statusCode"] == 302 and "connect_error" in r["headers"]["location"] and "connected=" not in r["headers"]["location"]
    r = webhooks.oauth_callback("microsoft365", {"error": "access_denied"})
    assert "cancelled" in r["headers"]["location"]
