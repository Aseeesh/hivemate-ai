"""Conversation API: test/web chat, conversations, leads and WhatsApp channel linking."""
import json
import re
import secrets

from botocore.exceptions import ClientError

from src.common import db
from src.common.context import Forbidden, from_event
from src.plugins.conversation import agent

CONV_ID = re.compile(r"^[a-f0-9]{8,40}$")
ORIGIN = re.compile(r"^https?://[A-Za-z0-9.-]+(:\d{1,5})?$")


def _resp(status: int, body) -> dict:
    return {"statusCode": status, "headers": {"content-type": "application/json"}, "body": json.dumps(body)}


def handler(event, _context):
    method = event["requestContext"]["http"]["method"]
    path = event["rawPath"]
    if method == "OPTIONS":
        return {"statusCode": 204}
    try:
        ctx = from_event(event)
        body = json.loads(event["body"]) if event.get("body") else {}

        if (method, path) == ("POST", "/chat"):
            conv_id = body.get("conversationId")
            if conv_id is not None and not CONV_ID.match(str(conv_id)):
                return _resp(400, {"error": "invalid conversationId"})
            if body.get("audience") == "admin":  # the owner's own view: internal documents included, admin role required
                ctx.require_admin()
                return _resp(200, agent.handle_admin_message(ctx.tenant_id, ctx.user_id, str(body["message"])))
            # Dashboard test chat: one customer identity per signed-in user.
            conv_id = conv_id or agent.new_conv_id()
            out = agent.handle_message(ctx.tenant_id, str(body["message"]), "web", f"web:{ctx.user_id}", conv_id)
            return _resp(200, out)

        if (method, path) == ("GET", "/conversations"):
            items = db.query_prefix(ctx.pk, "CONV#", limit=100)
            items.sort(key=lambda c: c.get("lastAt", 0), reverse=True)
            return _resp(200, [{k: c.get(k) for k in ("convId", "channel", "customer", "status", "collected", "turns", "lastAt", "createdAt")} for c in items])

        m = re.fullmatch(r"/conversations/([a-f0-9]{8,40})", path)
        if m and method == "GET":
            ctx.require_admin()
            conv = db.table().get_item(Key={"PK": ctx.pk, "SK": f"CONV#{m.group(1)}"}).get("Item")
            if not conv:
                return _resp(404, {"error": "not found"})
            turns = db.query_prefix(ctx.pk, f"TURN#{m.group(1)}#", limit=200)
            return _resp(200, {"conversation": db.clean(conv), "turns": [{"role": t["role"], "text": t["text"], "at": t["at"]} for t in turns]})

        m = re.fullmatch(r"/conversations/([a-f0-9]{8,40})/status", path)
        if m and method == "POST":
            ctx.require_admin()
            status = body.get("status")
            if status not in ("OPEN", "CLOSED"):
                return _resp(400, {"error": "status must be OPEN or CLOSED"})
            key = {"PK": ctx.pk, "SK": f"CONV#{m.group(1)}"}
            if not db.table().get_item(Key=key).get("Item"):
                return _resp(404, {"error": "not found"})
            db.table().update_item(Key=key, UpdateExpression="SET #s = :s", ExpressionAttributeNames={"#s": "status"}, ExpressionAttributeValues={":s": status})
            # The lead card mirrors the conversation: a resumed or closed chat must not keep saying "needs a person".
            lead_key = {"PK": ctx.pk, "SK": f"LEAD#{m.group(1)}"}
            lead = db.table().get_item(Key=lead_key).get("Item")
            if lead and lead.get("status") == "HANDOFF":
                db.table().update_item(Key=lead_key, UpdateExpression="SET #s = :s, handoffReason = :r", ExpressionAttributeNames={"#s": "status"},
                                       ExpressionAttributeValues={":s": "COLLECTING" if status == "OPEN" else "CLOSED", ":r": ""})
            db.audit(ctx.pk, ctx.user_id, "conversation.status", {"convId": m.group(1), "status": status})
            return _resp(200, {"status": status})

        if (method, path) == ("GET", "/leads"):
            items = db.query_prefix(ctx.pk, "LEAD#", limit=100)
            items.sort(key=lambda c: c.get("updatedAt", 0), reverse=True)
            return _resp(200, items)

        if (method, path) == ("PUT", "/channels/whatsapp"):
            ctx.require_admin()
            meta_id, origination = str(body["metaPhoneNumberId"]), str(body["originationPhoneNumberId"])
            if not re.fullmatch(r"\d{5,30}", meta_id) or not re.fullmatch(r"[A-Za-z0-9-]{5,80}", origination):
                return _resp(400, {"error": "invalid phone number ids"})
            # A phone number may belong to one tenant only.
            claimed = db.table().query(IndexName="ChannelIndex", KeyConditionExpression="GSI1PK = :p", ExpressionAttributeValues={":p": f"WA#{meta_id}"})["Items"]
            if any(i["PK"] != ctx.pk for i in claimed):
                return _resp(409, {"error": "this WhatsApp number is already linked to another business"})
            db.table().put_item(Item={"PK": ctx.pk, "SK": "CHANNEL#whatsapp", "GSI1PK": f"WA#{meta_id}", "GSI1SK": ctx.pk,
                                      "metaPhoneNumberId": meta_id, "originationPhoneNumberId": origination})
            db.audit(ctx.pk, ctx.user_id, "channel.whatsapp_linked", {"metaPhoneNumberId": meta_id})
            return _resp(200, {"linked": meta_id})

        if (method, path) == ("GET", "/channels/web"):
            ctx.require_admin()
            item = db.table().get_item(Key={"PK": ctx.pk, "SK": "CHANNEL#web"}).get("Item")
            return _resp(200, {"key": item["siteKey"], "allowedOrigins": item.get("allowedOrigins", [])} if item else {"key": None, "allowedOrigins": []})

        if (method, path) == ("PUT", "/channels/web"):
            ctx.require_admin()
            origins = body.get("allowedOrigins", [])
            if not isinstance(origins, list) or len(origins) > 10 or not all(isinstance(o, str) and ORIGIN.match(o) for o in origins):
                return _resp(400, {"error": "allowedOrigins must be up to 10 origins like https://example.co.nz"})
            key = {"PK": ctx.pk, "SK": "CHANNEL#web"}
            current = db.table().get_item(Key=key).get("Item")
            site_key = current["siteKey"] if current and not body.get("rotate") else "pk_" + secrets.token_urlsafe(18)
            db.table().put_item(Item={**key, "GSI1PK": f"WEB#{site_key}", "GSI1SK": ctx.pk, "siteKey": site_key, "allowedOrigins": origins})
            db.audit(ctx.pk, ctx.user_id, "channel.web_configured", {"rotated": bool(body.get("rotate")), "origins": origins})
            return _resp(200, {"key": site_key, "allowedOrigins": origins})

        return _resp(404, {"error": "not found"})
    except Forbidden as e:
        return _resp(403, {"error": str(e)})
    except agent.NotInstalled as e:
        return _resp(409, {"error": str(e)})
    except (ValueError, KeyError) as e:
        return _resp(400, {"error": str(e)})
    except ClientError as e:
        print(json.dumps({"level": "ERROR", "error": repr(e)[:300]}))
        return _resp(502, {"error": "AI service temporarily unavailable, please try again"})
