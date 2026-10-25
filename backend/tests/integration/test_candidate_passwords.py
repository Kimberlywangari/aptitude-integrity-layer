"""Candidates with an email sign in with a password they choose at their first sign-in, a running
test cannot be taken over from another device, and a candidate can see whose test it is."""

import pytest
from sqlalchemy import select

from app.core.security import format_invite_code
from app.core.staff_token import issue_staff_token
from app.models import AuditLog, Candidate, EmailOutbox, Event, Sitting, TestSession
from app.services import mail
from app.services.login import MIN_PASSWORD_CHARS
from app.services.staff_auth import create_reviewer
from tests.integration.test_candidate_emails import FakeMailer, paste, start
from tests.integration.test_sitting_invites import sitting_of

PASSWORD = "a password of her own"
ADMIN_PASSWORD = "correct horse battery"
SAME = {"code": "invalid_invitation"}


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def admin_headers(db, clock, settings):
    account, _ = create_reviewer(
        db, clock, email="boss@example.com", password=ADMIN_PASSWORD, role="admin"
    )
    token = issue_staff_token(settings.session_secret, clock, account.id, account.password_hash)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def sitting(client, seeded, admin_headers):
    return sitting_of(client, admin_headers, "Passwords", {"numerical": 2})


@pytest.fixture
def ada(client, sitting, admin_headers):
    """Ada, invited, with no password chosen yet. Returns (code, candidate id)."""
    made = paste(client, admin_headers, sitting, "Ada Lovelace, ada@example.org\n").json()
    invite = made["invites"][0]
    return invite["code"], invite["candidate_id"]


@pytest.fixture
def chosen(client, ada):
    """Ada has signed in once and chosen her password. Returns (code, session id)."""
    code, _ = ada
    first = start(client, code, "ada@example.org", new_password=PASSWORD)
    assert first.status_code == 200
    return code, first.json()["session_id"]


# ------------------------------------------------------------------------ choosing a password


def test_the_first_sign_in_asks_for_a_password_and_starts_nothing_until_one_is_chosen(
    client, db, ada
):
    code, candidate_id = ada
    needed = start(client, code, "ada@example.org")
    assert (needed.status_code, needed.json()["code"]) == (409, "password_needed")
    assert db.scalar(select(TestSession)) is None
    assert db.get(Candidate, candidate_id).password_hash is None


def test_a_password_that_is_too_short_or_too_long_is_refused_and_nothing_is_saved(
    client, db, ada
):
    code, candidate_id = ada
    short = start(client, code, "ada@example.org", new_password="seven77")
    assert (short.status_code, short.json()["code"]) == (422, "password_too_short")
    assert short.json()["min"] == MIN_PASSWORD_CHARS
    blank = start(client, code, "ada@example.org", new_password="         ")
    assert blank.json()["code"] == "password_too_short"
    long = start(client, code, "ada@example.org", new_password="x" * 73)
    assert (long.status_code, long.json()["code"]) == (422, "password_too_long")
    assert db.get(Candidate, candidate_id).password_hash is None


def test_the_password_is_kept_only_as_a_hash(client, db, ada):
    code, candidate_id = ada
    assert start(client, code, "ada@example.org", new_password=PASSWORD).status_code == 200
    stored = db.get(Candidate, candidate_id).password_hash
    assert stored.startswith("$2") and PASSWORD not in stored


# ------------------------------------------------------------------------------ signing in again


def test_after_choosing_one_the_code_and_email_alone_no_longer_work(client, chosen):
    code, _ = chosen
    assert start(client, code, "ada@example.org").status_code == 401
    assert start(client, code, "ada@example.org", password="not her password").status_code == 401
    assert start(client, code, "ada@example.org", password=PASSWORD).status_code == 200


def test_email_and_password_are_enough_and_the_code_is_not_needed(client, chosen):
    _, session_id = chosen
    again = start(client, None, " Ada@Example.org ", password=PASSWORD)
    assert again.status_code == 200
    assert again.json()["session_id"] == session_id  # the same test, not a second attempt


def test_every_way_of_being_wrong_gives_the_same_answer(client, chosen):
    code, _ = chosen
    wrong = [
        start(client, None, "ada@example.org", password="not her password"),
        start(client, None, "nobody@example.org", password=PASSWORD),  # nobody has this email
        start(client, None, "ada@example.org"),  # no password at all
        start(client, None, None, password=PASSWORD),  # no email
        start(client, "ZZZZ-ZZZZ", "ada@example.org", password=PASSWORD),  # no such code
        start(client, code, "someone@else.test", password=PASSWORD),  # not her email
    ]
    assert [r.status_code for r in wrong] == [401] * 6
    assert [r.json() for r in wrong] == [SAME] * 6


