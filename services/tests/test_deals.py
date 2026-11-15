from src.common import events, policy
from src.pipeline import deals

PK = "TENANT#a1"
T0 = 1_800_000_000


def kinds(fake):
    return [i["kind"] for k, i in sorted(fake.items.items()) if k[1].startswith("EVT#")]


def test_policy_defaults_and_safety_rules(fake):
    p = policy.get(PK)
    assert p["modes"]["follow_up"] == "approve" and p["cadence"]["maxFollowUps"] == 2
    import pytest
    with pytest.raises(ValueError):
        policy.validate({"modes": {"refund": "automate"}})
    with pytest.raises(ValueError):
        policy.validate({"modes": {"quote": "automate"}})
    with pytest.raises(ValueError):
        policy.validate({"cadence": {"maxFollowUps": 99}})
    with pytest.raises(ValueError):
        policy.validate({"bogus": {}})
    assert policy.validate({"modes": {"follow_up": "automate"}})["modes"]["follow_up"] == "automate"


def test_stored_policy_cannot_smuggle_automatic_quotes(fake):
    fake.seed({"PK": PK, "SK": "POLICY", "modes": {"quote": "automate", "refund": "automate"}})
    assert policy.get(PK)["modes"]["quote"] == "approve" and policy.get(PK)["modes"]["refund"] == "approve"


def test_send_window_is_weekday_business_hours():
    p = policy.DEFAULTS
    # Monday 2026-11-16 10:00 NZDT = 2026-11-15 21:00 UTC
    import calendar, datetime
    mon_10 = calendar.timegm(datetime.datetime(2026, 11, 15, 21, 0).timetuple())
    sat_10 = calendar.timegm(datetime.datetime(2026, 11, 20, 21, 0).timetuple())
    mon_22 = calendar.timegm(datetime.datetime(2026, 11, 16, 9, 0).timetuple())
    assert policy.in_send_window(p, "Pacific/Auckland", mon_10)
    assert not policy.in_send_window(p, "Pacific/Auckland", sat_10)
    assert not policy.in_send_window(p, "Pacific/Auckland", mon_22)


def test_first_enquiry_creates_deal_awaiting_business_with_due_time(fake):
    d = deals.on_inbound(PK, "d1", "email", "m1", T0, name="Jo", email="jo@x.nz")
    assert d["stage"] == "new" and d["awaiting"] == "business"
    assert d["nextDueAt"] == T0 + 24 * 3600
    assert d["GSI1PK"].startswith("DUE#") and d["GSI1SK"].startswith(f"{T0 + 86400:013d}")
    assert kinds(fake) == ["enquiry_received"]


def test_reply_records_first_response_time_once_and_starts_follow_up_clock(fake):
    deals.on_inbound(PK, "d1", "email", "m1", T0)
    d = deals.on_outbound(PK, "d1", "approved_draft", T0 + 600)
    assert d["stage"] == "responded" and d["awaiting"] == "customer" and d["nextDueAt"] == T0 + 600 + 86400
    deals.on_outbound(PK, "d1", "approved_draft", T0 + 900)
    ev = [i for k, i in fake.items.items() if k[1].startswith("EVT#") and i["kind"] == "first_response"]
    assert len(ev) == 1 and ev[0]["meta"]["seconds"] == 600


def test_quote_sent_uses_quote_cadence_and_terminal_stages_leave_the_sweeper_index(fake):
    deals.on_inbound(PK, "d1", "email", "m1", T0)
    deals.on_outbound(PK, "d1", "x", T0 + 10)
    d = deals.set_stage(PK, "d1", "quote_sent", T0 + 100)
    assert d["nextDueAt"] == T0 + 100 + 3 * 86400 and d["awaiting"] == "customer"
    d = deals.set_stage(PK, "d1", "won", T0 + 200)
    assert "GSI1PK" not in d and "nextDueAt" not in d
    import pytest
    with pytest.raises(ValueError):
        deals.set_stage(PK, "d1", "cold")  # cold is system-only


def test_reply_after_follow_up_is_a_recovered_lead(fake):
    deals.on_inbound(PK, "d1", "email", "m1", T0)
    deals.on_outbound(PK, "d1", "x", T0 + 10)
    d = deals.get(PK, "d1")
    d.update({"followUpCount": 1, "stage": "followed_up"})
    deals.save(PK, d)
    d = deals.on_inbound(PK, "d1", "email", "m2", T0 + 5 * 86400)
    assert d["stage"] == "responded" and d["awaiting"] == "business" and d.get("recoveredAt")
    assert "lead_recovered" in kinds(fake)


def test_a_normal_second_message_is_not_a_recovery(fake):
    deals.on_inbound(PK, "d1", "email", "m1", T0)
    deals.on_outbound(PK, "d1", "x", T0 + 10)
    deals.on_inbound(PK, "d1", "email", "m2", T0 + 60)
    assert "lead_recovered" not in kinds(fake)


def test_chat_without_any_contact_detail_creates_no_deal(fake):
    deals.on_chat_turn(PK, "c1", "web", "web:1", {}, False, T0)
    assert deals.list_deals(PK) == []
    deals.on_chat_turn(PK, "c1", "web", "web:1", {"name": "Jo"}, False, T0 + 5)
    d = deals.get(PK, "c1")
    assert d["awaiting"] == "customer" and d["source"] == "chat"


def test_chat_handoff_leaves_the_business_owing_a_reply(fake):
    deals.on_chat_turn(PK, "c2", "web", "web:1", {"name": "Jo"}, True, T0)
    assert deals.get(PK, "c2")["awaiting"] == "business"


def test_email_deal_is_one_per_sender_regardless_of_case():
    assert deals.email_deal_id("Jo@X.nz ") == deals.email_deal_id("jo@x.nz")
