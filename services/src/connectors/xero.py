"""Xero (accounting). Reads outstanding invoices; writes a history note on the invoice when a reminder is sent.
Financial records stay in Xero: Hivemate keeps only a small cache (number, customer, amount, due date) to coordinate the chasing.

Environment: XERO_CLIENT_ID, XERO_CLIENT_SECRET, XERO_WEBHOOK_KEY (from the Xero app's webhook settings), XERO_SCOPES (optional).
Check the scope names against your app in developer.xero.com: apps created after Xero's 2026 scope change use granular scopes.
"""
import base64
import hashlib
import hmac
import re
import time
import urllib.parse
from datetime import datetime, timezone

from src.connectors import appconfig, http
from src.connectors.base import AuthExpired, Connector, envelope, with_expiry

API = "https://api.xero.com/api.xro/2.0"
IDENTITY = "https://identity.xero.com/connect/token"
DEFAULT_SCOPES = "offline_access accounting.transactions accounting.contacts.read"
GUID = re.compile(r"^[0-9a-fA-F-]{36}$")
PAGE = 100
MAX_PAGES = 20


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


class Xero(Connector):
    provider = "xero"
    label = "Xero"
    write_actions = ("add_history_note",)

    def configured(self) -> bool:
        return bool(appconfig.get("XERO_CLIENT_ID") and appconfig.get("XERO_CLIENT_SECRET"))

    def authorize_url(self, state: str, redirect_uri: str) -> str:
        q = urllib.parse.urlencode({"response_type": "code", "client_id": appconfig.get("XERO_CLIENT_ID"), "redirect_uri": redirect_uri,
                                    "scope": appconfig.get("XERO_SCOPES", DEFAULT_SCOPES), "state": state})
        return f"https://login.xero.com/identity/connect/authorize?{q}"

    def _token(self, form: dict, previous: dict | None = None) -> dict:
        basic = base64.b64encode(f"{appconfig.get('XERO_CLIENT_ID')}:{appconfig.get('XERO_CLIENT_SECRET')}".encode()).decode()
        _, body, _ = http.request("POST", IDENTITY, headers={"authorization": f"Basic {basic}"}, form=form)
        return with_expiry(body, previous)

    def exchange_code(self, code: str, redirect_uri: str) -> dict:
        return self._token({"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri})

    def refresh(self, tokens: dict) -> dict:
        try:  # Xero rotates the refresh token on every use; the caller persists the new one
            return self._token({"grant_type": "refresh_token", "refresh_token": tokens["refresh_token"]}, tokens)
        except http.HttpError as exc:
            if exc.status in (400, 401):
                raise AuthExpired("Xero refused the refresh token") from exc
            raise

    def account_info(self, tokens: dict) -> dict:
        _, conns, _ = http.request("GET", "https://api.xero.com/connections", headers={"authorization": f"Bearer {tokens['access_token']}"})
        orgs = [c for c in (conns if isinstance(conns, list) else []) if c.get("tenantType") == "ORGANISATION"]
        if not orgs:
            raise http.HttpError(400, "no Xero organisation was authorised")
        return {"label": orgs[0].get("tenantName", "Xero organisation"), "externalId": orgs[0]["tenantId"]}

    def _hdr(self, tokens: dict, conn: dict, extra: dict | None = None) -> dict:
        return {"authorization": f"Bearer {tokens['access_token']}", "xero-tenant-id": conn["externalId"], **(extra or {})}

    def pull(self, tokens: dict, conn: dict, reconcile: bool, now: float | None = None):
        now = now or time.time()
        cp = dict(conn.get("checkpoint") or {})
        incremental = bool(cp.get("modifiedAfter")) and not reconcile
        statuses = "AUTHORISED,PAID,VOIDED" if incremental else "AUTHORISED"
        extra_hdr = {"if-modified-since": cp["modifiedAfter"]} if incremental else {}
        invoices, page = [], 1
        while page <= MAX_PAGES:
            q = urllib.parse.urlencode({"Statuses": statuses, "where": 'Type=="ACCREC"', "page": page, "order": "DueDate"})
            _, body, _ = http.request("GET", f"{API}/Invoices?{q}", headers=self._hdr(tokens, conn, extra_hdr))
            batch = body.get("Invoices", []) if isinstance(body, dict) else []
            invoices += batch
            if len(batch) < PAGE:
                break
            page += 1
        today = datetime.fromtimestamp(now, timezone.utc).strftime("%Y-%m-%d")
        emails = self._contact_emails(tokens, conn, {i["Contact"]["ContactID"] for i in invoices
                                                      if i.get("Status") == "AUTHORISED" and (i.get("DueDateString") or "")[:10] < today and i.get("Contact")})
        evs = []
        for i in invoices:
            c = i.get("Contact") or {}
            data = {"invoiceId": i["InvoiceID"], "number": i.get("InvoiceNumber", ""), "contactName": c.get("Name", ""),
                    "contactEmail": emails.get(c.get("ContactID"), ""), "status": i.get("Status", ""), "total": float(i.get("Total", 0)),
                    "amountDue": float(i.get("AmountDue", 0)), "currency": i.get("CurrencyCode", "NZD"),
                    "dueDate": (i.get("DueDateString") or "")[:10], "date": (i.get("DateString") or "")[:10]}
            evs.append(envelope(self.provider, "invoice.updated", f"{i['InvoiceID']}:{data['status']}:{data['amountDue']}:{data['contactEmail']}",
                                i["InvoiceID"], _iso(now), data))
        if not incremental:  # the full outstanding list lets Hivemate notice invoices that were paid without any event reaching it
            evs.append(envelope(self.provider, "invoice.snapshot", f"snapshot:{int(now // 3600)}", "snapshot", _iso(now),
                                {"outstandingIds": [i["InvoiceID"] for i in invoices]}))
        return evs, {"modifiedAfter": _iso(now - 60)}, {}

    def _contact_emails(self, tokens: dict, conn: dict, ids: set) -> dict:
        out, ids = {}, sorted(i for i in ids if GUID.match(i))
        for n in range(0, len(ids), 40):
            _, body, _ = http.request("GET", f"{API}/Contacts?" + urllib.parse.urlencode({"IDs": ",".join(ids[n:n + 40])}), headers=self._hdr(tokens, conn))
            for c in body.get("Contacts", []) if isinstance(body, dict) else []:
                if c.get("EmailAddress"):
                    out[c["ContactID"]] = c["EmailAddress"]
        return out

    def execute(self, tokens: dict, conn: dict, action: str, params: dict) -> dict:
        if action != "add_history_note":
            raise ValueError(action)
        inv = str(params["invoiceId"])
        if not GUID.match(inv):
            raise ValueError("invalid invoice id")
        http.request("PUT", f"{API}/Invoices/{inv}/History", headers=self._hdr(tokens, conn),
                     body={"HistoryRecords": [{"Details": str(params["text"])[:2400]}]})
        return {"noted": True}

    def verify_webhook(self, headers: dict, body: bytes, query: dict, conn_lookup) -> tuple[bool, dict]:
        key = appconfig.get("XERO_WEBHOOK_KEY", "")
        sig = next((v for k, v in headers.items() if k.lower() == "x-xero-signature"), "")
        if not key:
            return False, {}
        good = base64.b64encode(hmac.new(key.encode(), body, hashlib.sha256).digest()).decode()
        return hmac.compare_digest(good, sig), {}
