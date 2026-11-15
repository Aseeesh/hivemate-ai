import pytest

from src.common import mailer
from src.pipeline import deals, followups, tasks

PK = "TENANT#a1"
T0 = 1_800_000_000  # a Sunday in NZ: automatic sends must wait for the window unless a test moves "now"
MON_10_NZ = 1_794_776_400  # 2026-11-16 10:00 NZDT


@pytest.fixture(autouse=True)
def base(fake, monkeypatch):
    fake.seed({"PK": PK, "SK": "META", "name": "SparkClean", "timezone": "Pacific/Auckland"})
    monkeypatch.setattr(mailer, "enabled", lambda: False)
    sent = []
    monkeypatch.setattr(mailer, "send_reply", lambda **kw: sent.append(kw) or "id")
    monkeypatch.setattr("src.connectors.runtime.try_send_mail", lambda *a, **k: None, raising=False)
    return sent


def task_list():
    return tasks.list_tasks(PK)


def answered(now=MON_10_NZ, **fields):
    deals.on_inbound(PK, "d1", "email", "m1", now, name="Jo Smith", email="jo@x.nz", need="end of lease clean", **fields)
    deals.on_outbound(PK, "d1", "assistant", now + 60)
    return now + 60


def test_nothing_happens_before_the_due_time(fake):
    t = answered()
    assert followups.sweep(t + 3600) == {"checked": 0, "tasks": 0, "sent": 0, "cold": 0}


def test_quiet_customer_gets_an_approval_task_with_a_safe_draft(fake):
    t = answered()
    r = followups.sweep(t + 86400 + 1)
    assert r["tasks"] == 1 and r["sent"] == 0
    [task] = task_list()
    assert task["status"] == "needs_approval" and task["type"] == "follow_up" and task["to"] == "jo@x.nz"
    assert "Hi Jo," in task["draft"] and "end of lease clean" in task["draft"] and "SparkClean" in task["draft"]
    assert "$" not in task["draft"]  # no invented prices
    d = deals.get(PK, "d1")
    assert d["stage"] == "followed_up" and d["followUpCount"] == 1


def test_sweeping_twice_creates_one_task(fake):
    t = answered()
    followups.sweep(t + 86400 + 1)
    followups.sweep(t + 86400 + 2)  # claim pushed the deal out, and the task id is deterministic anyway
    assert len(task_list()) == 1


def test_two_workers_racing_claim_a_deal_once(fake):
    t = answered()
    due = t + 86400 + 1
    assert followups.process_due(PK, "d1", due)["tasks"] == 1
    # a second worker that read the deal before the first claimed it holds a stale nextDueAt
    stale = deals.get(PK, "d1")
    assert stale["nextDueAt"] > due
    assert followups.process_due(PK, "d1", due)["tasks"] == 0


def test_after_max_follow_ups_the_lead_goes_cold_with_one_escalation(fake):
    t = answered()
    now = t + 86400 + 1
    for _ in range(4):
        followups.sweep(now)
        now += 86400 + 1
    d = deals.get(PK, "d1")
    assert d["stage"] == "cold" and "GSI1PK" not in d
    types = [x["type"] for x in task_list()]
    assert types.count("follow_up") == 2 and types.count("cold_lead") == 1


def test_automate_mode_sends_inside_the_window_and_only_once(fake, base):
    fake.seed({"PK": PK, "SK": "POLICY", "modes": {"follow_up": "automate"}})
    t = answered()
    r = followups.sweep(t + 86400 + 1)  # Tuesday 10:01 NZ
    assert r["sent"] == 1 and len(base) == 0  # SES disabled -> simulated, nothing real sent
    [task] = task_list()
    assert task["status"] == "done" and task["sentVia"] == "simulated" and task["sentBy"] == "automation"


