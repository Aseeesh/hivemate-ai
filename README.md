# Hivemate AI

Multi-tenant, plugin-based AI automation platform for NZ SMEs, built serverless-first on AWS.

## Architecture (implemented so far)

```
Client ─► API Gateway (HTTP, Cognito JWT) ─► ApiFn ─► DynamoDB (single table, tenant-partitioned)
                                               │
                                               └─► EventBridge bus ─► rule(email.received) ─► SQS (+DLQ)
                                                                                          │
                                       Email plugin Lambda ◄──────────────────────────────┘
                                         ├─ Bedrock Knowledge Base Retrieve (tenant-filtered)   
                                         ├─ Bedrock Converse + Guardrail (PII, prompt attack)
                                         └─ approval gate ─► MSG# record + AUDIT# trail
```

| Stack | Contents |
|---|---|
| `data` | KMS key, DynamoDB (PITR, CMK), S3 docs bucket |
| `auth` | Cognito pool; post-confirmation Lambda creates tenant + admin |
| `events` | EventBridge bus + archive, SQS + DLQ + alarm |
| `ai` | Bedrock Guardrail, Knowledge Base (Titan Embeddings v2, S3 Vectors store, shared, filtered by `tenantId`) |
| `api` | HTTP API, control-plane Lambda, email plugin worker |
| `cost` | AWS Budget with 50/80/100% email alerts |

Tenant isolation: `tenantId` comes only from the signed JWT (`custom:tenantId`, not writable by the client) and prefixes every DynamoDB key.

Plugins are declared in `services/manifests/*.json` (permissions, events, actions, config schema) and installed per tenant.

## Run

```bash
cd infra && npm install
npx cdk bootstrap          # once per account/region
npx cdk deploy --all
python -m pytest services/tests
```

Bedrock models must be enabled in the console (Bedrock > Model access) in the deploy region.
Default model: `apac.amazon.nova-pro-v1:0` (change in `infra/cdk.json`). It scored 94% on the agent evaluation versus 89% for Nova Lite, see `docs/EVAL.md`.

## API

`GET /me` · `GET /plugins` · `PUT|DELETE /plugins/{id}` (admin) · `POST /plugins/email-automation/ingest` ·
`GET|POST /documents` (admin to write) · `DELETE /documents/{name}` · `POST /documents/sync` ·
`GET /messages` · `POST /messages/{id}/approve|reject` · `GET /audit` (admin)

See `docs/ROADMAP.md` for what is next.

## Conversation agent (WhatsApp / web chat)

Plugin `conversation-agent`: a multi-turn agent that answers from the tenant knowledge base, collects lead details
(configurable `collectFields` / `requiredFields`), keeps the conversation in DynamoDB, summarises it, and emails the owner when a lead
is complete or a person is needed (complaints, refunds, legal, safety, abuse, or a request for a human).
Guardrail is applied to every customer message and every reply; the model's reasoning tags are stripped.

- Test it: dashboard **Agent** tab, or `POST /chat`.
- WhatsApp text: `src/channels/whatsapp.py` is subscribed to the SNS topic of AWS End User Messaging Social (the owner creates the
  subscription to the `WhatsAppFnArn` stack output), then `PUT /channels/whatsapp` links the number to a business. Unit-tested with
  Meta webhook fixtures; **not yet run against a live number**.
- Website chat (no login): the owner creates an embed code in the dashboard (Agent tab) and pastes
  `<script src="<PublicChatUrl>/widget.js" data-key="pk_..." async></script>` into their site. It runs on a **separate public API**
  (`src/channels/web.py`) so open CORS never touches the authenticated API. The site key only selects the business; abuse is bounded by an
  optional Origin allow-list, 30 messages/visitor/hour, 300/business/day (DynamoDB counters with TTL), an 800-character limit, and API throttling.
  Replies never include captured lead data. Keys can be rotated. Live-tested (`tests/e2e/public_chat_e2e.py`, 25 checks) and the widget
  was exercised in a real browser. See `docs/widget-demo.html`.
