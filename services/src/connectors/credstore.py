"""OAuth tokens live in Secrets Manager (KMS-encrypted, one secret per business and provider), never in the DynamoDB table.
Only the Lambdas that need them are granted secretsmanager access, scoped to the name prefix."""
import json
import os

import boto3
from botocore.exceptions import ClientError

_sm = None


def _client():
    global _sm
    if _sm is None:
        _sm = boto3.client("secretsmanager")
    return _sm


def secret_id(pk: str, provider: str) -> str:
    assert pk.startswith("TENANT#") and provider.isalnum()
    return f"{os.environ.get('SECRET_PREFIX', 'hivemate/dev')}/{pk[7:]}/{provider}"


def put(pk: str, provider: str, tokens: dict) -> None:
    sid, body = secret_id(pk, provider), json.dumps(tokens)
    try:
        _client().put_secret_value(SecretId=sid, SecretString=body)
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "ResourceNotFoundException":
            raise
        kw = {"KmsKeyId": os.environ["SECRETS_KMS_KEY_ID"]} if os.environ.get("SECRETS_KMS_KEY_ID") else {}
        _client().create_secret(Name=sid, SecretString=body, Description="Hivemate connector credentials", **kw)


def get(pk: str, provider: str) -> dict | None:
    try:
        return json.loads(_client().get_secret_value(SecretId=secret_id(pk, provider))["SecretString"])
    except ClientError as exc:
        if exc.response["Error"]["Code"] in ("ResourceNotFoundException", "InvalidRequestException"):
            return None
        raise


def delete(pk: str, provider: str) -> None:
    try:
        _client().delete_secret(SecretId=secret_id(pk, provider), RecoveryWindowInDays=7)
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "ResourceNotFoundException":
            raise
