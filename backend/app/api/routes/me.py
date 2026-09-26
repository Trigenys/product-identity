from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import get_current_user
from app.db.session import get_db_session
from app.models.auth import Membership, User

router = APIRouter(prefix="/v1", tags=["identity"])


class MembershipResponse(BaseModel):
    organization_id: str
    organization_name: str
    organization_slug: str
    role: str


class MeResponse(BaseModel):
    id: str
    email: str | None
    memberships: list[MembershipResponse]


@router.get("/me", response_model=MeResponse)
def me(
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> MeResponse:
    memberships = session.scalars(
        select(Membership)
        .options(selectinload(Membership.organization))
        .where(Membership.user_id == user.id)
    ).all()

    return MeResponse(
        id=str(user.id),
        email=user.email,
        memberships=[
            MembershipResponse(
                organization_id=str(m.organization_id),
                organization_name=m.organization.name,
                organization_slug=m.organization.slug,
                role=m.role.value,
            )
            for m in memberships
        ],
    )
