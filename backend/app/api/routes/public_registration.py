from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.proof_deps import get_proof_grant_factory
from app.api.routes.identity import get_token_factory
from app.api.routes.public_verification import _client_key
from app.db.session import get_db_session
from app.services.proof import ProofUploadGrantFactory
from app.services.rate_limit import (
    InMemoryFixedWindowRateLimiter,
    RateLimitExceeded,
    VerificationRateLimiter,
)
from app.services.serialization import VerificationTokenFactory
from app.services.warranty import (
    RegistrationConflict,
    RegistrationIdempotencyConflict,
    RegistrationInput,
    RegistrationTokenInvalid,
    WarrantyPolicyMissing,
    register_unit,
    warranty_state,
)

router = APIRouter(prefix="/v1/public", tags=["public-registration"])

_registration_limiter = InMemoryFixedWindowRateLimiter(limit=20, window_seconds=60)


class PublicRegistrationCreate(BaseModel):
    customer_name: str = Field(min_length=1, max_length=200)
    customer_email: str = Field(min_length=3, max_length=320)
    purchase_date: date | None = None


class PublicRegistrationResponse(BaseModel):
    registration_id: str
    proof_upload_token: str
    replayed: bool
    warranty_state: str
    warranty_started_on: date
    warranty_expires_on: date
    message: str


def get_registration_rate_limiter() -> VerificationRateLimiter:
    return _registration_limiter


@router.post(
    "/register/{token}",
    response_model=PublicRegistrationResponse,
    status_code=status.HTTP_201_CREATED,
)
def register_product(
    token: Annotated[str, Path(min_length=32, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")],
    payload: PublicRegistrationCreate,
    request: Request,
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=1, max_length=200),
    ],
    session: Annotated[Session, Depends(get_db_session)],
    token_factory: Annotated[VerificationTokenFactory, Depends(get_token_factory)],
    proof_grant_factory: Annotated[ProofUploadGrantFactory, Depends(get_proof_grant_factory)],
    limiter: Annotated[VerificationRateLimiter, Depends(get_registration_rate_limiter)],
) -> PublicRegistrationResponse:
    try:
        limiter.check(_client_key(request))
    except RateLimitExceeded as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many registration attempts. Please try again shortly.",
        ) from exc

    try:
        result = register_unit(
            session,
            token=token,
            token_factory=token_factory,
            idempotency_key=idempotency_key,
            payload=RegistrationInput(
                customer_name=payload.customer_name,
                customer_email=payload.customer_email,
                purchase_date=payload.purchase_date,
            ),
        )
        session.commit()
    except RegistrationTokenInvalid as exc:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except WarrantyPolicyMissing as exc:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except (RegistrationConflict, RegistrationIdempotencyConflict) as exc:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ValueError as exc:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This product registration already exists",
        ) from exc

    registration = result.registration
    return PublicRegistrationResponse(
        registration_id=str(registration.id),
        proof_upload_token=proof_grant_factory.token_for_registration(registration.id),
        replayed=result.replayed,
        warranty_state=warranty_state(registration).value,
        warranty_started_on=registration.warranty_started_on,
        warranty_expires_on=registration.warranty_expires_on,
        message="Product registered and warranty activated.",
    )
