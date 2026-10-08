from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import database_is_configured, get_db_session

router = APIRouter(tags=["system"])


@router.get("/health", summary="Liveness probe")
def health() -> dict[str, str | bool]:
    settings = get_settings()
    database_ready = database_is_configured()
    return {
        "status": "ok" if database_ready else "degraded",
        "runtime": settings.runtime,
        "database_configured": database_ready,
    }


@router.get("/ready", summary="Database readiness probe")
def ready(session: Session = Depends(get_db_session)) -> dict[str, str | bool]:
    settings = get_settings()
    try:
        session.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database readiness check failed",
        ) from exc

    return {
        "status": "ok",
        "runtime": settings.runtime,
        "database_configured": True,
    }
