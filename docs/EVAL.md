# Conversation agent evaluation

`tests/eval/agent_eval.py` sends scripted customer messages to the deployed agent and checks the replies with deterministic rules
(string and structure checks, not another model). Each of 22 cases runs 3 times because the model is not deterministic.
Run on 4-6 Nov 2026, knowledge base = one short SparkClean NZ price/hours document.

| Run | Model | Prompt/code | Runs passed | Cases fully stable |
|---|---|---|---|---|
| 1 | Nova Lite | baseline | 57/66 (86%) | 15/22 |
| 2 | Nova Lite | "answer first, then ask" prompt | 47/66 (71%) | 13/22 |
| 3 | Nova Lite | prompt reverted + grounding + field rules + wrapper-tag strip | 59/66 (89%) | 16/22 |
| 4 | **Nova Pro** (now default) | same as run 3 | **62/66 (94%)** | **19/22** |

What the evaluation caught and what changed:
- A greeting ("Hi") was saved as the customer's name -> names and phone numbers must now appear in the customer's own words.
- A stated suburb was folded into "need" or dropped -> prompt now says one detail per field. Still the main failure on Nova Pro (location omitted from the tool call in some runs).
- The summary said the booking was "confirmed" -> summaries now read only the customer's messages.
- Run 2 shows a prompt change that sounded sensible made the agent deflect every question; it was reverted. Prompt changes need the suite.
- Nova Lite sometimes stated wrong opening hours or gave only a "passed to the team" message; Nova Pro did not in this run.

Limits: 3 runs per case is a small sample; one tiny document; checks are keyword rules and can miss subtle errors; English only; no voice.