def test_wrong_passwords_count_towards_the_same_limit_as_wrong_codes(client, settings, chosen):
    for _ in range(settings.start_max_failures):
        assert start(client, None, "ada@example.org", password="guess").status_code == 401
    blocked = start(client, None, "ada@example.org", password=PASSWORD)
    assert (blocked.status_code, blocked.json()["code"]) == (429, "too_many_attempts")


def test_someone_invited_to_two_sittings_is_signed_in_to_the_open_one(
    client, db, seeded, admin_headers
):
    older = sitting_of(client, admin_headers, "Older", {"numerical": 2})
    newer = sitting_of(client, admin_headers, "Newer", {"numerical": 2})
    for sitting in (older, newer):
        code = paste(client, admin_headers, sitting, "Ada Lovelace, ada@example.org\n").json()[
            "invites"
        ][0]["code"]
        assert start(client, code, "ada@example.org", new_password=PASSWORD).status_code == 200
    db.get(Sitting, newer["id"]).status = "closed"
    db.flush()

    again = start(client, None, "ada@example.org", password=PASSWORD)
    assert again.status_code == 200
    session = db.get(TestSession, again.json()["session_id"])
    assert session.sitting_id == older["id"]


def test_a_candidate_made_without_an_email_is_untouched_by_passwords(
    client, sitting, admin_headers
):
    made = client.post(
        "/api/admin/invites", json={"count": 1, "sitting_id": sitting["id"]}, headers=admin_headers
    ).json()["invites"][0]
    assert start(client, made["code"]).status_code == 200
    assert start(client, made["code"], new_password=PASSWORD).status_code == 200  # ignored


# --------------------------------------------------------------------- a forgotten password


def test_sending_a_new_link_clears_the_password_and_sends_the_invitation_again(
    client, db, clock, chosen, admin_headers
):
    code, session_id = chosen
    candidate_id = db.get(TestSession, session_id).candidate_id
    mail.send_queued(db, clock, FakeMailer())

    new = client.post(f"/api/admin/invites/{candidate_id}/reissue", headers=admin_headers).json()

    assert db.get(Candidate, candidate_id).password_hash is None
    assert start(client, None, "ada@example.org", password=PASSWORD).status_code == 401  # forgotten
    old_code = start(client, code, "ada@example.org", new_password=PASSWORD)
    assert old_code.status_code == 401
    needed = start(client, new["code"], "ada@example.org")
    assert needed.json()["code"] == "password_needed"
    again = start(client, new["code"], "ada@example.org", new_password="a brand new password")
    assert again.status_code == 200
    (invite,) = [m for m in db.scalars(select(EmailOutbox)) if m.kind == "invite"]
    assert "choose a password" in invite.body and format_invite_code(new["code"]) in invite.body


def test_someone_who_has_finished_gets_a_new_link_on_screen_but_no_new_invitation(
    client, db, clock, chosen, admin_headers
):
    code, session_id = chosen
    token = start(client, None, "ada@example.org", password=PASSWORD).json()["access_token"]
    running(client, session_id, bearer(token))
    client.post(f"/api/session/{session_id}/finish", headers=bearer(token))
    mail.send_queued(db, clock, FakeMailer())
    candidate_id = db.get(TestSession, session_id).candidate_id

    new = client.post(f"/api/admin/invites/{candidate_id}/reissue", headers=admin_headers)

    assert new.status_code == 200 and new.json()["code"] != code
    (invite,) = [m for m in db.scalars(select(EmailOutbox)) if m.kind == "invite"]
    assert invite.status == "sent" and invite.body is None  # not queued again
    assert db.get(Candidate, candidate_id).password_hash is None  # but the password is cleared


# --------------------------------------------------------- finishing an upload after the test


def test_the_upload_page_takes_the_same_credentials(client, db, clock, chosen):
    code, session_id = chosen
    token = start(client, None, "ada@example.org", password=PASSWORD).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    running(client, session_id, headers)
    assert client.post(f"/api/session/{session_id}/finish", headers=headers).status_code == 200

    wrong = client.post("/api/session/resume", json={"email": "ada@example.org", "password": "no"})
    assert (wrong.status_code, wrong.json()) == (401, SAME)
    ok = client.post("/api/session/resume", json={"email": "ada@example.org", "password": PASSWORD})
    assert ok.status_code == 200 and ok.json()["session_id"] == session_id


