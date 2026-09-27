"""shopify connector

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-27
"""
from alembic import op
import sqlalchemy as sa

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "shopify_installations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("shop_domain", sa.String(length=255), nullable=False),
        sa.Column("scopes", sa.String(length=500), nullable=False),
        sa.Column("encrypted_access_token", sa.Text(), nullable=True),
        sa.Column("encrypted_refresh_token", sa.Text(), nullable=True),
        sa.Column("access_token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("refresh_token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "ACTIVE",
                "UNINSTALLED",
                "REAUTH_REQUIRED",
                name="shopify_installation_status",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column("installed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("uninstalled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("shop_domain", name="uq_shopify_installation_shop_domain"),
        sa.UniqueConstraint("organization_id", name="uq_shopify_installation_organization"),
    )
    op.create_index("ix_shopify_installations_organization_id", "shopify_installations", ["organization_id"], unique=False)
    op.create_index("ix_shopify_installations_shop_domain", "shopify_installations", ["shop_domain"], unique=False)

    op.create_table(
        "shopify_oauth_states",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("shop_domain", sa.String(length=255), nullable=False),
        sa.Column("nonce_digest", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("nonce_digest"),
    )
    op.create_index("ix_shopify_oauth_states_organization_id", "shopify_oauth_states", ["organization_id"], unique=False)

    op.create_table(
        "shopify_product_maps",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("installation_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("shopify_product_gid", sa.String(length=100), nullable=False),
        sa.Column("shopify_variant_gid", sa.String(length=100), nullable=False),
        sa.Column("sku", sa.String(length=120), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("synced_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["installation_id"], ["shopify_installations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("installation_id", "shopify_variant_gid", name="uq_shopify_product_map_variant"),
    )
    op.create_index("ix_shopify_product_maps_organization_id", "shopify_product_maps", ["organization_id"], unique=False)
    op.create_index("ix_shopify_product_maps_installation_id", "shopify_product_maps", ["installation_id"], unique=False)
    op.create_index("ix_shopify_product_maps_product_id", "shopify_product_maps", ["product_id"], unique=False)
    op.create_index("ix_shopify_product_maps_shopify_product_gid", "shopify_product_maps", ["shopify_product_gid"], unique=False)
    op.create_index("ix_shopify_product_maps_shopify_variant_gid", "shopify_product_maps", ["shopify_variant_gid"], unique=False)

    op.create_table(
        "shopify_order_maps",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("installation_id", sa.Uuid(), nullable=False),
        sa.Column("shopify_order_gid", sa.String(length=100), nullable=False),
        sa.Column("order_name", sa.String(length=80), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("synced_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["installation_id"], ["shopify_installations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("installation_id", "shopify_order_gid", name="uq_shopify_order_map_order"),
    )
    op.create_index("ix_shopify_order_maps_organization_id", "shopify_order_maps", ["organization_id"], unique=False)
    op.create_index("ix_shopify_order_maps_installation_id", "shopify_order_maps", ["installation_id"], unique=False)
    op.create_index("ix_shopify_order_maps_shopify_order_gid", "shopify_order_maps", ["shopify_order_gid"], unique=False)

    op.create_table(
        "shopify_order_line_maps",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("order_map_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=True),
        sa.Column("unit_id", sa.Uuid(), nullable=True),
        sa.Column("shopify_line_item_gid", sa.String(length=100), nullable=False),
        sa.Column("sku", sa.String(length=120), nullable=True),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["order_map_id"], ["shopify_order_maps.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["unit_id"], ["units.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("order_map_id", "shopify_line_item_gid", name="uq_shopify_order_line_map_line"),
    )
    op.create_index("ix_shopify_order_line_maps_organization_id", "shopify_order_line_maps", ["organization_id"], unique=False)
    op.create_index("ix_shopify_order_line_maps_order_map_id", "shopify_order_line_maps", ["order_map_id"], unique=False)
    op.create_index("ix_shopify_order_line_maps_product_id", "shopify_order_line_maps", ["product_id"], unique=False)
    op.create_index("ix_shopify_order_line_maps_unit_id", "shopify_order_line_maps", ["unit_id"], unique=False)

    op.create_table(
        "shopify_webhook_deliveries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("installation_id", sa.Uuid(), nullable=True),
        sa.Column("shop_domain", sa.String(length=255), nullable=False),
        sa.Column("webhook_id", sa.String(length=120), nullable=False),
        sa.Column("event_id", sa.String(length=120), nullable=True),
        sa.Column("topic", sa.String(length=120), nullable=False),
        sa.Column("payload_sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "RECEIVED",
                "PROCESSED",
                "IGNORED",
                "FAILED",
                name="shopify_webhook_status",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column("error_message", sa.String(length=500), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["installation_id"], ["shopify_installations.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("webhook_id", name="uq_shopify_webhook_delivery_id"),
    )
    op.create_index("ix_shopify_webhook_deliveries_installation_id", "shopify_webhook_deliveries", ["installation_id"], unique=False)
    op.create_index("ix_shopify_webhook_deliveries_shop_domain", "shopify_webhook_deliveries", ["shop_domain"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_shopify_webhook_deliveries_shop_domain", table_name="shopify_webhook_deliveries")
    op.drop_index("ix_shopify_webhook_deliveries_installation_id", table_name="shopify_webhook_deliveries")
    op.drop_table("shopify_webhook_deliveries")

    op.drop_index("ix_shopify_order_line_maps_unit_id", table_name="shopify_order_line_maps")
    op.drop_index("ix_shopify_order_line_maps_product_id", table_name="shopify_order_line_maps")
    op.drop_index("ix_shopify_order_line_maps_order_map_id", table_name="shopify_order_line_maps")
    op.drop_index("ix_shopify_order_line_maps_organization_id", table_name="shopify_order_line_maps")
    op.drop_table("shopify_order_line_maps")

    op.drop_index("ix_shopify_order_maps_shopify_order_gid", table_name="shopify_order_maps")
    op.drop_index("ix_shopify_order_maps_installation_id", table_name="shopify_order_maps")
    op.drop_index("ix_shopify_order_maps_organization_id", table_name="shopify_order_maps")
    op.drop_table("shopify_order_maps")

    op.drop_index("ix_shopify_product_maps_shopify_variant_gid", table_name="shopify_product_maps")
    op.drop_index("ix_shopify_product_maps_shopify_product_gid", table_name="shopify_product_maps")
    op.drop_index("ix_shopify_product_maps_product_id", table_name="shopify_product_maps")
    op.drop_index("ix_shopify_product_maps_installation_id", table_name="shopify_product_maps")
    op.drop_index("ix_shopify_product_maps_organization_id", table_name="shopify_product_maps")
    op.drop_table("shopify_product_maps")

    op.drop_index("ix_shopify_oauth_states_organization_id", table_name="shopify_oauth_states")
    op.drop_table("shopify_oauth_states")

    op.drop_index("ix_shopify_installations_shop_domain", table_name="shopify_installations")
    op.drop_index("ix_shopify_installations_organization_id", table_name="shopify_installations")
    op.drop_table("shopify_installations")
