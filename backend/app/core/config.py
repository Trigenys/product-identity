from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Product Identity API"
    environment: str = "development"
    database_url: str = "sqlite:///./product_identity.db"

    auth_issuer: str = "https://auth.example.invalid/"
    auth_audience: str = "product-identity-api"
    auth_algorithm: str = "RS256"
    auth_jwt_key: str = Field(default="")

    verification_token_secret: str = Field(default="")
    public_base_url: str = "http://localhost:5173"
    cors_origins: list[str] = ["http://localhost:5173"]

    proof_upload_secret: str = Field(default="")
    proof_max_bytes: int = 8 * 1024 * 1024
    proof_retention_days: int = 730
    proof_download_ttl_seconds: int = 300

    object_storage_bucket: str = ""
    object_storage_region: str = "auto"
    object_storage_endpoint_url: str | None = None
    object_storage_access_key_id: str = ""
    object_storage_secret_access_key: str = ""

    verification_repeat_scan_threshold: int = 6
    verification_repeat_scan_window_minutes: int = 10
    verification_country_threshold: int = 2
    verification_country_window_hours: int = 24
    verification_trust_edge_country: bool = False
    verification_country_header: str = "cf-ipcountry"

    shopify_client_id: str = ""
    shopify_client_secret: str = Field(default="")
    shopify_previous_client_secret: str = Field(default="")
    shopify_token_encryption_key: str = Field(default="")
    shopify_api_version: str = "2026-07"
    shopify_scopes: str = "read_products,read_orders"
    shopify_oauth_callback_url: str = "http://localhost:8000/v1/integrations/shopify/oauth/callback"
    shopify_after_install_url: str = "http://localhost:5173/app"
    shopify_http_timeout_seconds: float = 20.0

    model_config = SettingsConfigDict(
        env_prefix="PRODUCT_IDENTITY_",
        env_file=".env",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
