import base64
import hashlib
import hmac
import json
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.integrations.shopify.crypto import TokenCipher
from app.models.auth import Organization, User
from app.models.identity import Product
from app.models.shopify import (
    ShopifyInstallation,
    ShopifyInstallationStatus,
    ShopifyOrderLineMap,
    ShopifyOrderMap,
    ShopifyProductMap,
    ShopifyWebhookDelivery,
)
from conftest import (
    TEST_SHOPIFY_CLIENT_SECRET,
    TEST_SHOPIFY_ENCRYPTION_KEY,
    FakeShopifyAdminClient,
)

SHOP = "product-identity-dev.myshopify.com"


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _callback_hmac(params: dict[str, str]) -> str:
    message = "&".join(
        f"{key}={value}"
        for key, value in sorted(params.items())
        if key != "hmac"
    )
    return hmac.new(
        TEST_SHOPIFY_CLIENT_SECRET.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _webhook_hmac(body: bytes) -> str:
    return base64.b64encode(
        hmac.new(
            TEST_SHOPIFY_CLIENT_SECRET.encode("utf-8"),
            body,
            hashlib.sha256,
        ).digest()
    ).decode("ascii")


def _webhook_headers(topic: str, webhook_id: str, body: bytes) -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "X-Shopify-Hmac-Sha256": _webhook_hmac(body),
        "X-Shopify-Topic": topic,
        "X-Shopify-Webhook-Id": webhook_id,
        "X-Shopify-Event-Id": f"event-{webhook_id}",
        "X-Shopify-Shop-Domain": SHOP,
    }


def _connect(
    client: TestClient,
    own_org: Organization,
    token: str,
) -> str:
    install = client.get(
        f"/v1/organizations/{own_org.id}/integrations/shopify/install",
        params={"shop": SHOP},
        headers=_auth(token),
        follow_redirects=False,
    )
    assert install.status_code == 307

    location = install.headers["location"]
    parsed = urlparse(location)
    assert parsed.netloc == SHOP
    assert parsed.path == "/admin/oauth/authorize"
    query = parse_qs(parsed.query)
    assert query["scope"] == ["read_products,read_orders"]
    assert query["redirect_uri"] == [
        "https://identity.test/v1/integrations/shopify/oauth/callback"
    ]

    state = query["state"][0]
    params = {
        "code": "oauth-code",
        "shop": SHOP,
        "state": state,
        "timestamp": "1790467200",
    }
    params["hmac"] = _callback_hmac(params)

    callback = client.get(
        "/v1/integrations/shopify/oauth/callback",
        params=params,
        follow_redirects=False,
    )
    assert callback.status_code == 303
    assert callback.headers["location"].startswith(
        "https://identity.test/app?shopify=connected"
    )
    return state


def _post_webhook(
    client: TestClient,
    *,
    topic: str,
    webhook_id: str,
    payload: dict[str, object],
):
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return client.post(
        "/v1/integrations/shopify/webhooks",
        content=body,
        headers=_webhook_headers(topic, webhook_id, body),
    )


def test_install_uses_least_privilege_and_strict_shop_domain(
    client: TestClient,
    seeded_user: tuple[User, Organization, Organization],
    token: str,
) -> None:
    _, own_org, _ = seeded_user

    bad = client.get(
        f"/v1/organizations/{own_org.id}/integrations/shopify/install",
        params={"shop": "product-identity-dev.myshopify.com.evil.example"},
        headers=_auth(token),
        follow_redirects=False,
    )
    assert bad.status_code == 422

    good = client.get(
        f"/v1/organizations/{own_org.id}/integrations/shopify/install",
        params={"shop": SHOP},
        headers=_auth(token),
        follow_redirects=False,
    )
    assert good.status_code == 307
    query = parse_qs(urlparse(good.headers["location"]).query)
    assert query["scope"] == ["read_products,read_orders"]
    assert "write_products" not in query["scope"][0]
    assert "write_orders" not in query["scope"][0]


