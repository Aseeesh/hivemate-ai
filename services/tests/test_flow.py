"""End-to-end scenario over the real modules (fake table, no AWS): enquiry -> reply -> silence -> follow-up -> recovery -> measured impact."""
import json
import time

import pytest

from src.api import handler, workqueue
from src.common import events, mailer, policy
from src.common.context import Ctx
from src.pipeline import deals, followups, impact, tasks
from src.plugins.email import processor

PK = "TENANT#a1"
CTX = Ctx("a1", "u1", "admin", "owner@spark.nz")
T0 = 1_794_776_400  # Monday 10:00 NZ


@pytest.fixture(autouse=True)
def base(fake, monkeypatch):
    fake.seed({"PK": PK, "SK": "META", "name": "SparkClean", "timezone": "Pacific/Auckland"})
    monkeypatch.setattr(mailer, "enabled", lambda: False)
    monkeypatch.setattr("src.connectors.runtime.try_send_mail", lambda *a, **k: None)


def test_lead_recovery_story(fake):
    # 1. an email enquiry arrives and the AI drafts a reply
    processor.track(PK, {"from": "Jo@Client.nz", "fromName": "Jo", "subject": "Quote for office clean"}, "m1", "PENDING_APPROVAL", True)
    # (track uses the real clock, so rebuild the story on the deal's own timeline)
    did = deals.email_deal_id("jo@client.nz")
    d = deals.get(PK, did)
    assert d["awaiting"] == "business" and d["need"] == "Quote for office clean"
    # 2. the owner approves the reply 30 minutes later, which starts the follow-up clock
    t_reply = int(d["createdAt"]) + 1800
    deals.on_outbound(PK, did, "approved_draft", t_reply)
    # 3. silence for a day: a follow-up draft appears
    followups.sweep(t_reply + 86400 + 5)
    [task] = [t for t in tasks.list_tasks(PK) if t["type"] == "follow_up"]
    assert task["status"] == "needs_approval" and task["to"] == "jo@client.nz"
    # 4. the owner approves it from the work queue
    assert workqueue.route(CTX, "POST", f"/work/{task['taskId']}/approve", {}, {})["statusCode"] == 200
    # 5. the customer replies: recovered
    deals.on_inbound(PK, did, "email", "m2", t_reply + 3 * 86400, name="Jo", email="jo@client.nz")
    # 6. the numbers come from events
    evs = events.since(PK, 0)
    m = impact.compute(evs, deals.list_deals(PK), policy.get(PK), time.time() + 5 * 86400, 90)["measured"]
    assert m["leadsRecovered"] == 1 and m["medianResponseSeconds"] == 1800 and m["followUpsDue"] == 1 and m["executionsOk"] == 1
    assert m["manualInterventions"] >= 1 and m["enquiries"] == 1


def api_event(method, path, body=None):
    claims = {"custom:tenantId": "a1", "sub": "u1", "email": "owner@spark.nz", "custom:role": "admin"}
    return {"requestContext": {"http": {"method": method}, "authorizer": {"jwt": {"claims": claims}}}, "rawPath": path, "body": json.dumps(body) if body else None}


def test_approving_an_outlook_enquiry_replies_from_their_mailbox_and_starts_the_follow_up_clock(fake, monkeypatch):
    sent = []
    monkeypatch.setattr("src.connectors.runtime.try_send_mail", lambda pk, to, subj, body, idem_key: sent.append((to, subj, idem_key)) or "microsoft365")
    fake.seed({"PK": PK, "SK": "MSG#abc123", "from": "al@x.nz", "subject": "Hours?", "body": "?", "draftReply": "We open at 8.", "status": "PENDING_APPROVAL", "source": "microsoft365"})
    deals.on_inbound(PK, deals.email_deal_id("al@x.nz"), "email", "abc123", int(time.time()) - 600, email="al@x.nz")
    r = handler.handler(api_event("POST", "/messages/abc123/approve"), None)
    assert r["statusCode"] == 200 and json.loads(r["body"])["status"] == "SENT"
    assert sent == [("al@x.nz", "Hours?", "msg-abc123")]
    d = deals.get(PK, deals.email_deal_id("al@x.nz"))
    assert d["awaiting"] == "customer" and d["stage"] == "responded"


def test_a_pipeline_fault_never_breaks_the_customer_chat_hook(fake, monkeypatch):
    from src.plugins.conversation import agent
    monkeypatch.setattr(agent.deals, "on_chat_turn", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    agent.track(PK, "c1", "web", "web:1", {"name": "Jo"}, False)  # must not raise
    monkeypatch.setattr("src.pipeline.deals.on_email", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    processor.track(PK, {"from": "a@b.nz", "subject": "s"}, "m", "SENT", True)  # must not raise