def test_automate_mode_waits_outside_the_send_window(fake):
    fake.seed({"PK": PK, "SK": "POLICY", "modes": {"follow_up": "automate"}})
    t = answered(now=MON_10_NZ + 12 * 3600)  # Monday 22:00 NZ: due at 22:01 Tuesday, outside the window
    r = followups.sweep(t + 86400 + 1)
    assert r["sent"] == 0 and task_list()[0]["status"] == "needs_approval"


def test_assist_mode_only_recommends(fake):
    fake.seed({"PK": PK, "SK": "POLICY", "modes": {"follow_up": "assist"}})
    t = answered()
    followups.sweep(t + 86400 + 1)
    assert task_list()[0]["status"] == "open"


def test_paused_automation_does_nothing(fake):
    fake.seed({"PK": PK, "SK": "POLICY", "paused": {"follow_up": True}})
    t = answered()
    assert followups.sweep(t + 86400 + 1)["tasks"] == 0


def test_unanswered_enquiry_becomes_an_urgent_reply_overdue_task(fake):
    deals.on_inbound(PK, "d2", "email", "m", MON_10_NZ, name="Al", email="al@x.nz")
    followups.sweep(MON_10_NZ + 86400 + 1)
    [task] = task_list()
    assert task["type"] == "reply_overdue" and task["priority"] == "urgent"
    d = deals.get(PK, "d2")
    assert d["remindCount"] == 1 and d["nextDueAt"] > MON_10_NZ + 86400  # reminds again tomorrow, capped


def test_quote_follow_up_uses_quote_wording_and_never_automates_quotes_themselves(fake):
    deals.on_inbound(PK, "d3", "email", "m", MON_10_NZ, name="Bo", email="bo@x.nz", need="office clean")
    deals.on_outbound(PK, "d3", "x", MON_10_NZ + 5)
    deals.set_stage(PK, "d3", "quote_sent", MON_10_NZ + 10)
    followups.sweep(MON_10_NZ + 10 + 3 * 86400 + 1)
    [task] = task_list()
    assert task["action"] == "quote_follow_up" and "quote" in task["draft"].lower() and task["priority"] == "high"


def test_delivery_is_exactly_once_and_updates_the_deal(fake, base, monkeypatch):
    monkeypatch.setattr(mailer, "enabled", lambda: True)
    t = answered()
    followups.sweep(t + 86400 + 1)
    tid = task_list()[0]["taskId"]
    out = followups.deliver(PK, tid, "Edited text", actor="user-1")
    assert out["via"] == "ses" and len(base) == 1 and base[0]["body"] == "Edited text" and base[0]["to"] == "jo@x.nz"
    with pytest.raises(followups.Conflict):
        followups.deliver(PK, tid, "Edited text", actor="user-1")  # double click
    assert len(base) == 1


def test_failed_send_keeps_the_task_for_retry(fake, monkeypatch):
    monkeypatch.setattr(mailer, "enabled", lambda: True)
    def boom(**kw):
        raise ValueError("invalid recipient address")
    monkeypatch.setattr(mailer, "send_reply", boom)
    t = answered()
    followups.sweep(t + 86400 + 1)
    tid = task_list()[0]["taskId"]
    with pytest.raises(ValueError):
        followups.deliver(PK, tid, "hi", actor="u")
    assert tasks.get(PK, tid)["status"] == "failed" and "invalid" in tasks.get(PK, tid)["error"]
    monkeypatch.setattr(mailer, "send_reply", lambda **kw: "ok")
    assert followups.deliver(PK, tid, "hi", actor="u")["status"] == "done"  # retry works


def test_cannot_send_without_an_email_address(fake):
    deals.on_inbound(PK, "d4", "chat", "c", MON_10_NZ, name="Cy", phone="021 000 000")
    deals.on_outbound(PK, "d4", "assistant", MON_10_NZ + 5)
    followups.sweep(MON_10_NZ + 5 + 86400 + 1)
    with pytest.raises(ValueError):
        followups.deliver(PK, task_list()[0]["taskId"], "hi", actor="u")