def test_install_is_tenant_scoped(
    client: TestClient,
    seeded_user: tuple[User, Organization, Organization],
    token: str,
) -> None:
    _, _, other_org = seeded_user
    response = client.get(
        f"/v1/organizations/{other_org.id}/integrations/shopify/install",
        params={"shop": SHOP},
        headers=_auth(token),
        follow_redirects=False,
    )
    assert response.status_code == 403


def test_oauth_callback_is_one_time_and_tokens_are_encrypted(
    client: TestClient,
    session: Session,
    seeded_user: tuple[User, Organization, Organization],
    token: str,
    shopify_client: FakeShopifyAdminClient,
) -> None:
    _, own_org, _ = seeded_user
    state = _connect(client, own_org, token)

    installation = session.scalar(
        select(ShopifyInstallation).where(
            ShopifyInstallation.organization_id == own_org.id
        )
    )
    assert installation is not None
    assert installation.shop_domain == SHOP
    assert installation.status == ShopifyInstallationStatus.ACTIVE
    assert installation.encrypted_access_token != "access-initial"
    assert installation.encrypted_refresh_token != "refresh-initial"

    cipher = TokenCipher(TEST_SHOPIFY_ENCRYPTION_KEY)
    assert cipher.decrypt(installation.encrypted_access_token) == "access-initial"
    assert cipher.decrypt(installation.encrypted_refresh_token) == "refresh-initial"

    replay_params = {
        "code": "oauth-code",
        "shop": SHOP,
        "state": state,
        "timestamp": "1790467200",
    }
    replay_params["hmac"] = _callback_hmac(replay_params)
    replay = client.get(
        "/v1/integrations/shopify/oauth/callback",
        params=replay_params,
        follow_redirects=False,
    )
    assert replay.status_code == 400
    assert len(shopify_client.exchange_calls) == 1


def test_oauth_callback_rejects_invalid_hmac_before_token_exchange(
    client: TestClient,
    seeded_user: tuple[User, Organization, Organization],
    token: str,
    shopify_client: FakeShopifyAdminClient,
) -> None:
    _, own_org, _ = seeded_user
    install = client.get(
        f"/v1/organizations/{own_org.id}/integrations/shopify/install",
        params={"shop": SHOP},
        headers=_auth(token),
        follow_redirects=False,
    )
    state = parse_qs(urlparse(install.headers["location"]).query)["state"][0]

    response = client.get(
        "/v1/integrations/shopify/oauth/callback",
        params={
            "code": "oauth-code",
            "shop": SHOP,
            "state": state,
            "timestamp": "1790467200",
            "hmac": "not-valid",
        },
        follow_redirects=False,
    )

    assert response.status_code == 401
    assert shopify_client.exchange_calls == []


