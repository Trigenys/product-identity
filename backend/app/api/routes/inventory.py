import csv
import html
import io
import uuid
from typing import Annotated

import segno
from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query, status
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.api.deps import get_current_user
from app.api.routes.identity import get_token_factory
from app.core.config import get_settings
from app.db.session import get_db_session
from app.models.auth import MembershipRole, User
from app.models.identity import Product, SerializationBatch, Unit, UnitImport
from app.services.inventory import (
    CsvImportError,
    ImportIdempotencyConflict,
    ImportProductNotFound,
    ImportResult,
    RowError,
    import_serial_csv,
)
from app.services.serialization import VerificationTokenFactory
from app.services.tenancy import TenantAccessDenied, require_membership

router = APIRouter(prefix="/v1/organizations/{organization_id}", tags=["inventory"])


class RowErrorResponse(BaseModel):
    row: int
    serial: str | None
    code: str
    message: str


class ImportedUnitResponse(BaseModel):
    serial: str
    verification_token: str | None


class UnitImportResponse(BaseModel):
    id: str | None
    batch_id: str | None
    status: str
    total_rows: int
    imported_count: int
    rejected_count: int
    replayed: bool
    dry_run: bool
    errors: list[RowErrorResponse]
    units: list[ImportedUnitResponse]


class UnitImportStatusResponse(BaseModel):
    id: str
    batch_id: str | None
    status: str
    total_rows: int
    imported_count: int
    rejected_count: int
    errors: list[RowErrorResponse]


def _require_access(
    session: Session,
    *,
    user: User,
    organization_id: uuid.UUID,
    write: bool,
) -> None:
    allowed_roles = (
        {MembershipRole.OWNER, MembershipRole.ADMIN, MembershipRole.MEMBER}
        if write
        else set(MembershipRole)
    )
    try:
        require_membership(
            session,
            user_id=user.id,
            organization_id=organization_id,
            allowed_roles=allowed_roles,
        )
    except TenantAccessDenied as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Organization access denied",
        ) from exc


def _error_response(error: RowError) -> RowErrorResponse:
    return RowErrorResponse(
        row=error.row,
        serial=error.serial,
        code=error.code,
        message=error.message,
    )


def _import_response(result: ImportResult) -> UnitImportResponse:
    job = result.import_job
    return UnitImportResponse(
        id=str(job.id) if job is not None else None,
        batch_id=str(job.batch_id) if job is not None and job.batch_id is not None else None,
        status=job.status.value if job is not None else "preview",
        total_rows=result.total_rows,
        imported_count=result.imported_count,
        rejected_count=result.rejected_count,
        replayed=result.replayed,
        dry_run=result.dry_run,
        errors=[_error_response(item) for item in result.errors],
        units=[
            ImportedUnitResponse(
                serial=item.unit.serial,
                verification_token=item.verification_token or None,
            )
            for item in result.issued_units
        ],
    )


def _verification_url(unit: Unit, token_factory: VerificationTokenFactory) -> str:
    base_url = get_settings().public_base_url.rstrip("/")
    return f"{base_url}/verify/{token_factory.token_for_unit(unit.id)}"


def _safe_csv_cell(value: str) -> str:
    if value and value[0] in "=+-@":
        return "'" + value
    return value


@router.post(
    "/products/{product_id}/unit-imports",
    response_model=UnitImportResponse,
)
def import_units(
    organization_id: uuid.UUID,
    product_id: uuid.UUID,
    csv_text: Annotated[str, Body(media_type="text/csv")],
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db_session)],
    token_factory: Annotated[VerificationTokenFactory, Depends(get_token_factory)],
    dry_run: bool = Query(default=False),
    idempotency_key: Annotated[
        str | None,
        Header(alias="Idempotency-Key", max_length=200),
    ] = None,
) -> UnitImportResponse:
    _require_access(session, user=user, organization_id=organization_id, write=True)

    try:
        result = import_serial_csv(
            session,
            organization_id=organization_id,
            product_id=product_id,
            csv_text=csv_text,
            token_factory=token_factory,
            dry_run=dry_run,
            idempotency_key=idempotency_key,
        )
        if not dry_run:
            session.commit()
    except ImportProductNotFound as exc:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ImportIdempotencyConflict as exc:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except CsvImportError as exc:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Import conflicted with an existing product identity",
        ) from exc

    return _import_response(result)


