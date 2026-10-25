# ruff: noqa: F811
"""Results: a person passes or fails a candidate and the system sends the email; the pass-mark rule
turns down a low score when a sitting closes; the outcomes list shows everyone where they stand.

Nothing here reaches a mail server: emails are read from the outbox, or sent through a fake."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.core.staff_token import issue_staff_token
from app.models import (
    AuditLog,
    Candidate,
    Decision,
    Flag,
    Question,
    SessionQuestion,
    Sitting,
    TestSession,
)
from app.services import mail, outcomes
from app.services.outcomes import Row, status_of
from app.services.staff_auth import create_reviewer
from tests.integration.test_candidate_emails import (  # noqa: F401  (fixtures used by name)
    PASSWORD,
    FakeMailer,
    admin_headers,
    outbox,
    paste,
    sitting,
)

NOW = datetime(2026, 1, 1, tzinfo=UTC)

# ------------------------------------------------------------------------------ the status table


def make_row(**overrides):
    base = {
        "candidate_id": "c",
        "has_email": True,
        "name": None,
        "email": None,
        "session_id": "s",
        "session_status": "finished",
        "score": 2,
        "total": 2,
        "result": None,
        "basis": None,
        "reason": None,
        "result_by": None,
        "result_at": None,
        "appeal_at": None,
    }
    return Row(**(base | overrides))


@pytest.mark.parametrize(
    ("overrides", "closed", "mark", "expected"),
    [
        ({"session_id": None, "session_status": None}, False, None, "invited"),
        ({"session_status": "created"}, False, None, "invited"),
        ({"session_status": "in_progress"}, False, None, "in_progress"),
        ({"session_status": "in_progress"}, True, None, "incomplete"),
        ({"session_id": None, "session_status": None}, True, None, "incomplete"),
        ({}, False, None, "ready"),
        ({"flagged": True}, False, None, "waiting_review"),
        ({"flagged": True, "decided": True}, False, None, "in_review"),
        ({"result": "pass", "basis": "review"}, True, None, "passed"),
        ({"result": "fail", "basis": "review"}, True, None, "failed_review"),
        ({"result": "fail", "basis": "score"}, True, 2, "failed_score"),
        ({"result": "fail", "basis": "review", "appeal_at": NOW}, True, None, "under_appeal"),
        # a score under the mark reads as failed as soon as they finish, before the close
        ({"score": 1}, False, 2, "failed_score"),
        # flags never change what the score rule does
        ({"score": 1, "flagged": True}, False, 2, "failed_score"),
        # exactly at the mark is a pass of the rule, not a fail
        ({"score": 2}, False, 2, "ready"),
        # a person's pass stands whatever the score
        ({"score": 1, "result": "pass", "basis": "review"}, False, 2, "passed"),
        # nobody is failed for a score before they have one
        ({"score": 0, "session_status": "created"}, False, 2, "invited"),
        # with no mark set, nobody is failed for their score
        ({"score": 0}, True, None, "ready"),
    ],
)
def test_the_one_status_function(overrides, closed, mark, expected):
    assert status_of(make_row(**overrides), closed=closed, pass_mark=mark) == expected


# ------------------------------------------------------------------------------------- a cohort


@pytest.fixture
def reviewer_headers(db, clock, settings):
    account, _ = create_reviewer(db, clock, email="reviewer@example.com", password=PASSWORD)
    db.flush()
    token = issue_staff_token(settings.session_secret, clock, account.id, account.password_hash)
    return {"Authorization": f"Bearer {token}"}


def finished(db, clock, sitting_id, candidate_id, *, correct, flagged=False, decision=None):
    """A finished two-question session with `correct` right answers."""
    session = TestSession(
        id=f"s-{candidate_id}",
        candidate_id=candidate_id,
        sitting_id=sitting_id,
        status="finished",
        created_at=clock.now(),
        started_at=clock.now(),
        ends_at=clock.now(),
        finished_at=clock.now(),
    )
    db.add(session)
    db.flush()
    for position, question_id in enumerate(db.scalars(select(Question.id).limit(2)), start=1):
        db.add(
            SessionQuestion(
                session_id=session.id,
                position=position,
                question_id=question_id,
                option_order=[],
                opened_at=clock.now(),
                answered_at=clock.now(),
                correct=position <= correct,
            )
        )
    if flagged:
        db.add(
            Flag(
                session_id=session.id, kind="COPY_ATTEMPT", weight=3.0, server_ts=clock.now(),
                position=1, detail={},
            )
        )  # fmt: skip
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
def cohort(client, db, clock, sitting, admin_headers):  # noqa: F811
    """Six invited people (two questions each). 0: both right. 1: one right. 2: none right.
    3: both right, flagged, undecided. 4: both right, flagged, decided. 5: never started."""
    text = "\n".join(f"Person {n}, p{n}@example.org" for n in range(1, 7))
    ids = [i["candidate_id"] for i in paste(client, admin_headers, sitting, text).json()["invites"]]
    finished(db, clock, sitting["id"], ids[0], correct=2)
    finished(db, clock, sitting["id"], ids[1], correct=1)
    finished(db, clock, sitting["id"], ids[2], correct=0)
    finished(db, clock, sitting["id"], ids[3], correct=2, flagged=True)
    finished(db, clock, sitting["id"], ids[4], correct=2, flagged=True, decision="no_concern")
    return ids


def record(client, headers, sitting, candidate_id, body):
    return client.post(
        f"/api/review/candidates/{candidate_id}/result",
        params={"sitting": sitting["id"]},
        json=body,
        headers=headers,
    )


def result_emails(db):
    return [r for r in outbox(db) if r.kind in ("passed", "not_passed")]


def close(db, sitting):
    db.get(Sitting, sitting["id"]).status = "closed"
    db.flush()


# --------------------------------------------------------------------- recording and sending


def test_a_reviewer_passes_a_candidate_and_the_system_sends_the_email(
    client, db, clock, cohort, sitting, reviewer_headers
):
    done = record(client, reviewer_headers, sitting, cohort[0], {"result": "pass"})
    assert (done.status_code, done.json()) == (200, {"status": "passed"})
    [row] = result_emails(db)
    assert (row.kind, row.to_address, row.status) == ("passed", "p1@example.org", "queued")
    assert "Dear Person 1," in row.body and "you have passed" in row.subject
    assert "Your result: 2 of 2 questions correct." in row.body
    assert "pass mark" not in row.body  # none is set

    again = record(client, reviewer_headers, sitting, cohort[0], {"result": "pass"})
    assert (again.status_code, again.json()["code"]) == (409, "already_emailed")
    assert len(result_emails(db)) == 1

    fake = FakeMailer()
    mail.send_queued(db, clock, fake)
    assert [to for to, subject, _ in fake.sent if "result" in subject] == ["p1@example.org"]


def test_an_admin_can_send_a_result_too_and_a_stranger_cannot(
    client, db, cohort, sitting, admin_headers
):
    assert record(client, admin_headers, sitting, cohort[1], {"result": "pass"}).status_code == 200
    assert record(client, {}, sitting, cohort[2], {"result": "pass"}).status_code == 401
    assert len(result_emails(db)) == 1


def test_a_flagged_candidate_needs_a_recorded_decision_first(
    client, db, cohort, sitting, reviewer_headers
):
    refused = record(client, reviewer_headers, sitting, cohort[3], {"result": "pass"})
    assert (refused.status_code, refused.json()["code"]) == (409, "review_first")
    assert (
        record(client, reviewer_headers, sitting, cohort[4], {"result": "pass"}).status_code == 200
    )
    assert [r.to_address for r in result_emails(db)] == ["p5@example.org"]


def test_nobody_who_has_not_finished_gets_a_result(client, cohort, sitting, reviewer_headers):
    refused = record(client, reviewer_headers, sitting, cohort[5], {"result": "pass"})
    assert refused.status_code == 404  # never started: there is no session to give a result to


def test_turning_someone_down_after_a_review_needs_a_reason_and_tells_them_how_to_appeal(
    client, db, settings, cohort, sitting, reviewer_headers
):
    headers = reviewer_headers
    missing = record(client, headers, sitting, cohort[2], {"result": "fail"})
    assert (missing.status_code, missing.json()["code"]) == (422, "reason_required")
    bad = record(client, headers, sitting, cohort[2], {"result": "fail", "reason_key": "nope"})
    assert bad.json()["code"] == "invalid_reason"
    too_long = record(
        client, headers, sitting, cohort[2],
        {"result": "fail", "reason_key": "other", "reason_text": "x" * 201},
    )  # fmt: skip
    assert too_long.json()["code"] == "reason_too_long"
    assert result_emails(db) == []  # none of that sent anything

    settings.appeal_email = "appeals@example.org"
    sent = record(client, headers, sitting, cohort[2], {"result": "fail", "reason_key": "focus"})
    assert (sent.status_code, sent.json()) == (200, {"status": "failed_review"})
    [row] = result_emails(db)
    assert row.kind == "not_passed"
    assert "your screen left the test page" in row.body
    assert "appeals@example.org" in row.body and cohort[2] in row.body
    lowered = row.body.lower()
    assert not any(word in lowered for word in ("flag", "video", "threshold", "artificial"))
    assert "Dear Person 3," in row.body


def test_a_reviewers_own_sentence_is_what_the_candidate_is_told(
    client, db, cohort, sitting, reviewer_headers
):
    typed = "  The recording stopped at 10:40.  "
    body = {"result": "fail", "reason_key": "other", "reason_text": typed}
    sent = record(client, reviewer_headers, sitting, cohort[1], body)
    assert sent.status_code == 200
    [row] = result_emails(db)
    assert "The reason: The recording stopped at 10:40." in row.body
    # no appeal address is configured, so the email says where it came from
    assert "the address this email came from" in row.body


def test_a_resend_needs_a_yes_and_never_makes_a_second_row(
    client, db, clock, cohort, sitting, reviewer_headers
):
    record(client, reviewer_headers, sitting, cohort[0], {"result": "pass"})
    fake = FakeMailer()
    mail.send_queued(db, clock, fake)
    url = f"/api/review/candidates/{cohort[0]}/result/resend"
    params = {"sitting": sitting["id"]}

    no = client.post(url, params=params, json={}, headers=reviewer_headers)
    assert (no.status_code, no.json()["code"]) == (422, "confirmation_required")
    yes = client.post(url, params=params, json={"confirm": True}, headers=reviewer_headers)
    assert yes.status_code == 204
    [row] = result_emails(db)
    assert row.status == "queued" and row.body
    mail.send_queued(db, clock, fake)
    results_sent = [to for to, subject, _ in fake.sent if "test result" in subject]
    assert len(results_sent) == 2  # the first send and the resend
    assert len(result_emails(db)) == 1


def test_a_result_is_written_to_the_audit_log_by_id_only(
    client, db, cohort, sitting, reviewer_headers
):
    record(client, reviewer_headers, sitting, cohort[0], {"result": "pass"})
    entries = list(db.scalars(select(AuditLog).where(AuditLog.session_id == f"s-{cohort[0]}")))
    assert [e.detail for e in entries] == ["pass email queued"]
    assert "Person" not in entries[0].detail and "@" not in entries[0].detail


# ------------------------------------------------------------------------------ bulk pass


def test_several_can_be_passed_at_once_and_the_refused_are_listed_with_why(
    client, db, cohort, sitting, reviewer_headers
):
    sent = client.post(
        "/api/review/results/bulk-pass",
        json={
            "sitting_id": sitting["id"],
            "candidate_ids": [cohort[0], cohort[3], "cand-nope", cohort[0], cohort[4]],
        },
        headers=reviewer_headers,
    )
    assert sent.status_code == 200, sent.text
    body = sent.json()
    assert body["queued"] == 2  # persons 1 and 5, once each
    assert {(r["candidate_id"], r["code"]) for r in body["refused"]} == {
        (cohort[3], "review_first"),
        ("cand-nope", "candidate_not_found"),
    }
    assert sorted(r.to_address for r in result_emails(db)) == ["p1@example.org", "p5@example.org"]


# ------------------------------------------------------------------------------- the pass mark


def set_mark(client, headers, sitting, value):
    return client.post(
        f"/api/admin/sittings/{sitting['id']}/pass-mark", json={"pass_mark": value}, headers=headers
    )


def test_the_pass_mark_has_limits_and_is_for_admins(
    client, cohort, sitting, admin_headers, reviewer_headers
):
    for bad in (0, 3, -1):
        refused = set_mark(client, admin_headers, sitting, bad)
        assert (refused.status_code, refused.json()["code"]) == (422, "invalid_pass_mark")
    assert set_mark(client, reviewer_headers, sitting, 1).status_code == 403
    assert set_mark(client, admin_headers, sitting, 2).json() == {"pass_mark": 2, "queued": 0}
    assert set_mark(client, admin_headers, sitting, None).json() == {"pass_mark": None, "queued": 0}


def test_closing_a_sitting_turns_down_low_scores_and_nothing_goes_before(
    client, db, cohort, sitting, admin_headers
):
    preview = client.get(
        f"/api/admin/sittings/{sitting['id']}/pass-mark/preview",
        params={"value": 2},
        headers=admin_headers,
    ).json()
    assert preview == {
        "current": None, "value": 2, "newly_below": 2, "no_longer_below": 0,
        "sitting_closed": False, "emails_now": 0,
    }  # fmt: skip

    assert set_mark(client, admin_headers, sitting, 2).json()["queued"] == 0
    assert result_emails(db) == []  # an open sitting sends nothing: the mark can still be tuned

    closed = client.post(
        f"/api/admin/sittings/{sitting['id']}/close", json={"force": True}, headers=admin_headers
    )
    assert closed.status_code == 200, closed.text
    rejected = {r.to_address: r for r in result_emails(db)}
    assert sorted(rejected) == ["p2@example.org", "p3@example.org"]
    one = rejected["p2@example.org"].body
    assert "Your result: 1 of 2 questions correct. The pass mark for this sitting was 2." in one
    assert "Dear Person 2," in one
    assert rejected["p2@example.org"].kind == "not_passed"
    # the rule is written down
    notes = [
        a.detail for a in db.scalars(select(AuditLog)) if a.detail and "pass mark 2" in a.detail
    ]
    assert len(notes) == 1 and "2 rejection emails" in notes[0]


def test_the_rule_never_reads_flags_and_runs_once(db, clock, settings, sitting, cohort):
    row_sitting = db.get(Sitting, sitting["id"])
    row_sitting.pass_mark = 2
    flagged_low = db.get(TestSession, f"s-{cohort[3]}")
    for sq in flagged_low.questions:
        sq.correct = False  # flagged, undecided, and now under the mark
    db.flush()
    close(db, sitting)

    assert outcomes.apply_score_rule(db, clock, settings, row_sitting) == 3  # persons 2, 3, 4
    assert outcomes.apply_score_rule(db, clock, settings, row_sitting) == 0  # and only once
    assert sorted(r.to_address for r in result_emails(db)) == [
        "p2@example.org", "p3@example.org", "p4@example.org",
    ]  # fmt: skip
    assert all("flag" not in r.body.lower() for r in result_emails(db))
    assert db.get(TestSession, f"s-{cohort[3]}").result_basis == "score"


def test_changing_the_mark_of_a_closed_sitting_never_touches_anyone_already_emailed(
    client, db, cohort, sitting, admin_headers
):
    close(db, sitting)
    assert set_mark(client, admin_headers, sitting, 2).json() == {"pass_mark": 2, "queued": 2}
    first = sorted(r.id for r in result_emails(db))

    preview = client.get(
        f"/api/admin/sittings/{sitting['id']}/pass-mark/preview",
        params={"value": 1},
        headers=admin_headers,
    ).json()
    assert (preview["newly_below"], preview["no_longer_below"]) == (0, 0)  # told already

    assert set_mark(client, admin_headers, sitting, 1).json()["queued"] == 0
    assert sorted(r.id for r in result_emails(db)) == first  # no one was written to again
    assert db.get(TestSession, f"s-{cohort[1]}").result == "fail"  # and their result stands


def test_a_candidate_without_an_address_is_marked_but_not_written_to_and_can_be_cleared(
    client, db, clock, settings, sitting, admin_headers
):
    anonymous = client.post(
        "/api/admin/invites", json={"count": 1, "sitting_id": sitting["id"]}, headers=admin_headers
    ).json()["invites"][0]["candidate_id"]
    finished(db, clock, sitting["id"], anonymous, correct=0)
    close(db, sitting)
    row_sitting = db.get(Sitting, sitting["id"])

    assert set_mark(client, admin_headers, sitting, 1).json()["queued"] == 0
    session = db.get(TestSession, f"s-{anonymous}")
    assert (session.result, session.result_basis) == ("fail", "score")
    assert result_emails(db) == []

    outcomes.set_pass_mark(
        db,
        clock,
        settings,
        create_reviewer(db, clock, email="a2@example.com", password=PASSWORD, role="admin")[0],
        row_sitting,
        None,
    )
    assert db.get(TestSession, f"s-{anonymous}").result is None  # no mark: nothing to be failed by


# ------------------------------------------------------------------------- the outcomes list


def test_a_reviewer_sees_every_status_by_id_and_never_a_name(
    client, db, cohort, sitting, reviewer_headers
):
    seen = client.get(
        "/api/review/outcomes", params={"sitting": sitting["id"]}, headers=reviewer_headers
    )
    assert seen.status_code == 200, seen.text
    body = seen.json()
    assert body["total"] == 6 and body["pass_mark"] is None
    assert body["counts"] == {
        "invited": 1, "in_progress": 0, "waiting_review": 1, "in_review": 1, "ready": 3,
        "passed": 0, "failed_score": 0, "failed_review": 0, "under_appeal": 0, "incomplete": 0,
    }  # fmt: skip
    assert body["email_counts"]["none"] == 6
    by_id = {i["candidate_id"]: i for i in body["items"]}
    assert by_id[cohort[0]]["score"] == 2 and by_id[cohort[0]]["can_mark_passed"] is True
    assert by_id[cohort[3]]["status"] == "waiting_review" and by_id[cohort[3]]["flag_count"] == 1
    assert by_id[cohort[3]]["can_mark_passed"] is False  # review it first
    assert by_id[cohort[4]]["can_mark_passed"] is True
    assert by_id[cohort[5]]["score"] is None
    assert "Person" not in seen.text and "example.org" not in seen.text
    assert all(not {"name", "email"} & set(item) for item in body["items"])


def test_the_list_filters_searches_and_pages(client, db, cohort, sitting, reviewer_headers):
    def ask(**params):
        return client.get(
            "/api/review/outcomes",
            params={"sitting": sitting["id"]} | params,
            headers=reviewer_headers,
        ).json()

    ready = ask(status="ready")
    assert (ready["matching"], len(ready["items"])) == (3, 3)
    assert ask(q=cohort[1].upper())["matching"] == 1
    assert ask(page=2)["items"] == [] and ask(page=2)["page"] == 2
    record(client, reviewer_headers, sitting, cohort[0], {"result": "pass"})
    assert ask(email="queued")["matching"] == 1
    assert ask(status="passed")["items"][0]["email_state"] == "queued"
    assert (
        client.get(
            "/api/review/outcomes", params={"status": "bogus"}, headers=reviewer_headers
        ).status_code
        == 422
    )


def test_the_admins_list_has_names_and_masked_addresses_and_a_csv_only_they_can_get(
    client, db, cohort, sitting, admin_headers, reviewer_headers
):
    db.get(Candidate, cohort[1]).full_name = "=SUM(1+1)"  # a name a spreadsheet would run
    db.flush()
    page = client.get(
        "/api/admin/outcomes", params={"sitting": sitting["id"]}, headers=admin_headers
    ).json()
    first = next(i for i in page["items"] if i["candidate_id"] == cohort[0])
    assert (first["name"], first["email"]) == ("Person 1", "p***@example.org")
    assert client.get("/api/admin/outcomes", headers=reviewer_headers).status_code == 403

    export = client.get(
        "/api/admin/outcomes.csv", params={"sitting": sitting["id"]}, headers=admin_headers
    )
    assert export.status_code == 200 and "attachment" in export.headers["content-disposition"]
    assert "p1@example.org" in export.text and "ready" in export.text
    assert "'=SUM(1+1)" in export.text  # defused, not a formula
    assert client.get("/api/admin/outcomes.csv", headers=reviewer_headers).status_code == 403


def test_an_admin_can_mark_a_failed_candidate_as_under_appeal(
    client, db, cohort, sitting, admin_headers, reviewer_headers
):
    record(client, reviewer_headers, sitting, cohort[2], {"result": "fail", "reason_key": "copy"})
    record(client, reviewer_headers, sitting, cohort[0], {"result": "pass"})
    url = "/api/admin/candidates/{}/appeal"
    params = {"sitting": sitting["id"]}

    assert (
        client.post(
            url.format(cohort[2]),
            params=params,
            json={"under_appeal": True},
            headers=reviewer_headers,
        ).status_code
        == 403
    )
    assert (
        client.post(
            url.format(cohort[0]), params=params, json={"under_appeal": True}, headers=admin_headers
        ).json()["code"]
        == "not_failed"
    )  # someone who passed has nothing to appeal

    marked = client.post(
        url.format(cohort[2]), params=params, json={"under_appeal": True}, headers=admin_headers
    )
    assert marked.status_code == 204
    counts = client.get(
        "/api/review/outcomes", params={"sitting": sitting["id"]}, headers=reviewer_headers
    ).json()["counts"]
    assert counts["under_appeal"] == 1 and counts["failed_review"] == 0
    client.post(
        url.format(cohort[2]), params=params, json={"under_appeal": False}, headers=admin_headers
    )
    assert db.get(TestSession, f"s-{cohort[2]}").appeal_at is None


def test_the_sitting_page_summary_counts_what_has_gone_and_who_is_waiting(
    client, db, clock, cohort, sitting, admin_headers, reviewer_headers
):
    record(client, reviewer_headers, sitting, cohort[0], {"result": "pass"})
    mail.send_queued(db, clock, FakeMailer())
    record(client, reviewer_headers, sitting, cohort[1], {"result": "fail", "reason_key": "copy"})
    body = client.get(f"/api/admin/sittings/{sitting['id']}/results", headers=admin_headers).json()
    assert (body["sent_passed"], body["sent_not_passed"], body["queued"], body["failed"]) == (
        1, 0, 1, 0,
    )  # fmt: skip
    assert sorted(body["held_back"]) == sorted(cohort[2:5])
    assert body["did_not_finish"] == 1 and body["without_email"] == 0
    assert "Dear [candidate's name]," in body["preview_passed"]["body"]
    assert "pass mark for this sitting was [pass mark]" in body["preview_not_passed"]["body"]
    assert (
        "The reason: [the reason the reviewer chose]" in body["preview_not_passed_review"]["body"]
    )


def test_the_candidates_page_shows_the_score_the_mark_and_what_may_be_done(
    client, db, cohort, sitting, admin_headers, reviewer_headers
):
    set_mark(client, admin_headers, sitting, 2)

    def panel(candidate_id):
        page = client.get(
            f"/api/review/candidates/{candidate_id}",
            params={"sitting": sitting["id"]},
            headers=reviewer_headers,
        )
        assert page.status_code == 200, page.text
        return page.json()["result"]

    ready = panel(cohort[0])
    assert (ready["score"], ready["total"], ready["pass_mark"]) == (2, 2, 2)
    assert (ready["status"], ready["can_record"], ready["blocked_by"]) == ("ready", True, None)
    assert {r["key"] for r in ready["reasons"]} == {"focus", "copy", "recording"}

    low = panel(cohort[1])
    assert low["status"] == "failed_score" and low["result"] is None  # shown, not yet decided

    flagged = panel(cohort[3])
    assert (flagged["status"], flagged["can_record"]) == ("waiting_review", False)
    assert flagged["blocked_by"] == "review_first"

    record(client, reviewer_headers, sitting, cohort[0], {"result": "pass"})
    done = panel(cohort[0])
    assert (done["status"], done["result"], done["decided_by"]) == (
        "passed",
        "pass",
        "reviewer@example.com",
    )
    assert (done["email_state"], done["can_record"], done["blocked_by"]) == (
        "queued",
        False,
        "already_emailed",
    )
