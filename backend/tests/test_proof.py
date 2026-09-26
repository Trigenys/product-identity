from datetime import datetime, timedelta, timezone
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.auth import Organization, User
from app.models.proof import ProofOfPurchase, ProofReviewState
from app.services.proof import (
    MAX_PROOF_BYTES,
    ProofValidationError,
    purge_expired_proofs,
    validate_proof_upload,
)


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _registered_unit(
    client: TestClient,
    organization_id: str,
    token: str,
    *,
    sku: str = "PROOF-1",
    batch_key: str = "proof-batch",
    registration_key: str = "proof-registration",
) -> dict[str, str]:
    product = client.post(
        f"/v1/organizations/{organization_id}/products",
        json={"name": "Proof Device", "sku": sku},
        headers=_auth(token),
    )
    assert product.status_code == 201
    product_id = product.json()["id"]

    policy = client.put(
        f"/v1/organizations/{organization_id}/products/{product_id}/warranty-policy",
        json={
            "duration_months": 12,
            "start_rule": "purchase_date_or_registration",
        },
        headers=_auth(token),
    )
    assert policy.status_code == 200

    batch = client.post(
        f"/v1/organizations/{organization_id}/products/{product_id}/serialization-batches",
        json={"quantity": 1, "prefix": "PRF"},
        headers={
            **_auth(token),
            "Idempotency-Key": batch_key,
        },
    )
    assert batch.status_code == 201
    issued = batch.json()["units"][0]

    registration = client.post(
        f"/v1/public/register/{issued['verification_token']}",
        json={
            "customer_name": "Receipt Owner",
            "customer_email": "receipt@example.com",
            "purchase_date": "2026-09-20",
        },
        headers={"Idempotency-Key": registration_key},
    )
    assert registration.status_code == 201

    return {
        "registration_id": registration.json()["registration_id"],
        "proof_upload_token": registration.json()["proof_upload_token"],
        "verification_token": issued["verification_token"],
    }


def _upload_pdf(
    client: TestClient,
    registration_id: str,
    proof_upload_token: str,
) -> dict[str, object]:
    response = client.post(
        f"/v1/public/registrations/{registration_id}/proof",
        headers={"X-Proof-Upload-Grant": proof_upload_token},
        files={
            "file": (
                "invoice.pdf",
                b"%PDF-1.7\nprivate receipt data",
                "application/pdf",
            )
        },
    )
    assert response.status_code == 201
    return response.json()


def test_registration_returns_stable_dedicated_proof_upload_grant(
    client: TestClient,
    seeded_user: tuple[User, Organization, Organization],
    token: str,
) -> None:
    _, own_org, _ = seeded_user
    created = _registered_unit(client, str(own_org.id), token)

    assert len(created["proof_upload_token"]) >= 32
    assert created["proof_upload_token"] != created["verification_token"]


def test_private_proof_upload_and_signed_merchant_download(
    client: TestClient,
    storage,
    seeded_user: tuple[User, Organization, Organization],
    token: str,
) -> None:
    _, own_org, _ = seeded_user
    created = _registered_unit(
        client,
        str(own_org.id),
        token,
        sku="PROOF-UPLOAD",
        batch_key="proof-upload-batch",
        registration_key="proof-upload-registration",
    )

    uploaded = _upload_pdf(
        client,
        created["registration_id"],
        created["proof_upload_token"],
    )

    assert uploaded["review_state"] == "pending"
    assert uploaded["content_type"] == "application/pdf"
    assert len(storage.objects) == 1
    object_key = next(iter(storage.objects))
    assert object_key.startswith(f"proofs/{own_org.id}/{created['registration_id']}/")
    assert "invoice.pdf" not in object_key

    metadata = client.get(
        f"/v1/organizations/{own_org.id}/registrations/{created['registration_id']}/proof",
        headers=_auth(token),
    )
    assert metadata.status_code == 200
    assert metadata.json()["original_filename"] == "invoice.pdf"
    assert "object_key" not in metadata.json()
    assert "url" not in metadata.json()

    download = client.post(
        f"/v1/organizations/{own_org.id}/registrations/{created['registration_id']}/proof/download",
        headers=_auth(token),
    )
    assert download.status_code == 200
    assert download.json()["expires_in_seconds"] == 300
    assert download.json()["url"].startswith("https://storage.test/private/")
    assert "expires=300" in download.json()["url"]


def test_proof_is_never_exposed_by_public_verification(
    client: TestClient,
    seeded_user: tuple[User, Organization, Organization],
    token: str,
) -> None:
    _, own_org, _ = seeded_user
    created = _registered_unit(
        client,
        str(own_org.id),
        token,
        sku="NO-PUBLIC-PROOF",
        batch_key="no-public-proof-batch",
        registration_key="no-public-proof-registration",
    )
    _upload_pdf(client, created["registration_id"], created["proof_upload_token"])

    verification = client.get(
        f"/v1/public/verify/{created['verification_token']}"
    )
    assert verification.status_code == 200
    body = verification.json()
    assert not any("proof" in key.lower() for key in body)
    assert "invoice.pdf" not in verification.text
    assert "storage.test" not in verification.text


