import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Header, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.proof_deps import get_object_storage, get_proof_grant_factory
from app.core.config import get_settings
from app.db.session import get_db_session
from app.services.proof import (
    MAX_PROOF_BYTES,
    ProofAccessDenied,
    ProofAlreadyExists,
    ProofNotFound,
    ProofUploadGrantFactory,
    ProofValidationError,
    create_proof,
    validate_proof_upload,
)
from app.services.storage import ObjectStorage, ObjectStorageError

router = APIRouter(prefix="/v1/public", tags=["public-proof"])


class PublicProofResponse(BaseModel):
    proof_id: str
    content_type: str
    size_bytes: int
    review_state: str
    retention_until: str
    message: str


@router.post(
    "/registrations/{registration_id}/proof",
    response_model=PublicProofResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_purchase_proof(
    registration_id: uuid.UUID,
    upload_grant: Annotated[
        str,
        Header(alias="X-Proof-Upload-Grant", min_length=32, max_length=128),
    ],
    file: Annotated[UploadFile, File(...)],
    session: Annotated[Session, Depends(get_db_session)],
    grant_factory: Annotated[ProofUploadGrantFactory, Depends(get_proof_grant_factory)],
    storage: Annotated[ObjectStorage, Depends(get_object_storage)],
) -> PublicProofResponse:
    if not grant_factory.verify(registration_id, upload_grant):
        await file.close()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Proof upload grant is invalid",
        )

    body = await file.read(MAX_PROOF_BYTES + 1)
    if len(body) > MAX_PROOF_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Proof file exceeds the 8 MB limit",
        )

    try:
        validated = validate_proof_upload(
            body=body,
            content_type=file.content_type,
            filename=file.filename,
        )
        proof = create_proof(
            session,
            storage=storage,
            registration_id=registration_id,
            upload_grant=upload_grant,
            grant_factory=grant_factory,
            validated=validated,
            retention_days=get_settings().proof_retention_days,
        )
        session.commit()
    except ProofAccessDenied as exc:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ProofNotFound as exc:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ProofAlreadyExists as exc:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ProofValidationError as exc:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    except ObjectStorageError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Proof storage is temporarily unavailable",
        ) from exc
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Purchase proof could not be attached",
        ) from exc
    finally:
        await file.close()

    return PublicProofResponse(
        proof_id=str(proof.id),
        content_type=proof.content_type,
        size_bytes=proof.size_bytes,
        review_state=proof.review_state.value,
        retention_until=proof.retention_until.isoformat(),
        message="Purchase proof uploaded privately.",
    )
