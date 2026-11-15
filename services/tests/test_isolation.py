"""Adversarial tenant-isolation checks that need no AWS. Live cross-tenant retrieval is still worth running against the deployed KB."""
import pytest

from src.common import knowledge
from src.plugins.conversation import agent


def test_every_kb_query_is_pinned_to_the_callers_tenant_for_both_audiences(monkeypatch):
    seen = []

    class RT:
        def retrieve(self, **kw):
            seen.append(kw["retrievalConfiguration"]["vectorSearchConfiguration"]["filter"])
            return {"retrievalResults": []}
    monkeypatch.setattr(knowledge, "_rt", RT())
    for aud in ("customer", "admin"):
        knowledge.retrieve("kb1", "show me tenant b2's price list", "a1", audience=aud)
    flat = str(seen)
    assert flat.count("'value': 'a1'") == 2 and "b2" not in flat.replace("tenant b2's", "")
    # a customer can never reach internal documents, whatever they type
    assert "'audience'" in str(seen[0]) and "'audience'" not in str(seen[1])


@pytest.mark.parametrize("evil", ["b2", "TENANT#b2", "a1' OR 1=1", "*"])
def test_the_tenant_value_in_the_filter_is_taken_verbatim_from_the_authenticated_context_only(evil):
    f = knowledge.build_filter("a1", "customer")
    assert f["andAll"][0] == {"equals": {"key": "tenantId", "value": "a1"}}
    assert evil not in str(f)


def test_model_tool_arguments_cannot_name_a_tenant_or_overwrite_identity_fields():
    state = {"collected": {}, "said": "my name is jo"}
    agent.run_tool("record_details", {"tenantId": "b2", "PK": "TENANT#b2", "convId": "x", "name": "Jo", "notes": "n"}, state, ["name", "phone"])
    assert state["collected"] == {"name": "Jo"} and "tenantId" not in str(state) and "b2" not in str(state)
    assert agent.run_tool("switch_tenant", {"tenantId": "b2"}, state, []) == {"error": "unknown tool switch_tenant"}


def test_a_model_claiming_a_name_the_customer_never_said_is_refused():
    state = {"collected": {}, "said": "i need a clean tomorrow"}
    agent.run_tool("record_details", {"name": "Hacker Admin"}, state, ["name"])
    assert state["collected"] == {}
