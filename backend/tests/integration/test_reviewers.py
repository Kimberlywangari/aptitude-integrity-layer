"""Creating, resetting and switching off staff accounts (the service and the CLI jobs)."""

import contextlib

import pytest
from sqlalchemy import select

from app.core.passwords import verify_password
from app.models import Reviewer
from app.services.staff_auth import create_reviewer, deactivate_reviewer
from scripts import reviewers as cli

PASSWORD = "correct horse battery"


def test_a_new_account_is_stored_lower_case_with_a_hash_and_the_clock_time(db, clock):
    account, created = create_reviewer(
        db, clock, email="  New.Person@Example.com ", password=PASSWORD, role="admin"
    )
    assert created
    assert account.email == "new.person@example.com"
    assert account.role == "admin"
    assert account.is_active
    assert account.created_at == clock.now()
    assert account.password_hash != PASSWORD
    assert verify_password(PASSWORD, account.password_hash)


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"password": "short"}, "at least 12"),
        ({"password": "é" * 37}, "at most 72 bytes"),
        ({"email": "not-an-email"}, "email address"),
        ({"email": "a@b"}, "email address"),
        ({"role": "superuser"}, "role must be"),
    ],
)
def test_bad_input_is_refused_with_a_readable_message(db, clock, kwargs, message):
    args = {"email": "ok@example.com", "password": PASSWORD, "role": "reviewer"} | kwargs
    with pytest.raises(ValueError, match=message):
        create_reviewer(db, clock, **args)
    assert db.scalars(select(Reviewer)).all() == []


def test_a_second_account_with_the_same_email_is_refused_without_update(db, clock):
    create_reviewer(db, clock, email="dup@example.com", password=PASSWORD)
    with pytest.raises(ValueError, match="--update"):
        create_reviewer(db, clock, email="DUP@example.com", password="another long passphrase")


def test_update_resets_the_password_and_role_and_switches_the_account_back_on(db, clock):
    account, _ = create_reviewer(db, clock, email="back@example.com", password=PASSWORD)
    deactivate_reviewer(db, "back@example.com")
    assert not account.is_active

    again, created = create_reviewer(
        db,
        clock,
        email="back@example.com",
        password="another long passphrase",
        role="admin",
        update=True,
    )
    assert not created
    assert again.id == account.id
    assert again.is_active
    assert again.role == "admin"
    assert verify_password("another long passphrase", again.password_hash)
    assert not verify_password(PASSWORD, again.password_hash)


def test_deactivating_an_unknown_account_says_so(db):
    with pytest.raises(ValueError, match="no account for ghost@example.com"):
        deactivate_reviewer(db, "Ghost@Example.com")


# ------------------------------------------------------------------------------- the CLI jobs


@pytest.fixture
def cli_db(db, monkeypatch):
    """Point the jobs at the test transaction instead of the development database."""
    monkeypatch.setattr("app.db.SessionLocal", lambda: contextlib.nullcontext(db))
    return db


def test_create_reviewer_job_creates_an_account(cli_db, capsys):
    cli.create_main(["--email", "cli@example.com", "--password", PASSWORD, "--role", "admin"])

    assert capsys.readouterr().out.strip() == "created cli@example.com (admin)"
    account = cli_db.scalar(select(Reviewer).where(Reviewer.email == "cli@example.com"))
    assert account is not None
    assert account.role == "admin"


def test_create_reviewer_job_asks_for_the_password_when_it_is_left_out(cli_db, monkeypatch):
    answers = iter([PASSWORD, PASSWORD])
    monkeypatch.setattr("getpass.getpass", lambda prompt="": next(answers))

    cli.create_main(["--email", "asked@example.com"])

    account = cli_db.scalar(select(Reviewer).where(Reviewer.email == "asked@example.com"))
    assert account is not None
    assert verify_password(PASSWORD, account.password_hash)


def test_create_reviewer_job_stops_when_the_two_passwords_differ(cli_db, monkeypatch):
    answers = iter([PASSWORD, "something else entirely"])
    monkeypatch.setattr("getpass.getpass", lambda prompt="": next(answers))

    with pytest.raises(SystemExit, match="differ"):
        cli.create_main(["--email", "mismatch@example.com"])
    assert cli_db.scalars(select(Reviewer)).all() == []


def test_create_reviewer_job_reports_a_short_password_and_exits(cli_db):
    with pytest.raises(SystemExit, match="at least 12"):
        cli.create_main(["--email", "short@example.com", "--password", "tiny"])


def test_deactivate_reviewer_job_switches_the_account_off(cli_db, clock, capsys):
    create_reviewer(cli_db, clock, email="leaver@example.com", password=PASSWORD)

    cli.deactivate_main(["--email", "leaver@example.com"])

    assert capsys.readouterr().out.strip() == "deactivated leaver@example.com"
    account = cli_db.scalar(select(Reviewer).where(Reviewer.email == "leaver@example.com"))
    assert account is not None
    assert not account.is_active


def test_both_jobs_are_registered():
    from scripts.jobs import JOBS

    assert JOBS["create_reviewer"] is cli.create_main
    assert JOBS["deactivate_reviewer"] is cli.deactivate_main
