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

    model_config = SettingsConfigDict(
        env_prefix="PRODUCT_IDENTITY_",
        env_file=".env",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
