import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.proof_deps import get_object_storage
from app.core.config import get_settings
from app.db.session import get_db_session
from app.models.auth import MembershipRole, User
from app.models.proof import ProofOfPurchase, ProofReviewState
from app.models.warranty import ProductRegistration
from app.services.proof import ProofNotFound, mark_proof_deleted
from app.services.storage import ObjectStorage, ObjectStorageError
from app.services.tenancy import TenantAccessDenied, require_membership

router = APIRouter(prefix="/v1/organizations/{organization_id}", tags=["proof-of-purchase"])


class ProofMetadataResponse(BaseModel):
    id: str
    registration_id: str
    original_filename: str
    content_type: str
    size_bytes: int
    sha256: str
    review_state: str
    reviewer_user_id: str | None
    reviewed_at: str | None
    uploaded_at: str
    retention_until: str


class ProofDownloadResponse(BaseModel):
    url: str
    expires_at: str
    expires_in_seconds: int


class ProofReviewRequest(BaseModel):
    state: ProofReviewState


def _require_proof_access(
    session: Session,
    *,
    user: User,
    organization_id: uuid.UUID,
    review: bool = False,
) -> None:
    roles = {MembershipRole.OWNER, MembershipRole.ADMIN, MembershipRole.MEMBER}
    if review:
        roles = {MembershipRole.OWNER, MembershipRole.ADMIN, MembershipRole.MEMBER}
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


def _get_active_proof(
    session: Session,
    *,
    organization_id: uuid.UUID,
    registration_id: uuid.UUID,
) -> ProofOfPurchase:
    proof = session.scalar(
        select(ProofOfPurchase).where(
            ProofOfPurchase.organization_id == organization_id,
            ProofOfPurchase.registration_id == registration_id,
            ProofOfPurchase.deleted_at.is_(None),
        )
    )
    if proof is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Purchase proof not found")
    return proof


def _metadata(proof: ProofOfPurchase) -> ProofMetadataResponse:
    return ProofMetadataResponse(
        id=str(proof.id),
        registration_id=str(proof.registration_id),
        original_filename=proof.original_filename,
        content_type=proof.content_type,
        size_bytes=proof.size_bytes,
        sha256=proof.sha256,
        review_state=proof.review_state.value,
        reviewer_user_id=str(proof.reviewer_user_id) if proof.reviewer_user_id else None,
        reviewed_at=proof.reviewed_at.isoformat() if proof.reviewed_at else None,
        uploaded_at=proof.uploaded_at.isoformat(),
        retention_until=proof.retention_until.isoformat(),
    )


@router.get(
    "/registrations/{registration_id}/proof",
    response_model=ProofMetadataResponse,
)
def get_proof_metadata(
    organization_id: uuid.UUID,
    registration_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> ProofMetadataResponse:
    _require_proof_access(session, user=user, organization_id=organization_id)
    return _metadata(
        _get_active_proof(
            session,
            organization_id=organization_id,
            registration_id=registration_id,
        )
    )


@router.post(
    "/registrations/{registration_id}/proof/download",
    response_model=ProofDownloadResponse,
)
def create_proof_download(
    organization_id: uuid.UUID,
    registration_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db_session)],
    storage: Annotated[ObjectStorage, Depends(get_object_storage)],
) -> ProofDownloadResponse:
    _require_proof_access(session, user=user, organization_id=organization_id)
    proof = _get_active_proof(
        session,
        organization_id=organization_id,
        registration_id=registration_id,
    )

    ttl = min(max(get_settings().proof_download_ttl_seconds, 60), 900)
    try:
        url = storage.create_download_url(key=proof.object_key, expires_seconds=ttl)
    except ObjectStorageError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Proof storage is temporarily unavailable",
        ) from exc

    expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl)
    return ProofDownloadResponse(
        url=url,
        expires_at=expires_at.isoformat(),
        expires_in_seconds=ttl,
    )


@router.patch(
    "/registrations/{registration_id}/proof/review",
    response_model=ProofMetadataResponse,
)
def review_proof(
    organization_id: uuid.UUID,
    registration_id: uuid.UUID,
    payload: ProofReviewRequest,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> ProofMetadataResponse:
    _require_proof_access(
        session,
        user=user,
        organization_id=organization_id,
        review=True,
    )
    if payload.state == ProofReviewState.PENDING:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Review state must be accepted or rejected",
        )

    proof = _get_active_proof(
        session,
        organization_id=organization_id,
        registration_id=registration_id,
    )
    proof.review_state = payload.state
    proof.reviewer_user_id = user.id
    proof.reviewed_at = datetime.now(timezone.utc)
    session.commit()
    return _metadata(proof)


@router.delete(
    "/registrations/{registration_id}/proof",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_purchase_proof(
    organization_id: uuid.UUID,
    registration_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db_session)],
    storage: Annotated[ObjectStorage, Depends(get_object_storage)],
) -> None:
    _require_proof_access(
        session,
        user=user,
        organization_id=organization_id,
        review=True,
    )

    try:
        _, object_key = mark_proof_deleted(
            session,
            organization_id=organization_id,
            registration_id=registration_id,
        )
        session.commit()
    except ProofNotFound as exc:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    # Deletion in the application is authoritative. A storage failure leaves
    # only a private orphan; it never restores application access.
    try:
        storage.delete(key=object_key)
    except ObjectStorageError:
        pass
