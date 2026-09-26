import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.authenticity import (
    AuthenticitySignal,
    AuthenticitySignalType,
)
from app.models.identity import Unit, VerificationEvent


@dataclass(frozen=True)
class AuthenticityThresholds:
    repeat_scan_count: int = 6
    repeat_scan_window_minutes: int = 10
    country_count: int = 2
    country_window_hours: int = 24


def _bucket_start(now: datetime, *, seconds: int) -> datetime:
    epoch = int(now.timestamp())
    floored = epoch - (epoch % seconds)
    return datetime.fromtimestamp(floored, tz=timezone.utc)


def _signal_key(
    *,
    unit_id: str,
    signal_type: AuthenticitySignalType,
    bucket_started_at: datetime,
) -> str:
    raw = f"{unit_id}:{signal_type.value}:{bucket_started_at.isoformat()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _upsert_signal(
    session: Session,
    *,
    unit: Unit,
    signal_type: AuthenticitySignalType,
    bucket_started_at: datetime,
    window_started_at: datetime,
    window_ended_at: datetime,
    observed_value: int,
    threshold_value: int,
    explanation: str,
) -> AuthenticitySignal:
    key = _signal_key(
        unit_id=str(unit.id),
        signal_type=signal_type,
        bucket_started_at=bucket_started_at,
    )
    existing = session.scalar(
        select(AuthenticitySignal).where(AuthenticitySignal.signal_key == key)
    )

    if existing is not None:
        existing.window_started_at = window_started_at
        existing.window_ended_at = window_ended_at
        existing.observed_value = observed_value
        existing.threshold_value = threshold_value
        existing.explanation = explanation
        session.flush()
        return existing

    signal = AuthenticitySignal(
        organization_id=unit.organization_id,
        unit_id=unit.id,
        signal_key=key,
        signal_type=signal_type,
        window_started_at=window_started_at,
        window_ended_at=window_ended_at,
        observed_value=observed_value,
        threshold_value=threshold_value,
        explanation=explanation,
    )
    session.add(signal)
    session.flush()
    return signal


def evaluate_authenticity_signals(
    session: Session,
    *,
    unit: Unit,
    now: datetime | None = None,
    thresholds: AuthenticityThresholds | None = None,
) -> list[AuthenticitySignal]:
    current = now or datetime.now(timezone.utc)
    policy = thresholds or AuthenticityThresholds()
    created_or_updated: list[AuthenticitySignal] = []

    repeat_window = timedelta(minutes=policy.repeat_scan_window_minutes)
    repeat_start = current - repeat_window
    repeat_count = int(
        session.scalar(
            select(func.count(VerificationEvent.id)).where(
                VerificationEvent.unit_id == unit.id,
                VerificationEvent.created_at >= repeat_start,
                VerificationEvent.created_at <= current,
            )
        )
        or 0
    )

    if repeat_count >= policy.repeat_scan_count:
        bucket = _bucket_start(
            current,
            seconds=policy.repeat_scan_window_minutes * 60,
        )
        created_or_updated.append(
            _upsert_signal(
                session,
                unit=unit,
                signal_type=AuthenticitySignalType.REPEAT_SCAN_BURST,
                bucket_started_at=bucket,
                window_started_at=repeat_start,
                window_ended_at=current,
                observed_value=repeat_count,
                threshold_value=policy.repeat_scan_count,
                explanation=(
                    f"Observed {repeat_count} scans within "
                    f"{policy.repeat_scan_window_minutes} minutes; configured threshold is "
                    f"{policy.repeat_scan_count}. This is an operational anomaly, not proof of counterfeiting."
                ),
            )
        )

    country_window = timedelta(hours=policy.country_window_hours)
    country_start = current - country_window
    country_count = int(
        session.scalar(
            select(func.count(func.distinct(VerificationEvent.country_code))).where(
                VerificationEvent.unit_id == unit.id,
                VerificationEvent.created_at >= country_start,
                VerificationEvent.created_at <= current,
                VerificationEvent.country_code.is_not(None),
            )
        )
        or 0
    )

    if country_count >= policy.country_count:
        bucket = _bucket_start(
            current,
            seconds=policy.country_window_hours * 60 * 60,
        )
        created_or_updated.append(
            _upsert_signal(
                session,
                unit=unit,
                signal_type=AuthenticitySignalType.MULTI_COUNTRY_ACTIVITY,
                bucket_started_at=bucket,
                window_started_at=country_start,
                window_ended_at=current,
                observed_value=country_count,
                threshold_value=policy.country_count,
                explanation=(
                    f"Observed scans from {country_count} countries within "
                    f"{policy.country_window_hours} hours; configured threshold is "
                    f"{policy.country_count}. Location can be affected by travel, VPNs or network routing "
                    "and is not proof of counterfeiting."
                ),
            )
        )

    return created_or_updated
