"""Ship Hivemate's model-call logs from CloudWatch to an LLMScope (OTLP/HTTP) endpoint. Run it from your laptop.

    AWS_PROFILE=hivemate python tools/llmscope_ship.py --since 120            # one pass
    AWS_PROFILE=hivemate python tools/llmscope_ship.py --watch                # keep shipping every 30 s

Reads only the metadata log lines written by services/src/common/llmlog.py (model, tokens, latency, hashed tenant).
No message text exists in those lines, so nothing customer-written is sent. Needs: boto3, requests.
The Lambdas send nothing anywhere; this script pulls, so no public endpoint or extra Lambda dependency is needed.
"""
import argparse, json, os, secrets, time
import boto3, requests

LOG_GROUP_PREFIX = "/aws/lambda/hivemate-dev-api-"
# USD per 1M tokens. ESTIMATES for Amazon Nova: confirm against the Bedrock price list for ap-southeast-2 before relying on cost figures.
PRICES = {"nova-lite": (0.06, 0.24), "nova-pro": (0.80, 3.20), "nova-micro": (0.035, 0.14)}


def price(model: str) -> tuple[float, float]:
    return next((v for k, v in PRICES.items() if k in (model or "")), (0.0, 0.0))


def attr(k, v):
    if isinstance(v, bool): return {"key": k, "value": {"boolValue": v}}
    if isinstance(v, int): return {"key": k, "value": {"intValue": str(v)}}
    return {"key": k, "value": {"stringValue": str(v)}}


def ns(ms: float) -> str:
    return str(int(ms * 1_000_000))


def span(rec: dict, end_ms: int) -> dict:
    start_ms = end_ms - rec.get("latencyMs", 0)
    if rec["event"] == "guardrail_call":
        name, attrs = f"guardrail {rec.get('source', '')}", [attr("hivemate.guardrail.action", rec.get("action", ""))]
    else:
        m = rec.get("model", "unknown")
        i, o = rec.get("inputTokens", 0), rec.get("outputTokens", 0)
        pi, po = price(m)
        attrs = [attr("gen_ai.operation.name", rec.get("operation", "chat")), attr("gen_ai.provider.name", rec.get("provider", "aws.bedrock")),
                 attr("gen_ai.request.model", m), attr("gen_ai.response.model", m), attr("gen_ai.usage.input_tokens", i),
                 attr("gen_ai.usage.output_tokens", o), attr("llmscope.cost.usd", round(i * pi / 1e6 + o * po / 1e6, 8))]
        if rec.get("stopReason"): attrs.append({"key": "gen_ai.response.finish_reasons", "value": {"arrayValue": {"values": [{"stringValue": rec["stopReason"]}]}}})
        if rec.get("error"): attrs.append(attr("error.type", rec["error"]))
        name = f"{rec.get('operation', 'chat')} {m}"
    attrs += [attr("hivemate.component", rec.get("component", "")), attr("hivemate.tenant", rec.get("tenant", ""))]
    return {"traceId": secrets.token_hex(16), "spanId": secrets.token_hex(8), "name": name, "kind": 3,
            "startTimeUnixNano": ns(start_ms), "endTimeUnixNano": ns(end_ms), "attributes": attrs,
            "status": {"code": 2 if rec.get("error") else 1}}


def fetch(logs, since_ms: int, seen: set):
    out = []
    for g in logs.describe_log_groups(logGroupNamePrefix=LOG_GROUP_PREFIX)["logGroups"]:
        kw = {"logGroupName": g["logGroupName"], "startTime": since_ms, "filterPattern": '{ $.app = "hivemate" }'}
        while True:
            r = logs.filter_log_events(**kw)
            for e in r["events"]:
                if e["eventId"] in seen: continue
                seen.add(e["eventId"])
                try: rec = json.loads(e["message"])
                except ValueError: continue
                if rec.get("event") in ("llm_call", "guardrail_call"): out.append((rec, e["timestamp"]))
            if "nextToken" not in r: break
            kw["nextToken"] = r["nextToken"]
    return out


def ship(endpoint: str, events: list, totals: dict, started_ms: int) -> None:
    res = {"attributes": [attr("service.name", "hivemate"), attr("deployment.environment", "dev")]}  # capture_content deliberately not set
    spans = [span(r, ts) for r, ts in events]
    requests.post(f"{endpoint}/v1/traces", json={"resourceSpans": [{"resource": res, "scopeSpans": [{"scope": {"name": "hivemate-ship"}, "spans": spans}]}]}, timeout=20).raise_for_status()
    for r, _ in events:
        if r["event"] != "llm_call" or r.get("error"): continue
        m, p = r.get("model", "unknown"), r.get("provider", "aws.bedrock")
        pi, po = price(m)
        for kind, n in (("input", r.get("inputTokens", 0)), ("output", r.get("outputTokens", 0))):
            totals["tok"][(m, p, kind)] = totals["tok"].get((m, p, kind), 0) + n
        totals["cost"][(m, p)] = totals["cost"].get((m, p), 0.0) + r.get("inputTokens", 0) * pi / 1e6 + r.get("outputTokens", 0) * po / 1e6
    now = ns(time.time() * 1000)
    tok = [{"attributes": [attr("gen_ai.request.model", m), attr("gen_ai.provider.name", p), attr("gen_ai.token.type", k)], "startTimeUnixNano": ns(started_ms),
            "timeUnixNano": now, "asInt": str(v)} for (m, p, k), v in totals["tok"].items()]
    cost = [{"attributes": [attr("gen_ai.request.model", m), attr("gen_ai.provider.name", p)], "startTimeUnixNano": ns(started_ms), "timeUnixNano": now, "asDouble": v}
            for (m, p), v in totals["cost"].items()]
    metrics = [{"name": "gen_ai.client.token.usage", "unit": "{token}", "sum": {"dataPoints": tok, "aggregationTemporality": 2, "isMonotonic": True}},
               {"name": "llmscope.cost", "unit": "USD", "sum": {"dataPoints": cost, "aggregationTemporality": 2, "isMonotonic": True}}]
    requests.post(f"{endpoint}/v1/metrics", json={"resourceMetrics": [{"resource": res, "scopeMetrics": [{"scope": {"name": "hivemate-ship"}, "metrics": metrics}]}]}, timeout=20).raise_for_status()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--endpoint", default=os.environ.get("LLMSCOPE_OTLP", "http://localhost:4318"))
    ap.add_argument("--since", type=int, default=60, help="minutes of history on the first pass")
    ap.add_argument("--watch", action="store_true")
    a = ap.parse_args()
    logs = boto3.Session(profile_name=os.environ.get("AWS_PROFILE"), region_name="ap-southeast-2").client("logs")
    seen, totals, started = set(), {"tok": {}, "cost": {}}, int(time.time() * 1000)
    since = int((time.time() - a.since * 60) * 1000)
    while True:
        events = fetch(logs, since, seen)
        if events:
            ship(a.endpoint, events, totals, started)
            since = max(ts for _, ts in events) - 1000
        print(f"shipped {len(events)} events ({sum(1 for r, _ in events if r['event'] == 'llm_call')} model calls)", flush=True)
        if not a.watch: break
        time.sleep(30)


if __name__ == "__main__":
    main()
