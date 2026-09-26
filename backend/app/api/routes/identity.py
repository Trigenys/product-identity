import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import get_settings
from app.db.session import get_db_session
from app.models.auth import MembershipRole, User
from app.models.identity import Product
from app.services.serialization import (
    IdempotencyConflict,
    ProductNotFound,
    VerificationTokenFactory,
    create_serialization_batch,
)
from app.services.tenancy import TenantAccessDenied, require_membership

router = APIRouter(prefix="/v1/organizations/{organization_id}", tags=["identity"])


class ProductCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    sku: str = Field(min_length=1, max_length=120)


class ProductResponse(BaseModel):
    id: str
    organization_id: str
    name: str
    sku: str


class SerializationBatchCreate(BaseModel):
    quantity: int = Field(ge=1, le=500)
    prefix: str | None = Field(default=None, max_length=20)


class IssuedUnitResponse(BaseModel):
    id: str
    serial: str
    status: str
    verification_token: str


class SerializationBatchResponse(BaseModel):
    id: str
    product_id: str
    replayed: bool
    units: list[IssuedUnitResponse]


def get_token_factory() -> VerificationTokenFactory:
    secret = get_settings().verification_token_secret
    return VerificationTokenFactory(secret)


def _require_write_membership(
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
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Organization access denied") from exc


@router.post("/products", response_model=ProductResponse, status_code=status.HTTP_201_CREATED)
def create_product(
    organization_id: uuid.UUID,
    payload: ProductCreate,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> ProductResponse:
    _require_write_membership(session, user=user, organization_id=organization_id)

    product = Product(
        organization_id=organization_id,
        name=payload.name.strip(),
        sku=payload.sku.strip(),
    )
    session.add(product)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="SKU already exists in this organization",
        ) from exc

    return ProductResponse(
        id=str(product.id),
        organization_id=str(product.organization_id),
        name=product.name,
        sku=product.sku,
    )


@router.post(
    "/products/{product_id}/serialization-batches",
    response_model=SerializationBatchResponse,
    status_code=status.HTTP_201_CREATED,
)
def serialize_units(
    organization_id: uuid.UUID,
    product_id: uuid.UUID,
    payload: SerializationBatchCreate,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=200)],
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db_session)],
    token_factory: Annotated[VerificationTokenFactory, Depends(get_token_factory)],
) -> SerializationBatchResponse:
    _require_write_membership(session, user=user, organization_id=organization_id)

    try:
        result = create_serialization_batch(
            session,
            organization_id=organization_id,
            product_id=product_id,
            quantity=payload.quantity,
            prefix=payload.prefix,
            idempotency_key=idempotency_key,
            token_factory=token_factory,
        )
        session.commit()
    except ProductNotFound as exc:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except IdempotencyConflict as exc:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ValueError as exc:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Serialization request conflicted with an existing identity",
        ) from exc

    return SerializationBatchResponse(
        id=str(result.batch.id),
        product_id=str(result.batch.product_id),
        replayed=result.replayed,
        units=[
            IssuedUnitResponse(
                id=str(item.unit.id),
                serial=item.unit.serial,
                status=item.unit.status.value,
                verification_token=item.verification_token,
            )
            for item in result.issued_units
        ],
    )
