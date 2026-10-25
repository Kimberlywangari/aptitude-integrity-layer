"""Questions written for each candidate: the admin makes an AI sitting, a candidate opens their
link, the paper is written in the background, and the test cannot begin until it exists.

The model is replaced by a stand-in that writes arithmetic questions with a known answer. What is
under test is everything around it: the sitting, the background hand-off, the waiting, the failure
and the restart, and that the bank and the flags are untouched.
"""

import random
from contextlib import nullcontext

import pytest
from sqlalchemy import func, select

from app.core.staff_token import issue_staff_token
from app.models import AuditLog, Option, Question, SessionQuestion, Sitting, TestSession
from app.services import admin as admin_service
from app.services import test_flow
from app.services.qgen import jobs, paper
from app.services.qgen.check import LABELS
from app.services.qgen.schema import RawQuestion
from app.services.qgen.writers import WriterUnavailable
from app.services.staff_auth import create_reviewer
from tests.support import Live

PASSWORD = "correct horse battery"


class FactoryWriter:
    """Writes simple sums, each with words no other question shares, and solves them correctly."""

    name = "stub"
    model = "factory-1"

    def __init__(self, fail_after: int | None = None, start: int = 0):
        self.made = start  # questions are numbered from here, so two writers can be told apart
        self.fail_after = fail_after  # a category number after which the model "goes away"
        self.categories: list[str] = []
        self.key: dict[str, str] = {}

    def write(self, category, count, difficulties, avoid):
        self.categories.append(category.key)
        if self.fail_after is not None and len(self.categories) > self.fail_after:
            raise WriterUnavailable("ollama is not running")
        out = []
        for difficulty in difficulties[:count]:
            self.made += 1
            n = self.made
            a, b = random.Random(n).randint(10, 99), random.Random(n + 1000).randint(10, 99)
            right = a + b
            options = [str(right), str(right + 7), str(right - 9), str(right + 21)]
            words = " ".join(f"zq{n}x{k}" for k in range(6))
            text = f"({category.key}) {words}: what is {a} plus {b}?"
            self.key[text] = str(right)
            out.append(
                RawQuestion(
                    difficulty=difficulty,
                    question=text,
                    options=options,
                    correct_index=0,
                    explanation=f"{a} + {b} = {right}.",
                    calculation=f"{a}+{b}",
                )
            )
        return out

    def solve(self, items):
        return [LABELS[options.index(self.key[text])] for text, options in items]


class Background:
    """Stands in for the thread pool: remembers what was launched, runs it when told to."""

    def __init__(self, db):
        self.db = db
        self.launched: list[str] = []

    def launch(self, session_id: str) -> bool:
        self.launched.append(session_id)
        return True

    def run(self, writer) -> list[str]:
        statuses = [paper.write_paper(self.db, sid, writer) for sid in dict.fromkeys(self.launched)]
        self.launched.clear()
        return statuses


@pytest.fixture
def background(db, monkeypatch):
    stand_in = Background(db)
    monkeypatch.setattr(jobs, "launch", stand_in.launch)
    return stand_in


@pytest.fixture
def writer_ready(monkeypatch):
    """The admin screens see a reachable writer."""
    monkeypatch.setattr("app.api.admin.check_available", lambda settings: (True, "Stub (test)."))
    writer = FactoryWriter()
    monkeypatch.setattr(admin_service, "writer_for", lambda settings: writer)
    return writer


@pytest.fixture
def admin_headers(db, clock, settings):
    account, _ = create_reviewer(
        db, clock, email="boss@example.com", password=PASSWORD, role="admin"
    )
    token = issue_staff_token(settings.session_secret, clock, account.id, account.password_hash)
    return {"Authorization": f"Bearer {token}"}


def make_sitting(client, headers, **body):
    payload = {
        "name": "AI sitting",
        "question_mode": "ai",
        "per_section": {"numerical": 2, "logical": 1},
    } | body
    return client.post("/api/admin/sittings", json=payload, headers=headers)


def only_sitting_id(client, headers):
    return client.get("/api/admin/sittings", headers=headers).json()["sittings"][0]["id"]


def paper_state(client, live):
    return client.get(live.url("paper"), headers=live.headers).json()


# ------------------------------------------------------------------------- making the sitting


def test_an_ai_sitting_is_refused_while_the_writer_cannot_be_reached(
    client, admin_headers, monkeypatch
):
    monkeypatch.setattr(
        "app.api.admin.check_available", lambda settings: (False, "Ollama is not running.")
    )
    response = make_sitting(client, admin_headers)
    assert response.status_code == 503
    assert response.json() == {
        "code": "question_writer_unavailable",
        "detail": "Ollama is not running.",
    }


