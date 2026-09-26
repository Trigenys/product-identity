"""identity serialization core

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-26
"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "products",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("sku", sa.String(length=120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "sku", name="uq_product_organization_sku"),
    )
    op.create_index("ix_products_organization_id", "products", ["organization_id"], unique=False)

    op.create_table(
        "serialization_batches",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("prefix", sa.String(length=20), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "idempotency_key", name="uq_batch_organization_idempotency"),
    )
    op.create_index(
        "ix_serialization_batches_organization_id",
        "serialization_batches",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        "ix_serialization_batches_product_id",
        "serialization_batches",
        ["product_id"],
        unique=False,
    )

    op.create_table(
        "units",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("batch_id", sa.Uuid(), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("serial", sa.String(length=120), nullable=False),
        sa.Column("verification_token_digest", sa.String(length=64), nullable=False),
        sa.Column(
            "status",
            sa.Enum("ACTIVE", "REVOKED", name="unit_status", native_enum=False),
            nullable=False,
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["batch_id"], ["serialization_batches.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "serial", name="uq_unit_organization_serial"),
        sa.UniqueConstraint("verification_token_digest", name="uq_unit_verification_token_digest"),
        sa.UniqueConstraint("batch_id", "sequence_number", name="uq_unit_batch_sequence"),
    )
    op.create_index("ix_units_organization_id", "units", ["organization_id"], unique=False)
    op.create_index("ix_units_product_id", "units", ["product_id"], unique=False)
    op.create_index("ix_units_batch_id", "units", ["batch_id"], unique=False)
    op.create_index("ix_units_serial", "units", ["serial"], unique=False)
    op.create_index(
        "ix_units_verification_token_digest",
        "units",
        ["verification_token_digest"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_units_verification_token_digest", table_name="units")
    op.drop_index("ix_units_serial", table_name="units")
    op.drop_index("ix_units_batch_id", table_name="units")
    op.drop_index("ix_units_product_id", table_name="units")
    op.drop_index("ix_units_organization_id", table_name="units")
    op.drop_table("units")
    op.drop_index("ix_serialization_batches_product_id", table_name="serialization_batches")
    op.drop_index("ix_serialization_batches_organization_id", table_name="serialization_batches")
    op.drop_table("serialization_batches")
    op.drop_index("ix_products_organization_id", table_name="products")
    op.drop_table("products")
