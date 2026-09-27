import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.integrations.shopify.client import ShopifyAdminClient, ShopifyTokenResponse
from app.integrations.shopify.crypto import TokenCipher
from app.models.identity import Product
from app.models.shopify import (
    ShopifyInstallation,
    ShopifyInstallationStatus,
    ShopifyOrderLineMap,
    ShopifyOrderMap,
    ShopifyProductMap,
    ShopifyWebhookDelivery,
    ShopifyWebhookStatus,
)

PRODUCTS_QUERY = """
query ProductIdentityProducts($first: Int!, $after: String) {
  products(first: $first, after: $after) {
    nodes {
      id
      title
      handle
      variants(first: 100) {
        nodes {
          id
          sku
        }
      }
    }
    pageInfo {
      hasNextPage
      endCursor
    }
  }
}
"""


class ShopifyConnectorError(RuntimeError):
    pass


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def store_installation_tokens(
    session: Session,
    *,
    organization_id: uuid.UUID,
    shop_domain: str,
    token_response: ShopifyTokenResponse,
    cipher: TokenCipher,
) -> ShopifyInstallation:
    installation = session.scalar(
        select(ShopifyInstallation).where(
            ShopifyInstallation.organization_id == organization_id
        )
    )
    if installation is None:
        installation = ShopifyInstallation(
            organization_id=organization_id,
            shop_domain=shop_domain,
        )
        session.add(installation)
        session.flush()
    elif installation.shop_domain != shop_domain:
        raise ShopifyConnectorError(
            "This organization is already connected to another Shopify store"
        )

    installation.scopes = token_response.scope
    installation.encrypted_access_token = cipher.encrypt(token_response.access_token)
    installation.encrypted_refresh_token = cipher.encrypt(token_response.refresh_token)
    installation.access_token_expires_at = token_response.access_token_expires_at
    installation.refresh_token_expires_at = token_response.refresh_token_expires_at
    installation.status = ShopifyInstallationStatus.ACTIVE
    installation.uninstalled_at = None
    session.flush()
    return installation


def access_token_for(
    session: Session,
    *,
    installation: ShopifyInstallation,
    client: ShopifyAdminClient,
    cipher: TokenCipher,
    refresh_skew_seconds: int = 90,
) -> str:
    if installation.status != ShopifyInstallationStatus.ACTIVE:
        raise ShopifyConnectorError("Shopify installation is not active")
    if not installation.encrypted_access_token or not installation.encrypted_refresh_token:
        raise ShopifyConnectorError("Shopify installation has no usable tokens")

    now = datetime.now(timezone.utc)
    expires_at = _utc(installation.access_token_expires_at)
    refresh_expires_at = _utc(installation.refresh_token_expires_at)

    if expires_at is None:
        raise ShopifyConnectorError("Shopify access token expiry is missing")

    if now < expires_at - timedelta(seconds=refresh_skew_seconds):
        return cipher.decrypt(installation.encrypted_access_token)

    if refresh_expires_at is None or now >= refresh_expires_at:
        installation.status = ShopifyInstallationStatus.REAUTH_REQUIRED
        session.flush()
        raise ShopifyConnectorError("Shopify refresh token expired; reauthorization is required")

    refreshed = client.refresh_token(
        shop=installation.shop_domain,
        refresh_token=cipher.decrypt(installation.encrypted_refresh_token),
    )
    installation.encrypted_access_token = cipher.encrypt(refreshed.access_token)
    installation.encrypted_refresh_token = cipher.encrypt(refreshed.refresh_token)
    installation.access_token_expires_at = refreshed.access_token_expires_at
    installation.refresh_token_expires_at = refreshed.refresh_token_expires_at
    installation.scopes = refreshed.scope
    session.flush()
    return refreshed.access_token


