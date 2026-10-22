"""Staff sign-in, the token it returns, the role dependencies and the attempt limit."""

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api.deps import get_clock, require_admin
from app.config import get_settings
from app.core.staff_token import issue_staff_token
from app.db import get_db
from app.errors import install_error_handlers
from app.models import AuditLog, Reviewer
from app.services.staff_auth import create_reviewer, deactivate_reviewer

PASSWORD = "correct horse battery"


@pytest.fixture
def reviewer(db, clock) -> Reviewer:
    account, _ = create_reviewer(db, clock, email="Rev@Example.com", password=PASSWORD)
    return account


@pytest.fixture
def admin(db, clock) -> Reviewer:
    account, _ = create_reviewer(
        db, clock, email="boss@example.com", password=PASSWORD, role="admin"
    )
    return account


def login(client, email="rev@example.com", password=PASSWORD, **kwargs):
    return client.post("/api/review/login", json={"email": email, "password": password}, **kwargs)


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# --------------------------------------------------------------------------------- signing in


def test_login_returns_a_token_that_me_accepts(client, reviewer):
    response = login(client)
    assert response.status_code == 200
    body = response.json()
    assert body["email"] == "rev@example.com"
    assert body["role"] == "reviewer"

    me = client.get("/api/review/me", headers=bearer(body["token"]))
    assert me.status_code == 200
    assert me.json() == {"email": "rev@example.com", "role": "reviewer"}


def test_an_admin_signs_in_as_admin_and_may_use_the_reviewer_routes(client, admin):
    body = login(client, email="boss@example.com").json()
    assert body["role"] == "admin"
    assert client.get("/api/review/me", headers=bearer(body["token"])).status_code == 200


def test_the_email_ignores_case_and_surrounding_spaces(client, reviewer):
    assert login(client, email="  REV@example.COM ").status_code == 200


def test_wrong_password_and_unknown_email_get_the_same_answer(client, reviewer):
    wrong = login(client, password="not the password")
    unknown = login(client, email="nobody@example.com")
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json() == {"code": "invalid_credentials"}


def test_a_password_longer_than_bcrypt_reads_is_just_wrong(client, reviewer):
    response = login(client, password="x" * 200)
    assert response.status_code == 401
    assert response.json() == {"code": "invalid_credentials"}


def test_a_login_is_written_to_the_audit_log_and_a_failure_is_not(db, client, clock, reviewer):
    login(client, password="not the password")
    assert db.scalars(select(AuditLog)).all() == []

    login(client)
    rows = db.scalars(select(AuditLog)).all()
    assert len(rows) == 1
    assert rows[0].action == "login"
    assert rows[0].reviewer_id == reviewer.id
    assert rows[0].ts == clock.now()


# --------------------------------------------------------------------------------- the token


def test_me_refuses_a_missing_or_malformed_token(client, reviewer):
    assert client.get("/api/review/me").json() == {"code": "unauthorized"}
    for header in ("Bearer", "Bearer nonsense", "Basic abc", "nonsense"):
        response = client.get("/api/review/me", headers={"Authorization": header})
        assert response.status_code == 401, header
        assert response.json() == {"code": "unauthorized"}


def test_a_token_expires_after_the_configured_lifetime(client, clock, settings, reviewer):
    token = login(client).json()["token"]
    clock.advance(settings.staff_token_ttl_s)
    assert client.get("/api/review/me", headers=bearer(token)).status_code == 200
    clock.advance(1)
    assert client.get("/api/review/me", headers=bearer(token)).status_code == 401


def test_a_token_signed_with_another_secret_is_refused(client, clock, reviewer):
    forged = issue_staff_token("another-secret", clock, reviewer.id, reviewer.password_hash)
    assert client.get("/api/review/me", headers=bearer(forged)).status_code == 401


def test_a_token_for_an_account_that_does_not_exist_is_refused(client, clock, settings):
    token = issue_staff_token(settings.session_secret, clock, 999_999, "any-hash")
    assert client.get("/api/review/me", headers=bearer(token)).status_code == 401


def test_switching_an_account_off_stops_its_token_and_its_sign_in(db, client, clock, reviewer):
    token = login(client).json()["token"]
    deactivate_reviewer(db, "rev@example.com")

    assert client.get("/api/review/me", headers=bearer(token)).status_code == 401
    assert login(client).status_code == 401


