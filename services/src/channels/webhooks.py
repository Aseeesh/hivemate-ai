"""Public endpoints for connected systems: the OAuth browser callback and provider webhooks.

Both are unauthenticated by design, so each proves itself: the callback by a single-use `state` we issued, a webhook by the
provider's signature or secret. The tenant is never read from the request.
"""
import base64
import json
import os
import urllib.parse

import boto3

from src.connectors import runtime

_lambda = None


def _resp(status: int, body="", headers=None):
    return {"statusCode": status, "headers": headers or {"content-type": "application/json"}, "body": body if isinstance(body, str) else json.dumps(body)}


def _dashboard(params: dict) -> str:
    base = os.environ.get("DASHBOARD_URL", "").rstrip("/") + "/dashboard/"
    return base + "?" + urllib.parse.urlencode(params)


def oauth_callback(provider: str, query: dict) -> dict:
    if query.get("error"):  # the owner pressed Cancel at the provider
        return _resp(302, "", {"location": _dashboard({"connect_error": "The connection was cancelled."})})
    try:
        runtime.complete_auth(provider, query.get("state", ""), query.get("code", ""))
    except PermissionError as e:
        return _resp(302, "", {"location": _dashboard({"connect_error": str(e)})})
    except Exception as e:  # noqa: BLE001
        print(json.dumps({"level": "ERROR", "event": "oauth_failed", "provider": provider, "error": repr(e)[:200]}))
        return _resp(302, "", {"location": _dashboard({"connect_error": "The connection could not be completed. Please try again."})})
    return _resp(302, "", {"location": _dashboard({"connected": provider})})


def _tenants_named_in(provider: str, body: bytes) -> set[str]:
    """The pks of businesses a verified webhook is about, found through ids that were stored when they connected."""
    try:
        doc = json.loads(body or b"{}")
    except ValueError:
        return set()
    keys = ({str(e.get("tenantId", "")) for e in doc.get("events", [])} if provider == "xero"
            else {str(n.get("subscriptionId", "")) for n in doc.get("value", [])})
    return {pk for pk in (runtime.tenant_for_external(provider, k) for k in keys if k) if pk}


def _wake_worker(pk: str, provider: str) -> None:
    global _lambda
    fn = os.environ.get("WORKER_FN")
    if not fn:
        return  # the scheduled sweep will pick the connection up (it is now due)
    _lambda = _lambda or boto3.client("lambda")
    _lambda.invoke(FunctionName=fn, InvocationType="Event", Payload=json.dumps({"syncTenant": pk, "provider": provider}).encode())


def webhook(provider: str, headers: dict, body: bytes, query: dict) -> dict:
    try:
        c = runtime.connector(provider)
    except LookupError:
        return _resp(404, {"error": "not found"})

    def conn_lookup(key: str):
        pk = runtime.tenant_for_external(provider, key)
        return runtime.get_conn(pk, provider) if pk else None

    ok, override = c.verify_webhook(headers, body, query, conn_lookup)
    if not ok:
        return _resp(401, "")  # Xero requires an empty 401 for a bad signature
    if override:
        return _resp(override["statusCode"], override.get("body", ""), override.get("headers"))
    for pk in _tenants_named_in(provider, body):
        try:
            if runtime.request_sync(pk, provider):
                _wake_worker(pk, provider)
        except Exception as e:  # noqa: BLE001 - never fail the delivery: the scheduled reconcile repairs it
            runtime.note_webhook_failure(pk, provider)
            print(json.dumps({"level": "ERROR", "event": "webhook_wake_failed", "provider": provider, "error": repr(e)[:200]}))
    return _resp(200, "")


def handler(event, _context):
    method, path = event["requestContext"]["http"]["method"], event["rawPath"]
    if method == "OPTIONS":
        return {"statusCode": 204}
    query = event.get("queryStringParameters") or {}
    parts = path.strip("/").split("/")
    if method == "GET" and len(parts) == 3 and parts[0] == "oauth" and parts[2] == "callback":
        return oauth_callback(parts[1], query)
    if method == "POST" and len(parts) == 2 and parts[0] == "webhooks":
        raw = base64.b64decode(event.get("body") or "") if event.get("isBase64Encoded") else (event.get("body") or "").encode()
        return webhook(parts[1], {k.lower(): v for k, v in (event.get("headers") or {}).items()}, raw, query)
    return _resp(404, {"error": "not found"})
