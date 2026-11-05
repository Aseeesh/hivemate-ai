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


def _prefix(ctx: Ctx) -> str:
    return f"tenants/{ctx.tenant_id}/docs/"


def safe_name(filename: str) -> str:
    name = re.sub(r"[^A-Za-z0-9._-]", "_", filename.rsplit("/", 1)[-1])[:120]
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext not in ALLOWED_EXT:
        raise ValueError(f"file type must be one of {sorted(ALLOWED_EXT)}")
    return name


def create_upload(ctx: Ctx, filename: str) -> dict:
    key = _prefix(ctx) + safe_name(filename)
    bucket = os.environ["DOCS_BUCKET"]
    # The sidecar is what makes retrieval tenant-safe: Retrieve filters on this metadata.
    s3.put_object(
        Bucket=bucket, Key=key + META_SUFFIX,
        Body=json.dumps({"metadataAttributes": {"tenantId": ctx.tenant_id}}),
        ContentType="application/json",
    )
    post = s3.generate_presigned_post(
        Bucket=bucket, Key=key,
        Conditions=[["content-length-range", 1, MAX_BYTES]],
        ExpiresIn=300,
    )
    return {"key": key, "upload": post}


def list_documents(ctx: Ctx) -> dict:
    res = s3.list_objects_v2(Bucket=os.environ["DOCS_BUCKET"], Prefix=_prefix(ctx), MaxKeys=200)
    docs = [
        {"name": o["Key"][len(_prefix(ctx)):], "size": o["Size"], "modified": o["LastModified"].isoformat()}
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
