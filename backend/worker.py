from workers import Response, WorkerEntrypoint

_app = None
_request_lock = None


def _install_cloudflare_sync_compat() -> None:
    """Run FastAPI sync callables inline because Python Workers have no threads."""
    import sys

    if sys.platform != "emscripten":
        return

    import anyio.to_thread

    async def run_sync_inline(
        func,
        *args,
        abandon_on_cancel=False,
        cancellable=None,
        limiter=None,
    ):
        del abandon_on_cancel, cancellable, limiter
        return func(*args)

    anyio.to_thread.run_sync = run_sync_inline


def _runtime(env):
    global _app, _request_lock

    if _app is None:
        # Cloudflare snapshots Python Workers while evaluating top-level imports.
        # Import the ASGI application only after a real request starts so
        # dependency initialization that needs entropy cannot poison the snapshot.
        import asyncio

        _install_cloudflare_sync_compat()

        # Cloudflare exposes vars, secrets and bindings through WorkerEntrypoint.env.
        # Bind that explicit request-time environment before importing FastAPI so
        # cached settings and the SQLAlchemy engine see the Hyperdrive binding.
        from app.core.runtime import install_worker_env

        install_worker_env(env)
        from app.main import app

        _app = app
        _request_lock = asyncio.Lock()

    return _app, _request_lock


class Default(WorkerEntrypoint):
    async def fetch(self, request):
        health_request = str(request.url).split("?", 1)[0].endswith("/health")

        try:
            # Cloudflare's ASGI bridge is runtime-provided. The documented
            # WorkerEntrypoint contract passes the underlying JS Request object.
            import asgi

            app, request_lock = _runtime(self.env)

            # Product Identity currently uses synchronous SQLAlchemy. Serialize
            # synchronous DB access while Hyperdrive owns connection pooling.
            async with request_lock:
                return await asgi.fetch(app, request.js_object, self.env)
        except Exception as exc:
            # Keep readiness diagnostics machine-readable while runtime
            # compatibility is being hardened. AppFactory rejects
            # status=degraded, so this cannot produce a false-green release.
            if health_request:
                return Response.json(
                    {
                        "status": "degraded",
                        "runtime": "cloudflare-worker",
                        "database_configured": hasattr(self.env, "HYPERDRIVE"),
                        "runtime_error_type": (
                            f"{type(exc).__module__}.{type(exc).__name__}"
                        ),
                        "runtime_error": str(exc)[:400],
                    }
                )
            raise
