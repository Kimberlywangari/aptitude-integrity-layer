"""What the candidate's page sends while the test runs and after it: the action log, the heartbeat,
the pre-check, video chunks and their manifest, complaints, and resuming an upload."""

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.config import Settings
from app.models import Complaint, Event, Heartbeat, VideoChunk
from tests.support import Live, media_chunk, sha, webm_header

ONE_DAY = 24 * 3600


@pytest.fixture
def live(client, db, seeded):
    return Live(client, db, seeded.invites[0].token).start()


@pytest.fixture
def running(live):
    assert live.begin().status_code == 200
    return live


@pytest.fixture
def other(client, db, seeded):
    return Live(client, db, seeded.invites[1].token).start()


def event(seq, type_="focus_lost", age_ms=0, payload=None):
    body = {"client_seq": seq, "type": type_, "age_ms": age_ms}
    if payload is not None:
        body["payload"] = payload
    return body


def stored_events(db, session_id):
    db.expire_all()
    return list(
        db.scalars(select(Event).where(Event.session_id == session_id).order_by(Event.client_seq))
    )


# ----------------------------------------------------------------------------------- events


def test_events_are_stored_with_the_servers_own_time(running, db, clock):
    clock.advance(100)
    response = running.events(event(1, "focus_lost"), event(2, "focus_returned", age_ms=4500))

    assert response.status_code == 200
    assert response.json() == {"accepted": 2, "duplicates": 0, "rejected": 0}
    first, second = stored_events(db, running.session_id)
    assert first.server_ts == clock.now()
    assert second.server_ts == clock.now() - timedelta(milliseconds=4500)
    assert first.received_at == second.received_at == clock.now()


def test_sending_a_batch_again_changes_nothing(running, db):
    batch = [event(1), event(2, "focus_returned")]
    assert running.events(*batch).json()["accepted"] == 2

    again = running.events(*batch, event(3)).json()

    assert again == {"accepted": 1, "duplicates": 2, "rejected": 0}
    assert len(stored_events(db, running.session_id)) == 3


def test_a_repeat_inside_one_batch_is_counted_once(running, db):
    response = running.events(event(1), event(1)).json()
    assert response["accepted"] == 1
    assert len(stored_events(db, running.session_id)) == 1


def test_an_unknown_event_type_is_rejected_but_the_rest_of_the_batch_lands(running, db):
    response = running.events(event(1, "keystroke_log"), event(2, "focus_lost")).json()
    assert response == {"accepted": 1, "duplicates": 0, "rejected": 1}
    assert [e.type for e in stored_events(db, running.session_id)] == ["focus_lost"]


def test_a_copy_event_keeps_the_length_and_never_the_text(running, db):
    running.events(
        event(1, "copy_attempt", payload={"length": 212, "text": "the question wording", "q": 3}),
        event(2, "cut_attempt", payload={"length": "not a number", "selection": "abc"}),
        event(3, "paste_attempt", payload={"text": "pasted words"}),
    )
    copy, cut, paste = stored_events(db, running.session_id)
    assert copy.payload == {"length": 212}
    assert cut.payload is None
    assert paste.payload is None


def test_device_labels_are_trimmed_and_unknown_fields_dropped(running, db):
    running.events(
        event(
            1,
            "device_info",
            payload={"camera_label": "  Webcam  ", "mic_label": "m" * 500, "serial": "XYZ"},
        )
    )
    (stored,) = stored_events(db, running.session_id)
    assert stored.payload == {"camera_label": "Webcam", "mic_label": "m" * 200}


def test_an_event_cannot_be_dated_before_the_session_existed(running, db):
    running.events(event(1, age_ms=47 * 3600 * 1000))
    (stored,) = stored_events(db, running.session_id)
    assert stored.server_ts == running.session().created_at


def test_the_first_recording_start_anchors_the_video(running, db, clock):
    clock.advance(30)
    running.events(event(1, "recording_started", payload={"segment": 0}))
    assert running.session().recording_started_at == clock.now()

    clock.advance(60)
    running.events(event(2, "recording_started", payload={"segment": 1}))  # a later segment
    assert running.session().recording_started_at == clock.now() - timedelta(seconds=60)


