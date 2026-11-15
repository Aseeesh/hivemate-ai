"""Append-only business events. Every number on the Impact page is computed from these rows, never asked of a model.

Row: PK=TENANT#id  SK=EVT#<ms>#<rand>   kind, dealId, at (ms), meta
Kinds: enquiry_received, first_response, follow_up_due, follow_up_drafted, follow_up_sent, follow_up_manual, lead_recovered, lead_cold,
       reply_overdue, task_completed, task_failed, approval_completed, invoice_reminder_drafted, invoice_reminder_sent, invoice_paid,
       send_failed, sync_ok, sync_failed, doc_extracted
"""
import time
import uuid

from src.common import db

KEEP_DAYS = 400


def record(pk: str, kind: str, deal_id: str = "", at: float | None = None, **meta) -> None:
    ms = int((at if at is not None else time.time()) * 1000)
    db.table().put_item(Item=db.to_ddb({
        "PK": pk, "SK": f"EVT#{ms:013d}#{uuid.uuid4().hex[:8]}", "kind": kind, "dealId": deal_id, "at": ms, "meta": meta,
        "ttl": int(ms / 1000) + KEEP_DAYS * 86400,
    }))


def since(pk: str, from_ts: float, limit: int = 5000) -> list[dict]:
    """Events at or after `from_ts` (seconds), oldest first. SK is time-ordered so this is one range query."""
    from boto3.dynamodb.conditions import Key
    items, kw = [], {"KeyConditionExpression": Key("PK").eq(pk) & Key("SK").gte(f"EVT#{int(from_ts * 1000):013d}") & Key("SK").lt("EVT$"), "Limit": 1000}
    while len(items) < limit:
        r = db.table().query(**kw)
        items += r["Items"]
        if "LastEvaluatedKey" not in r:
            break
        kw["ExclusiveStartKey"] = r["LastEvaluatedKey"]
    return [db.clean(i) for i in items[:limit]]
