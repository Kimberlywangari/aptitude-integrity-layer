"""A name and an email on every invitation: the pasted list, the invitation emails, the login that
asks for the email as well as the code, the result emails, and the outbox that sends them."""

import pytest
from sqlalchemy import func, select

from app.core.security import format_invite_code
from app.core.staff_token import issue_staff_token
from app.models import AuditLog, Candidate, Decision, EmailOutbox, Flag, Sitting, TestSession
from app.services import mail, results
from app.services.staff_auth import create_reviewer
from tests.integration.test_sitting_invites import sitting_of

PASSWORD = "correct horse battery"
LIST = "Name, Email\nAda Lovelace, Ada@Example.org\nGrace Hopper <grace@navy.test>\n"


class FakeMailer:
    def __init__(self, fail: int = 0) -> None:
        self.fail = fail
        self.sent: list[tuple[str, str, str]] = []

    def send(self, to: str, subject: str, body: str) -> None:
        if self.fail:
            self.fail -= 1
            raise mail.MailError("the server said no")
        self.sent.append((to, subject, body))


@pytest.fixture
def admin_headers(db, clock, settings):
    account, _ = create_reviewer(
        db, clock, email="boss@example.com", password=PASSWORD, role="admin"
    )
    token = issue_staff_token(settings.session_secret, clock, account.id, account.password_hash)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def sitting(client, seeded, admin_headers):
    return sitting_of(client, admin_headers, "Emails", {"numerical": 2})


def paste(client, headers, sitting, text=LIST):
    return client.post(
        "/api/admin/invites", json={"list_text": text, "sitting_id": sitting["id"]}, headers=headers
    )


def outbox(db):
    return list(db.scalars(select(EmailOutbox).order_by(EmailOutbox.id)))


def with_email(db) -> int:
    """Candidates that have an email (the seed's own 20 have none)."""
    named = select(func.count()).select_from(Candidate).where(Candidate.email.is_not(None))
    return db.scalar(named)


# ------------------------------------------------------------------------ making the invitations


def test_a_list_makes_one_candidate_per_person_and_queues_their_invitation(
    client, db, sitting, admin_headers
):
    response = paste(client, admin_headers, sitting)
    assert response.status_code == 200
    invites = response.json()["invites"]
    assert [(i["name"], i["email"]) for i in invites] == [
        ("Ada Lovelace", "ada@example.org"),
        ("Grace Hopper", "grace@navy.test"),
    ]

    candidates = db.scalars(select(Candidate).where(Candidate.sitting_id == sitting["id"]))
    assert sorted((c.full_name, c.email) for c in candidates) == [
        ("Ada Lovelace", "ada@example.org"),
        ("Grace Hopper", "grace@navy.test"),
    ]
    first, second = outbox(db)
    assert (first.kind, first.to_address, first.status) == ("invite", "ada@example.org", "queued")
    assert second.to_address == "grace@navy.test"
    code = format_invite_code(invites[0]["code"])
    assert "Dear Ada Lovelace," in first.body
    assert f"/?t={code}" in first.body and f"invitation code: {code}" in first.body
    assert "4 questions" not in first.body and "2 questions" in first.body  # the sitting's own
    assert "4 minutes" in first.body  # 2 questions at 1 minute 45 s, rounded up


def test_the_audit_log_counts_invitations_but_never_names_or_addresses_them(
    client, db, sitting, admin_headers
):
    paste(client, admin_headers, sitting)
    details = " ".join(db.scalars(select(AuditLog.detail)))
    assert "generated 2 invitations" in details
    for secret in ("Ada", "Lovelace", "example.org", "grace", "navy.test"):
        assert secret not in details


def test_one_bad_line_creates_nobody(client, db, sitting, admin_headers):
    response = paste(client, admin_headers, sitting, "Ada Lovelace, ada@example.org\nBob, nope\n")

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "list_has_problems"
    assert body["problems"] == [{"line": 2, "reason": "bad_email", "text": "Bob, nope"}]
    assert with_email(db) == 0
    assert outbox(db) == []


