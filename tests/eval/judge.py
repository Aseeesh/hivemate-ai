"""LLM-as-judge for the conversation agent (harness area 4, level 2).

Deterministic checks say whether a reply contains the right fact; the judge scores what string checks can't see:
is it grounded in the knowledge, does it answer, is the tone right, is it concise. Scores are 1-5 per criterion.
Use a different model from the agent where you can (JUDGE_MODEL); a model grading its own output is lenient.
"""
import json, os, re

import boto3

JUDGE_MODEL = os.environ.get("JUDGE_MODEL", "apac.amazon.nova-pro-v1:0")
RUBRIC = """You grade a customer-service chat reply for a New Zealand business. Use ONLY the knowledge given.
Score each 1 (bad) to 5 (excellent):
- grounded: every fact, price, time and policy in the reply is supported by the knowledge; no invented specifics.
- helpful: it answers the customer's question, or honestly says the team will confirm. Only asking for details is a 2.
- tone: polite, plain, natural, not pushy, no emojis or markdown.
- concise: short and to the point (about 60 words or fewer).
Reply with JSON only: {"grounded":n,"helpful":n,"tone":n,"concise":n,"reason":"one sentence"}"""

_rt = None


def judge(knowledge: str, customer: str, reply: str) -> dict:
    global _rt
    _rt = _rt or boto3.Session(profile_name=os.environ.get("AWS_PROFILE"), region_name="ap-southeast-2").client("bedrock-runtime")
    res = _rt.converse(
        modelId=JUDGE_MODEL, system=[{"text": RUBRIC}], inferenceConfig={"maxTokens": 200, "temperature": 0},
        messages=[{"role": "user", "content": [{"text": f"<knowledge>\n{knowledge}\n</knowledge>\n<customer>\n{customer}\n</customer>\n<reply>\n{reply}\n</reply>"}]}])
    text = res["output"]["message"]["content"][0]["text"]
    m = re.search(r"\{.*\}", text, re.S)
    try:
        out = json.loads(m.group(0)) if m else {}
        return {k: int(out[k]) for k in ("grounded", "helpful", "tone", "concise")} | {"reason": str(out.get("reason", ""))[:200]}
    except (ValueError, KeyError, TypeError):
        return {"error": text[:120]}


def low(scores: dict, floor: int = 3) -> bool:
    return "error" in scores or min(scores.get(k, 0) for k in ("grounded", "helpful", "tone", "concise")) < floor
