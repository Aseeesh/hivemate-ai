import pytest

from src.api import business, workqueue
from src.common.context import Ctx
from src.pipeline import customers, deals, docintel, packs, tasks

PK = "TENANT#a1"
ADMIN = Ctx("a1", "u1", "admin", "o@x.nz")


def line(t, v, c=99.0):
    return {"Type": {"Text": t}, "ValueDetection": {"Text": v, "Confidence": c}}


RESP = {"ExpenseDocuments": [{"SummaryFields": [line("VENDOR_NAME", "Bunnings Ltd"), line("INVOICE_RECEIPT_ID", "INV-7781"), line("INVOICE_RECEIPT_DATE", "2026-11-02"),
                                                  line("SUBTOTAL", "$100.00"), line("TAX", "$15.00"), line("TOTAL", "$115.00"), line("TAX", "$999")]}]}


def test_textract_response_parses_amounts_and_keeps_first_value():
    f, low = docintel.parse(RESP)
    assert f == {"supplier": "Bunnings Ltd", "invoiceNumber": "INV-7781", "invoiceDate": "2026-11-02", "subtotal": 100.0, "gst": 15.0, "total": 115.0} and low == 99.0
    assert docintel.money("NZ$1,234.50") == 1234.5 and docintel.money("n/a") is None


def test_checks_catch_wrong_gst_bad_totals_low_confidence_and_duplicates():
    good, _ = docintel.parse(RESP)
    assert docintel.check(good, 99, [], []) == []
    bad = {**good, "gst": 10.0}
    flags = docintel.check(bad, 99, [], [])
    assert any("not 15%" in f for f in flags) and any("does not equal" in f for f in flags)
    assert any("hard to read" in f for f in docintel.check(good, 60, [], []))
    assert any("duplicate" in f for f in docintel.check(good, 99, [{"docId": "d1", "invoiceNumber": "INV-7781", "supplier": "bunnings ltd"}], []))
    assert any("Could not read the total" in f for f in docintel.check({"supplier": "X", "invoiceNumber": "1"}, 99, [], []))
    assert any("Xero already has" in f for f in docintel.check(good, 99, [], [{"number": "INV-7781", "amountDue": 200.0, "status": "AUTHORISED"}]))


def test_extract_creates_a_review_task_and_refuses_other_tenants_files(fake, monkeypatch):
    class T:
        def analyze_expense(self, **kw):
            self.kw = kw
            return RESP
    t = T()
    monkeypatch.setattr(docintel, "_textract", t)
    out = docintel.extract(PK, "bucket", "tenants/a1/extract/abc-inv.pdf", 1000)
    assert out["supplier"] == "Bunnings Ltd" and out["flags"] == [] and t.kw["Document"]["S3Object"]["Name"].startswith("tenants/a1/")
    [task] = tasks.list_tasks(PK)
    assert task["type"] == "document_review" and task["status"] == "needs_approval"
    with pytest.raises(AssertionError):
        docintel.extract(PK, "bucket", "tenants/b2/extract/steal.pdf")
    r = business.route(ADMIN, "POST", "/extract", {"key": "tenants/b2/extract/steal.pdf"}, {})
    assert r["statusCode"] == 400
    assert business.route(ADMIN, "POST", "/extract", {"key": "tenants/a1/extract/../../b2/x.pdf"}, {})["statusCode"] == 400


def test_approving_a_document_task_marks_it_approved_without_sending_any_email(fake, monkeypatch):
    monkeypatch.setattr(docintel, "_textract", type("T", (), {"analyze_expense": lambda self, **k: RESP})())
    out = docintel.extract(PK, "b", "tenants/a1/extract/x-inv.pdf")
    r = workqueue.route(ADMIN, "POST", f"/work/doc-{out['docId']}/approve", {}, {})
    assert r["statusCode"] == 200 and fake.items[(PK, f"DOC#{out['docId']}")]["status"] == "approved"


def test_upload_url_rejects_dangerous_types(monkeypatch):
    with pytest.raises(ValueError):
        business.upload_url(ADMIN, "payload.exe")


def test_customer_360_joins_by_email_and_labels_sources(fake):
    deals.on_inbound(PK, "c1", "chat", "c1", 100, name="Jo", email="Jo@Client.nz", channel="web")
    deals.on_inbound(PK, deals.email_deal_id("jo@client.nz"), "email", "m1", 200, name="Jo Smith", email="jo@client.nz", channel="email")
    deals.on_inbound(PK, "c2", "chat", "c2", 150, name="Other", phone="021 555 1234")
    rows = customers.list_customers(deals.list_deals(PK))
    assert len(rows) == 2
    jo = next(r for r in rows if r["email"])
    assert jo["deals"] == 2 and set(jo["channels"]) == {"web", "email"}
    d = customers.detail("e:jo@client.nz", deals.list_deals(PK), [{"convId": "c1", "channel": "web", "status": "OPEN", "lastAt": 5}],
                         [{"SK": "MSG#m1", "from": "JO@client.nz", "subject": "Hi", "status": "SENT", "createdAt": 9, "source": "microsoft365"}],
                         [{"convId": "c1", "summary": "Wants a deep clean"}], [{"SK": "XINV#i1", "contactEmail": "jo@client.nz", "number": "INV-1", "amountDue": 5, "daysOverdue": 3}], [])
    assert d["emails"][0]["source"] == "microsoft365" and d["invoices"][0]["source"] == "xero" and d["summary"] == "Wants a deep clean" and "email" in d["identity"]
    assert customers.detail("e:nobody@x.nz", deals.list_deals(PK), [], [], [], [], []) is None
    assert [r["name"] for r in customers.list_customers(deals.list_deals(PK), "other")] == ["Other"]


def test_customer_detail_never_returns_other_tenants_records(fake):
    deals.on_inbound("TENANT#b2", "x1", "email", "m", 1, name="Secret", email="s@b2.nz")
    assert business.route(ADMIN, "GET", "/customers/e:s@b2.nz", {}, {})["statusCode"] == 404
    assert business.route(ADMIN, "GET", "/customers", {}, {})["body"]["customers"] == []


def test_packs_report_what_is_missing_and_enable_installs_plugins_and_unpauses(fake):
    fake.seed({"PK": PK, "SK": "POLICY", "paused": {"follow_up": True}})
    s = {p["id"]: p for p in packs.status(PK)}
    assert not s["smart-inbox"]["enabled"] and s["invoice-assistant"]["missing"] == ["Connect Xero under Integrations"]
    assert s["lead-recovery"]["missing"] and s["smart-scheduling"]["planned"]
    out = packs.enable(PK, "smart-inbox")
    assert out["enabled"] and (PK, "PLUGIN#email-automation") in fake.items
    assert packs.enable(PK, "lead-recovery")["enabled"]  # inbound now exists and follow-ups are unpaused
    with pytest.raises(ValueError):
        packs.enable(PK, "smart-scheduling")
    with pytest.raises(LookupError):
        packs.enable(PK, "nope")
