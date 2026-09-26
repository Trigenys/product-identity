from datetime import date, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.auth import Organization, User
from app.models.identity import Unit, UnitStatus
from app.models.warranty import ProductRegistration


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _issue_unit(
    client: TestClient,
    organization_id: str,
    token: str,
    *,
    name: str,
    sku: str,
    prefix: str,
    batch_key: str,
) -> dict[str, str]:
    product = client.post(
        f"/v1/organizations/{organization_id}/products",
        json={"name": name, "sku": sku},
        headers=_auth(token),
    )
    assert product.status_code == 201

    batch = client.post(
        f"/v1/organizations/{organization_id}/products/{product.json()['id']}/serialization-batches",
        json={"quantity": 1, "prefix": prefix},
        headers={
            **_auth(token),
            "Idempotency-Key": batch_key,
        },
    )
    assert batch.status_code == 201

    issued = batch.json()["units"][0]
    return {
        **issued,
        "product_id": product.json()["id"],
    }


def _register(
    client: TestClient,
    organization_id: str,
    product_id: str,
    verification_token: str,
    token: str,
    *,
    key: str,
) -> str:
    policy = client.put(
        f"/v1/organizations/{organization_id}/products/{product_id}/warranty-policy",
        json={
            "duration_months": 12,
            "start_rule": "purchase_date_or_registration",
        },
        headers=_auth(token),
    )
    assert policy.status_code == 200

    registered = client.post(
        f"/v1/public/register/{verification_token}",
        json={
            "customer_name": "Registry Customer",
            "customer_email": "registry@example.com",
            "purchase_date": date.today().isoformat(),
        },
        headers={"Idempotency-Key": key},
    )
    assert registered.status_code == 201
    return registered.json()["registration_id"]


def test_registry_empty_state_is_explicit(
    client: TestClient,
    seeded_user: tuple[User, Organization, Organization],
    token: str,
) -> None:
    _, own_org, _ = seeded_user

    response = client.get(
        f"/v1/organizations/{own_org.id}/registry/units",
        headers=_auth(token),
    )

    assert response.status_code == 200
    assert response.json() == {
        "summary": {
            "total_units": 0,
            "active_units": 0,
            "revoked_units": 0,
            "registered_units": 0,
            "unregistered_units": 0,
            "open_authenticity_signals": 0,
        },
        "total": 0,
        "limit": 50,
        "offset": 0,
        "units": [],
    }


def test_registry_search_and_filters_are_tenant_scoped(
    client: TestClient,
    session: Session,
    seeded_user: tuple[User, Organization, Organization],
    token: str,
) -> None:
    _, own_org, other_org = seeded_user

    headphones = _issue_unit(
        client,
        str(own_org.id),
        token,
        name="Reference Headphones",
        sku="AUDIO-100",
        prefix="AUDIO",
        batch_key="registry-audio",
    )
    camera = _issue_unit(
        client,
        str(own_org.id),
        token,
        name="Pocket Camera",
        sku="CAM-200",
        prefix="CAM",
        batch_key="registry-camera",
    )
    registration_id = _register(
        client,
        str(own_org.id),
        headphones["product_id"],
        headphones["verification_token"],
        token,
        key="registry-registration",
    )

    camera_unit = session.get(Unit, camera["id"])
    assert camera_unit is not None
    camera_unit.status = UnitStatus.REVOKED
    session.commit()

    by_sku = client.get(
        f"/v1/organizations/{own_org.id}/registry/units?search=AUDIO-100",
        headers=_auth(token),
    )
    assert by_sku.status_code == 200
    assert by_sku.json()["total"] == 1
    assert by_sku.json()["units"][0]["serial"] == headphones["serial"]
    assert by_sku.json()["units"][0]["registered"] is True
    assert by_sku.json()["units"][0]["warranty_state"] == "active"

    revoked = client.get(
        f"/v1/organizations/{own_org.id}/registry/units?unit_status=revoked",
        headers=_auth(token),
    )
    assert revoked.status_code == 200
    assert revoked.json()["total"] == 1
    assert revoked.json()["units"][0]["serial"] == camera["serial"]

    registered = client.get(
        f"/v1/organizations/{own_org.id}/registry/units?registration=registered&warranty=active",
        headers=_auth(token),
    )
    assert registered.status_code == 200
    assert registered.json()["total"] == 1
    assert registered.json()["units"][0]["id"] == headphones["id"]

    summary = registered.json()["summary"]
    assert summary["total_units"] == 2
    assert summary["active_units"] == 1
    assert summary["revoked_units"] == 1
    assert summary["registered_units"] == 1
    assert summary["unregistered_units"] == 1

    cross_tenant = client.get(
        f"/v1/organizations/{other_org.id}/registry/units",
        headers=_auth(token),
    )
    assert cross_tenant.status_code == 403

    registration = session.get(ProductRegistration, registration_id)
    assert registration is not None


