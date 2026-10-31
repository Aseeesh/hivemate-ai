import glob
import json
import os
from functools import lru_cache

_TYPES = {"boolean": bool, "string": str, "number": (int, float), "array": list}


@lru_cache(maxsize=1)
def registry() -> dict[str, dict]:
    base = os.environ.get("MANIFEST_DIR") or os.path.join(os.path.dirname(__file__), "../../manifests")
    out = {}
    for path in glob.glob(os.path.join(base, "*.json")):
        with open(path) as f:
            m = json.load(f)
        out[m["pluginId"]] = m
    return out


def validate_config(manifest: dict, config: dict) -> dict:
    """Apply defaults and reject unknown keys / wrong types. Returns the effective config."""
    schema = manifest["configurationSchema"]
    unknown = set(config) - set(schema)
    if unknown:
        raise ValueError(f"unknown config keys: {sorted(unknown)}")
    effective = {}
    for key, spec in schema.items():
        val = config.get(key, spec["default"])
        expected = _TYPES[spec["type"]]
        # bool is a subclass of int; don't let True pass as a number
        if not isinstance(val, expected) or (spec["type"] == "number" and isinstance(val, bool)):
            raise ValueError(f"{key} must be {spec['type']}")
        effective[key] = val
    return effective
