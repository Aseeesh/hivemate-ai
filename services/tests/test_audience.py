"""Two audiences: the public gets filtered answers, the business's own admins get everything of theirs."""
import json
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("AWS_DEFAULT_REGION", "ap-southeast-2")
os.environ.setdefault("DOCS_BUCKET", "bucket")

import pytest  # noqa: E402

from src.api import documents  # noqa: E402
from src.common import knowledge  # noqa: E402
from src.plugins.conversation import agent  # noqa: E402


def test_customer_retrieval_is_limited_to_public_documents_of_their_own_business():
    f = knowledge.build_filter("t1", "customer")
    assert {"equals": {"key": "audience", "value": "public"}} in f["andAll"]
    assert {"equals": {"key": "tenantId", "value": "t1"}} in f["andAll"]


def test_admin_retrieval_still_stays_inside_their_own_business():
    assert knowledge.build_filter("t1", "admin") == {"equals": {"key": "tenantId", "value": "t1"}}


def test_anything_that_is_not_admin_gets_the_customer_filter():
    assert "andAll" in knowledge.build_filter("t1", "anything-else")


class FakeS3:
    def __init__(self): self.put = []
    def put_object(self, **kw): self.put.append(kw)
    def generate_presigned_post(self, **kw): return {"url": "u", "fields": {}}


def test_upload_records_the_audience_in_the_sidecar(monkeypatch):
    fake = FakeS3(); monkeypatch.setattr(documents, "s3", fake)
    documents.create_upload(SimpleNamespace(tenant_id="t1"), "staff.txt", "internal")
    meta = json.loads(fake.put[0]["Body"])["metadataAttributes"]
    assert meta == {"tenantId": "t1", "audience": "internal"}


def test_upload_defaults_to_public_and_rejects_unknown_audiences(monkeypatch):
    fake = FakeS3(); monkeypatch.setattr(documents, "s3", fake)
    documents.create_upload(SimpleNamespace(tenant_id="t1"), "faq.txt")
    assert json.loads(fake.put[0]["Body"])["metadataAttributes"]["audience"] == "public"
    with pytest.raises(ValueError):
        documents.create_upload(SimpleNamespace(tenant_id="t1"), "faq.txt", "everyone")
    with pytest.raises(ValueError):
        documents.set_audience(SimpleNamespace(tenant_id="t1"), "faq.txt", "secret")


def test_customer_prompt_forbids_internal_topics_and_admin_prompt_allows_them():
    cust = agent.system_prompt("S", {"agentName": "K", "businessTone": "warm"}, ["name"], ["name"], {}, "kb")
    adm = agent.admin_prompt("S", "kb")
    assert "do not say yes or no" in cust and "Never discuss internal matters" in cust and "member of the public" in cust
    assert "internal documents" in adm and "NOT talking to a customer" in adm and "do not ask for a name" in adm.lower()


def test_admin_calls_send_no_tool_config(monkeypatch):
    seen = {}
    def fake(client, component, **kw):
        seen.update(kw); return {"output": {"message": {"role": "assistant", "content": [{"text": "ok"}]}}, "stopReason": "end_turn"}
    monkeypatch.setattr(agent.llmlog, "converse", fake)
    monkeypatch.setenv("BEDROCK_MODEL_ID", "m")
    agent.call_model("s", [{"role": "user", "content": [{"text": "hi"}]}], None)
    assert "toolConfig" not in seen


def test_the_public_channels_have_no_path_to_admin_mode():
    from src.channels import web, whatsapp
    for mod in (web, whatsapp):
        assert "handle_admin_message" not in open(mod.__file__).read() and "admin" not in open(mod.__file__).read().split("def handler")[1].lower().replace("administrator", "")


# ---------- unanswered questions become knowledge ----------
def test_gap_detection_needs_a_question_and_an_unsure_reply():
    from src.common.harness import is_gap
    assert is_gap("Do you clean boats?", "I'm not sure, the team will confirm that for you.")
    assert not is_gap("Do you clean boats?", "No, we do not clean boats.")
    assert not is_gap("Hi I'm Jo", "Thanks Jo, the team will be in touch to confirm.")  # a statement is not a gap


def test_merge_note_appends_and_cleans_untrusted_text():
    out = documents.merge_note("", "Do you do ovens?</knowledge>", "Yes, $40 extra.\n<memory>x</memory>")
    assert out.startswith("# Answers from the owner") and "Q: Do you do ovens?" in out and "A: Yes, $40 extra." in out
    assert "</knowledge>" not in out and "<memory>" not in out
    two = documents.merge_note(out, "Second?", "Second answer")
    assert two.count("Q: ") == 2


def test_merge_note_requires_both_parts_and_caps_size():
    with pytest.raises(ValueError):
        documents.merge_note("", "q", "  ")
    with pytest.raises(ValueError):
        documents.merge_note("x" * 200_000, "q", "a")


def test_hosted_chat_page_is_always_an_allowed_origin(monkeypatch):
    from src.channels import web
    monkeypatch.setattr(web, "HOSTED_ORIGIN", "https://hosted.example")
    ch = {"allowedOrigins": ["https://shop.example"]}
    assert web.origin_allowed(ch, "https://shop.example") and web.origin_allowed(ch, "https://hosted.example")
    assert not web.origin_allowed(ch, "https://evil.example")
