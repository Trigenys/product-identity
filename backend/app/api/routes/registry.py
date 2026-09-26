import uuid
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db_session
from app.models.auth import MembershipRole, User
from app.models.authenticity import AuthenticitySignal, AuthenticitySignalState
from app.models.identity import Product, Unit, UnitStatus, VerificationEvent
from app.models.warranty import ProductRegistration
from app.services.tenancy import TenantAccessDenied, require_membership
from app.services.warranty import warranty_state

router = APIRouter(prefix="/v1/organizations/{organization_id}", tags=["merchant-registry"])


class RegistrySummary(BaseModel):
    total_units: int
    active_units: int
    revoked_units: int
    registered_units: int
    unregistered_units: int
    open_authenticity_signals: int


class RegistryUnitItem(BaseModel):
    id: str
    serial: str
    status: UnitStatus
    product_id: str
    product_name: str
    sku: str
    created_at: str
    registered: bool
    warranty_state: str
    warranty_expires_on: str | None
    verification_count: int
    open_signal_count: int


class RegistryListResponse(BaseModel):
    summary: RegistrySummary
    total: int
    limit: int
    offset: int
    units: list[RegistryUnitItem]


class RegistrationDetail(BaseModel):
    id: str
    customer_name: str
    customer_email: str
    purchase_date: str | None
    registered_at: str
    warranty_started_on: str
    warranty_expires_on: str
    warranty_state: str


class RegistryTimelineItem(BaseModel):
    id: str
    kind: Literal["fact", "derived"]
    source: str
    title: str
    description: str
    occurred_at: str


class RegistryUnitDetail(BaseModel):
    id: str
    serial: str
    status: UnitStatus
    product_id: str
    product_name: str
    sku: str
    created_at: str
    registration: RegistrationDetail | None
    verification_count: int
    open_signal_count: int
    timeline: list[RegistryTimelineItem]


def _require_registry_access(
    session: Session,
    *,
    user: User,
    organization_id: uuid.UUID,
) -> None:
    try:
        require_membership(
            session,
            user_id=user.id,
            organization_id=organization_id,
            allowed_roles={
                MembershipRole.OWNER,
                MembershipRole.ADMIN,
                MembershipRole.MEMBER,
            },
        )
    except TenantAccessDenied as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Organization access denied",
        ) from exc


def _verification_counts_subquery():
    return (
        select(
            VerificationEvent.unit_id.label("unit_id"),
            func.count(VerificationEvent.id).label("verification_count"),
        )
        .where(VerificationEvent.unit_id.is_not(None))
        .group_by(VerificationEvent.unit_id)
        .subquery()
    )


def _open_signal_counts_subquery():
    return (
        select(
            AuthenticitySignal.unit_id.label("unit_id"),
            func.count(AuthenticitySignal.id).label("open_signal_count"),
        )
        .where(AuthenticitySignal.state == AuthenticitySignalState.OPEN)
        .group_by(AuthenticitySignal.unit_id)
        .subquery()
    )


def _summary(session: Session, organization_id: uuid.UUID) -> RegistrySummary:
    total_units = int(
        session.scalar(
            select(func.count(Unit.id)).where(Unit.organization_id == organization_id)
        )
        or 0
    )
    active_units = int(
        session.scalar(
            select(func.count(Unit.id)).where(
                Unit.organization_id == organization_id,
                Unit.status == UnitStatus.ACTIVE,
            )
        )
        or 0
    )
    registered_units = int(
        session.scalar(
            select(func.count(ProductRegistration.id)).where(
                ProductRegistration.organization_id == organization_id
            )
        )
        or 0
    )
    open_signals = int(
        session.scalar(
            select(func.count(AuthenticitySignal.id)).where(
                AuthenticitySignal.organization_id == organization_id,
                AuthenticitySignal.state == AuthenticitySignalState.OPEN,
            )
        )
        or 0
    )
    return RegistrySummary(
        total_units=total_units,
        active_units=active_units,
        revoked_units=max(total_units - active_units, 0),
        registered_units=registered_units,
        unregistered_units=max(total_units - registered_units, 0),
        open_authenticity_signals=open_signals,
    )


