"""The device pre-check: what the page reports about the camera, microphone, full screen and the
notification warning, and whether the test may start.

Only the camera and the microphone gate the start (the proposal's one automatic outcome). The
notification confirmation and the full-screen result are kept in the report for the reviewer and
are never part of the gate. The page cannot read the system's notification settings, so that
checkbox is the candidate's own word.
"""

from sqlalchemy.orm import Session

from app.clock import Clock
from app.errors import ApiError
from app.models import TestSession
from app.schemas.recording import PrecheckRequest
from app.services.video.chunks import recording_verified


def passes(body: PrecheckRequest) -> bool:
    """Camera ok, and the microphone ok or its step switched off for testing. A microphone that
    was checked and failed never passes."""
    return body.camera_ok and (body.mic_ok or not body.mic_checked)


def record_result(db: Session, clock: Clock, session: TestSession, body: PrecheckRequest) -> bool:
    """Store the report. Once the test has begun the result is no longer the gate, so a late
    report changes nothing and the answer is whatever was already decided."""
    if session.status != "created":
        return session.precheck_passed_at is not None

    passed = passes(body)
    now = clock.now()
    report = body.model_dump()
    report["checked_at"] = now.isoformat()
    session.precheck_report = report
    session.precheck_passed_at = now if passed else None
    db.commit()
    return passed


def require_ready(db: Session, session: TestSession, gate: str) -> None:
    """Raise 409 unless the start gate is met. `off` waives it (development only; a production
    server cannot be configured that way, see Settings)."""
    if gate == "off":
        return
    if session.precheck_passed_at is None:
        raise ApiError(409, "precheck_required", reason="precheck")
    if gate == "recording" and not recording_verified(db, session.id):
        # the page starts recording first and waits for chunk 0 to be accepted before it begins
        raise ApiError(409, "precheck_required", reason="recording")
