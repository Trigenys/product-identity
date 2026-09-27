import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ShopifyInstallationStatus(str, enum.Enum):
    ACTIVE = "active"
    UNINSTALLED = "uninstalled"
    REAUTH_REQUIRED = "reauth_required"


class ShopifyWebhookStatus(str, enum.Enum):
    RECEIVED = "received"
    PROCESSED = "processed"
    IGNORED = "ignored"
    FAILED = "failed"


class ShopifyInstallation(Base):
    __tablename__ = "shopify_installations"
    __table_args__ = (
        UniqueConstraint("shop_domain", name="uq_shopify_installation_shop_domain"),
        UniqueConstraint("organization_id", name="uq_shopify_installation_organization"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    shop_domain: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    scopes: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    encrypted_access_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    encrypted_refresh_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    access_token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    refresh_token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[ShopifyInstallationStatus] = mapped_column(
        Enum(ShopifyInstallationStatus, name="shopify_installation_status", native_enum=False),
        nullable=False,
        default=ShopifyInstallationStatus.ACTIVE,
    )
    installed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    uninstalled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ShopifyOAuthState(Base):
    __tablename__ = "shopify_oauth_states"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    shop_domain: Mapped[str] = mapped_column(String(255), nullable=False)
    nonce_digest: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ShopifyProductMap(Base):
    __tablename__ = "shopify_product_maps"
    __table_args__ = (
        UniqueConstraint(
            "installation_id",
            "shopify_variant_gid",
            name="uq_shopify_product_map_variant",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    installation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("shopify_installations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    shopify_product_gid: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    shopify_variant_gid: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    sku: Mapped[str] = mapped_column(String(120), nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ShopifyOrderMap(Base):
    __tablename__ = "shopify_order_maps"
    __table_args__ = (
        UniqueConstraint(
            "installation_id",
            "shopify_order_gid",
            name="uq_shopify_order_map_order",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    installation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("shopify_installations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    shopify_order_gid: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    order_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ShopifyOrderLineMap(Base):
    __tablename__ = "shopify_order_line_maps"
    __table_args__ = (
        UniqueConstraint(
            "order_map_id",
            "shopify_line_item_gid",
            name="uq_shopify_order_line_map_line",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    order_map_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("shopify_order_maps.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    product_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("products.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    unit_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("units.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    shopify_line_item_gid: Mapped[str] = mapped_column(String(100), nullable=False)
    sku: Mapped[str | None] = mapped_column(String(120), nullable=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)


class ShopifyWebhookDelivery(Base):
    __tablename__ = "shopify_webhook_deliveries"
    __table_args__ = (
        UniqueConstraint("webhook_id", name="uq_shopify_webhook_delivery_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    installation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("shopify_installations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    shop_domain: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    webhook_id: Mapped[str] = mapped_column(String(120), nullable=False)
    event_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    topic: Mapped[str] = mapped_column(String(120), nullable=False)
    payload_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[ShopifyWebhookStatus] = mapped_column(
        Enum(ShopifyWebhookStatus, name="shopify_webhook_status", native_enum=False),
        nullable=False,
        default=ShopifyWebhookStatus.RECEIVED,
    )
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
