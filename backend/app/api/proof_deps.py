from typing import Annotated

from fastapi import Depends, HTTPException, status

from app.core.config import Settings, get_settings
from app.services.proof import ProofUploadGrantFactory
from app.services.storage import ObjectStorage, S3PrivateObjectStorage, S3StorageConfig


def get_proof_grant_factory(
    settings: Annotated[Settings, Depends(get_settings)],
) -> ProofUploadGrantFactory:
    try:
        return ProofUploadGrantFactory(settings.proof_upload_secret)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Proof upload service is not configured",
        ) from exc


def get_object_storage(
    settings: Annotated[Settings, Depends(get_settings)],
) -> ObjectStorage:
    required = (
        settings.object_storage_bucket,
        settings.object_storage_access_key_id,
        settings.object_storage_secret_access_key,
    )
    if not all(required):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Private object storage is not configured",
        )

    return S3PrivateObjectStorage(
        S3StorageConfig(
            bucket=settings.object_storage_bucket,
            region=settings.object_storage_region,
            endpoint_url=settings.object_storage_endpoint_url,
            access_key_id=settings.object_storage_access_key_id,
            secret_access_key=settings.object_storage_secret_access_key,
        )
    )
