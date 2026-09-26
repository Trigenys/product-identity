import pytest
from sqlalchemy.orm import Session

from app.models.auth import MembershipRole, Organization, User
from app.services.tenancy import TenantAccessDenied, require_membership


def test_member_can_access_own_organization(
    session: Session,
    seeded_user: tuple[User, Organization, Organization],
) -> None:
    user, own_org, _ = seeded_user

    membership = require_membership(
        session,
        user_id=user.id,
        organization_id=own_org.id,
        allowed_roles={MembershipRole.OWNER, MembershipRole.ADMIN},
    )

    assert membership.organization_id == own_org.id
    assert membership.role == MembershipRole.OWNER


def test_member_cannot_cross_tenant_boundary(
    session: Session,
    seeded_user: tuple[User, Organization, Organization],
) -> None:
    user, _, other_org = seeded_user

    with pytest.raises(TenantAccessDenied):
        require_membership(
            session,
            user_id=user.id,
            organization_id=other_org.id,
        )
