import asyncio

from fastapi.responses import RedirectResponse
from workers import WorkerEntrypoint, asgi

from app.core.config import get_settings
from app.main import app

_worker_request_lock = asyncio.Lock()


@app.get("/", include_in_schema=False)
async def worker_root():
    settings = get_settings()
    destination = settings.public_base_url.rstrip("/") + "/app"
    return RedirectResponse(destination, status_code=307)


class Default(WorkerEntrypoint):
    async def fetch(self, request):
        # Product Identity currently uses synchronous SQLAlchemy. Cloudflare's
        # Python runtime recommends serializing synchronous DB access. Hyperdrive
        # still owns the actual connection pooling underneath.
        async with _worker_request_lock:
            return await asgi.fetch(app, request, self.env)
