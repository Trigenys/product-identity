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