def test_an_ai_sitting_needs_no_question_bank(client, db, admin_headers, writer_ready):
    assert db.scalar(select(func.count()).select_from(Question)) == 0  # nothing in the bank

    response = make_sitting(client, admin_headers, per_section={"numerical": 6, "logical": 10})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["question_mode"] == "ai"
    assert body["question_count"] == 16
    assert body["blueprint"] == {"numerical": 6, "logical": 10}
    detail = db.scalar(select(AuditLog.detail).where(AuditLog.action == "admin"))
    assert detail == 'created sitting "AI sitting" (questions written by AI)'


@pytest.mark.parametrize(
    ("per_section", "status", "code"),
    [
        ({"numerical": 2, "astrology": 3}, 422, "unknown_section"),
        ({"numerical": 0}, 422, "invalid_question_count"),
        ({}, 422, "invalid_question_count"),
        ({"numerical": -1, "logical": 4}, 422, "invalid_question_count"),
        ({"numerical": 31}, 422, "too_many_questions"),
        ({k: 20 for k in ("numerical", "verbal", "logical", "critical thinking", "error checking",
                          "ai competence")}, 422, "too_many_questions"),
    ],
)
def test_an_ai_sitting_checks_its_blueprint(
    client, admin_headers, writer_ready, per_section, status, code
):
    response = make_sitting(client, admin_headers, per_section=per_section)
    assert (response.status_code, response.json()["code"]) == (status, code)


def test_all_seven_categories_are_offered_and_the_status_names_the_writer(
    client, admin_headers, writer_ready
):
    body = client.get("/api/admin/ai-questions/status", headers=admin_headers).json()
    assert [c["key"] for c in body["categories"]] == [
        "numerical", "verbal", "logical", "critical thinking", "error checking",
        "ai competence", "office assistant",
    ]
    assert body["available"] is True and body["detail"] == "Stub (test)."
    assert body["provider"] == "ollama" and body["max_per_category"] == 30


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/api/admin/ai-questions/status"),
        ("post", "/api/admin/ai-questions/sample"),
        ("post", "/api/admin/sittings/1/retry-papers"),
    ],
)
def test_the_new_admin_routes_need_an_admin(client, staff, method, path):
    assert getattr(client, method)(path).status_code == 401
    as_reviewer = getattr(client, method)(path, headers=staff)
    assert (as_reviewer.status_code, as_reviewer.json()) == (403, {"code": "forbidden"})


# ------------------------------------------------------------------- a candidate's paper


@pytest.fixture
def ai_candidate(client, db, seeded, admin_headers, writer_ready, background):
    """A candidate who has opened their link in an AI sitting. Nothing is written yet."""
    assert make_sitting(client, admin_headers).status_code == 200
    live = Live(client, db, seeded.invites[0].token).start()
    return live


def test_opening_the_link_starts_the_writing_and_the_test_waits_for_it(
    client, db, ai_candidate, background
):
    live = ai_candidate
    assert background.launched == [live.session_id]
    assert live.session().paper_status == "pending"
    assert paper_state(client, live) == {
        "status": "pending",
        "written": 0,
        "total": 3,
        "waited_s": 0,
        "can_retry": False,
        "candidate_name": None,
    }

    refused = live.begin()
    assert (refused.status_code, refused.json()) == (
        409,
        {"code": "paper_not_ready", "paper_status": "pending"},
    )
    assert live.session().status == "created"  # and the timer did not start

    assert background.run(FactoryWriter()) == ["ready"]
    assert paper_state(client, live) == {
        "status": "ready",
        "written": 3,
        "total": 3,
        "waited_s": None,
        "can_retry": False,
        "candidate_name": None,
    }
    assert live.begin().status_code == 200


def test_the_paper_has_the_blueprint_in_category_order_and_the_key_is_stored_with_it(
    client, db, ai_candidate, background
):
    live = ai_candidate
    background.run(FactoryWriter())
    rows = db.execute(
        select(SessionQuestion.position, Question)
        .join(Question, Question.id == SessionQuestion.question_id)
        .where(SessionQuestion.session_id == live.session_id)
        .order_by(SessionQuestion.position)
    ).all()

    assert [q.section for _, q in rows] == ["logical", "numerical", "numerical"]
    for _, q in rows:
        assert q.source == "ai" and q.id.startswith("G") and len(q.id) == 16
        assert q.written_by == "stub:factory-1" and q.explanation
        options = db.scalars(select(Option).where(Option.question_id == q.id)).all()
        assert sorted(o.label for o in options) == ["A", "B", "C", "D"]
        right = next(o for o in options if o.label == q.correct_option)
        a, b = (int(x) for x in q.explanation.split(" = ")[0].split(" + "))
        assert right.text == str(a + b)


