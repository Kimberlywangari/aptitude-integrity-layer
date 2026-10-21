"""A reviewer watching a candidate's recording: where each flag lands in it, the signed links the
<video> element plays from, range requests so it can scrub, who may watch, and the audit trail.

The recordings here are made-up files with segment rows written directly, so none of this needs
ffmpeg; assembly itself is covered in test_video_pipeline.py.
"""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.video_url import issue_video_token
from app.models import Reviewer, TestSession, VideoChunk, VideoSegment
from app.services.ranking.rules import rule_order
from app.services.video import ffmpeg
from app.services.video.store import LocalVideoStore, assembled_key, chunk_key

SECRET = "test-secret"
SIZE = 4000


def payload(segment: int) -> bytes:
    return bytes((segment * 37 + i) % 251 for i in range(SIZE))


@pytest.fixture
def store(settings):
    return LocalVideoStore(settings.video_root_path)


@pytest.fixture
def target(db, sim):
    """A queued candidate: flagged enough to be in the queue, so their video may be watched."""
    return rule_order(db, sim.sitting_id)[0].session


def add_segments(db, store, session, spans=((0, 600), (700, 800))):
    """Segment rows and files. Each tuple is (seconds after the recording began, length)."""
    anchor = session.recording_started_at
    for number, (offset, length) in enumerate(spans):
        key = assembled_key(session.id, number)
        store.put(key, payload(number))
        db.add(
            VideoSegment(
                session_id=session.id,
                segment=number,
                started_at=anchor + timedelta(seconds=offset),
                duration_s=float(length),
                chunk_count=3,
                bytes=SIZE,
                path=key,
                assembled_at=anchor,
            )
        )
    db.flush()


@pytest.fixture
def watched(db, store, target):
    add_segments(db, store, target)
    return target


def detail(client, staff, candidate):
    return client.get(f"/api/review/candidates/{candidate}", headers=staff).json()


def expected_seek(offset):
    """`offset` is seconds from the start of the recording; the two segments cover 0 to 600 and
    700 to 1500, so anything between is a gap."""
    if 0 <= offset <= 600:
        return {"segment": 0, "seek_s": pytest.approx(max(0.0, offset - 5), abs=0.01)}
    if 700 <= offset <= 1500:
        return {"segment": 1, "seek_s": pytest.approx(max(0.0, offset - 700 - 5), abs=0.01)}
    return None


def offset_of(flag, session):
    moment = datetime.fromisoformat(flag["server_ts"])
    return (moment - session.recording_started_at).total_seconds()


# ------------------------------------------------------------------------- the candidate page


def test_the_page_lists_each_segment_with_a_signed_link_and_its_place_in_the_recording(
    client, staff, watched
):
    body = detail(client, staff, watched.candidate_id)

    first, second = body["segments"]
    assert (first["segment"], first["start_s"], first["duration_s"]) == (0, 0.0, 600.0)
    assert (second["segment"], second["start_s"], second["duration_s"]) == (1, 700.0, 800.0)
    prefix = f"/api/review/candidates/{watched.candidate_id}/video?segment="
    assert first["url"].startswith(prefix + "0&t=") and second["url"].startswith(prefix + "1&t=")


def test_every_flag_knows_where_it_sits_in_the_recording_five_seconds_early(client, staff, watched):
    body = detail(client, staff, watched.candidate_id)
    assert body["flags"]
    seeks = []
    for flag in body["flags"]:
        assert flag["video_seek"] == expected_seek(offset_of(flag, watched)), flag["id"]
        seeks.append(flag["video_seek"])
    assert any(seeks), "at least one flag falls inside a recorded part"


def test_a_moment_in_the_gap_between_segments_has_no_video(client, db, store, staff, target):
    add_segments(db, store, target, spans=((0, 10), (20, 10)))  # nearly everything is a gap
    body = detail(client, staff, target.candidate_id)
    gaps = [f for f in body["flags"] if f["video_seek"] is None]
    assert gaps and all(f["elapsed_s"] > 30 or 10 < f["elapsed_s"] < 20 for f in gaps)


def test_a_candidate_with_no_recording_shows_no_segments_and_no_seeks(client, staff, target):
    body = detail(client, staff, target.candidate_id)
    assert body["segments"] == []
    assert all(f["video_seek"] is None for f in body["flags"])


def test_a_quiet_stretch_gets_a_jump_target_too(client, db, store, staff, sim):
    for item in rule_order(db, sim.sitting_id):
        session = item.session
        body = detail(client, staff, session.candidate_id)
        if body["mic_silence"]:
            add_segments(db, store, session, spans=((0, 1500),))
            body = detail(client, staff, session.candidate_id)
            stretch = body["mic_silence"][0]
            assert stretch["video_seek"] == {
                "segment": 0,
                "seek_s": max(0.0, stretch["start_s"] - 5),
            }
            return
    pytest.fail("the simulator makes a flagged candidate with a quiet stretch")


# --------------------------------------------------------------------------------- playing


def link(client, staff, candidate, segment=0):
    return detail(client, staff, candidate)["segments"][segment]["url"]


def test_the_signed_link_plays_without_any_authorization_header(client, staff, watched):
    response = client.get(link(client, staff, watched.candidate_id))

    assert response.status_code == 200
    assert response.content == payload(0)
    assert response.headers["content-type"] == "video/webm"
    assert response.headers["accept-ranges"] == "bytes"
    assert response.headers["cache-control"] == "private, no-store"