def test_a_batch_of_more_than_a_hundred_is_refused(running):
    response = running.events(*[event(n) for n in range(101)])
    assert response.status_code == 422


def test_events_need_a_token(client, running):
    assert client.post("/api/events", json={"events": [event(1)]}).status_code == 401
    bad = {"Authorization": "Bearer nope"}
    assert running.events(event(1), headers=bad).status_code == 401


# --------------------------------------------------------------------------------- heartbeat


def test_a_heartbeat_before_the_test_begins_stores_nothing(live, db):
    body = live.heartbeat().json()
    assert body["status"] == "created" and body["remaining_s"] == 0
    assert db.scalar(select(Heartbeat).where(Heartbeat.session_id == live.session_id)) is None


def test_a_heartbeat_while_running_stores_a_tick_and_resyncs_the_clock(running, db, clock):
    clock.advance(75)
    body = running.heartbeat().json()

    assert body["status"] == "in_progress"
    assert body["remaining_s"] == 1800 - 75
    assert body["server_time"].startswith(clock.now().strftime("%Y-%m-%dT%H:%M:%S"))
    (tick,) = db.scalars(select(Heartbeat).where(Heartbeat.session_id == running.session_id))
    assert tick.server_ts == clock.now()


def test_a_heartbeat_after_time_is_up_stores_nothing(running, db, clock):
    clock.advance(1801)
    body = running.heartbeat().json()
    assert body["remaining_s"] == 0
    assert db.scalar(select(Heartbeat).where(Heartbeat.session_id == running.session_id)) is None


def test_a_heartbeat_needs_the_tests_own_token(client):
    assert client.post("/api/heartbeat").status_code == 401


# --------------------------------------------------------------------------------- pre-check


def test_a_good_precheck_passes_and_is_kept_for_the_reviewer(live):
    response = live.precheck()
    assert response.status_code == 200 and response.json() == {"passed": True}
    session = live.session()
    assert session.precheck_passed_at is not None
    report = session.precheck_report
    assert report["notifications_off_confirmed"] is True
    assert report["fullscreen_ok"] is True
    assert report["browser"] == {"name": "Chrome", "version": "141"}
    assert report["device_labels"]["camera"] == "Integrated Webcam"


@pytest.mark.parametrize(
    "overrides,passed",
    [
        ({"camera_ok": False}, False),
        ({"mic_ok": False}, False),  # checked and failed
        ({"mic_ok": False, "mic_checked": False}, True),  # step switched off for testing
        ({"camera_ok": False, "mic_ok": False, "mic_checked": False}, False),
        # the notification box and full screen are context for a reviewer, never the gate
        ({"notifications_off_confirmed": False, "fullscreen_ok": False}, True),
    ],
)
def test_only_the_camera_and_microphone_decide_the_result(live, overrides, passed):
    assert live.precheck(**overrides).json() == {"passed": passed}
    assert (live.session().precheck_passed_at is not None) is passed


def test_a_later_failed_check_withdraws_an_earlier_pass(live):
    live.precheck()
    live.precheck(camera_ok=False)
    assert live.session().precheck_passed_at is None


def test_a_report_after_the_test_has_begun_changes_nothing(running):
    before = running.session().precheck_report
    assert running.precheck(camera_ok=False).json() == {"passed": False}
    assert running.session().precheck_report == before


def test_precheck_needs_a_token(client):
    assert (
        client.post("/api/precheck/result", json={"camera_ok": True, "mic_ok": True}).status_code
        == 401
    )


# --------------------------------------------------------------------------- the start gate


def test_with_the_gate_off_the_test_begins_without_a_precheck(live):
    assert live.begin().status_code == 200


def test_the_precheck_gate_blocks_begin_until_it_passes(live, settings):
    settings.precheck_gate = "precheck"

    refused = live.begin()
    assert refused.status_code == 409
    assert refused.json() == {"code": "precheck_required", "reason": "precheck"}

    live.precheck(camera_ok=False)
    assert live.begin().status_code == 409

    live.precheck()
    assert live.begin().status_code == 200


