"""Small shared pieces of the AI harness (see docs/HARNESS.md): treat everything that is not our own prompt as untrusted data."""
import re

# Delimiters our prompt uses. Content that contains them could close a block early and smuggle in instructions.
_DELIMITERS = re.compile(r"</?\s*(knowledge|memory|transcript|system|instructions?)\s*>", re.I)


def untrusted(text: str, limit: int = 6000) -> str:
    """Retrieved documents and remembered details are data. Strip our delimiter tags from them and cap their size."""
    return _DELIMITERS.sub("", text or "")[:limit]


_QUESTION = re.compile(r"\?|^\s*(how|what|when|where|which|who|do|does|can|could|are|is|will|would)\b", re.I)
_ASKS_DETAILS = re.compile(r"\b(your (full )?name|phone|number|suburb|address|when would you|what day|where in)\b", re.I)
_REAL_ANSWER = re.compile(r"[$\d]|\b(team|quote|confirm|not |n't|cannot|only|closed|open|unfortunately|sorry)\b", re.I)


def deflects(question: str, reply: str) -> bool:
    """True when the customer asked something and the reply only asks for their details.
    A reply that gives a figure, says the team will confirm, or declines is an answer, so it is left alone."""
    return bool(_QUESTION.search(question) and _ASKS_DETAILS.search(reply) and not _REAL_ANSWER.search(reply))
