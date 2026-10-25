"""The endpoints the rebuilt console reads: the overview, the queue's priority bands, the
invitation list and reissue, the paged question list and a sitting's per-section blueprint."""

import random

import pytest
from sqlalchemy import select

from app.config import Settings
from app.core.security import hash_token, normalise_invite_code
from app.core.staff_token import issue_staff_token
from app.errors import ApiError
from app.models import AuditLog, Candidate, Question, QuestionStats, Sitting, TestSession
from app.services import admin, overview
from app.services.staff_auth import create_reviewer
from app.services.test_flow import select_questions

PASSWORD = "correct horse battery"
SECTIONS = ("logical", "numerical", "verbal")
LONG_REASON = "Only a pace flag and nothing else on the video review."


@pytest.fixture
def admin_headers(db, clock, settings):
    account, _ = create_reviewer(
        db, clock, email="boss@example.com", password=PASSWORD, role="admin"
    )
    token = issue_staff_token(settings.session_secret, clock, account.id, account.password_hash)
    return {"Authorization": f"Bearer {token}"}


# ----------------------------------------------------------------------------- queue and detail


def test_every_queue_item_has_a_strength_a_band_and_a_flag_count(client, sim, staff):
    items = client.get("/api/review/queue", headers=staff).json()["items"]

    assert items
    for item in items:
        assert 1 <= item["strength"] <= 5
        assert item["band"] == {5: "high", 4: "high", 3: "moderate", 2: "low", 1: "low"}[
            item["strength"]
        ]
        assert item["flag_count"] == len(item["flag_kinds"]) >= 1
        if item["logging_only"]:
            assert item["band"] == "low"


def test_the_candidate_page_agrees_with_the_queue_on_strength_and_band(client, sim, staff):
    first = client.get("/api/review/queue", headers=staff).json()["items"][0]
    detail = client.get(f"/api/review/candidates/{first['candidate_id']}", headers=staff).json()
    assert (detail["strength"], detail["band"]) == (first["strength"], first["band"])


# ----------------------------------------------------------------------------------- overview


def test_the_overview_needs_a_signed_in_account(client, sim):
    assert client.get("/api/review/overview").status_code == 401


def test_the_overview_counts_the_sitting(client, sim, staff):
    queue = client.get("/api/review/queue", headers=staff).json()["items"]
    body = client.get("/api/review/overview", headers=staff).json()

    assert body["sitting_id"] == sim.sitting_id
    tiles = body["tiles"]
    assert tiles["flagged"] == len(queue)
    assert tiles["reviewed"] == 0 and body["pending"] == len(queue)
    assert tiles["finished"] == tiles["sat"] == 16
    assert tiles["videos_expected"] == 16
    assert body["sitting_status"] == "closed"

    kinds = {k["kind"]: k["count"] for k in body["flags_by_kind"]}
    assert kinds["COPY_ATTEMPT"] >= 3
    counts = [k["count"] for k in body["flags_by_kind"]]
    assert counts == sorted(counts, reverse=True)

    assert [n["candidate_id"] for n in body["next_up"]] == [i["candidate_id"] for i in queue[:3]]
    assert {n["band"] for n in body["next_up"]} <= {"high", "moderate", "low"}


def test_a_decision_moves_a_candidate_from_pending_to_reviewed(client, db, sim, staff):
    first = client.get("/api/review/queue", headers=staff).json()["items"][0]["candidate_id"]
    session = db.scalar(select(TestSession).where(TestSession.candidate_id == first))
    client.post(
        "/api/review/decisions",
        json={"session_id": session.id, "outcome": "no_concern", "reason": LONG_REASON},
        headers=staff,
    )

    body = client.get("/api/review/overview", headers=staff).json()

    assert body["tiles"]["reviewed"] == 1
    assert body["pending"] == body["tiles"]["flagged"] - 1
    assert first not in [n["candidate_id"] for n in body["next_up"]]
    assert body["tiles"]["videos_decided_not_deleted"] == 1


def test_the_overview_of_an_empty_database_is_all_zeros(client, staff):
    body = client.get("/api/review/overview", headers=staff).json()
    assert body["sitting_id"] == 0 and body["sitting_status"] is None
    assert body["pending"] == 0 and body["next_up"] == [] and body["flags_by_kind"] == []
    assert set(body["tiles"].values()) == {0}
    keys = {c["key"] for c in body["checks"]}
    assert keys >= {"ai", "factcheck", "fallback", "gate", "heartbeat"}


