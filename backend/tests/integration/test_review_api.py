"""The reviewer API on a made-up sitting: who is in the queue and in what order, what a
candidate's page holds, and the three things a reviewer can write."""

import pytest
from sqlalchemy import select

from app.models import Decision, Sitting
from app.services.staff_auth import create_reviewer
from scripts.simulate_cohort import SITTING_NAME, simulate
from tests.support import Live

PASSWORD = "correct horse battery"
LONG_REASON = "Only a pace flag and nothing else on the video review."


@pytest.fixture
def sim(db, seeded):
    result = simulate(db, seed=1)
    db.flush()
    return result


@pytest.fixture
def staff(client, db, clock):
    create_reviewer(db, clock, email="rev@example.com", password=PASSWORD)
    db.flush()
    token = client.post(
        "/api/review/login", json={"email": "rev@example.com", "password": PASSWORD}
    ).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def candidates_by_archetype(sim, name):
    return [c for c, a in sim.by_archetype.items() if a == name]


# ------------------------------------------------------------------------------------ access


@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "/api/review/queue"),
        ("get", "/api/review/candidates"),
        ("get", "/api/review/candidates/sim-001"),
        ("get", "/api/review/candidates/sim-001/events"),
        ("post", "/api/review/candidates/sim-001/shortlist"),
        ("post", "/api/review/candidates/sim-001/video-view"),
        ("post", "/api/review/decisions"),
        ("get", "/api/review/audit"),
    ],
)
def test_every_review_route_needs_a_signed_in_account(client, sim, method, path):
    response = getattr(client, method)(path)
    assert response.status_code == 401
    assert response.json() == {"code": "unauthorized"}


# ------------------------------------------------------------------------------------ queue


def test_the_queue_lists_flagged_candidates_most_evidence_first(client, sim, staff):
    body = client.get("/api/review/queue", headers=staff).json()

    assert body["sitting_id"] == sim.sitting_id
    assert {"id": sim.sitting_id, "name": SITTING_NAME} in body["sittings"]
    items = body["items"]
    assert [i["rank"] for i in items] == list(range(1, len(items) + 1))

    scores = [i["rule_score"] for i in items if not i["logging_only"]]
    assert scores == sorted(scores, reverse=True)
    assert scores[0] > 0

    # a gap in the record sits below everyone with evidence
    lanes = [i["logging_only"] for i in items]
    assert lanes == sorted(lanes)
    assert all(i["flag_kinds"] == ["LOGGING_PROBLEM"] for i in items if i["logging_only"])

    # the AI step is not built, so the order is rules only and says so
    assert all(i["ai_status"] == "not_run" and i["ai_strength"] is None for i in items)
    assert all(i["decision"] is None and i["shortlisted"] is False for i in items)


def test_the_scripted_cases_are_found(client, sim, staff):
    items = {
        i["candidate_id"]: i for i in client.get("/api/review/queue", headers=staff).json()["items"]
    }

    for candidate in candidates_by_archetype(sim, "tab_lookup"):
        assert "LONG_HOLD_CORRECT" in items[candidate]["flag_kinds"]
        assert "FOCUS_LOSS" in items[candidate]["flag_kinds"]
    for candidate in candidates_by_archetype(sim, "copier"):
        assert items[candidate]["flag_kinds"].count("COPY_ATTEMPT") == 3
    for candidate in candidates_by_archetype(sim, "answer_runner"):
        assert "CORRECT_RUN_AFTER_GAP" in items[candidate]["flag_kinds"]
    for candidate in candidates_by_archetype(sim, "logging_blocker"):
        assert items[candidate]["flag_kinds"] == ["LOGGING_PROBLEM"]
        assert items[candidate]["logging_only"] is True

    # Two things hold for honest people whatever the thresholds are. They never copy, and a
    # dropped connection or reload explains a gap in the log, so it never becomes a logging
    # problem. (How often the *threshold* rules flag an honest person is a measurement, not a
    # guarantee: see scripts/measure_false_flags.py.)
    for archetype in ("honest", "honest_fast", "honest_tech"):
        for candidate in candidates_by_archetype(sim, archetype):
            item = items.get(candidate)
            if item is not None:
                assert not {"COPY_ATTEMPT", "LOGGING_PROBLEM"} & set(item["flag_kinds"]), candidate


