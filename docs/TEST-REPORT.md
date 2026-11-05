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
- LLMScope: red-team package is a skeleton. (Hivemate log lines were added to Log Search afterwards: 109 model calls backfilled, verified in Loki and in the dashboard.)
- Model cost uses estimated Nova prices.

## Hosted site, browser check (6 Nov 2026, business admin signed in by the owner)
| Check | Result |
|---|---|
| Sign-in and profile from the CloudFront origin | works |
| Inbox, Agent, Plugins, Documents, Audit tabs load real data, no console errors | works |
| Business admin opening `/platform/` is redirected to `/dashboard/`, no "Platform console" button | works |
| Install Conversation Agent from the Plugins tab | works |
| Test chat: honest "no details yet" answer, lead captured (name, phone, need), marked COMPLETE | works |
| AI summary no longer claims anything was confirmed | works |
| Audit tab shows plugin.configured, conversation.turn, owner.notified.lead | works |
| Documents "last sync" is the business's own (shows "never") | fixed and verified |

Found: the owner alert email failed (`MessageRejected`, address not verified): SES is in sandbox, so alerts only reach verified addresses.
Found: a place name ("Hamilton") was stored in `need`, not `location` (known gap).

Not yet verified: the super admin console in a browser and the authenticated `tests/e2e/console_e2e.py` run (need the owner's passwords and a member in `platform-admins`); document upload and the Inbox test email on the hosted site.

### Further browser checks on the hosted site (same session)
| Check | Result |
|---|---|
| Conversation transcript opens | works |
| Website embed code created with the live public chat URL and a site key | works |
| Complaint -> handoff: safe reply, HANDOFF badge, lead with reason and summary | works |
| "Give back to the agent" sets the conversation back to OPEN | works; the lead card stayed HANDOFF (fixed, unit-tested, not re-clicked) |
| Document upload from the browser to S3 (CORS + CSP) | works |
| Sync knowledge, per-business status COMPLETE | works |
| Agent answers from the uploaded file ($55/hour, closed weekends) | works |
| Install Email Automation, send test email, AI draft correct, held PENDING_APPROVAL (low confidence) | works |
| Reject a draft; audit trail shows upload, sync, installs, turns, draft, rejection | works |
| Success message in the Inbox looked like an error (red) | fixed |
| Owner alert emails (lead and handoff) | fail: SES sandbox, address unverified |
