"""The tools used on and after pilot day: the chunk integrity check, the AI explanation audit, the
pilot metrics and the seek-accuracy check."""

import csv
import json
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.models import Flag, Ranking, TestSession, VideoChunk, VideoSegment
from app.services import review as review_service
from app.services.ranking.rules import rule_order
from app.services.ranking.runner import rank_sitting
from app.services.video.integrity import verify_session
from app.services.video.store import LocalVideoStore, assembled_key, chunk_key
from scripts import ai_explanations, pilot_metrics, video_offset
from tests.integration.test_packets_and_ranking import Scripted, always, hallucinating
from tests.support import Live, media_chunk, sha


@pytest.fixture
def store(settings):
    return LocalVideoStore(settings.video_root_path)


# ------------------------------------------------------------------------- chunk integrity


@pytest.fixture
def uploaded(client, db, seeded, clock):
    live = Live(client, db, seeded.invites[0].token).start()
    live.begin()
    for seq in range(4):
        live.put_chunk(seq, media_chunk(seq))
    live.answer_everything(clock)
    live.finish(chunks_total=4)
    return live


def test_a_complete_untouched_upload_passes(db, store, uploaded):
    result = verify_session(db, store, uploaded.session())
    assert result.ok and (result.expected, result.received) == (4, 4)
    assert result.missing == result.mismatched == result.unreadable == []


def test_a_missing_chunk_a_changed_file_and_a_vanished_file_are_each_reported(db, store, uploaded):
    uploaded.finish(chunks_total=6)  # the page said it made six; 4 and 5 never came
    store.put(chunk_key(uploaded.session_id, 0, 1), b"corrupted on disk")
    store.local_path(chunk_key(uploaded.session_id, 0, 2)).unlink()

    result = verify_session(db, store, uploaded.session())

    assert not result.ok
    assert result.missing == [4, 5] and result.mismatched == [1] and result.unreadable == [2]


def test_without_a_reported_total_the_highest_number_seen_sets_the_bar(db, store, client, seeded):
    live = Live(client, db, seeded.invites[1].token).start()
    for seq in (0, 1, 3):
        live.put_chunk(seq, media_chunk(seq))
    result = verify_session(db, store, live.session())
    assert result.expected is None and result.missing == [2]


def test_a_chunk_that_was_purged_on_purpose_is_not_reread_and_not_a_loss(
    db, store, uploaded, clock
):
    store.delete_session(uploaded.session_id)
    for chunk in db.scalars(select(VideoChunk).where(VideoChunk.session_id == uploaded.session_id)):
        chunk.deleted_at = clock.now()
    db.flush()
    assert verify_session(db, store, uploaded.session()).ok


# ------------------------------------------------------------------- AI explanation audit


def test_the_audit_passes_answers_the_fact_check_accepted_and_writes_a_sheet(
    db, sim, clock, tmp_path
):
    rank_sitting(db, sim.sitting_id, Scripted(always(3)), clock)

    audited = ai_explanations.audit_sitting(db, sim.sitting_id)

    assert audited and all(a.violations == [] for a in audited)
    sheet = tmp_path / "sheet.csv"
    ai_explanations.write_sheet(audited, sheet)
    rows = list(csv.DictReader(sheet.open(encoding="utf-8")))
    assert len(rows) == len(audited)
    assert {r["automatic_check"] for r in rows} == {"pass"}
    assert {r["hand_check"] for r in rows} == {""}  # left for a person to tick
    assert json.loads(rows[0]["packet_facts"])["counts"]["flags"] >= 1


def test_the_audit_catches_a_stored_answer_that_would_not_pass_now(db, sim, clock):
    rank_sitting(db, sim.sitting_id, Scripted(always(3)), clock)
    ranking = db.scalars(select(Ranking)).first()
    ranking.ai_json = {**ranking.ai_json, "explanation": "They cheated on 777 questions."}
    db.flush()

    bad = [a for a in ai_explanations.audit_sitting(db, sim.sitting_id) if a.violations]

    assert len(bad) == 1
    assert {v.split(":")[0] for v in bad[0].violations} >= {"verdict_word", "number_not_in_facts"}


def test_rankings_that_fell_back_have_no_ai_explanation_to_audit(db, sim, clock):
    rank_sitting(db, sim.sitting_id, Scripted(hallucinating), clock)
    assert ai_explanations.audit_sitting(db, sim.sitting_id) == []


# ------------------------------------------------------------------------------ pilot metrics


def truth_for(db, sim, cheaters):
    """Everyone honest except the named candidates."""
    candidates = db.scalars(
        select(TestSession.candidate_id).where(TestSession.sitting_id == sim.sitting_id)
    )
    return {c: ("C1" if c in cheaters else "honest") for c in candidates}


def test_the_metrics_count_cheaters_caught_and_honest_people_flagged(db, sim, clock):
    ordered = rule_order(db, sim.sitting_id)
    top = [o.session.candidate_id for o in ordered if not o.logging_only][:2]
    rank_sitting(db, sim.sitting_id, None, clock)

    metrics = pilot_metrics.measure(db, sim.sitting_id, truth_for(db, sim, set(top)))

    assert metrics.cheaters == 2 and sorted(metrics.caught) == sorted(top)
    assert metrics.missed == []
    assert sorted(metrics.top_third) == sorted(top)  # the two strongest are at the top
    assert metrics.honest == 16 - 2
    flagged_honest = {
        o.session.candidate_id
        for o in ordered
        if o.score >= 1.0 and o.session.candidate_id not in top
    }
    assert set(metrics.honest_flagged) == flagged_honest
    assert metrics.queued == len(ordered)


