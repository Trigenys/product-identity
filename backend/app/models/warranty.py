import enum
import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Enum, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class WarrantyStartRule(str, enum.Enum):
    REGISTRATION_DATE = "registration_date"
    PURCHASE_DATE_OR_REGISTRATION = "purchase_date_or_registration"


class WarrantyState(str, enum.Enum):
    UNREGISTERED = "unregistered"
    ACTIVE = "active"
    EXPIRED = "expired"


class RegistrationActor(str, enum.Enum):
    CUSTOMER = "customer"
    MERCHANT = "merchant"
    SYSTEM = "system"


class WarrantyPolicy(Base):
    __tablename__ = "warranty_policies"
    __table_args__ = (
        UniqueConstraint("product_id", name="uq_warranty_policy_product"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    duration_months: Mapped[int] = mapped_column(Integer, nullable=False)
    start_rule: Mapped[WarrantyStartRule] = mapped_column(
        Enum(WarrantyStartRule, name="warranty_start_rule", native_enum=False),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class ProductRegistration(Base):
    __tablename__ = "product_registrations"
    __table_args__ = (
        UniqueConstraint("unit_id", name="uq_product_registration_unit"),
        UniqueConstraint(
            "organization_id",
            "idempotency_key",
            name="uq_product_registration_organization_idempotency",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    unit_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("units.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)

    customer_name: Mapped[str] = mapped_column(String(200), nullable=False)
    customer_email: Mapped[str] = mapped_column(String(320), nullable=False)
    purchase_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    registered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    warranty_started_on: Mapped[date] = mapped_column(Date, nullable=False)
    warranty_expires_on: Mapped[date] = mapped_column(Date, nullable=False)

    policy_duration_months: Mapped[int] = mapped_column(Integer, nullable=False)
    policy_start_rule: Mapped[WarrantyStartRule] = mapped_column(
        Enum(WarrantyStartRule, name="registration_policy_start_rule", native_enum=False),
        nullable=False,
    )

    corrected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class RegistrationAudit(Base):
    __tablename__ = "registration_audits"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    registration_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("product_registrations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    actor: Mapped[RegistrationActor] = mapped_column(
        Enum(RegistrationActor, name="registration_actor", native_enum=False),
        nullable=False,
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    before_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    after_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
