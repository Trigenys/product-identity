import uuid
from collections.abc import Collection

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.auth import Membership, MembershipRole


class TenantAccessDenied(Exception):
    pass


def require_membership(
    session: Session,
    *,
    user_id: uuid.UUID,
    organization_id: uuid.UUID,
    allowed_roles: Collection[MembershipRole] | None = None,
) -> Membership:
    membership = session.scalar(
        select(Membership).where(
            Membership.user_id == user_id,
            Membership.organization_id == organization_id,
        )
    )

    if membership is None:
        raise TenantAccessDenied("User is not a member of this organization")

    if allowed_roles is not None and membership.role not in allowed_roles:
        raise TenantAccessDenied("Membership role is not authorized for this operation")

    return membership