def test_the_preview_says_what_is_wrong_and_creates_nobody(client, db, sitting, admin_headers):
    paste(client, admin_headers, sitting)
    before = db.scalar(select(func.count()).select_from(Candidate))

    again = "Ada Lovelace, ada@example.org\nNew Person, new@example.org\n,\n"
    response = client.post(
        "/api/admin/invites/preview",
        json={"list_text": again, "sitting_id": sitting["id"]},
        headers=admin_headers,
    )

    body = response.json()
    assert [p["email"] for p in body["people"]] == ["new@example.org"]
    assert [(p["line"], p["reason"]) for p in body["problems"]] == [
        (1, "already_invited"),
        (3, "bad_email"),
    ]
    assert db.scalar(select(func.count()).select_from(Candidate)) == before


def test_the_same_person_can_be_invited_to_another_sitting(client, db, sitting, admin_headers):
    other = sitting_of(client, admin_headers, "Another", {"numerical": 2})
    assert paste(client, admin_headers, sitting).status_code == 200
    assert paste(client, admin_headers, other).status_code == 200


def test_a_count_still_makes_anonymous_codes_and_queues_nothing(
    client, db, sitting, admin_headers
):
    response = client.post(
        "/api/admin/invites", json={"count": 2, "sitting_id": sitting["id"]}, headers=admin_headers
    )
    assert [i["email"] for i in response.json()["invites"]] == [None, None]
    assert outbox(db) == []


def test_the_candidate_table_shows_the_name_a_masked_email_and_the_mail_status(
    client, db, clock, sitting, admin_headers
):
    paste(client, admin_headers, sitting)
    mail.send_queued(db, clock, FakeMailer(), limit=1)  # only the first goes

    detail = client.get(f"/api/admin/sittings/{sitting['id']}", headers=admin_headers).json()
    rows = [(c["name"], c["email"], c["invite_mail"]) for c in detail["candidates"] if c["name"]]
    assert rows == [
        ("Ada Lovelace", "a***@example.org", "sent"),
        ("Grace Hopper", "g***@navy.test", "queued"),
    ]
    assert "ada@example.org" not in str(detail)


# --------------------------------------------------------------------------------- sending mail


def test_each_email_is_sent_once_and_an_invitation_forgets_its_code_once_sent(db, clock):
    sitting = Sitting(name="S", duration_s=600, question_count=2, status="open")
    db.add(sitting)
    db.flush()
    db.add(Candidate(id="cand-001", invite_token_hash="x" * 64, sitting_id=sitting.id))
    db.flush()
    ask = dict(candidate_id="cand-001", kind="invite", to="a@b.test", subject="S")
    mail.queue(db, clock, body="code ABCD", **ask)
    again = mail.queue(db, clock, body="other", **ask)
    assert again.body == "code ABCD"  # asking twice queues once

    fake = FakeMailer()
    assert mail.send_queued(db, clock, fake).sent == 1
    assert mail.send_queued(db, clock, fake).sent == 0
    assert fake.sent == [("a@b.test", "S", "code ABCD")]
    row = outbox(db)[0]
    assert (row.status, row.body, row.sent_at) == ("sent", None, clock.now())


def test_a_mail_server_that_refuses_is_tried_three_times_then_left_for_an_admin(
    client, db, clock, sitting, admin_headers
):
    paste(client, admin_headers, sitting, "Ada Lovelace, ada@example.org\n")
    fake = FakeMailer(fail=99)
    for _ in range(3):
        mail.send_queued(db, clock, fake)
    row = outbox(db)[0]
    assert (row.status, row.attempts, row.error) == ("failed", 3, "the server said no")
    assert row.body is not None  # still there to send
    assert mail.send_queued(db, clock, FakeMailer()).sent == 0  # nobody keeps trying on its own

    retried = client.post("/api/admin/mail/retry", headers=admin_headers).json()
    assert retried == {"requeued": 1}
    assert mail.send_queued(db, clock, FakeMailer()).sent == 1


