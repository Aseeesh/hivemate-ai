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
