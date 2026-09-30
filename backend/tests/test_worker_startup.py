import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _top_level_imports(relative_path: str) -> set[str]:
    tree = ast.parse((ROOT / relative_path).read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def test_worker_startup_does_not_import_entropy_backed_crypto_modules() -> None:
    security_imports = _top_level_imports("app/core/security.py")
    shopify_crypto_imports = _top_level_imports("app/integrations/shopify/crypto.py")

    assert "jwt" not in security_imports
    assert "cryptography.fernet" not in shopify_crypto_imports


def test_cloudflare_entropy_patch_toolchain_is_pinned() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    package_script = (ROOT / "scripts/package_worker.sh").read_text(encoding="utf-8")
    production_config = (ROOT / "wrangler.production.toml").read_text(encoding="utf-8")

    assert "workers-py==1.17.5" in pyproject
    assert "workers-runtime-sdk==1.9.1" in pyproject
    assert 'workers-py==1.17.5' in package_script
    assert 'workers-runtime-sdk==1.9.1' in package_script
    assert "python_process_pth_files" in production_config


def test_worker_entrypoint_defers_application_imports_until_fetch() -> None:
    worker_path = ROOT / "worker.py"
    tree = ast.parse(worker_path.read_text(encoding="utf-8"))

    top_level_modules: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            top_level_modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            top_level_modules.add(node.module)

    assert top_level_modules == {"workers"}

    source = worker_path.read_text(encoding="utf-8")
    assert "from app.main import app" in source
    assert "import asgi" in source
    assert "from workers import Response, WorkerEntrypoint" in source


def test_worker_runs_fastapi_sync_callables_inline_on_emscripten() -> None:
    source = (ROOT / "worker.py").read_text(encoding="utf-8")

    assert 'sys.platform != "emscripten"' in source
    assert "import anyio.to_thread" in source
    assert "async def run_sync_inline(" in source
    assert "anyio.to_thread.run_sync = run_sync_inline" in source
    assert source.index("_install_cloudflare_sync_compat()") < source.index(
        "from app.main import app"
    )


def test_worker_uses_cloudflare_asgi_request_and_env_contract() -> None:
    source = (ROOT / "worker.py").read_text(encoding="utf-8")

    assert "_runtime(self.env)" in source
    assert "install_worker_env(env)" in source
    assert "return await asgi.fetch(app, request.js_object, self.env)" in source


def test_worker_health_diagnostics_cover_asgi_request_failures() -> None:
    source = (ROOT / "worker.py").read_text(encoding="utf-8")

    assert "return await asgi.fetch(app, request.js_object, self.env)" in source
    assert '"runtime_error_type"' in source
    assert '"runtime_error"' in source


def test_cloudflare_runtime_reads_explicit_worker_entrypoint_env() -> None:
    from app.core import runtime

    class Hyperdrive:
        user = "product identity"
        password = "p@ss/word"
        host = "hyperdrive.internal"
        port = "5432"
        database = "identity db"

    class WorkerEnv:
        HYPERDRIVE = Hyperdrive()
        PRODUCT_IDENTITY_ENVIRONMENT = "production"
        PRODUCT_IDENTITY_PUBLIC_BASE_URL = "https://example.test"
        PRODUCT_IDENTITY_CORS_ORIGINS = '["https://example.test"]'

    runtime.install_worker_env(WorkerEnv())
    try:
        values = runtime.cloudflare_settings()
    finally:
        runtime.install_worker_env(None)

    assert values["runtime"] == "cloudflare-worker"
    assert values["environment"] == "production"
    assert values["public_base_url"] == "https://example.test"
    assert values["cors_origins"] == ["https://example.test"]
    assert values["database_url"] == (
        "postgresql+psycopg://product%20identity:p%40ss%2Fword"
        "@hyperdrive.internal:5432/identity%20db?sslmode=disable"
    )


def test_rate_limiter_does_not_import_threading_at_worker_startup() -> None:
    imports = _top_level_imports("app/services/rate_limit.py")
    source = (ROOT / "app/services/rate_limit.py").read_text(encoding="utf-8")

    assert "threading" not in imports
    assert 'sys.platform == "emscripten"' in source
    assert "nullcontext()" in source


def test_worker_runtime_probe_is_fail_closed_and_non_secret() -> None:
    source = (ROOT / "worker.py").read_text(encoding="utf-8")

    assert 'probe_prefix = "/_appfactory/runtime-probe/"' in source
    assert '"status": "degraded"' in source
    assert '"probe_stage"' in source
    assert '"probe_ok"' in source
    assert 'stage in {"db", "db-connect"}' in source
    assert '"SELECT 1"' in source
    probe_source = source[source.index("def _runtime_probe"):source.index("class Default")]
    assert "password" not in probe_source
