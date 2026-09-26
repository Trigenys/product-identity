from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.auth import Organization
from app.models.identity import Product, Unit, UnitStatus, VerificationEvent, VerificationOutcome
from app.services.serialization import VerificationTokenFactory


@dataclass(frozen=True)
class PublicVerification:
    outcome: VerificationOutcome
    brand_name: str | None
    product_name: str | None
    sku: str | None
    serial: str | None


def verify_public_token(
    session: Session,
    *,
    token: str,
    token_factory: VerificationTokenFactory,
) -> PublicVerification:
    digest = token_factory.digest(token)
    unit = session.scalar(
        select(Unit)
        .options(
            selectinload(Unit.product),
        )
        .where(Unit.verification_token_digest == digest)
    )

    if unit is None:
        session.add(
            VerificationEvent(
                unit_id=None,
                token_digest=digest,
                outcome=VerificationOutcome.UNKNOWN,
            )
        )
        session.flush()
        return PublicVerification(
            outcome=VerificationOutcome.UNKNOWN,
            brand_name=None,
            product_name=None,
            sku=None,
            serial=None,
        )

    organization = session.scalar(
        select(Organization).where(Organization.id == unit.organization_id)
    )
    outcome = (
        VerificationOutcome.REVOKED
        if unit.status == UnitStatus.REVOKED
        else VerificationOutcome.VALID
    )

    session.add(
        VerificationEvent(
            unit_id=unit.id,
            token_digest=digest,
            outcome=outcome,
        )
    )
    session.flush()

    product: Product = unit.product
    return PublicVerification(
        outcome=outcome,
        brand_name=organization.name if organization is not None else None,
        product_name=product.name,
        sku=product.sku,
        serial=unit.serial,
    )