def test_the_recording_gate_needs_a_real_video_and_audio_chunk(live, settings):
    settings.precheck_gate = "recording"
    live.precheck()

    refused = live.begin()
    assert refused.json() == {"code": "precheck_required", "reason": "recording"}

    assert live.put_chunk(0, webm_header(audio=False)).status_code == 200  # video only
    assert live.begin().status_code == 409
    assert live.put_chunk(1, media_chunk(1)).status_code == 200  # no header: says nothing
    assert live.begin().status_code == 409

    # chunk 0 cannot be replaced (same number, new bytes), but a fresh recorder run can: its
    # opening chunk carries its own header and proves a real video and audio recording
    assert live.put_chunk(0, webm_header()).status_code == 409
    assert live.put_chunk(2, webm_header(), segment=1).status_code == 200
    assert live.begin().status_code == 200


def test_the_recording_gate_opens_with_a_video_and_audio_first_chunk(live, settings):
    settings.precheck_gate = "recording"
    live.precheck()
    assert live.put_chunk(0, webm_header()).status_code == 200
    assert live.begin().status_code == 200


def test_begin_is_idempotent_once_running_even_with_the_gate_on(live, settings):
    settings.precheck_gate = "recording"
    live.precheck()
    live.put_chunk(0, webm_header())
    assert live.begin().status_code == 200
    settings.precheck_gate = "recording"
    assert live.begin().status_code == 200


def test_a_production_server_cannot_run_without_the_recording_gate():
    with pytest.raises(ValueError, match="PRECHECK_GATE"):
        Settings(env="production", precheck_gate="off", session_secret="x")
    with pytest.raises(ValueError, match="PRECHECK_GATE"):
        Settings(env="production", precheck_gate="precheck", session_secret="x")
    assert Settings(env="production", precheck_gate="recording", session_secret="x")


# ---------------------------------------------------------------------------------- chunks


def test_a_chunk_is_stored_checked_and_recorded(live, settings, db):
    data = webm_header()
    response = live.put_chunk(0, data)

    assert response.status_code == 200 and response.json() == {"status": "stored"}
    row = db.scalar(select(VideoChunk).where(VideoChunk.session_id == live.session_id))
    assert (row.seq, row.segment, row.bytes, row.sha256) == (0, 0, len(data), sha(data))
    assert (row.has_video, row.has_audio) == (True, True)
    on_disk = settings.video_root_path / row.path
    assert on_disk.read_bytes() == data


def test_a_chunk_without_a_header_has_unknown_tracks(live, db):
    live.put_chunk(3, media_chunk(3))
    row = db.scalar(select(VideoChunk).where(VideoChunk.session_id == live.session_id))
    assert row.has_video is None and row.has_audio is None


def test_the_same_chunk_twice_is_a_duplicate_not_an_error(live, db):
    data = media_chunk(1)
    assert live.put_chunk(1, data).json() == {"status": "stored"}
    assert live.put_chunk(1, data).json() == {"status": "duplicate"}
    assert db.scalars(select(VideoChunk)).all().__len__() == 1


def test_a_different_chunk_under_a_used_number_is_refused(live):
    live.put_chunk(1, media_chunk(1))
    response = live.put_chunk(1, media_chunk(2))
    assert response.status_code == 409 and response.json() == {"code": "chunk_conflict"}


def test_a_chunk_damaged_in_transit_is_refused(live, db):
    response = live.put_chunk(0, media_chunk(1), digest=sha(b"something else"))
    assert response.status_code == 422 and response.json() == {"code": "checksum_mismatch"}
    assert db.scalars(select(VideoChunk)).first() is None


def test_a_chunk_with_no_checksum_is_refused(live):
    response = live.client.put(
        f"/api/chunks/{live.session_id}/0", content=b"abc", headers=live.headers
    )
    assert response.status_code == 422 and response.json() == {"code": "missing_checksum"}


