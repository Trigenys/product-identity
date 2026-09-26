from collections.abc import Generator
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import get_jwt_verifier
from app.api.routes.identity import get_token_factory
from app.core.config import Settings
from app.core.security import JWTVerifier
from app.db.base import Base
from app.db.session import get_db_session
from app.main import app
from app.models.auth import Membership, MembershipRole, Organization, User
from app.services.serialization import VerificationTokenFactory

TEST_KEY = "test-secret-key-at-least-32-bytes-long"
TEST_ISSUER = "https://issuer.test/"
TEST_AUDIENCE = "product-identity-api"
TEST_VERIFICATION_SECRET = "verification-test-secret-at-least-32-bytes-long"

engine = create_engine(
    "sqlite+pysqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSession = sessionmaker(bind=engine, expire_on_commit=False)


@pytest.fixture(autouse=True)
def reset_database() -> Generator[None, None, None]:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield


@pytest.fixture
def session() -> Generator[Session, None, None]:
    db = TestingSession()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def seeded_user(session: Session) -> tuple[User, Organization, Organization]:
    user = User(external_subject="oidc|user-1", email="owner@example.com")
    own_org = Organization(name="Alpha Brand", slug="alpha")
    other_org = Organization(name="Beta Brand", slug="beta")
    session.add_all([user, own_org, other_org])
    session.flush()
    session.add(Membership(user_id=user.id, organization_id=own_org.id, role=MembershipRole.OWNER))
    session.commit()
    return user, own_org, other_org


@pytest.fixture
def token() -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": "oidc|user-1",
            "email": "owner@example.com",
            "iss": TEST_ISSUER,
            "aud": TEST_AUDIENCE,
            "iat": now,
            "exp": now + timedelta(minutes=10),
        },
        TEST_KEY,
        algorithm="HS256",
    )


@pytest.fixture
def token_factory() -> VerificationTokenFactory:
    return VerificationTokenFactory(TEST_VERIFICATION_SECRET)


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    def override_session() -> Generator[Session, None, None]:
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    def override_verifier() -> JWTVerifier:
        return JWTVerifier(
            Settings(
                auth_issuer=TEST_ISSUER,
                auth_audience=TEST_AUDIENCE,
                auth_algorithm="HS256",
                auth_jwt_key=TEST_KEY,
            )
        )

    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_jwt_verifier] = override_verifier
    app.dependency_overrides[get_token_factory] = lambda: VerificationTokenFactory(TEST_VERIFICATION_SECRET)
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