def test_an_unknown_sitting_falls_back_to_the_default_one(client, sim, staff):
    body = client.get("/api/review/queue?sitting=99999", headers=staff).json()
    assert body["sitting_id"] == sim.sitting_id


def test_the_invited_sitting_has_no_flagged_candidates_so_its_queue_is_empty(
    client, sim, staff, db
):
    real = db.scalar(select(Sitting).where(Sitting.name != SITTING_NAME))
    body = client.get(f"/api/review/queue?sitting={real.id}", headers=staff).json()
    assert body["items"] == []


# ------------------------------------------------------------------------------- one candidate


def test_the_candidate_page_holds_the_flags_the_breakdown_and_the_context(client, sim, staff):
    candidate = candidates_by_archetype(sim, "tab_lookup")[0]
    detail = client.get(f"/api/review/candidates/{candidate}", headers=staff).json()

    assert detail["candidate_id"] == candidate
    assert len(detail["session_id"]) == 32
    assert detail["rank"] >= 1

    flags = detail["flags"]
    assert [f["id"] for f in flags] == [f"F{i}" for i in range(1, len(flags) + 1)]
    assert all(f["video_seek"] is None for f in flags)  # no video is stored yet
    assert detail["segments"] == []

    # the breakdown adds up to the score, so nobody is ranked by a number they cannot take apart
    assert sum(line["points"] for line in detail["rule_breakdown"]) == pytest.approx(
        detail["rule_score"]
    )
    assert detail["vs_sitting"].keys() == {
        "pace_percentile",
        "spread_percentile",
        "score_percentile",
    }
    assert "history_source" not in detail  # no rule compares anyone with past candidates

    text = detail["explanation"]
    assert text["source"] == "rules" and text["status"] == "not_run"
    assert text["text"].startswith("Rules only:")
    lowered = text["text"].lower()
    assert not any(word in lowered for word in ("cheat", "guilty", "disqualif", "reject"))


def test_a_copy_flag_keeps_only_the_length_never_the_text(client, sim, staff):
    candidate = candidates_by_archetype(sim, "copier")[0]
    flags = client.get(f"/api/review/candidates/{candidate}", headers=staff).json()["flags"]
    copies = [f for f in flags if f["kind"] == "COPY_ATTEMPT"]
    assert len(copies) == 3
    for flag in copies:
        assert set(flag["detail"]) == {"target", "length"}
        assert isinstance(flag["detail"]["length"], int)


def test_technical_trouble_shows_as_context_not_as_a_flag(client, sim, staff):
    candidate = candidates_by_archetype(sim, "honest_tech")[0]
    detail = client.get(f"/api/review/candidates/{candidate}", headers=staff).json()

    kinds = {s["kind"] for s in detail["innocent_signals"]}
    assert {"connection_lost", "reload", "camera_dropped", "self_report"} <= kinds
    assert detail["self_report"]["had_technical_issues"] is True
    assert "LOGGING_PROBLEM" not in {f["kind"] for f in detail["flags"]}  # the drop explains it
    assert detail["complaints"][0]["category"] == "camera"


def test_a_long_muted_stretch_is_shown_but_never_flagged(client, sim, staff):
    candidate = "sim-004"  # the fourth honest candidate, given a long silent stretch
    assert sim.by_archetype[candidate] == "honest"
    detail = client.get(f"/api/review/candidates/{candidate}", headers=staff).json()
    assert len(detail["mic_silence"]) == 1
    assert detail["mic_silence"][0]["duration_s"] >= 60
    assert detail["mic_silence"][0]["layers"] == ["browser"]
    # context only: it adds no flag and no weight
    assert {f["kind"] for f in detail["flags"]} <= {"FOCUS_LOSS"}