def test_a_transient_failure_followed_by_success_sends_the_email(
    client, db, clock, sitting, admin_headers
):
    paste(client, admin_headers, sitting, "Ada Lovelace, ada@example.org\n")
    fake = FakeMailer(fail=1)
    mail.send_queued(db, clock, fake)
    mail.send_queued(db, clock, fake)
    assert [r.status for r in outbox(db)] == ["sent"]


def test_mail_is_not_set_up_until_there_is_a_host_and_a_sender(client, settings, admin_headers):
    assert mail.get_mailer(settings) is None
    status = client.get("/api/admin/mail", headers=admin_headers).json()
    assert status["set_up"] is False
    sent = client.post("/api/admin/mail/test", json={"to": "me@x.test"}, headers=admin_headers)
    assert (sent.status_code, sent.json()["code"]) == (409, "mail_not_set_up")

    settings.smtp_host, settings.mail_from = "smtp.example.test", "me@example.test"
    assert mail.get_mailer(settings) is not None
    status = client.get("/api/admin/mail", headers=admin_headers).json()
    assert (status["set_up"], status["from_address"]) == (True, "m***@example.test")


def test_a_reissued_code_sends_a_fresh_invitation_over_the_old_one(
    client, db, clock, sitting, admin_headers
):
    made = paste(client, admin_headers, sitting, "Ada Lovelace, ada@example.org\n").json()
    mail.send_queued(db, clock, FakeMailer())
    candidate_id = made["invites"][0]["candidate_id"]

    new = client.post(f"/api/admin/invites/{candidate_id}/reissue", headers=admin_headers).json()

    (row,) = outbox(db)
    assert (row.status, row.attempts) == ("queued", 0)
    assert format_invite_code(new["code"]) in row.body
    assert format_invite_code(made["invites"][0]["code"]) not in row.body


def test_deleting_a_sitting_deletes_its_names_emails_and_queued_mail(
    client, db, sitting, admin_headers
):
    paste(client, admin_headers, sitting)
    response = client.post(
        f"/api/admin/sittings/{sitting['id']}/delete",
        json={"confirm_name": "Emails"},
        headers=admin_headers,
    )
    assert response.status_code == 200
    assert with_email(db) == 0
    assert outbox(db) == []


# ------------------------------------------------------------------------------ the login


def start(client, token, email=None, **more):
    body = ({} if token is None else {"token": token}) | ({} if email is None else {"email": email})
    return client.post("/api/session/start", json=body | more)


def test_a_candidate_with_an_email_needs_the_code_and_the_email(client, sitting, admin_headers):
    code = paste(client, admin_headers, sitting).json()["invites"][0]["code"]

    wrong_code = start(client, "ZZZZ-ZZZZ", "ada@example.org")
    code_only = start(client, code)
    wrong_email = start(client, code, "someone@else.test")
    assert (wrong_code.status_code, code_only.status_code, wrong_email.status_code) == (401,) * 3
    # nobody can tell which half was wrong
    same = {"code": "invalid_invitation"}
    assert wrong_code.json() == code_only.json() == wrong_email.json() == same

    # the right pair, before any password is chosen: the page is asked to make one
    pair = (format_invite_code(code).lower(), "  ADA@example.org ")
    needed = start(client, *pair)
    assert (needed.status_code, needed.json()["code"]) == (409, "password_needed")

    ok = start(client, *pair, new_password="a password of her own")
    assert ok.status_code == 200 and ok.json()["session_id"]


def test_a_candidate_made_without_an_email_still_logs_in_with_the_code_alone(
    client, sitting, admin_headers
):
    made = client.post(
        "/api/admin/invites", json={"count": 1, "sitting_id": sitting["id"]}, headers=admin_headers
    )
    assert start(client, made.json()["invites"][0]["code"]).status_code == 200


