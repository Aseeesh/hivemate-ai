import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("AWS_DEFAULT_REGION", "ap-southeast-2")

from src.channels import whatsapp  # noqa: E402
from src.plugins.conversation import agent  # noqa: E402


def test_field_names_are_sanitised():
    assert agent.clean_fields(["Name", "Phone Number", "evil; drop", "x" * 40], ["a"]) == ["name", "phone_number"]
    assert agent.clean_fields([], ["need"]) == ["need"]
    assert agent.clean_fields(None, ["need"]) == ["need"]


def test_tool_schema_has_one_property_per_field():
    props = agent.tool_config(["name", "suburb"])["tools"][0]["toolSpec"]["inputSchema"]["json"]["properties"]
    assert set(props) == {"name", "suburb", "notes"}


def test_system_prompt_lists_missing_and_states_rules():
    p = agent.system_prompt("SparkClean", {"agentName": "Kiri", "businessTone": "warm"}, ["name", "phone"], ["name", "phone"], {"name": "Jo"}, "Open 8-5")
    assert "Still needed: phone" in p and "UNTRUSTED" in p and "Open 8-5" in p and "Kiri" in p


def test_record_details_ignores_unknown_fields_and_non_strings():
    state = {"collected": {}}
    agent.run_tool("record_details", {"name": " Jo ", "password": "x", "phone": 123, "notes": "urgent"}, state, ["name", "phone"])
    assert state["collected"] == {"name": "Jo"} and state["notes"] == "urgent"


def test_handoff_tool_sets_flag():
    state = {"collected": {}}
    agent.run_tool("request_handoff", {"reason": "wants a human"}, state, [])
    assert state["handoff"] == "wants a human"


def test_conversation_ids_are_stable_per_customer():
    assert agent.conv_id_for("whatsapp", "6421000111") == agent.conv_id_for("whatsapp", "6421000111")
    assert agent.conv_id_for("whatsapp", "6421000111") != agent.conv_id_for("whatsapp", "6421000222")


WEBHOOK = {"object": "whatsapp_business_account", "changes": [{"field": "messages", "value": {
    "metadata": {"phone_number_id": "109876543210"},
    "contacts": [{"wa_id": "6421000111", "profile": {"name": "Jo"}}],
    "messages": [{"from": "6421000111", "id": "wamid.A", "type": "text", "text": {"body": "Hi, do you clean offices?"}},
                 {"from": "6421000111", "id": "wamid.B", "type": "image", "image": {"id": "x"}}],
}}]}


def test_whatsapp_parse_extracts_text_only():
    msgs = whatsapp.parse({"whatsAppWebhookEntry": json.dumps(WEBHOOK)})
    assert msgs == [{"phoneNumberId": "109876543210", "from": "6421000111", "id": "wamid.A", "text": "Hi, do you clean offices?", "name": "Jo"}]


def test_whatsapp_parse_ignores_status_updates():
    status = {"changes": [{"value": {"metadata": {"phone_number_id": "1"}, "statuses": [{"id": "x", "status": "read"}]}}]}
    assert whatsapp.parse({"whatsAppWebhookEntry": json.dumps(status)}) == []


def test_reasoning_is_stripped_from_replies():
    assert agent.strip_reasoning("<thinking>they want hours</thinking>\nWe open at 8am.") == "We open at 8am."
    assert agent.strip_reasoning("Hi!<thinking>unclosed reasoning") == "Hi!"
    assert agent.strip_reasoning("<THINKING>x</THINKING>Hello") == "Hello"
    assert agent.strip_reasoning("plain reply") == "plain reply"


def test_transient_model_error_is_retried_once(monkeypatch):
    from botocore.exceptions import ClientError
    calls = []

    def flaky(**kw):
        calls.append(1)
        if len(calls) == 1:
            raise ClientError({"Error": {"Code": "ModelErrorException", "Message": "bad tool sequence"}}, "Converse")
        return {"output": {"message": {"role": "assistant", "content": [{"text": "ok"}]}}, "stopReason": "end_turn"}

    monkeypatch.setattr(agent.bedrock, "converse", flaky)
    monkeypatch.setattr(agent.time, "sleep", lambda _: None)
    os.environ["BEDROCK_MODEL_ID"] = "m"
    assert agent.call_model("s", [], {})["stopReason"] == "end_turn" and len(calls) == 2


def test_non_transient_error_is_not_retried(monkeypatch):
    import pytest
    from botocore.exceptions import ClientError
    calls = []

    def denied(**kw):
        calls.append(1)
        raise ClientError({"Error": {"Code": "AccessDeniedException", "Message": "no"}}, "Converse")

    monkeypatch.setattr(agent.bedrock, "converse", denied)
    os.environ["BEDROCK_MODEL_ID"] = "m"
    with pytest.raises(ClientError):
        agent.call_model("s", [], {})
    assert len(calls) == 1


def test_reasoning_only_reply_is_nudged_once(monkeypatch):
    replies = iter(["<thinking>hmm</thinking>", "Hello Sam!"])

    def fake(**kw):
        return {"output": {"message": {"role": "assistant", "content": [{"text": next(replies)}]}}, "stopReason": "end_turn"}

    monkeypatch.setattr(agent.bedrock, "converse", fake)
    os.environ["BEDROCK_MODEL_ID"] = "m"
    state = {"collected": {}}
    assert agent.converse_loop("s", [], "hi", agent.tool_config(["name"]), state, ["name"]) == "Hello Sam!"


