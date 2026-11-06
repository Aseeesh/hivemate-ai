"""WhatsApp text adapter for AWS End User Messaging Social.

Inbound: Social publishes Meta webhook events to an SNS topic; this Lambda is subscribed to it.
Each event's `whatsAppWebhookEntry` is a JSON string in Meta's webhook format.
Outbound: replies go back through socialmessaging:SendWhatsAppMessage.
Status: parsing is unit-tested with fixtures; NOT yet run against a live WhatsApp number.
"""
import datetime
import json
import os
import time
import zoneinfo

import boto3
from botocore.exceptions import ClientError

from src.common import db
from src.plugins.conversation import agent

_social = None
FALLBACK = "Sorry, something went wrong on our side. The team will get back to you."


def parse(sns_message: dict) -> list[dict]:
    """Extract text messages from one Social event. Ignores statuses, media and everything else."""
    entry = sns_message.get("whatsAppWebhookEntry")
    if isinstance(entry, str):
        entry = json.loads(entry)
    out = []
    for change in (entry or {}).get("changes", []):
        value = change.get("value", {})
        phone_id = value.get("metadata", {}).get("phone_number_id", "")
        names = {c.get("wa_id"): c.get("profile", {}).get("name", "") for c in value.get("contacts", [])}
        for m in value.get("messages", []):
            if m.get("type") == "text" and m.get("text", {}).get("body"):
                out.append({"phoneNumberId": phone_id, "from": m["from"], "id": m["id"], "text": m["text"]["body"], "name": names.get(m["from"], "")})
    return out


def tenant_for(phone_number_id: str) -> dict | None:
    res = db.table().query(IndexName="ChannelIndex", KeyConditionExpression="GSI1PK = :p", ExpressionAttributeValues={":p": f"WA#{phone_number_id}"})
    return res["Items"][0] if res["Items"] else None


def first_delivery(pk: str, wamid: str) -> bool:
    """WhatsApp redelivers webhooks; process each message id once."""
    try:
        db.table().put_item(Item={"PK": pk, "SK": f"DEDUP#{wamid}", "ttl": int(time.time()) + 86400},
                            ConditionExpression="attribute_not_exists(SK)")
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return False
        raise


def send(origination_id: str, to: str, text: str) -> None:
    global _social
    if _social is None:
        _social = boto3.client("socialmessaging", region_name=os.environ.get("WHATSAPP_REGION", "ap-southeast-1"))
    payload = {"messaging_product": "whatsapp", "to": to, "type": "text", "text": {"body": text[:4000]}}
    _social.send_whatsapp_message(originationPhoneNumberId=origination_id, metaApiVersion="v20.0", message=json.dumps(payload).encode())


def within_hours(hours: dict, tz: str, now: datetime.datetime | None = None) -> bool:
    """True when the business itself is open (its own timezone), so the assistant can stay out of the owner's way."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    try:
        local = now.astimezone(zoneinfo.ZoneInfo(tz))
    except Exception:  # noqa: BLE001  unknown timezone: treat as UTC rather than failing the customer
        local = now
    return local.isoweekday() in hours.get("days", []) and hours.get("start", "00:00") <= local.strftime("%H:%M") < hours.get("end", "00:00")


def handler(event, _context):
    for record in event.get("Records", []):
        for msg in parse(json.loads(record["Sns"]["Message"])):
            link = tenant_for(msg["phoneNumberId"])
            if not link:
                print(json.dumps({"level": "WARN", "event": "unlinked_number", "phoneNumberId": msg["phoneNumberId"]}))
                continue
            pk = link["PK"]
            if not first_delivery(pk, msg["id"]):
                continue
            # "After hours only": while the business is open the owner answers from their own WhatsApp; the assistant does not butt in.
            if link.get("mode") == "after_hours" and within_hours(db.clean(link.get("hours", {})), link.get("tz", "Pacific/Auckland")):
                continue
            try:
                out = agent.handle_message(pk.split("#", 1)[1], msg["text"], "whatsapp", msg["from"], customer_name=msg["name"])
                reply = out["reply"]
            except agent.NotInstalled:
                continue
            except Exception as exc:  # noqa: BLE001 - never leave the customer without an answer
                print(json.dumps({"level": "ERROR", "error": repr(exc)}))
                reply = FALLBACK
            if reply:
                try:
                    send(link["originationPhoneNumberId"], msg["from"], reply)
                except Exception as exc:  # noqa: BLE001 - the turn is already stored; a retry would be deduplicated away
                    print(json.dumps({"level": "ERROR", "event": "send_failed", "error": repr(exc)[:700]}))
    return {"ok": True}
