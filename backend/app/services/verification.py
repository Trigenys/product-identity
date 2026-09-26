from dataclasses import dataclass
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.auth import Organization
from app.models.identity import Product, Unit, UnitStatus, VerificationEvent, VerificationOutcome
from app.models.warranty import ProductRegistration, WarrantyState
from app.services.authenticity import AuthenticityThresholds, evaluate_authenticity_signals
from app.services.serialization import VerificationTokenFactory
from app.services.warranty import warranty_state


@dataclass(frozen=True)
class VerificationContext:
    country_code: str | None = None
    device_class: str | None = None


@dataclass(frozen=True)
class PublicVerification:
    outcome: VerificationOutcome
    brand_name: str | None
    product_name: str | None
    sku: str | None
    serial: str | None
    warranty_state: WarrantyState | None
    warranty_started_on: date | None
    warranty_expires_on: date | None


def verify_public_token(
    session: Session,
    *,
    token: str,
    token_factory: VerificationTokenFactory,
    context: VerificationContext | None = None,
    thresholds: AuthenticityThresholds | None = None,
) -> PublicVerification:
    digest = token_factory.digest(token)
    event_context = context or VerificationContext()
    now = datetime.now(timezone.utc)

    unit = session.scalar(
        select(Unit)
        .options(selectinload(Unit.product))
        .where(Unit.verification_token_digest == digest)
    )

    if unit is None:
        session.add(
            VerificationEvent(
                unit_id=None,
                token_digest=digest,
                outcome=VerificationOutcome.UNKNOWN,
                country_code=event_context.country_code,
                device_class=event_context.device_class,
                created_at=now,
            )
        )
        session.flush()
        return PublicVerification(
            outcome=VerificationOutcome.UNKNOWN,
            brand_name=None,
            product_name=None,
            sku=None,
            serial=None,
            warranty_state=None,
            warranty_started_on=None,
            warranty_expires_on=None,
        )

    organization = session.scalar(
        select(Organization).where(Organization.id == unit.organization_id)
    )
    outcome = (
        VerificationOutcome.REVOKED
        if unit.status == UnitStatus.REVOKED
        else VerificationOutcome.VALID
    )

    registration = session.scalar(
        select(ProductRegistration).where(ProductRegistration.unit_id == unit.id)
    )
    if registration is None:
        public_warranty_state = WarrantyState.UNREGISTERED
        warranty_started_on = None
        warranty_expires_on = None
    else:
        public_warranty_state = warranty_state(registration)
        warranty_started_on = registration.warranty_started_on
        warranty_expires_on = registration.warranty_expires_on

    session.add(
        VerificationEvent(
            unit_id=unit.id,
            token_digest=digest,
            outcome=outcome,
            country_code=event_context.country_code,
            device_class=event_context.device_class,
            created_at=now,
        )
    )
    session.flush()

    evaluate_authenticity_signals(
        session,
        unit=unit,
        now=now,
        thresholds=thresholds,
    )

    product: Product = unit.product
    return PublicVerification(
        outcome=outcome,
        brand_name=organization.name if organization is not None else None,
        product_name=product.name,
        sku=product.sku,
        serial=unit.serial,
        warranty_state=public_warranty_state,
        warranty_started_on=warranty_started_on,
        warranty_expires_on=warranty_expires_on,
    )