def test_the_test_runs_on_a_written_paper_like_any_other(
    client, db, clock, ai_candidate, background
):
    live = ai_candidate
    background.run(FactoryWriter())
    assert live.begin().status_code == 200

    first = live.question().json()
    assert first["section"] == "logical" and first["total"] == 3
    assert "zq" in first["text"] and len(first["options"]) == 4
    assert "correct" not in str(first).lower().replace("correct_", "")  # no key in what is sent

    live.answer_everything(clock)
    assert live.session().status == "finished"
    assert test_flow.score(live.session()) == 3


def test_a_model_that_goes_away_keeps_what_was_written_and_the_page_says_it_failed(
    client, db, ai_candidate, background
):
    live = ai_candidate
    assert background.run(FactoryWriter(fail_after=1)) == ["failed"]  # logical done, then gone

    assert paper_state(client, live) == {
        "status": "failed",
        "written": 1,
        "total": 3,
        "waited_s": None,
        "can_retry": True,
        "candidate_name": None,
    }
    assert live.session().paper_error == "ollama is not running"
    assert live.begin().json()["paper_status"] == "failed"
    kept = list(db.scalars(select(SessionQuestion.question_id).where(
        SessionQuestion.session_id == live.session_id)))
    assert len(kept) == 1


def test_trying_again_writes_only_what_is_missing(client, db, ai_candidate, background):
    live = ai_candidate
    background.run(FactoryWriter(fail_after=1))
    kept = db.scalar(select(SessionQuestion.question_id).where(
        SessionQuestion.session_id == live.session_id))

    retry = client.post(live.url("paper/retry"), headers=live.headers)
    assert retry.json() == {
        "status": "pending",
        "written": 1,
        "total": 3,
        "waited_s": 0,
        "can_retry": False,
        "candidate_name": None,
    }
    assert background.launched == [live.session_id]

    healthy = FactoryWriter(start=100)  # different wording from the question already written
    assert background.run(healthy) == ["ready"]
    assert healthy.categories == ["numerical"]  # logical was already on the paper
    rows = db.scalars(select(SessionQuestion).where(
        SessionQuestion.session_id == live.session_id).order_by(SessionQuestion.position)).all()
    assert [r.position for r in rows] == [1, 2, 3]
    assert rows[0].question_id == kept
    assert live.session().paper_error is None


# ------------------------------------------------------------------ the waiting cap


def test_after_ten_minutes_of_waiting_the_candidate_may_ask_again(
    client, db, clock, ai_candidate, background, settings
):
    live = ai_candidate
    assert settings.question_wait_limit_s == 600

    clock.advance(599)
    waiting = paper_state(client, live)
    assert (waiting["waited_s"], waiting["can_retry"]) == (599, False)
    # asking too early changes nothing: work that is going well is not restarted
    background.launched.clear()
    early = client.post(live.url("paper/retry"), headers=live.headers).json()
    assert (early["waited_s"], early["can_retry"]) == (599, False)

    clock.advance(1)
    stale = paper_state(client, live)
    assert (stale["waited_s"], stale["can_retry"]) == (600, True)

    background.launched.clear()
    again = client.post(live.url("paper/retry"), headers=live.headers).json()
    assert (again["status"], again["waited_s"], again["can_retry"]) == ("pending", 0, False)
    assert background.launched == [live.session_id]  # started again, and the wait begins anew

    clock.advance(599)
    assert paper_state(client, live)["can_retry"] is False


def test_asking_again_abandons_a_stuck_run_so_a_new_one_can_start(
    client, db, clock, ai_candidate, background, monkeypatch
):
    live = ai_candidate
    abandoned: list[str] = []
    monkeypatch.setattr(jobs, "abandon", abandoned.append)

    clock.advance(600)
    client.post(live.url("paper/retry"), headers=live.headers)

    assert abandoned == [live.session_id]


def test_a_run_that_takes_too_long_stops_with_what_it_has_and_can_be_asked_again(
    client, db, ai_candidate, background
):
    live = ai_candidate

    status = paper.write_paper(db, live.session_id, FactoryWriter(), timeout_s=1e-9)

    assert status == "failed"
    assert "took too long" in live.session().paper_error
    state = paper_state(client, live)
    assert (state["status"], state["can_retry"]) == ("failed", True)


