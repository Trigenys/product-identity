import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class DeviceClass(str, enum.Enum):
    MOBILE = "mobile"
    DESKTOP = "desktop"
    UNKNOWN = "unknown"


class AuthenticitySignalType(str, enum.Enum):
    REPEAT_SCAN_BURST = "repeat_scan_burst"
    MULTI_COUNTRY_ACTIVITY = "multi_country_activity"


class AuthenticitySignalState(str, enum.Enum):
    OPEN = "open"
    REVIEWED = "reviewed"
    DISMISSED = "dismissed"


class AuthenticitySignal(Base):
    __tablename__ = "authenticity_signals"
    __table_args__ = (
        UniqueConstraint("signal_key", name="uq_authenticity_signal_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    unit_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("units.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    signal_key: Mapped[str] = mapped_column(String(180), nullable=False)
    signal_type: Mapped[AuthenticitySignalType] = mapped_column(
        Enum(AuthenticitySignalType, name="authenticity_signal_type", native_enum=False),
        nullable=False,
        index=True,
    )
    state: Mapped[AuthenticitySignalState] = mapped_column(
        Enum(AuthenticitySignalState, name="authenticity_signal_state", native_enum=False),
        nullable=False,
        default=AuthenticitySignalState.OPEN,
        index=True,
    )

    window_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_ended_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    observed_value: Mapped[int] = mapped_column(Integer, nullable=False)
    threshold_value: Mapped[int] = mapped_column(Integer, nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)

    reviewed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_note: Mapped[str | None] = mapped_column(String(500), nullable=True)

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
