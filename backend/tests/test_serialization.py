from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.auth import Organization, User
from app.models.identity import ImmutableUnitIdentityError, Product, Unit
from app.services.serialization import VerificationTokenFactory, create_serialization_batch


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_serialization_batch_is_idempotent(
    client: TestClient,
    seeded_user: tuple[User, Organization, Organization],
    token: str,
) -> None:
    _, own_org, _ = seeded_user

    product_response = client.post(
        f"/v1/organizations/{own_org.id}/products",
        json={"name": "Studio Headphones", "sku": "HP-001"},
        headers=_headers(token),
    )
    assert product_response.status_code == 201
    product_id = product_response.json()["id"]

    first = client.post(
        f"/v1/organizations/{own_org.id}/products/{product_id}/serialization-batches",
        json={"quantity": 3, "prefix": "AUDIO"},
        headers={**_headers(token), "Idempotency-Key": "launch-batch-001"},
    )
    replay = client.post(
        f"/v1/organizations/{own_org.id}/products/{product_id}/serialization-batches",
        json={"quantity": 3, "prefix": "AUDIO"},
        headers={**_headers(token), "Idempotency-Key": "launch-batch-001"},
    )

    assert first.status_code == 201
    assert replay.status_code == 201
    assert first.json()["replayed"] is False
    assert replay.json()["replayed"] is True
    assert first.json()["id"] == replay.json()["id"]
    assert first.json()["units"] == replay.json()["units"]

    serials = [unit["serial"] for unit in first.json()["units"]]
    tokens = [unit["verification_token"] for unit in first.json()["units"]]
    assert len(serials) == len(set(serials)) == 3
    assert len(tokens) == len(set(tokens)) == 3
    assert all(serial.startswith("AUDIO-") for serial in serials)


def test_idempotency_key_rejects_different_payload(
    client: TestClient,
    seeded_user: tuple[User, Organization, Organization],
    token: str,
) -> None:
    _, own_org, _ = seeded_user
    product = client.post(
        f"/v1/organizations/{own_org.id}/products",
        json={"name": "Tool", "sku": "TOOL-1"},
        headers=_headers(token),
    ).json()

    endpoint = f"/v1/organizations/{own_org.id}/products/{product['id']}/serialization-batches"
    headers = {**_headers(token), "Idempotency-Key": "same-key"}

    assert client.post(endpoint, json={"quantity": 2}, headers=headers).status_code == 201
    conflict = client.post(endpoint, json={"quantity": 3}, headers=headers)
    assert conflict.status_code == 409


def test_cross_tenant_product_creation_is_denied(
    client: TestClient,
    seeded_user: tuple[User, Organization, Organization],
    token: str,
) -> None:
    _, _, other_org = seeded_user

    response = client.post(
        f"/v1/organizations/{other_org.id}/products",
        json={"name": "Should Fail", "sku": "NOPE"},
        headers=_headers(token),
    )

    assert response.status_code == 403


def test_raw_verification_token_is_not_stored(
    session: Session,
    seeded_user: tuple[User, Organization, Organization],
    token_factory: VerificationTokenFactory,
) -> None:
    _, own_org, _ = seeded_user
    product = Product(organization_id=own_org.id, name="Camera", sku="CAM-1")
    session.add(product)
    session.commit()

    result = create_serialization_batch(
        session,
        organization_id=own_org.id,
        product_id=product.id,
        quantity=1,
        idempotency_key="batch-camera",
        token_factory=token_factory,
    )
    session.commit()

    issued = result.issued_units[0]
    assert issued.unit.verification_token_digest == token_factory.digest(issued.verification_token)
    assert issued.verification_token != issued.unit.verification_token_digest


class SequencePolicy:
    def __init__(self, values: list[str]) -> None:
        self._values: Iterator[str] = iter(values)

    def generate(self) -> str:
        return next(self._values)


def test_existing_serial_collision_is_retried(
    session: Session,
    seeded_user: tuple[User, Organization, Organization],
    token_factory: VerificationTokenFactory,
) -> None:
    _, own_org, _ = seeded_user
    product = Product(organization_id=own_org.id, name="Amp", sku="AMP-1")
    session.add(product)
    session.commit()

    first = create_serialization_batch(
        session,
        organization_id=own_org.id,
        product_id=product.id,
        quantity=1,
        idempotency_key="first",
        token_factory=token_factory,
        serial_policy=SequencePolicy(["DUPLICATE"]),
    )
    session.commit()
    assert first.issued_units[0].unit.serial == "DUPLICATE"

    second = create_serialization_batch(
        session,
        organization_id=own_org.id,
        product_id=product.id,
        quantity=1,
        idempotency_key="second",
        token_factory=token_factory,
        serial_policy=SequencePolicy(["DUPLICATE", "RECOVERED"]),
    )
    session.commit()

    assert second.issued_units[0].unit.serial == "RECOVERED"


def test_unit_identity_cannot_be_mutated_after_issuance(
    session: Session,
    seeded_user: tuple[User, Organization, Organization],
    token_factory: VerificationTokenFactory,
) -> None:
    _, own_org, _ = seeded_user
    product = Product(organization_id=own_org.id, name="Keyboard", sku="KB-1")
    session.add(product)
    session.commit()

    result = create_serialization_batch(
        session,
        organization_id=own_org.id,
        product_id=product.id,
        quantity=1,
        idempotency_key="immutable",
        token_factory=token_factory,
    )
    session.commit()

    unit: Unit = result.issued_units[0].unit
    original_serial = unit.serial
    unit.serial = "CHANGED"

    with pytest.raises(ImmutableUnitIdentityError):
        session.commit()
    session.rollback()

    assert session.get(Unit, unit.id).serial == original_serial
