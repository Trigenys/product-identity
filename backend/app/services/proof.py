import base64
import hashlib
import hmac
import re
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.proof import ProofOfPurchase, ProofReviewState
from app.models.warranty import ProductRegistration
from app.services.storage import ObjectStorage, ObjectStorageError

ALLOWED_PROOF_TYPES: dict[str, tuple[bytes, str]] = {
    "application/pdf": (b"%PDF-", ".pdf"),
    "image/jpeg": (b"\xff\xd8\xff", ".jpg"),
    "image/png": (b"\x89PNG\r\n\x1a\n", ".png"),
}
MAX_PROOF_BYTES = 8 * 1024 * 1024


class ProofAccessDenied(Exception):
    pass


class ProofAlreadyExists(Exception):
    pass


class ProofNotFound(Exception):
    pass


class ProofValidationError(ValueError):
    pass


class ProofUploadGrantFactory:
    def __init__(self, secret: str) -> None:
        if len(secret.encode("utf-8")) < 32:
            raise ValueError("Proof upload secret must be at least 32 bytes")
        self._secret = secret.encode("utf-8")

    def token_for_registration(self, registration_id: uuid.UUID) -> str:
        digest = hmac.new(
            self._secret,
            b"proof-upload:" + registration_id.bytes,
            hashlib.sha256,
        ).digest()
        return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")

    def verify(self, registration_id: uuid.UUID, token: str) -> bool:
        expected = self.token_for_registration(registration_id)
        return hmac.compare_digest(expected, token)


@dataclass(frozen=True)
class ValidatedProof:
    body: bytes
    content_type: str
    original_filename: str
    sha256: str
    extension: str


def _safe_filename(filename: str | None) -> str:
    candidate = (filename or "purchase-proof").strip()
    candidate = re.sub(r"[\x00-\x1f\x7f]+", "", candidate)
    candidate = candidate.replace("/", "_").replace("\\", "_")
    candidate = candidate[:180].strip()
    return candidate or "purchase-proof"


def validate_proof_upload(
    *,
    body: bytes,
    content_type: str | None,
    filename: str | None,
) -> ValidatedProof:
    if not body:
        raise ProofValidationError("Proof file is empty")
    if len(body) > MAX_PROOF_BYTES:
        raise ProofValidationError("Proof file exceeds the 8 MB limit")

    normalized_type = (content_type or "").split(";", maxsplit=1)[0].strip().lower()
    rule = ALLOWED_PROOF_TYPES.get(normalized_type)
    if rule is None:
        raise ProofValidationError("Only PDF, JPEG and PNG proof files are allowed")

    magic, extension = rule
    if not body.startswith(magic):
        raise ProofValidationError("File content does not match its declared content type")

    return ValidatedProof(
        body=body,
        content_type=normalized_type,
        original_filename=_safe_filename(filename),
        sha256=hashlib.sha256(body).hexdigest(),
        extension=extension,
    )


def create_proof(
    session: Session,
    *,
    storage: ObjectStorage,
    registration_id: uuid.UUID,
    upload_grant: str,
    grant_factory: ProofUploadGrantFactory,
    validated: ValidatedProof,
    retention_days: int,
) -> ProofOfPurchase:
    if not grant_factory.verify(registration_id, upload_grant):
        raise ProofAccessDenied("Proof upload grant is invalid")

    registration = session.get(ProductRegistration, registration_id)
    if registration is None:
        raise ProofNotFound("Registration not found")

    existing = session.scalar(
        select(ProofOfPurchase).where(ProofOfPurchase.registration_id == registration_id)
    )
    if existing is not None and existing.deleted_at is None:
        raise ProofAlreadyExists("A purchase proof is already attached to this registration")

    now = datetime.now(timezone.utc)
    object_key = (
        f"proofs/{registration.organization_id}/{registration.id}/"
        f"{uuid.uuid4().hex}{validated.extension}"
    )
    storage.put_private(
        key=object_key,
        body=validated.body,
        content_type=validated.content_type,
    )

    try:
        if existing is None:
            proof = ProofOfPurchase(
                organization_id=registration.organization_id,
                registration_id=registration.id,
                object_key=object_key,
                original_filename=validated.original_filename,
                content_type=validated.content_type,
                size_bytes=len(validated.body),
                sha256=validated.sha256,
                review_state=ProofReviewState.PENDING,
                retention_until=now + timedelta(days=retention_days),
                deleted_at=None,
            )
            session.add(proof)
        else:
            proof = existing
            proof.object_key = object_key
            proof.original_filename = validated.original_filename
            proof.content_type = validated.content_type
            proof.size_bytes = len(validated.body)
            proof.sha256 = validated.sha256
            proof.review_state = ProofReviewState.PENDING
            proof.reviewer_user_id = None
            proof.reviewed_at = None
            proof.uploaded_at = now
            proof.retention_until = now + timedelta(days=retention_days)
            proof.deleted_at = None

        session.flush()
        return proof
    except Exception:
        try:
            storage.delete(key=object_key)
        except ObjectStorageError:
            pass
        raise


def mark_proof_deleted(
    session: Session,
    *,
    organization_id: uuid.UUID,
    registration_id: uuid.UUID,
) -> tuple[ProofOfPurchase, str]:
    proof = session.scalar(
        select(ProofOfPurchase).where(
            ProofOfPurchase.organization_id == organization_id,
            ProofOfPurchase.registration_id == registration_id,
            ProofOfPurchase.deleted_at.is_(None),
        )
    )
    if proof is None:
        raise ProofNotFound("Purchase proof not found")

    object_key = proof.object_key
    proof.deleted_at = datetime.now(timezone.utc)
    session.flush()
    return proof, object_key


def purge_expired_proofs(
    session: Session,
    *,
    storage: ObjectStorage,
    now: datetime | None = None,
    limit: int = 100,
) -> int:
    cutoff = now or datetime.now(timezone.utc)
    proofs = session.scalars(
        select(ProofOfPurchase)
        .where(
            ProofOfPurchase.deleted_at.is_(None),
            ProofOfPurchase.retention_until <= cutoff,
        )
        .order_by(ProofOfPurchase.retention_until)
        .limit(limit)
    ).all()

    keys = []
    for proof in proofs:
        proof.deleted_at = cutoff
        keys.append(proof.object_key)

    session.flush()

    for key in keys:
        try:
            storage.delete(key=key)
        except ObjectStorageError:
            # Logical deletion is authoritative; private orphan cleanup can retry later.
            pass

    return len(proofs)
