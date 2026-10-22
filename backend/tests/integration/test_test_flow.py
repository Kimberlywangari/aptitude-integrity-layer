"""The candidate's test, end to end through the HTTP API with a fake clock."""

from collections import Counter

import pytest

from app.core.security import format_invite_code, hash_token
from app.models import Candidate as CandidateRow
from app.models import Question, SessionQuestion, TestSession
from app.services import test_flow

DURATION = 1800
TOTAL = 12


# ------------------------------------------------------------------------------ helpers


class Candidate:
    """Drives one candidate's session through the API."""

    def __init__(self, client, db, invite_token):
        self.client = client
        self.db = db
        self.invite_token = invite_token
        self.session_id = None
        self.headers = {}

    def start(self):
        response = self.client.post(
            "/api/session/start",
            json={"token": self.invite_token},
        )
        if response.status_code == 200:
            body = response.json()
            self.session_id = body["session_id"]
            self.headers = {"Authorization": f"Bearer {body['access_token']}"}
        return response

    def url(self, tail):
        return f"/api/session/{self.session_id}/{tail}"

    def begin(self, accepted=True):
        return self.client.post(
            self.url("begin"), json={"accepted": accepted}, headers=self.headers
        )

    def question(self):
        return self.client.get(self.url("question"), headers=self.headers)

    def answer(self, position, option_id):
        return self.client.post(
            self.url("answer"),
            json={"position": position, "option_id": option_id},
            headers=self.headers,
        )

    def skip(self, position):
        return self.client.post(
            self.url("skip"),
            json={"position": position},
            headers=self.headers,
        )

    def finish(self):
        return self.client.post(self.url("finish"), headers=self.headers)

    def self_report(self, **body):
        return self.client.post(self.url("self-report"), json=body, headers=self.headers)

    def row(self, position):
        self.db.expire_all()
        return self.db.get(SessionQuestion, (self.session_id, position))

    def session(self):
        self.db.expire_all()
        return self.db.get(TestSession, self.session_id)

    def correct_option_id(self, position):
        sq = self.row(position)
        question = self.db.get(Question, sq.question_id)
        return next(o.id for o in question.options if o.label == question.correct_option)

    def wrong_option_id(self, position):
        sq = self.row(position)
        return next(i for i in sq.option_order if i != self.correct_option_id(position))


@pytest.fixture
def candidate(client, db, seeded):
    return Candidate(client, db, seeded.invites[0].token)


@pytest.fixture
def running(candidate):
    """A candidate who has started, accepted the statement and is on question 1."""
    assert candidate.start().status_code == 200
    assert candidate.begin().status_code == 200
    return candidate


# ------------------------------------------------------------------------------ start


def test_start_creates_a_session_with_a_token_and_no_running_timer(candidate):
    response = candidate.start()
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "created"
    assert body["session_id"] and body["access_token"]
    session = candidate.session()
    assert session.started_at is None and session.ends_at is None


def test_unknown_invitation_is_refused(client, seeded):
    response = client.post("/api/session/start", json={"token": "not-a-real-token"})
    assert response.status_code == 401
    assert response.json() == {"code": "invalid_invitation"}


def test_starting_again_returns_the_same_session_and_replaces_the_token(candidate):
    first = candidate.start().json()
    old_headers = dict(candidate.headers)
    second = candidate.start().json()

    assert second["session_id"] == first["session_id"]
    assert second["access_token"] != first["access_token"]
    stale = candidate.client.get(candidate.url("question"), headers=old_headers)
    assert stale.status_code == 401


def test_no_open_sitting_is_refused(client, db, seeded):
    from app.models import Sitting

    db.query(Sitting).update({"status": "closed"})
    db.flush()
    response = client.post("/api/session/start", json={"token": seeded.invites[0].token})
    assert response.status_code == 403
    assert response.json() == {"code": "no_open_sitting"}


def test_a_typed_code_with_a_dash_and_lower_case_starts_the_same_session(client, seeded):
    code = seeded.invites[0].token
    exact = client.post("/api/session/start", json={"token": code})
    typed = client.post("/api/session/start", json={"token": format_invite_code(code).lower()})
    assert typed.status_code == 200
    assert typed.json()["session_id"] == exact.json()["session_id"]


