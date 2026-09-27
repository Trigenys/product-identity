from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

import httpx


class ShopifyTransportError(RuntimeError):
    pass


@dataclass(frozen=True)
class ShopifyTokenResponse:
    access_token: str
    refresh_token: str
    scope: str
    access_token_expires_at: datetime
    refresh_token_expires_at: datetime


class ShopifyAdminClient(Protocol):
    def exchange_code(self, *, shop: str, code: str) -> ShopifyTokenResponse:
        ...

    def refresh_token(self, *, shop: str, refresh_token: str) -> ShopifyTokenResponse:
        ...

    def graphql(self, *, shop: str, access_token: str, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        ...


class HttpShopifyAdminClient:
    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        api_version: str,
        timeout_seconds: float = 20.0,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._api_version = api_version
        self._timeout = timeout_seconds

    @staticmethod
    def _token_response(body: dict[str, Any]) -> ShopifyTokenResponse:
        now = datetime.now(timezone.utc)
        try:
            access_token = str(body["access_token"])
            refresh_token = str(body["refresh_token"])
            expires_in = int(body["expires_in"])
            refresh_expires_in = int(body["refresh_token_expires_in"])
            scope = str(body.get("scope", ""))
        except (KeyError, TypeError, ValueError) as exc:
            raise ShopifyTransportError("Shopify returned an invalid token response") from exc

        return ShopifyTokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            scope=scope,
            access_token_expires_at=now + timedelta(seconds=expires_in),
            refresh_token_expires_at=now + timedelta(seconds=refresh_expires_in),
        )

    def exchange_code(self, *, shop: str, code: str) -> ShopifyTokenResponse:
        try:
            response = httpx.post(
                f"https://{shop}/admin/oauth/access_token",
                data={
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "code": code,
                    "expiring": "1",
                },
                headers={"Accept": "application/json"},
                timeout=self._timeout,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ShopifyTransportError("Shopify OAuth token exchange failed") from exc
        return self._token_response(response.json())

    def refresh_token(self, *, shop: str, refresh_token: str) -> ShopifyTokenResponse:
        try:
            response = httpx.post(
                f"https://{shop}/admin/oauth/access_token",
                data={
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                },
                headers={"Accept": "application/json"},
                timeout=self._timeout,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ShopifyTransportError("Shopify access token refresh failed") from exc
        return self._token_response(response.json())

    def graphql(
        self,
        *,
        shop: str,
        access_token: str,
        query: str,
        variables: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            response = httpx.post(
                f"https://{shop}/admin/api/{self._api_version}/graphql.json",
                json={"query": query, "variables": variables},
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "X-Shopify-Access-Token": access_token,
                },
                timeout=self._timeout,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ShopifyTransportError("Shopify Admin GraphQL request failed") from exc

        body = response.json()
        if body.get("errors"):
            raise ShopifyTransportError("Shopify Admin GraphQL returned errors")
        return body
