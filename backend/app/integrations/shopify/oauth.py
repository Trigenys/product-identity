import hashlib
import hmac
import re
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.shopify import ShopifyOAuthState

SHOP_DOMAIN_RE = re.compile(r"^[a-z0-9][a-z0-9-]*\.myshopify\.com$")


class ShopifyOAuthError(ValueError):
    pass


def normalize_shop_domain(value: str) -> str:
    candidate = value.strip().lower()
    if not SHOP_DOMAIN_RE.fullmatch(candidate):
        raise ShopifyOAuthError("Invalid Shopify shop domain")
    return candidate


def callback_hmac_is_valid(params: dict[str, str], *, client_secret: str) -> bool:
    provided = params.get("hmac", "")
    if not provided or not client_secret:
        return False
    message = "&".join(
        f"{key}={value}"
        for key, value in sorted(params.items())
        if key != "hmac"
    )
    computed = hmac.new(
        client_secret.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(computed, provided)


@dataclass(frozen=True)
class OAuthStart:
    authorization_url: str
    state: str


def create_oauth_start(
    session: Session,
    *,
    organization_id: uuid.UUID,
    shop_domain: str,
    client_id: str,
    scopes: str,
    redirect_uri: str,
    ttl_minutes: int = 10,
) -> OAuthStart:
    shop = normalize_shop_domain(shop_domain)
    if not client_id or not redirect_uri:
        raise ShopifyOAuthError("Shopify OAuth is not configured")

    nonce = secrets.token_urlsafe(32)
    digest = hashlib.sha256(nonce.encode("utf-8")).hexdigest()
    now = datetime.now(timezone.utc)

    session.add(
        ShopifyOAuthState(
            organization_id=organization_id,
            shop_domain=shop,
            nonce_digest=digest,
            expires_at=now + timedelta(minutes=ttl_minutes),
        )
    )
    session.flush()

    query = urlencode(
        {
            "client_id": client_id,
            "scope": scopes,
            "redirect_uri": redirect_uri,
            "state": nonce,
        }
    )
    return OAuthStart(
        authorization_url=f"https://{shop}/admin/oauth/authorize?{query}",
        state=nonce,
    )


def consume_oauth_state(
    session: Session,
    *,
    shop_domain: str,
    state: str,
    now: datetime | None = None,
) -> ShopifyOAuthState:
    shop = normalize_shop_domain(shop_domain)
    digest = hashlib.sha256(state.encode("utf-8")).hexdigest()
    current = now or datetime.now(timezone.utc)

    row = session.scalar(
        select(ShopifyOAuthState).where(
            ShopifyOAuthState.shop_domain == shop,
            ShopifyOAuthState.nonce_digest == digest,
        )
    )
    if row is None:
        raise ShopifyOAuthError("OAuth state is invalid")
    if row.consumed_at is not None:
        raise ShopifyOAuthError("OAuth state has already been used")

    expires_at = row.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at < current:
        raise ShopifyOAuthError("OAuth state has expired")

    row.consumed_at = current
    session.flush()
    return row