def test_an_oversized_chunk_is_refused(live, settings):
    settings.chunk_max_bytes = 1000
    data = media_chunk(1, size=2000)
    response = live.put_chunk(0, data)
    assert response.status_code == 413
    assert response.json() == {"code": "chunk_too_large", "max_bytes": 1000}


@pytest.mark.parametrize("segment", ["-1", "abc", "5000"])
def test_a_bad_segment_number_is_refused(live, segment):
    data = media_chunk(1)
    response = live.client.put(
        f"/api/chunks/{live.session_id}/0",
        content=data,
        headers={**live.headers, "X-Chunk-SHA256": sha(data), "X-Chunk-Segment": segment},
    )
    assert response.status_code == 422 and response.json() == {"code": "bad_segment"}


def test_chunks_may_arrive_out_of_order(live, db):
    for seq in (2, 0, 1):
        assert live.put_chunk(seq, media_chunk(seq)).status_code == 200
    seqs = [c.seq for c in db.scalars(select(VideoChunk).order_by(VideoChunk.seq))]
    assert seqs == [0, 1, 2]


def test_a_chunk_needs_the_right_token(live, other):
    data = media_chunk(1)
    assert live.put_chunk(0, data, headers={"Authorization": "Bearer nope"}).status_code == 401
    # another candidate's token, aimed at this candidate's session
    assert live.put_chunk(0, data, headers=other.headers).status_code == 401
    assert live.client.put(f"/api/chunks/{live.session_id}/0", content=data).status_code == 401


def test_a_chunk_for_a_session_whose_video_was_deleted_is_gone(live, db, clock):
    session = live.session()
    session.video_deleted_at = clock.now()
    db.flush()
    assert live.put_chunk(0, media_chunk(1)).status_code == 410


def test_fault_injection_refuses_uploads_in_development_only(live, settings):
    settings.chunk_fail_rate = 1.0
    refused = live.put_chunk(0, media_chunk(1))
    assert refused.status_code == 503 and refused.json() == {"code": "chunk_unavailable"}

    settings.env = "production"  # ignored in production
    assert live.put_chunk(0, media_chunk(1)).status_code == 200


# --------------------------------------------------------------------------------- manifest


def test_the_manifest_of_a_running_session_reports_gaps_below_the_highest_chunk(running):
    for seq in (0, 1, 3):
        running.put_chunk(seq, media_chunk(seq))
    body = running.manifest().json()

    assert body["expected"] is None
    assert (body["received"], body["missing"], body["complete"]) == (3, 1, False)
    assert body["bytes"] > 0


def test_the_manifest_is_complete_only_when_every_chunk_up_to_the_total_has_arrived(running, clock):
    for seq in (0, 1, 3):
        running.put_chunk(seq, media_chunk(seq))
    running.answer_everything(clock)
    assert running.finish(chunks_total=4).status_code == 200

    body = running.manifest().json()
    assert (body["expected"], body["received"], body["missing"], body["complete"]) == (
        4,
        3,
        1,
        False,
    )

    running.put_chunk(2, media_chunk(2))
    body = running.manifest().json()
    assert (body["missing"], body["complete"]) == (0, True)


def test_chunks_past_the_total_do_not_hide_a_missing_one(running, clock):
    running.put_chunk(0, media_chunk(0))
    running.put_chunk(2, media_chunk(2))
    running.answer_everything(clock)
    running.finish(chunks_total=2)  # 0 and 1 expected; 1 never arrived, 2 is extra

    body = running.manifest().json()
    assert body["missing"] == 1 and body["complete"] is False


def test_a_session_that_finished_with_no_chunks_has_nothing_to_upload(running, clock):
    running.answer_everything(clock)
    running.finish(chunks_total=0)
    assert running.manifest().json()["complete"] is True


def test_the_manifest_is_never_complete_before_the_test_finishes(running):
    running.put_chunk(0, media_chunk(0))
    assert running.manifest().json()["complete"] is False


