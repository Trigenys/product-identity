from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import AuthenticationError, JWTVerifier
from app.db.session import get_db_session
from app.models.auth import User

bearer_scheme = HTTPBearer(auto_error=False)


def get_jwt_verifier() -> JWTVerifier:
    return JWTVerifier(get_settings())


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    session: Annotated[Session, Depends(get_db_session)],
    verifier: Annotated[JWTVerifier, Depends(get_jwt_verifier)],
) -> User:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
        )

    try:
        identity = verifier.verify(credentials.credentials)
    except AuthenticationError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid bearer token",
        ) from exc

    user = session.scalar(select(User).where(User.external_subject == identity.subject))
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Authenticated identity is not provisioned",
        )

    return user
