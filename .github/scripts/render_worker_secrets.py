#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import secrets
import sys
from pathlib import Path

from cryptography.fernet import Fernet


def existing_names(path: Path) -> set[str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return set()
    if not isinstance(data, list):
        return set()
    return {
        str(item.get("name"))
        for item in data
        if isinstance(item, dict) and item.get("name")
    }


def env(name: str) -> str:
    return os.environ.get(name, "").strip()


def main() -> int:
    if len(sys.argv) != 3:
        raise SystemExit(
            "usage: render_worker_secrets.py <existing-secret-list.json> <output.json>"
        )

    existing = existing_names(Path(sys.argv[1]))
    output = Path(sys.argv[2])
    values: dict[str, str] = {}

    shopify_secret = env("SHOPIFY_CLIENT_SECRET")
    if not shopify_secret:
        raise SystemExit("SHOPIFY_CLIENT_SECRET is required")
    values["PRODUCT_IDENTITY_SHOPIFY_CLIENT_SECRET"] = shopify_secret

    previous = env("SHOPIFY_PREVIOUS_CLIENT_SECRET")
    if previous:
        values["PRODUCT_IDENTITY_SHOPIFY_PREVIOUS_CLIENT_SECRET"] = previous

    if "PRODUCT_IDENTITY_SHOPIFY_TOKEN_ENCRYPTION_KEY" not in existing:
        values["PRODUCT_IDENTITY_SHOPIFY_TOKEN_ENCRYPTION_KEY"] = (
            Fernet.generate_key().decode("ascii")
        )

    if "PRODUCT_IDENTITY_VERIFICATION_TOKEN_SECRET" not in existing:
        values["PRODUCT_IDENTITY_VERIFICATION_TOKEN_SECRET"] = (
            secrets.token_urlsafe(48)
        )

    if "PRODUCT_IDENTITY_PROOF_UPLOAD_SECRET" not in existing:
        values["PRODUCT_IDENTITY_PROOF_UPLOAD_SECRET"] = secrets.token_urlsafe(48)

    auth_jwt_key = env("PRODUCT_IDENTITY_AUTH_JWT_KEY")
    if auth_jwt_key:
        values["PRODUCT_IDENTITY_AUTH_JWT_KEY"] = auth_jwt_key

    # Omitted remote secrets are preserved by Wrangler. This makes generated
    # encryption/signing keys stable across deployments.
    output.write_text(json.dumps(values), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
