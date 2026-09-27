from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.auth import Organization, User


def test_health_is_public(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "runtime": "server",
        "database_configured": True,
    }


def test_me_requires_bearer_token(client: TestClient) -> None:
    response = client.get("/v1/me")
    assert response.status_code == 401


def test_unknown_identity_is_not_auto_provisioned(client: TestClient, token: str) -> None:
    response = client.get("/v1/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 403


def test_me_returns_only_user_memberships(
    client: TestClient,
    session: Session,
    seeded_user: tuple[User, Organization, Organization],
    token: str,
) -> None:
    user, own_org, _ = seeded_user
    assert user.external_subject == "oidc|user-1"

    response = client.get("/v1/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    body = response.json()
    assert body["email"] == "owner@example.com"
    assert body["memberships"] == [
        {
            "organization_id": str(own_org.id),
            "organization_name": "Alpha Brand",
            "organization_slug": "alpha",
            "role": "owner",
        }
    ]
