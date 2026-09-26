import base64
import hashlib
import hmac
import json
import re
import secrets
import uuid
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.identity import Product, SerializationBatch, Unit

_PREFIX_PATTERN = re.compile(r"^[A-Z0-9-]{1,20}$")


class ProductNotFound(Exception):
    pass


class IdempotencyConflict(Exception):
    pass


class SerialGenerationError(Exception):
    pass


class SerialPolicy(Protocol):
    def generate(self) -> str:
        ...


class RandomSerialPolicy:
    def __init__(self, prefix: str | None = None) -> None:
        normalized = prefix.upper().strip() if prefix else None
        if normalized and not _PREFIX_PATTERN.fullmatch(normalized):
            raise ValueError("Serial prefix must contain only A-Z, 0-9 and hyphens")
        self._prefix = normalized

    def generate(self) -> str:
        suffix = secrets.token_hex(10).upper()
        return f"{self._prefix}-{suffix}" if self._prefix else suffix


class VerificationTokenFactory:
    def __init__(self, secret: str) -> None:
        if len(secret.encode("utf-8")) < 32:
            raise ValueError("Verification token secret must be at least 32 bytes")
        self._secret = secret.encode("utf-8")

    def token_for_unit(self, unit_id: uuid.UUID) -> str:
        digest = hmac.new(self._secret, unit_id.bytes, hashlib.sha256).digest()
        return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")

    @staticmethod
    def digest(token: str) -> str:
        return hashlib.sha256(token.encode("ascii")).hexdigest()


@dataclass(frozen=True)
class IssuedUnit:
    unit: Unit
    verification_token: str


@dataclass(frozen=True)
class BatchResult:
    batch: SerializationBatch
    issued_units: list[IssuedUnit]
    replayed: bool


def _request_fingerprint(*, product_id: uuid.UUID, quantity: int, prefix: str | None) -> str:
    payload = json.dumps(
        {
            "product_id": str(product_id),
            "quantity": quantity,
            "prefix": prefix.upper().strip() if prefix else None,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _load_batch(
    session: Session,
    *,
    organization_id: uuid.UUID,
    idempotency_key: str,
) -> SerializationBatch | None:
    return session.scalar(
        select(SerializationBatch)
        .options(selectinload(SerializationBatch.units))
        .where(
            SerializationBatch.organization_id == organization_id,
            SerializationBatch.idempotency_key == idempotency_key,
        )
    )


def create_serialization_batch(
    session: Session,
    *,
    organization_id: uuid.UUID,
    product_id: uuid.UUID,
    quantity: int,
    idempotency_key: str,
    token_factory: VerificationTokenFactory,
    prefix: str | None = None,
    serial_policy: SerialPolicy | None = None,
) -> BatchResult:
    if quantity < 1 or quantity > 500:
        raise ValueError("Quantity must be between 1 and 500")

    clean_key = idempotency_key.strip()
    if not clean_key or len(clean_key) > 200:
        raise ValueError("Idempotency key is required and must be at most 200 characters")

    fingerprint = _request_fingerprint(product_id=product_id, quantity=quantity, prefix=prefix)
    existing_batch = _load_batch(
        session,
        organization_id=organization_id,
        idempotency_key=clean_key,
    )
    if existing_batch is not None:
        if existing_batch.request_fingerprint != fingerprint:
            raise IdempotencyConflict("Idempotency key was already used with a different request")
        return BatchResult(
            batch=existing_batch,
            issued_units=[
                IssuedUnit(unit=unit, verification_token=token_factory.token_for_unit(unit.id))
                for unit in existing_batch.units
            ],
            replayed=True,
        )

    product = session.scalar(
        select(Product).where(
            Product.id == product_id,
            Product.organization_id == organization_id,
        )
    )
    if product is None:
        raise ProductNotFound("Product does not exist in this organization")

    policy = serial_policy or RandomSerialPolicy(prefix)
    batch = SerializationBatch(
        organization_id=organization_id,
        product_id=product_id,
        idempotency_key=clean_key,
        request_fingerprint=fingerprint,
        quantity=quantity,
        prefix=prefix.upper().strip() if prefix else None,
    )
    session.add(batch)
    session.flush()

    generated_serials: set[str] = set()
    generated_token_digests: set[str] = set()
    issued: list[IssuedUnit] = []

    for sequence_number in range(1, quantity + 1):
        unit_id = uuid.uuid4()

        for _ in range(12):
            serial = policy.generate()
            serial_exists = serial in generated_serials or session.scalar(
                select(Unit.id).where(
                    Unit.organization_id == organization_id,
                    Unit.serial == serial,
                )
            ) is not None
            if not serial_exists:
                break
        else:
            raise SerialGenerationError("Unable to generate a unique serial")

        token = token_factory.token_for_unit(unit_id)
        token_digest = token_factory.digest(token)
        if token_digest in generated_token_digests or session.scalar(
            select(Unit.id).where(Unit.verification_token_digest == token_digest)
        ) is not None:
            raise SerialGenerationError("Verification token collision detected")

        unit = Unit(
            id=unit_id,
            organization_id=organization_id,
            product_id=product_id,
            batch_id=batch.id,
            sequence_number=sequence_number,
            serial=serial,
            verification_token_digest=token_digest,
        )
        session.add(unit)
        generated_serials.add(serial)
        generated_token_digests.add(token_digest)
        issued.append(IssuedUnit(unit=unit, verification_token=token))

    session.flush()
    return BatchResult(batch=batch, issued_units=issued, replayed=False)