def test_finishing_again_updates_the_total(running, clock):
    running.answer_everything(clock)
    running.finish(chunks_total=3)
    running.finish(chunks_total=5)
    assert running.session().chunks_total == 5
    assert running.finish().status_code == 200  # no body: nothing changes
    assert running.session().chunks_total == 5


def test_the_manifest_belongs_to_one_candidate(live, other):
    assert other.manifest(headers=live.headers).status_code == 401


# ------------------------------------------------------------------------------- complaints


def test_a_complaint_is_stored_for_a_person_to_read(running, db, clock):
    response = running.client.post(
        "/api/complaints",
        json={"category": "camera", "text": "  My camera light went out.  "},
        headers=running.headers,
    )
    assert response.status_code == 204
    (row,) = db.scalars(select(Complaint).where(Complaint.session_id == running.session_id))
    assert (row.category, row.text, row.status) == ("camera", "My camera light went out.", "open")
    assert row.created_at == clock.now()


@pytest.mark.parametrize(
    "body",
    [
        {"category": "weather", "text": "hello"},
        {"category": "camera", "text": "   "},
        {"category": "camera", "text": "x" * 1001},
    ],
)
def test_a_bad_complaint_is_refused(running, body):
    response = running.client.post("/api/complaints", json=body, headers=running.headers)
    assert response.status_code == 422 and response.json() == {"code": "invalid_complaint"}


def test_a_session_cannot_file_unlimited_complaints(running):
    body = {"category": "other", "text": "again"}
    for _ in range(10):
        assert (
            running.client.post("/api/complaints", json=body, headers=running.headers).status_code
            == 204
        )
    response = running.client.post("/api/complaints", json=body, headers=running.headers)
    assert response.status_code == 429 and response.json() == {"code": "too_many_complaints"}


def test_a_complaint_needs_a_token(client):
    assert (
        client.post("/api/complaints", json={"category": "other", "text": "hi"}).status_code == 401
    )


# ---------------------------------------------------------------------------------- resume


@pytest.fixture
def finished(running, clock):
    running.put_chunk(0, webm_header())
    running.answer_everything(clock)
    running.finish(chunks_total=3)
    return running


def resume(live, code=None):
    return live.client.post("/api/session/resume", json={"token": code or live.invite_token})


def test_resume_needs_a_finished_test(live):
    response = resume(live)
    assert response.status_code == 409 and response.json() == {"code": "nothing_to_resume"}


def test_resume_gives_an_upload_only_token(finished):
    body = resume(finished).json()
    assert body["session_id"] == finished.session_id and body["status"] == "finished"
    upload = {"Authorization": f"Bearer {body['access_token']}"}

    assert finished.put_chunk(1, media_chunk(1), headers=upload).status_code == 200
    assert finished.manifest(headers=upload).status_code == 200
    assert finished.events(event(1, "upload_incomplete"), headers=upload).status_code == 200
    # but it opens nothing else
    assert finished.client.get(finished.url("question"), headers=upload).status_code == 401
    assert finished.client.post(finished.url("finish"), headers=upload).status_code == 401
    assert finished.client.post("/api/heartbeat", headers=upload).status_code == 401


def test_the_upload_window_lasts_forty_eight_hours(finished, clock):
    clock.advance(2 * ONE_DAY - 60)
    assert resume(finished).status_code == 200
    assert finished.put_chunk(1, media_chunk(1)).status_code == 200  # the old token still works

    clock.advance(120)
    refused = resume(finished)
    assert refused.status_code == 410 and refused.json() == {"code": "resume_window_closed"}
    assert finished.put_chunk(2, media_chunk(2)).status_code == 410
    assert finished.manifest().status_code == 410
    assert finished.events(event(9)).status_code == 410


def test_a_wrong_code_cannot_resume_and_counts_against_the_limit(client, finished, settings):
    for _ in range(settings.start_max_failures):
        assert resume(finished, code="ZZZZ-ZZZZ").status_code == 401
    blocked = resume(finished, code="ZZZZ-ZZZZ")
    assert blocked.status_code == 429
