"""The recruiter's setup endpoints: access, sittings, invitations, the bank and the import."""

import pytest
from sqlalchemy import func, select

from app.core.security import hash_token, normalise_invite_code
from app.core.staff_token import issue_staff_token
from app.models import (
    AuditLog,
    Candidate,
    Option,
    Question,
    QuestionStats,
    SessionQuestion,
    Sitting,
    TestSession,
)
from app.services.staff_auth import create_reviewer

PASSWORD = "correct horse battery"
SUMMARY_HEADER = ",".join(
    ["question_id", "section", "correct_option", "difficulty_tag"]
    + ["n_candidates", "pct_correct", "median_s", "p25_s", "p75_s"]
)


@pytest.fixture
def admin_headers(db, clock, settings):
    account, _ = create_reviewer(
        db, clock, email="boss@example.com", password=PASSWORD, role="admin"
    )
    token = issue_staff_token(settings.session_secret, clock, account.id, account.password_hash)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def reviewer_headers(db, clock, settings):
    account, _ = create_reviewer(db, clock, email="rev@example.com", password=PASSWORD)
    token = issue_staff_token(settings.session_secret, clock, account.id, account.password_hash)
    return {"Authorization": f"Bearer {token}"}


def sitting_body(**overrides):
    body = {
        "name": "October sitting",
        "opens_at": None,
        "closes_at": None,
        "duration_s": 1800,
        "question_count": 12,
    }
    return body | overrides


def audit_details(db):
    return [row.detail for row in db.scalars(select(AuditLog).where(AuditLog.action == "admin"))]


def finish_everyone(db, clock, sitting_id):
    """A finished session for every candidate, so nothing is left unfinished."""
    for index, candidate in enumerate(db.scalars(select(Candidate))):
        db.add(
            TestSession(
                id=f"done-{index:03d}",
                candidate_id=candidate.id,
                sitting_id=sitting_id,
                status="finished",
                created_at=clock.now(),
            )
        )
    db.flush()


def close_the_open_sitting(client, headers):
    sittings = client.get("/api/admin/sittings", headers=headers).json()["sittings"]
    open_one = next(s for s in sittings if s["status"] == "open")
    response = client.post(
        f"/api/admin/sittings/{open_one['id']}/close", json={"force": True}, headers=headers
    )
    assert response.status_code == 200


# ---------------------------------------------------------------------------------- access


ROUTES = [
    ("get", "/api/admin/sittings", None),
    ("post", "/api/admin/sittings", sitting_body()),
    ("post", "/api/admin/sittings/1/close", {"force": False}),
    ("post", "/api/admin/invites", {"count": 1}),
    ("get", "/api/admin/questions/summary", None),
    ("post", "/api/admin/questions/import", {"filename": "a.csv", "summary_csv": SUMMARY_HEADER}),
    ("post", "/api/admin/questions/retire-synthetic", None),
]


@pytest.mark.parametrize(("method", "path", "body"), ROUTES)
def test_every_admin_route_needs_a_signed_in_admin(client, reviewer_headers, method, path, body):
    anonymous = getattr(client, method)(path, json=body) if body else getattr(client, method)(path)
    assert anonymous.status_code == 401

    kwargs = {"headers": reviewer_headers} | ({"json": body} if body else {})
    as_reviewer = getattr(client, method)(path, **kwargs)
    assert as_reviewer.status_code == 403
    assert as_reviewer.json() == {"code": "forbidden"}


# ---------------------------------------------------------------------------------- sittings


