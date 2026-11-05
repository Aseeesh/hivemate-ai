"""One structured log line per model call, for monitoring (e.g. LLMScope). Metadata only: never message text.

Fields follow the OpenTelemetry GenAI names where there is one. The tenant id is hashed so dashboards can group by business
without exposing ids.
"""
import hashlib
import json
import time

_tenant = ""


def set_tenant(tenant_id: str) -> None:
    global _tenant
    _tenant = hashlib.sha256(tenant_id.encode()).hexdigest()[:10] if tenant_id else ""


def emit(event: str, component: str, started: float, **fields) -> None:
    print(json.dumps({"event": event, "app": "hivemate", "component": component, "tenant": _tenant,
                      "latencyMs": int((time.time() - started) * 1000), **fields}))


def converse(client, component: str, **kwargs) -> dict:
    """bedrock-runtime converse() plus one llm_call log line (success or failure)."""
    t0 = time.time()
    try:
        res = client.converse(**kwargs)
    except Exception as e:  # logged, then re-raised unchanged
        code = getattr(e, "response", {}).get("Error", {}).get("Code", type(e).__name__)
        emit("llm_call", component, t0, operation="chat", provider="aws.bedrock", model=kwargs.get("modelId"), error=str(code))
        raise
    usage = res.get("usage", {})
    emit("llm_call", component, t0, operation="chat", provider="aws.bedrock", model=kwargs.get("modelId"),
         inputTokens=usage.get("inputTokens", 0), outputTokens=usage.get("outputTokens", 0), stopReason=res.get("stopReason", ""))
    return res
