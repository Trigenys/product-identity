import json
import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db_session
from app.models.auth import MembershipRole, User
from app.models.identity import Product, Unit
from app.models.warranty import (
    ProductRegistration,
    RegistrationAudit,
    WarrantyPolicy,
    WarrantyStartRule,
)
from app.services.tenancy import TenantAccessDenied, require_membership
from app.services.warranty import RegistrationNotFound, correct_registration, warranty_state

router = APIRouter(prefix="/v1/organizations/{organization_id}", tags=["warranty"])


class WarrantyPolicyUpsert(BaseModel):
    duration_months: int = Field(ge=1, le=120)
    start_rule: WarrantyStartRule


class WarrantyPolicyResponse(BaseModel):
    id: str
    product_id: str
    duration_months: int
    start_rule: WarrantyStartRule


class RegistrationMerchantResponse(BaseModel):
    id: str
    unit_id: str
    product_id: str
    serial: str
    customer_name: str
    customer_email: str
    purchase_date: date | None
    registered_at: str
    warranty_started_on: date
    warranty_expires_on: date
    warranty_state: str


class RegistrationCorrection(BaseModel):
    customer_name: str | None = Field(default=None, min_length=1, max_length=200)
    customer_email: str | None = Field(default=None, min_length=3, max_length=320)
    purchase_date: date | None = None


class RegistrationAuditResponse(BaseModel):
    id: str
    version: int
    actor: str
    actor_user_id: str | None
    action: str
    before: dict[str, object] | None
    after: dict[str, object]
    created_at: str


def _require_membership(
    session: Session,
    *,
    user: User,
    organization_id: uuid.UUID,
    roles: set[MembershipRole],
) -> None:
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


def _registration_response(registration: ProductRegistration, serial: str) -> RegistrationMerchantResponse:
    return RegistrationMerchantResponse(
        id=str(registration.id),
        unit_id=str(registration.unit_id),
        product_id=str(registration.product_id),
        serial=serial,
        customer_name=registration.customer_name,
        customer_email=registration.customer_email,
        purchase_date=registration.purchase_date,
        registered_at=registration.registered_at.isoformat(),
        warranty_started_on=registration.warranty_started_on,
        warranty_expires_on=registration.warranty_expires_on,
        warranty_state=warranty_state(registration).value,
    )


@router.put(
    "/products/{product_id}/warranty-policy",
    response_model=WarrantyPolicyResponse,
)
def upsert_warranty_policy(
    organization_id: uuid.UUID,
    product_id: uuid.UUID,
    payload: WarrantyPolicyUpsert,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> WarrantyPolicyResponse:
    _require_membership(
        session,
        user=user,
        organization_id=organization_id,
        roles={MembershipRole.OWNER, MembershipRole.ADMIN},
    )

    product = session.scalar(
        select(Product).where(
            Product.id == product_id,
            Product.organization_id == organization_id,
        )
    )
    if product is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")

    policy = session.scalar(
        select(WarrantyPolicy).where(
            WarrantyPolicy.organization_id == organization_id,
            WarrantyPolicy.product_id == product_id,
        )
    )
    if policy is None:
        policy = WarrantyPolicy(
            organization_id=organization_id,
            product_id=product_id,
            duration_months=payload.duration_months,
            start_rule=payload.start_rule,
        )
        session.add(policy)
    else:
        policy.duration_months = payload.duration_months
        policy.start_rule = payload.start_rule

    session.commit()

    return WarrantyPolicyResponse(
        id=str(policy.id),
        product_id=str(policy.product_id),
        duration_months=policy.duration_months,
        start_rule=policy.start_rule,
    )


@router.get("/registrations", response_model=list[RegistrationMerchantResponse])
def list_registrations(
    organization_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db_session)],
    limit: int = Query(default=100, ge=1, le=200),
) -> list[RegistrationMerchantResponse]:
    _require_membership(
        session,
        user=user,
        organization_id=organization_id,
        roles={MembershipRole.OWNER, MembershipRole.ADMIN, MembershipRole.MEMBER},
    )

    rows = session.execute(
        select(ProductRegistration, Unit.serial)
        .join(Unit, Unit.id == ProductRegistration.unit_id)
        .where(ProductRegistration.organization_id == organization_id)
        .order_by(ProductRegistration.registered_at.desc())
        .limit(limit)
    ).all()

    return [_registration_response(registration, serial) for registration, serial in rows]


@router.patch(
    "/registrations/{registration_id}",
    response_model=RegistrationMerchantResponse,
)
def patch_registration(
    organization_id: uuid.UUID,
    registration_id: uuid.UUID,
    payload: RegistrationCorrection,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> RegistrationMerchantResponse:
    _require_membership(
        session,
        user=user,
        organization_id=organization_id,
        roles={MembershipRole.OWNER, MembershipRole.ADMIN},
    )

    try:
        registration = correct_registration(
            session,
            organization_id=organization_id,
            registration_id=registration_id,
            actor_user_id=user.id,
            customer_name=payload.customer_name,
            customer_email=payload.customer_email,
            purchase_date=payload.purchase_date,
            purchase_date_supplied="purchase_date" in payload.model_fields_set,
        )
        session.commit()
    except RegistrationNotFound as exc:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Registration correction conflicted with current state",
        ) from exc

    serial = session.scalar(select(Unit.serial).where(Unit.id == registration.unit_id))
    if serial is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Registered unit no longer exists")

    return _registration_response(registration, serial)


@router.get(
    "/registrations/{registration_id}/audit",
    response_model=list[RegistrationAuditResponse],
)
def registration_audit(
    organization_id: uuid.UUID,
    registration_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> list[RegistrationAuditResponse]:
    _require_membership(
        session,
        user=user,
        organization_id=organization_id,
        roles={MembershipRole.OWNER, MembershipRole.ADMIN},
    )

    registration_exists = session.scalar(
        select(ProductRegistration.id).where(
            ProductRegistration.id == registration_id,
            ProductRegistration.organization_id == organization_id,
        )
    )
    if registration_exists is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Registration not found")

    audits = session.scalars(
        select(RegistrationAudit)
        .where(
            RegistrationAudit.registration_id == registration_id,
            RegistrationAudit.organization_id == organization_id,
        )
        .order_by(RegistrationAudit.version)
    ).all()

    return [
        RegistrationAuditResponse(
            id=str(item.id),
            version=item.version,
            actor=item.actor.value,
            actor_user_id=str(item.actor_user_id) if item.actor_user_id else None,
            action=item.action,
            before=json.loads(item.before_json) if item.before_json else None,
            after=json.loads(item.after_json),
            created_at=item.created_at.isoformat(),
        )
        for item in audits
    ]
