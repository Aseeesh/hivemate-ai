# WhatsApp voice agent: design

Status: **not built.** The conversation agent (`services/src/plugins/conversation/agent.py`) is the reusable brain and is live
for text. Voice reuses it; what is missing is the audio path.

## What voice adds

```
Customer taps "call" in WhatsApp
  -> WhatsApp Business Calling API (Meta) -> AWS End User Messaging Social (voice calling, WebRTC audio)
  -> media bridge (container, one task per call) ----> speech-to-speech model (Amazon Nova Sonic via Bedrock bidirectional stream)
          |                                                      |
          |  tool calls: record_details, request_handoff,        |  grounding: retrieve() from the tenant knowledge base
          +--------------- same functions as the text agent -----+
  -> call ends -> transcript -> summarise() -> lead + owner email (existing code)
```

## Why it is a separate piece of work

- **WebRTC needs a long-lived process.** Lambda cannot hold a media session. Use ECS Fargate with one task per active call
  (Pipecat or aiortc), started on an incoming-call event. Idle cost is zero; each call costs a task for its duration.
- **Account concurrency.** New AWS accounts allow 10 concurrent Lambda executions and few Fargate vCPUs. Request quota increases first.
- **Latency budget.** Voice feels broken above about 1 s response time. Retrieval must be pre-fetched (hot facts in the prompt) or run
  as a tool the model calls only when needed.
- **Prerequisites only the business owner can do:** a Meta Business account with business verification, a WhatsApp phone number
  registered in AWS End User Messaging Social, calling enabled on it, and a region where both Social voice calling and Nova Sonic are available.
  AWS Social is not available in every region (it was Singapore, not Sydney, at last check): the WhatsApp resources can live in a
  different region from the rest of Hivemate, which needs a privacy decision for NZ customers.
- **Calling eligibility is set by Meta** (message-limit tier, per-country availability). Confirm for New Zealand before promising it.

## Build order

1. Link a real WhatsApp number for **text** and verify `src/channels/whatsapp.py` end to end (the adapter is unit-tested only).
2. Media bridge in a container: accept call, stream audio both ways to Nova Sonic, expose the two existing tools.
3. Call-end hook: store transcript turns as `TURN#` items so the dashboard, `summarise()` and owner alerts work unchanged.
4. Per-call cost metering and a hard cap on call length.
