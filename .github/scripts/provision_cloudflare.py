#!/usr/bin/env python3
"""Provision immutable Cloudflare dependencies and render the Worker config.

Secrets are read only from environment variables. No credential values are
printed or written to GitHub outputs.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://api.cloudflare.com/client/v4"
HYPERDRIVE_NAME = "product-identity-postgres"
WORKER_NAME = "product-identity-api"


class ProvisionError(RuntimeError):
    pass


def required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ProvisionError(f"Missing required environment value: {name}")
    return value


def cloudflare(method: str, path: str, *, body: dict | None = None) -> dict:
    token = required("CLOUDFLARE_API_TOKEN")
    payload = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(
        API + path,
        data=payload,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            **({"Content-Type": "application/json"} if body is not None else {}),
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            parsed = json.load(response)
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode("utf-8"))
        except Exception:
            detail = {"errors": [{"message": f"HTTP {exc.code}"}]}
        messages = "; ".join(
            str(item.get("message", item))
            for item in detail.get("errors", [])
        )
        raise ProvisionError(
            f"Cloudflare API {method} {path} failed: {messages or exc.code}"
        ) from exc

    if not parsed.get("success", False):
        messages = "; ".join(
            str(item.get("message", item))
            for item in parsed.get("errors", [])
        )
        raise ProvisionError(
            f"Cloudflare API {method} {path} failed: {messages or 'unknown error'}"
        )
    return parsed


def parse_database_url() -> dict[str, object]:
    raw = required("NEON_DATABASE_URL")
    parsed = urllib.parse.urlparse(raw)
    if parsed.scheme not in {"postgres", "postgresql"}:
        raise ProvisionError(
            "NEON_DATABASE_URL must use postgres:// or postgresql://"
        )
    if not parsed.hostname or not parsed.username or parsed.password is None:
        raise ProvisionError("NEON_DATABASE_URL is incomplete")
    if "-pooler." in parsed.hostname:
        raise ProvisionError(
            "NEON_DATABASE_URL must be the direct (non-pooled) Neon connection string "
            "because Hyperdrive provides its own pool"
        )

    database = parsed.path.lstrip("/")
    if not database:
        raise ProvisionError("NEON_DATABASE_URL does not contain a database name")

    return {
        "scheme": "postgresql",
        "host": parsed.hostname,
        "port": parsed.port or 5432,
        "database": urllib.parse.unquote(database),
        "user": urllib.parse.unquote(parsed.username),
        "password": urllib.parse.unquote(parsed.password),
    }


def ensure_hyperdrive(account_id: str, origin: dict[str, object]) -> str:
    result = cloudflare(
        "GET",
        f"/accounts/{account_id}/hyperdrive/configs?per_page=100",
    ).get("result", [])

    for config in result:
        if config.get("name") != HYPERDRIVE_NAME:
            continue
        remote = config.get("origin") or {}
        expected = {
            "host": origin["host"],
            "port": origin["port"],
            "database": origin["database"],
            "user": origin["user"],
        }
        actual = {key: remote.get(key) for key in expected}
        if actual != expected:
            raise ProvisionError(
                "Existing product-identity-postgres Hyperdrive points to a "
                "different database. Refusing to replace it automatically."
            )
        return str(config["id"])

    created = cloudflare(
        "POST",
        f"/accounts/{account_id}/hyperdrive/configs",
        body={
            "name": HYPERDRIVE_NAME,
            "origin": origin,
            "mtls": {"sslmode": "require"},
            "caching": {"disabled": True},
        },
    )
    return str(created["result"]["id"])


def discover_worker_url(account_id: str) -> str:
    result = cloudflare(
        "GET",
        f"/accounts/{account_id}/workers/subdomain",
    ).get("result") or {}
    subdomain = str(result.get("subdomain") or "").strip()
    if not subdomain:
        raise ProvisionError(
            "This Cloudflare account has no workers.dev subdomain configured."
        )
    return f"https://{WORKER_NAME}.{subdomain}.workers.dev"


def discover_web_url(account_id: str) -> str:
    explicit = os.environ.get("PRODUCT_IDENTITY_WEB_URL", "").strip()
    if explicit:
        return explicit.rstrip("/")

    project = os.environ.get(
        "CLOUDFLARE_PAGES_PROJECT",
        "product-identity",
    ).strip()
    try:
        result = cloudflare(
            "GET",
            f"/accounts/{account_id}/pages/projects/{urllib.parse.quote(project)}",
        ).get("result") or {}
    except ProvisionError as exc:
        raise ProvisionError(
            f"Could not discover Pages project '{project}'. "
            "Set PRODUCT_IDENTITY_WEB_URL explicitly or give the API token Pages Read."
        ) from exc

    subdomain = str(result.get("subdomain") or "").strip()
    if not subdomain:
        raise ProvisionError(
            f"Pages project '{project}' did not return a subdomain."
        )
    return f"https://{subdomain}"


def render_config(
    *,
    web_url: str,
    api_url: str,
    hyperdrive_id: str,
    shopify_client_id: str,
) -> None:
    template_path = Path("backend/wrangler.production.toml.template")
    output_path = Path("backend/wrangler.production.toml")
    rendered = (
        template_path.read_text(encoding="utf-8")
        .replace("__WEB_URL__", web_url)
        .replace("__API_URL__", api_url)
        .replace("__HYPERDRIVE_ID__", hyperdrive_id)
        .replace("__SHOPIFY_CLIENT_ID__", shopify_client_id)
    )
    output_path.write_text(rendered, encoding="utf-8")


def github_output(name: str, value: str) -> None:
    target = os.environ.get("GITHUB_OUTPUT")
    if not target:
        return
    with open(target, "a", encoding="utf-8") as handle:
        handle.write(f"{name}={value}\n")


def main() -> int:
    account_id = required("CLOUDFLARE_ACCOUNT_ID")
    shopify_client_id = required("SHOPIFY_CLIENT_ID")
    origin = parse_database_url()

    hyperdrive_id = ensure_hyperdrive(account_id, origin)
    api_url = discover_worker_url(account_id)
    web_url = discover_web_url(account_id)

    render_config(
        web_url=web_url,
        api_url=api_url,
        hyperdrive_id=hyperdrive_id,
        shopify_client_id=shopify_client_id,
    )

    github_output("hyperdrive_id", hyperdrive_id)
    github_output("api_url", api_url)
    github_output("web_url", web_url)

    print("Cloudflare production configuration rendered.")
    print(f"Worker URL: {api_url}")
    print(f"Web URL: {web_url}")
    print(f"Hyperdrive: {HYPERDRIVE_NAME} ({hyperdrive_id})")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ProvisionError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        raise SystemExit(1)
