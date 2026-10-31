"""Cognito post-confirmation trigger: every new sign-up creates a tenant and becomes its admin."""
import os
import time
import uuid

import boto3

from src.common import db

cognito = boto3.client("cognito-idp")


def handler(event, _context):
    if event["triggerSource"] != "PostConfirmation_ConfirmSignUp":
        return event
    attrs = event["request"]["userAttributes"]
    tenant_id = uuid.uuid4().hex[:12]
    pk = f"TENANT#{tenant_id}"
    now = int(time.time())

    db.table().put_item(Item={
        "PK": pk, "SK": "META",
        "tenantId": tenant_id,
        "name": attrs.get("custom:businessName") or attrs["email"],
        "region": "NZ", "currency": "NZD", "gstRate": "0.15", "timezone": "Pacific/Auckland",
        "createdAt": now,
    })
    db.table().put_item(Item={
        "PK": pk, "SK": f"USER#{attrs['sub']}",
        "email": attrs["email"], "role": "admin", "createdAt": now,
    })
    db.audit(pk, attrs["sub"], "tenant.created")

    cognito.admin_update_user_attributes(
        UserPoolId=event["userPoolId"],
        Username=event["userName"],
        UserAttributes=[
            {"Name": "custom:tenantId", "Value": tenant_id},
            {"Name": "custom:role", "Value": "admin"},
        ],
    )
    return event