def test_a_long_token_from_the_first_seed_still_works(client, db, seeded):
    legacy = "a3f9c1d2e4b5a6f7c8d9e0f1"
    db.add(CandidateRow(id="cand-legacy", invite_token_hash=hash_token(legacy)))
    db.flush()
    response = client.post("/api/session/start", json={"token": f"  {legacy}  "})
    assert response.status_code == 200


def test_wrong_codes_are_refused_with_429_after_the_limit_and_released_later(
    client, seeded, settings, clock
):
    for _ in range(settings.start_max_failures):
        response = client.post("/api/session/start", json={"token": "ZZZZ-ZZZZ"})
        assert response.status_code == 401

    blocked = client.post("/api/session/start", json={"token": "ZZZZ-ZZZZ"})
    assert blocked.status_code == 429
    body = blocked.json()
    assert body["code"] == "too_many_attempts"
    assert 0 < body["retry_after_s"] <= settings.start_window_s

    clock.advance(settings.start_window_s + 1)
    again = client.post("/api/session/start", json={"token": "ZZZZ-ZZZZ"})
    assert again.status_code == 401


def test_a_blocked_client_cannot_start_even_with_a_right_code(client, seeded, settings):
    for _ in range(settings.start_max_failures):
        client.post("/api/session/start", json={"token": "ZZZZ-ZZZZ"})
    response = client.post("/api/session/start", json={"token": seeded.invites[0].token})
    assert response.status_code == 429


def test_successful_starts_never_count_towards_the_limit(client, seeded, settings):
    # a venue of honest candidates behind one address must not lock itself out
    for invite in seeded.invites * 3:
        response = client.post("/api/session/start", json={"token": invite.token})
        assert response.status_code == 200


def test_forwarded_for_is_only_trusted_when_configured(client, seeded, settings):
    def attempt(address):
        return client.post(
            "/api/session/start",
            json={"token": "ZZZZ-ZZZZ"},
            headers={"X-Forwarded-For": f"1.1.1.1, {address}"},
        )

    # not trusted: every request is the same peer, so spreading headers does not help
    for i in range(settings.start_max_failures):
        attempt(f"10.0.0.{i}")
    assert attempt("10.0.0.250").status_code == 429


def test_each_proxied_client_has_its_own_count_when_the_proxy_is_trusted(client, seeded, settings):
    settings.trust_forwarded_for = True
    for _ in range(settings.start_max_failures):
        client.post(
            "/api/session/start",
            json={"token": "ZZZZ-ZZZZ"},
            headers={"X-Forwarded-For": "9.9.9.9, 10.0.0.1"},
        )
    other = client.post(
        "/api/session/start",
        json={"token": seeded.invites[0].token},
        headers={"X-Forwarded-For": "9.9.9.9, 10.0.0.2"},
    )
    assert other.status_code == 200
    same = client.post(
        "/api/session/start",
        json={"token": seeded.invites[0].token},
        headers={"X-Forwarded-For": "9.9.9.9, 10.0.0.1"},
    )
    assert same.status_code == 429


# ------------------------------------------------------------------------------ the paper


def test_paper_has_twelve_questions_four_from_each_section(candidate, db):
    candidate.start()
    rows = candidate.session().questions
    assert [r.position for r in rows] == list(range(1, TOTAL + 1))
    sections = Counter(db.get(Question, r.question_id).section for r in rows)
    assert sections == {"numerical": 4, "verbal": 4, "logical": 4}
    assert len({r.question_id for r in rows}) == TOTAL


def test_same_session_keeps_questions_and_option_order(candidate):
    candidate.start()
    before = [(r.question_id, list(r.option_order)) for r in candidate.session().questions]
    candidate.start()  # a reload or restart must not rebuild the paper
    after = [(r.question_id, list(r.option_order)) for r in candidate.session().questions]
    assert before == after


