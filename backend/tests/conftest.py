from collections.abc import Generator
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import get_jwt_verifier
from app.api.proof_deps import get_object_storage, get_proof_grant_factory
from app.api.routes.identity import get_token_factory
from app.api.routes.public_registration import get_registration_rate_limiter
from app.api.shopify_deps import get_shopify_admin_client, get_shopify_token_cipher
from app.core.config import Settings, get_settings
from app.core.security import JWTVerifier
from app.db.base import Base
from app.db.session import get_db_session
from app.main import app
from app.models.auth import Membership, MembershipRole, Organization, User
from app.services.proof import ProofUploadGrantFactory
from app.services.rate_limit import InMemoryFixedWindowRateLimiter
from app.services.serialization import VerificationTokenFactory
from app.services.storage import ObjectStorage
from app.integrations.shopify.client import ShopifyTokenResponse
from app.integrations.shopify.crypto import TokenCipher

TEST_KEY = "test-secret-key-at-least-32-bytes-long"
TEST_ISSUER = "https://issuer.test/"
TEST_AUDIENCE = "product-identity-api"
TEST_VERIFICATION_SECRET = "verification-test-secret-at-least-32-bytes-long"
TEST_PROOF_SECRET = "proof-upload-test-secret-at-least-32-bytes-long"
TEST_SHOPIFY_CLIENT_ID = "shopify-test-client-id"
TEST_SHOPIFY_CLIENT_SECRET = "shopify-test-client-secret"
TEST_SHOPIFY_ENCRYPTION_KEY = Fernet.generate_key().decode("ascii")

engine = create_engine(
    "sqlite+pysqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSession = sessionmaker(bind=engine, expire_on_commit=False)


class InMemoryObjectStorage(ObjectStorage):
    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}
        self.deleted: list[str] = []

    def reset(self) -> None:
        self.objects.clear()
        self.deleted.clear()

    def put_private(self, *, key: str, body: bytes, content_type: str) -> None:
        self.objects[key] = (body, content_type)

    def create_download_url(self, *, key: str, expires_seconds: int) -> str:
        if key not in self.objects:
            raise RuntimeError("Object does not exist")
        return f"https://storage.test/private/{key}?expires={expires_seconds}"

    def delete(self, *, key: str) -> None:
        self.objects.pop(key, None)
        self.deleted.append(key)


TEST_STORAGE = InMemoryObjectStorage()


class FakeShopifyAdminClient:
    def __init__(self) -> None:
        self.exchange_calls: list[tuple[str, str]] = []
        self.refresh_calls: list[tuple[str, str]] = []
        self.graphql_calls: list[dict[str, object]] = []
        self.graphql_responses: list[dict[str, object]] = []
        self.exchange_response = self._token_response("access-initial", "refresh-initial")
        self.refresh_response = self._token_response("access-refreshed", "refresh-refreshed")

    @staticmethod
    def _token_response(access_token: str, refresh_token: str) -> ShopifyTokenResponse:
        now = datetime.now(timezone.utc)
        return ShopifyTokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            scope="read_products,read_orders",
            access_token_expires_at=now + timedelta(hours=1),
            refresh_token_expires_at=now + timedelta(days=90),
        )

    def reset(self) -> None:
        self.exchange_calls.clear()
        self.refresh_calls.clear()
        self.graphql_calls.clear()
        self.graphql_responses.clear()
        self.exchange_response = self._token_response("access-initial", "refresh-initial")
        self.refresh_response = self._token_response("access-refreshed", "refresh-refreshed")

    def exchange_code(self, *, shop: str, code: str) -> ShopifyTokenResponse:
        self.exchange_calls.append((shop, code))
        return self.exchange_response

    def refresh_token(self, *, shop: str, refresh_token: str) -> ShopifyTokenResponse:
        self.refresh_calls.append((shop, refresh_token))
        return self.refresh_response

    def graphql(
        self,
        *,
        shop: str,
        access_token: str,
        query: str,
        variables: dict[str, object],
    ) -> dict[str, object]:
        self.graphql_calls.append(
            {
                "shop": shop,
                "access_token": access_token,
                "query": query,
                "variables": variables,
            }
        )
        if self.graphql_responses:
            return self.graphql_responses.pop(0)
        return {
            "data": {
                "products": {
                    "nodes": [],
                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                }
            }
        }


TEST_SHOPIFY_CLIENT = FakeShopifyAdminClient()



@pytest.fixture(autouse=True)
def reset_database() -> Generator[None, None, None]:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    TEST_STORAGE.reset()
    TEST_SHOPIFY_CLIENT.reset()
    yield


@pytest.fixture
def session() -> Generator[Session, None, None]:
    db = TestingSession()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def storage() -> InMemoryObjectStorage:
    return TEST_STORAGE


@pytest.fixture
def shopify_client() -> FakeShopifyAdminClient:
    return TEST_SHOPIFY_CLIENT


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
def proof_grant_factory() -> ProofUploadGrantFactory:
    return ProofUploadGrantFactory(TEST_PROOF_SECRET)


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

    shopify_settings = Settings(
        shopify_client_id=TEST_SHOPIFY_CLIENT_ID,
        shopify_client_secret=TEST_SHOPIFY_CLIENT_SECRET,
        shopify_token_encryption_key=TEST_SHOPIFY_ENCRYPTION_KEY,
        shopify_oauth_callback_url="https://identity.test/v1/integrations/shopify/oauth/callback",
        shopify_after_install_url="https://identity.test/app",
    )

    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_jwt_verifier] = override_verifier
    app.dependency_overrides[get_token_factory] = lambda: VerificationTokenFactory(TEST_VERIFICATION_SECRET)
    registration_limiter = InMemoryFixedWindowRateLimiter(limit=1000, window_seconds=60)
    app.dependency_overrides[get_proof_grant_factory] = lambda: ProofUploadGrantFactory(TEST_PROOF_SECRET)
    app.dependency_overrides[get_object_storage] = lambda: TEST_STORAGE
    app.dependency_overrides[get_registration_rate_limiter] = lambda: registration_limiter
    app.dependency_overrides[get_settings] = lambda: shopify_settings
    app.dependency_overrides[get_shopify_admin_client] = lambda: TEST_SHOPIFY_CLIENT
    app.dependency_overrides[get_shopify_token_cipher] = lambda: TokenCipher(TEST_SHOPIFY_ENCRYPTION_KEY)
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
