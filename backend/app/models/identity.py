import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text, UniqueConstraint, event, func, inspect
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class UnitStatus(str, enum.Enum):
    ACTIVE = "active"
    REVOKED = "revoked"


class UnitImportStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class VerificationOutcome(str, enum.Enum):
    VALID = "valid"
    REVOKED = "revoked"
    UNKNOWN = "unknown"


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (
        UniqueConstraint("organization_id", "sku", name="uq_product_organization_sku"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    sku: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    batches: Mapped[list["SerializationBatch"]] = relationship(
        back_populates="product",
        cascade="all, delete-orphan",
    )
    units: Mapped[list["Unit"]] = relationship(
        back_populates="product",
        cascade="all, delete-orphan",
    )
    imports: Mapped[list["UnitImport"]] = relationship(
        back_populates="product",
        cascade="all, delete-orphan",
    )


class SerializationBatch(Base):
    __tablename__ = "serialization_batches"
    __table_args__ = (
        UniqueConstraint("organization_id", "idempotency_key", name="uq_batch_organization_idempotency"),
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
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    prefix: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    product: Mapped[Product] = relationship(back_populates="batches")
    units: Mapped[list["Unit"]] = relationship(
        back_populates="batch",
        cascade="all, delete-orphan",
        order_by="Unit.sequence_number",
    )


class UnitImport(Base):
    __tablename__ = "unit_imports"
    __table_args__ = (
        UniqueConstraint("organization_id", "idempotency_key", name="uq_unit_import_organization_idempotency"),
        UniqueConstraint("batch_id", name="uq_unit_import_batch"),
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
    batch_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("serialization_batches.id", ondelete="SET NULL"),
        nullable=True,
    )
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[UnitImportStatus] = mapped_column(
        Enum(UnitImportStatus, name="unit_import_status", native_enum=False),
        nullable=False,
        default=UnitImportStatus.PENDING,
    )
    total_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    imported_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rejected_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    errors_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    product: Mapped[Product] = relationship(back_populates="imports")
    batch: Mapped[SerializationBatch | None] = relationship()


class Unit(Base):
    __tablename__ = "units"
    __table_args__ = (
        UniqueConstraint("organization_id", "serial", name="uq_unit_organization_serial"),
        UniqueConstraint("verification_token_digest", name="uq_unit_verification_token_digest"),
        UniqueConstraint("batch_id", "sequence_number", name="uq_unit_batch_sequence"),
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
    batch_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("serialization_batches.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    serial: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    verification_token_digest: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[UnitStatus] = mapped_column(
        Enum(UnitStatus, name="unit_status", native_enum=False),
        nullable=False,
        default=UnitStatus.ACTIVE,
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    product: Mapped[Product] = relationship(back_populates="units")
    batch: Mapped[SerializationBatch] = relationship(back_populates="units")


class VerificationEvent(Base):
    __tablename__ = "verification_events"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    unit_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("units.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    token_digest: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    outcome: Mapped[VerificationOutcome] = mapped_column(
        Enum(VerificationOutcome, name="verification_outcome", native_enum=False),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )


class ImmutableUnitIdentityError(ValueError):
    pass


@event.listens_for(Unit, "before_update")
def protect_unit_identity(_mapper, _connection, target: Unit) -> None:
    state = inspect(target)
    immutable_fields = (
        "id",
        "organization_id",
        "product_id",
        "batch_id",
        "sequence_number",
        "serial",
    )
    changed = [field for field in immutable_fields if state.attrs[field].history.has_changes()]
    if changed:
        raise ImmutableUnitIdentityError(
            f"Unit identity fields are immutable after issuance: {', '.join(changed)}"
        )
