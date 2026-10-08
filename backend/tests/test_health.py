import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.db import session as db_session


def test_health_is_ok_in_normal_test_runtime(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["database_configured"] is True


def test_ready_proves_database_connectivity(client: TestClient) -> None:
    response = client.get("/ready")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["database_configured"] is True


def test_production_worker_without_postgres_is_explicitly_degraded(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(db_session.settings, "runtime", "cloudflare-worker")
    monkeypatch.setattr(db_session.settings, "environment", "production")
    monkeypatch.setattr(
        db_session.settings,
        "database_url",
        "sqlite:///./product_identity.db",
    )

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "degraded",
        "runtime": "cloudflare-worker",
        "database_configured": False,
    }


def test_production_worker_without_postgres_rejects_database_sessions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(db_session.settings, "runtime", "cloudflare-worker")
    monkeypatch.setattr(db_session.settings, "environment", "production")
    monkeypatch.setattr(
        db_session.settings,
        "database_url",
        "sqlite:///./product_identity.db",
    )

    dependency = db_session.get_db_session()

    with pytest.raises(HTTPException) as exc:
        next(dependency)

    assert exc.value.status_code == 503
    assert exc.value.detail == "Production database is not configured"
