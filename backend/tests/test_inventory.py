import csv
import io

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.auth import Organization, User
from app.models.identity import Unit


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _create_product(client: TestClient, organization_id: str, token: str) -> str:
    response = client.post(
        f"/v1/organizations/{organization_id}/products",
        json={"name": "Field Recorder", "sku": "REC-1"},
        headers=_auth(token),
    )
    assert response.status_code == 201
    return response.json()["id"]


def test_csv_dry_run_reports_bad_rows_without_persisting(
    client: TestClient,
    session: Session,
    seeded_user: tuple[User, Organization, Organization],
    token: str,
) -> None:
    _, own_org, _ = seeded_user
    product_id = _create_product(client, str(own_org.id), token)

    payload = "serial\nA-001\n\nA-001\nB-002\n"
    response = client.post(
        f"/v1/organizations/{own_org.id}/products/{product_id}/unit-imports?dry_run=true",
        content=payload,
        headers={**_auth(token), "Content-Type": "text/csv"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["dry_run"] is True
    assert body["imported_count"] == 2
    assert body["rejected_count"] == 2
    assert [item["code"] for item in body["errors"]] == ["missing_serial", "duplicate_in_file"]
    assert [item["serial"] for item in body["units"]] == ["A-001", "B-002"]
    assert session.scalar(select(func.count(Unit.id))) == 0


def test_csv_import_is_retry_safe_and_progress_is_queryable(
    client: TestClient,
    seeded_user: tuple[User, Organization, Organization],
    token: str,
) -> None:
    _, own_org, _ = seeded_user
    product_id = _create_product(client, str(own_org.id), token)
    payload = "serial\nA-001\nB-002\n"

    endpoint = f"/v1/organizations/{own_org.id}/products/{product_id}/unit-imports"
    headers = {
        **_auth(token),
        "Content-Type": "text/csv",
        "Idempotency-Key": "warehouse-import-001",
    }

    first = client.post(endpoint, content=payload, headers=headers)
    replay = client.post(endpoint, content=payload, headers=headers)

    assert first.status_code == 200
    assert replay.status_code == 200
    assert first.json()["replayed"] is False
    assert replay.json()["replayed"] is True
    assert first.json()["id"] == replay.json()["id"]
    assert first.json()["batch_id"] == replay.json()["batch_id"]
    assert first.json()["units"] == replay.json()["units"]

    status_response = client.get(
        f"/v1/organizations/{own_org.id}/unit-imports/{first.json()['id']}",
        headers=_auth(token),
    )
    assert status_response.status_code == 200
    assert status_response.json()["status"] == "completed"
    assert status_response.json()["imported_count"] == 2
    assert status_response.json()["rejected_count"] == 0


def test_same_import_key_rejects_different_csv(
    client: TestClient,
    seeded_user: tuple[User, Organization, Organization],
    token: str,
) -> None:
    _, own_org, _ = seeded_user
    product_id = _create_product(client, str(own_org.id), token)
    endpoint = f"/v1/organizations/{own_org.id}/products/{product_id}/unit-imports"
    headers = {
        **_auth(token),
        "Content-Type": "text/csv",
        "Idempotency-Key": "same-import",
    }

    assert client.post(endpoint, content="serial\nA-001\n", headers=headers).status_code == 200
    conflict = client.post(endpoint, content="serial\nB-002\n", headers=headers)
    assert conflict.status_code == 409


def test_existing_serial_is_rejected_but_new_rows_are_imported(
    client: TestClient,
    seeded_user: tuple[User, Organization, Organization],
    token: str,
) -> None:
    _, own_org, _ = seeded_user
    product_id = _create_product(client, str(own_org.id), token)
    endpoint = f"/v1/organizations/{own_org.id}/products/{product_id}/unit-imports"

    first = client.post(
        endpoint,
        content="serial\nEXISTING\n",
        headers={
            **_auth(token),
            "Content-Type": "text/csv",
            "Idempotency-Key": "first-import",
        },
    )
    assert first.status_code == 200

    second = client.post(
        endpoint,
        content="serial\nEXISTING\nNEW-001\n",
        headers={
            **_auth(token),
            "Content-Type": "text/csv",
            "Idempotency-Key": "second-import",
        },
    )

    assert second.status_code == 200
    body = second.json()
    assert body["imported_count"] == 1
    assert body["rejected_count"] == 1
    assert body["errors"][0]["code"] == "already_exists"
    assert body["units"][0]["serial"] == "NEW-001"


def test_csv_export_uses_opaque_verification_urls_and_neutralizes_formulas(
    client: TestClient,
    seeded_user: tuple[User, Organization, Organization],
    token: str,
) -> None:
    _, own_org, _ = seeded_user
    product_id = _create_product(client, str(own_org.id), token)
    import_response = client.post(
        f"/v1/organizations/{own_org.id}/products/{product_id}/unit-imports",
        content="serial\n=FORMULA\nSAFE-001\n",
        headers={
            **_auth(token),
            "Content-Type": "text/csv",
            "Idempotency-Key": "export-source",
        },
    )
    assert import_response.status_code == 200

    export = client.get(
        f"/v1/organizations/{own_org.id}/products/{product_id}/units.csv",
        headers=_auth(token),
    )

    assert export.status_code == 200
    rows = list(csv.DictReader(io.StringIO(export.text)))
    assert rows[0]["serial"] == "'=FORMULA"
    assert rows[1]["serial"] == "SAFE-001"
    assert all("/verify/" in row["verification_url"] for row in rows)
    assert all(product_id not in row["verification_url"] for row in rows)


def test_label_sheet_contains_printable_qr_assets(
    client: TestClient,
    seeded_user: tuple[User, Organization, Organization],
    token: str,
) -> None:
    _, own_org, _ = seeded_user
    product_id = _create_product(client, str(own_org.id), token)
    imported = client.post(
        f"/v1/organizations/{own_org.id}/products/{product_id}/unit-imports",
        content="serial\nQR-001\nQR-002\n",
        headers={
            **_auth(token),
            "Content-Type": "text/csv",
            "Idempotency-Key": "label-source",
        },
    )
    assert imported.status_code == 200
    batch_id = imported.json()["batch_id"]

    labels = client.get(
        f"/v1/organizations/{own_org.id}/serialization-batches/{batch_id}/labels",
        headers=_auth(token),
    )

    assert labels.status_code == 200
    assert "data:image/svg+xml" in labels.text
    assert "QR-001" in labels.text
    assert "QR-002" in labels.text
    assert "/verify/" in labels.text
    assert "@page" in labels.text