- Voice: see `docs/VOICE.md`.

## AI harness

Context and memory, tools, security and evaluation around the model are mapped in [docs/HARNESS.md](docs/HARNESS.md): session/state/long-term memory, untrusted-context handling, and a three-level evaluation (checks, LLM judge, human review sheet).

## Agent evaluation

`tests/eval/agent_eval.py` runs 22 behaviour cases (answers match the documents, no invented prices, details captured, handoff, injection, privacy,
summary honesty) three times each against the deployed stack and reports pass rates. Results and model comparison: `docs/EVAL.md`.

## Monitoring models

Every model call writes one metadata-only JSON line (`services/src/common/llmlog.py`: model, tokens, latency, outcome, hashed tenant; never customer text).
Query them in CloudWatch Logs Insights, and read Bedrock's own CloudWatch metrics (invocations, tokens, latency per model). Unsafe input and output is
blocked by Bedrock Guardrails. Details and ready-made queries: [docs/OBSERVABILITY.md](docs/OBSERVABILITY.md), including why LLMScope was tried and removed.

## Email sending

Replies go out through SES from `SENDER_EMAIL` (CDK context `-c senderEmail=...`), with the business name as the display name.
The account is in the SES sandbox: the sender and every recipient must be verified until production access is granted.
If SES refuses a send, the draft stays `PENDING_APPROVAL` with the error shown, and nothing is lost.
Inbound mail (SES receiving) needs a domain you control and is not set up yet.

## Platform console (super admin)

A separate operator console at `/platform/` for members of the Cognito group `platform-admins`. **Read-only, metadata only:** business list,
usage counts (users, plugins, conversations, leads, emails held), channel status, document counts, recent action names. It never returns customer
messages, lead details, plugin settings or site keys. Each look at one business is written to that business's audit log (`platform.viewed_tenant`).
Membership is granted only by an operator with the AWS CLI (browsers cannot set it):

```bash
aws cognito-idp admin-add-user-to-group --user-pool-id <UserPoolId> --username <email> --group-name platform-admins
```
The user must sign in again to get a token with the group. Business admins calling `/platform/*` get 403 (unit-tested); signed-out callers get 401.
Counts come from a table scan: fine at this stage, replace with maintained counters before hundreds of businesses.

## Hosted dashboard

The dashboard is a static export served from a private S3 bucket through CloudFront (HTTPS, security headers incl. CSP, direct bucket access denied):
**https://d3skf5nh4g91r9.cloudfront.net** (dev backend; default CloudFront domain, no custom domain yet).
Publish a new build with `AWS_PROFILE=hivemate scripts/deploy-web.sh` (reads the stack outputs, builds, syncs, invalidates).
The API and docs-bucket CORS allow this origin via `-c webOrigin=...` (set in `infra/cdk.json`). Verified without signing in: page and route
rendering, headers, CORS (an unknown origin gets no allow header). Sign-in on the hosted site has not been exercised by me.

## Dashboard (local)

```bash
cd web && npm install
cp .env.example .env.local   # fill from infra/outputs.json
npm run dev                  # http://localhost:3000
```

Sign up (a confirmation code is emailed), then use Inbox, Plugins, Documents and Audit. API and S3 CORS allow `http://localhost:3000` only.

## CI/CD

`.github/workflows/ci.yml`: tests + `cdk synth` on every PR; on push to `main` it assumes an AWS role through GitHub OIDC
(no stored keys) and runs `cdk bootstrap` + `cdk deploy --all`.
Repo variables required: `AWS_ROLE_ARN`, `AWS_ACCOUNT_ID`, `ALERT_EMAIL`. Local deploys: `npx cdk deploy --all -c alertEmail=you@example.com`.

## Deployed (dev)

Deployed to `ap-southeast-2` from a laptop with `cdk deploy --all -c alertEmail=...` because the AWS account's
organization policy blocks the GitHub OIDC provider. The CI deploy job stays skipped until `AWS_ROLE_ARN` is set.
