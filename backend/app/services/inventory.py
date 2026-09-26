import csv
import hashlib
import io
import json
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.identity import Product, SerializationBatch, Unit, UnitImport, UnitImportStatus
from app.services.serialization import IssuedUnit, VerificationTokenFactory

MAX_IMPORT_ROWS = 5000


class CsvImportError(ValueError):
    pass


class ImportIdempotencyConflict(Exception):
    pass


class ImportProductNotFound(Exception):
    pass


@dataclass(frozen=True)
class RowError:
    row: int
    serial: str | None
    code: str
    message: str


@dataclass(frozen=True)
class ImportResult:
    import_job: UnitImport | None
    issued_units: list[IssuedUnit]
    errors: list[RowError]
    total_rows: int
    replayed: bool
    dry_run: bool

    @property
    def imported_count(self) -> int:
        return len(self.issued_units)

    @property
    def rejected_count(self) -> int:
        return len(self.errors)


def _fingerprint(product_id: uuid.UUID, csv_text: str) -> str:
    digest = hashlib.sha256()
    digest.update(str(product_id).encode("ascii"))
    digest.update(b"\0")
    digest.update(csv_text.encode("utf-8"))
    return digest.hexdigest()


def _parse_csv(csv_text: str) -> tuple[list[tuple[int, str]], list[RowError], int]:
    if not csv_text.strip():
        raise CsvImportError("CSV payload is empty")

    reader = csv.DictReader(io.StringIO(csv_text))
    headers = [header.strip().lower() for header in (reader.fieldnames or []) if header]
    if "serial" not in headers:
        raise CsvImportError("CSV must contain a 'serial' header")

    serial_header = next(
        header for header in (reader.fieldnames or []) if header and header.strip().lower() == "serial"
    )

    candidates: list[tuple[int, str]] = []
    errors: list[RowError] = []
    seen: set[str] = set()
    total_rows = 0

    for row_number, row in enumerate(reader, start=2):
        total_rows += 1
        if total_rows > MAX_IMPORT_ROWS:
            raise CsvImportError(f"CSV import is limited to {MAX_IMPORT_ROWS} data rows")

        raw_serial = row.get(serial_header)
        serial = raw_serial.strip() if raw_serial is not None else ""

        if not serial:
            errors.append(RowError(row_number, None, "missing_serial", "Serial is required"))
            continue
        if len(serial) > 120:
            errors.append(RowError(row_number, serial[:120], "serial_too_long", "Serial exceeds 120 characters"))
            continue
        if any(ord(char) < 32 for char in serial):
            errors.append(RowError(row_number, serial, "invalid_serial", "Serial contains control characters"))
            continue
        if serial in seen:
            errors.append(RowError(row_number, serial, "duplicate_in_file", "Serial is duplicated in this CSV"))
            continue

        seen.add(serial)
        candidates.append((row_number, serial))

    return candidates, errors, total_rows


def _deserialize_errors(value: str) -> list[RowError]:
    return [RowError(**item) for item in json.loads(value or "[]")]


def import_serial_csv(
    session: Session,
    *,
    organization_id: uuid.UUID,
    product_id: uuid.UUID,
    csv_text: str,
    token_factory: VerificationTokenFactory,
    dry_run: bool,
    idempotency_key: str | None = None,
) -> ImportResult:
    fingerprint = _fingerprint(product_id, csv_text)

    if not dry_run:
        clean_key = (idempotency_key or "").strip()
        if not clean_key or len(clean_key) > 200:
            raise CsvImportError("Idempotency-Key is required and must be at most 200 characters")

        existing_import = session.scalar(
            select(UnitImport).where(
                UnitImport.organization_id == organization_id,
                UnitImport.idempotency_key == clean_key,
            )
        )
        if existing_import is not None:
            if existing_import.request_fingerprint != fingerprint:
                raise ImportIdempotencyConflict(
                    "Idempotency key was already used with a different CSV payload"
                )
            units = (
                session.scalars(
                    select(Unit)
                    .where(Unit.batch_id == existing_import.batch_id)
                    .order_by(Unit.sequence_number)
                ).all()
                if existing_import.batch_id is not None
                else []
            )
            return ImportResult(
                import_job=existing_import,
                issued_units=[
                    IssuedUnit(unit=unit, verification_token=token_factory.token_for_unit(unit.id))
                    for unit in units
                ],
                errors=_deserialize_errors(existing_import.errors_json),
                total_rows=existing_import.total_rows,
                replayed=True,
                dry_run=False,
            )
    else:
        clean_key = ""

    product = session.scalar(
        select(Product).where(
            Product.id == product_id,
            Product.organization_id == organization_id,
        )
    )
    if product is None:
        raise ImportProductNotFound("Product does not exist in this organization")

    candidates, errors, total_rows = _parse_csv(csv_text)
    serials = [serial for _, serial in candidates]
    existing_serials = set(
        session.scalars(
            select(Unit.serial).where(
                Unit.organization_id == organization_id,
                Unit.serial.in_(serials),
            )
        ).all()
    ) if serials else set()

    accepted: list[tuple[int, str]] = []
    for row_number, serial in candidates:
        if serial in existing_serials:
            errors.append(
                RowError(row_number, serial, "already_exists", "Serial already exists in this organization")
            )
        else:
            accepted.append((row_number, serial))

    errors.sort(key=lambda item: item.row)

    if dry_run:
        preview = [
            IssuedUnit(
                unit=Unit(
                    id=uuid.uuid4(),
                    organization_id=organization_id,
                    product_id=product_id,
                    batch_id=uuid.uuid4(),
                    sequence_number=index,
                    serial=serial,
                    verification_token_digest="preview",
                ),
                verification_token="",
            )
            for index, (_, serial) in enumerate(accepted, start=1)
        ]
        return ImportResult(
            import_job=None,
            issued_units=preview,
            errors=errors,
            total_rows=total_rows,
            replayed=False,
            dry_run=True,
        )

    batch: SerializationBatch | None = None
    issued_units: list[IssuedUnit] = []

    if accepted:
        batch = SerializationBatch(
            organization_id=organization_id,
            product_id=product_id,
            idempotency_key=f"csv:{uuid.uuid4().hex}",
            request_fingerprint=fingerprint,
            quantity=len(accepted),
            prefix=None,
        )
        session.add(batch)
        session.flush()

        for sequence_number, (_, serial) in enumerate(accepted, start=1):
            unit_id = uuid.uuid4()
            token = token_factory.token_for_unit(unit_id)
            unit = Unit(
                id=unit_id,
                organization_id=organization_id,
                product_id=product_id,
                batch_id=batch.id,
                sequence_number=sequence_number,
                serial=serial,
                verification_token_digest=token_factory.digest(token),
            )
            session.add(unit)
            issued_units.append(IssuedUnit(unit=unit, verification_token=token))

    now = datetime.now(timezone.utc)
    import_job = UnitImport(
        organization_id=organization_id,
        product_id=product_id,
        batch_id=batch.id if batch is not None else None,
        idempotency_key=clean_key,
        request_fingerprint=fingerprint,
        status=UnitImportStatus.COMPLETED,
        total_rows=total_rows,
        imported_count=len(issued_units),
        rejected_count=len(errors),
        errors_json=json.dumps([asdict(error) for error in errors], separators=(",", ":")),
        completed_at=now,
    )
    session.add(import_job)
    session.flush()

    return ImportResult(
        import_job=import_job,
        issued_units=issued_units,
        errors=errors,
        total_rows=total_rows,
        replayed=False,
        dry_run=False,
    )
