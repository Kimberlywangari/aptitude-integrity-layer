"""The 30-day promise and the 48-hour window, on a fake clock: video is deleted 30 days after the
latest decision and not a day before, the record stays, and an upload that never finished is noted
once."""

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.models import AuditLog, Decision, Event, Flag, TestSession, VideoChunk, VideoSegment
from app.services.ranking.rules import rule_order
from app.services.uploads import INCOMPLETE_MARKER_SEQ, mark_incomplete_uploads
from app.services.video.purge import purge_due, undecided_report
from app.services.video.store import LocalVideoStore, assembled_key, chunk_key
from tests.support import Live, media_chunk, sha

DAY = timedelta(days=1)


@pytest.fixture
def store(settings):
    return LocalVideoStore(settings.video_root_path)


@pytest.fixture
def sessions(db, sim):
    ids = sorted(db.scalars(select(TestSession.id).where(TestSession.sitting_id == sim.sitting_id)))
    return [db.get(TestSession, i) for i in ids]


def give_video(db, store, clock, session, chunks=3):
    for seq in range(chunks):
        key = chunk_key(session.id, 0, seq)
        store.put(key, media_chunk(seq))
        db.add(
            VideoChunk(
                session_id=session.id,
                segment=0,
                seq=seq,
                bytes=400,
                sha256=sha(media_chunk(seq)),
                path=key,
                received_at=clock.now(),
            )
        )
    key = assembled_key(session.id, 0)
    store.put(key, b"assembled video")
    db.add(
        VideoSegment(
            session_id=session.id,
            segment=0,
            started_at=clock.now(),
            duration_s=30.0,
            chunk_count=chunks,
            bytes=15,
            path=key,
            assembled_at=clock.now(),
        )
    )
    session.chunks_total = chunks
    db.flush()


def decide(db, session, when, outcome="no_concern"):
    db.add(
        Decision(
            session_id=session.id,
            reviewer_id=None,
            outcome=outcome,
            reason="Checked the flagged moments against the video.",
            decided_at=when,
        )
    )
    db.flush()


def files(store, session):
    root = store.local_path(session.id)
    return [p for p in root.rglob("*") if p.is_file()] if root.exists() else []


# ----------------------------------------------------------------------------------- purging


def test_video_goes_thirty_days_after_the_decision_and_not_a_day_before(db, store, clock, sessions):
    old, boundary, recent = sessions[:3]
    for session in (old, boundary, recent):
        give_video(db, store, clock, session)
    decide(db, old, clock.now() - 31 * DAY)
    decide(db, boundary, clock.now() - 30 * DAY)
    decide(db, recent, clock.now() - 29 * DAY)

    result = purge_due(db, store, clock, 30)

    assert sorted(result.purged) == sorted([old.id, boundary.id])
    assert result.files_removed == 2 * 4
    assert files(store, old) == [] and files(store, boundary) == []
    assert len(files(store, recent)) == 4  # one day short: untouched
    assert old.video_deleted_at == clock.now() and boundary.video_deleted_at == clock.now()
    assert recent.video_deleted_at is None


def test_the_record_stays_when_the_video_goes(db, store, clock, sessions):
    session = sessions[0]
    give_video(db, store, clock, session)
    flags = db.scalar(select(Flag.id).where(Flag.session_id == session.id))
    decide(db, session, clock.now() - 40 * DAY)

    purge_due(db, store, clock, 30)

    chunks = db.scalars(select(VideoChunk).where(VideoChunk.session_id == session.id)).all()
    assert len(chunks) == 3 and all(
        c.deleted_at == clock.now() for c in chunks
    )  # rows kept, marked
    (segment,) = db.scalars(select(VideoSegment).where(VideoSegment.session_id == session.id))
    assert segment.path is None and segment.duration_s == 30.0
    assert db.scalar(select(Flag.id).where(Flag.session_id == session.id)) == flags
    assert db.scalar(select(Decision.id).where(Decision.session_id == session.id))


