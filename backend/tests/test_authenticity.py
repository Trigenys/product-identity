import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.main import app
from app.models.auth import Organization, User
from app.models.authenticity import (
    AuthenticitySignal,
    AuthenticitySignalState,
    AuthenticitySignalType,
)
from app.models.identity import VerificationEvent
from app.services.rate_limit import InMemoryFixedWindowRateLimiter, RateLimitExceeded


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _issue_unit(
    client: TestClient,
    organization_id: str,
    token: str,
    *,
    sku: str = "SIGNAL-1",
    batch_key: str = "signal-batch",
) -> dict[str, str]:
    product = client.post(
        f"/v1/organizations/{organization_id}/products",
        json={"name": "Signal Device", "sku": sku},
        headers=_auth(token),
    )
    assert product.status_code == 201

    batch = client.post(
        f"/v1/organizations/{organization_id}/products/{product.json()['id']}/serialization-batches",
        json={"quantity": 1, "prefix": "SIG"},
        headers={
            **_auth(token),
            "Idempotency-Key": batch_key,
        },
    )
    assert batch.status_code == 201
    return batch.json()["units"][0]


def test_repeat_scan_burst_creates_one_explainable_signal_and_updates_it(
    client: TestClient,
    session: Session,
    seeded_user: tuple[User, Organization, Organization],
    token: str,
) -> None:
    _, own_org, _ = seeded_user
    issued = _issue_unit(client, str(own_org.id), token)

    responses = [
        client.get(
            f"/v1/public/verify/{issued['verification_token']}",
            headers={"Sec-CH-UA-Mobile": "?1"},
        )
        for _ in range(6)
    ]

    assert all(response.status_code == 200 for response in responses)
    assert all(response.json()["state"] == "valid" for response in responses)
    forbidden_public_fields = {
        "authenticity_signal",
        "authenticity_signals",
        "signal_type",
        "observed_value",
        "threshold_value",
        "review_note",
    }
    assert all(
        forbidden_public_fields.isdisjoint(response.json().keys())
        for response in responses
    )

    signals = session.scalars(select(AuthenticitySignal)).all()
    assert len(signals) == 1
    signal = signals[0]
    assert signal.signal_type == AuthenticitySignalType.REPEAT_SCAN_BURST
    assert signal.state == AuthenticitySignalState.OPEN
    assert signal.observed_value == 6
    assert signal.threshold_value == 6
    assert "10 minutes" in signal.explanation
    assert "not proof of counterfeiting" in signal.explanation.lower()

    seventh = client.get(
        f"/v1/public/verify/{issued['verification_token']}",
        headers={"Sec-CH-UA-Mobile": "?1"},
    )
    assert seventh.status_code == 200

    session.expire_all()
    signals = session.scalars(select(AuthenticitySignal)).all()
    assert len(signals) == 1
    assert signals[0].observed_value == 7


def test_device_class_is_coarse_and_raw_user_agent_is_not_persisted(
    client: TestClient,
    session: Session,
    seeded_user: tuple[User, Organization, Organization],
    token: str,
) -> None:
    _, own_org, _ = seeded_user
    issued = _issue_unit(
        client,
        str(own_org.id),
        token,
        sku="DEVICE-CTX",
        batch_key="device-context-batch",
    )

    response = client.get(
        f"/v1/public/verify/{issued['verification_token']}",
        headers={
            "Sec-CH-UA-Mobile": "?1",
            "User-Agent": "Highly-Specific-Test-Agent/99.1",
            "CF-IPCountry": "CM",
        },
    )
    assert response.status_code == 200

    event = session.scalar(select(VerificationEvent))
    assert event is not None
    assert event.device_class == "mobile"
    assert event.country_code is None
    assert not hasattr(event, "user_agent")
    assert not hasattr(event, "ip_address")


