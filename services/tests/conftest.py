import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))
os.environ.setdefault("AWS_DEFAULT_REGION", "ap-southeast-2")
os.environ.setdefault("TABLE_NAME", "test")

# A test that compares a fixed date with the real clock passes today and fails later. CI runs the suite a second time with
# the clock pushed forward (HIVEMATE_TEST_CLOCK_SHIFT_DAYS) so that kind of test fails immediately instead of weeks later.
_shift = float(os.environ.get("HIVEMATE_TEST_CLOCK_SHIFT_DAYS", "0")) * 86400
if _shift:
    import time as _time
    _real_time = _time.time
    _time.time = lambda: _real_time() + _shift

from fakedb import FakeTable  # noqa: E402
from src.common import db  # noqa: E402


@pytest.fixture
def fake(monkeypatch):
    t = FakeTable()
    monkeypatch.setattr(db, "table", lambda: t)
    return t
