import os
import time
import uuid
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

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


def _conditional(fn) -> bool:
    try:
        fn()
        return True
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return False
        raise


def create(item: dict) -> bool:
    """Put only if the key is new. False means it already existed: the basis of idempotent writes and webhook de-duplication."""
    return _conditional(lambda: table().put_item(Item=to_ddb(item), ConditionExpression="attribute_not_exists(PK)"))


def update(key: dict, sets: dict | None = None, remove: list[str] | None = None, add: dict | None = None,
           if_eq: dict | None = None, must_exist: bool = True) -> bool:
    """Atomic update. `if_eq` makes it a compare-and-set (False when another worker got there first)."""
    names, values, parts, n = {}, {}, [], 0

    def ph(attr, val=None, with_value=True):
        nonlocal n
        n += 1
        names[f"#a{n}"] = attr
        if with_value:
            values[f":v{n}"] = to_ddb(val)
        return f"#a{n}", f":v{n}"

    set_parts = []
    for k, v in (sets or {}).items():
        a, v_ = ph(k, v)
        set_parts.append(f"{a} = {v_}")
    if set_parts:
        parts.append("SET " + ", ".join(set_parts))
    if remove:
        parts.append("REMOVE " + ", ".join(ph(k, with_value=False)[0] for k in remove))
    add_parts = []
    for k, v in (add or {}).items():
        a, v_ = ph(k, v)
        add_parts.append(f"{a} {v_}")
    if add_parts:
        parts.append("ADD " + ", ".join(add_parts))
    conds = ["attribute_exists(PK)"] if must_exist else []
    for k, v in (if_eq or {}).items():
        a, v_ = ph(k, v)
        conds.append(f"{a} = {v_}")
    kwargs = {"Key": key, "UpdateExpression": " ".join(parts), "ExpressionAttributeNames": names}
    if values:
        kwargs["ExpressionAttributeValues"] = values
    if conds:
        kwargs["ConditionExpression"] = " AND ".join(conds)
    return _conditional(lambda: table().update_item(**kwargs))


def query_index(pk: str, sk_max: str, limit: int = 100) -> list[dict]:
    res = table().query(IndexName="ChannelIndex", KeyConditionExpression=Key("GSI1PK").eq(pk) & Key("GSI1SK").lte(sk_max), Limit=limit)
    return [clean(i) for i in res["Items"]]
