import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("AWS_DEFAULT_REGION", "ap-southeast-2")

from src.channels import web  # noqa: E402


def test_site_key_shape_is_checked_before_any_lookup(monkeypatch):
    monkeypatch.setattr(web.db, "table", lambda: (_ for _ in ()).throw(AssertionError("must not query")))
    for bad in ("", "abc", "pk_short", "pk_" + "x" * 80, "pk_../../etc/passwd" + "a" * 20, None):
        assert web.tenant_for_key(bad) is None


def test_origin_allow_list():
    assert web.origin_allowed({}, "https://anything.example")
    assert web.origin_allowed({"allowedOrigins": ["https://shop.co.nz"]}, "https://shop.co.nz")
    assert not web.origin_allowed({"allowedOrigins": ["https://shop.co.nz"]}, "https://evil.example")
    assert not web.origin_allowed({"allowedOrigins": ["https://shop.co.nz"]}, "")


def test_visitor_and_tenant_caps(monkeypatch):
    counts = {}

    def fake_bump(pk, sk, ttl):
        counts[sk] = counts.get(sk, 0) + 1
        return counts[sk]

    monkeypatch.setattr(web, "bump", fake_bump)
    for _ in range(web.VISITOR_PER_HOUR):
        assert web.over_limit("TENANT#a", "pk_k", "1.2.3.4") == ""
    assert "quickly" in web.over_limit("TENANT#a", "pk_k", "1.2.3.4")
    assert web.over_limit("TENANT#a", "pk_k", "5.6.7.8") == ""  # another visitor is unaffected


def test_tenant_daily_cap(monkeypatch):
    monkeypatch.setattr(web, "TENANT_PER_DAY", 2)
    day = {}
    monkeypatch.setattr(web, "bump", lambda pk, sk, ttl: day.__setitem__(sk, day.get(sk, 0) + 1) or day[sk])
    assert web.over_limit("TENANT#a", "pk_k", "1.1.1.1") == ""
    assert web.over_limit("TENANT#a", "pk_k", "2.2.2.2") == ""
    assert "busy" in web.over_limit("TENANT#a", "pk_k", "3.3.3.3")


def test_widget_never_uses_innerhtml_and_is_served():
    src = open(web.WIDGET, encoding="utf-8").read()
    assert "innerHTML" not in src and "document.write" not in src and "eval(" not in src
    out = web.handler({"requestContext": {"http": {"method": "GET"}}, "rawPath": "/widget.js"}, None)
    assert out["statusCode"] == 200 and out["headers"]["content-type"].startswith("text/javascript")


def test_unknown_key_is_404_and_leaks_nothing(monkeypatch):
    monkeypatch.setattr(web, "tenant_for_key", lambda k: None)
    ev = {"requestContext": {"http": {"method": "POST", "sourceIp": "1.1.1.1"}}, "rawPath": "/chat", "body": '{"key":"pk_x","message":"hi"}'}
    assert web.handler(ev, None)["statusCode"] == 404