def test_the_list_counts_finished_in_progress_and_not_started(
    client, db, clock, seeded, admin_headers
):
    sittings = client.get("/api/admin/sittings", headers=admin_headers).json()["sittings"]
    assert len(sittings) == 1
    assert sittings[0]["name"] == "Synthetic sitting 1"
    assert sittings[0]["status"] == "open"
    # 20 invited candidates, nobody has a session yet
    assert sittings[0]["counts"] == {"finished": 0, "in_progress": 0, "not_started": 20}

    sitting_id = sittings[0]["id"]
    candidates = list(db.scalars(select(Candidate).order_by(Candidate.id)))
    statuses = ("finished", "finished", "in_progress", "created")
    for status, candidate in zip(statuses, candidates, strict=False):
        db.add(
            TestSession(
                id=f"s-{candidate.id}",
                candidate_id=candidate.id,
                sitting_id=sitting_id,
                status=status,
                created_at=clock.now(),
            )
        )
    db.flush()

    counts = client.get("/api/admin/sittings", headers=admin_headers).json()["sittings"][0][
        "counts"
    ]
    # the "created" session and the 16 candidates with no session are both "not started"
    assert counts == {"finished": 2, "in_progress": 1, "not_started": 17}


def test_a_closed_sitting_does_not_count_later_invitations_as_not_started(
    client, db, clock, seeded, admin_headers
):
    close_the_open_sitting(client, admin_headers)
    counts = client.get("/api/admin/sittings", headers=admin_headers).json()["sittings"][0][
        "counts"
    ]
    assert counts == {"finished": 0, "in_progress": 0, "not_started": 0}


