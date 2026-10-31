import os
import time
import uuid
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key

_table = None


def table():
    global _table
    if _table is None:
        _table = boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"])
    return _table


def clean(value):
    """DynamoDB returns Decimal; make it JSON-serialisable."""
    if isinstance(value, list):
        return [clean(v) for v in value]
    if isinstance(value, dict):
        return {k: clean(v) for k, v in value.items()}
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    return value


def to_ddb(value):
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, list):
        return [to_ddb(v) for v in value]
    if isinstance(value, dict):
        return {k: to_ddb(v) for k, v in value.items()}
    return value


def query_prefix(pk: str, sk_prefix: str, limit: int = 50, newest_first: bool = False) -> list[dict]:
    res = table().query(
        KeyConditionExpression=Key("PK").eq(pk) & Key("SK").begins_with(sk_prefix),
        Limit=limit,
        ScanIndexForward=not newest_first,
    )
    return [clean(i) for i in res["Items"]]


def audit(pk: str, actor: str, action: str, detail: dict | None = None) -> None:
    """Append-only audit trail for human and AI actions."""
    now = int(time.time() * 1000)
    table().put_item(Item=to_ddb({
        "PK": pk,
        "SK": f"AUDIT#{now:013d}#{uuid.uuid4().hex[:8]}",
        "actor": actor,
        "action": action,
        "detail": detail or {},
        "at": now,
    }))