def test_each_purge_is_audited_with_how_much_went_and_why(db, store, clock, sessions):
    give_video(db, store, clock, sessions[0])
    decide(db, sessions[0], clock.now() - 35 * DAY)

    purge_due(db, store, clock, 30)

    (entry,) = db.scalars(select(AuditLog).where(AuditLog.action == "video_purged"))
    assert entry.session_id == sessions[0].id and entry.reviewer_id is None
    assert "4 files" in entry.detail and "30 days after the decision" in entry.detail


def test_running_the_purge_again_does_nothing(db, store, clock, sessions):
    give_video(db, store, clock, sessions[0])
    decide(db, sessions[0], clock.now() - 35 * DAY)
    purge_due(db, store, clock, 30)

    again = purge_due(db, store, clock, 30)

    assert again.purged == [] and again.files_removed == 0
    assert len(list(db.scalars(select(AuditLog).where(AuditLog.action == "video_purged")))) == 1


def test_a_later_decision_extends_the_thirty_days(db, store, clock, sessions):
    give_video(db, store, clock, sessions[0])
    decide(db, sessions[0], clock.now() - 40 * DAY, "concern_noted")
    decide(db, sessions[0], clock.now() - 10 * DAY, "no_concern")

    assert purge_due(db, store, clock, 30).purged == []
    assert len(files(store, sessions[0])) == 4

    clock.advance(21 * 24 * 3600)  # now 31 days after the latest decision
    assert purge_due(db, store, clock, 30).purged == [sessions[0].id]


def test_nobody_without_a_decision_is_ever_deleted(db, store, clock, sessions):
    give_video(db, store, clock, sessions[0])
    clock.advance(400 * 24 * 3600)
    assert purge_due(db, store, clock, 30).purged == []
    assert len(files(store, sessions[0])) == 4


def test_the_retention_period_is_a_setting_not_a_constant(db, store, clock, sessions):
    give_video(db, store, clock, sessions[0])
    decide(db, sessions[0], clock.now() - 8 * DAY)
    assert purge_due(db, store, clock, 30).purged == []
    assert purge_due(db, store, clock, 7).purged == [sessions[0].id]


def test_a_session_with_no_video_is_not_marked_deleted(db, store, clock, sessions):
    decide(db, sessions[0], clock.now() - 90 * DAY)
    assert purge_due(db, store, clock, 30).purged == []
    assert sessions[0].video_deleted_at is None


def test_after_the_purge_the_reviewer_page_says_when_and_the_video_is_gone(
    client, db, store, clock, sessions, staff
):
    flagged = rule_order(db, sessions[0].sitting_id)[0].session
    give_video(db, store, clock, flagged)
    decide(db, flagged, clock.now() - 31 * DAY)
    purge_due(db, store, clock, 30)

    body = client.get(f"/api/review/candidates/{flagged.candidate_id}", headers=staff).json()

    assert body["video_deleted_at"] is not None and body["video_purge_on"] is None
    assert all(s["url"] is None for s in body["segments"])
    video = client.get(
        f"/api/review/candidates/{flagged.candidate_id}/video?segment=0", headers=staff
    )
    assert video.status_code == 410


def test_the_purge_state_before_it_happens_is_shown_on_the_page(client, db, clock, sessions, staff):
    flagged = rule_order(db, sessions[0].sitting_id)[0].session
    decide(db, flagged, clock.now() - 5 * DAY)
    body = client.get(f"/api/review/candidates/{flagged.candidate_id}", headers=staff).json()
    assert body["video_purge_on"].startswith((clock.now() + 25 * DAY).strftime("%Y-%m-%dT%H:%M"))


def test_a_late_upload_after_the_purge_is_refused(client, db, seeded, clock):
    live = Live(client, db, seeded.invites[0].token).start()
    live.session().video_deleted_at = clock.now()
    db.flush()
    assert live.put_chunk(0, media_chunk(0)).status_code == 410


