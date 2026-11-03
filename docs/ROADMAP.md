# Roadmap

- [x] Phase 1-3 core: CDK stacks, Cognito, tenant creation, plugin registry/manifests, config validation, audit
- [x] Email Automation worker: EventBridge -> SQS/DLQ -> Bedrock + Guardrail -> approval gate
- [x] Deploy `dev` to ap-southeast-2, smoke test end to end
- [x] Phase 4 RAG: Bedrock Knowledge Base on S3 Vectors, per-tenant `tenantId` metadata filter, verified with two tenants
- [x] Document upload (presigned POST, SigV4), list, delete, KB sync endpoints
- [x] Full e2e test on deployed stack (tests/e2e/e2e.py): 49/51 on first run; the 2 failures were Lambda throttling (account concurrency quota = 10), worker concurrency now capped at 2
- [ ] Request a Lambda concurrency quota increase (Service Quotas L-B99A9384) so bursts above ~10 concurrent requests are not throttled
- [ ] Auto-sync KB on upload (S3 event -> debounced ingestion); Document Analysis plugin (Textract + Bedrock)
- [ ] AI evaluation suite: golden questions per tenant, check grounding, no cross-tenant leakage, no invented facts
- [x] Next.js dashboard (Cognito SRP login + signup confirm, plugin catalog/config, documents, inbox approval queue, audit)
- [x] SES outbound: approve and auto-reply send real email (sandbox: verified recipients only)
- [ ] Phase 5: SES inbound (needs a domain), website chat (WebSocket/API GW), WhatsApp via End User Messaging Social (check region)
- [ ] Booking plugin + Step Functions workflow
- [ ] Phase 6: CloudWatch dashboard, X-Ray, per-tenant usage metering, load tests, CI deploy via OIDC role
- [ ] Phase 7: threat model, Well-Architected review, cost analysis, demo tenants (SparkClean NZ, Auckland Property Services, Kiwi Retail)
