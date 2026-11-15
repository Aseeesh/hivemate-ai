"""HTTP for connectors: JSON in/out, retries with backoff on throttling and server errors. No third-party dependency."""
import json
import time
import urllib.error
import urllib.parse
import urllib.request

RETRY_STATUS = {429, 500, 502, 503, 504}


class HttpError(Exception):
    def __init__(self, status: int, body: str):
        super().__init__(f"HTTP {status}: {body[:200]}")
        self.status, self.body = status, body


def _open(req: urllib.request.Request, timeout: float):
    """Returns (status, headers, bytes). Isolated so tests can replace it."""
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 - https URLs only, built by connectors
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def request(method: str, url: str, *, headers: dict | None = None, form: dict | None = None, body: dict | None = None,
            timeout: float = 15, retries: int = 3, sleep=None) -> tuple[int, dict | str, dict]:
    if not url.startswith("https://"):
        raise ValueError("connectors only talk to https URLs")
    hdrs = {"accept": "application/json", **(headers or {})}
    data = None
    if form is not None:
        data, hdrs["content-type"] = urllib.parse.urlencode(form).encode(), "application/x-www-form-urlencoded"
    elif body is not None:
        data, hdrs["content-type"] = json.dumps(body).encode(), "application/json"
    last = None
    for attempt in range(retries + 1):
        try:
            status, rh, raw = _open(urllib.request.Request(url, data=data, headers=hdrs, method=method), timeout)
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:  # network trouble is retried like a 503
            status, rh, raw = 599, {}, str(exc).encode()
        if status in RETRY_STATUS or status == 599:
            last = HttpError(status, raw.decode("utf-8", "replace"))
            if attempt < retries:
                wait = min(30.0, float(next((v for k, v in rh.items() if k.lower() == "retry-after"), 0)) or 0.5 * 2 ** attempt)
                (sleep or time.sleep)(wait)
                continue
            raise last
        text = raw.decode("utf-8", "replace")
        if status >= 400:
            raise HttpError(status, text)
        try:
            return status, (json.loads(text) if text.strip() else {}), rh
        except ValueError:
            return status, text, rh
    raise last  # pragma: no cover
