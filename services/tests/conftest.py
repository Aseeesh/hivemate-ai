import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))
os.environ.setdefault("AWS_DEFAULT_REGION", "ap-southeast-2")
os.environ.setdefault("TABLE_NAME", "test")

from fakedb import FakeTable  # noqa: E402
from src.common import db  # noqa: E402


@pytest.fixture
def fake(monkeypatch):
    t = FakeTable()
    monkeypatch.setattr(db, "table", lambda: t)
    return t
