import uuid
from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.auth import Organization, User
from app.models.warranty import ProductRegistration, RegistrationAudit, WarrantyPolicy, WarrantyStartRule
from app.services.warranty import calculate_warranty_dates


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _create_product_and_unit(
    client: TestClient,
    organization_id: str,
    token: str,
    *,
    sku: str = "WARRANTY-1",
    batch_key: str = "warranty-fixture",
) -> tuple[str, dict[str, str]]:
    product = client.post(
        f"/v1/organizations/{organization_id}/products",
        json={"name": "Warranty Device", "sku": sku},
        headers=_auth(token),
    )
    assert product.status_code == 201
    product_id = product.json()["id"]

    batch = client.post(
        f"/v1/organizations/{organization_id}/products/{product_id}/serialization-batches",
        json={"quantity": 1, "prefix": "WAR"},
        headers={
            **_auth(token),
            "Idempotency-Key": batch_key,
        },
    )
    assert batch.status_code == 201
    return product_id, batch.json()["units"][0]


def _set_policy(
    client: TestClient,
    organization_id: str,
    product_id: str,
    token: str,
    *,
    months: int = 12,
    start_rule: str = "purchase_date_or_registration",
) -> dict[str, object]:
    response = client.put(
        f"/v1/organizations/{organization_id}/products/{product_id}/warranty-policy",
        json={"duration_months": months, "start_rule": start_rule},
        headers=_auth(token),
    )
    assert response.status_code == 200
    return response.json()


def test_warranty_month_calculation_is_deterministic_at_month_end() -> None:
    policy = WarrantyPolicy(
        duration_months=1,
        start_rule=WarrantyStartRule.PURCHASE_DATE_OR_REGISTRATION,
    )

    started, expires = calculate_warranty_dates(
        policy=policy,
        registered_on=date(2026, 1, 31),
        purchase_date=date(2026, 1, 31),
    )

    assert started == date(2026, 1, 31)
    assert expires == date(2026, 2, 28)


def test_public_registration_is_idempotent_and_unit_cannot_be_claimed_twice(
    client: TestClient,
    seeded_user: tuple[User, Organization, Organization],
    token: str,
) -> None:
    _, own_org, _ = seeded_user
    product_id, issued = _create_product_and_unit(client, str(own_org.id), token)
    _set_policy(client, str(own_org.id), product_id, token)

    endpoint = f"/v1/public/register/{issued['verification_token']}"
    payload = {
        "customer_name": "  Jane   Buyer ",
        "customer_email": "JANE@example.com",
        "purchase_date": "2026-09-01",
    }
    headers = {"Idempotency-Key": "customer-registration-1"}

    first = client.post(endpoint, json=payload, headers=headers)
    replay = client.post(endpoint, json=payload, headers=headers)

    assert first.status_code == 201
    assert replay.status_code == 201
    assert first.json()["registration_id"] == replay.json()["registration_id"]
    assert first.json()["replayed"] is False
    assert replay.json()["replayed"] is True
    assert first.json()["warranty_started_on"] == "2026-09-01"
    assert first.json()["warranty_expires_on"] == "2027-09-01"

    second_claim = client.post(
        endpoint,
        json={**payload, "customer_email": "someone-else@example.com"},
        headers={"Idempotency-Key": "another-registration"},
    )
    assert second_claim.status_code == 409


def test_registration_requires_brand_warranty_policy(
    client: TestClient,
    seeded_user: tuple[User, Organization, Organization],
    token: str,
) -> None:
    _, own_org, _ = seeded_user
    _, issued = _create_product_and_unit(
        client,
        str(own_org.id),
        token,
        sku="NO-POLICY",
        batch_key="no-policy-batch",
    )

    response = client.post(
        f"/v1/public/register/{issued['verification_token']}",
        json={"customer_name": "Buyer", "customer_email": "buyer@example.com"},
        headers={"Idempotency-Key": "missing-policy"},
    )

    assert response.status_code == 409
    assert "warranty policy" in response.json()["detail"].lower()


def test_public_verification_shows_warranty_without_registrant_pii(
    client: TestClient,
    seeded_user: tuple[User, Organization, Organization],
    token: str,
) -> None:
    _, own_org, _ = seeded_user
    product_id, issued = _create_product_and_unit(
        client,
        str(own_org.id),
        token,
        sku="PUBLIC-PII",
        batch_key="public-pii-batch",
    )
    _set_policy(client, str(own_org.id), product_id, token)

    registered = client.post(
        f"/v1/public/register/{issued['verification_token']}",
        json={
            "customer_name": "Private Customer",
            "customer_email": "private@example.com",
            "purchase_date": "2026-09-01",
        },
        headers={"Idempotency-Key": "private-registration"},
    )
    assert registered.status_code == 201

    response = client.get(f"/v1/public/verify/{issued['verification_token']}")
    assert response.status_code == 200
    body = response.json()

    assert body["warranty_state"] == "active"
    assert body["warranty_started_on"] == "2026-09-01"
    assert body["warranty_expires_on"] == "2027-09-01"
    serialized = response.text.lower()
    assert "private customer" not in serialized
    assert "private@example.com" not in serialized
    assert "customer_name" not in body
    assert "customer_email" not in body