@router.get("/unit-imports/{import_id}", response_model=UnitImportStatusResponse)
def import_status(
    organization_id: uuid.UUID,
    import_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> UnitImportStatusResponse:
    _require_access(session, user=user, organization_id=organization_id, write=False)

    job = session.scalar(
        select(UnitImport).where(
            UnitImport.id == import_id,
            UnitImport.organization_id == organization_id,
        )
    )
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Import job not found")

    errors = [
        RowError(**item)
        for item in __import__("json").loads(job.errors_json or "[]")
    ]
    return UnitImportStatusResponse(
        id=str(job.id),
        batch_id=str(job.batch_id) if job.batch_id is not None else None,
        status=job.status.value,
        total_rows=job.total_rows,
        imported_count=job.imported_count,
        rejected_count=job.rejected_count,
        errors=[_error_response(item) for item in errors],
    )


@router.get("/products/{product_id}/units.csv")
def export_units_csv(
    organization_id: uuid.UUID,
    product_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db_session)],
    token_factory: Annotated[VerificationTokenFactory, Depends(get_token_factory)],
) -> Response:
    _require_access(session, user=user, organization_id=organization_id, write=False)

    product = session.scalar(
        select(Product).where(
            Product.id == product_id,
            Product.organization_id == organization_id,
        )
    )
    if product is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")

    units = session.scalars(
        select(Unit)
        .where(
            Unit.organization_id == organization_id,
            Unit.product_id == product_id,
        )
        .order_by(Unit.created_at, Unit.sequence_number)
    ).all()

    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(["serial", "status", "verification_url"])
    for unit in units:
        writer.writerow(
            [
                _safe_csv_cell(unit.serial),
                unit.status.value,
                _verification_url(unit, token_factory),
            ]
        )

    filename = f"{product.sku}-units.csv"
    return Response(
        content=output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/serialization-batches/{batch_id}/labels", response_class=HTMLResponse)
def printable_labels(
    organization_id: uuid.UUID,
    batch_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db_session)],
    token_factory: Annotated[VerificationTokenFactory, Depends(get_token_factory)],
) -> HTMLResponse:
    _require_access(session, user=user, organization_id=organization_id, write=False)

    batch = session.scalar(
        select(SerializationBatch)
        .options(
            selectinload(SerializationBatch.units),
            selectinload(SerializationBatch.product),
        )
        .where(
            SerializationBatch.id == batch_id,
            SerializationBatch.organization_id == organization_id,
        )
    )
    if batch is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Serialization batch not found")

    cards: list[str] = []
    for unit in batch.units:
        url = _verification_url(unit, token_factory)
        qr_data_uri = segno.make(url, error="m").svg_data_uri(scale=3, border=1)
        cards.append(
            '<article class="label">'
            f'<img src="{html.escape(qr_data_uri, quote=True)}" alt="QR code for {html.escape(unit.serial)}">'
            f'<strong>{html.escape(batch.product.name)}</strong>'
            f'<span class="serial">{html.escape(unit.serial)}</span>'
            f'<small>{html.escape(url)}</small>'
            "</article>"
        )

    document = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Product Identity labels</title>
<style>
@page { size: A4; margin: 10mm; }
* { box-sizing: border-box; }
body { margin: 0; font-family: Arial, sans-serif; color: #111; }
header { margin-bottom: 8mm; }
.grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 5mm; }
.label { border: 1px solid #bbb; border-radius: 3mm; padding: 4mm; min-height: 58mm;
         display: flex; flex-direction: column; align-items: center; text-align: center; gap: 1.5mm;
         break-inside: avoid; }
.label img { width: 30mm; height: 30mm; }
.label strong { font-size: 10pt; }
.label .serial { font: 700 9pt monospace; }
.label small { font-size: 5.5pt; overflow-wrap: anywhere; }
@media print { header { display: none; } .label { border-color: #777; } }
</style>
</head>
<body>
<header><h1>Product Identity labels</h1><p>Print at 100% scale on A4.</p></header>
<section class="grid">""" + "".join(cards) + """</section>
</body>
</html>"""

    return HTMLResponse(content=document)
