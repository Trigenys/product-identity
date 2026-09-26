import calendar
import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.identity import Unit, UnitStatus
from app.models.warranty import (
    ProductRegistration,
    RegistrationActor,
    RegistrationAudit,
    WarrantyPolicy,
    WarrantyStartRule,
    WarrantyState,
)
from app.services.serialization import VerificationTokenFactory


class WarrantyPolicyMissing(Exception):
    pass


class RegistrationConflict(Exception):
    pass


class RegistrationIdempotencyConflict(Exception):
    pass


class RegistrationNotFound(Exception):
    pass


class RegistrationTokenInvalid(Exception):
    pass


@dataclass(frozen=True)
class RegistrationInput:
    customer_name: str
    customer_email: str
    purchase_date: date | None


@dataclass(frozen=True)
class RegistrationResult:
    registration: ProductRegistration
    replayed: bool


def _add_months(value: date, months: int) -> date:
    if months < 1:
        raise ValueError("Warranty duration must be at least one month")
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _normalize_input(payload: RegistrationInput) -> RegistrationInput:
    name = " ".join(payload.customer_name.strip().split())
    email = payload.customer_email.strip().lower()
    if not name:
        raise ValueError("Customer name is required")
    if not email:
        raise ValueError("Customer email is required")
    if "@" not in email or email.startswith("@") or email.endswith("@"):
        raise ValueError("Customer email is invalid")
    return RegistrationInput(
        customer_name=name,
        customer_email=email,
        purchase_date=payload.purchase_date,
    )


