"""Customer 360, automation packs and document extraction routes (called by the main handler)."""
import os
import re
import urllib.parse
import uuid

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from src.common import db
from src.common.context import Ctx
from src.pipeline import customers, deals, docintel, packs, tasks

_s3 = None


def _client():
    global _s3
    if _s3 is None:
        _s3 = boto3.client("s3", config=Config(signature_version="s3v4", s3={"addressing_style": "virtual"}))
    return _s3


def _r(status: int, body):
    return {"statusCode": status, "body": body}


def upload_url(ctx: Ctx, filename: str) -> dict:
    name = re.sub(r"[^A-Za-z0-9._-]", "_", filename.rsplit("/", 1)[-1])[:100]
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext not in docintel.ALLOWED:
        raise ValueError(f"file type must be one of {sorted(docintel.ALLOWED)}")
    key = f"tenants/{ctx.tenant_id}/extract/{uuid.uuid4().hex[:8]}-{name}"
    post = _client().generate_presigned_post(Bucket=os.environ["DOCS_BUCKET"], Key=key, Conditions=[["content-length-range", 1, 10 * 1024 * 1024]], ExpiresIn=300)
    return {"key": key, "upload": post}


def route(ctx: Ctx, method: str, path: str, body: dict, query: dict):
    if (method, path) == ("GET", "/customers"):
        return _r(200, {"customers": customers.list_customers(deals.list_deals(ctx.pk, 500), str((query or {}).get("q", ""))[:80])})
    m = re.fullmatch(r"/customers/([^/]{3,200})", path)
    if m and method == "GET":
        key = urllib.parse.unquote(m.group(1))
        out = customers.detail(key, deals.list_deals(ctx.pk, 500), db.query_prefix(ctx.pk, "CONV#", limit=200), db.query_prefix(ctx.pk, "MSG#", limit=200, newest_first=True),
                               db.query_prefix(ctx.pk, "LEAD#", limit=200), db.query_prefix(ctx.pk, "XINV#", limit=300), tasks.list_tasks(ctx.pk, tasks.OPEN))
        return _r(200, out) if out else _r(404, {"error": "not found"})

    if (method, path) == ("GET", "/packs"):
        return _r(200, packs.status(ctx.pk))
    m = re.fullmatch(r"/packs/([a-z-]{3,40})/enable", path)
    if m and method == "POST":
        ctx.require_admin()
        try:
            out = packs.enable(ctx.pk, m.group(1))
        except LookupError:
            return _r(404, {"error": "unknown pack"})
        except ValueError as e:
            return _r(409, {"error": str(e)})
        db.audit(ctx.pk, ctx.user_id, "pack.enabled", {"pack": m.group(1)})
        return _r(200, out)

    if (method, path) == ("GET", "/extract"):
        rows = db.query_prefix(ctx.pk, "DOC#", limit=100, newest_first=True)
        return _r(200, {"documents": [{k: v for k, v in r.items() if k not in ("PK", "SK")} for r in rows]})
    if (method, path) == ("POST", "/extract/upload"):
        return _r(200, upload_url(ctx, str(body["filename"])))
    if (method, path) == ("POST", "/extract"):
        key = str(body.get("key", ""))
        if not key.startswith(f"tenants/{ctx.tenant_id}/extract/") or ".." in key:  # never trust a key from the client
            return _r(400, {"error": "unknown document"})
        try:
            return _r(200, docintel.extract(ctx.pk, os.environ["DOCS_BUCKET"], key))
        except ClientError as e:
            code = e.response["Error"]["Code"]
            msg = {"UnsupportedDocumentException": "That file type or a multi-page PDF cannot be read yet. Upload a photo or a one-page PDF.",
                   "InvalidS3ObjectException": "The upload was not found. Try uploading again."}.get(code, "The document could not be read right now.")
            return _r(422, {"error": msg})
    return None
