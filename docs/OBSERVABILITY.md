# Observability

## What is in place
- **`llmlog`**: one JSON line per model call (`llm_call`) and per guardrail call (`guardrail_call`) with model, tokens, latency, stop reason and a hashed tenant id. No customer text.
- **Bedrock's CloudWatch metrics** (namespace `AWS/Bedrock`): invocations, input/output tokens, latency and errors per model.
- **Bedrock Guardrails** on input and output (prompt attacks, PII such as card numbers).
- **Alarms** for the dead-letter queue, errors and cost (cost stack).
- **Owner view**: the dashboard Home page (chats, leads, handoffs). **Operator view**: the platform console.

## Logs Insights queries
```
# calls, tokens and p95 latency per model, last 24 h (select the conversation, email and summary Lambda log groups)
filter event = "llm_call"
| stats count() as calls, sum(inputTokens) as inTok, sum(outputTokens) as outTok, pct(latencyMs, 95) as p95 by model

# failures
filter event = "llm_call" and ispresent(error)
| stats count() by model, error
```

## Why LLMScope is not part of Hivemate
It was integrated, run and measured (metrics, traces, logs, dashboards), then removed from this project on purpose:
- Hivemate is entirely on AWS, which LLMScope's own docs name as the case where the cloud's monitoring is enough.
- Guardrails and the eval suite already cover what its guard and evals offer for this app.
- Using it for real would need a hosted collector (cost, auth, a public endpoint) and a package in the request path of every Lambda.
- Its remaining value is a dev-time one: one Grafana across several projects, and a red team. That does not belong in the product.

LLMScope stays a separate project. It is still a good fit for apps that call providers directly outside a single cloud (for example cleaning-business-nz).
To try the red team against the public chat later, point it at the public chat URL from a laptop; nothing in Hivemate needs to change.
