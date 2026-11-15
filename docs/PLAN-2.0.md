# Hivemate 2.0 implementation plan (tracks `BACKLOG-2.0.md`)

All items below are implemented and unit-tested. "Tested" means against fakes and recorded provider responses; nothing was run against live AWS, Microsoft or Xero. Live checks are in `GO-LIVE.md`.

Order matters: each step is testable on its own and later steps reuse earlier ones. Tick when done AND covered by tests.

## Foundations
- [x] F1 `common/db.py`: conditional create / update helpers (idempotency, claims)
- [x] F2 `common/events.py`: append-only business events (source of every metric)
- [x] F3 `common/policy.py`: per-action modes (assist/approve/automate), cadence, minutes-per-task, pauses, send window
- [x] F4 `tests/fakedb.py`: in-memory DynamoDB double so logic is tested without AWS

## R1 Follow-up engine + Work Queue
- [x] R1.1 `pipeline/deals.py`: deal state machine (new/responded/quote_sent/followed_up/won/lost/cold), awaiting business|customer, due times, recovery
- [x] R1.2 `pipeline/followups.py`: sweeper logic, drafts, claim-before-act, policy-driven send/approve/assist, cold escalation, idempotent send
- [x] R1.3 `api/workqueue.py`: work list + filters, approve/reject/done/snooze/assign, deals + stage, policy, inbox merge
- [x] R1.4 hooks: chat agent, email processor, approve endpoint, conversation status
- [x] R1.5 `workers/sweeper.py` + CDK schedule (every 15 min)

## R2 Measured impact
- [x] R2.1 `pipeline/impact.py`: metrics computed only from events; estimated vs measured kept separate
- [x] R2.2 `GET /impact`, owner-editable minutes
- [x] R2.3 BI assistant (`pipeline/ask.py`): deterministic intents, every answer returns calculation + source records

## R3 Connector framework + connectors
- [x] R3.1 `connectors/http.py` retry/backoff, `credstore.py` (Secrets Manager), `base.py`, `runtime.py` (OAuth state, refresh, sync + checkpoints, idempotent execute, reconcile, health, alerts)
- [x] R3.2 `connectors/microsoft365.py` read (inbox) + write (draft reply, send)
- [x] R3.3 `connectors/xero.py` read (overdue invoices) + write (history note); `pipeline/invoices.py` reminder tasks, paid detection
- [x] R3.4 `channels/webhooks.py`: signature/clientState verification, dedupe, trigger sync
- [x] R3.5 `api/connections.py`: list/health, start OAuth, callback, sync now, disconnect

## R4
- [x] R4.1 Customer 360 (`pipeline/customers.py`)
- [x] R4.2 Automation packs (`pipeline/packs.py`)
- [x] R4.3 Document intelligence (`pipeline/docintel.py`, Textract AnalyzeExpense, GST/duplicate checks, approval task)

## Dashboard
- [x] W1 Navigation by outcome: Overview, Work Queue, Conversations, Customers, Automations, Integrations, Impact, Ask, Knowledge, Settings
- [x] W2 Work Queue with inline approve/reject/edit, filters, assign
- [x] W3 Impact page, Automations (modes, cadence, pause), Integrations health, Ask, Customer 360, Packs, Documents extraction

## Infra and gaps
- [x] I1 CDK: worker Lambda + schedule, webhook/callback routes, Secrets Manager + Textract + lambda:Invoke permissions, DLQ alarm
- [x] I2 Cross-tenant isolation tests (forged tenantId, tool args, KB filter)
- [x] I3 Platform console: hourly rollup + per-tenant query replace per-request scans (no counters or backfill needed)
- [x] I4 Docs: README, INTEGRATIONS, runbook for what the owner must do (Microsoft/Xero app registration, SES, WhatsApp)
- [x] I5 Full test run, tsc, web build, cdk synth

## Not code (cannot be done from here; listed in docs/GO-LIVE.md)
Registering Microsoft/Xero OAuth apps, SES production access, a real WhatsApp number, Google restricted-scope review.
