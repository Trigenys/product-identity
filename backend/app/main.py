from fastapi import FastAPI

from app.api.routes.health import router as health_router
from app.api.routes.identity import router as identity_router
from app.api.routes.inventory import router as inventory_router
from app.api.routes.me import router as me_router
from app.core.config import get_settings

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
)

app.include_router(health_router)
app.include_router(me_router)
app.include_router(identity_router)
app.include_router(inventory_router)
