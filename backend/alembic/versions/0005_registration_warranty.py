"""product registration and warranty

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-27
"""
from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "warranty_policies",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("duration_months", sa.Integer(), nullable=False),
        sa.Column(
            "start_rule",
            sa.Enum(
                "REGISTRATION_DATE",
                "PURCHASE_DATE_OR_REGISTRATION",
                name="warranty_start_rule",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("product_id", name="uq_warranty_policy_product"),
    )
    op.create_index("ix_warranty_policies_organization_id", "warranty_policies", ["organization_id"], unique=False)
    op.create_index("ix_warranty_policies_product_id", "warranty_policies", ["product_id"], unique=False)

    op.create_table(
        "product_registrations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("unit_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("customer_name", sa.String(length=200), nullable=False),
        sa.Column("customer_email", sa.String(length=320), nullable=False),
        sa.Column("purchase_date", sa.Date(), nullable=True),
        sa.Column("registered_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("warranty_started_on", sa.Date(), nullable=False),
        sa.Column("warranty_expires_on", sa.Date(), nullable=False),
        sa.Column("policy_duration_months", sa.Integer(), nullable=False),
        sa.Column(
            "policy_start_rule",
            sa.Enum(
                "REGISTRATION_DATE",
                "PURCHASE_DATE_OR_REGISTRATION",
                name="registration_policy_start_rule",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column("corrected_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["unit_id"], ["units.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("unit_id", name="uq_product_registration_unit"),
        sa.UniqueConstraint(
            "organization_id",
            "idempotency_key",
            name="uq_product_registration_organization_idempotency",
        ),
    )
    op.create_index("ix_product_registrations_organization_id", "product_registrations", ["organization_id"], unique=False)
    op.create_index("ix_product_registrations_product_id", "product_registrations", ["product_id"], unique=False)
    op.create_index("ix_product_registrations_unit_id", "product_registrations", ["unit_id"], unique=False)

    op.create_table(
        "registration_audits",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("registration_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "actor",
            sa.Enum("CUSTOMER", "MERCHANT", "SYSTEM", name="registration_actor", native_enum=False),
            nullable=False,
        ),
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column("action", sa.String(length=80), nullable=False),
        sa.Column("before_json", sa.Text(), nullable=True),
        sa.Column("after_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["registration_id"], ["product_registrations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("registration_id", "version", name="uq_registration_audit_version"),
    )
    op.create_index("ix_registration_audits_organization_id", "registration_audits", ["organization_id"], unique=False)
    op.create_index("ix_registration_audits_registration_id", "registration_audits", ["registration_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_registration_audits_registration_id", table_name="registration_audits")
    op.drop_index("ix_registration_audits_organization_id", table_name="registration_audits")
    op.drop_table("registration_audits")
    op.drop_index("ix_product_registrations_unit_id", table_name="product_registrations")
    op.drop_index("ix_product_registrations_product_id", table_name="product_registrations")
    op.drop_index("ix_product_registrations_organization_id", table_name="product_registrations")
    op.drop_table("product_registrations")
    op.drop_index("ix_warranty_policies_product_id", table_name="warranty_policies")
    op.drop_index("ix_warranty_policies_organization_id", table_name="warranty_policies")
    op.drop_table("warranty_policies")