def test_the_checks_say_what_is_set_up():
    def configured(**changes):
        # every field that matters is spelled out, so a developer's .env cannot change the result
        base = {"ai_provider": "rules", "anthropic_api_key": "", "precheck_gate": "off"}
        return Settings(**(base | changes))

    def keyed(settings, **kw):
        return {c["key"]: c for c in overview.checks(settings, 0, **kw)}

    rules = keyed(configured())
    assert rules["ai"]["state"] == "off"
    assert rules["gate"]["state"] == "warn"  # a gate that is off is a development setting

    up = keyed(configured(ai_provider="ollama"), ollama_probe=lambda url: True)
    down = keyed(configured(ai_provider="ollama"), ollama_probe=lambda url: False)
    assert (up["ai"]["state"], down["ai"]["state"]) == ("ok", "warn")

    assert keyed(configured(ai_provider="claude"))["ai"]["state"] == "warn"  # no key set
    assert keyed(configured(ai_provider="claude", anthropic_api_key="x"))["ai"]["state"] == "ok"
    assert keyed(configured(precheck_gate="recording"))["gate"]["state"] == "ok"

    gaps = {c["key"]: c for c in overview.checks(configured(), 2)}["heartbeat"]
    assert (gaps["state"], gaps["detail"]) == ("note", "2 to look at.")


# --------------------------------------------------------------------------------- invitations


def test_the_invite_list_is_for_admins_only(client, staff):
    assert client.get("/api/admin/invites").status_code == 401
    assert client.get("/api/admin/invites", headers=staff).status_code == 403


def test_the_invite_list_says_where_each_candidate_is(client, db, sim, admin_headers):
    body = client.post("/api/admin/invites", json={"count": 2}, headers=admin_headers).json()
    new_ids = [i["candidate_id"] for i in body["invites"]]

    listed = client.get("/api/admin/invites", headers=admin_headers).json()
    status = {i["candidate_id"]: i["status"] for i in listed["invites"]}

    assert all(status[c] == "not_opened" for c in new_ids)
    assert status["sim-001"] == "finished"
    assert listed["total"] >= len(status)
    assert "code" not in listed["invites"][0]  # codes are never listed

    in_progress = db.scalar(select(TestSession).where(TestSession.candidate_id == "sim-001"))
    in_progress.status = "in_progress"
    db.flush()
    again = client.get("/api/admin/invites", headers=admin_headers).json()
    assert {i["candidate_id"]: i["status"] for i in again["invites"]}["sim-001"] == "started"


def test_a_reissued_code_replaces_the_old_one(client, db, clock, admin_headers):
    db.add(Sitting(name="Only one", duration_s=600, question_count=3, status="open"))
    db.flush()
    first = client.post("/api/admin/invites", json={"count": 1}, headers=admin_headers).json()
    candidate_id, old_code = (first["invites"][0][key] for key in ("candidate_id", "code"))

    response = client.post(f"/api/admin/invites/{candidate_id}/reissue", headers=admin_headers)

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    new_code = response.json()["code"]
    assert response.json()["candidate_id"] == candidate_id and new_code != old_code
    stored = db.get(Candidate, candidate_id).invite_token_hash
    assert stored == hash_token(normalise_invite_code(new_code))
    assert stored != hash_token(normalise_invite_code(old_code))
    details = [r.detail for r in db.scalars(select(AuditLog).where(AuditLog.action == "admin"))]
    assert f"issued a new code for {candidate_id}" in details
    assert new_code not in " ".join(d or "" for d in details)  # the code is never logged


def test_reissuing_for_an_unknown_candidate_is_a_404(client, admin_headers):
    response = client.post("/api/admin/invites/nobody/reissue", headers=admin_headers)
    assert (response.status_code, response.json()["code"]) == (404, "candidate_not_found")


# ------------------------------------------------------------------------------------ questions


def test_the_question_list_is_paged_and_filtered(client, seeded, admin_headers):
    page = client.get("/api/admin/questions?limit=25", headers=admin_headers).json()
    assert page["total"] == 60 and len(page["questions"]) == 25
    ordered = [(q["section"], q["id"]) for q in page["questions"]]
    assert ordered == sorted(ordered)

    second = client.get("/api/admin/questions?limit=25&offset=25", headers=admin_headers).json()
    assert {q["id"] for q in second["questions"]}.isdisjoint({q["id"] for q in page["questions"]})

    verbal = client.get("/api/admin/questions?section=verbal&limit=500", headers=admin_headers)
    assert verbal.json()["total"] == 20
    assert {q["section"] for q in verbal.json()["questions"]} == {"verbal"}


def test_a_list_row_carries_a_preview_not_the_whole_text(client, db, seeded, admin_headers):
    db.get(Question, "Q001").text = "x" * 900
    db.flush()
    rows = client.get("/api/admin/questions?section=numerical", headers=admin_headers).json()
    first = next(q for q in rows["questions"] if q["id"] == "Q001")
    assert len(first["preview"]) == admin.PREVIEW_CHARS


