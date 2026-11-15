"""Operator-level connector settings (OAuth client ids and secrets, webhook keys).

Read from the environment first (tests, local), otherwise from ONE Secrets Manager secret `<SECRET_PREFIX>/apps` holding a JSON object,
so client secrets are never Lambda environment variables or CloudFormation parameters.
"""
import json
import os

import boto3

_cache: dict | None = None


def _load() -> dict:
    global _cache
    if _cache is None:
        try:
            raw = boto3.client("secretsmanager").get_secret_value(SecretId=f"{os.environ.get('SECRET_PREFIX', 'hivemate/dev')}/apps")["SecretString"]
            _cache = json.loads(raw)
        except Exception:  # noqa: BLE001 - missing secret, no permission, bad JSON: all mean "not configured"
            _cache = {}
    return _cache


def get(name: str, default: str = "") -> str:
    return os.environ.get(name) or str(_load().get(name, default) or default)
