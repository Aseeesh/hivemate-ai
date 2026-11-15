"""Deals: one record per customer enquiry, tracking who owes the next move.

stage:    new -> responded -> quote_sent -> followed_up -> won | lost | cold   (cold can recover when the customer comes back)
awaiting: "business" (customer wrote, nobody has answered) | "customer" (we answered, they have not replied)

The follow-up sweeper only looks at `nextDueAt`; every function here keeps that field and its index keys consistent.
"""
import hashlib
import re
import time
import zlib

from src.common import db, events, policy

STAGES = ("new", "responded", "quote_sent", "followed_up", "won", "lost", "cold")
TERMINAL = ("won", "lost")
MANUAL_STAGES = ("quote_sent", "won", "lost", "responded")  # what an owner may set by hand
SHARDS = 4


def shard(pk: str) -> int:
    return zlib.crc32(pk.encode()) % SHARDS


def key(pk: str, deal_id: str) -> dict:
    return {"PK": pk, "SK": f"DEAL#{deal_id}"}


def email_deal_id(address: str) -> str:
    return "em-" + hashlib.sha1(address.strip().lower().encode()).hexdigest()[:14]


def get(pk: str, deal_id: str) -> dict | None:
    it = db.table().get_item(Key=key(pk, deal_id)).get("Item")
    return db.clean(it) if it else None


def save(pk: str, deal: dict) -> dict:
    """Write the deal and (re)compute the due-time index keys so the sweeper can find it."""
    deal = {k: v for k, v in deal.items() if k not in ("GSI1PK", "GSI1SK")}
    due = deal.get("nextDueAt")
    if due and deal["stage"] not in TERMINAL:
        deal["GSI1PK"], deal["GSI1SK"] = f"DUE#{shard(pk)}", f"{int(due):013d}#{pk}#{deal['dealId']}"
    deal["updatedAt"] = int(time.time())
    db.table().put_item(Item=db.to_ddb(deal))
    return deal


def _hours(h: float) -> int:
    return int(h * 3600)


def _new(pk: str, deal_id: str, source: str, ref: str, now: int, **fields) -> dict:
    return {**key(pk, deal_id), "dealId": deal_id, "source": source, "ref": ref, "stage": "new", "awaiting": "business",
            "createdAt": now, "lastInboundAt": now, "followUpCount": 0, "remindCount": 0, **fields}


def _clip(v, n: int) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip()[:n]


def on_inbound(pk: str, deal_id: str, source: str, ref: str, now: int | None = None, **fields) -> dict:
    """The customer wrote. Creates the deal on first contact; a reply after a follow-up or going cold counts as a recovered lead."""
    now = int(now or time.time())
    pol = policy.get(pk)
    clean = {k: _clip(v, 300 if k in ("need", "subject") else 120) for k, v in fields.items() if v}
    deal = get(pk, deal_id)
    if not deal:
        deal = save(pk, {**_new(pk, deal_id, source, ref, now, **clean), "nextDueAt": now + _hours(pol["cadence"]["noReplyHours"])})
        events.record(pk, "enquiry_received", deal_id, at=now, source=source)
        return deal
    deal.update({k: v for k, v in clean.items() if v})
    if deal.get("awaiting") == "customer" and deal.get("followUpCount") and deal["stage"] in ("followed_up", "cold", "quote_sent"):
        events.record(pk, "lead_recovered", deal_id, at=now, wasCold=deal["stage"] == "cold",
                      waitedSeconds=now - int(deal.get("lastOutboundAt", now)))
        deal["recoveredAt"], deal["stage"] = now, "responded"
    if deal["stage"] in TERMINAL:  # a won/lost customer writing again is a new conversation
        deal["stage"] = "new"
    if deal.get("awaiting") != "business":  # only the first unanswered message starts the clock
        deal["awaiting"], deal["lastInboundAt"], deal["remindCount"] = "business", now, 0
        deal["nextDueAt"] = now + _hours(pol["cadence"]["noReplyHours"])
    return save(pk, deal)


def on_outbound(pk: str, deal_id: str, via: str, now: int | None = None) -> dict | None:
    """We answered (AI reply, approved draft, owner reply). Starts the follow-up clock and records first-response time."""
    now = int(now or time.time())
    deal = get(pk, deal_id)
    if not deal:
        return None
    pol = policy.get(pk)
    if not deal.get("firstResponseAt"):
        deal["firstResponseAt"] = now
        events.record(pk, "first_response", deal_id, at=now, seconds=max(0, now - int(deal["createdAt"])), via=via)
    deal["lastOutboundAt"], deal["awaiting"] = now, "customer"
    if deal["stage"] == "new":
        deal["stage"] = "responded"
    c = pol["cadence"]
    deal["nextDueAt"] = now + (_hours(c["quoteFollowUpDays"] * 24) if deal["stage"] == "quote_sent" else _hours(c["followUpAfterHours"]))
    return save(pk, deal)


def set_stage(pk: str, deal_id: str, stage: str, now: int | None = None) -> dict:
    if stage not in MANUAL_STAGES:
        raise ValueError(f"stage must be one of {', '.join(MANUAL_STAGES)}")
    now = int(now or time.time())
    deal = get(pk, deal_id)
    if not deal:
        raise LookupError("deal not found")
    deal["stage"] = stage
    c = policy.get(pk)["cadence"]
    if stage in TERMINAL:
        deal.pop("nextDueAt", None)
        deal["closedAt"] = now
        events.record(pk, f"deal_{stage}", deal_id, at=now)
    elif stage == "quote_sent":
        deal["awaiting"], deal["followUpCount"] = "customer", 0
        deal["lastOutboundAt"], deal["nextDueAt"] = now, now + c["quoteFollowUpDays"] * 86400
        events.record(pk, "quote_sent", deal_id, at=now)
    return save(pk, deal)


def list_deals(pk: str, limit: int = 200) -> list[dict]:
    return db.query_prefix(pk, "DEAL#", limit=limit)


def stage_counts(deals: list[dict]) -> dict:
    out = {s: 0 for s in STAGES}
    for d in deals:
        out[d["stage"]] = out.get(d["stage"], 0) + 1
    return out


# ---- channel hooks: called by the chat agent and the email worker. They must never break the customer-facing flow. ----
def on_chat_turn(pk: str, conv_id: str, channel: str, customer: str, collected: dict, handoff: bool, now: int | None = None) -> None:
    """A chat becomes a deal once there is someone to follow up (a name, phone or email, or a stated need)."""
    if not any(collected.get(k) for k in ("name", "phone", "email", "need")) and not handoff:
        return
    now = int(now or time.time())
    on_inbound(pk, conv_id, "chat", conv_id, now, name=collected.get("name"), phone=collected.get("phone"),
               email=collected.get("email"), need=collected.get("need"), channel=channel)
    if handoff:  # a person must answer: leave awaiting=business so the work queue shows it
        return
    on_outbound(pk, conv_id, "assistant", now)


def on_email(pk: str, sender: str, name: str, subject: str, message_id: str, now: int | None = None) -> str:
    deal_id = email_deal_id(sender)
    on_inbound(pk, deal_id, "email", message_id, now, name=name, email=sender.strip().lower(), subject=subject, need=subject, channel="email")
    return deal_id
