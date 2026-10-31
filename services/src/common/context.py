"""Tenant context. The tenant is taken ONLY from verified JWT claims - never from request bodies."""
from dataclasses import dataclass


class Forbidden(Exception):
    pass


@dataclass(frozen=True)
class Ctx:
    tenant_id: str
    user_id: str
    role: str
    email: str

    @property
    def pk(self) -> str:
        return f"TENANT#{self.tenant_id}"

    def require_admin(self) -> None:
        if self.role != "admin":
            raise Forbidden("admin role required")


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
    )