def test_product_sync_maps_sku_to_canonical_product_idempotently(
    client: TestClient,
    session: Session,
    seeded_user: tuple[User, Organization, Organization],
    token: str,
    shopify_client: FakeShopifyAdminClient,
) -> None:
    _, own_org, _ = seeded_user
    _connect(client, own_org, token)

    page = {
        "data": {
            "products": {
                "nodes": [
                    {
                        "id": "gid://shopify/Product/100",
                        "title": "Field Recorder",
                        "handle": "field-recorder",
                        "variants": {
                            "nodes": [
                                {
                                    "id": "gid://shopify/ProductVariant/200",
                                    "sku": "REC-100",
                                },
                                {
                                    "id": "gid://shopify/ProductVariant/201",
                                    "sku": "",
                                },
                            ]
                        },
                    }
                ],
                "pageInfo": {"hasNextPage": False, "endCursor": None},
            }
        }
    }
    shopify_client.graphql_responses.extend([page, page])

    first = client.post(
        f"/v1/organizations/{own_org.id}/integrations/shopify/sync",
        headers=_auth(token),
    )
    second = client.post(
        f"/v1/organizations/{own_org.id}/integrations/shopify/sync",
        headers=_auth(token),
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["mapped_variants"] == 1
    assert session.scalar(
        select(func.count(Product.id)).where(Product.organization_id == own_org.id)
    ) == 1
    assert session.scalar(select(func.count(ShopifyProductMap.id))) == 1

    canonical = session.scalar(
        select(Product).where(
            Product.organization_id == own_org.id,
            Product.sku == "REC-100",
        )
    )
    mapping = session.scalar(select(ShopifyProductMap))
    assert canonical is not None
    assert mapping is not None
    assert mapping.product_id == canonical.id


def test_expiring_offline_token_is_refreshed_before_sync(
    client: TestClient,
    session: Session,
    seeded_user: tuple[User, Organization, Organization],
    token: str,
    shopify_client: FakeShopifyAdminClient,
) -> None:
    _, own_org, _ = seeded_user
    _connect(client, own_org, token)
    installation = session.scalar(
        select(ShopifyInstallation).where(
            ShopifyInstallation.organization_id == own_org.id
        )
    )
    assert installation is not None

    installation.access_token_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    installation.refresh_token_expires_at = datetime.now(timezone.utc) + timedelta(days=30)
    session.commit()

    response = client.post(
        f"/v1/organizations/{own_org.id}/integrations/shopify/sync",
        headers=_auth(token),
    )

    assert response.status_code == 200
    assert shopify_client.refresh_calls == [(SHOP, "refresh-initial")]

    session.expire_all()
    refreshed = session.get(ShopifyInstallation, installation.id)
    assert refreshed is not None
    cipher = TokenCipher(TEST_SHOPIFY_ENCRYPTION_KEY)
    assert cipher.decrypt(refreshed.encrypted_access_token) == "access-refreshed"
    assert cipher.decrypt(refreshed.encrypted_refresh_token) == "refresh-refreshed"


def test_product_webhook_hmac_and_duplicate_delivery_are_safe(
    client: TestClient,
    session: Session,
    seeded_user: tuple[User, Organization, Organization],
    token: str,
) -> None:
    _, own_org, _ = seeded_user
    _connect(client, own_org, token)

    payload = {
        "id": 100,
        "title": "Webhook Device",
        "variants": [{"id": 200, "sku": "WEB-100"}],
    }
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")

    invalid = client.post(
        "/v1/integrations/shopify/webhooks",
        content=body,
        headers={
            **_webhook_headers("products/update", "wh-invalid", body),
            "X-Shopify-Hmac-Sha256": "bad-signature",
        },
    )
    assert invalid.status_code == 401

    first = _post_webhook(
        client,
        topic="products/update",
        webhook_id="wh-product-1",
        payload=payload,
    )
    duplicate = _post_webhook(
        client,
        topic="products/update",
        webhook_id="wh-product-1",
        payload=payload,
    )

    assert first.status_code == 200
    assert first.json()["duplicate"] is False
    assert duplicate.status_code == 200
    assert duplicate.json()["duplicate"] is True
    assert session.scalar(select(func.count(ShopifyProductMap.id))) == 1
    assert session.scalar(select(func.count(ShopifyWebhookDelivery.id))) == 1


def test_order_webhook_maps_only_operational_fields_not_customer_pii(
    client: TestClient,
    session: Session,
    seeded_user: tuple[User, Organization, Organization],
    token: str,
) -> None:
    _, own_org, _ = seeded_user
    _connect(client, own_org, token)

    product_response = _post_webhook(
        client,
        topic="products/update",
        webhook_id="wh-product-order",
        payload={
            "id": 100,
            "title": "Order Device",
            "variants": [{"id": 200, "sku": "ORDER-100"}],
        },
    )
    assert product_response.status_code == 200

    order_response = _post_webhook(
        client,
        topic="orders/create",
        webhook_id="wh-order-1",
        payload={
            "id": 300,
            "admin_graphql_api_id": "gid://shopify/Order/300",
            "name": "#1001",
            "email": "private-customer@example.com",
            "phone": "+237600000000",
            "shipping_address": {"name": "Private Customer", "address1": "Private address"},
            "line_items": [
                {
                    "id": 400,
                    "variant_id": 200,
                    "sku": "ORDER-100",
                    "quantity": 2,
                }
            ],
        },
    )

    assert order_response.status_code == 200
    order = session.scalar(select(ShopifyOrderMap))
    line = session.scalar(select(ShopifyOrderLineMap))
    assert order is not None
    assert order.order_name == "#1001"
    assert line is not None
    assert line.sku == "ORDER-100"
    assert line.quantity == 2
    assert line.product_id is not None
    assert line.unit_id is None

    assert not hasattr(order, "email")
    assert not hasattr(order, "phone")
    assert not hasattr(order, "shipping_address")

    delivery = session.scalar(
        select(ShopifyWebhookDelivery).where(
            ShopifyWebhookDelivery.webhook_id == "wh-order-1"
        )
    )
    assert delivery is not None
    assert "private-customer@example.com" not in delivery.payload_sha256


def test_uninstall_revokes_tokens_but_keeps_canonical_identity(
    client: TestClient,
    session: Session,
    seeded_user: tuple[User, Organization, Organization],
    token: str,
) -> None:
    _, own_org, _ = seeded_user
    _connect(client, own_org, token)

    _post_webhook(
        client,
        topic="products/update",
        webhook_id="wh-product-uninstall",
        payload={
            "id": 100,
            "title": "Persistent Product",
            "variants": [{"id": 200, "sku": "KEEP-100"}],
        },
    )
    canonical = session.scalar(
        select(Product).where(
            Product.organization_id == own_org.id,
            Product.sku == "KEEP-100",
        )
    )
    assert canonical is not None

    response = _post_webhook(
        client,
        topic="app/uninstalled",
        webhook_id="wh-uninstall",
        payload={"id": 999, "domain": SHOP},
    )
    assert response.status_code == 200

    installation = session.scalar(
        select(ShopifyInstallation).where(
            ShopifyInstallation.organization_id == own_org.id
        )
    )
    assert installation is not None
    assert installation.status == ShopifyInstallationStatus.UNINSTALLED
    assert installation.encrypted_access_token is None
    assert installation.encrypted_refresh_token is None
    assert session.get(Product, canonical.id) is not None


def test_shop_redact_purges_connector_data_without_deleting_canonical_product(
    client: TestClient,
    session: Session,
    seeded_user: tuple[User, Organization, Organization],
    token: str,
) -> None:
    _, own_org, _ = seeded_user
    _connect(client, own_org, token)

    _post_webhook(
        client,
        topic="products/update",
        webhook_id="wh-product-redact",
        payload={
            "id": 100,
            "title": "Canonical Product",
            "variants": [{"id": 200, "sku": "CANON-100"}],
        },
    )
    canonical = session.scalar(
        select(Product).where(
            Product.organization_id == own_org.id,
            Product.sku == "CANON-100",
        )
    )
    assert canonical is not None

    response = _post_webhook(
        client,
        topic="shop/redact",
        webhook_id="wh-shop-redact",
        payload={"shop_id": 123, "shop_domain": SHOP},
    )
    assert response.status_code == 200

    assert session.scalar(select(func.count(ShopifyInstallation.id))) == 0
    assert session.scalar(select(func.count(ShopifyProductMap.id))) == 0
    assert session.scalar(select(func.count(ShopifyOrderMap.id))) == 0
    assert session.get(Product, canonical.id) is not None


def test_customer_compliance_webhook_does_not_persist_customer_payload(
    client: TestClient,
    session: Session,
    seeded_user: tuple[User, Organization, Organization],
    token: str,
) -> None:
    _, own_org, _ = seeded_user
    _connect(client, own_org, token)

    response = _post_webhook(
        client,
        topic="customers/data_request",
        webhook_id="wh-customer-data-request",
        payload={
            "shop_id": 1,
            "shop_domain": SHOP,
            "customer": {
                "id": 55,
                "email": "erase-me@example.com",
                "phone": "+237699999999",
            },
            "orders_requested": [10, 11],
        },
    )
    assert response.status_code == 200

    delivery = session.scalar(
        select(ShopifyWebhookDelivery).where(
            ShopifyWebhookDelivery.webhook_id == "wh-customer-data-request"
        )
    )
    assert delivery is not None
    assert not hasattr(delivery, "payload")
    assert not hasattr(delivery, "customer_email")
    assert "erase-me@example.com" not in delivery.payload_sha256