# ------------------------------------------------------------ no silent takeover of a running test


def running(client, sid, headers):
    begun = client.post(f"/api/session/{sid}/begin", json={"accepted": True}, headers=headers)
    assert begun.status_code == 200


def test_a_second_device_cannot_take_over_a_test_that_is_still_being_heard_from(
    client, clock, chosen
):
    _, session_id = chosen
    first = start(client, None, "ada@example.org", password=PASSWORD).json()
    first_headers = {"Authorization": f"Bearer {first['access_token']}"}
    running(client, session_id, first_headers)

    clock.advance(20)
    blocked = start(client, None, "ada@example.org", password=PASSWORD)
    assert (blocked.status_code, blocked.json()["code"]) == (409, "test_open_elsewhere")
    assert 1 <= blocked.json()["retry_after_s"] <= 60
    # the first device is not cut off by the attempt
    still = client.get(f"/api/session/{session_id}/question", headers=first_headers)
    assert still.status_code == 200


def test_a_beating_heart_keeps_the_test_protected_and_silence_releases_it(client, clock, chosen):
    _, session_id = chosen
    first = start(client, None, "ada@example.org", password=PASSWORD).json()
    headers = {"Authorization": f"Bearer {first['access_token']}"}
    running(client, session_id, headers)

    clock.advance(50)
    assert client.post("/api/heartbeat", headers=headers).status_code == 200
    clock.advance(50)  # 100 s after the start, but only 50 s after the last heartbeat
    assert start(client, None, "ada@example.org", password=PASSWORD).status_code == 409

    clock.advance(11)  # a minute of silence: a crashed browser
    taken = start(client, None, "ada@example.org", password=PASSWORD)
    assert taken.status_code == 200 and taken.json()["session_id"] == session_id
    assert client.get(f"/api/session/{session_id}/question", headers=headers).status_code == 401


def test_a_test_that_has_not_begun_can_be_opened_again_at_once(client, chosen):
    again = start(client, None, "ada@example.org", password=PASSWORD)
    assert again.status_code == 200  # still on the device check: nothing to protect


# --------------------------------------------------------------------------- whose test it is


def test_the_candidate_is_told_their_own_name_and_nobody_else_can_read_it(
    client, chosen, sitting, admin_headers
):
    _, session_id = chosen
    mine = start(client, None, "ada@example.org", password=PASSWORD).json()
    paper = client.get(f"/api/session/{session_id}/paper", headers=bearer(mine["access_token"]))
    assert paper.json()["candidate_name"] == "Ada Lovelace"

    made = paste(client, admin_headers, sitting, "Grace Hopper, grace@navy.test\n").json()
    other = made["invites"][0]
    theirs = start(client, other["code"], "grace@navy.test", new_password=PASSWORD).json()
    stolen = client.get(f"/api/session/{session_id}/paper", headers=bearer(theirs["access_token"]))
    assert stolen.status_code == 401 and "Ada" not in stolen.text


def test_a_candidate_without_a_name_gets_none(client, sitting, admin_headers):
    made = client.post(
        "/api/admin/invites", json={"count": 1, "sitting_id": sitting["id"]}, headers=admin_headers
    ).json()["invites"][0]
    started = start(client, made["code"]).json()
    paper = client.get(
        f"/api/session/{started['session_id']}/paper",
        headers={"Authorization": f"Bearer {started['access_token']}"},
    )
    assert paper.json()["candidate_name"] is None


# -------------------------------------------------------------------- passwords never leak


def test_a_password_is_never_echoed_stored_or_audited(client, db, ada):
    code, _ = ada
    secret = "Zxq-never-seen-anywhere-91"
    responses = [
        start(client, code, "ada@example.org", new_password=secret),
        start(client, None, "ada@example.org", password=secret + "x"),  # a wrong guess
        start(client, None, "ada@example.org", password=secret),
        client.post("/api/session/resume", json={"email": "ada@example.org", "password": secret}),
    ]
    assert all(secret not in r.text for r in responses)
    everything = " ".join(str(row.detail) for row in db.scalars(select(AuditLog)))
    everything += " ".join(str(e.payload) for e in db.scalars(select(Event)))
    everything += " ".join(str(m.body) + m.subject for m in db.scalars(select(EmailOutbox)))
    assert secret not in everything
