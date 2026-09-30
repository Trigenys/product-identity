from workers import WorkerEntrypoint

_app = None
_request_lock = None


def _runtime():
    global _app, _request_lock

    if _app is None:
        # Cloudflare snapshots Python Workers while evaluating top-level imports.
        # Import the ASGI application only after a real request starts so
        # dependency initialization that needs entropy cannot poison the snapshot.
        import asyncio

        from app.main import app

        _app = app
        _request_lock = asyncio.Lock()

    return _app, _request_lock


class Default(WorkerEntrypoint):
    async def fetch(self, request):
        # The ASGI adapter is runtime-provided and intentionally imported after startup.
        from workers import asgi

        app, request_lock = _runtime()

        # Product Identity currently uses synchronous SQLAlchemy. Serialize
        # synchronous DB access while Hyperdrive owns connection pooling.
        async with request_lock:
            return await asgi.fetch(app, request, self.env)
