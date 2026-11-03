"""Control-plane API. Routes are matched on API Gateway's routeKey."""
import json
import os
import re
import time
import uuid

import boto3

from src.api import documents
from src.common import db, plugins
from src.common.context import Forbidden, from_event

events = boto3.client("events")


def _resp(status: int, body) -> dict:
    return {"statusCode": status, "headers": {"content-type": "application/json"}, "body": json.dumps(body)}


def handler(event, _context):
    method = event["requestContext"]["http"]["method"]
    path = event["rawPath"]
    try:
        ctx = from_event(event)
        body = json.loads(event["body"]) if event.get("body") else {}

        if (method, path) == ("GET", "/me"):
            meta = db.table().get_item(Key={"PK": ctx.pk, "SK": "META"}).get("Item", {})
            return _resp(200, {"user": {"id": ctx.user_id, "email": ctx.email, "role": ctx.role}, "tenant": db.clean(meta)})

        if (method, path) == ("GET", "/plugins"):
            installed = {i["SK"].split("#", 1)[1]: i for i in db.query_prefix(ctx.pk, "PLUGIN#")}
            catalog = [
                {**m, "installed": pid in installed, "config": installed.get(pid, {}).get("config")}
                for pid, m in plugins.registry().items()
            ]
            return _resp(200, catalog)

        m = re.fullmatch(r"/plugins/([a-z0-9-]+)", path)
        if m and method in ("PUT", "DELETE"):
            ctx.require_admin()
            manifest = plugins.registry().get(m.group(1))
            if not manifest:
                return _resp(404, {"error": "unknown plugin"})
            key = {"PK": ctx.pk, "SK": f"PLUGIN#{manifest['pluginId']}"}
            if method == "DELETE":
                db.table().delete_item(Key=key)
                db.audit(ctx.pk, ctx.user_id, "plugin.removed", {"plugin": manifest["pluginId"]})
                return _resp(200, {"removed": manifest["pluginId"]})
            config = plugins.validate_config(manifest, body.get("config", {}))
            db.table().put_item(Item=db.to_ddb({
                **key, "version": manifest["version"], "permissions": manifest["permissions"],
                "config": config, "installedAt": int(time.time()),
            }))
            db.audit(ctx.pk, ctx.user_id, "plugin.configured", {"plugin": manifest["pluginId"], "version": manifest["version"]})
            return _resp(200, {"installed": manifest["pluginId"], "config": config})

        if (method, path) == ("POST", "/plugins/email-automation/ingest"):
            # Stand-in for SES inbound mail. A real channel adapter resolves the tenant
            # from the recipient address via ChannelIndex; here the caller's tenant is used.
            if not db.table().get_item(Key={"PK": ctx.pk, "SK": "PLUGIN#email-automation"}).get("Item"):
                return _resp(409, {"error": "email-automation plugin not installed"})
            # Time-prefixed so the MSG# sort key (and GET /messages) is chronological.
            message_id = f"{int(time.time() * 1000):013d}{uuid.uuid4().hex[:8]}"
            events.put_events(Entries=[{
                "EventBusName": os.environ["EVENT_BUS"],
                "Source": "hivemate.channel",
                "DetailType": "email.received",
                "Detail": json.dumps({
                    "tenantId": ctx.tenant_id, "messageId": message_id,
                    "from": body["from"], "subject": body.get("subject", ""), "body": body["body"],
                }),
            }])
            return _resp(202, {"messageId": message_id})

        if (method, path) == ("GET", "/messages"):
            return _resp(200, db.query_prefix(ctx.pk, "MSG#", newest_first=True))

        m = re.fullmatch(r"/messages/([a-f0-9]+)/(approve|reject)", path)
        if m and method == "POST":
            key = {"PK": ctx.pk, "SK": f"MSG#{m.group(1)}"}
            item = db.table().get_item(Key=key).get("Item")
            if not item:
                return _resp(404, {"error": "not found"})
            if item["status"] != "PENDING_APPROVAL":
                return _resp(409, {"error": f"message is {item['status']}"})
            # TODO(phase 5): on approve, send via SES. Recorded as simulated for now.
            new_status = "SENT_SIMULATED" if m.group(2) == "approve" else "REJECTED"
            db.table().update_item(
                Key=key, UpdateExpression="SET #s = :s, reviewedBy = :u",
                ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues={":s": new_status, ":u": ctx.user_id},
            )
            db.audit(ctx.pk, ctx.user_id, f"message.{m.group(2)}", {"messageId": m.group(1)})
            return _resp(200, {"status": new_status})

        if (method, path) == ("GET", "/documents"):
            return _resp(200, documents.list_documents(ctx))

        if (method, path) == ("POST", "/documents"):
            ctx.require_admin()
            out = documents.create_upload(ctx, body["filename"])
            db.audit(ctx.pk, ctx.user_id, "document.upload_requested", {"key": out["key"]})
            return _resp(200, out)

        if (method, path) == ("POST", "/documents/sync"):
            ctx.require_admin()
            out = documents.start_sync(ctx)
            db.audit(ctx.pk, ctx.user_id, "documents.sync_started", out)
            return _resp(202, out)

        m = re.fullmatch(r"/documents/([^/]+)", path)
        if m and method == "DELETE":
            ctx.require_admin()
            documents.delete_document(ctx, m.group(1))
            db.audit(ctx.pk, ctx.user_id, "document.deleted", {"name": m.group(1)})
            return _resp(200, {"deleted": m.group(1)})

        if (method, path) == ("GET", "/audit"):
            ctx.require_admin()
            return _resp(200, db.query_prefix(ctx.pk, "AUDIT#", newest_first=True, limit=100))

        return _resp(404, {"error": "not found"})
    except Forbidden as e:
        return _resp(403, {"error": str(e)})
    except (ValueError, KeyError) as e:
        return _resp(400, {"error": str(e)})
