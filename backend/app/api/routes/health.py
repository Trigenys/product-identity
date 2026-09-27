from fastapi import APIRouter

from app.core.config import get_settings
from app.db.session import database_is_configured

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
