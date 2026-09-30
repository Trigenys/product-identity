from dataclasses import dataclass
from typing import Any

from app.core.config import Settings


class AuthenticationError(Exception):
    pass


@dataclass(frozen=True)
class AuthenticatedIdentity:
    subject: str
    email: str | None


class JWTVerifier:
    """Validate externally issued JWTs without owning user passwords."""

    def __init__(self, settings: Settings) -> None:
        self._issuer = settings.auth_issuer
        self._audience = settings.auth_audience
        self._algorithm = settings.auth_algorithm
        self._key = settings.auth_jwt_key

    def verify(self, token: str) -> AuthenticatedIdentity:
        if not self._key:
            raise AuthenticationError("JWT verification key is not configured")

        # PyJWT's crypto backend pulls in cryptography. Cloudflare Python Workers
        # forbid entropy reads during module startup, so load the crypto stack
        # only when a request actually needs JWT verification.
        try:
            import jwt
            from jwt import InvalidTokenError
        except ImportError as exc:
            raise AuthenticationError("JWT runtime dependency is unavailable") from exc

        try:
            payload: dict[str, Any] = jwt.decode(
                token,
                self._key,
                algorithms=[self._algorithm],
                issuer=self._issuer,
                audience=self._audience,
                options={"require": ["exp", "iat", "iss", "aud", "sub"]},
            )
        except InvalidTokenError as exc:
            raise AuthenticationError("Invalid access token") from exc

        subject = str(payload.get("sub", "")).strip()
        if not subject:
            raise AuthenticationError("Access token has no subject")

        email = payload.get("email")
        return AuthenticatedIdentity(
            subject=subject,
            email=str(email) if email is not None else None,
        )
