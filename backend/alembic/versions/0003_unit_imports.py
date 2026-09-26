"""unit import jobs

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-26
"""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "unit_imports",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("batch_id", sa.Uuid(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column(
            "status",
            sa.Enum("PENDING", "PROCESSING", "COMPLETED", "FAILED", name="unit_import_status", native_enum=False),
            nullable=False,
        ),
        sa.Column("total_rows", sa.Integer(), nullable=False),
        sa.Column("imported_count", sa.Integer(), nullable=False),
        sa.Column("rejected_count", sa.Integer(), nullable=False),
        sa.Column("errors_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["batch_id"], ["serialization_batches.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "idempotency_key", name="uq_unit_import_organization_idempotency"),
        sa.UniqueConstraint("batch_id", name="uq_unit_import_batch"),
    )
    op.create_index("ix_unit_imports_organization_id", "unit_imports", ["organization_id"], unique=False)
    op.create_index("ix_unit_imports_product_id", "unit_imports", ["product_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_unit_imports_product_id", table_name="unit_imports")
    op.drop_index("ix_unit_imports_organization_id", table_name="unit_imports")
    op.drop_table("unit_imports")
