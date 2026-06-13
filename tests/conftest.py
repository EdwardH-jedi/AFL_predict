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
from sqlalchemy.pool import StaticPool

# Override settings before any app module is imported
os.environ.setdefault("DB_URL", "sqlite:///:memory:")
os.environ.setdefault("API_SECRET_KEY", "test-secret")
os.environ.setdefault("APP_ENV", "development")

import db.models  # noqa: E402, F401 — register all models
from db.base import Base  # noqa: E402
from db.session import get_db  # noqa: E402


@pytest.fixture()
def test_engine():
    """Create a fresh in-memory SQLite engine for each test.

    A new engine — and therefore a brand-new in-memory database — per test is
    what guarantees isolation: rows that code under test *commits* (the ingest
    jobs commit their own session) are destroyed at teardown and cannot leak
    into the next test. A session-scoped engine shared the same database across
    tests, so committed rows survived the per-test session.rollback() and bled
    into later count assertions.

    StaticPool keeps a single underlying connection, so the same in-memory
    database is visible across threads (e.g. the FastAPI TestClient) within
    one test.
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    try:
        yield engine
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture()
def db_session(test_engine):
    """Yield a database session bound to the per-test engine."""
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
    session = TestingSession()
    try:
        yield session
    finally:
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
