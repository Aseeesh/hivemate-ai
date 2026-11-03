# Hivemate AI

Multi-tenant, plugin-based AI automation platform for NZ SMEs, built serverless-first on AWS.

## Architecture (implemented so far)

```
Client ─► API Gateway (HTTP, Cognito JWT) ─► ApiFn ─► DynamoDB (single table, tenant-partitioned)
                                               │
                                               └─► EventBridge bus ─► rule(email.received) ─► SQS (+DLQ)
                                                                                          │
                                       Email plugin Lambda ◄──────────────────────────────┘
                                         ├─ Bedrock Knowledge Base Retrieve (tenant-filtered)   [Phase 4]
                                         ├─ Bedrock Converse + Guardrail (PII, prompt attack)
                                         └─ approval gate ─► MSG# record + AUDIT# trail
```

| Stack | Contents |
|---|---|
| `data` | KMS key, DynamoDB (PITR, CMK), S3 docs bucket |
| `auth` | Cognito pool; post-confirmation Lambda creates tenant + admin |
| `events` | EventBridge bus + archive, SQS + DLQ + alarm |
| `ai` | Bedrock Guardrail |
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
Default model: `apac.amazon.nova-lite-v1:0` (cheap; change in `infra/cdk.json`).

## API

`GET /me` · `GET /plugins` · `PUT|DELETE /plugins/{id}` (admin) · `POST /plugins/email-automation/ingest` ·
`GET /messages` · `POST /messages/{id}/approve|reject` · `GET /audit` (admin)

See `docs/ROADMAP.md` for what is next.

## CI/CD

`.github/workflows/ci.yml`: tests + `cdk synth` on every PR; on push to `main` it assumes an AWS role through GitHub OIDC
(no stored keys) and runs `cdk bootstrap` + `cdk deploy --all`.
Repo variables required: `AWS_ROLE_ARN`, `AWS_ACCOUNT_ID`, `ALERT_EMAIL`. Local deploys: `npx cdk deploy --all -c alertEmail=you@example.com`.

## Deployed (dev)

Deployed to `ap-southeast-2` from a laptop with `cdk deploy --all -c alertEmail=...` because the AWS account's
organization policy blocks the GitHub OIDC provider. The CI deploy job stays skipped until `AWS_ROLE_ARN` is set.
