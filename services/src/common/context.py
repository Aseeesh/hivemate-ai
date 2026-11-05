"""Tenant context. The tenant is taken ONLY from verified JWT claims - never from request bodies."""
import re
from dataclasses import dataclass


class Forbidden(Exception):
    pass


@dataclass(frozen=True)
class Ctx:
    tenant_id: str
    user_id: str
    role: str
    email: str
    platform: bool = False

    def require_platform(self) -> None:
        if not self.platform:
            raise Forbidden("platform admin required")

    @property
    def pk(self) -> str:
        return f"TENANT#{self.tenant_id}"

    def require_admin(self) -> None:
        if self.role != "admin":
            raise Forbidden("admin role required")


PLATFORM_GROUP = "platform-admins"


def is_platform(claims: dict) -> bool:
    """Membership comes from the signed token's cognito:groups claim, which only an operator can change (AdminAddUserToGroup).
    API Gateway renders the array as a string like "[platform-admins other]", so match whole group names."""
    raw = claims.get("cognito:groups", "")
    names = raw if isinstance(raw, list) else re.findall(r"[A-Za-z0-9_+=,.@-]+", str(raw))
    return PLATFORM_GROUP in names


def from_event(event: dict) -> Ctx:
    claims = event["requestContext"]["authorizer"]["jwt"]["claims"]
    tenant_id = claims.get("custom:tenantId")
    if not tenant_id:
        # Fresh sign-up: token was issued before the post-confirmation trigger ran.
        raise Forbidden("no tenant on token - sign in again")
    return Ctx(
        tenant_id=tenant_id,
        user_id=claims["sub"],
        role=claims.get("custom:role", "member"),
        email=claims.get("email", ""),
        platform=is_platform(claims),
    )
