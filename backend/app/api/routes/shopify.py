import json
import uuid
from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.shopify_deps import get_shopify_admin_client, get_shopify_token_cipher
from app.core.config import Settings, get_settings
from app.db.session import get_db_session
from app.integrations.shopify.client import ShopifyAdminClient, ShopifyTransportError
from app.integrations.shopify.crypto import TokenCipher
from app.integrations.shopify.oauth import (
    ShopifyOAuthError,
    callback_hmac_is_valid,
    consume_oauth_state,
    create_oauth_start,
    normalize_shop_domain,
)
from app.integrations.shopify.service import (
    ShopifyConnectorError,
    apply_order_webhook,
    apply_product_webhook,
    payload_digest,
    redact_shop_connector_data,
    store_installation_tokens,
    sync_products,
    uninstall_shop,
)
from app.integrations.shopify.webhooks import verify_webhook_hmac
from app.models.auth import MembershipRole, User
from app.models.shopify import (
    ShopifyInstallation,
    ShopifyInstallationStatus,
    ShopifyWebhookDelivery,
    ShopifyWebhookStatus,
)
from app.services.tenancy import TenantAccessDenied, require_membership

router = APIRouter(tags=["shopify"])


class ShopifyInstallationResponse(dict):
    pass


def _require_manage_access(
    session: Session,
    *,
    user: User,
    organization_id: uuid.UUID,
) -> None:
    try:
        require_membership(
            session,
            user_id=user.id,
            organization_id=organization_id,
            allowed_roles={MembershipRole.OWNER, MembershipRole.ADMIN},
        )
    except TenantAccessDenied as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Organization access denied",
        ) from exc


def _installation_payload(installation: ShopifyInstallation) -> dict[str, object]:
    return {
        "id": str(installation.id),
        "organization_id": str(installation.organization_id),
        "shop_domain": installation.shop_domain,
        "scopes": sorted(filter(None, installation.scopes.split(","))),
        "status": installation.status.value,
        "installed_at": installation.installed_at.isoformat(),
        "uninstalled_at": (
            installation.uninstalled_at.isoformat()
            if installation.uninstalled_at
            else None
        ),
        "last_synced_at": (
            installation.last_synced_at.isoformat()
            if installation.last_synced_at
            else None
        ),
    }


@router.get("/v1/organizations/{organization_id}/integrations/shopify/install")
def install_shopify(
    organization_id: uuid.UUID,
    shop: str = Query(min_length=1, max_length=255),
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> RedirectResponse:
    _require_manage_access(
        session,
        user=user,
        organization_id=organization_id,
    )
    try:
        start = create_oauth_start(
            session,
            organization_id=organization_id,
            shop_domain=shop,
            client_id=settings.shopify_client_id,
            scopes=settings.shopify_scopes,
            redirect_uri=settings.shopify_oauth_callback_url,
        )
        session.commit()
    except ShopifyOAuthError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc

    return RedirectResponse(
        start.authorization_url,
        status_code=status.HTTP_307_TEMPORARY_REDIRECT,
    )


@router.get("/v1/integrations/shopify/oauth/callback")
def shopify_oauth_callback(
    request: Request,
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
    shopify_client: ShopifyAdminClient = Depends(get_shopify_admin_client),
    cipher: TokenCipher = Depends(get_shopify_token_cipher),
) -> RedirectResponse:
    params = {key: value for key, value in request.query_params.items()}
    shop = params.get("shop", "")
    code = params.get("code", "")
    state_value = params.get("state", "")

    if not code or not state_value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Shopify OAuth callback is incomplete",
        )

    if not callback_hmac_is_valid(params, client_secret=settings.shopify_client_secret):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Shopify OAuth callback signature is invalid",
        )

    try:
        normalized_shop = normalize_shop_domain(shop)
        oauth_state = consume_oauth_state(
            session,
            shop_domain=normalized_shop,
            state=state_value,
        )
        token_response = shopify_client.exchange_code(
            shop=normalized_shop,
            code=code,
        )

        required_scopes = {
            scope.strip()
            for scope in settings.shopify_scopes.split(",")
            if scope.strip()
        }
        granted_scopes = {
            scope.strip()
            for scope in token_response.scope.split(",")
            if scope.strip()
        }
        if not required_scopes.issubset(granted_scopes):
            raise ShopifyConnectorError(
                "Shopify did not grant all required scopes"
            )

        installation = store_installation_tokens(
            session,
            organization_id=oauth_state.organization_id,
            shop_domain=normalized_shop,
            token_response=token_response,
            cipher=cipher,
        )
        session.commit()
    except (ShopifyOAuthError, ShopifyConnectorError, ShopifyTransportError) as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    destination = settings.shopify_after_install_url
    separator = "&" if "?" in destination else "?"
    query = urlencode(
        {
            "shopify": "connected",
            "organization_id": str(installation.organization_id),
        }
    )
    return RedirectResponse(f"{destination}{separator}{query}", status_code=303)


