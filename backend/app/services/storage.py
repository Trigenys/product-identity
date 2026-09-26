from dataclasses import dataclass
from typing import Protocol

import boto3
from botocore.client import Config


class ObjectStorageError(Exception):
    pass


class ObjectStorage(Protocol):
    def put_private(self, *, key: str, body: bytes, content_type: str) -> None:
        ...

    def create_download_url(self, *, key: str, expires_seconds: int) -> str:
        ...

    def delete(self, *, key: str) -> None:
        ...


@dataclass(frozen=True)
class S3StorageConfig:
    bucket: str
    region: str
    endpoint_url: str | None
    access_key_id: str
    secret_access_key: str


class S3PrivateObjectStorage:
    def __init__(self, config: S3StorageConfig) -> None:
        self._bucket = config.bucket
        self._client = boto3.client(
            "s3",
            region_name=config.region,
            endpoint_url=config.endpoint_url or None,
            aws_access_key_id=config.access_key_id,
            aws_secret_access_key=config.secret_access_key,
            config=Config(signature_version="s3v4"),
        )

    def put_private(self, *, key: str, body: bytes, content_type: str) -> None:
        try:
            self._client.put_object(
                Bucket=self._bucket,
                Key=key,
                Body=body,
                ContentType=content_type,
                CacheControl="private, no-store",
            )
        except Exception as exc:
            raise ObjectStorageError("Private object upload failed") from exc

    def create_download_url(self, *, key: str, expires_seconds: int) -> str:
        try:
            return str(
                self._client.generate_presigned_url(
                    "get_object",
                    Params={"Bucket": self._bucket, "Key": key},
                    ExpiresIn=expires_seconds,
                )
            )
        except Exception as exc:
            raise ObjectStorageError("Signed download URL generation failed") from exc

    def delete(self, *, key: str) -> None:
        try:
            self._client.delete_object(Bucket=self._bucket, Key=key)
        except Exception as exc:
            raise ObjectStorageError("Private object deletion failed") from exc
