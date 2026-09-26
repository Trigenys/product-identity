"""public verification events

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-26
"""
from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "verification_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("unit_id", sa.Uuid(), nullable=True),
        sa.Column("token_digest", sa.String(length=64), nullable=False),
        sa.Column(
            "outcome",
            sa.Enum("VALID", "REVOKED", "UNKNOWN", name="verification_outcome", native_enum=False),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["unit_id"], ["units.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_verification_events_unit_id", "verification_events", ["unit_id"], unique=False)
    op.create_index("ix_verification_events_token_digest", "verification_events", ["token_digest"], unique=False)
    op.create_index("ix_verification_events_created_at", "verification_events", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_verification_events_created_at", table_name="verification_events")
    op.drop_index("ix_verification_events_token_digest", table_name="verification_events")
    op.drop_index("ix_verification_events_unit_id", table_name="verification_events")
    op.drop_table("verification_events")
