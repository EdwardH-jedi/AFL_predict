"""
tests/conftest.py
------------------
Shared pytest fixtures.

Uses an in-memory SQLite database for all tests — no external DB required.
Overrides the DB_URL and API_SECRET_KEY settings via environment variables
before any app code imports them.
"""

import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Override settings before any app module is imported
os.environ.setdefault("DB_URL", "sqlite:///:memory:")
os.environ.setdefault("API_SECRET_KEY", "test-secret")
os.environ.setdefault("APP_ENV", "development")

from config.settings import get_settings  # noqa: E402 — must come after env override
from db.base import Base  # noqa: E402
from db.session import get_db  # noqa: E402
import db.models  # noqa: E402, F401 — register all models


@pytest.fixture(scope="session")
def test_engine():
    """Create an in-memory SQLite engine for the test session."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def db_session(test_engine):
    """Yield a database session that is rolled back after each test."""
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
    session = TestingSession()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture()
def client(db_session):
    """Return a FastAPI TestClient with the DB dependency overridden."""
    from api.main import app

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