def test_a_planted_cheater_with_no_flags_is_a_miss_and_a_low_one_is_caught_but_not_top_third(
    db, sim, clock
):
    ordered = rule_order(db, sim.sitting_id)
    unflagged = {
        s.candidate_id
        for s in db.scalars(select(TestSession).where(TestSession.sitting_id == sim.sitting_id))
        if s.candidate_id not in {o.session.candidate_id for o in ordered}
    }
    lowest = next(o.session.candidate_id for o in reversed(ordered) if not o.logging_only)
    rank_sitting(db, sim.sitting_id, None, clock)
    quiet = sorted(unflagged)[0]

    metrics = pilot_metrics.measure(db, sim.sitting_id, truth_for(db, sim, {quiet, lowest}))

    assert metrics.missed == [quiet]
    assert metrics.caught == [lowest] and metrics.top_third == []


def test_the_top_third_is_a_third_of_the_queue_not_of_everyone_who_sat(db, sim, clock):
    ordered = rule_order(db, sim.sitting_id)
    third = -(-len(ordered) // 3)
    inside = ordered[third - 1].session.candidate_id
    outside = ordered[third].session.candidate_id
    rank_sitting(db, sim.sitting_id, None, clock)

    metrics = pilot_metrics.measure(db, sim.sitting_id, truth_for(db, sim, {inside, outside}))

    assert metrics.top_third == [inside]


def test_a_truth_file_listing_someone_who_did_not_sit_is_called_out(db, sim, clock):
    rank_sitting(db, sim.sitting_id, None, clock)
    metrics = pilot_metrics.measure(db, sim.sitting_id, {"cand-999": "honest", "sim-001": "honest"})
    assert metrics.unknown == ["cand-999"] and metrics.honest == 1


def test_the_report_states_each_criterion_with_its_target(db, sim, clock):
    rank_sitting(db, sim.sitting_id, Scripted(always(3), clock=clock, seconds_per_call=4), clock)
    text = pilot_metrics.render(
        pilot_metrics.measure(db, sim.sitting_id, truth_for(db, sim, set()))
    )
    assert "Honest volunteers wrongly flagged | at most 1 in 10" in text
    assert "median 4.0 s, max 4.0 s" in text and "ok" in text


def test_the_truth_file_must_name_candidates_and_roles(tmp_path):
    bad = tmp_path / "truth.csv"
    bad.write_text("who,what\nx,y\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        pilot_metrics.read_truth(bad)
    good = tmp_path / "ok.csv"
    good.write_text(
        "candidate_id,role,planted_actions\ncand-001,Honest,\ncand-002,C3,idle\n", encoding="utf-8"
    )
    assert pilot_metrics.read_truth(good) == {"cand-001": "honest", "cand-002": "c3"}


# ----------------------------------------------------------------------------- video offset


def test_the_seek_error_is_how_far_the_cue_is_from_five_seconds_after_the_jump(
    db, sim, store, clock, settings
):
    session = db.get(TestSession, sorted(set(db.scalars(select(Flag.session_id))))[0])
    key = assembled_key(session.id, 0)
    store.put(key, b"video")
    db.add(
        VideoSegment(
            session_id=session.id,
            segment=0,
            started_at=session.recording_started_at,
            duration_s=1800.0,
            chunk_count=1,
            bytes=5,
            path=key,
            assembled_at=clock.now(),
        )
    )
    db.flush()
    video = review_service.VideoContext(store, clock, settings, reviewer_id=0)
    detail = review_service.candidate_detail(db, session.candidate_id, None, video=video)
    flag = next(f for f in detail["flags"] if f["video_seek"] and f["video_seek"]["seek_s"] > 0)
    seek = flag["video_seek"]["seek_s"]

    cues = [
        video_offset.Cue(session.candidate_id, flag["id"], 0, seek + 5.0),  # spot on
        video_offset.Cue(session.candidate_id, flag["id"], 0, seek + 6.5),  # 1.5 s late
        video_offset.Cue(session.candidate_id, flag["id"], 0, seek + 9.0),  # 4 s late
        video_offset.Cue(session.candidate_id, flag["id"], 1, seek + 5.0),  # the wrong part
        video_offset.Cue(session.candidate_id, "F99", 0, 10.0),  # no such flag
    ]
    results = video_offset.measure(db, video, cues)

    assert [round(r.error_s, 1) if r.error_s is not None else None for r in results] == [
        0.0,
        1.5,
        4.0,
        None,
        None,
    ]
    assert [r.ok for r in results] == [True, True, False, False, False]
    assert "part 0" in results[3].note and results[4].note == "no such flag"


def test_the_cue_sheet_is_read_with_its_columns(tmp_path):
    path = tmp_path / "cues.csv"
    path.write_text("candidate_id,flag_id,segment,cue_s\ncand-001,F2,0,41.5\n", encoding="utf-8")
    (cue,) = video_offset.read_cues(path)
    assert (cue.candidate_id, cue.flag_id, cue.segment, cue.cue_s) == ("cand-001", "F2", 0, 41.5)
    path.write_text("candidate_id\ncand-001\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        video_offset.read_cues(path)


def test_a_flag_with_no_video_at_that_moment_cannot_be_checked(db, sim, store, clock, settings):
    session = db.get(TestSession, sorted(set(db.scalars(select(Flag.session_id))))[0])
    video = review_service.VideoContext(store, clock, settings, reviewer_id=0)
    (result,) = video_offset.measure(
        db, video, [video_offset.Cue(session.candidate_id, "F1", 0, 5)]
    )
    assert result.error_s is None and result.note == "no video at that moment"


def test_a_late_timestamp_helper_is_not_needed():
    assert timedelta(seconds=1).total_seconds() == 1  # keeps the import honest
    assert sha(b"") and chunk_key("s", 0, 0).endswith("000000.chunk")
