"""Shared fixtures.

Integration tests run against the `integrity_test` database (TEST_DATABASE_URL). The schema is
built from the real migrations once per run, and every test runs inside a transaction that is
rolled back, so tests never see each other's data.
"""

from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session

from app.api.deps import get_clock
from app.clock import FakeClock
from app.config import Settings, get_settings
from app.db import get_db
from app.main import app
from scripts.seed_synthetic import SeedSummary, seed

BACKEND_DIR = Path(__file__).resolve().parents[1]
TEST_PUBLIC_URL = "http://localhost:5173"


def alembic_config(url: str) -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    cfg.attributes["configure_logger"] = False
    return cfg


@pytest.fixture(scope="session")
def test_database_url() -> str:
    return Settings().test_database_url


@pytest.fixture(scope="session")
def test_engine(test_database_url: str) -> Iterator[Engine]:
    command.upgrade(alembic_config(test_database_url), "head")
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


@pytest.fixture
def seeded(db: Session) -> SeedSummary:
    return seed(db, seed=42, secret="test-secret", public_base_url=TEST_PUBLIC_URL)
