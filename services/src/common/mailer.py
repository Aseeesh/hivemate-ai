"""Outbound email through SES. Disabled (simulated sends) when SENDER_EMAIL is not configured."""
import os
import re

import boto3

_ses = None
_ADDR = re.compile(r"^[^@\s<>,;\"]+@[^@\s<>,;\"]+\.[^@\s<>,;\"]+$")


def enabled() -> bool:
    return bool(os.environ.get("SENDER_EMAIL"))


def _client():
    global _ses
    if _ses is None:
        _ses = boto3.client("sesv2")
    return _ses


def _line(value: str, limit: int = 200) -> str:
    """Header values must be a single line; stripping CR/LF blocks header injection from customer-supplied text."""
    return re.sub(r"[\r\n]+", " ", value).strip()[:limit]


def display_name(business: str) -> str:
    return re.sub(r'[<>",;]', "", _line(business, 60)) or "Hivemate"


def reply_subject(subject: str) -> str:
    s = _line(subject) or "Your enquiry"
    return s if s.lower().startswith("re:") else f"Re: {s}"


def valid_address(addr: str) -> bool:
    return bool(_ADDR.match(addr)) and len(addr) <= 254


def send_reply(*, business: str, to: str, subject: str, body: str, reply_to: str = "") -> str:
    """Returns the SES message id. Raises ValueError for a bad recipient, botocore ClientError on SES refusal."""
    if not valid_address(to):
        raise ValueError(f"invalid recipient address: {to!r}")
    reply_tos = [reply_to] if reply_to and valid_address(reply_to) else []
    res = _client().send_email(
        FromEmailAddress=f"{display_name(business)} <{os.environ['SENDER_EMAIL']}>",
        Destination={"ToAddresses": [to]},
        ReplyToAddresses=reply_tos,
        Content={"Simple": {
            "Subject": {"Data": reply_subject(subject), "Charset": "UTF-8"},
            "Body": {"Text": {"Data": body, "Charset": "UTF-8"}},
        }},
    )
    return res["MessageId"]