def test_merchant_visibility_is_tenant_scoped(
    client: TestClient,
    seeded_user: tuple[User, Organization, Organization],
    token: str,
) -> None:
    _, own_org, other_org = seeded_user
    product_id, issued = _create_product_and_unit(
        client,
        str(own_org.id),
        token,
        sku="TENANT-REG",
        batch_key="tenant-registration-batch",
    )
    _set_policy(client, str(own_org.id), product_id, token)

    assert client.post(
        f"/v1/public/register/{issued['verification_token']}",
        json={"customer_name": "Visible Owner", "customer_email": "visible@example.com"},
        headers={"Idempotency-Key": "tenant-registration"},
    ).status_code == 201

    own = client.get(
        f"/v1/organizations/{own_org.id}/registrations",
        headers=_auth(token),
    )
    other = client.get(
        f"/v1/organizations/{other_org.id}/registrations",
        headers=_auth(token),
    )

    assert own.status_code == 200
    assert own.json()[0]["customer_email"] == "visible@example.com"
    assert other.status_code == 403


def test_manual_correction_uses_policy_snapshot_and_writes_audit(
    client: TestClient,
    session: Session,
    seeded_user: tuple[User, Organization, Organization],
    token: str,
) -> None:
    _, own_org, _ = seeded_user
    product_id, issued = _create_product_and_unit(
        client,
        str(own_org.id),
        token,
        sku="CORRECT-1",
        batch_key="correction-batch",
    )
    _set_policy(client, str(own_org.id), product_id, token, months=12)

    registered = client.post(
        f"/v1/public/register/{issued['verification_token']}",
        json={
            "customer_name": "Original Name",
            "customer_email": "original@example.com",
            "purchase_date": "2026-01-31",
        },
        headers={"Idempotency-Key": "correction-registration"},
    )
    assert registered.status_code == 201
    registration_id = registered.json()["registration_id"]
    assert registered.json()["warranty_expires_on"] == "2027-01-31"

    # Future policy changes must not rewrite already-issued warranty terms.
    _set_policy(client, str(own_org.id), product_id, token, months=24)

    corrected = client.patch(
        f"/v1/organizations/{own_org.id}/registrations/{registration_id}",
        json={
            "customer_name": "Corrected Name",
            "purchase_date": "2026-02-28",
        },
        headers=_auth(token),
    )

    assert corrected.status_code == 200
    body = corrected.json()
    assert body["customer_name"] == "Corrected Name"
    assert body["warranty_started_on"] == "2026-02-28"
    assert body["warranty_expires_on"] == "2027-02-28"

    registration = session.get(ProductRegistration, uuid.UUID(registration_id))
    assert registration is not None
    assert registration.policy_duration_months == 12

    audit = client.get(
        f"/v1/organizations/{own_org.id}/registrations/{registration_id}/audit",
        headers=_auth(token),
    )
    assert audit.status_code == 200
    assert [item["action"] for item in audit.json()] == ["registered", "corrected"]
    assert audit.json()[1]["before"]["customer_name"] == "Original Name"
    assert audit.json()[1]["after"]["customer_name"] == "Corrected Name"

    rows = session.scalars(
        select(RegistrationAudit).where(RegistrationAudit.registration_id == registration.id)
    ).all()
    assert len(rows) == 2


def test_future_purchase_date_is_rejected(
    client: TestClient,
    seeded_user: tuple[User, Organization, Organization],
    token: str,
) -> None:
    _, own_org, _ = seeded_user
    product_id, issued = _create_product_and_unit(
        client,
        str(own_org.id),
        token,
        sku="FUTURE-DATE",
        batch_key="future-date-batch",
    )
    _set_policy(client, str(own_org.id), product_id, token)

    response = client.post(
        f"/v1/public/register/{issued['verification_token']}",
        json={
            "customer_name": "Time Traveller",
            "customer_email": "time@example.com",
            "purchase_date": "2099-01-01",
        },
        headers={"Idempotency-Key": "future-date"},
    )

    assert response.status_code == 422
    assert "future" in response.json()["detail"].lower()