def test_a_stuck_run_does_not_clear_the_run_that_replaced_it(monkeypatch):
    """Two runs for one candidate: when the old one finally ends, the new one still counts."""
    submitted: list = []

    class Pool:
        def submit(self, fn, *args):
            submitted.append((fn, args))

    monkeypatch.setattr(jobs, "_executor", lambda: Pool())
    monkeypatch.setattr(jobs, "_running", {})
    monkeypatch.setattr(jobs.paper, "write_paper", lambda *args, **kwargs: "ready")
    monkeypatch.setattr(jobs, "SessionLocal", lambda: nullcontext())

    assert jobs.launch("s1") is True
    old = submitted[-1]
    jobs.abandon("s1")
    assert jobs.launch("s1") is True
    new = submitted[-1]

    old[0](*old[1])  # the stuck run finally ends
    assert jobs.is_running("s1")
    new[0](*new[1])
    assert not jobs.is_running("s1")


def test_the_admin_can_restart_a_paper_that_has_waited_too_long_but_not_one_going_well(
    client, db, clock, ai_candidate, background, admin_headers
):
    live = ai_candidate
    sitting = client.get("/api/admin/sittings", headers=admin_headers).json()["sittings"][0]
    url = f"/api/admin/sittings/{sitting['id']}/retry-papers"

    clock.advance(300)
    assert client.post(url, headers=admin_headers).json() == {"restarted": 0}

    clock.advance(300)
    background.launched.clear()
    assert client.post(url, headers=admin_headers).json() == {"restarted": 1}
    assert background.launched == [live.session_id]
    assert paper_state(client, live)["waited_s"] == 0


def test_a_page_that_asks_again_restarts_a_paper_nobody_is_writing(
    client, db, ai_candidate, background
):
    live = ai_candidate
    background.launched.clear()  # the server restarted: whatever was running is gone

    paper_state(client, live)  # the page's next poll

    assert background.launched == [live.session_id]


def test_the_admin_sees_failed_papers_and_can_restart_them(
    client, db, ai_candidate, background, admin_headers
):
    live = ai_candidate
    background.run(FactoryWriter(fail_after=0))
    sitting = client.get("/api/admin/sittings", headers=admin_headers).json()["sittings"][0]
    assert sitting["question_mode"] == "ai"
    assert sitting["counts"]["papers_failed"] == 1 and sitting["counts"]["papers_pending"] == 0

    url = f"/api/admin/sittings/{sitting['id']}/retry-papers"
    response = client.post(url, headers=admin_headers)
    assert response.json() == {"restarted": 1}
    assert background.launched == [live.session_id]
    after = client.get("/api/admin/sittings", headers=admin_headers).json()["sittings"][0]
    assert after["counts"]["papers_failed"] == 0 and after["counts"]["papers_pending"] == 1

    bank = db.scalar(select(Sitting).where(Sitting.question_mode == "bank"))
    again = client.post(f"/api/admin/sittings/{bank.id}/retry-papers", headers=admin_headers)
    assert (again.status_code, again.json()) == (409, {"code": "not_an_ai_sitting"})


def test_the_sitting_page_shows_how_long_each_paper_has_been_waited_for(
    client, db, clock, ai_candidate, background, admin_headers
):
    sitting_id = only_sitting_id(client, admin_headers)
    clock.advance(125)

    row = client.get(f"/api/admin/sittings/{sitting_id}", headers=admin_headers).json()[
        "candidates"
    ][0]
    assert (row["state"], row["paper_status"], row["waited_s"]) == ("opened", "pending", 125)

    background.run(FactoryWriter(fail_after=0))
    row = client.get(f"/api/admin/sittings/{sitting_id}", headers=admin_headers).json()[
        "candidates"
    ][0]
    assert (row["paper_status"], row["waited_s"]) == ("failed", None)
    assert row["paper_error"] == "ollama is not running"


def test_deleting_an_ai_sitting_removes_the_questions_written_for_it_and_only_those(
    client, db, ai_candidate, background, admin_headers
):
    live = ai_candidate
    background.run(FactoryWriter())
    stored = select(func.count()).select_from(Question).where(Question.source != "ai")
    written = select(func.count()).select_from(Question).where(Question.source == "ai")
    bank_before = db.scalar(stored)
    assert db.scalar(written) == 3
    sitting_id = only_sitting_id(client, admin_headers)

    response = client.post(
        f"/api/admin/sittings/{sitting_id}/delete",
        json={"confirm_name": "AI sitting"},
        headers=admin_headers,
    )

    # the seeded code belongs to no sitting, so the code stays and only its session goes
    assert response.json() == {"sessions": 1, "candidates": 0, "questions": 3}
    assert db.scalar(select(func.count()).select_from(Question).where(Question.source == "ai")) == 0
    assert db.scalar(select(func.count()).select_from(Option).where(
        Option.question_id.like("G%"))) == 0
    assert db.scalar(select(func.count()).select_from(Question).where(
        Question.source != "ai")) == bank_before
    assert db.get(TestSession, live.session_id) is None


