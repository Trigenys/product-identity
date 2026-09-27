from typing import Annotated

from fastapi import Depends, HTTPException, status

from app.core.config import Settings, get_settings
from app.integrations.shopify.client import HttpShopifyAdminClient, ShopifyAdminClient
from app.integrations.shopify.crypto import TokenCipher, TokenEncryptionError


def get_shopify_admin_client(
    settings: Annotated[Settings, Depends(get_settings)],
) -> ShopifyAdminClient:
    if not settings.shopify_client_id or not settings.shopify_client_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Shopify connector is not configured",
        )
    return HttpShopifyAdminClient(
        client_id=settings.shopify_client_id,
        client_secret=settings.shopify_client_secret,
        api_version=settings.shopify_api_version,
        timeout_seconds=settings.shopify_http_timeout_seconds,
    )


def get_shopify_token_cipher(
    settings: Annotated[Settings, Depends(get_settings)],
) -> TokenCipher:
    try:
        return TokenCipher(settings.shopify_token_encryption_key)
    except TokenEncryptionError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Shopify token encryption is not configured",
        ) from exc
