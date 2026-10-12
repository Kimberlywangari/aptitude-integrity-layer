"""Shared fixtures.

Integration tests run against the `integrity_test` database (TEST_DATABASE_URL). Every test runs inside a transaction that is rolled back, so tests never see each
other's data.
"""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session

from app.api.deps import get_clock
from app.clock import FakeClock
from app.config import Settings, get_settings
from app.db import get_db
from app.main import app

TEST_PUBLIC_URL = "http://localhost:5173"


@pytest.fixture(scope="session")
def test_database_url() -> str:
    return Settings().test_database_url


@pytest.fixture(scope="session")
def test_engine(test_database_url: str) -> Iterator[Engine]:
    engine = create_engine(test_database_url)
    yield engine
    engine.dispose()


@pytest.fixture
def db(test_engine: Engine) -> Iterator[Session]:
    connection = test_engine.connect()
    outer = connection.begin()
    session = Session(
        bind=connection,
        join_transaction_mode="create_savepoint",
        autoflush=False,
        expire_on_commit=False,
    )
    try:
        yield session
    finally:
        session.close()
        outer.rollback()
        connection.close()


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def settings() -> Settings:
    """Test settings: SEB gate off, public URL fixed. Tests replace fields as they need."""
    return Settings(
        seb_mode="off",
        seb_allowed_keys="",
        public_base_url=TEST_PUBLIC_URL,
        session_secret="test-secret",
    )


@pytest.fixture
def client(db: Session, clock: FakeClock, settings: Settings) -> Iterator[TestClient]:
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_clock] = lambda: clock
    app.dependency_overrides[get_settings] = lambda: settings
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