def test_different_candidates_get_different_papers(client, db, seeded):
    papers = []
    for invite in seeded.invites[:3]:
        person = Candidate(client, db, invite.token)
        person.start()
        papers.append([r.question_id for r in person.session().questions])
    assert len({tuple(p) for p in papers}) == 3


# ------------------------------------------------------------------------------ begin and timer


def test_question_is_refused_before_the_statement_is_accepted(candidate):
    candidate.start()
    response = candidate.question()
    assert response.status_code == 409
    assert response.json()["code"] == "not_started"


def test_begin_needs_the_statement_accepted(candidate):
    candidate.start()
    response = candidate.begin(accepted=False)
    assert response.status_code == 422
    assert candidate.session().status == "created"


def test_timer_starts_at_begin_not_at_start(candidate, clock):
    candidate.start()
    clock.advance(600)  # reading the statement costs no test time
    response = candidate.begin()
    assert response.json() == {"status": "in_progress", "remaining_s": DURATION}


def test_begin_twice_does_not_reset_the_timer(candidate, clock):
    candidate.start()
    candidate.begin()
    ends_at = candidate.session().ends_at
    clock.advance(100)
    response = candidate.begin()
    assert response.status_code == 200
    assert response.json()["remaining_s"] == DURATION - 100
    assert candidate.session().ends_at == ends_at


def test_question_has_shuffled_opaque_options_and_no_answer_key(running, db):
    body = running.question().json()
    assert body["position"] == 1 and body["total"] == TOTAL
    assert body["remaining_s"] == DURATION
    assert len(body["options"]) == 4
    assert set(body) == {"position", "total", "section", "text", "options", "remaining_s"}
    for option in body["options"]:
        assert set(option) == {"id", "text"}
    assert [o["id"] for o in body["options"]] == list(running.row(1).option_order)


def test_reload_keeps_the_question_clock_and_the_remaining_time(running, clock):
    first = running.question().json()
    opened_at = running.row(1).opened_at
    clock.advance(40)
    again = running.question().json()
    clock.advance(5)
    third = running.question().json()

    assert again["position"] == third["position"] == first["position"] == 1
    assert running.row(1).opened_at == opened_at
    assert again["remaining_s"] == DURATION - 40
    assert third["remaining_s"] == DURATION - 45


# ------------------------------------------------------------------------------ answering


def test_correct_answer_is_marked_correct_and_advances(running, clock):
    running.question()
    clock.advance(20)
    response = running.answer(1, running.correct_option_id(1))
    assert response.status_code == 200
    assert response.json() == {"done": False, "remaining_s": DURATION - 20}

    row = running.row(1)
    assert row.correct is True and row.skipped is False
    assert (row.answered_at - row.opened_at).total_seconds() == 20
    assert running.question().json()["position"] == 2


def test_wrong_answer_is_marked_incorrect(running):
    running.question()
    running.answer(1, running.wrong_option_id(1))
    assert running.row(1).correct is False


def test_skip_sets_skipped_and_advances(running):
    running.question()
    response = running.skip(1)
    assert response.status_code == 200
    row = running.row(1)
    assert row.skipped is True and row.correct is None and row.selected_option is None
    assert running.question().json()["position"] == 2


def test_cannot_answer_a_question_twice_or_go_back(running):
    running.question()
    running.answer(1, running.correct_option_id(1))
    again = running.answer(1, running.wrong_option_id(1))
    assert again.status_code == 409
    assert again.json() == {"code": "not_current", "current_position": 2}
    assert running.row(1).correct is True  # the first answer stands


def test_cannot_jump_ahead(running):
    running.question()
    response = running.answer(3, running.correct_option_id(3))
    assert response.status_code == 409
    assert response.json()["code"] == "not_current"


def test_option_must_belong_to_the_current_question(running):
    running.question()
    foreign = next(i for i in running.row(2).option_order)
    response = running.answer(1, foreign)
    assert response.status_code == 422
    assert response.json() == {"code": "invalid_option"}
    assert running.row(1).answered_at is None


