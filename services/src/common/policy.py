"""Per-business automation policy: how much Hivemate may do alone, how often it follows up, and what a task is worth.

Modes: assist (it recommends, a person acts) < approve (it drafts, a person approves) < automate (it acts inside limits).
Quotes and refunds can never be automated, whatever is stored.
"""
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from src.common import db

MODES = ("assist", "approve", "automate")
ACTIONS = ("follow_up", "quote_follow_up", "invoice_reminder", "quote", "refund")
NEVER_AUTOMATE = {"quote", "refund"}
AUTOMATIONS = ("follow_up", "invoice_reminder", "connector_sync")  # each can be paused

DEFAULTS = {
    "modes": {"follow_up": "approve", "quote_follow_up": "approve", "invoice_reminder": "approve", "quote": "approve", "refund": "approve"},
    "cadence": {"noReplyHours": 24, "followUpAfterHours": 24, "quoteFollowUpDays": 3, "maxFollowUps": 2},
    "minutes": {"follow_up": 5, "quote_follow_up": 8, "invoice_reminder": 6, "email_drafted": 4, "document_extracted": 7},
    "paused": {"follow_up": False, "invoice_reminder": False, "connector_sync": False},
    "sendWindow": {"start": "08:00", "end": "18:00"},
}
LIMITS = {"noReplyHours": (1, 336), "followUpAfterHours": (1, 720), "quoteFollowUpDays": (1, 60), "maxFollowUps": (0, 5)}


def get(pk: str) -> dict:
    item = db.clean(db.table().get_item(Key={"PK": pk, "SK": "POLICY"}).get("Item") or {})
    return merge(item)


def merge(stored: dict) -> dict:
    out = {k: dict(v) for k, v in DEFAULTS.items()}
    for section in out:
        out[section].update({k: v for k, v in (stored.get(section) or {}).items() if k in out[section]})
    for a in NEVER_AUTOMATE:
        out["modes"][a] = "approve" if out["modes"][a] == "automate" else out["modes"][a]
    return out


def validate(body: dict) -> dict:
    """Return the cleaned policy, or raise ValueError saying what is wrong."""
    unknown = set(body) - set(DEFAULTS)
    if unknown:
        raise ValueError(f"unknown policy sections: {sorted(unknown)}")
    cur = merge(body)
    for action, mode in cur["modes"].items():
        if action not in ACTIONS or mode not in MODES:
            raise ValueError(f"invalid mode for {action}")
        if action in NEVER_AUTOMATE and (body.get("modes") or {}).get(action) == "automate":
            raise ValueError(f"{action} can never be automated")
    for k, (lo, hi) in LIMITS.items():
        v = cur["cadence"][k]
        if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
            raise ValueError(f"{k} must be a whole number between {lo} and {hi}")
    for k, v in cur["minutes"].items():
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not 0 <= v <= 240:
            raise ValueError(f"minutes.{k} must be between 0 and 240")
    for k, v in cur["paused"].items():
        if not isinstance(v, bool):
            raise ValueError(f"paused.{k} must be true or false")
    w = cur["sendWindow"]
    if not all(isinstance(w[k], str) and len(w[k]) == 5 and w[k][2] == ":" for k in ("start", "end")) or w["start"] >= w["end"]:
        raise ValueError("sendWindow must look like {start:'08:00', end:'18:00'}")
    return cur


def save(pk: str, body: dict) -> dict:
    cur = validate(body)
    db.table().put_item(Item=db.to_ddb({"PK": pk, "SK": "POLICY", **cur, "updatedAt": int(time.time())}))
    return cur


def in_send_window(policy: dict, tz: str = "Pacific/Auckland", now: float | None = None) -> bool:
    """Automatic sends only happen in business hours, Monday to Friday."""
    t = datetime.fromtimestamp(now if now is not None else time.time(), ZoneInfo(tz))
    w = policy["sendWindow"]
    return t.isoweekday() <= 5 and w["start"] <= t.strftime("%H:%M") < w["end"]
