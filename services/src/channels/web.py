"""Public website chat: the embeddable widget talks to this Lambda without a login.

Trust model: the site key (pk_...) only selects the tenant. It is public by design, so abuse is bounded instead:
an optional Origin allow-list, a per-visitor hourly cap, a per-business daily cap (protects Bedrock spend),
a short message limit and the agent's own turn limit. Replies never include the collected lead data.
"""
import hashlib
import json
import os
import re
import time
import uuid

from botocore.exceptions import ClientError

from src.api import integrations
from src.common import db, llmlog
from src.common.harness import untrusted
from src.common.knowledge import retrieve
from src.plugins.conversation import agent
from src.plugins.email import processor

KEY_RE = re.compile(r"^pk_[A-Za-z0-9_-]{16,64}$")
CONV_RE = re.compile(r"^[a-f0-9]{32}$")
MAX_MESSAGE = 800
VISITOR_PER_HOUR = 30
TENANT_PER_DAY = int(os.environ.get("PUBLIC_CHAT_DAILY_CAP", "300"))
WIDGET = os.path.join(os.path.dirname(__file__), "widget.js")


def _resp(status: int, body, content_type: str = "application/json", extra: dict | None = None) -> dict:
    headers = {"content-type": content_type, "cache-control": "no-store", **(extra or {})}
    return {"statusCode": status, "headers": headers, "body": body if isinstance(body, str) else json.dumps(body)}


def tenant_for_key(key: str) -> dict | None:
    if not KEY_RE.match(key or ""):
        return None
    res = db.table().query(IndexName="ChannelIndex", KeyConditionExpression="GSI1PK = :p", ExpressionAttributeValues={":p": f"WEB#{key}"})
    return res["Items"][0] if res["Items"] else None


HOSTED_ORIGIN = os.environ.get("HOSTED_CHAT_ORIGIN", "")  # Hivemate's own chat page, always allowed so owners can share its link
SUGGESTIONS = ["What services do you offer?", "How much does it cost?", "Which areas do you cover?", "What are your opening hours?", "I'd like a quote"]


def origin_allowed(channel: dict, origin: str) -> bool:
    allowed = channel.get("allowedOrigins") or []
    return not allowed or origin in allowed or (bool(HOSTED_ORIGIN) and origin == HOSTED_ORIGIN)


def bump(pk: str, sk: str, ttl_seconds: int) -> int:
    """Atomic counter that expires on its own (DynamoDB TTL)."""
    res = db.table().update_item(
        Key={"PK": pk, "SK": sk},
        UpdateExpression="ADD n :one SET #t = if_not_exists(#t, :ttl)",
        ExpressionAttributeNames={"#t": "ttl"},
        ExpressionAttributeValues={":one": 1, ":ttl": int(time.time()) + ttl_seconds},
        ReturnValues="UPDATED_NEW",
    )
    return int(res["Attributes"]["n"])


def over_limit(pk: str, key: str, ip: str, now: float | None = None) -> str:
    now = now or time.time()
    visitor = hashlib.sha256(f"{key}|{ip}".encode()).hexdigest()[:16]
    if bump(pk, f"RATE#hour#{int(now // 3600)}#{visitor}", 7200) > VISITOR_PER_HOUR:
        return "You're sending messages very quickly. Please wait a little and try again."
    if bump(pk, f"RATE#day#{time.strftime('%Y-%m-%d', time.gmtime(now))}", 172800) > TENANT_PER_DAY:
        return "Our assistant is busy right now. Please contact the business directly."
    return ""


SUGGEST_PER_DAY = int(os.environ.get("EMAIL_SUGGEST_DAILY_CAP", "200"))
DEFAULT_EMAIL_CONFIG = {"businessTone": "friendly, concise, New Zealand English", "autoReplyCategories": ["faq"], "confidenceThreshold": 0.8, "knowledgeBaseId": ""}


def tenant_for_token(token: str) -> dict | None:
    if not token.startswith(integrations.PREFIX) or len(token) > 80:
        return None
    res = db.table().query(IndexName="ChannelIndex", KeyConditionExpression="GSI1PK = :p", ExpressionAttributeValues={":p": f"TOK#{integrations.hash_token(token)}"})
    return res["Items"][0] if res["Items"] else None