def test_wrong_emails_count_towards_the_same_limit_as_wrong_codes(
    client, settings, sitting, admin_headers
):
    code = paste(client, admin_headers, sitting).json()["invites"][0]["code"]
    for _ in range(settings.start_max_failures):
        assert start(client, code, "guess@else.test").status_code == 401
    assert start(client, code, "ada@example.org").status_code == 429


def test_finishing_an_upload_later_also_needs_the_email(db, clock, client, sitting, admin_headers):
    code = paste(client, admin_headers, sitting).json()["invites"][0]["code"]
    session = db.scalar(select(TestSession))  # none yet
    assert session is None
    nothing = client.post("/api/session/resume", json={"token": code})
    assert nothing.status_code == 401  # the code alone is not enough here either
    both = {"token": code, "email": "ada@example.org"}
    assert client.post("/api/session/resume", json=both).json()["code"] == "password_needed"
    both |= {"password": "a password of her own"}
    assert start(client, code, "ada@example.org", new_password=both["password"]).status_code == 200
    nothing = client.post("/api/session/resume", json=both)
    assert nothing.status_code == 409  # right credentials, but nothing has finished yet


# ------------------------------------------------------------------------------ result emails


def finished(
    db, clock, sitting_id, candidate_id, *, shortlisted=False, flagged=False, decision=None
):
    """A finished session for a candidate, optionally flagged, shortlisted or decided."""
    session = TestSession(
        id=f"s-{candidate_id}",
        candidate_id=candidate_id,
        sitting_id=sitting_id,
        status="finished",
        created_at=clock.now(),
        started_at=clock.now(),
        ends_at=clock.now(),
        finished_at=clock.now(),
        shortlisted=shortlisted,
    )
    db.add(session)
    db.flush()
    if flagged:
        db.add(
            Flag(
                session_id=session.id, kind="COPY_ATTEMPT", weight=3.0, server_ts=clock.now(),
                position=1, detail={},
            )
        )
    if decision:
        account, _ = create_reviewer(db, clock, email=f"r-{candidate_id}@x.test", password=PASSWORD)
        db.add(
            Decision(
                session_id=session.id,
                reviewer_id=account.id,
                outcome=decision,
                reason="a long enough reason to be accepted here",
                decided_at=clock.now(),
            )
        )
    db.flush()


@pytest.fixture
def cohort(client, db, clock, sitting, admin_headers):
    """Six invited people: passed, plain not-passed, flagged and undecided, flagged and decided,
    referred for follow-up, and one who never finished."""
    text = "\n".join(f"Person {n}, p{n}@example.org" for n in range(1, 7))
    made = paste(client, admin_headers, sitting, text).json()["invites"]
    ids = [i["candidate_id"] for i in made]
    finished(db, clock, sitting["id"], ids[0], shortlisted=True)
    finished(db, clock, sitting["id"], ids[1])
    finished(db, clock, sitting["id"], ids[2], flagged=True)
    finished(db, clock, sitting["id"], ids[3], flagged=True, decision="no_concern")
    finished(db, clock, sitting["id"], ids[4], flagged=True, decision="refer_for_follow_up")
    return ids


def plan(client, headers, sitting):
    return client.get(f"/api/admin/sittings/{sitting['id']}/results", headers=headers).json()


def test_the_plan_says_who_gets_which_email_and_who_is_held_back(
    client, cohort, sitting, admin_headers
):
    body = plan(client, admin_headers, sitting)
    assert (body["passed"], body["not_passed"]) == (1, 2)  # persons 2 and 4
    assert sorted(body["held_back"]) == sorted([cohort[2], cohort[4]])
    assert body["did_not_finish"] == 1
    assert body["sitting_closed"] is False
    preview = body["preview_passed"]["body"]
    assert "passed" in preview and "[candidate's name]" in preview