def test_answering_without_opening_still_records_a_time(running, clock):
    clock.advance(7)
    running.answer(1, running.correct_option_id(1))
    row = running.row(1)
    assert row.opened_at == row.answered_at


# ------------------------------------------------------------------------------ finish and time-up


def test_answering_the_last_question_finishes_the_test(running):
    for position in range(1, TOTAL + 1):
        running.question()
        response = running.answer(position, running.correct_option_id(position))
    assert response.json() == {"done": True, "remaining_s": 0.0}
    assert running.session().status == "finished"
    assert test_flow.score(running.session()) == TOTAL

    after = running.question()
    assert after.status_code == 409 and after.json()["code"] == "finished"


def test_finish_is_idempotent_and_counts_answered_and_skipped(running):
    running.question()
    running.answer(1, running.correct_option_id(1))
    running.skip(2)
    first = running.finish()
    finished_at = running.session().finished_at
    second = running.finish()

    assert first.json() == second.json()
    assert first.json() == {
        "status": "finished",
        "total": TOTAL,
        "answered": 1,
        "skipped": 1,
        "unanswered": TOTAL - 2,
    }
    assert running.session().finished_at == finished_at


def test_finish_response_never_contains_the_score(running):
    running.question()
    running.answer(1, running.correct_option_id(1))
    assert "score" not in running.finish().json()


def test_request_after_time_is_up_finishes_the_session_with_410(running, clock):
    running.question()
    running.answer(1, running.correct_option_id(1))
    clock.advance(DURATION + 1)

    response = running.question()
    assert response.status_code == 410
    assert response.json() == {"code": "time_up"}
    session = running.session()
    assert session.status == "finished"
    assert session.finished_at == session.ends_at  # timed out at the deadline, not at the request


def test_answer_after_time_is_up_is_refused_and_not_recorded(running, clock):
    running.question()
    clock.advance(DURATION)  # exactly the deadline counts as over
    response = running.answer(1, running.correct_option_id(1))
    assert response.status_code == 410
    assert running.row(1).answered_at is None


def test_time_up_stays_time_up_and_finish_still_returns_a_summary(running, clock):
    running.question()
    clock.advance(DURATION + 30)
    assert running.question().status_code == 410
    assert running.question().status_code == 410
    summary = running.finish()
    assert summary.status_code == 200
    assert summary.json()["unanswered"] == TOTAL


# ------------------------------------------------------------------------------ self-report


def test_self_report_is_saved_after_the_test(running):
    running.finish()
    response = running.self_report(had_technical_issues=True, note="  wifi dropped twice ")
    assert response.status_code == 204
    assert running.session().self_report == {
        "had_technical_issues": True,
        "note": "wifi dropped twice",
    }


def test_self_report_before_finishing_is_refused(running):
    response = running.self_report(had_technical_issues=False)
    assert response.status_code == 409
    assert response.json()["code"] == "not_finished"


def test_self_report_note_is_capped_at_300_characters(running):
    running.finish()
    assert running.self_report(had_technical_issues=True, note="x" * 301).status_code == 422
    assert running.self_report(had_technical_issues=True, note="x" * 300).status_code == 204


# ------------------------------------------------------------------------------ tokens


def test_token_from_another_session_is_refused(client, db, seeded):
    alice = Candidate(client, db, seeded.invites[0].token)
    bob = Candidate(client, db, seeded.invites[1].token)
    alice.start()
    bob.start()
    alice.begin()

    response = client.get(alice.url("question"), headers=bob.headers)
    assert response.status_code == 401
    assert response.json() == {"code": "unauthorized"}


@pytest.mark.parametrize("header", [None, "", "Bearer", "Bearer wrong", "Basic abc"])
def test_missing_or_bad_authorization_is_refused(candidate, header):
    candidate.start()
    headers = {} if header is None else {"Authorization": header}
    response = candidate.client.get(candidate.url("question"), headers=headers)
    assert response.status_code == 401


def test_unknown_session_looks_the_same_as_a_wrong_token(client, seeded):
    response = client.get("/api/session/nope/question", headers={"Authorization": "Bearer x"})
    assert response.status_code == 401
