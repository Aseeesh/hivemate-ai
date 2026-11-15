"""Document intelligence: read a supplier invoice or receipt with Textract AnalyzeExpense, check it, and send it for human approval.
Nothing is posted anywhere: the result waits in the Work Queue as a "document review" task.
Limit: synchronous Textract reads images and single-page PDFs. Multi-page PDFs need the asynchronous API (not built)."""
import re
import time
import uuid

import boto3

from src.common import db, events
from src.pipeline import tasks

GST_RATE = 0.15
TOLERANCE = 0.05
LOW_CONFIDENCE = 80.0
ALLOWED = {"pdf", "png", "jpg", "jpeg", "tif", "tiff"}
_textract = None

FIELDS = {"VENDOR_NAME": "supplier", "INVOICE_RECEIPT_ID": "invoiceNumber", "INVOICE_RECEIPT_DATE": "invoiceDate", "DUE_DATE": "dueDate",
          "SUBTOTAL": "subtotal", "TAX": "gst", "TOTAL": "total", "TAX_PAYER_ID": "gstNumber"}
AMOUNTS = {"subtotal", "gst", "total"}


def textract():
    global _textract
    if _textract is None:
        _textract = boto3.client("textract")
    return _textract


def money(text: str) -> float | None:
    m = re.search(r"-?\d[\d,]*\.?\d*", (text or "").replace(" ", ""))
    try:
        return round(float(m.group(0).replace(",", "")), 2) if m else None
    except ValueError:
        return None


def parse(resp: dict) -> tuple[dict, float]:
    """Textract summary fields -> our fields, plus the lowest confidence among those found."""
    docs = resp.get("ExpenseDocuments") or []
    fields, low = {}, 100.0
    for f in (docs[0].get("SummaryFields", []) if docs else []):
        name = FIELDS.get((f.get("Type") or {}).get("Text", ""))
        text = ((f.get("ValueDetection") or {}).get("Text") or "").strip()
        if not name or not text or name in fields:
            continue
        fields[name] = money(text) if name in AMOUNTS else text[:120]
        low = min(low, float((f.get("ValueDetection") or {}).get("Confidence", 100)))
    return fields, low


def check(fields: dict, low_conf: float, existing_docs: list[dict], invoices: list[dict]) -> list[str]:
    flags = []
    for need, label in (("supplier", "supplier"), ("invoiceNumber", "invoice number"), ("total", "total")):
        if fields.get(need) in (None, ""):
            flags.append(f"Could not read the {label}")
    sub, gst, total = fields.get("subtotal"), fields.get("gst"), fields.get("total")
    if sub is not None and gst is not None and abs(gst - round(sub * GST_RATE, 2)) > TOLERANCE:
        flags.append(f"GST ${gst:.2f} is not 15% of the subtotal ${sub:.2f} (expected ${sub * GST_RATE:.2f})")
    if sub is not None and gst is not None and total is not None and abs(sub + gst - total) > TOLERANCE:
        flags.append(f"Subtotal plus GST (${sub + gst:.2f}) does not equal the total ${total:.2f}")
    if low_conf < LOW_CONFIDENCE:
        flags.append(f"Some fields were hard to read (lowest confidence {low_conf:.0f}%). Check them against the document")
    sup, num = (fields.get("supplier") or "").lower(), fields.get("invoiceNumber")
    for d in existing_docs:
        if num and sup and d.get("invoiceNumber") == num and (d.get("supplier") or "").lower() == sup:
            flags.append(f"Possible duplicate of a document already received ({d['docId']})")
            break
    for i in invoices:
        if num and i.get("number") == num and total is not None and abs(float(i.get("amountDue", 0)) - total) > TOLERANCE and i.get("status") == "AUTHORISED":
            flags.append(f"Xero already has invoice {num} with amount due ${i['amountDue']:.2f}, which differs from ${total:.2f}")
            break
    return flags


def extract(pk: str, bucket: str, key: str, now: int | None = None) -> dict:
    now = int(now or time.time())
    assert key.startswith(f"tenants/{pk[7:]}/extract/"), "document is outside this business's folder"
    resp = textract().analyze_expense(Document={"S3Object": {"Bucket": bucket, "Name": key}})
    fields, low = parse(resp)
    doc_id = uuid.uuid4().hex[:12]
    flags = check(fields, low, db.query_prefix(pk, "DOC#", limit=300), db.query_prefix(pk, "XINV#", limit=300))
    doc = {"PK": pk, "SK": f"DOC#{doc_id}", "docId": doc_id, "s3Key": key, "fileName": key.rsplit("/", 1)[-1], "status": "needs_review", "flags": flags,
           "confidence": round(low), "createdAt": now, **fields}
    db.table().put_item(Item=db.to_ddb(doc))
    tasks.create(pk, f"doc-{doc_id}", "document_review", f"Review {fields.get('supplier') or 'document'} {fields.get('invoiceNumber') or ''}".strip(),
                 status="needs_approval", priority="high" if flags else "normal", channel="document", action="document_review", docId=doc_id,
                 detail=("; ".join(flags) if flags else "No problems found. Approve to confirm the details are right."))
    events.record(pk, "doc_extracted", doc_id, at=now, flags=len(flags))
    return {k: v for k, v in doc.items() if k not in ("PK", "SK")}


def decide(pk: str, doc_id: str, approved: bool) -> None:
    db.update({"PK": pk, "SK": f"DOC#{doc_id}"}, sets={"status": "approved" if approved else "rejected", "decidedAt": int(time.time())})