def suggest_email(event, body: dict, headers: dict) -> dict:
    """Server-to-server: a business's own Gmail script asks for a suggested reply. Nothing is sent and nothing is stored."""
    auth = headers.get("authorization", "")
    item = tenant_for_token(auth[7:].strip()) if auth.lower().startswith("bearer ") else None
    if not item:
        return _resp(401, {"error": "invalid token"})
    pk = item["PK"]
    tenant_id = pk.split("#", 1)[1]
    sender, subject, text = str(body.get("from", ""))[:200], str(body.get("subject", ""))[:300], str(body.get("body", ""))[:6000]
    if not text.strip():
        return _resp(400, {"error": "body is required"})
    if bump(pk, f"RATE#sugg#{time.strftime('%Y-%m-%d', time.gmtime())}", 172800) > SUGGEST_PER_DAY:
        return _resp(429, {"error": "daily suggestion limit reached"})
    plugin = db.table().get_item(Key={"PK": pk, "SK": "PLUGIN#email-automation"}).get("Item")
    business = db.table().get_item(Key={"PK": pk, "SK": "META"}).get("Item", {}).get("name", "")
    cfg = {**DEFAULT_EMAIL_CONFIG, **(db.clean(plugin["config"]) if plugin else {}), "businessName": business}
    llmlog.set_tenant(tenant_id)
    msg = {"from": untrusted(sender, 200), "subject": untrusted(subject, 300), "body": untrusted(text)}
    knowledge = untrusted(retrieve(cfg.get("knowledgeBaseId") or os.environ.get("KNOWLEDGE_BASE_ID", ""), f"{subject}\n{text}"[:1000], tenant_id))  # customer audience: public documents only
    result = processor.draft(msg, cfg, knowledge)
    human = processor.needs_human(result, cfg, knowledge, approval_required=False)
    db.audit(pk, "integration:email", "integration.email_suggested", {"category": result["category"], "needsHuman": human})
    return _resp(200, {"category": result["category"], "confidence": result["confidence"], "reply": result["reply"], "needsHuman": human, "business": business})


def handler(event, _context):
    method = event["requestContext"]["http"]["method"]
    path = event["rawPath"]
    if method == "OPTIONS":
        return {"statusCode": 204}
    try:
        if (method, path) == ("POST", "/integrations/email/suggest"):
            hdrs = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
            return suggest_email(event, json.loads(event["body"]) if event.get("body") else {}, hdrs)

        if (method, path) == ("GET", "/widget.js"):
            with open(WIDGET, encoding="utf-8") as f:
                return _resp(200, f.read(), "text/javascript; charset=utf-8", {"cache-control": "public, max-age=300"})

        headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
        body = json.loads(event["body"]) if event.get("body") else {}
        key = (event.get("queryStringParameters") or {}).get("key") or str(body.get("key", ""))
        channel = tenant_for_key(key)
        # Unknown key, wrong origin and uninstalled plugin look the same from outside.
        if not channel or not origin_allowed(channel, headers.get("origin", "")):
            return _resp(404, {"error": "chat unavailable"})
        pk = channel["PK"]
        tenant_id = pk.split("#", 1)[1]

        plugin = db.table().get_item(Key={"PK": pk, "SK": "PLUGIN#conversation-agent"}).get("Item")
        if not plugin:
            return _resp(404, {"error": "chat unavailable"})
        cfg = db.clean(plugin["config"])

        if (method, path) == ("GET", "/info"):
            business = db.table().get_item(Key={"PK": pk, "SK": "META"}).get("Item", {}).get("name", "")
            return _resp(200, {"agentName": cfg.get("agentName", "Assistant"), "business": business, "suggestions": SUGGESTIONS})

        if (method, path) == ("POST", "/chat"):
            message = str(body.get("message", "")).strip()
            if not message or len(message) > MAX_MESSAGE:
                return _resp(400, {"error": f"message must be 1-{MAX_MESSAGE} characters"})
            conv_id = body.get("conversationId")
            if conv_id is not None and not CONV_RE.match(str(conv_id)):
                return _resp(400, {"error": "invalid conversationId"})
            conv_id = conv_id or uuid.uuid4().hex  # unguessable: it is the visitor's only credential
            limited = over_limit(pk, key, event["requestContext"]["http"].get("sourceIp", ""))
            if limited:
                return _resp(429, {"error": limited})
            out = agent.handle_message(tenant_id, message, "web-public", f"web:{conv_id}", conv_id)
            return _resp(200, {"conversationId": out["conversationId"], "reply": out["reply"], "status": out["status"]})

        return _resp(404, {"error": "not found"})
    except (ValueError, KeyError):
        return _resp(400, {"error": "bad request"})
    except ClientError as e:
        print(json.dumps({"level": "ERROR", "error": repr(e)[:300]}))
        return _resp(502, {"error": "The assistant is temporarily unavailable, please try again."})
