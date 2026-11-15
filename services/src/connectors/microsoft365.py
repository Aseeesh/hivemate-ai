"""Microsoft 365 (Outlook mail) via Microsoft Graph. Reads the inbox, writes drafts and sends from the owner's own mailbox.

Environment: MS_CLIENT_ID, MS_CLIENT_SECRET, optional MS_AUTHORITY (default "common"), WEBHOOK_BASE (public URL, enables push notifications).
Scopes are delegated and minimal: read/write mail and send. Nothing about calendars or files is requested.
"""
import hmac
import secrets
import time
import urllib.parse
from datetime import datetime, timezone

from src.connectors import appconfig, http
from src.connectors.base import AuthExpired, Connector, envelope, with_expiry

GRAPH = "https://graph.microsoft.com/v1.0"
SCOPES = "offline_access User.Read Mail.ReadWrite Mail.Send"
SKIP_SENDERS = ("noreply", "no-reply", "donotreply", "do-not-reply", "mailer-daemon", "postmaster", "notifications@")
FIRST_SYNC_WINDOW = 86400       # a new connection only looks at the last day: never draft replies to someone's old mail
RECONCILE_WINDOW = 3 * 86400
MAX_PAGES = 4
SUB_MINUTES = 4200              # Graph allows up to 4230 minutes for mail subscriptions


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Microsoft365(Connector):
    provider = "microsoft365"
    label = "Microsoft 365 (Outlook)"
    write_actions = ("send_mail", "create_draft_reply")

    def _authority(self) -> str:
        return f"https://login.microsoftonline.com/{appconfig.get('MS_AUTHORITY', 'common')}/oauth2/v2.0"

    def configured(self) -> bool:
        return bool(appconfig.get("MS_CLIENT_ID") and appconfig.get("MS_CLIENT_SECRET"))

    def authorize_url(self, state: str, redirect_uri: str) -> str:
        q = urllib.parse.urlencode({"client_id": appconfig.get("MS_CLIENT_ID"), "response_type": "code", "redirect_uri": redirect_uri,
                                    "response_mode": "query", "scope": SCOPES, "state": state, "prompt": "select_account"})
        return f"{self._authority()}/authorize?{q}"

    def _token(self, form: dict, previous: dict | None = None) -> dict:
        _, body, _ = http.request("POST", f"{self._authority()}/token", form={
            "client_id": appconfig.get("MS_CLIENT_ID"), "client_secret": appconfig.get("MS_CLIENT_SECRET"), "scope": SCOPES, **form})
        return with_expiry(body, previous)

    def exchange_code(self, code: str, redirect_uri: str) -> dict:
        return self._token({"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri})

    def refresh(self, tokens: dict) -> dict:
        try:
            return self._token({"grant_type": "refresh_token", "refresh_token": tokens["refresh_token"]}, tokens)
        except http.HttpError as exc:
            if exc.status in (400, 401) and "invalid_grant" in exc.body:
                raise AuthExpired("Microsoft refused the refresh token") from exc
            raise

    def _get(self, tokens: dict, url: str, **kw):
        return http.request("GET", url, headers={"authorization": f"Bearer {tokens['access_token']}", "prefer": 'outlook.body-content-type="text"'}, **kw)[1]

    def account_info(self, tokens: dict) -> dict:
        me = self._get(tokens, f"{GRAPH}/me?$select=mail,userPrincipalName,id")
        return {"label": me.get("mail") or me.get("userPrincipalName") or "Outlook mailbox", "externalId": me.get("id", "")}

    def pull(self, tokens: dict, conn: dict, reconcile: bool, now: float | None = None):
        now = now or time.time()
        cp = dict(conn.get("checkpoint") or {})
        if cp.get("receivedAfter") and not reconcile:
            since = cp["receivedAfter"]
        else:
            floor = _iso(now - (RECONCILE_WINDOW if cp.get("receivedAfter") else FIRST_SYNC_WINDOW))
            since = min(floor, cp["receivedAfter"]) if cp.get("receivedAfter") else floor
        own = (conn.get("label") or "").lower()
        url = (f"{GRAPH}/me/mailFolders/inbox/messages?$filter=" + urllib.parse.quote(f"receivedDateTime ge {since}") +
               "&$orderby=receivedDateTime asc&$top=25&$select=id,subject,from,receivedDateTime,body")
        evs, newest = [], cp.get("receivedAfter") or since
        for _ in range(MAX_PAGES):
            page = self._get(tokens, url)
            for m in page.get("value", []):
                addr = ((m.get("from") or {}).get("emailAddress") or {})
                sender = (addr.get("address") or "").strip().lower()
                newest = max(newest, m["receivedDateTime"])
                if not sender or sender == own or any(s in sender for s in SKIP_SENDERS):
                    continue
                evs.append(envelope(self.provider, "email.received", m["id"], m["id"], m["receivedDateTime"],
                                    {"from": sender, "fromName": (addr.get("name") or "")[:100], "subject": (m.get("subject") or "")[:300],
                                     "body": ((m.get("body") or {}).get("content") or "")[:4000]}))
            url = page.get("@odata.nextLink")
            if not url:
                break
        extra = self._maintain_subscription(tokens, conn, now)
        return evs, {"receivedAfter": newest}, extra

    # ---- push notifications (optional; polling alone is correct, push only makes it faster) ----
    def _maintain_subscription(self, tokens: dict, conn: dict, now: float) -> dict:
        base = appconfig.get("WEBHOOK_BASE", "").rstrip("/")
        if not base:
            return {}
        exp = conn.get("subscriptionExpires", 0)
        hdr = {"authorization": f"Bearer {tokens['access_token']}"}
        try:
            if conn.get("subscriptionId") and exp - now > 86400:
                return {}
            expires = _iso(now + SUB_MINUTES * 60)
            if conn.get("subscriptionId") and exp > now:
                http.request("PATCH", f"{GRAPH}/subscriptions/{urllib.parse.quote(conn['subscriptionId'], safe='')}", headers=hdr, body={"expirationDateTime": expires})
                return {"subscriptionExpires": int(now + SUB_MINUTES * 60)}
            state = conn.get("clientState") or secrets.token_urlsafe(24)
            _, sub, _ = http.request("POST", f"{GRAPH}/subscriptions", headers=hdr, body={
                "changeType": "created", "notificationUrl": f"{base}/webhooks/microsoft365", "resource": "me/mailFolders('inbox')/messages",
                "expirationDateTime": expires, "clientState": state})
            return {"subscriptionId": sub["id"], "subscriptionExpires": int(now + SUB_MINUTES * 60), "clientState": state, "webhookKey": sub["id"]}
        except http.HttpError:
            return {}  # push is best effort; the scheduled poll still runs

    def execute(self, tokens: dict, conn: dict, action: str, params: dict) -> dict:
        hdr = {"authorization": f"Bearer {tokens['access_token']}"}
        if action == "send_mail":
            http.request("POST", f"{GRAPH}/me/sendMail", headers=hdr, body={"message": {
                "subject": str(params["subject"])[:200], "body": {"contentType": "Text", "content": str(params["body"])[:20000]},
                "toRecipients": [{"emailAddress": {"address": str(params["to"])}}]}, "saveToSentItems": True})
            return {"sent": True}
        if action == "create_draft_reply":
            _, draft, _ = http.request("POST", f"{GRAPH}/me/messages/{urllib.parse.quote(str(params['messageId']), safe='')}/createReply",
                                       headers=hdr, body={"comment": str(params["body"])[:20000]})
            return {"draftId": draft.get("id", "")}
        raise ValueError(action)

    def verify_webhook(self, headers: dict, body: bytes, query: dict, conn_lookup) -> tuple[bool, dict]:
        token = query.get("validationToken")
        if token:  # Graph's endpoint-ownership handshake: echo the token as plain text
            return True, {"statusCode": 200, "headers": {"content-type": "text/plain"}, "body": token}
        import json
        try:
            notes = json.loads(body or b"{}").get("value", [])
        except ValueError:
            return False, {}
        if not notes:
            return False, {}
        for n in notes:
            conn = conn_lookup(str(n.get("subscriptionId", "")))
            if not conn or not hmac.compare_digest(str(n.get("clientState", "")), str(conn.get("clientState", "x"))):
                return False, {}
        return True, {}
