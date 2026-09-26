from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.routes.public_verification import get_verification_rate_limiter
from app.main import app
from app.models.auth import Organization, User
from app.models.identity import Unit, UnitStatus, VerificationEvent, VerificationOutcome
from app.services.rate_limit import RateLimitExceeded


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _issue_unit(
    client: TestClient,
    organization_id: str,
    token: str,
) -> dict[str, str]:
    product = client.post(
        f"/v1/organizations/{organization_id}/products",
        json={"name": "Reference Headphones", "sku": "REF-100"},
        headers=_auth(token),
    )
    assert product.status_code == 201

    batch = client.post(
        f"/v1/organizations/{organization_id}/products/{product.json()['id']}/serialization-batches",
        json={"quantity": 1, "prefix": "REF"},
        headers={
            **_auth(token),
            "Idempotency-Key": "public-verification-fixture",
        },
    )
    assert batch.status_code == 201
    return batch.json()["units"][0]


def test_valid_identity_is_public_and_contains_no_private_fields(
    client: TestClient,
    session: Session,
    seeded_user: tuple[User, Organization, Organization],
    token: str,
) -> None:
    _, own_org, _ = seeded_user
    issued = _issue_unit(client, str(own_org.id), token)

    response = client.get(f"/v1/public/verify/{issued['verification_token']}")

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "state": "valid",
        "brand_name": "Alpha Brand",
        "product_name": "Reference Headphones",
        "sku": "REF-100",
        "serial": issued["serial"],
        "warranty_state": "unregistered",
        "message": "This digital product identity is active.",
    }

    forbidden_keys = {
        "unit_id",
        "organization_id",
        "owner",
        "owner_email",
        "customer",
        "email",
        "address",
        "order_id",
        "proof_url",
        "verification_token",
    }
    assert forbidden_keys.isdisjoint(body.keys())

    events = session.scalars(select(VerificationEvent)).all()
    assert len(events) == 1
    assert events[0].outcome == VerificationOutcome.VALID
    assert events[0].unit_id is not None
    assert not hasattr(events[0], "ip_address")
    assert not hasattr(events[0], "user_agent")


def test_unknown_token_is_distinct_and_leaks_no_product_metadata(
    client: TestClient,
    session: Session,
) -> None:
    unknown_token = "u" * 43
    response = client.get(f"/v1/public/verify/{unknown_token}")

    assert response.status_code == 200
    assert response.json() == {
        "state": "unknown",
        "message": "This verification code is not recognized.",
    }

    event = session.scalar(select(VerificationEvent))
    assert event is not None
    assert event.outcome == VerificationOutcome.UNKNOWN
    assert event.unit_id is None
    assert event.token_digest != unknown_token


def test_revoked_identity_is_distinct(
    client: TestClient,
    session: Session,
    seeded_user: tuple[User, Organization, Organization],
    token: str,
) -> None:
    _, own_org, _ = seeded_user
    issued = _issue_unit(client, str(own_org.id), token)

    unit = session.scalar(select(Unit).where(Unit.serial == issued["serial"]))
    assert unit is not None
    unit.status = UnitStatus.REVOKED
    session.commit()

    response = client.get(f"/v1/public/verify/{issued['verification_token']}")

    assert response.status_code == 200
    assert response.json()["state"] == "revoked"
    assert response.json()["serial"] == issued["serial"]


class AlwaysRejectLimiter:
    def check(self, _key: str) -> None:
        raise RateLimitExceeded("blocked")


def test_public_verification_boundary_can_enforce_rate_limit(client: TestClient) -> None:
    app.dependency_overrides[get_verification_rate_limiter] = lambda: AlwaysRejectLimiter()
    try:
        response = client.get("/v1/public/verify/" + ("r" * 43))
        assert response.status_code == 429
        assert "Too many verification attempts" in response.json()["detail"]
    finally:
        app.dependency_overrides.pop(get_verification_rate_limiter, None)


def test_malformed_short_token_is_rejected_before_lookup(
    client: TestClient,
    session: Session,
) -> None:
    response = client.get("/v1/public/verify/short")

    assert response.status_code == 422
    assert session.scalar(select(func.count(VerificationEvent.id))) == 0