def _fingerprint(unit_id: uuid.UUID, payload: RegistrationInput) -> str:
    body = json.dumps(
        {
            "unit_id": str(unit_id),
            "customer_name": payload.customer_name,
            "customer_email": payload.customer_email,
            "purchase_date": payload.purchase_date.isoformat() if payload.purchase_date else None,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def warranty_state(registration: ProductRegistration, *, today: date | None = None) -> WarrantyState:
    current = today or datetime.now(timezone.utc).date()
    return (
        WarrantyState.ACTIVE
        if registration.warranty_started_on <= current <= registration.warranty_expires_on
        else WarrantyState.EXPIRED
    )


def calculate_warranty_dates(
    *,
    policy: WarrantyPolicy,
    registered_on: date,
    purchase_date: date | None,
) -> tuple[date, date]:
    if policy.duration_months < 1 or policy.duration_months > 120:
        raise ValueError("Warranty duration must be between 1 and 120 months")

    if policy.start_rule == WarrantyStartRule.REGISTRATION_DATE:
        started_on = registered_on
    elif policy.start_rule == WarrantyStartRule.PURCHASE_DATE_OR_REGISTRATION:
        started_on = purchase_date or registered_on
    else:
        raise ValueError("Unsupported warranty start rule")

    if started_on > registered_on:
        raise ValueError("Purchase date cannot be in the future")

    return started_on, _add_months(started_on, policy.duration_months)


def register_unit(
    session: Session,
    *,
    token: str,
    token_factory: VerificationTokenFactory,
    idempotency_key: str,
    payload: RegistrationInput,
    registered_on: date | None = None,
) -> RegistrationResult:
    clean_key = idempotency_key.strip()
    if not clean_key or len(clean_key) > 200:
        raise ValueError("Idempotency-Key is required and must be at most 200 characters")

    digest = token_factory.digest(token)
    unit = session.scalar(select(Unit).where(Unit.verification_token_digest == digest))
    if unit is None:
        raise RegistrationTokenInvalid("Verification code is not recognized")
    if unit.status != UnitStatus.ACTIVE:
        raise RegistrationTokenInvalid("Revoked product identities cannot be registered")

    normalized = _normalize_input(payload)
    fingerprint = _fingerprint(unit.id, normalized)

    existing_by_key = session.scalar(
        select(ProductRegistration).where(
            ProductRegistration.organization_id == unit.organization_id,
            ProductRegistration.idempotency_key == clean_key,
        )
    )
    if existing_by_key is not None:
        if existing_by_key.request_fingerprint != fingerprint:
            raise RegistrationIdempotencyConflict(
                "Idempotency key was already used with a different registration request"
            )
        return RegistrationResult(registration=existing_by_key, replayed=True)

    existing_by_unit = session.scalar(
        select(ProductRegistration).where(ProductRegistration.unit_id == unit.id)
    )
    if existing_by_unit is not None:
        raise RegistrationConflict("This product unit has already been registered")

    policy = session.scalar(
        select(WarrantyPolicy).where(
            WarrantyPolicy.organization_id == unit.organization_id,
            WarrantyPolicy.product_id == unit.product_id,
        )
    )
    if policy is None:
        raise WarrantyPolicyMissing("The issuing brand has not configured a warranty policy")

    today = registered_on or datetime.now(timezone.utc).date()
    started_on, expires_on = calculate_warranty_dates(
        policy=policy,
        registered_on=today,
        purchase_date=normalized.purchase_date,
    )

    registration = ProductRegistration(
        organization_id=unit.organization_id,
        product_id=unit.product_id,
        unit_id=unit.id,
        idempotency_key=clean_key,
        request_fingerprint=fingerprint,
        customer_name=normalized.customer_name,
        customer_email=normalized.customer_email,
        purchase_date=normalized.purchase_date,
        warranty_started_on=started_on,
        warranty_expires_on=expires_on,
        policy_duration_months=policy.duration_months,
        policy_start_rule=policy.start_rule,
    )
    session.add(registration)
    session.flush()

    after = _snapshot(registration)
    session.add(
        RegistrationAudit(
            organization_id=registration.organization_id,
            registration_id=registration.id,
            actor=RegistrationActor.CUSTOMER,
            actor_user_id=None,
            action="registered",
            before_json=None,
            after_json=json.dumps(after, sort_keys=True, separators=(",", ":")),
        )
    )
    session.flush()
    return RegistrationResult(registration=registration, replayed=False)


def _snapshot(registration: ProductRegistration) -> dict[str, object]:
    return {
        "customer_name": registration.customer_name,
        "customer_email": registration.customer_email,
        "purchase_date": registration.purchase_date.isoformat() if registration.purchase_date else None,
        "warranty_started_on": registration.warranty_started_on.isoformat(),
        "warranty_expires_on": registration.warranty_expires_on.isoformat(),
        "policy_duration_months": registration.policy_duration_months,
        "policy_start_rule": registration.policy_start_rule.value,
    }


def correct_registration(
    session: Session,
    *,
    organization_id: uuid.UUID,
    registration_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    customer_name: str | None = None,
    customer_email: str | None = None,
    purchase_date: date | None = None,
    purchase_date_supplied: bool = False,
) -> ProductRegistration:
    registration = session.scalar(
        select(ProductRegistration).where(
            ProductRegistration.id == registration_id,
            ProductRegistration.organization_id == organization_id,
        )
    )
    if registration is None:
        raise RegistrationNotFound("Registration not found")

    before = _snapshot(registration)

    if customer_name is not None:
        clean_name = " ".join(customer_name.strip().split())
        if not clean_name:
            raise ValueError("Customer name cannot be empty")
        registration.customer_name = clean_name
    if customer_email is not None:
        clean_email = customer_email.strip().lower()
        if not clean_email:
            raise ValueError("Customer email cannot be empty")
        registration.customer_email = clean_email
    if purchase_date_supplied:
        registration.purchase_date = purchase_date

    registered_on = registration.registered_at.date()
    if registration.policy_start_rule == WarrantyStartRule.REGISTRATION_DATE:
        started_on = registered_on
    else:
        started_on = registration.purchase_date or registered_on

    if started_on > datetime.now(timezone.utc).date():
        raise ValueError("Purchase date cannot be in the future")

    registration.warranty_started_on = started_on
    registration.warranty_expires_on = _add_months(
        started_on,
        registration.policy_duration_months,
    )
    registration.corrected_at = datetime.now(timezone.utc)
    session.flush()

    after = _snapshot(registration)
    session.add(
        RegistrationAudit(
            organization_id=organization_id,
            registration_id=registration.id,
            actor=RegistrationActor.MERCHANT,
            actor_user_id=actor_user_id,
            action="corrected",
            before_json=json.dumps(before, sort_keys=True, separators=(",", ":")),
            after_json=json.dumps(after, sort_keys=True, separators=(",", ":")),
        )
    )
    session.flush()
    return registration