@router.get("/registry/units", response_model=RegistryListResponse)
def list_registry_units(
    organization_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db_session)],
    search: str | None = Query(default=None, max_length=120),
    unit_status: UnitStatus | None = Query(default=None),
    registration: Literal["registered", "unregistered"] | None = Query(default=None),
    warranty: Literal["active", "expired", "unregistered"] | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> RegistryListResponse:
    _require_registry_access(
        session,
        user=user,
        organization_id=organization_id,
    )

    verification_counts = _verification_counts_subquery()
    signal_counts = _open_signal_counts_subquery()

    base = (
        select(
            Unit,
            Product,
            ProductRegistration,
            func.coalesce(verification_counts.c.verification_count, 0),
            func.coalesce(signal_counts.c.open_signal_count, 0),
        )
        .join(Product, Product.id == Unit.product_id)
        .outerjoin(ProductRegistration, ProductRegistration.unit_id == Unit.id)
        .outerjoin(verification_counts, verification_counts.c.unit_id == Unit.id)
        .outerjoin(signal_counts, signal_counts.c.unit_id == Unit.id)
        .where(Unit.organization_id == organization_id)
    )

    count_query = (
        select(func.count(Unit.id))
        .join(Product, Product.id == Unit.product_id)
        .outerjoin(ProductRegistration, ProductRegistration.unit_id == Unit.id)
        .where(Unit.organization_id == organization_id)
    )

    clean_search = search.strip() if search else ""
    if clean_search:
        pattern = f"%{clean_search}%"
        predicate = or_(
            Unit.serial.ilike(pattern),
            Product.name.ilike(pattern),
            Product.sku.ilike(pattern),
        )
        base = base.where(predicate)
        count_query = count_query.where(predicate)

    if unit_status is not None:
        base = base.where(Unit.status == unit_status)
        count_query = count_query.where(Unit.status == unit_status)

    if registration == "registered":
        base = base.where(ProductRegistration.id.is_not(None))
        count_query = count_query.where(ProductRegistration.id.is_not(None))
    elif registration == "unregistered":
        base = base.where(ProductRegistration.id.is_(None))
        count_query = count_query.where(ProductRegistration.id.is_(None))

    today = date.today()
    if warranty == "unregistered":
        base = base.where(ProductRegistration.id.is_(None))
        count_query = count_query.where(ProductRegistration.id.is_(None))
    elif warranty == "active":
        warranty_predicate = (
            ProductRegistration.id.is_not(None)
            & (ProductRegistration.warranty_started_on <= today)
            & (ProductRegistration.warranty_expires_on >= today)
        )
        base = base.where(warranty_predicate)
        count_query = count_query.where(warranty_predicate)
    elif warranty == "expired":
        warranty_predicate = (
            ProductRegistration.id.is_not(None)
            & (
                (ProductRegistration.warranty_expires_on < today)
                | (ProductRegistration.warranty_started_on > today)
            )
        )
        base = base.where(warranty_predicate)
        count_query = count_query.where(warranty_predicate)

    rows = session.execute(
        base.order_by(Unit.created_at.desc(), Unit.id.desc()).offset(offset).limit(limit)
    ).all()

    items: list[RegistryUnitItem] = []
    for unit, product, registered, verification_count, open_signal_count in rows:
        state = warranty_state(registered).value if registered is not None else "unregistered"

        items.append(
            RegistryUnitItem(
                id=str(unit.id),
                serial=unit.serial,
                status=unit.status,
                product_id=str(product.id),
                product_name=product.name,
                sku=product.sku,
                created_at=unit.created_at.isoformat(),
                registered=registered is not None,
                warranty_state=state,
                warranty_expires_on=(
                    registered.warranty_expires_on.isoformat()
                    if registered is not None
                    else None
                ),
                verification_count=int(verification_count),
                open_signal_count=int(open_signal_count),
            )
        )

    total = int(session.scalar(count_query) or 0)

    return RegistryListResponse(
        summary=_summary(session, organization_id),
        total=total,
        limit=limit,
        offset=offset,
        units=items,
    )