@router.get("/v1/organizations/{organization_id}/integrations/shopify")
def shopify_status(
    organization_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> dict[str, object]:
    _require_manage_access(
        session,
        user=user,
        organization_id=organization_id,
    )
    installation = session.scalar(
        select(ShopifyInstallation).where(
            ShopifyInstallation.organization_id == organization_id
        )
    )
    if installation is None:
        return {"connected": False}
    return {
        "connected": installation.status == ShopifyInstallationStatus.ACTIVE,
        "installation": _installation_payload(installation),
    }


@router.post("/v1/organizations/{organization_id}/integrations/shopify/sync")
def shopify_sync(
    organization_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db_session),
    shopify_client: ShopifyAdminClient = Depends(get_shopify_admin_client),
    cipher: TokenCipher = Depends(get_shopify_token_cipher),
) -> dict[str, object]:
    _require_manage_access(
        session,
        user=user,
        organization_id=organization_id,
    )
    installation = session.scalar(
        select(ShopifyInstallation).where(
            ShopifyInstallation.organization_id == organization_id
        )
    )
    if installation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Shopify is not connected to this organization",
        )

    try:
        mapped = sync_products(
            session,
            installation=installation,
            client=shopify_client,
            cipher=cipher,
        )
        session.commit()
    except (ShopifyConnectorError, ShopifyTransportError) as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc

    return {
        "shop_domain": installation.shop_domain,
        "mapped_variants": mapped,
        "last_synced_at": installation.last_synced_at.isoformat(),
    }


@router.post("/v1/integrations/shopify/webhooks")
async def shopify_webhook(
    request: Request,
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> dict[str, object]:
    raw_body = await request.body()
    provided_hmac = request.headers.get("x-shopify-hmac-sha256", "")
    topic = request.headers.get("x-shopify-topic", "").strip().lower()
    webhook_id = request.headers.get("x-shopify-webhook-id", "").strip()
    event_id = request.headers.get("x-shopify-event-id", "").strip() or None
    raw_shop = request.headers.get("x-shopify-shop-domain", "").strip()

    secrets = [
        settings.shopify_client_secret,
        settings.shopify_previous_client_secret,
    ]
    if not verify_webhook_hmac(
        raw_body,
        provided_hmac=provided_hmac,
        client_secrets=secrets,
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Shopify webhook signature is invalid",
        )

    if not topic or not webhook_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Shopify webhook headers are incomplete",
        )

    try:
        shop = normalize_shop_domain(raw_shop)
    except ShopifyOAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    duplicate = session.scalar(
        select(ShopifyWebhookDelivery).where(
            ShopifyWebhookDelivery.webhook_id == webhook_id
        )
    )
    if duplicate is not None:
        return {"accepted": True, "duplicate": True}

    installation = session.scalar(
        select(ShopifyInstallation).where(
            ShopifyInstallation.shop_domain == shop
        )
    )
    delivery = ShopifyWebhookDelivery(
        installation_id=installation.id if installation else None,
        shop_domain=shop,
        webhook_id=webhook_id,
        event_id=event_id,
        topic=topic,
        payload_sha256=payload_digest(raw_body),
        status=ShopifyWebhookStatus.RECEIVED,
    )
    session.add(delivery)

    try:
        payload = json.loads(raw_body.decode("utf-8")) if raw_body else {}

        if topic == "shop/redact":
            if installation is not None:
                redact_shop_connector_data(
                    session,
                    installation=installation,
                )
            else:
                session.delete(delivery)
            session.commit()
            return {"accepted": True, "duplicate": False}

        if installation is None:
            delivery.status = ShopifyWebhookStatus.IGNORED
        elif topic in {"products/create", "products/update"}:
            apply_product_webhook(
                session,
                installation=installation,
                payload=payload,
            )
            delivery.status = ShopifyWebhookStatus.PROCESSED
        elif topic == "products/delete":
            apply_product_webhook(
                session,
                installation=installation,
                payload=payload,
                deleted=True,
            )
            delivery.status = ShopifyWebhookStatus.PROCESSED
        elif topic in {"orders/create", "orders/updated", "orders/cancelled"}:
            apply_order_webhook(
                session,
                installation=installation,
                payload=payload,
            )
            delivery.status = ShopifyWebhookStatus.PROCESSED
        elif topic == "app/uninstalled":
            uninstall_shop(session, installation=installation)
            delivery.status = ShopifyWebhookStatus.PROCESSED
        elif topic in {"customers/data_request", "customers/redact"}:
            # Product Identity does not persist Shopify customer records or
            # customer PII. The verified request is acknowledged and audited
            # only by topic/id/digest.
            delivery.status = ShopifyWebhookStatus.PROCESSED
        else:
            delivery.status = ShopifyWebhookStatus.IGNORED

        from datetime import datetime, timezone
        delivery.processed_at = datetime.now(timezone.utc)
        session.commit()
    except (ValueError, ShopifyConnectorError, json.JSONDecodeError) as exc:
        session.rollback()
        failed = ShopifyWebhookDelivery(
            installation_id=installation.id if installation else None,
            shop_domain=shop,
            webhook_id=webhook_id,
            event_id=event_id,
            topic=topic,
            payload_sha256=payload_digest(raw_body),
            status=ShopifyWebhookStatus.FAILED,
            error_message=str(exc)[:500],
        )
        session.add(failed)
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Shopify webhook payload could not be processed",
        ) from exc
    except IntegrityError:
        session.rollback()
        existing = session.scalar(
            select(ShopifyWebhookDelivery).where(
                ShopifyWebhookDelivery.webhook_id == webhook_id
            )
        )
        if existing is not None:
            return {"accepted": True, "duplicate": True}
        raise

    return {"accepted": True, "duplicate": False}