# --------------------------------------------------------------------- the undecided report


def test_the_report_lists_old_undecided_video_for_a_person_to_decide(db, store, clock, sessions):
    old, fresh, decided, purged = sessions[:4]
    for session in (old, fresh, decided, purged):
        give_video(db, store, clock, session)
    old.finished_at = clock.now() - 90 * DAY
    fresh.finished_at = clock.now() - 20 * DAY
    decided.finished_at = clock.now() - 90 * DAY
    purged.finished_at = clock.now() - 90 * DAY
    purged.video_deleted_at = clock.now() - DAY
    decide(db, decided, clock.now() - 80 * DAY)
    db.flush()

    listed = undecided_report(db, clock, 60)

    assert [(u.session_id, u.age_days) for u in listed] == [(old.id, 90)]
    assert listed[0].candidate_id == old.candidate_id


# ------------------------------------------------------------------------- incomplete uploads


@pytest.fixture
def finished(client, db, seeded, clock):
    live = Live(client, db, seeded.invites[0].token).start()
    live.begin()
    live.answer_everything(clock)
    return live


def markers(db, session_id):
    return list(
        db.scalars(
            select(Event).where(
                Event.session_id == session_id, Event.client_seq == INCOMPLETE_MARKER_SEQ
            )
        )
    )


def test_an_upload_still_missing_chunks_after_forty_eight_hours_is_noted_once(db, clock, finished):
    finished.put_chunk(0, media_chunk(0))
    finished.put_chunk(1, media_chunk(1))
    finished.finish(chunks_total=3)  # chunk 2 never arrives
    finished_at = finished.session().finished_at

    clock.advance(48 * 3600 - 60)
    assert mark_incomplete_uploads(db, clock, 48 * 3600) == []  # still inside the window

    clock.advance(120)
    assert mark_incomplete_uploads(db, clock, 48 * 3600) == [finished.session_id]
    (marker,) = markers(db, finished.session_id)
    assert marker.type == "upload_incomplete" and marker.payload == {"missing": 1}
    assert marker.server_ts == finished_at + timedelta(hours=48)

    clock.advance(24 * 3600)
    assert mark_incomplete_uploads(db, clock, 48 * 3600) == []  # once, however often it runs
    assert len(markers(db, finished.session_id)) == 1


def test_a_complete_upload_is_never_marked(db, clock, finished):
    for seq in range(3):
        finished.put_chunk(seq, media_chunk(seq))
    finished.finish(chunks_total=3)
    clock.advance(5 * 24 * 3600)
    assert mark_incomplete_uploads(db, clock, 48 * 3600) == []


def test_a_session_that_never_reported_a_total_counts_as_incomplete(db, clock, finished):
    finished.put_chunk(0, media_chunk(0))  # the page closed before it could say how many
    clock.advance(3 * 24 * 3600)
    assert mark_incomplete_uploads(db, clock, 48 * 3600) == [finished.session_id]


def test_the_marker_never_clashes_with_a_number_the_page_can_send(client, db, clock, finished):
    response = finished.events({"client_seq": -1, "type": "upload_incomplete"})
    assert response.status_code == 422  # a page cannot send a negative number at all
    assert finished.events({"client_seq": 0, "type": "upload_incomplete"}).status_code == 200
    clock.advance(3 * 24 * 3600)
    assert mark_incomplete_uploads(db, clock, 48 * 3600) == [finished.session_id]


def test_an_upload_forgotten_for_more_than_a_week_past_the_window_is_not_reread(
    db, clock, finished
):
    finished.put_chunk(0, media_chunk(0))
    clock.advance(10 * 24 * 3600)  # the window closed eight days ago and nobody ran the job
    assert mark_incomplete_uploads(db, clock, 48 * 3600) == []