# ----------------------------------------------------------------- the bank is left alone


def test_written_questions_are_not_part_of_the_bank(
    client, db, seeded, admin_headers, writer_ready, background
):
    before = client.get("/api/admin/questions/summary", headers=admin_headers).json()
    listed = client.get("/api/admin/questions", headers=admin_headers).json()["total"]

    assert make_sitting(client, admin_headers).status_code == 200
    live = Live(client, db, seeded.invites[0].token).start()
    background.run(FactoryWriter())
    assert db.scalar(select(func.count()).select_from(Question).where(Question.source == "ai")) == 3

    assert client.get("/api/admin/questions/summary", headers=admin_headers).json() == before
    assert client.get("/api/admin/questions", headers=admin_headers).json()["total"] == listed
    assert live.session().paper_status == "ready"


def test_a_written_question_is_never_drawn_for_a_bank_sitting(db, seeded):
    db.add(Question(id="Gzzzzzzzzzzzzzzz", section="numerical", difficulty="easy",
                    correct_option="A", text="a written one", source="ai"))
    db.flush()
    for seed in range(40):
        drawn = test_flow.select_questions(db, 12, random.Random(seed))
        assert all(q.source != "ai" for q in drawn)


def test_an_open_ai_sitting_does_not_lock_the_bank(client, db, admin_headers, writer_ready):
    assert make_sitting(client, admin_headers).status_code == 200
    response = client.post("/api/admin/questions/retire-synthetic", headers=admin_headers)
    assert response.status_code == 200


def test_a_bank_sitting_is_ready_at_once(client, db, seeded, background):
    live = Live(client, db, seeded.invites[0].token).start()
    assert paper_state(client, live) == {
        "status": "ready",
        "written": 12,
        "total": 12,
        "waited_s": None,
        "can_retry": False,
        "candidate_name": None,
    }
    assert background.launched == []
    assert live.begin().status_code == 200


# ------------------------------------------------------------------------- try the writer


def test_try_the_writer_shows_one_checked_question_and_stores_nothing(
    client, db, admin_headers, writer_ready
):
    response = client.post(
        "/api/admin/ai-questions/sample",
        json={"category": "numerical", "difficulty": "hard"},
        headers=admin_headers,
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["category"] == "numerical" and body["written_by"] == "stub:factory-1"
    assert len(body["options"]) == 4 and 0 <= body["correct_index"] < 4
    assert body["rounds"] == 1 and body["rejected"] == []
    a, b = (int(x) for x in body["explanation"].rstrip(".").split(" = ")[0].split(" + "))
    assert body["options"][body["correct_index"]] == str(a + b)
    assert db.scalar(select(func.count()).select_from(Question)) == 0


def test_try_the_writer_reports_why_it_failed(client, admin_headers, monkeypatch):
    monkeypatch.setattr("app.api.admin.check_available", lambda settings: (True, "Stub."))
    monkeypatch.setattr(
        admin_service, "writer_for", lambda settings: FactoryWriter(fail_after=0)
    )
    response = client.post(
        "/api/admin/ai-questions/sample", json={"category": "verbal"}, headers=admin_headers
    )
    assert response.status_code == 503 or response.status_code == 502
    assert response.json()["code"] in ("question_writer_failed", "question_writer_unavailable")


def test_try_the_writer_refuses_an_unknown_category(client, admin_headers, writer_ready):
    response = client.post(
        "/api/admin/ai-questions/sample", json={"category": "astrology"}, headers=admin_headers
    )
    assert (response.status_code, response.json()["code"]) == (422, "unknown_section")


def test_the_session_row_default_means_every_older_session_is_ready(db, seeded):
    statuses = set(db.scalars(select(TestSession.paper_status)))
    assert statuses <= {"ready"}


def test_a_reviewer_is_told_which_questions_an_ai_wrote(
    client, db, clock, ai_candidate, background, staff
):
    live = ai_candidate
    background.run(FactoryWriter())
    assert live.begin().status_code == 200
    live.answer_everything(clock)

    candidate = live.session().candidate_id
    log = client.get(f"/api/review/candidates/{candidate}/events", headers=staff).json()

    assert [q["written_by"] for q in log["questions"]] == ["stub:factory-1"] * 3
    assert all("text" not in q for q in log["questions"])  # still no question text, no options
