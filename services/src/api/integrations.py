"""Integration tokens: let a business's own tools (for example a Google Apps Script in their Gmail) ask Hivemate for a suggested reply.

A token can do exactly one thing: request suggestions for its own business. It cannot read data, send anything or change settings.
Only a hash is stored; the token is shown once when it is created and replaced when rotated.
"""
import hashlib
import secrets
import time

from src.common import db
from src.common.context import Ctx

PREFIX = "hm_"


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_email_token(ctx: Ctx) -> str:
    token = PREFIX + secrets.token_urlsafe(24)
    db.table().put_item(Item={"PK": ctx.pk, "SK": "INTEGRATION#email", "GSI1PK": f"TOK#{hash_token(token)}", "GSI1SK": ctx.pk, "createdAt": int(time.time())})
    return token  # the old token stops working: same item key, new hash


def email_status(ctx: Ctx) -> dict:
    item = db.table().get_item(Key={"PK": ctx.pk, "SK": "INTEGRATION#email"}).get("Item")
    return {"connected": bool(item), "createdAt": int(item["createdAt"]) if item else None}


def revoke_email(ctx: Ctx) -> None:
    db.table().delete_item(Key={"PK": ctx.pk, "SK": "INTEGRATION#email"})
