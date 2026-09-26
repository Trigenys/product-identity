"""protected proof of purchase

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-27
"""
from alembic import op
import sqlalchemy as sa

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "proofs_of_purchase",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("registration_id", sa.Uuid(), nullable=False),
        sa.Column("object_key", sa.String(length=600), nullable=False),
        sa.Column("original_filename", sa.String(length=180), nullable=False),
        sa.Column("content_type", sa.String(length=80), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "review_state",
            sa.Enum("PENDING", "ACCEPTED", "REJECTED", name="proof_review_state", native_enum=False),
            nullable=False,
        ),
        sa.Column("reviewer_user_id", sa.Uuid(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("retention_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["registration_id"], ["product_registrations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reviewer_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("object_key"),
        sa.UniqueConstraint("registration_id", name="uq_proof_registration"),
    )
    op.create_index("ix_proofs_of_purchase_organization_id", "proofs_of_purchase", ["organization_id"], unique=False)
    op.create_index("ix_proofs_of_purchase_registration_id", "proofs_of_purchase", ["registration_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_proofs_of_purchase_registration_id", table_name="proofs_of_purchase")
    op.drop_index("ix_proofs_of_purchase_organization_id", table_name="proofs_of_purchase")
    op.drop_table("proofs_of_purchase")
