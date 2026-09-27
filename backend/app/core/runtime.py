import json
from urllib.parse import quote


def _worker_env():
    try:
        from workers import env  # type: ignore
    except ImportError:
        return None
    return env


def _value(env, name: str):
    if env is None:
        return None
    try:
        value = getattr(env, name)
    except Exception:
        return None
    if value is None:
        return None
    return str(value)


def _hyperdrive_database_url(env) -> str | None:
    if env is None:
        return None
    try:
        hd = getattr(env, "HYPERDRIVE")
    except Exception:
        return None

    try:
        user = quote(str(hd.user), safe="")
        password = quote(str(hd.password), safe="")
        host = str(hd.host)
        port = int(hd.port)
        database = quote(str(hd.database), safe="")
    except Exception:
        return None

    return (
        f"postgresql+psycopg://{user}:{password}@{host}:{port}/{database}"
        "?sslmode=disable"
    )


def cloudflare_settings() -> dict[str, object]:
    env = _worker_env()
    if env is None:
        return {}

    names = {
        "environment": "PRODUCT_IDENTITY_ENVIRONMENT",
        "auth_issuer": "PRODUCT_IDENTITY_AUTH_ISSUER",
        "auth_audience": "PRODUCT_IDENTITY_AUTH_AUDIENCE",
        "auth_algorithm": "PRODUCT_IDENTITY_AUTH_ALGORITHM",
        "auth_jwt_key": "PRODUCT_IDENTITY_AUTH_JWT_KEY",
        "verification_token_secret": "PRODUCT_IDENTITY_VERIFICATION_TOKEN_SECRET",
        "public_base_url": "PRODUCT_IDENTITY_PUBLIC_BASE_URL",
        "proof_upload_secret": "PRODUCT_IDENTITY_PROOF_UPLOAD_SECRET",
        "object_storage_bucket": "PRODUCT_IDENTITY_OBJECT_STORAGE_BUCKET",
        "object_storage_region": "PRODUCT_IDENTITY_OBJECT_STORAGE_REGION",
        "object_storage_endpoint_url": "PRODUCT_IDENTITY_OBJECT_STORAGE_ENDPOINT_URL",
        "object_storage_access_key_id": "PRODUCT_IDENTITY_OBJECT_STORAGE_ACCESS_KEY_ID",
        "object_storage_secret_access_key": "PRODUCT_IDENTITY_OBJECT_STORAGE_SECRET_ACCESS_KEY",
        "shopify_client_id": "PRODUCT_IDENTITY_SHOPIFY_CLIENT_ID",
        "shopify_client_secret": "PRODUCT_IDENTITY_SHOPIFY_CLIENT_SECRET",
        "shopify_previous_client_secret": "PRODUCT_IDENTITY_SHOPIFY_PREVIOUS_CLIENT_SECRET",
        "shopify_token_encryption_key": "PRODUCT_IDENTITY_SHOPIFY_TOKEN_ENCRYPTION_KEY",
        "shopify_api_version": "PRODUCT_IDENTITY_SHOPIFY_API_VERSION",
        "shopify_scopes": "PRODUCT_IDENTITY_SHOPIFY_SCOPES",
        "shopify_oauth_callback_url": "PRODUCT_IDENTITY_SHOPIFY_OAUTH_CALLBACK_URL",
        "shopify_after_install_url": "PRODUCT_IDENTITY_SHOPIFY_AFTER_INSTALL_URL",
    }

    values: dict[str, object] = {"runtime": "cloudflare-worker"}
    database_url = _hyperdrive_database_url(env)
    if database_url:
        values["database_url"] = database_url

    for field, binding in names.items():
        value = _value(env, binding)
        if value not in (None, ""):
            values[field] = value

    cors_raw = _value(env, "PRODUCT_IDENTITY_CORS_ORIGINS")
    if cors_raw:
        try:
            parsed = json.loads(cors_raw)
            if isinstance(parsed, list):
                values["cors_origins"] = [str(item) for item in parsed]
        except json.JSONDecodeError:
            values["cors_origins"] = [
                item.strip() for item in cors_raw.split(",") if item.strip()
            ]

    return values
