"""authenticity anomaly signals

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-27
"""
from alembic import op
import sqlalchemy as sa

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("verification_events") as batch_op:
        batch_op.add_column(sa.Column("country_code", sa.String(length=2), nullable=True))
        batch_op.add_column(sa.Column("device_class", sa.String(length=16), nullable=True))

    op.create_table(
        "authenticity_signals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("unit_id", sa.Uuid(), nullable=False),
        sa.Column("signal_key", sa.String(length=180), nullable=False),
        sa.Column(
            "signal_type",
            sa.Enum(
                "REPEAT_SCAN_BURST",
                "MULTI_COUNTRY_ACTIVITY",
                name="authenticity_signal_type",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "state",
            sa.Enum(
                "OPEN",
                "REVIEWED",
                "DISMISSED",
                name="authenticity_signal_state",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column("window_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_ended_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("observed_value", sa.Integer(), nullable=False),
        sa.Column("threshold_value", sa.Integer(), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("reviewed_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_note", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["unit_id"], ["units.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reviewed_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("signal_key", name="uq_authenticity_signal_key"),
    )
    op.create_index("ix_authenticity_signals_organization_id", "authenticity_signals", ["organization_id"], unique=False)
    op.create_index("ix_authenticity_signals_unit_id", "authenticity_signals", ["unit_id"], unique=False)
    op.create_index("ix_authenticity_signals_signal_type", "authenticity_signals", ["signal_type"], unique=False)
    op.create_index("ix_authenticity_signals_state", "authenticity_signals", ["state"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_authenticity_signals_state", table_name="authenticity_signals")
    op.drop_index("ix_authenticity_signals_signal_type", table_name="authenticity_signals")
    op.drop_index("ix_authenticity_signals_unit_id", table_name="authenticity_signals")
    op.drop_index("ix_authenticity_signals_organization_id", table_name="authenticity_signals")
    op.drop_table("authenticity_signals")

    with op.batch_alter_table("verification_events") as batch_op:
        batch_op.drop_column("device_class")
        batch_op.drop_column("country_code")
