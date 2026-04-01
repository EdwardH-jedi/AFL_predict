"""
db/session.py
-------------
Database engine and session factory.
Provides a FastAPI-compatible dependency (get_db) and a plain context manager
for use in pipeline scripts.
"""

from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from config.settings import get_settings

settings = get_settings()

# connect_args is only needed for SQLite (disables same-thread check)
connect_args = {"check_same_thread": False} if settings.db_url.startswith("sqlite") else {}

engine = create_engine(
    settings.db_url,
    connect_args=connect_args,
    echo=settings.app_debug,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that yields a database session and closes it after the request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def db_session() -> Generator[Session, None, None]:
    """Context manager for use in pipeline scripts (outside FastAPI request lifecycle)."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


# Alias for scripts that import get_session
get_session = get_db


def create_all_tables() -> None:
    """Create all tables defined in ORM models. Used for local dev / testing."""
    from db.base import Base  # noqa: F401 — import models to register them
    import db.models  # noqa: F401 — ensures all models are registered

    Base.metadata.create_all(bind=engine)