def test_an_unknown_candidate_is_a_404(client, sim, staff):
    response = client.get("/api/review/candidates/cand-does-not-exist", headers=staff)
    assert response.status_code == 404
    assert response.json() == {"code": "candidate_not_found"}
    response = client.get("/api/review/candidates/cand-does-not-exist/events", headers=staff)
    assert response.status_code == 404
    assert response.json() == {"code": "candidate_not_found"}


# ------------------------------------------------------------------- everyone in the sitting


def queued(client, staff) -> set[str]:
    items = client.get("/api/review/queue", headers=staff).json()["items"]
    return {i["candidate_id"] for i in items}


def test_the_list_of_everyone_holds_candidates_the_queue_leaves_out(client, sim, staff):
    body = client.get("/api/review/candidates", headers=staff).json()

    assert body["sitting_id"] == sim.sitting_id
    items = body["items"]
    assert len(items) == len(sim.by_archetype)  # every sixteen, not only the flagged ones
    assert all(i["status"] == "finished" for i in items)
    assert all(i["total"] == 12 and i["resolved"] <= 12 for i in items)

    in_queue = {i["candidate_id"] for i in items if i["in_queue"]}
    assert in_queue == queued(client, staff)  # the two lists agree about who is in the queue
    left_out = [i for i in items if not i["in_queue"]]
    assert left_out, "the made-up sitting has honest candidates the queue does not show"

    flagged = {i["candidate_id"]: i for i in items if i["flag_count"]}
    for candidate in candidates_by_archetype(sim, "copier"):
        assert flagged[candidate]["flag_kinds"].count("COPY_ATTEMPT") == 1  # listed once each


def test_the_list_of_everyone_follows_invitation_order_and_the_chosen_sitting(client, sim, staff):
    items = client.get("/api/review/candidates", headers=staff).json()["items"]
    ids = [i["candidate_id"] for i in items]
    assert ids == sorted(ids, key=lambda c: (len(c), c))

    other = client.get("/api/review/candidates?sitting=99999", headers=staff).json()
    assert other["sitting_id"] == sim.sitting_id  # an unknown sitting falls back, as the queue does


def test_someone_the_queue_leaves_out_still_opens_but_their_video_stays_closed(
    client, sim, staff
):
    in_queue = queued(client, staff)
    everyone = client.get("/api/review/candidates", headers=staff).json()["items"]
    candidate = next(i["candidate_id"] for i in everyone if i["candidate_id"] not in in_queue)

    detail = client.get(f"/api/review/candidates/{candidate}", headers=staff)
    assert detail.status_code == 200
    assert detail.json()["rank"] == 0
    assert detail.json()["video_available"] is False
    assert detail.json()["segments"] == []

    video = client.get(f"/api/review/candidates/{candidate}/video", headers=staff)
    assert video.status_code == 403 and video.json() == {"code": "video_not_available"}

    # a reviewer who shortlists them chooses to open it
    assert client.post(
        f"/api/review/candidates/{candidate}/shortlist", headers=staff
    ).json() == {"shortlisted": True, "result_email_sent": False}
    again = client.get(f"/api/review/candidates/{candidate}", headers=staff).json()
    assert again["video_available"] is True


def test_someone_in_the_queue_has_video_available(client, sim, staff):
    candidate = candidates_by_archetype(sim, "copier")[0]
    detail = client.get(f"/api/review/candidates/{candidate}", headers=staff).json()
    assert detail["video_available"] is True


# ----------------------------------------------------------------------------- the action log


