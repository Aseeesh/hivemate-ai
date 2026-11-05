# Test report, 6 Nov 2026 (dev)

Both projects were tested from a clean state: Hivemate on the deployed ap-southeast-2 stack, LLMScope on the local Docker stack.

## Hivemate
| Check | Result |
|---|---|
| Unit tests (pytest) | 30 passed |
| Infra type-check, `cdk synth`, web type-check | clean |
| `tests/e2e/e2e.py` (core platform, 51 checks) | 51/51 |
| `tests/e2e/agent_e2e.py` (conversation agent) | 38/38 |
| `tests/e2e/public_chat_e2e.py` (public website chat) | 25/25 |
| Agent evaluation (`tests/eval`, 22 cases x 3) | 94% of runs (Nova Pro); see docs/EVAL.md |
| DLQ alarm after the run | OK, queue empty |

## LLMScope
| Check | Result |
|---|---|
| ruff, mypy (51 files) | clean |
| pytest | 115 passed |
| `scripts/smoke_test.py` against the live stack | OK |
| Containers: server, proxy, Grafana (lgtm) | healthy |
| Hivemate data in Cost Watch, Overview, Traces, Guardrails | visible after the fixes below |

## Problems found and fixed
1. **LLMScope dashboards showed "No data" for every project.** The Project dropdown read a span-metrics series that labels the project `service`, not `service_name`, so it was empty and all panels filtered to nothing. Overview's calls, latency and error panels had the same wrong label. Fixed in `dashboards/*.json` (LLMScope commit d65a2d4). Error rate now shows 0 instead of "No data".
2. **Hivemate e2e load check failed (HTTP 503).** The check used 20 parallel requests but this account's Lambda concurrency limit is 10. It now uses 8.
3. **Hivemate e2e DLQ check failed early.** A stale poison message from an earlier run made the receive loop return instantly. The loop now polls against a deadline and clears stale poison messages. That message had also left the DLQ alarm in ALARM; it is now OK.

## Not covered
- Hivemate on a real WhatsApp number (simulated only); voice calling (not built); the dashboard is local only.
- LLMScope: Hivemate's Loki log panel has no Hivemate lines (only spans and metrics are shipped); red-team package is a skeleton.
- Model cost uses estimated Nova prices.