def upsert_product_variant_mapping(
    session: Session,
    *,
    installation: ShopifyInstallation,
    shopify_product_gid: str,
    shopify_variant_gid: str,
    sku: str,
    title: str,
) -> ShopifyProductMap | None:
    clean_sku = sku.strip()
    if not clean_sku:
        return None

    canonical = session.scalar(
        select(Product).where(
            Product.organization_id == installation.organization_id,
            Product.sku == clean_sku,
        )
    )
    if canonical is None:
        canonical = Product(
            organization_id=installation.organization_id,
            name=title.strip() or clean_sku,
            sku=clean_sku,
        )
        session.add(canonical)
        session.flush()

    mapping = session.scalar(
        select(ShopifyProductMap).where(
            ShopifyProductMap.installation_id == installation.id,
            ShopifyProductMap.shopify_variant_gid == shopify_variant_gid,
        )
    )
    if mapping is None:
        mapping = ShopifyProductMap(
            organization_id=installation.organization_id,
            installation_id=installation.id,
            product_id=canonical.id,
            shopify_product_gid=shopify_product_gid,
            shopify_variant_gid=shopify_variant_gid,
            sku=clean_sku,
        )
        session.add(mapping)
    else:
        mapping.product_id = canonical.id
        mapping.shopify_product_gid = shopify_product_gid
        mapping.sku = clean_sku
        mapping.deleted_at = None
        mapping.synced_at = datetime.now(timezone.utc)
    session.flush()
    return mapping


def sync_products(
    session: Session,
    *,
    installation: ShopifyInstallation,
    client: ShopifyAdminClient,
    cipher: TokenCipher,
) -> int:
    token = access_token_for(
        session,
        installation=installation,
        client=client,
        cipher=cipher,
    )
    cursor: str | None = None
    mapped = 0

    while True:
        body = client.graphql(
            shop=installation.shop_domain,
            access_token=token,
            query=PRODUCTS_QUERY,
            variables={"first": 50, "after": cursor},
        )
        products = body.get("data", {}).get("products", {})
        for product in products.get("nodes", []):
            for variant in product.get("variants", {}).get("nodes", []):
                result = upsert_product_variant_mapping(
                    session,
                    installation=installation,
                    shopify_product_gid=str(product["id"]),
                    shopify_variant_gid=str(variant["id"]),
                    sku=str(variant.get("sku") or ""),
                    title=str(product.get("title") or ""),
                )
                if result is not None:
                    mapped += 1

        page_info = products.get("pageInfo", {})
        if not page_info.get("hasNextPage"):
            break
        cursor = page_info.get("endCursor")
        if not cursor:
            raise ShopifyConnectorError("Shopify pagination cursor is missing")

    installation.last_synced_at = datetime.now(timezone.utc)
    session.flush()
    return mapped


def _gid(resource: str, raw_id: Any, admin_gid: Any = None) -> str:
    if admin_gid:
        return str(admin_gid)
    return f"gid://shopify/{resource}/{raw_id}"


def apply_product_webhook(
    session: Session,
    *,
    installation: ShopifyInstallation,
    payload: dict[str, Any],
    deleted: bool = False,
) -> int:
    product_gid = _gid("Product", payload.get("id"), payload.get("admin_graphql_api_id"))
    if deleted:
        mappings = session.scalars(
            select(ShopifyProductMap).where(
                ShopifyProductMap.installation_id == installation.id,
                ShopifyProductMap.shopify_product_gid == product_gid,
                ShopifyProductMap.deleted_at.is_(None),
            )
        ).all()
        now = datetime.now(timezone.utc)
        for mapping in mappings:
            mapping.deleted_at = now
        session.flush()
        return len(mappings)

    mapped = 0
    title = str(payload.get("title") or "")
    for variant in payload.get("variants") or []:
        variant_gid = _gid(
            "ProductVariant",
            variant.get("id"),
            variant.get("admin_graphql_api_id"),
        )
        result = upsert_product_variant_mapping(
            session,
            installation=installation,
            shopify_product_gid=product_gid,
            shopify_variant_gid=variant_gid,
            sku=str(variant.get("sku") or ""),
            title=title,
        )
        if result is not None:
            mapped += 1
    return mapped


