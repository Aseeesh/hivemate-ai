"""Tenant-scoped retrieval from the shared Bedrock Knowledge Base."""
import os

import boto3

NO_KNOWLEDGE = ("(no knowledge base configured)", "(no matching knowledge)")
_rt = None


def retrieve(kb_id: str, query: str, tenant_id: str, results: int = 4) -> str:
    global _rt
    if not kb_id:
        return NO_KNOWLEDGE[0]
    if _rt is None:
        _rt = boto3.client("bedrock-agent-runtime")
    res = _rt.retrieve(
        knowledgeBaseId=kb_id,
        retrievalQuery={"text": query[:1000]},
        retrievalConfiguration={"vectorSearchConfiguration": {
            "numberOfResults": results,
            # Tenant isolation inside a shared KB: every document is tagged with tenantId metadata.
            "filter": {"equals": {"key": "tenantId", "value": tenant_id}},
        }},
    )
    return "\n---\n".join(r["content"]["text"] for r in res["retrievalResults"]) or NO_KNOWLEDGE[1]
