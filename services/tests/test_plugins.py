import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))
os.environ["MANIFEST_DIR"] = os.path.join(os.path.dirname(__file__), "../manifests")

from services.src.common import plugins  # noqa: E402


def test_registry_loads_email_plugin():
    assert "email-automation" in plugins.registry()


def test_defaults_applied():
    m = plugins.registry()["email-automation"]
    cfg = plugins.validate_config(m, {})
    assert cfg["approvalRequired"] is True and cfg["confidenceThreshold"] == 0.8


def test_unknown_key_rejected():
    with pytest.raises(ValueError):
        plugins.validate_config(plugins.registry()["email-automation"], {"evil": 1})


def test_bool_is_not_a_number():
    with pytest.raises(ValueError):
        plugins.validate_config(plugins.registry()["email-automation"], {"confidenceThreshold": True})


def test_document_names_cannot_escape_tenant_prefix():
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from src.api import documents
    assert documents.safe_name("../../tenants/other/docs/secret.pdf") == "secret.pdf"
    assert documents.safe_name("my faq (v2).txt") == "my_faq__v2_.txt"
    with pytest.raises(ValueError):
        documents.safe_name("malware.exe")