def test_resetting_the_password_stops_tokens_issued_before(db, client, clock, reviewer):
    old = login(client).json()["token"]
    create_reviewer(
        db, clock, email="rev@example.com", password="a brand new passphrase", update=True
    )

    assert client.get("/api/review/me", headers=bearer(old)).status_code == 401
    assert login(client, password=PASSWORD).status_code == 401
    fresh = login(client, password="a brand new passphrase")
    assert fresh.status_code == 200
    assert client.get("/api/review/me", headers=bearer(fresh.json()["token"])).status_code == 200


# --------------------------------------------------------------------------------- the roles


def _app_with_an_admin_route(db, clock, settings) -> TestClient:
    """A tiny app, because no real admin endpoint exists yet to put the dependency in front of."""
    app = FastAPI()
    install_error_handlers(app)

    @app.get("/admin-only")
    def admin_only(staff: Reviewer = Depends(require_admin)) -> dict[str, str]:
        return {"email": staff.email}

    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_clock] = lambda: clock
    app.dependency_overrides[get_settings] = lambda: settings
    return TestClient(app)


def test_the_admin_dependency_lets_an_admin_in_and_refuses_a_reviewer(
    db, clock, settings, reviewer, admin
):
    app_client = _app_with_an_admin_route(db, clock, settings)
    reviewer_token = issue_staff_token(
        settings.session_secret, clock, reviewer.id, reviewer.password_hash
    )
    admin_token = issue_staff_token(settings.session_secret, clock, admin.id, admin.password_hash)

    assert app_client.get("/admin-only").status_code == 401
    refused = app_client.get("/admin-only", headers=bearer(reviewer_token))
    assert refused.status_code == 403
    assert refused.json() == {"code": "forbidden"}
    allowed = app_client.get("/admin-only", headers=bearer(admin_token))
    assert allowed.status_code == 200
    assert allowed.json() == {"email": "boss@example.com"}


def test_the_role_comes_from_the_account_not_from_the_token(db, clock, settings, reviewer):
    app_client = _app_with_an_admin_route(db, clock, settings)
    token = issue_staff_token(settings.session_secret, clock, reviewer.id, reviewer.password_hash)
    assert app_client.get("/admin-only", headers=bearer(token)).status_code == 403

    reviewer.role = "admin"  # promoted after the token was issued
    assert app_client.get("/admin-only", headers=bearer(token)).status_code == 200


# --------------------------------------------------------------------------------- the limit


def test_wrong_passwords_are_refused_with_429_after_the_limit_and_released_later(
    client, clock, settings, reviewer
):
    for _ in range(settings.login_max_failures):
        assert login(client, password="wrong wrong wrong").status_code == 401

    blocked = login(client, password="wrong wrong wrong")
    assert blocked.status_code == 429
    body = blocked.json()
    assert body["code"] == "too_many_attempts"
    assert 0 < body["retry_after_s"] <= settings.login_window_s

    clock.advance(settings.login_window_s + 1)
    assert login(client, password="wrong wrong wrong").status_code == 401


def test_a_blocked_address_cannot_sign_in_even_with_the_right_password(client, settings, reviewer):
    for _ in range(settings.login_max_failures):
        login(client, password="wrong wrong wrong")
    assert login(client).status_code == 429


def test_one_email_is_limited_across_addresses(client, settings, reviewer):
    settings.trust_forwarded_for = True
    for number in range(settings.login_max_failures):
        login(client, password="wrong wrong wrong", headers={"X-Forwarded-For": f"10.0.0.{number}"})

    # a new address, the right password, but the account has had too many wrong tries
    response = login(client, headers={"X-Forwarded-For": "10.0.1.1"})
    assert response.status_code == 429


def test_one_address_is_limited_across_emails(client, settings, reviewer):
    for number in range(settings.login_max_failures):
        login(client, email=f"guess{number}@example.com")
    assert login(client).status_code == 429


def test_successful_sign_ins_never_count_towards_the_limit(client, settings, reviewer):
    for _ in range(settings.login_max_failures * 2):
        assert login(client).status_code == 200


def test_an_empty_email_or_password_is_a_validation_error_not_a_server_error(client):
    assert client.post("/api/review/login", json={"email": "", "password": "x"}).status_code == 422
    assert client.post("/api/review/login", json={"email": "a@b.co"}).status_code == 422