def apply_order_webhook(
    session: Session,
    *,
    installation: ShopifyInstallation,
    payload: dict[str, Any],
) -> ShopifyOrderMap:
    order_gid = _gid("Order", payload.get("id"), payload.get("admin_graphql_api_id"))
    order = session.scalar(
        select(ShopifyOrderMap).where(
            ShopifyOrderMap.installation_id == installation.id,
            ShopifyOrderMap.shopify_order_gid == order_gid,
        )
    )
    if order is None:
        order = ShopifyOrderMap(
            organization_id=installation.organization_id,
            installation_id=installation.id,
            shopify_order_gid=order_gid,
        )
        session.add(order)
        session.flush()

    order.order_name = str(payload.get("name") or "") or None
    cancelled_at = payload.get("cancelled_at")
    order.cancelled_at = (
        datetime.fromisoformat(str(cancelled_at).replace("Z", "+00:00"))
        if cancelled_at
        else None
    )
    order.synced_at = datetime.now(timezone.utc)

    existing_lines = {
        row.shopify_line_item_gid: row
        for row in session.scalars(
            select(ShopifyOrderLineMap).where(
                ShopifyOrderLineMap.order_map_id == order.id
            )
        ).all()
    }
    seen: set[str] = set()

    for line in payload.get("line_items") or []:
        line_gid = _gid("LineItem", line.get("id"), line.get("admin_graphql_api_id"))
        seen.add(line_gid)
        sku = str(line.get("sku") or "").strip() or None
        canonical_product_id = None

        variant_id = line.get("variant_id")
        if variant_id:
            variant_gid = _gid("ProductVariant", variant_id)
            mapping = session.scalar(
                select(ShopifyProductMap).where(
                    ShopifyProductMap.installation_id == installation.id,
                    ShopifyProductMap.shopify_variant_gid == variant_gid,
                    ShopifyProductMap.deleted_at.is_(None),
                )
            )
            if mapping is not None:
                canonical_product_id = mapping.product_id

        if canonical_product_id is None and sku:
            canonical = session.scalar(
                select(Product).where(
                    Product.organization_id == installation.organization_id,
                    Product.sku == sku,
                )
            )
            canonical_product_id = canonical.id if canonical is not None else None

        row = existing_lines.get(line_gid)
        if row is None:
            row = ShopifyOrderLineMap(
                organization_id=installation.organization_id,
                order_map_id=order.id,
                shopify_line_item_gid=line_gid,
                sku=sku,
                quantity=int(line.get("quantity") or 0),
                product_id=canonical_product_id,
                unit_id=None,
            )
            session.add(row)
        else:
            row.sku = sku
            row.quantity = int(line.get("quantity") or 0)
            row.product_id = canonical_product_id

    for line_gid, row in existing_lines.items():
        if line_gid not in seen:
            session.delete(row)

    session.flush()
    return order


def uninstall_shop(session: Session, *, installation: ShopifyInstallation) -> None:
    installation.status = ShopifyInstallationStatus.UNINSTALLED
    installation.uninstalled_at = datetime.now(timezone.utc)
    installation.encrypted_access_token = None
    installation.encrypted_refresh_token = None
    installation.access_token_expires_at = None
    installation.refresh_token_expires_at = None
    session.flush()


def redact_shop_connector_data(
    session: Session,
    *,
    installation: ShopifyInstallation,
) -> None:
    order_ids = session.scalars(
        select(ShopifyOrderMap.id).where(
            ShopifyOrderMap.installation_id == installation.id
        )
    ).all()
    if order_ids:
        session.execute(
            delete(ShopifyOrderLineMap).where(
                ShopifyOrderLineMap.order_map_id.in_(order_ids)
            )
        )
    session.execute(
        delete(ShopifyOrderMap).where(
            ShopifyOrderMap.installation_id == installation.id
        )
    )
    session.execute(
        delete(ShopifyProductMap).where(
            ShopifyProductMap.installation_id == installation.id
        )
    )
    session.execute(
        delete(ShopifyWebhookDelivery).where(
            ShopifyWebhookDelivery.installation_id == installation.id
        )
    )
    session.delete(installation)
    session.flush()


def payload_digest(raw_body: bytes) -> str:
    return hashlib.sha256(raw_body).hexdigest()