def test_pass_emails_go_to_the_shortlisted_and_only_once(
    client, db, clock, cohort, sitting, admin_headers
):
    sent = client.post(
        f"/api/admin/sittings/{sitting['id']}/results/send",
        json={"kind": "passed"},
        headers=admin_headers,
    )
    assert sent.json() == {"queued": 1}
    again = client.post(
        f"/api/admin/sittings/{sitting['id']}/results/send",
        json={"kind": "passed"},
        headers=admin_headers,
    )
    assert again.json() == {"queued": 0}  # asked twice: the one person is not written to again
    rows = [r for r in outbox(db) if r.kind == "passed"]
    assert [(r.to_address, "Dear Person 1," in r.body) for r in rows] == [("p1@example.org", True)]

    fake = FakeMailer()
    mail.send_queued(db, clock, fake)
    results_sent = [to for to, subject, _ in fake.sent if subject.endswith("test result")]
    assert results_sent == ["p1@example.org"]


def test_not_passed_emails_wait_for_the_sitting_to_close_and_skip_anyone_under_review(
    client, db, clock, cohort, sitting, admin_headers
):
    url = f"/api/admin/sittings/{sitting['id']}/results/send"
    early = client.post(url, json={"kind": "not_passed"}, headers=admin_headers)
    assert (early.status_code, early.json()["code"]) == (409, "sitting_not_closed")

    db.get(Sitting, sitting["id"]).status = "closed"
    db.flush()
    sent = client.post(url, json={"kind": "not_passed"}, headers=admin_headers)
    assert sent.json() == {"queued": 2}
    recipients = sorted(r.to_address for r in outbox(db) if r.kind == "not_passed")
    # persons 2 (plain) and 4 (flagged, decided), not 3 (undecided), 5 (follow-up), 6 (unfinished)
    assert recipients == ["p2@example.org", "p4@example.org"]
    assert all("Dear Person" in r.body for r in outbox(db) if r.kind == "not_passed")


def test_nobody_gets_both_a_pass_and_a_not_passed_email(
    client, db, clock, cohort, sitting, admin_headers
):
    url = f"/api/admin/sittings/{sitting['id']}/results/send"
    db.get(Sitting, sitting["id"]).status = "closed"
    db.flush()
    client.post(url, json={"kind": "not_passed"}, headers=admin_headers)
    # a reviewer then shortlists person 2, who has already been told no
    db.get(TestSession, f"s-{cohort[1]}").shortlisted = True
    db.flush()

    body = plan(client, admin_headers, sitting)
    assert body["passed"] == 1  # only person 1; person 2 cannot be told yes after no
    assert body["sent_not_passed"] == 1 and body["not_passed"] == 0


def test_a_reviewer_is_told_when_a_result_email_has_already_gone_but_sees_no_address(
    client, db, clock, cohort, sitting, admin_headers
):
    client.post(
        f"/api/admin/sittings/{sitting['id']}/results/send",
        json={"kind": "passed"},
        headers=admin_headers,
    )
    account, _ = create_reviewer(db, clock, email="rev@example.com", password=PASSWORD)
    db.flush()
    token = client.post(
        "/api/review/login", json={"email": "rev@example.com", "password": PASSWORD}
    ).json()["token"]
    toggled = client.post(
        f"/api/review/candidates/{cohort[0]}/shortlist",
        params={"sitting": sitting["id"]},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert toggled.json() == {"shortlisted": False, "result_email_sent": True}


def test_without_an_email_a_finished_candidate_is_counted_not_written_to(
    client, db, clock, sitting, admin_headers
):
    anonymous = client.post(
        "/api/admin/invites", json={"count": 1, "sitting_id": sitting["id"]}, headers=admin_headers
    ).json()["invites"][0]["candidate_id"]
    finished(db, clock, sitting["id"], anonymous, shortlisted=True)
    body = plan(client, admin_headers, sitting)
    assert (body["passed"], body["without_email"]) == (0, 1)
    assert results.result_email_exists(db, anonymous) is False
