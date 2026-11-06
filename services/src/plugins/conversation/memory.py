"""Long-term customer memory for the conversation agent (harness area 1: context & memory).

A conversation's transcript is the session and `conv.collected` is its state; this is what survives between
conversations: the stable details a returning customer already gave, so the agent doesn't ask again.

Privacy rules: only channels with a real, stable customer identity (WhatsApp number), never anonymous web visitors or the owner's dashboard test chat;
only a short allow-list of fields, not transcripts; expires on its own after 180 days (DynamoDB TTL);
`forget()` erases one customer on request. Memory is shown to the model as reference data, never instructions.
"""
import hashlib
import time

from src.common import db

REMEMBERED = ("name", "phone", "location")
KEEP_SECONDS = 180 * 86400
REMEMBERED_CHANNELS = {"whatsapp"}  # allow-list: the dashboard test chat and anonymous web visitors are not customers


def _sk(channel: str, customer: str) -> str:
    return "MEM#" + hashlib.sha256(f"{channel}:{customer}".encode()).hexdigest()[:24]


def remembers(channel: str) -> bool:
    return channel in REMEMBERED_CHANNELS


def profile_from(collected: dict) -> dict:
    return {k: v.strip()[:100] for k, v in collected.items() if k in REMEMBERED and isinstance(v, str) and v.strip()}


def load(pk: str, channel: str, customer: str) -> dict:
    if not remembers(channel):
        return {}
    item = db.table().get_item(Key={"PK": pk, "SK": _sk(channel, customer)}).get("Item")
    return profile_from(db.clean(item.get("profile", {}))) if item else {}


def save(pk: str, channel: str, customer: str, collected: dict) -> None:
    profile = profile_from(collected)
    if not remembers(channel) or not profile:
        return
    old = load(pk, channel, customer)
    now = int(time.time())
    db.table().put_item(Item={"PK": pk, "SK": _sk(channel, customer), "profile": {**old, **profile}, "updatedAt": now, "ttl": now + KEEP_SECONDS})


def forget(pk: str, channel: str, customer: str) -> None:
    db.table().delete_item(Key={"PK": pk, "SK": _sk(channel, customer)})


def as_prompt(profile: dict) -> str:
    if not profile:
        return "(new customer, nothing remembered)"
    return "Returning customer. Details they gave before. Answer their question first; only mention these if relevant, and never ask them to re-confirm unprompted: " + "; ".join(f"{k}: {v}" for k, v in profile.items())
