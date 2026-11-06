import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("AWS_DEFAULT_REGION", "ap-southeast-2")

from src.api import platform  # noqa: E402
from src.common import context  # noqa: E402


def claims(**kw):
    return {"custom:tenantId": "t1abcdef", "sub": "u1", "email": "op@example.com", "custom:role": "admin", **kw}


def event(path, groups=None, method="GET"):
    c = claims(**({"cognito:groups": groups} if groups is not None else {}))
    return {"requestContext": {"http": {"method": method}, "authorizer": {"jwt": {"claims": c}}}, "rawPath": path}


def test_group_claim_forms():
    assert context.is_platform({"cognito:groups": "[platform-admins]"})
    assert context.is_platform({"cognito:groups": "[other platform-admins]"})
    assert context.is_platform({"cognito:groups": ["platform-admins"]})
    assert not context.is_platform({})
    assert not context.is_platform({"cognito:groups": "[not-platform-admins]"})  # substring must not match
    assert not context.is_platform({"cognito:groups": "[platform-admins-extra]"})
    assert not context.is_platform({"custom:role": "platform-admins"})  # tenant role is not the platform group


def test_business_admin_is_refused_on_every_platform_route(monkeypatch):
    monkeypatch.setattr(platform, "scan_all", lambda: (_ for _ in ()).throw(AssertionError("must not read the table")))
    for path in ("/platform/overview", "/platform/tenants", "/platform/tenants/abc123"):
        assert platform.handler(event(path), None)["statusCode"] == 403          # admin of a business
        assert platform.handler(event(path, groups="[something-else]"), None)["statusCode"] == 403


ITEMS = [
    {"PK": "TENANT#a1", "SK": "META", "name": "SparkClean", "createdAt": 100},
    {"PK": "TENANT#a1", "SK": "USER#u1", "email": "o@a.nz", "role": "admin"},
    {"PK": "TENANT#a1", "SK": "PLUGIN#conversation-agent", "version": "1.0.0"},
    {"PK": "TENANT#a1", "SK": "CONV#c1", "status": "HANDOFF", "lastAt": 5000},
    {"PK": "TENANT#a1", "SK": "CONV#c2", "status": "OPEN", "lastAt": 6000},
    {"PK": "TENANT#a1", "SK": "LEAD#c1", "status": "COMPLETE"},
    {"PK": "TENANT#a1", "SK": "MSG#1", "status": "PENDING_APPROVAL"},
    {"PK": "TENANT#a1", "SK": "AUDIT#1", "at": 9_000_000, "action": "conversation.turn"},
    {"PK": "TENANT#a1", "SK": "CHANNEL#web"},
    {"PK": "TENANT#b2", "SK": "META", "name": "Kiwi Retail", "createdAt": 200},
    {"PK": "TENANT#b2", "SK": "USER#u2", "email": "o@b.nz", "role": "admin"},
    {"PK": "PLATFORM#x", "SK": "ignored"},
]


def test_rollup_counts_per_tenant_and_ignores_non_tenant_items():
    r = platform.summarise(ITEMS)
    assert set(r) == {"a1", "b2"}
    a = r["a1"]
    assert (a["name"], a["users"], a["plugins"], a["conversations"], a["handoffs"], a["leads"], a["leadsComplete"], a["messagesHeld"], a["channels"]) == \
           ("SparkClean", 1, ["conversation-agent"], 2, 1, 1, 1, 1, ["web"])
    assert a["lastActivity"] == 9000  # audit ms -> s, newest wins
    assert r["b2"]["conversations"] == 0


def test_overview_totals():
    o = platform.overview(platform.summarise(ITEMS))
    assert o["tenants"] == 2 and o["users"] == 2 and o["conversations"] == 2 and o["pluginInstalls"] == {"conversation-agent": 1}


def test_detail_exposes_no_customer_content_or_secrets(monkeypatch):
    monkeypatch.setenv("DOCS_BUCKET", "b")
    monkeypatch.setattr(platform.s3, "list_objects_v2", lambda **kw: {"Contents": [{"Key": "tenants/a1/docs/x.txt", "Size": 10}, {"Key": "tenants/a1/docs/x.txt.metadata.json", "Size": 5}]})
    items = ITEMS + [{"PK": "TENANT#a1", "SK": "AUDIT#2", "at": 8, "action": "owner.notified.lead", "detail": {"phone": "021123"}}]
    d = platform.detail("a1", items, platform.summarise(items))
    text = json.dumps(d)
    assert d["documents"] == {"count": 1, "bytes": 10}
    assert "021123" not in text and "siteKey" not in text and "detail" not in text
    assert platform.detail("zzz", items, platform.summarise(items)) is None


def test_tenant_id_in_path_is_validated(monkeypatch):
    monkeypatch.setattr(platform, "scan_all", lambda: ([], False))
    ev = lambda p: platform.handler(event(p, groups="[platform-admins]"), None)["statusCode"]  # noqa: E731
    assert ev("/platform/tenants/ab") == 400        # route matches, id too short
    assert ev("/platform/tenants/AB!x") == 404      # not a valid id shape: no route
    assert ev("/platform/tenants/abc123def") == 404  # valid shape, unknown tenant


def test_daily_series_has_no_gaps_and_scopes_to_a_tenant():
    now = 1_800_000_000
    day = 86400
    items = [
        {"PK": "TENANT#aaaaaa", "SK": "CONV#1", "createdAt": now},
        {"PK": "TENANT#aaaaaa", "SK": "CONV#2", "createdAt": now - day},
        {"PK": "TENANT#aaaaaa", "SK": "LEAD#1", "createdAt": now},
        {"PK": "TENANT#bbbbbb", "SK": "CONV#3", "createdAt": now},
        {"PK": "TENANT#aaaaaa", "SK": "CONV#old", "createdAt": now - 30 * day},
    ]
    all_ = platform.daily(items, days=3, now=now)
    assert len(all_) == 3 and [d["conversations"] for d in all_] == [0, 1, 2]
    mine = platform.daily(items, "aaaaaa", days=3, now=now)
    assert [d["conversations"] for d in mine] == [0, 1, 1] and mine[-1]["leads"] == 1