def test_the_action_log_lists_what_the_page_reported_in_order(client, sim, staff):
    candidate = candidates_by_archetype(sim, "copier")[0]
    log = client.get(f"/api/review/candidates/{candidate}/events", headers=staff).json()

    assert log["candidate_id"] == candidate and log["status"] == "finished"
    assert log["total_events"] == len(log["events"]) and log["truncated"] is False
    times = [e["at_s"] for e in log["events"]]
    assert times == sorted(times)

    types = [e["type"] for e in log["events"]]
    assert types.count("copy_attempt") == 3
    assert "question_opened" in types and "answered" in types

    # copy events carry a length and nothing else: never the text
    for event in (e for e in log["events"] if e["type"] == "copy_attempt"):
        assert set(event["detail"]) == {"length"}
        assert isinstance(event["detail"]["length"], int)
        assert event["question"] is not None  # it happened while a question was open

    # the question a position belongs to comes from the question_opened event before it
    opened = [e for e in log["events"] if e["type"] == "question_opened"]
    assert all(e["question"] is not None and "position" not in e["detail"] for e in opened)


def test_the_action_log_has_the_paper_question_by_question(client, sim, staff):
    candidate = candidates_by_archetype(sim, "copier")[0]
    log = client.get(f"/api/review/candidates/{candidate}/events", headers=staff).json()

    paper = log["questions"]
    assert [q["position"] for q in paper] == list(range(1, 13))
    assert {q["result"] for q in paper} <= {"correct", "wrong", "skipped", "unanswered"}
    for q in paper:
        assert q["section"] in {"numerical", "verbal", "logical"}
        assert set(q) == {
            "position", "section", "difficulty", "opened_s", "answered_s", "time_s", "result",
            "written_by", "sitting_median_s", "median_of", "median_n",
        }  # no question text, no options: the last three are numbers about the sitting
        assert q["written_by"] is None  # these came from the bank, not from an AI
        if q["time_s"] is not None:
            assert q["time_s"] == pytest.approx(q["answered_s"] - q["opened_s"], abs=0.2)


def test_the_action_log_of_someone_who_never_started_is_empty_not_an_error(
    client, db, seeded, sim, staff
):
    live = Live(client, db, seeded.invites[0].token).start()  # opened the link, never began
    session = live.session()
    log = client.get(
        f"/api/review/candidates/{session.candidate_id}/events?sitting={session.sitting_id}",
        headers=staff,
    )
    assert log.status_code == 200
    body = log.json()
    assert body["status"] == "created" and body["started_at"] is None
    assert body["events"] == [] and body["total_events"] == 0 and body["heartbeats"] == 0


# ----------------------------------------------------------------------------------- writing


def test_a_decision_needs_a_real_reason_and_a_known_outcome(client, sim, staff):
    session_id = client.get("/api/review/queue", headers=staff).json()
    first = session_id["items"][0]["candidate_id"]
    sid = client.get(f"/api/review/candidates/{first}", headers=staff).json()["session_id"]

    def post(**changes):
        body = {"session_id": sid, "outcome": "no_concern", "reason": LONG_REASON, **changes}
        return client.post("/api/review/decisions", json=body, headers=staff)

    assert post(reason="too short").status_code == 422
    assert post(reason="too short").json()["code"] == "reason_too_short"
    assert post(reason="x" * 19).status_code == 422  # one under the minimum
    assert post(outcome="rejected").json()["code"] == "invalid_outcome"
    assert post(session_id="f" * 32).json()["code"] == "candidate_not_found"
    assert post(reason="x" * 20).status_code == 200  # exactly the minimum