def test_country_context_requires_explicit_trusted_edge_configuration(
    client: TestClient,
    session: Session,
    seeded_user: tuple[User, Organization, Organization],
    token: str,
) -> None:
    _, own_org, _ = seeded_user
    issued = _issue_unit(
        client,
        str(own_org.id),
        token,
        sku="COUNTRY-CTX",
        batch_key="country-context-batch",
    )

    app.dependency_overrides[get_settings] = lambda: Settings(
        verification_trust_edge_country=True,
        verification_country_threshold=2,
        verification_country_window_hours=24,
        verification_repeat_scan_threshold=99,
    )
    try:
        first = client.get(
            f"/v1/public/verify/{issued['verification_token']}",
            headers={"CF-IPCountry": "CM", "Sec-CH-UA-Mobile": "?1"},
        )
        second = client.get(
            f"/v1/public/verify/{issued['verification_token']}",
            headers={"CF-IPCountry": "FR", "Sec-CH-UA-Mobile": "?0"},
        )
    finally:
        app.dependency_overrides.pop(get_settings, None)

    assert first.status_code == 200
    assert second.status_code == 200

    events = session.scalars(
        select(VerificationEvent).order_by(VerificationEvent.created_at, VerificationEvent.id)
    ).all()
    assert {event.country_code for event in events} == {"CM", "FR"}
    assert {event.device_class for event in events} == {"mobile", "desktop"}

    signal = session.scalar(
        select(AuthenticitySignal).where(
            AuthenticitySignal.signal_type == AuthenticitySignalType.MULTI_COUNTRY_ACTIVITY
        )
    )
    assert signal is not None
    assert signal.observed_value == 2
    assert signal.threshold_value == 2
    assert "VPNs" in signal.explanation
    assert "not proof of counterfeiting" in signal.explanation.lower()


def test_unknown_code_flood_does_not_create_unit_authenticity_signal(
    client: TestClient,
    session: Session,
) -> None:
    for _ in range(8):
        response = client.get("/v1/public/verify/" + ("z" * 43))
        assert response.status_code == 200
        assert response.json()["state"] == "unknown"

    assert session.scalars(select(AuthenticitySignal)).all() == []


def test_fixed_window_rate_limiter_blocks_scan_flood() -> None:
    limiter = InMemoryFixedWindowRateLimiter(limit=3, window_seconds=60)

    limiter.check("same-client")
    limiter.check("same-client")
    limiter.check("same-client")

    with pytest.raises(RateLimitExceeded):
        limiter.check("same-client")


def test_merchant_can_review_signal_and_cross_tenant_access_is_denied(
    client: TestClient,
    seeded_user: tuple[User, Organization, Organization],
    token: str,
) -> None:
    _, own_org, other_org = seeded_user
    issued = _issue_unit(
        client,
        str(own_org.id),
        token,
        sku="REVIEW-SIGNAL",
        batch_key="review-signal-batch",
    )
    for _ in range(6):
        assert client.get(f"/v1/public/verify/{issued['verification_token']}").status_code == 200

    listed = client.get(
        f"/v1/organizations/{own_org.id}/authenticity-signals",
        headers=_auth(token),
    )
    assert listed.status_code == 200
    assert len(listed.json()) == 1
    item = listed.json()[0]
    assert item["serial"] == issued["serial"]
    assert item["state"] == "open"
    assert item["observed_value"] == 6

    reviewed = client.patch(
        f"/v1/organizations/{own_org.id}/authenticity-signals/{item['id']}",
        json={
            "state": "dismissed",
            "note": "Known in-store demo unit; repeated scans are expected.",
        },
        headers=_auth(token),
    )
    assert reviewed.status_code == 200
    assert reviewed.json()["state"] == "dismissed"
    assert reviewed.json()["reviewed_by_user_id"] is not None
    assert "demo unit" in reviewed.json()["review_note"]

    cross_tenant = client.get(
        f"/v1/organizations/{other_org.id}/authenticity-signals",
        headers=_auth(token),
    )
    assert cross_tenant.status_code == 403
