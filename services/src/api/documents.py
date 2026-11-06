"""Tenant knowledge documents: upload to S3 under the tenant prefix, then sync into the Bedrock Knowledge Base."""
import json
import os
import re

import boto3
from botocore.config import Config

from src.common import db
from src.common.context import Ctx

# SigV4 + regional endpoint: required for presigned uploads into a KMS-encrypted bucket.
s3 = boto3.client("s3", config=Config(signature_version="s3v4", s3={"addressing_style": "virtual"}))
agent = boto3.client("bedrock-agent")

ALLOWED_EXT = {"pdf", "txt", "md", "html", "csv", "docx"}
MAX_BYTES = 10 * 1024 * 1024
META_SUFFIX = ".metadata.json"
AUDIENCES = ("public", "internal")  # public: customers may be told; internal: only the business's own admins


def _prefix(ctx: Ctx) -> str:
    return f"tenants/{ctx.tenant_id}/docs/"


def safe_name(filename: str) -> str:
    name = re.sub(r"[^A-Za-z0-9._-]", "_", filename.rsplit("/", 1)[-1])[:120]
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext not in ALLOWED_EXT:
        raise ValueError(f"file type must be one of {sorted(ALLOWED_EXT)}")
    return name


def create_upload(ctx: Ctx, filename: str, audience: str = "public") -> dict:
    if audience not in AUDIENCES:
        raise ValueError(f"audience must be one of {list(AUDIENCES)}")
    key = _prefix(ctx) + safe_name(filename)
    bucket = os.environ["DOCS_BUCKET"]
    # The sidecar is what makes retrieval tenant-safe: Retrieve filters on this metadata.
    s3.put_object(
        Bucket=bucket, Key=key + META_SUFFIX,
        Body=json.dumps({"metadataAttributes": {"tenantId": ctx.tenant_id, "audience": audience}}),
        ContentType="application/json",
    )
    post = s3.generate_presigned_post(
        Bucket=bucket, Key=key,
        Conditions=[["content-length-range", 1, MAX_BYTES]],
        ExpiresIn=300,
    )
    return {"key": key, "upload": post}


def audience_of(key: str) -> str:
    try:
        body = s3.get_object(Bucket=os.environ["DOCS_BUCKET"], Key=key + META_SUFFIX)["Body"].read()
        return json.loads(body)["metadataAttributes"].get("audience", "public")
    except Exception:  # noqa: BLE001  a missing or unreadable sidecar is shown as the default, never an error
        return "public"


def set_audience(ctx: Ctx, name: str, audience: str) -> None:
    """Re-tag a document. Takes effect for retrieval after the next sync."""
    if audience not in AUDIENCES:
        raise ValueError(f"audience must be one of {list(AUDIENCES)}")
    key = _prefix(ctx) + safe_name(name)
    s3.put_object(Bucket=os.environ["DOCS_BUCKET"], Key=key + META_SUFFIX,
                  Body=json.dumps({"metadataAttributes": {"tenantId": ctx.tenant_id, "audience": audience}}), ContentType="application/json")


def list_documents(ctx: Ctx) -> dict:
    res = s3.list_objects_v2(Bucket=os.environ["DOCS_BUCKET"], Prefix=_prefix(ctx), MaxKeys=200)
    docs = [
        {"name": o["Key"][len(_prefix(ctx)):], "size": o["Size"], "modified": o["LastModified"].isoformat(), "audience": audience_of(o["Key"])}
        for o in res.get("Contents", []) if not o["Key"].endswith(META_SUFFIX)
    ]
    # The data source is shared, so "the latest job" would be another business's. Track this tenant's own last job.
    mine = db.table().get_item(Key={"PK": ctx.pk, "SK": "SYNC#latest"}).get("Item")
    last = None
    if mine:
        job = agent.get_ingestion_job(knowledgeBaseId=os.environ["KNOWLEDGE_BASE_ID"], dataSourceId=os.environ["DATA_SOURCE_ID"],
                                      ingestionJobId=mine["jobId"])["ingestionJob"]
        last = {"status": job["status"], "startedAt": job["startedAt"].isoformat()}
    return {"documents": docs, "lastSync": last}