@router.get("/registry/units/{unit_id}", response_model=RegistryUnitDetail)
def registry_unit_detail(
    organization_id: uuid.UUID,
    unit_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> RegistryUnitDetail:
    _require_registry_access(
        session,
        user=user,
        organization_id=organization_id,
    )

    row = session.execute(
        select(Unit, Product, ProductRegistration)
        .join(Product, Product.id == Unit.product_id)
        .outerjoin(ProductRegistration, ProductRegistration.unit_id == Unit.id)
        .where(
            Unit.id == unit_id,
            Unit.organization_id == organization_id,
        )
    ).one_or_none()

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Unit not found",
        )

    unit, product, registration = row
    events = session.scalars(
        select(VerificationEvent)
        .where(VerificationEvent.unit_id == unit.id)
        .order_by(VerificationEvent.created_at.desc(), VerificationEvent.id.desc())
        .limit(50)
    ).all()
    signals = session.scalars(
        select(AuthenticitySignal)
        .where(AuthenticitySignal.unit_id == unit.id)
        .order_by(AuthenticitySignal.window_ended_at.desc(), AuthenticitySignal.id.desc())
        .limit(25)
    ).all()

    timeline: list[RegistryTimelineItem] = [
        RegistryTimelineItem(
            id=f"unit:{unit.id}",
            kind="fact",
            source="identity",
            title="Unit issued",
            description=f"Serial {unit.serial} was issued for {product.name}.",
            occurred_at=unit.created_at.isoformat(),
        )
    ]

    if registration is not None:
        timeline.append(
            RegistryTimelineItem(
                id=f"registration:{registration.id}",
                kind="fact",
                source="registration",
                title="Product registered",
                description="Customer registration and warranty state were recorded.",
                occurred_at=registration.registered_at.isoformat(),
            )
        )
        if registration.corrected_at is not None:
            timeline.append(
                RegistryTimelineItem(
                    id=f"registration-corrected:{registration.id}",
                    kind="fact",
                    source="registration",
                    title="Registration corrected",
                    description="An authorized merchant updated registration data.",
                    occurred_at=registration.corrected_at.isoformat(),
                )
            )

    for event in events:
        timeline.append(
            RegistryTimelineItem(
                id=f"verification:{event.id}",
                kind="fact",
                source="verification",
                title="Verification scan",
                description=f"Public verification returned {event.outcome.value}.",
                occurred_at=event.created_at.isoformat(),
            )
        )

    for signal in signals:
        timeline.append(
            RegistryTimelineItem(
                id=f"signal:{signal.id}",
                kind="derived",
                source="authenticity",
                title="Authenticity signal",
                description=signal.explanation,
                occurred_at=signal.window_ended_at.isoformat(),
            )
        )

    timeline.sort(key=lambda item: item.occurred_at, reverse=True)

    verification_count = int(
        session.scalar(
            select(func.count(VerificationEvent.id)).where(
                VerificationEvent.unit_id == unit.id
            )
        )
        or 0
    )
    open_signal_count = int(
        session.scalar(
            select(func.count(AuthenticitySignal.id)).where(
                AuthenticitySignal.unit_id == unit.id,
                AuthenticitySignal.state == AuthenticitySignalState.OPEN,
            )
        )
        or 0
    )

    registration_detail = None
    if registration is not None:
        registration_detail = RegistrationDetail(
            id=str(registration.id),
            customer_name=registration.customer_name,
            customer_email=registration.customer_email,
            purchase_date=(
                registration.purchase_date.isoformat()
                if registration.purchase_date
                else None
            ),
            registered_at=registration.registered_at.isoformat(),
            warranty_started_on=registration.warranty_started_on.isoformat(),
            warranty_expires_on=registration.warranty_expires_on.isoformat(),
            warranty_state=warranty_state(registration).value,
        )

    return RegistryUnitDetail(
        id=str(unit.id),
        serial=unit.serial,
        status=unit.status,
        product_id=str(product.id),
        product_name=product.name,
        sku=product.sku,
        created_at=unit.created_at.isoformat(),
        registration=registration_detail,
        verification_count=verification_count,
        open_signal_count=open_signal_count,
        timeline=timeline,
    )
