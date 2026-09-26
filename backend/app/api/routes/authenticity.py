import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db_session
from app.models.auth import MembershipRole, User
from app.models.authenticity import (
    AuthenticitySignal,
    AuthenticitySignalState,
    AuthenticitySignalType,
)
from app.models.identity import Product, Unit
from app.services.tenancy import TenantAccessDenied, require_membership

router = APIRouter(prefix="/v1/organizations/{organization_id}", tags=["authenticity-signals"])


class AuthenticitySignalResponse(BaseModel):
    id: str
    unit_id: str
    product_id: str
    product_name: str
    sku: str
    serial: str
    signal_type: AuthenticitySignalType
    state: AuthenticitySignalState
    observed_value: int
    threshold_value: int
    window_started_at: str
    window_ended_at: str
    explanation: str
    reviewed_by_user_id: str | None
    reviewed_at: str | None
    review_note: str | None


class AuthenticitySignalReview(BaseModel):
    state: AuthenticitySignalState
    note: str | None = Field(default=None, max_length=500)


def _require_signal_access(
    session: Session,
    *,
    user: User,
    organization_id: uuid.UUID,
    review: bool,
) -> None:
    roles = set(MembershipRole)
    if review:
        roles = {MembershipRole.OWNER, MembershipRole.ADMIN, MembershipRole.MEMBER}

    try:
        require_membership(
            session,
            user_id=user.id,
            organization_id=organization_id,
            allowed_roles=roles,
        )
    except TenantAccessDenied as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Organization access denied",
        ) from exc


def _signal_response(
    signal: AuthenticitySignal,
    unit: Unit,
    product: Product,
) -> AuthenticitySignalResponse:
    return AuthenticitySignalResponse(
        id=str(signal.id),
        unit_id=str(unit.id),
        product_id=str(product.id),
        product_name=product.name,
        sku=product.sku,
        serial=unit.serial,
        signal_type=signal.signal_type,
        state=signal.state,
        observed_value=signal.observed_value,
        threshold_value=signal.threshold_value,
        window_started_at=signal.window_started_at.isoformat(),
        window_ended_at=signal.window_ended_at.isoformat(),
        explanation=signal.explanation,
        reviewed_by_user_id=str(signal.reviewed_by_user_id) if signal.reviewed_by_user_id else None,
        reviewed_at=signal.reviewed_at.isoformat() if signal.reviewed_at else None,
        review_note=signal.review_note,
    )


@router.get("/authenticity-signals", response_model=list[AuthenticitySignalResponse])
def list_authenticity_signals(
    organization_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db_session)],
    state: AuthenticitySignalState | None = Query(default=None),
    signal_type: AuthenticitySignalType | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=200),
) -> list[AuthenticitySignalResponse]:
    _require_signal_access(
        session,
        user=user,
        organization_id=organization_id,
        review=False,
    )

    query = (
        select(AuthenticitySignal, Unit, Product)
        .join(Unit, Unit.id == AuthenticitySignal.unit_id)
        .join(Product, Product.id == Unit.product_id)
        .where(AuthenticitySignal.organization_id == organization_id)
        .order_by(AuthenticitySignal.window_ended_at.desc())
        .limit(limit)
    )
    if state is not None:
        query = query.where(AuthenticitySignal.state == state)
    if signal_type is not None:
        query = query.where(AuthenticitySignal.signal_type == signal_type)

    rows = session.execute(query).all()
    return [_signal_response(signal, unit, product) for signal, unit, product in rows]


@router.patch(
    "/authenticity-signals/{signal_id}",
    response_model=AuthenticitySignalResponse,
)
def review_authenticity_signal(
    organization_id: uuid.UUID,
    signal_id: uuid.UUID,
    payload: AuthenticitySignalReview,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> AuthenticitySignalResponse:
    _require_signal_access(
        session,
        user=user,
        organization_id=organization_id,
        review=True,
    )

    if payload.state == AuthenticitySignalState.OPEN:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Review state must be reviewed or dismissed",
        )

    row = session.execute(
        select(AuthenticitySignal, Unit, Product)
        .join(Unit, Unit.id == AuthenticitySignal.unit_id)
        .join(Product, Product.id == Unit.product_id)
        .where(
            AuthenticitySignal.id == signal_id,
            AuthenticitySignal.organization_id == organization_id,
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Authenticity signal not found",
        )

    signal, unit, product = row
    signal.state = payload.state
    signal.reviewed_by_user_id = user.id
    signal.reviewed_at = datetime.now(timezone.utc)
    signal.review_note = payload.note.strip() if payload.note else None
    session.commit()

    return _signal_response(signal, unit, product)