def test_invalid_grant_is_rejected_without_storing_file(
    client: TestClient,
    storage,
    seeded_user: tuple[User, Organization, Organization],
    token: str,
) -> None:
    _, own_org, _ = seeded_user
    created = _registered_unit(
        client,
        str(own_org.id),
        token,
        sku="BAD-GRANT",
        batch_key="bad-grant-batch",
        registration_key="bad-grant-registration",
    )

    response = client.post(
        f"/v1/public/registrations/{created['registration_id']}/proof",
        headers={"X-Proof-Upload-Grant": "x" * 43},
        files={"file": ("invoice.pdf", b"%PDF-1.7\ndata", "application/pdf")},
    )

    assert response.status_code == 403
    assert storage.objects == {}


@pytest.mark.parametrize(
    ("filename", "content_type", "body"),
    [
        ("fake.pdf", "application/pdf", b"not a pdf"),
        ("script.svg", "image/svg+xml", b"<svg></svg>"),
        ("fake.jpg", "image/jpeg", b"not jpeg"),
    ],
)
def test_proof_type_and_magic_bytes_are_enforced(
    client: TestClient,
    storage,
    seeded_user: tuple[User, Organization, Organization],
    token: str,
    filename: str,
    content_type: str,
    body: bytes,
) -> None:
    _, own_org, _ = seeded_user
    created = _registered_unit(
        client,
        str(own_org.id),
        token,
        sku=f"TYPE-{filename}",
        batch_key=f"type-batch-{filename}",
        registration_key=f"type-registration-{filename}",
    )

    response = client.post(
        f"/v1/public/registrations/{created['registration_id']}/proof",
        headers={"X-Proof-Upload-Grant": created["proof_upload_token"]},
        files={"file": (filename, body, content_type)},
    )

    assert response.status_code == 422
    assert storage.objects == {}


def test_proof_size_limit_is_enforced_before_storage() -> None:
    with pytest.raises(ProofValidationError, match="8 MB"):
        validate_proof_upload(
            body=b"%PDF-" + (b"x" * MAX_PROOF_BYTES),
            content_type="application/pdf",
            filename="huge.pdf",
        )


def test_merchant_review_is_tenant_scoped(
    client: TestClient,
    seeded_user: tuple[User, Organization, Organization],
    token: str,
) -> None:
    _, own_org, other_org = seeded_user
    created = _registered_unit(
        client,
        str(own_org.id),
        token,
        sku="REVIEW",
        batch_key="review-batch",
        registration_key="review-registration",
    )
    _upload_pdf(client, created["registration_id"], created["proof_upload_token"])

    reviewed = client.patch(
        f"/v1/organizations/{own_org.id}/registrations/{created['registration_id']}/proof/review",
        json={"state": "accepted"},
        headers=_auth(token),
    )
    assert reviewed.status_code == 200
    assert reviewed.json()["review_state"] == "accepted"
    assert reviewed.json()["reviewer_user_id"] is not None

    cross_tenant = client.get(
        f"/v1/organizations/{other_org.id}/registrations/{created['registration_id']}/proof",
        headers=_auth(token),
    )
    assert cross_tenant.status_code == 403


def test_deletion_revokes_application_access_and_removes_private_object(
    client: TestClient,
    storage,
    seeded_user: tuple[User, Organization, Organization],
    token: str,
) -> None:
    _, own_org, _ = seeded_user
    created = _registered_unit(
        client,
        str(own_org.id),
        token,
        sku="DELETE",
        batch_key="delete-batch",
        registration_key="delete-registration",
    )
    _upload_pdf(client, created["registration_id"], created["proof_upload_token"])
    object_key = next(iter(storage.objects))

    deleted = client.delete(
        f"/v1/organizations/{own_org.id}/registrations/{created['registration_id']}/proof",
        headers=_auth(token),
    )
    assert deleted.status_code == 204
    assert object_key not in storage.objects
    assert object_key in storage.deleted

    metadata = client.get(
        f"/v1/organizations/{own_org.id}/registrations/{created['registration_id']}/proof",
        headers=_auth(token),
    )
    assert metadata.status_code == 404


def test_retention_purge_logically_deletes_expired_proofs(
    client: TestClient,
    storage,
    session: Session,
    seeded_user: tuple[User, Organization, Organization],
    token: str,
) -> None:
    _, own_org, _ = seeded_user
    created = _registered_unit(
        client,
        str(own_org.id),
        token,
        sku="RETENTION",
        batch_key="retention-batch",
        registration_key="retention-registration",
    )
    _upload_pdf(client, created["registration_id"], created["proof_upload_token"])

    proof = session.scalar(
        select(ProofOfPurchase).where(
            ProofOfPurchase.registration_id == uuid.UUID(created["registration_id"])
        )
    )
    assert proof is not None
    object_key = proof.object_key
    proof.retention_until = datetime.now(timezone.utc) - timedelta(seconds=1)
    session.commit()

    purged = purge_expired_proofs(
        session,
        storage=storage,
        now=datetime.now(timezone.utc),
    )
    session.commit()

    assert purged == 1
    refreshed = session.get(ProofOfPurchase, proof.id)
    assert refreshed is not None
    assert refreshed.deleted_at is not None
    assert object_key not in storage.objects