def delete_document(ctx: Ctx, name: str) -> None:
    key = _prefix(ctx) + safe_name(name)  # safe_name strips any path, so ../ cannot leave the tenant prefix
    bucket = os.environ["DOCS_BUCKET"]
    s3.delete_objects(Bucket=bucket, Delete={"Objects": [{"Key": key}, {"Key": key + META_SUFFIX}]})


def start_sync(ctx: Ctx) -> dict:
    """Ingestion is KB-wide (one data source shared by all tenants); isolation is by metadata filter."""
    job = agent.start_ingestion_job(
        knowledgeBaseId=os.environ["KNOWLEDGE_BASE_ID"], dataSourceId=os.environ["DATA_SOURCE_ID"],
    )["ingestionJob"]
    db.table().put_item(Item={"PK": ctx.pk, "SK": "SYNC#latest", "jobId": job["ingestionJobId"]})
    return {"jobId": job["ingestionJobId"], "status": job["status"]}


# ---------- unanswered questions -> knowledge ----------
NOTES_FILE = "owner-answers.md"
MAX_NOTES_BYTES = 200_000
GAP_ID = re.compile(r"^\d{13}-[a-f0-9]{8}$")


def merge_note(existing: str, question: str, answer: str) -> str:
    """Append one owner-written Q&A to the notes file. Both parts are cleaned: the question started as customer text, so it is not trusted."""
    from src.common.harness import untrusted
    q, a = " ".join(untrusted(question, 300).split()), untrusted(answer, 1500).strip()
    if not q or not a:
        raise ValueError("question and answer are both required")
    base = existing.rstrip() or "# Answers from the owner"
    out = f"{base}\n\nQ: {q}\nA: {a}\n"
    if len(out.encode()) > MAX_NOTES_BYTES:
        raise ValueError("owner-answers file is full; delete old answers first")
    return out


def list_gaps(ctx: Ctx) -> list[dict]:
    items = db.query_prefix(ctx.pk, "GAP#", limit=100, newest_first=True)
    return [{"id": g["SK"][4:], "question": g.get("question", ""), "at": g.get("at", 0)} for g in items if g.get("status") == "OPEN"]


def _gap(ctx: Ctx, gap_id: str) -> dict:
    if not GAP_ID.match(gap_id):
        raise ValueError("invalid id")
    item = db.table().get_item(Key={"PK": ctx.pk, "SK": f"GAP#{gap_id}"}).get("Item")
    if not item or item.get("status") != "OPEN":
        raise LookupError("not found")
    return item


def answer_gap(ctx: Ctx, gap_id: str, question: str, answer: str) -> dict:
    _gap(ctx, gap_id)
    bucket, key = os.environ["DOCS_BUCKET"], _prefix(ctx) + NOTES_FILE
    try:
        existing = s3.get_object(Bucket=bucket, Key=key)["Body"].read().decode("utf-8")
    except s3.exceptions.NoSuchKey:
        existing = ""
    s3.put_object(Bucket=bucket, Key=key, Body=merge_note(existing, question, answer).encode("utf-8"), ContentType="text/markdown")
    s3.put_object(Bucket=bucket, Key=key + META_SUFFIX, Body=json.dumps({"metadataAttributes": {"tenantId": ctx.tenant_id, "audience": "public"}}), ContentType="application/json")
    db.table().update_item(Key={"PK": ctx.pk, "SK": f"GAP#{gap_id}"}, UpdateExpression="SET #s = :a", ExpressionAttributeNames={"#s": "status"}, ExpressionAttributeValues={":a": "ANSWERED"})
    return start_sync(ctx)


def dismiss_gap(ctx: Ctx, gap_id: str) -> None:
    _gap(ctx, gap_id)
    db.table().update_item(Key={"PK": ctx.pk, "SK": f"GAP#{gap_id}"}, UpdateExpression="SET #s = :a", ExpressionAttributeNames={"#s": "status"}, ExpressionAttributeValues={":a": "DISMISSED"})
