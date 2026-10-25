"""One sitting, opened up: who was invited and where each person is, and deleting a whole sitting
with everything that belongs to it (and nothing that does not)."""

import pytest
from sqlalchemy import func, select

from app.core.staff_token import issue_staff_token
from app.models import (
    AuditLog,
    Candidate,
    Decision,
    Event,
    Heartbeat,
    Question,
    SessionQuestion,
    Sitting,
    TestSession,
    VideoChunk,
)
from app.services.staff_auth import create_reviewer
from app.services.video.store import LocalVideoStore, chunk_key
from tests.support import Live, webm_header

PASSWORD = "correct horse battery"


@pytest.fixture
def admin_headers(db, clock, settings):
    account, _ = create_reviewer(
        db, clock, email="boss@example.com", password=PASSWORD, role="admin"
    )
    token = issue_staff_token(settings.session_secret, clock, account.id, account.password_hash)
    return {"Authorization": f"Bearer {token}"}


def make_sitting(client, headers, name, **extra):
    body = {
        "name": name,
        "per_section": {"numerical": 2},
        "question_mode": "practice",
    } | extra
    response = client.post("/api/admin/sittings", json=body, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def invite(client, headers, sitting_id, count=1):
    response = client.post(
        "/api/admin/invites", json={"count": count, "sitting_id": sitting_id}, headers=headers
    )
    assert response.status_code == 200, response.text
    return response.json()["invites"]


def detail(client, headers, sitting_id):
    return client.get(f"/api/admin/sittings/{sitting_id}", headers=headers)


def delete(client, headers, sitting_id, name):
    return client.post(
        f"/api/admin/sittings/{sitting_id}/delete", json={"confirm_name": name}, headers=headers
    )


@pytest.fixture
def cohort(client, db, clock, seeded, admin_headers):
    """Four invited to one sitting: one has not used the code, one opened the link, one is part
    way through and one has finished. A second sitting holds one more person."""
    sitting = make_sitting(client, admin_headers, "Graduate intake")
    other = make_sitting(client, admin_headers, "Another one")
    codes = invite(client, admin_headers, sitting["id"], 4)
    elsewhere = invite(client, admin_headers, other["id"], 1)[0]

    opened = Live(client, db, codes[1]["code"]).start()
    part_way = Live(client, db, codes[2]["code"]).start()
    assert part_way.begin().status_code == 200
    part_way.answer_one(clock, 1)
    done = Live(client, db, codes[3]["code"]).start()
    assert done.begin().status_code == 200
    done.answer_everything(clock)
    stranger = Live(client, db, elsewhere["code"]).start()
    return {
        "sitting": sitting,
        "other": other,
        "ids": [c["candidate_id"] for c in codes],
        "opened": opened,
        "part_way": part_way,
        "done": done,
        "stranger": stranger,
    }


# ------------------------------------------------------------------------------ the detail


def test_the_detail_says_where_each_invited_person_is(client, admin_headers, cohort):
    response = detail(client, admin_headers, cohort["sitting"]["id"])

    assert response.status_code == 200
    body = response.json()
    assert body["sitting"]["name"] == "Graduate intake"
    assert body["sitting"]["counts"] == {
        "finished": 1,
        "in_progress": 1,
        "not_started": 2,
        "papers_pending": 0,
        "papers_failed": 0,
    }
    rows = {row["candidate_id"]: row for row in body["candidates"]}
    assert list(rows) == cohort["ids"]  # oldest code first, nobody from the other sitting
    states = [rows[i]["state"] for i in cohort["ids"]]
    assert states == ["not_opened", "opened", "started", "finished"]
    assert [rows[i]["answered"] for i in cohort["ids"]] == [0, 0, 1, 2]
    assert rows[cohort["ids"][0]]["paper_status"] is None  # the link was never opened
    assert rows[cohort["ids"][1]]["paper_status"] == "ready"
    assert rows[cohort["ids"][3]]["finished_at"] is not None


def test_the_detail_carries_nothing_that_could_name_or_sign_in_a_candidate(
    client, admin_headers, cohort
):
    text = detail(client, admin_headers, cohort["sitting"]["id"]).text
    for secret in ("invite_token_hash", "access_token", "code"):
        assert secret not in text


def test_a_sitting_that_does_not_exist_is_a_404(client, admin_headers):
    response = detail(client, admin_headers, 99999)
    assert (response.status_code, response.json()) == (404, {"code": "sitting_not_found"})


@pytest.mark.parametrize(
    ("method", "path"),
    [("get", "/api/admin/sittings/1"), ("post", "/api/admin/sittings/1/delete")],
)
def test_the_detail_and_delete_need_an_admin(client, staff, method, path):
    assert getattr(client, method)(path).status_code == 401
    as_reviewer = getattr(client, method)(path, headers=staff)
    assert (as_reviewer.status_code, as_reviewer.json()) == (403, {"code": "forbidden"})


# ------------------------------------------------------------------------------ deleting


def test_the_name_has_to_be_typed_as_written_or_nothing_is_deleted(
    client, db, admin_headers, cohort
):
    sitting_id = cohort["sitting"]["id"]

    for wrong in ("", "graduate intake", "Graduate", "Another one"):
        response = delete(client, admin_headers, sitting_id, wrong)
        assert (response.status_code, response.json()) == (422, {"code": "name_does_not_match"})

    assert db.get(Sitting, sitting_id) is not None
    assert db.scalar(select(func.count()).select_from(TestSession)) == 4


def test_a_sitting_with_a_test_running_is_refused(client, db, admin_headers, cohort):
    response = delete(client, admin_headers, cohort["sitting"]["id"], "Graduate intake")

    assert (response.status_code, response.json()) == (
        409,
        {"code": "sessions_in_progress", "in_progress": 1},
    )
    assert db.get(Sitting, cohort["sitting"]["id"]) is not None


def test_a_test_whose_time_ran_out_no_longer_blocks_it(client, db, clock, admin_headers, cohort):
    clock.advance(1801)

    response = delete(client, admin_headers, cohort["sitting"]["id"], "Graduate intake")

    assert response.status_code == 200


def test_deleting_removes_the_sitting_and_everything_that_belongs_to_it(
    client, db, clock, settings, admin_headers, cohort
):
    sitting_id = cohort["sitting"]["id"]
    done, part_way = cohort["done"], cohort["part_way"]
    store = LocalVideoStore(settings.video_root_path)
    assert part_way.put_chunk(0, webm_header()).status_code == 200
    assert part_way.events({"client_seq": 1, "type": "focus_lost", "age_ms": 0}).status_code == 200
    chunk = chunk_key(part_way.session_id, 0, 0)
    assert store.exists(chunk)
    assert db.scalar(select(func.count()).select_from(VideoChunk)) >= 1
    assert db.scalar(select(func.count()).select_from(Event)) >= 1
    clock.advance(1801)  # the test that was part way has run out of time
    db.add(Heartbeat(session_id=done.session_id, server_ts=clock.now()))
    db.add(
        Decision(
            session_id=done.session_id,
            reviewer_id=None,
            outcome="no_concern",
            reason="fine",
            decided_at=clock.now(),
        )
    )
    db.add(
        AuditLog(
            reviewer_id=None,
            action="video_view",
            session_id=done.session_id,
            ts=clock.now(),
            detail="looked at the recording",
        )
    )
    db.flush()
    gone_sessions = [cohort[k].session_id for k in ("opened", "part_way", "done")]
    kept_session = cohort["stranger"].session_id

    response = delete(client, admin_headers, sitting_id, "Graduate intake")

    assert response.status_code == 200
    assert response.json() == {"sessions": 3, "candidates": 4, "questions": 0}
    db.expire_all()
    assert db.get(Sitting, sitting_id) is None
    assert db.scalar(select(func.count()).select_from(Candidate).where(
        Candidate.id.in_(cohort["ids"]))) == 0
    for table in (SessionQuestion, Event, Heartbeat, Decision, VideoChunk):
        assert db.scalar(
            select(func.count()).select_from(table).where(table.session_id.in_(gone_sessions))
        ) == 0, table.__name__
    assert not store.exists(chunk)  # the recording is gone too

    # the audit trail stays, no longer pointing at a session that does not exist
    viewed = db.scalar(select(AuditLog).where(AuditLog.action == "video_view"))
    assert viewed is not None and viewed.session_id is None
    note = db.scalar(select(AuditLog.detail).where(AuditLog.detail.like("deleted sitting%")))
    assert note == (
        'deleted sitting "Graduate intake": 3 sessions (1 finished), 1 decision records, '
        "4 candidates, 0 written questions"
    )

    # the other sitting, its person and the question bank are untouched
    assert db.get(Sitting, cohort["other"]["id"]) is not None
    assert db.get(TestSession, kept_session) is not None
    assert db.scalar(select(func.count()).select_from(SessionQuestion).where(
        SessionQuestion.session_id == kept_session)) == 2
    assert db.scalar(select(func.count()).select_from(Question).where(
        Question.source != "ai")) > 0
    assert detail(client, admin_headers, sitting_id).status_code == 404


def test_deleting_an_empty_sitting_works(client, db, seeded, admin_headers):
    sitting = make_sitting(client, admin_headers, "Never used")

    response = delete(client, admin_headers, sitting["id"], "Never used")

    assert (response.status_code, response.json()) == (
        200,
        {"sessions": 0, "candidates": 0, "questions": 0},
    )
    assert db.get(Sitting, sitting["id"]) is None


def test_a_code_from_a_deleted_sitting_no_longer_starts_anything(
    client, db, seeded, admin_headers
):
    sitting = make_sitting(client, admin_headers, "Short lived")
    code = invite(client, admin_headers, sitting["id"])[0]["code"]
    assert delete(client, admin_headers, sitting["id"], "Short lived").status_code == 200

    response = client.post("/api/session/start", json={"token": code})

    assert (response.status_code, response.json()) == (401, {"code": "invalid_invitation"})
    assert db.scalar(select(func.count()).select_from(TestSession)) == 0


def test_deleting_a_sitting_leaves_an_unassigned_code_alone(client, db, seeded, admin_headers):
    unassigned = db.scalar(select(func.count()).select_from(Candidate).where(
        Candidate.sitting_id.is_(None)))
    sitting = make_sitting(client, admin_headers, "Passing through")
    invite(client, admin_headers, sitting["id"], 2)

    response = delete(client, admin_headers, sitting["id"], "Passing through")

    assert response.json()["candidates"] == 2
    assert db.scalar(select(func.count()).select_from(Candidate).where(
        Candidate.sitting_id.is_(None))) == unassigned
