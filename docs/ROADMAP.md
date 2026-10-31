# Roadmap

- [x] Phase 1-3 core: CDK stacks, Cognito, tenant creation, plugin registry/manifests, config validation, audit
- [x] Email Automation worker: EventBridge -> SQS/DLQ -> Bedrock + Guardrail -> approval gate
- [ ] Deploy `dev`, enable Bedrock model access, smoke test with curl
- [ ] Phase 4 RAG: Bedrock Knowledge Base (S3 docs bucket + S3 Vectors or Aurora pgvector), ingestion on upload, `tenantId` metadata filter
- [ ] Phase 4: presigned-URL document upload endpoint (`<tenantId>/` prefix), Document Analysis plugin (Textract + Bedrock)
- [ ] Next.js dashboard (Cognito SRP login, plugin catalog, approval queue)
- [ ] Phase 5: SES inbound + send, website chat (WebSocket/API GW), WhatsApp via End User Messaging Social (check region)
- [ ] Booking plugin + Step Functions workflow
- [ ] Phase 6: CloudWatch dashboard, X-Ray, per-tenant usage metering, load tests, CI deploy via OIDC role
- [ ] Phase 7: threat model, Well-Architected review, cost analysis, demo tenants (SparkClean NZ, Auckland Property Services, Kiwi Retail)