def test_a_sitting_can_be_created_and_is_audited(client, db, seeded, admin_headers):
    response = client.post("/api/admin/sittings", json=sitting_body(), headers=admin_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "October sitting"
    assert body["status"] == "open"
    assert body["counts"] == {"finished": 0, "in_progress": 0, "not_started": 20}
    assert db.scalar(select(func.count()).select_from(Sitting)) == 2
    assert audit_details(db) == ['created sitting "October sitting"']

    newest_first = client.get("/api/admin/sittings", headers=admin_headers).json()["sittings"]
    assert [s["name"] for s in newest_first] == ["October sitting", "Synthetic sitting 1"]


@pytest.mark.parametrize(
    ("overrides", "status", "code"),
    [
        ({"name": "   "}, 422, "name_required"),
        ({"name": "x" * 101}, 422, "name_too_long"),
        ({"duration_s": 59}, 422, "invalid_duration"),
        ({"question_count": 0}, 422, "invalid_question_count"),
        (
            {"opens_at": "2026-10-20T10:00:00Z", "closes_at": "2026-10-20T09:00:00Z"},
            422,
            "invalid_window",
        ),
        ({"name": "Synthetic sitting 1"}, 409, "name_taken"),
    ],
)
def test_a_sitting_with_a_problem_is_refused_with_a_code(
    client, db, seeded, admin_headers, overrides, status, code
):
    response = client.post(
        "/api/admin/sittings", json=sitting_body(**overrides), headers=admin_headers
    )
    assert response.status_code == status
    assert response.json()["code"] == code
    assert audit_details(db) == []


def test_a_sitting_cannot_ask_for_more_questions_than_the_bank_has(client, seeded, admin_headers):
    response = client.post(
        "/api/admin/sittings", json=sitting_body(question_count=61), headers=admin_headers
    )
    assert response.status_code == 409
    assert response.json() == {"code": "question_bank_too_small", "available": 60}


def test_closing_needs_force_while_candidates_are_unfinished(client, db, seeded, admin_headers):
    sitting_id = client.get("/api/admin/sittings", headers=admin_headers).json()["sittings"][0][
        "id"
    ]

    refused = client.post(
        f"/api/admin/sittings/{sitting_id}/close", json={"force": False}, headers=admin_headers
    )
    assert refused.status_code == 409
    assert refused.json() == {"code": "sessions_unfinished", "unfinished": 20}
    assert db.get(Sitting, sitting_id).status == "open"

    forced = client.post(
        f"/api/admin/sittings/{sitting_id}/close", json={"force": True}, headers=admin_headers
    )
    assert forced.status_code == 200
    assert forced.json() == {"status": "closed", "forced": True}
    assert db.get(Sitting, sitting_id).status == "closed"
    assert audit_details(db) == ['closed sitting "Synthetic sitting 1" (forced, 20 unfinished)']


def test_a_sitting_everyone_finished_closes_without_force(client, db, clock, seeded, admin_headers):
    sitting_id = client.get("/api/admin/sittings", headers=admin_headers).json()["sittings"][0][
        "id"
    ]
    finish_everyone(db, clock, sitting_id)

    response = client.post(f"/api/admin/sittings/{sitting_id}/close", headers=admin_headers)

    assert response.status_code == 200
    assert response.json() == {"status": "closed", "forced": False}
    assert audit_details(db) == ['closed sitting "Synthetic sitting 1"']


def test_closing_twice_or_closing_nothing_is_refused(client, seeded, admin_headers):
    sitting_id = client.get("/api/admin/sittings", headers=admin_headers).json()["sittings"][0][
        "id"
    ]
    client.post(
        f"/api/admin/sittings/{sitting_id}/close", json={"force": True}, headers=admin_headers
    )

    again = client.post(f"/api/admin/sittings/{sitting_id}/close", headers=admin_headers)
    assert (again.status_code, again.json()["code"]) == (409, "already_closed")

    missing = client.post("/api/admin/sittings/9999/close", headers=admin_headers)
    assert (missing.status_code, missing.json()["code"]) == (404, "sitting_not_found")


# ---------------------------------------------------------------------------------- invitations


def test_invites_continue_the_numbering_and_store_only_hashes(client, db, seeded, admin_headers):
    response = client.post("/api/admin/invites", json={"count": 3}, headers=admin_headers)

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    invites = response.json()["invites"]
    assert [i["candidate_id"] for i in invites] == ["cand-021", "cand-022", "cand-023"]
    for invite in invites:
        assert len(invite["code"]) == 8
        stored = db.get(Candidate, invite["candidate_id"])
        assert stored.invite_token_hash == hash_token(invite["code"])
        assert invite["code"] not in stored.invite_token_hash
    assert audit_details(db) == ["generated 3 invitations"]
    assert all(i["code"] not in (d or "") for d in audit_details(db) for i in invites)


def test_a_generated_code_starts_a_session_typed_the_way_a_candidate_would(
    client, db, seeded, admin_headers
):
    code = client.post("/api/admin/invites", json={"count": 1}, headers=admin_headers).json()[
        "invites"
    ][0]["code"]
    typed = f"{code[:4].lower()}-{code[4:]}"
    assert normalise_invite_code(typed) == code

    started = client.post("/api/session/start", json={"token": typed})
    assert started.status_code == 200


@pytest.mark.parametrize("count", [0, -1, 501])
def test_an_invite_count_outside_one_to_five_hundred_is_refused(
    client, seeded, admin_headers, count
):
    response = client.post("/api/admin/invites", json={"count": count}, headers=admin_headers)
    assert (response.status_code, response.json()["code"]) == (422, "invalid_count")


def test_invites_start_from_one_in_an_empty_database(client, db, admin_headers):
    invites = client.post("/api/admin/invites", json={"count": 2}, headers=admin_headers).json()
    assert [i["candidate_id"] for i in invites["invites"]] == ["cand-001", "cand-002"]


# ---------------------------------------------------------------------------------- the bank


def test_the_bank_summary_splits_placeholders_from_real_questions(client, seeded, admin_headers):
    summary = client.get("/api/admin/questions/summary", headers=admin_headers).json()
    assert summary["total"] == 60
    assert summary["cytonn"] == 0
    assert summary["synthetic"] == 60
    assert [s["section"] for s in summary["by_section"]] == ["logical", "numerical", "verbal"]
    assert all(s["count"] == 20 and s["synthetic"] == 20 for s in summary["by_section"])


def test_placeholders_are_retired_but_a_question_a_paper_uses_is_kept(
    client, db, clock, seeded, admin_headers
):
    sitting_id = db.scalar(select(Sitting.id))
    db.add(
        TestSession(
            id="drew-one",
            candidate_id="cand-001",
            sitting_id=sitting_id,
            status="finished",
            created_at=clock.now(),
        )
    )
    db.flush()
    db.add(SessionQuestion(session_id="drew-one", position=1, question_id="Q001", option_order=[]))
    db.flush()
    close_the_open_sitting(client, admin_headers)

    response = client.post("/api/admin/questions/retire-synthetic", headers=admin_headers)

    assert response.status_code == 200
    assert response.json() == {"removed": 59, "kept": 1}
    assert db.scalars(select(Question.id)).all() == ["Q001"]
    assert (
        audit_details(db)[-1]
        == "removed 59 placeholder questions (1 kept: an earlier session used them)"
    )


def test_the_bank_does_not_change_while_a_sitting_is_open(client, seeded, admin_headers):
    retire = client.post("/api/admin/questions/retire-synthetic", headers=admin_headers)
    assert (retire.status_code, retire.json()["code"]) == (409, "sitting_open")

    imported = client.post(
        "/api/admin/questions/import",
        json={"filename": "a.csv", "summary_csv": SUMMARY_HEADER},
        headers=admin_headers,
    )
    assert (imported.status_code, imported.json()["code"]) == (409, "sitting_open")


# ---------------------------------------------------------------------------------- the import


@pytest.fixture
def closed_bank(client, seeded, admin_headers):
    close_the_open_sitting(client, admin_headers)


def do_import(client, headers, summary, bank=None, filename="summary.csv"):
    return client.post(
        "/api/admin/questions/import",
        json={"filename": filename, "summary_csv": summary, "bank_csv": bank},
        headers=headers,
    )


def test_a_file_missing_columns_is_refused_and_says_which(client, closed_bank, admin_headers):
    response = do_import(client, admin_headers, "question_id,section\nQ001,verbal\n")
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "missing_columns"
    assert "correct_option" in body["columns"]
    assert "question_id" not in body["columns"]


def test_existing_questions_get_cytonn_statistics_and_keep_their_text(
    client, db, closed_bank, admin_headers
):
    before = db.get(Question, "Q001")
    text = before.text
    option_ids = [o.id for o in before.options]
    summary = f"{SUMMARY_HEADER}\nQ001,Verbal,b,hard,812,38.5,71,50,96\n"

    response = do_import(client, admin_headers, summary)

    assert response.status_code == 200
    report = response.json()
    assert report["imported"] == 1
    assert report["rejected"] == []
    assert any("no question text" in w for w in report["warnings"])

    question = db.get(Question, "Q001")
    assert (question.section, question.difficulty, question.correct_option) == (
        "verbal",
        "hard",
        "B",
    )
    assert question.text == text
    assert [o.id for o in question.options] == option_ids
    stats = db.get(QuestionStats, "Q001")
    assert (stats.source, stats.n, stats.pct_correct, stats.median_s) == ("cytonn", 812, 38.5, 71)

    summary_after = client.get("/api/admin/questions/summary", headers=admin_headers).json()
    assert (summary_after["cytonn"], summary_after["synthetic"]) == (1, 59)
    assert audit_details(db)[-1] == "imported 1 of 1 questions from summary.csv"


def test_a_new_question_comes_in_with_its_text_and_options_from_the_bank_export(
    client, db, closed_bank, admin_headers
):
    summary = f"{SUMMARY_HEADER}\nR001,numerical,C,,300,80,40,30,55\n"
    bank = (
        "question_id,text,option_a,option_b,option_c,option_d\n"
        'R001,"What is 2 + 2, in total?",3,5,4,22\n'
    )

    response = do_import(client, admin_headers, summary, bank)

    assert response.status_code == 200
    report = response.json()
    assert report["imported"] == 1
    assert report["difficulty_derived"] == 1  # no tag: 80% correct reads as easy
    assert not any("no question text" in w for w in report["warnings"])

    question = db.get(Question, "R001")
    assert question.text == "What is 2 + 2, in total?"
    assert question.difficulty == "easy"
    assert {o.label: o.text for o in question.options} == {"A": "3", "B": "5", "C": "4", "D": "22"}
    assert db.get(QuestionStats, "R001").source == "cytonn"


def test_the_summary_can_carry_the_text_itself(client, db, closed_bank, admin_headers):
    summary = (
        f"{SUMMARY_HEADER},text,option_a,option_b,option_c,option_d\n"
        "R002,logical,A,medium,120,55,33,25,48,Which comes next?,w,x,y,z\n"
    )
    response = do_import(client, admin_headers, summary)
    assert response.json()["imported"] == 1
    assert db.get(Question, "R002").difficulty == "medium"
    assert (
        db.scalar(select(func.count()).select_from(Option).where(Option.question_id == "R002")) == 4
    )


@pytest.mark.parametrize(
    ("row", "reason"),
    [
        (",verbal,A,easy,10,50,20,10,30", "question_id is empty"),
        ("Q001,verbal,E,easy,10,50,20,10,30", "correct_option must be A to D"),
        ("Q001,verbal,A,easy,10,150,20,10,30", "pct_correct above 100"),
        ("Q001,verbal,A,easy,10,50,20,25,30", "p25 <= median <= p75 does not hold"),
        ("Q001,verbal,A,easy,ten,50,20,10,30", "a number is missing or negative"),
        ("Q001,verbal,A,easy,10,-5,20,10,30", "a number is missing or negative"),
        ("Q001,verbal,A,tough,10,50,20,10,30", "difficulty_tag must be easy, medium or hard"),
        ("Q001,,A,easy,10,50,20,10,30", "section is empty or too long"),
        ("NEW1,verbal,A,easy,10,50,20,10,30", "a new question needs its text and options A to D"),
    ],
)
def test_a_bad_row_is_rejected_with_its_row_number_and_nothing_else_is_stopped(
    client, db, closed_bank, admin_headers, row, reason
):
    good = "Q002,verbal,A,easy,10,50,20,10,30"
    summary = f"{SUMMARY_HEADER}\n{row}\n{good}\n"

    report = do_import(client, admin_headers, summary).json()

    assert report["rows"] == 2
    assert report["imported"] == 1
    assert len(report["rejected"]) == 1
    rejected = report["rejected"][0]
    assert rejected["row"] == 2  # the first data row, counting the header
    assert rejected["reason"].startswith(reason)
    assert db.get(QuestionStats, "Q002").source == "cytonn"


def test_a_repeated_question_id_in_one_file_is_rejected(client, closed_bank, admin_headers):
    summary = (
        f"{SUMMARY_HEADER}\nQ001,verbal,A,easy,10,50,20,10,30\nQ001,verbal,B,easy,10,50,20,10,30\n"
    )
    report = do_import(client, admin_headers, summary).json()
    assert report["imported"] == 1
    assert report["rejected"] == [
        {"row": 3, "question_id": "Q001", "reason": "duplicate question_id"}
    ]


def test_a_file_with_a_windows_line_ending_and_extra_blank_lines_reads_the_same(
    client, closed_bank, admin_headers
):
    summary = f"{SUMMARY_HEADER}\r\nQ001,verbal,A,easy,10,50,20,10,30\r\n\r\n"
    assert do_import(client, admin_headers, summary).json()["imported"] == 1


def test_a_bank_export_without_question_ids_is_refused(client, closed_bank, admin_headers):
    summary = f"{SUMMARY_HEADER}\nQ001,verbal,A,easy,10,50,20,10,30\n"
    response = do_import(client, admin_headers, summary, bank="text,option_a\nhello,x\n")
    assert response.status_code == 422
    assert response.json()["columns"] == ["question_id"]