def test_summary_is_built_from_customer_words_only(monkeypatch):
    sent = {}
    monkeypatch.setattr(agent.db, "query_prefix", lambda *a, **k: [
        {"role": "user", "text": "I need a clean in Albany"}, {"role": "assistant", "text": "We'll get your clean sorted"}])

    def fake_converse(**kw):
        sent.update(kw)
        return {"output": {"message": {"content": [{"text": "- wants a clean"}]}}}

    monkeypatch.setattr(agent.bedrock, "converse", fake_converse)
    monkeypatch.setenv("BEDROCK_MODEL_ID", "m")
    assert agent.summarise("TENANT#x", "c1", {}) == "- wants a clean"
    body = sent["messages"][0]["content"][0]["text"]
    assert "Albany" in body and "sorted" not in body
    assert "never write that a booking" in sent["system"][0]["text"]


def test_identifiers_must_be_grounded_in_customer_words():
    said = "hi, i need a clean. i'm sam taylor, 021 123 4567".lower()
    assert agent.accept("name", "Sam Taylor", said)
    assert not agent.accept("name", "Hi", said)           # greeting recorded as a name
    assert not agent.accept("name", "Jordan Smith", said)  # never said
    assert agent.accept("phone", "0211234567", said)       # formatting differs, digits match
    assert not agent.accept("phone", "0219999999", said)
    assert agent.accept("need", "carpet cleaning", said)   # free-text fields are not policed
    assert agent.accept("name", "Anything", None)          # no transcript available: do not block


def test_record_details_drops_ungrounded_name():
    state = {"collected": {}, "said": "hello i need a quote"}
    agent.run_tool("record_details", {"name": "Hello", "need": "a quote"}, state, ["name", "need"])
    assert state["collected"] == {"need": "a quote"}


def test_wrapper_tags_are_stripped_from_replies():
    assert agent.strip_reasoning("<response> Hello there </response>") == "Hello there"
    assert agent.strip_reasoning("<message>Hi</message>") == "Hi"
    assert agent.strip_reasoning("<thinking>x</thinking>Hi") == "Hi"


def test_llm_call_log_has_metadata_but_no_message_text(capsys):
    from src.common import llmlog

    class Fake:
        def converse(self, **kw):
            return {"usage": {"inputTokens": 120, "outputTokens": 40}, "stopReason": "end_turn", "output": {"message": {"content": [{"text": "secret reply"}]}}}

    llmlog.set_tenant("abc123")
    llmlog.converse(Fake(), "conversation", modelId="m", messages=[{"role": "user", "content": [{"text": "my phone is 0211234567"}]}])
    line = capsys.readouterr().out
    rec = json.loads(line)
    assert rec["event"] == "llm_call" and rec["inputTokens"] == 120 and rec["outputTokens"] == 40 and rec["model"] == "m"
    assert "0211234567" not in line and "secret reply" not in line and "abc123" not in line and len(rec["tenant"]) == 10


def test_llm_call_failure_is_logged_and_reraised(capsys):
    import pytest
    from botocore.exceptions import ClientError
    from src.common import llmlog

    class Boom:
        def converse(self, **kw):
            raise ClientError({"Error": {"Code": "ThrottlingException"}}, "Converse")

    with pytest.raises(ClientError):
        llmlog.converse(Boom(), "email", modelId="m")
    assert json.loads(capsys.readouterr().out)["error"] == "ThrottlingException"


def test_resuming_a_handed_off_conversation_updates_its_lead(monkeypatch):
    from src.api import chat

    class FakeTable:
        def __init__(self):
            self.items = {("TENANT#t1", "CONV#abcdef12"): {"status": "HANDOFF"},
                          ("TENANT#t1", "LEAD#abcdef12"): {"status": "HANDOFF", "handoffReason": "refund"}}

        def get_item(self, Key):
            it = self.items.get((Key["PK"], Key["SK"]))
            return {"Item": dict(it)} if it else {}

        def update_item(self, Key, ExpressionAttributeValues, **kw):
            it = self.items[(Key["PK"], Key["SK"])]
            it["status"] = ExpressionAttributeValues[":s"]
            if ":r" in ExpressionAttributeValues:
                it["handoffReason"] = ExpressionAttributeValues[":r"]

    t = FakeTable()
    monkeypatch.setattr(chat.db, "table", lambda: t)
    monkeypatch.setattr(chat.db, "audit", lambda *a, **k: None)
    ev = {"requestContext": {"http": {"method": "POST"}, "authorizer": {"jwt": {"claims": {"custom:tenantId": "t1", "custom:role": "admin", "sub": "u", "email": "a@b.nz"}}}},
          "rawPath": "/conversations/abcdef12/status", "body": json.dumps({"status": "OPEN"})}
    assert chat.handler(ev, None)["statusCode"] == 200
    assert t.items[("TENANT#t1", "CONV#abcdef12")]["status"] == "OPEN"
    assert t.items[("TENANT#t1", "LEAD#abcdef12")] == {"status": "COLLECTING", "handoffReason": ""}
