"""Small shared pieces of the AI harness (see docs/HARNESS.md): treat everything that is not our own prompt as untrusted data."""
import re

# Delimiters our prompt uses. Content that contains them could close a block early and smuggle in instructions.
_DELIMITERS = re.compile(r"</?\s*(knowledge|memory|transcript|system|instructions?)\s*>", re.I)


def untrusted(text: str, limit: int = 6000) -> str:
    """Retrieved documents and remembered details are data. Strip our delimiter tags from them and cap their size."""
    return _DELIMITERS.sub("", text or "")[:limit]
