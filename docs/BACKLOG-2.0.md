# Hivemate 2.0: backlog grounded in the current codebase

Source: external product review (positioning: "AI operations layer on top of existing software"). This file maps that advice
onto what already exists, and keeps only what is worth building next. Status as of the commit `e72fe03`.

## 1. What the review asks for vs what already exists

| Review item | Already in repo | Real gap |
|---|---|---|
| Don't replace their software | `docs/INTEGRATIONS.md`: Gmail drafts via owner's Apps Script, widget, WhatsApp after-hours | No connector framework; no OAuth; Gmail only |
| Unified inbox | `Inbox.tsx` (approval queue for email), conversations in the Agent tab | Channels are not one list; no assignment, no categories |
| Owner dashboard | `Home.tsx` (what it did, needs-you list, setup steps), `charts.tsx` | No work queue, no filters, no "why did it say this" |
| Lead recovery | Unanswered-question loop, lead capture with owner alert | **No follow-up scheduling, no quote/lead states, no cold-lead escalation** |
| Approve / assist / automate | Approval gate on email, draft-first Gmail | Modes are not a per-action policy the owner can set |
| ROI reporting | Audit trail, per-tenant counters | No event-derived time-saved, response-time or recovery metrics |
| Workflow engine | EventBridge + SQS + DLQ | No scheduler, no workflow state, no run history |
| Integration health | n/a (one connector) | Needed as soon as there are two |
| Tenant isolation | JWT-only `tenantId`, KB metadata filter, two-tenant test | No adversarial cross-tenant retrieval test in CI |

Most of "Release 1" in the review is partly built. The missing core is **time**: follow-ups, reminders and measured outcomes.

## 2. Recommendation: do not start with a visual builder or Step Functions

A drag-and-drop builder is the most expensive item and the one customers ask for least. The first offer
("Business Response & Follow-up") needs three fixed, well-tuned flows. Build those as code with an
owner-editable settings panel; add a builder only after pilots show owners want to change the flow itself.

## 3. Release plan

### R1: Follow-up engine and Work Queue (the sellable core)
- `LEAD#id` state machine: `new → responded → quote_sent → followed_up → won | lost | cold`. Created from chat leads and email enquiries.
- `TASK#id` work item (type, due, owner, source record, status). One list the dashboard reads: overdue, due today, needs approval, failed.
- EventBridge Scheduler: one-off schedule per follow-up (24h no reply, quote after 3 days, cold after 7). Handler is a Lambda that re-checks state before acting, so a reply cancels the follow-up implicitly.
- Follow-up drafts go through the existing approval gate (Approve mode); acknowledgements may auto-send (Automate mode).
- Per-tenant `policy` record: for each action (acknowledge, follow-up, quote, refund) choose assist / approve / automate. Default approve; refunds and quotes can never be automate.
- Dashboard: Work Queue tab, filters (status, channel, date), inline approve/reject, click KPI to records.
- Idempotency key on every outbound send (`tenant#record#action#attempt`), conditional put before sending.

### R2: Measured impact
- Emit one `EVENT#` row per meaningful step (received, first_response, followup_sent, approved, recovered, failed) with timestamps.
- Metrics computed from those rows only: median first-response time, enquiries with follow-up %, leads recovered (cold or overdue then replied), tasks completed × owner-editable minutes per task type.
- Label "estimated" (time saved) vs "measured" (response time, recovered leads). Business Impact page + weekly summary email.
- Replace console table scans with counters while here (known gap).

### R3: Connector framework + first two connectors
- `INTEGRATION#`, `CONNECTION#`, `SYNC#provider` records. Tokens in Secrets Manager (never in the table); store only the secret ARN and status.
- Interface: `authorize`, `refresh`, `verify_webhook`, `pull(since_checkpoint)`, `execute(action, idempotency_key)`; shared retry with backoff, DLQ + redrive, reconciliation job.
- Connectors, in order: **Microsoft 365 mail/calendar** (largest NZ share, closes the Outlook gap), then **Xero read + reminder drafts** (overdue invoice follow-up reuses R1 engine). Google OAuth only after Google's restricted-scope review is realistic; the Apps Script route stays.
- Integration Health tab: last sync, token expiry, failed webhooks, retry button.

### R4: Later, only on pilot demand
Customer 360, document intelligence (Textract), packs marketplace, visual builder, Shopify/HubSpot/Stripe, BI chat (must cite source rows and calculations).

## 4. Close before charging anyone
1. Live-test WhatsApp on a real number (still only fixtures).
2. SES out of sandbox; inbound email (domain + SES receiving) or keep Gmail/Outlook drafts as the inbound path.
3. Exercise hosted dashboard auth end to end (signup, confirm, login, token expiry).
4. Chat abuse test (rate limits under load) plus CloudWatch alarms on the public API.
5. Cross-tenant adversarial retrieval tests in CI: tenant A prompts that ask for B's data, forged `tenantId` in tool arguments, KB filter bypass attempts.
6. Lambda concurrency quota increase (still open in the roadmap).

## 5. Pilot and success metrics
Target: 1 cleaning company, then 1 trades business, 4-week pilot with a before/after baseline taken in week 0.
Measure: median first-response time, % enquiries followed up, leads recovered, owner minutes saved, manual interventions per week, % of drafts sent unedited.
Decision rule: if response time and follow-up rate do not improve in all three pilots, fix the product before adding connectors.

## 6. Suggested first task
R1 slice 1: `LEAD#` state + `TASK#` records + one Scheduler-driven "no reply after 24h" follow-up draft that lands in the Inbox approval queue.
Small, demoable end to end, and every later release reuses it.