def test_a_range_request_gets_just_that_piece_so_the_player_can_scrub(client, staff, watched):
    url = link(client, staff, watched.candidate_id, segment=1)

    response = client.get(url, headers={"Range": "bytes=100-199"})

    assert response.status_code == 206
    assert response.content == payload(1)[100:200]
    assert response.headers["content-range"] == f"bytes 100-199/{SIZE}"


def test_the_staff_token_works_in_place_of_the_link(client, staff, watched):
    path = f"/api/review/candidates/{watched.candidate_id}/video"
    assert client.get(path, params={"segment": 1}, headers=staff).content == payload(1)
    assert client.get(path, params={"segment": 1}).status_code == 401


def test_a_link_cannot_be_altered_reused_for_another_part_or_aimed_at_another_candidate(
    client, db, staff, watched, sim
):
    url = link(client, staff, watched.candidate_id)
    assert client.get(url + "x").status_code == 401
    assert client.get(url.replace("segment=0", "segment=1")).status_code == 401
    other = db.scalars(select(TestSession).where(TestSession.id != watched.id)).first()
    wrong_person = url.replace(watched.candidate_id, other.candidate_id)
    assert client.get(wrong_person).status_code == 401


def test_a_link_goes_stale_after_four_hours(client, clock, staff, watched):
    url = link(client, staff, watched.candidate_id)
    clock.advance(4 * 3600 - 60)
    assert client.get(url).status_code == 200
    clock.advance(120)
    assert client.get(url).status_code == 401


def test_a_link_stops_working_the_moment_the_reviewer_is_switched_off(client, db, staff, watched):
    url = link(client, staff, watched.candidate_id)
    db.query(Reviewer).update({"is_active": False})
    db.flush()
    assert client.get(url).status_code == 401


def test_a_part_that_does_not_exist_is_not_found(client, staff, watched):
    path = f"/api/review/candidates/{watched.candidate_id}/video"
    response = client.get(path, params={"segment": 7}, headers=staff)
    assert response.status_code == 404 and response.json() == {"code": "no_such_segment"}


# ------------------------------------------------------------------------------ who may watch


def test_someone_not_in_the_queue_and_not_shortlisted_cannot_be_watched(
    client, db, clock, store, staff, sim
):
    queued = {o.session.id for o in rule_order(db, sim.sitting_id)}
    quiet = next(s for s in db.scalars(select(TestSession)) if s.id not in queued)
    add_segments(db, store, quiet)
    reviewer_id = db.scalar(select(Reviewer.id))
    token = issue_video_token(SECRET, clock, reviewer_id, quiet.id, 0)
    url = f"/api/review/candidates/{quiet.candidate_id}/video?segment=0&t={token}"

    refused = client.get(url)
    assert refused.status_code == 403 and refused.json() == {"code": "video_not_available"}

    client.post(f"/api/review/candidates/{quiet.candidate_id}/shortlist", headers=staff)
    assert client.get(url).status_code == 200


def test_video_that_has_been_deleted_is_gone_and_the_page_says_so(
    client, db, clock, staff, watched
):
    url = link(client, staff, watched.candidate_id)
    watched.video_deleted_at = clock.now()
    db.flush()

    gone = client.get(url)
    assert gone.status_code == 410 and gone.json() == {"code": "video_deleted"}
    assert detail(client, staff, watched.candidate_id)["video_deleted_at"] is not None


# ------------------------------------------------------------------------------------ audit


def watched_entries(client, staff):
    entries = client.get("/api/review/audit", headers=staff).json()["entries"]
    return [e for e in entries if e["action"] == "video_view" and e["detail"].startswith("playing")]


def test_watching_is_audited_once_per_part_per_five_minutes_however_many_requests(
    client, clock, staff, watched
):
    url = link(client, staff, watched.candidate_id)
    for start in (0, 500, 1000, 1500):
        client.get(url, headers={"Range": f"bytes={start}-{start + 99}"})
    (entry,) = watched_entries(client, staff)
    assert entry["detail"] == "playing part 1" and entry["candidate_id"] == watched.candidate_id

    clock.advance(6 * 60)
    client.get(url)
    assert len(watched_entries(client, staff)) == 2

    client.get(link(client, staff, watched.candidate_id, segment=1))
    assert {e["detail"] for e in watched_entries(client, staff)} == {
        "playing part 1",
        "playing part 2",
    }


# --------------------------------------------------------------------------------- no ffmpeg


def test_without_ffmpeg_a_recording_not_yet_assembled_is_a_clear_503_and_the_page_still_loads(
    client, db, clock, staff, store, target, monkeypatch
):
    key = chunk_key(target.id, 0, 0)
    store.put(key, b"raw chunk")
    db.add(
        VideoChunk(
            session_id=target.id,
            segment=0,
            seq=0,
            bytes=9,
            sha256="0" * 64,
            path=key,
            received_at=clock.now(),
        )
    )
    db.flush()

    def missing():
        raise ffmpeg.FfmpegMissing("ffmpeg was not found")

    monkeypatch.setattr(ffmpeg, "ffmpeg_path", missing)

    assert detail(client, staff, target.candidate_id)["segments"] == []  # the page must not fail
    token = issue_video_token(SECRET, clock, db.scalar(select(Reviewer.id)), target.id, 0)
    response = client.get(f"/api/review/candidates/{target.candidate_id}/video?segment=0&t={token}")
    assert response.status_code == 503 and response.json() == {"code": "ffmpeg_missing"}