def test_registry_warranty_filter_is_applied_before_pagination(
    client: TestClient,
    session: Session,
    seeded_user: tuple[User, Organization, Organization],
    token: str,
) -> None:
    _, own_org, _ = seeded_user

    active = _issue_unit(
        client,
        str(own_org.id),
        token,
        name="Active Device",
        sku="ACTIVE-1",
        prefix="ACT",
        batch_key="registry-active",
    )
    expired = _issue_unit(
        client,
        str(own_org.id),
        token,
        name="Expired Device",
        sku="EXPIRED-1",
        prefix="EXP",
        batch_key="registry-expired",
    )

    active_registration = _register(
        client,
        str(own_org.id),
        active["product_id"],
        active["verification_token"],
        token,
        key="active-registration",
    )
    expired_registration = _register(
        client,
        str(own_org.id),
        expired["product_id"],
        expired["verification_token"],
        token,
        key="expired-registration",
    )

    expired_row = session.get(ProductRegistration, expired_registration)
    assert expired_row is not None
    expired_row.warranty_started_on = date.today() - timedelta(days=400)
    expired_row.warranty_expires_on = date.today() - timedelta(days=35)
    session.commit()

    active_response = client.get(
        f"/v1/organizations/{own_org.id}/registry/units?warranty=active&limit=1",
        headers=_auth(token),
    )
    expired_response = client.get(
        f"/v1/organizations/{own_org.id}/registry/units?warranty=expired&limit=1",
        headers=_auth(token),
    )

    assert active_response.status_code == 200
    assert active_response.json()["total"] == 1
    assert active_response.json()["units"][0]["id"] == active["id"]
    assert expired_response.status_code == 200
    assert expired_response.json()["total"] == 1
    assert expired_response.json()["units"][0]["id"] == expired["id"]

    assert session.get(ProductRegistration, active_registration) is not None


def test_unit_detail_timeline_separates_facts_from_derived_signals(
    client: TestClient,
    seeded_user: tuple[User, Organization, Organization],
    token: str,
) -> None:
    _, own_org, _ = seeded_user

    issued = _issue_unit(
        client,
        str(own_org.id),
        token,
        name="Timeline Device",
        sku="TIME-1",
        prefix="TIM",
        batch_key="registry-timeline",
    )
    _register(
        client,
        str(own_org.id),
        issued["product_id"],
        issued["verification_token"],
        token,
        key="timeline-registration",
    )

    for _ in range(6):
        scan = client.get(f"/v1/public/verify/{issued['verification_token']}")
        assert scan.status_code == 200

    detail = client.get(
        f"/v1/organizations/{own_org.id}/registry/units/{issued['id']}",
        headers=_auth(token),
    )

    assert detail.status_code == 200
    body = detail.json()
    assert body["serial"] == issued["serial"]
    assert body["registration"]["customer_email"] == "registry@example.com"
    assert body["verification_count"] == 6
    assert body["open_signal_count"] == 1

    facts = [item for item in body["timeline"] if item["kind"] == "fact"]
    derived = [item for item in body["timeline"] if item["kind"] == "derived"]

    assert any(item["source"] == "identity" for item in facts)
    assert any(item["source"] == "registration" for item in facts)
    assert sum(item["source"] == "verification" for item in facts) == 6
    assert len(derived) == 1
    assert derived[0]["source"] == "authenticity"
    assert "not proof of counterfeiting" in derived[0]["description"].lower()


def test_registry_detail_does_not_cross_tenant_boundary(
    client: TestClient,
    seeded_user: tuple[User, Organization, Organization],
    token: str,
) -> None:
    _, own_org, other_org = seeded_user
    issued = _issue_unit(
        client,
        str(own_org.id),
        token,
        name="Private Unit",
        sku="PRIVATE-1",
        prefix="PVT",
        batch_key="registry-private",
    )

    response = client.get(
        f"/v1/organizations/{other_org.id}/registry/units/{issued['id']}",
        headers=_auth(token),
    )
    assert response.status_code == 403
