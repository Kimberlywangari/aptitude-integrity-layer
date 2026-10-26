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

from app.api.deps import get_clock, get_login_limiter, get_start_limiter
from app.clock import FakeClock
from app.config import Settings, get_settings
from app.core import passwords
from app.db import get_db
from app.main import app
from app.services.rate_limit import AttemptLimiter
from app.services.staff_auth import create_reviewer
from scripts.seed_synthetic import SeedSummary, seed
from scripts.simulate_cohort import simulate

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


@pytest.fixture(autouse=True)
def cheap_password_hashing(monkeypatch: pytest.MonkeyPatch) -> None:
    """bcrypt's lowest cost, so a test that signs in does not spend a quarter of a second on it."""
    monkeypatch.setattr(passwords, "ROUNDS", 4)


@pytest.fixture(autouse=True)
def no_background_mail(monkeypatch: pytest.MonkeyPatch) -> None:
    """A request that queues mail starts a thread that sends it with its own database session,
    which would leave the test's transaction. Tests send with `mail.send_queued` and a fake."""
    monkeypatch.setattr("app.services.mail.launch_sending", lambda clock=None: None)


@pytest.fixture(autouse=True)
def no_background_processing(monkeypatch: pytest.MonkeyPatch) -> None:
    """The Process sitting button runs in a thread with its own database session; a test that
    starts it would leave the test's transaction. Tests call `processing._work` inline instead."""
    monkeypatch.setattr("app.services.processing.launch", lambda sitting_id, clock=None: False)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def settings(tmp_path) -> Settings:
    """Test settings: public URL fixed, video kept in a throwaway folder. Tests replace fields
    as they need. The behaviour switches are pinned here so a developer's own .env (a camera gate
    on, a local model chosen) cannot change what the tests see."""
    return Settings(
        public_base_url=TEST_PUBLIC_URL,
        session_secret="test-secret",
        video_root=str(tmp_path / "video"),
        precheck_gate="off",
        ai_provider="rules",
        chunk_fail_rate=0.0,
        # whatever mail account a developer has put in .env, a test never has one: nothing a test
        # does can send a real email
        smtp_host="",
        smtp_user="",
        smtp_password="",
        mail_from="",
        appeal_email="",
    )


@pytest.fixture
def client(db: Session, clock: FakeClock, settings: Settings) -> Iterator[TestClient]:
    def reload_db():
        # Each request sees the database, not objects cached by an earlier request.
        db.expire_all()
        return db

    app.dependency_overrides[get_db] = reload_db
    app.dependency_overrides[get_clock] = lambda: clock
    app.dependency_overrides[get_settings] = lambda: settings
    # a fresh wrong-code limiter per test, so one test's failures never block another
    limiter = AttemptLimiter(settings.start_max_failures, settings.start_window_s)
    app.dependency_overrides[get_start_limiter] = lambda: limiter
    login_limiter = AttemptLimiter(settings.login_max_failures, settings.login_window_s)
    app.dependency_overrides[get_login_limiter] = lambda: login_limiter
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def seeded(db: Session) -> SeedSummary:
    return seed(db, seed=42, secret="test-secret", public_base_url=TEST_PUBLIC_URL)


@pytest.fixture
def sim(db: Session, seeded: SeedSummary):
    """The made-up closed sitting of sixteen finished candidates, flags already computed."""
    result = simulate(db, seed=1)
    db.flush()
    return result


STAFF_PASSWORD = "correct horse battery"


@pytest.fixture
def staff(client: TestClient, db: Session, clock: FakeClock) -> dict[str, str]:
    """Authorization headers for a signed-in reviewer."""
    create_reviewer(db, clock, email="rev@example.com", password=STAFF_PASSWORD)
    db.flush()
    token = client.post(
        "/api/review/login", json={"email": "rev@example.com", "password": STAFF_PASSWORD}
    ).json()["token"]
    return {"Authorization": f"Bearer {token}"}