def test_only_real_percent_correct_is_shown(client, db, seeded, admin_headers):
    stats = db.get(QuestionStats, "Q002")
    stats.source, stats.pct_correct, stats.n = "cytonn", 38.5, 812
    db.flush()

    rows = client.get("/api/admin/questions?limit=500", headers=admin_headers).json()["questions"]
    by_id = {q["id"]: q for q in rows}

    assert (by_id["Q002"]["pct_correct"], by_id["Q002"]["n"]) == (38.5, 812)
    assert (by_id["Q001"]["pct_correct"], by_id["Q001"]["n"]) == (None, None)  # made-up estimate


def test_the_question_list_is_for_admins_only(client, staff):
    assert client.get("/api/admin/questions", headers=staff).status_code == 403


# ------------------------------------------------------------------------------------ blueprint


def per_section_args(**counts):
    return {
        "name": "Blueprint sitting",
        "opens_at": None,
        "closes_at": None,
        "per_section": counts,
    }


def test_a_sitting_can_ask_for_a_number_of_questions_from_each_section(db, seeded):
    sitting = admin.create_sitting(db, **per_section_args(numerical=5, verbal=2, logical=0))

    assert sitting.blueprint == {"numerical": 5, "verbal": 2}  # a zero is simply not asked for
    assert sitting.question_count == 7


def test_a_papers_sections_follow_the_blueprint(db, seeded):
    blueprint = {"numerical": 5, "verbal": 2}
    questions = select_questions(db, 0, random.Random(7), blueprint)

    assert len(questions) == 7 and len({q.id for q in questions}) == 7
    counts = {s: sum(1 for q in questions if q.section == s) for s in blueprint}
    assert counts == blueprint


def test_a_sitting_without_a_blueprint_still_spreads_evenly(db, seeded):
    sitting = admin.create_sitting(
        db, name="Even", opens_at=None, closes_at=None, question_count=12
    )
    assert sitting.blueprint is None
    assert sitting.duration_s == 12 * 105
    questions = select_questions(db, 12, random.Random(7), sitting.blueprint)
    per_section = [sum(1 for q in questions if q.section == s) for s in SECTIONS]
    assert per_section == [4, 4, 4]


def test_a_blueprint_that_asks_for_too_many_says_which_sections(db, seeded):
    with pytest.raises(ApiError) as refused:
        admin.create_sitting(db, **per_section_args(numerical=21, verbal=25))
    assert (refused.value.status_code, refused.value.code) == (409, "section_too_small")
    assert refused.value.extra["sections"] == [
        {"section": "numerical", "available": 20, "needed": 21},
        {"section": "verbal", "available": 20, "needed": 25},
    ]


@pytest.mark.parametrize(
    ("counts", "status", "code"),
    [
        ({"astrology": 3}, 422, "unknown_section"),
        ({"numerical": -1}, 422, "invalid_question_count"),
        ({"numerical": 0}, 422, "invalid_question_count"),
        ({}, 422, "invalid_question_count"),
    ],
)
def test_a_bad_blueprint_is_refused_with_a_code(db, seeded, counts, status, code):
    with pytest.raises(ApiError) as refused:
        admin.create_sitting(db, **per_section_args(**counts))
    assert (refused.value.status_code, refused.value.code) == (status, code)


def test_the_blueprint_goes_through_the_api_and_comes_back(client, db, seeded, admin_headers):
    body = {
        "name": "Via the API",
        "per_section": {"numerical": 3, "logical": 3},
    }
    created = client.post("/api/admin/sittings", json=body, headers=admin_headers)

    assert created.status_code == 200
    assert created.json()["blueprint"] == {"numerical": 3, "logical": 3}
    assert created.json()["question_count"] == 6
    listed = client.get("/api/admin/sittings", headers=admin_headers).json()["sittings"]
    assert next(s for s in listed if s["name"] == "Via the API")["blueprint"] == {
        "numerical": 3,
        "logical": 3,
    }
    assert db.scalar(select(Sitting.blueprint).where(Sitting.name == "Via the API")) is not None


def test_a_candidate_who_starts_gets_the_sections_the_sitting_asked_for(client, db, seeded):
    from app.models import SessionQuestion

    # an invitation opens the sitting it was made for, not just whichever is newest
    sitting = admin.create_sitting(db, **per_section_args(numerical=3, verbal=2))
    ((_, code),) = admin.generate_invites(db, 1, sitting)

    response = client.post("/api/session/start", json={"token": code})

    assert response.status_code == 200
    rows = db.execute(
        select(Question.section)
        .join(SessionQuestion, SessionQuestion.question_id == Question.id)
        .where(SessionQuestion.session_id == response.json()["session_id"])
    ).scalars().all()
    assert sorted(rows) == ["numerical"] * 3 + ["verbal"] * 2
