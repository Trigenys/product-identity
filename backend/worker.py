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


def _bind_worker_env(env) -> None:
    from app.core.runtime import install_worker_env

    install_worker_env(env)


def _runtime(env):
    global _app, _request_lock

    if _app is None:
        # Cloudflare snapshots Python Workers while evaluating top-level imports.
        # Import the ASGI application only after a real request starts so
        # dependency initialization that needs entropy cannot poison the snapshot.
        import asyncio

        _install_cloudflare_sync_compat()
        _bind_worker_env(env)

        from app.main import app

        _app = app
        _request_lock = asyncio.Lock()

    return _app, _request_lock


def _probe_error(stage: str, env, exc: BaseException):
    return Response.json(
        {
            "status": "degraded",
            "runtime": "cloudflare-worker",
            "database_configured": hasattr(env, "HYPERDRIVE"),
            "probe_stage": stage,
            "probe_ok": False,
            "runtime_error_type": f"{type(exc).__module__}.{type(exc).__name__}",
            "runtime_error": str(exc)[:400],
        }
    )


def _runtime_probe(stage: str, env):
    """Fail-closed, non-secret probe for isolating Python Worker bootstrap failures."""
    result = {
        "status": "degraded",
        "runtime": "cloudflare-worker",
        "database_configured": hasattr(env, "HYPERDRIVE"),
        "probe_stage": stage,
        "probe_ok": True,
    }

    try:
        if stage == "entrypoint":
            return Response.json(result)

        _install_cloudflare_sync_compat()
        _bind_worker_env(env)

        if stage == "runtime":
            return Response.json(result)

        if stage == "settings":
            from app.core.config import get_settings

            get_settings.cache_clear()
            settings = get_settings()
            result["settings_runtime"] = settings.runtime
            result["settings_environment"] = settings.environment
            result["settings_database_postgres"] = settings.database_url.startswith(
                "postgresql"
            )
            return Response.json(result)

        if stage in {"db", "db-connect"}:
            from app.db import session as db_session

            result["db_configured"] = db_session.database_is_configured()
            if stage == "db-connect":
                with db_session.engine.connect() as connection:
                    result["db_select_one"] = connection.exec_driver_sql(
                        "SELECT 1"
                    ).scalar_one() == 1
            return Response.json(result)

        if stage == "app":
            from app.main import app as probe_app

            result["app_loaded"] = probe_app is not None
            return Response.json(result)

        result["probe_ok"] = False
        result["runtime_error_type"] = "builtins.ValueError"
        result["runtime_error"] = "Unknown runtime probe stage"
        return Response.json(result, status=404)
    except BaseException as exc:
        return _probe_error(stage, env, exc)


class Default(WorkerEntrypoint):
    async def fetch(self, request):
        try:
            request_url = str(request.url).split("?", 1)[0]
            health_request = request_url.endswith("/health")
            probe_prefix = "/_appfactory/runtime-probe/"
            if probe_prefix in request_url:
                stage = request_url.rsplit(probe_prefix, 1)[1].strip("/")
                return _runtime_probe(stage, self.env)

            # Keep the production readiness endpoint fail-closed while the
            # request-time bootstrap is isolated. This proves the entrypoint and
            # binding boundary without claiming the application is ready.
            if health_request:
                return Response.json(
                    {
                        "status": "degraded",
                        "runtime": "cloudflare-worker",
                        "database_configured": hasattr(self.env, "HYPERDRIVE"),
                        "probe_stage": "entrypoint",
                        "probe_ok": True,
                    }
                )

            # Cloudflare's ASGI bridge is runtime-provided. The documented
            # WorkerEntrypoint contract passes the underlying JS Request object.
            import asgi

            app, request_lock = _runtime(self.env)

            # Product Identity currently uses synchronous SQLAlchemy. Serialize
            # synchronous DB access while Hyperdrive owns connection pooling.
            async with request_lock:
                return await asgi.fetch(app, request.js_object, self.env)
        except BaseException as exc:
            if "health_request" in locals() and health_request:
                return _probe_error("asgi", self.env, exc)
            raise