def test_a_decision_is_kept_with_who_and_when_and_shows_in_the_queue_and_the_audit(
    client, sim, staff, db, clock
):
    top = client.get("/api/review/queue", headers=staff).json()["items"][0]["candidate_id"]
    sid = client.get(f"/api/review/candidates/{top}", headers=staff).json()["session_id"]

    clock.advance(60)
    response = client.post(
        "/api/review/decisions",
        json={"session_id": sid, "outcome": "concern_noted", "reason": LONG_REASON},
        headers=staff,
    )
    assert response.status_code == 200

    stored = db.scalar(select(Decision).where(Decision.session_id == sid))
    assert stored.outcome == "concern_noted"
    assert stored.reason == LONG_REASON
    assert stored.reviewer_id is not None

    queue = client.get("/api/review/queue", headers=staff).json()["items"]
    assert next(i for i in queue if i["candidate_id"] == top)["decision"] == "concern_noted"

    detail = client.get(f"/api/review/candidates/{top}", headers=staff).json()
    assert detail["decisions"][-1]["reviewer"] == "rev@example.com"
    assert detail["decisions"][-1]["outcome"] == "concern_noted"
    assert detail["video_purge_on"] is not None  # 30 days after the decision

    audit = client.get("/api/review/audit", headers=staff).json()["entries"]
    entry = next(e for e in audit if e["action"] == "decision")
    assert entry["candidate_id"] == top
    assert entry["reviewer"] == "rev@example.com"
    assert entry["detail"] == "concern_noted"


def test_the_latest_of_several_decisions_is_the_one_that_counts(client, sim, staff):
    top = client.get("/api/review/queue", headers=staff).json()["items"][0]["candidate_id"]
    sid = client.get(f"/api/review/candidates/{top}", headers=staff).json()["session_id"]
    for outcome in ("concern_noted", "no_concern"):
        client.post(
            "/api/review/decisions",
            json={"session_id": sid, "outcome": outcome, "reason": LONG_REASON},
            headers=staff,
        )
    queue = client.get("/api/review/queue", headers=staff).json()["items"]
    assert next(i for i in queue if i["candidate_id"] == top)["decision"] == "no_concern"
    detail = client.get(f"/api/review/candidates/{top}", headers=staff).json()
    assert [d["outcome"] for d in detail["decisions"]] == ["concern_noted", "no_concern"]


def test_shortlisting_toggles_and_is_audited(client, sim, staff, db):
    top = client.get("/api/review/queue", headers=staff).json()["items"][0]["candidate_id"]
    first = client.post(f"/api/review/candidates/{top}/shortlist", headers=staff)
    assert first.json() == {"shortlisted": True, "result_email_sent": False}
    queue = client.get("/api/review/queue", headers=staff).json()["items"]
    assert next(i for i in queue if i["candidate_id"] == top)["shortlisted"] is True

    second = client.post(f"/api/review/candidates/{top}/shortlist", headers=staff)
    assert second.json() == {"shortlisted": False, "result_email_sent": False}

    details = [
        e["detail"]
        for e in client.get("/api/review/audit", headers=staff).json()["entries"]
        if e["action"] == "decision"
    ]
    assert details == ["removed from shortlist", "shortlisted"]  # newest first


def test_opening_the_video_is_audited_with_the_flag_jumped_to(client, sim, staff):
    top = client.get("/api/review/queue", headers=staff).json()["items"][0]["candidate_id"]
    assert client.post(f"/api/review/candidates/{top}/video-view", headers=staff).status_code == 204
    done = client.post(
        f"/api/review/candidates/{top}/video-view", json={"flag_id": "F2"}, headers=staff
    )
    assert done.status_code == 204
    entries = [
        e for e in client.get("/api/review/audit", headers=staff).json()["entries"]
        if e["action"] == "video_view"
    ]
    assert [e["detail"] for e in entries] == ["jumped to F2", "opened video"]
    assert all(e["candidate_id"] == top for e in entries)


def test_the_audit_lists_sign_ins_newest_first(client, sim, staff):
    entries = client.get("/api/review/audit", headers=staff).json()["entries"]
    assert entries[0]["action"] == "login"
    assert entries[0]["detail"] == "signed in"
    assert entries[0]["reviewer"] == "rev@example.com"
    stamps = [e["ts"] for e in entries]
    assert stamps == sorted(stamps, reverse=True)
