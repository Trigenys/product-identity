from collections.abc import Generator

from fastapi import HTTPException, status
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from app.core.config import get_settings

settings = get_settings()


def database_is_configured() -> bool:
    return not (
        settings.environment == "production"
        and settings.database_url.startswith("sqlite")
    )


connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine_kwargs: dict[str, object] = {
    "connect_args": connect_args,
}

if settings.runtime == "cloudflare-worker":
    # Hyperdrive owns pooling. NullPool prevents SQLAlchemy from reusing a
    # connection across Worker request contexts, which Cloudflare forbids.
    engine_kwargs["poolclass"] = NullPool
else:
    engine_kwargs["pool_pre_ping"] = True

engine = create_engine(settings.database_url, **engine_kwargs)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db_session() -> Generator[Session, None, None]:
    if not database_is_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Production database is not configured",
        )

    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
