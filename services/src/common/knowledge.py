"""Tenant-scoped retrieval from the shared Bedrock Knowledge Base."""
import os

import boto3

NO_KNOWLEDGE = ("(no knowledge base configured)", "(no matching knowledge)")
_rt = None


def build_filter(tenant_id: str, audience: str) -> dict:
    """Customers only ever retrieve customer-visible documents; admins retrieve everything of their own business.
    This is the privacy boundary: the model is never shown internal text in a customer chat, so it cannot leak it."""
    mine = {"equals": {"key": "tenantId", "value": tenant_id}}  # tenant isolation inside the shared KB
    if audience == "admin":
        return mine
    return {"andAll": [mine, {"equals": {"key": "audience", "value": "public"}}]}


def retrieve(kb_id: str, query: str, tenant_id: str, results: int = 4, audience: str = "customer") -> str:
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
            "filter": build_filter(tenant_id, audience),
        }},
    )
    return "\n---\n".join(r["content"]["text"] for r in res["retrievalResults"]) or NO_KNOWLEDGE[1]
