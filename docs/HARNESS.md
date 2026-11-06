# AI harness

The model only produces text. Everything that makes the conversation agent usable and safe is the harness around it.
This maps the four harness areas to what Hivemate has, where it lives, and what is still open.

| Area | What it is here | Where |
|---|---|---|
| **Context & memory** | *Session*: the last 12 turns of the conversation. *State*: the details collected so far (`conv.collected`), re-injected into every prompt. *Long-term*: a returning WhatsApp customer's name, phone and location, kept 180 days. | `agent.py` (`load_history`, `collected`), `memory.py` |
| **Tools & execution flow** | Two tools (`record_details`, `request_handoff`) validated server-side (unknown fields dropped, names/phones must be grounded in what the customer wrote). Hard loop cap, one retry on transient model errors, a turn limit that forces a handoff. Retrieval is a tenant-filtered knowledge-base lookup. | `agent.py` (`run_tool`, `accept`, `converse_loop`, `call_model`), `common/knowledge.py` |
| **Runtime, security & privacy** | Untrusted input: customer text, retrieved documents and remembered details are all labelled as data in the prompt, and our delimiter tags are stripped from them. Bedrock Guardrails on input and output. Per-tenant isolation (KB metadata filter, tenant-scoped keys). Human approval: low-confidence email drafts wait for the owner; handoff silences the AI. Public chat is rate limited. Logs carry metadata only. | `common/harness.py`, `agent.py` (`guard`), `plugins/email`, `channels/web.py`, `common/llmlog.py` |
| **Evaluation** | *Level 1* deterministic checks (22 cases x 3 runs). *Level 2* LLM-as-judge scoring grounded / helpful / tone / concise (1-5). *Level 3* human review sheet listing every reply the judge scored low or that disagrees with the string check. | `tests/eval/agent_eval.py`, `tests/eval/judge.py` |

## Memory and privacy

Only WhatsApp customers are remembered (an allow-list). Anonymous web visitors and the owner's dashboard test chat never are; the first eval run with the judge showed why: the test chat reused one id, so every case looked like the same returning customer. Only `name`, `phone`
and `location` are stored, not transcripts. Entries expire by TTL after 180 days, and `memory.forget()` erases one customer.
Remembered values are shown to the model as reference data and it is told to confirm them gently, because people change numbers.
Not yet exposed: a dashboard button that calls `forget()` for a customer who asks to be erased.

## Running the evaluation

```bash
export E2E_USER_POOL_ID=... E2E_CLIENT_ID=... E2E_API_URL=...
EVAL_REPORT=eval.json EVAL_REVIEW=review.md python3 tests/eval/agent_eval.py
```

`EVAL_JUDGE=0` skips the judge; `JUDGE_MODEL` picks another model. The judge defaults to the same model family as the agent,
which grades more leniently than a different one; point `JUDGE_MODEL` at a stronger or different model for a fairer score.
The judge sees one run per case to keep cost down. The review sheet is the human level: read each item, tick it, and turn real
failures into new cases in `CASES`.

## Open

- Tool use is two fixed tools. MCP servers and a workflow graph with parallel checks are not needed yet.
- The agent runs in Lambda, which is the isolation boundary. There is no code-execution sandbox because the agent runs no code.
- Human feedback is a markdown sheet. A thumbs up/down on replies in the Inbox that feeds the sheet is the natural next step.
