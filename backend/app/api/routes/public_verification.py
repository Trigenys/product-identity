from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Request, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.routes.identity import get_token_factory
from app.core.config import Settings, get_settings
from app.db.session import get_db_session
from app.models.authenticity import DeviceClass
from app.models.identity import VerificationOutcome
from app.models.warranty import WarrantyState
from app.services.authenticity import AuthenticityThresholds
from app.services.rate_limit import (
    InMemoryFixedWindowRateLimiter,
    RateLimitExceeded,
    VerificationRateLimiter,
)
from app.services.serialization import VerificationTokenFactory
from app.services.verification import VerificationContext, verify_public_token

router = APIRouter(prefix="/v1/public", tags=["public-verification"])

_default_limiter = InMemoryFixedWindowRateLimiter()


class PublicVerificationResponse(BaseModel):
    state: VerificationOutcome
    brand_name: str | None
    product_name: str | None
    sku: str | None
    serial: str | None
    warranty_state: WarrantyState | None
    warranty_started_on: date | None
    warranty_expires_on: date | None
    message: str


def get_verification_rate_limiter() -> VerificationRateLimiter:
    return _default_limiter


def get_authenticity_thresholds(
    settings: Annotated[Settings, Depends(get_settings)],
) -> AuthenticityThresholds:
    return AuthenticityThresholds(
        repeat_scan_count=max(settings.verification_repeat_scan_threshold, 2),
        repeat_scan_window_minutes=max(settings.verification_repeat_scan_window_minutes, 1),
        country_count=max(settings.verification_country_threshold, 2),
        country_window_hours=max(settings.verification_country_window_hours, 1),
    )


def _client_key(request: Request) -> str:
    # Used transiently for throttling only. It is deliberately not persisted
    # in VerificationEvent.
    if request.client is not None:
        return request.client.host
    return "unknown"


def _device_class(request: Request) -> str:
    mobile_hint = request.headers.get("sec-ch-ua-mobile")
    if mobile_hint == "?1":
        return DeviceClass.MOBILE.value
    if mobile_hint == "?0":
        return DeviceClass.DESKTOP.value
    return DeviceClass.UNKNOWN.value


def _country_code(request: Request, settings: Settings) -> str | None:
    if not settings.verification_trust_edge_country:
        return None

    raw = request.headers.get(settings.verification_country_header)
    if raw is None:
        return None

    candidate = raw.strip().upper()
    if len(candidate) != 2 or not candidate.isalpha() or candidate in {"XX"}:
        return None
    return candidate


@router.get(
    "/verify/{token}",
    response_model=PublicVerificationResponse,
    response_model_exclude_none=True,
)
def verify_product(
    token: Annotated[str, Path(min_length=32, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")],
    request: Request,
    session: Annotated[Session, Depends(get_db_session)],
    token_factory: Annotated[VerificationTokenFactory, Depends(get_token_factory)],
    limiter: Annotated[VerificationRateLimiter, Depends(get_verification_rate_limiter)],
    thresholds: Annotated[AuthenticityThresholds, Depends(get_authenticity_thresholds)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> PublicVerificationResponse:
    try:
        limiter.check(_client_key(request))
    except RateLimitExceeded as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many verification attempts. Please try again shortly.",
        ) from exc

    result = verify_public_token(
        session,
        token=token,
        token_factory=token_factory,
        context=VerificationContext(
            country_code=_country_code(request, settings),
            device_class=_device_class(request),
        ),
        thresholds=thresholds,
    )
    session.commit()

    messages = {
        VerificationOutcome.VALID: "This digital product identity is active.",
        VerificationOutcome.REVOKED: "This digital product identity has been revoked by the issuing brand.",
        VerificationOutcome.UNKNOWN: "This verification code is not recognized.",
    }

    return PublicVerificationResponse(
        state=result.outcome,
        brand_name=result.brand_name,
        product_name=result.product_name,
        sku=result.sku,
        serial=result.serial,
        warranty_state=result.warranty_state,
        warranty_started_on=result.warranty_started_on,
        warranty_expires_on=result.warranty_expires_on,
        message=messages[result.outcome],
    )
