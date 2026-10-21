from datetime import timedelta

from fastapi import Depends, Header, Request
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.clock import Clock, SystemClock
from app.config import Settings, get_settings
from app.core.security import hash_token
from app.core.staff_token import fingerprint_matches, read_staff_token
from app.db import get_db
from app.errors import ApiError
from app.models import Reviewer, TestSession
from app.services.rate_limit import AttemptLimiter
from app.services.video.store import LocalVideoStore, VideoStore

_clock: Clock = SystemClock()
_start_limiter: AttemptLimiter | None = None
_login_limiter: AttemptLimiter | None = None


def get_clock() -> Clock:
    """FastAPI dependency. Tests override it with a FakeClock."""
    return _clock


def get_video_store(settings: Settings = Depends(get_settings)) -> VideoStore:
    """FastAPI dependency: where video bytes are kept. Tests point the video root at a temp folder
    through their settings."""
    return LocalVideoStore(settings.video_root_path)


def get_start_limiter(settings: Settings = Depends(get_settings)) -> AttemptLimiter:
    """FastAPI dependency: the one limiter for wrong invitation codes. Tests override it."""
    global _start_limiter
    if _start_limiter is None:
        _start_limiter = AttemptLimiter(settings.start_max_failures, settings.start_window_s)
    return _start_limiter


def get_login_limiter(settings: Settings = Depends(get_settings)) -> AttemptLimiter:
    """FastAPI dependency: the one limiter for wrong staff passwords. Tests override it."""
    global _login_limiter
    if _login_limiter is None:
        _login_limiter = AttemptLimiter(settings.login_max_failures, settings.login_window_s)
    return _login_limiter


def client_key(request: Request, settings: Settings) -> str:
    """Who is asking, for the attempt limits.

    Behind our own reverse proxy the real client is the last X-Forwarded-For entry (the one the
    proxy appended; earlier entries are whatever the client claimed). Otherwise it is the peer.
    """
    if settings.trust_forwarded_for:
        last = request.headers.get("x-forwarded-for", "").split(",")[-1].strip()
        if last:
            return last
    return request.client.host if request.client else "unknown"


def bearer_token(authorization: str | None) -> str | None:
    scheme, _, token = (authorization or "").partition(" ")
    return token if scheme.lower() == "bearer" and token else None


def session_from_token(
    authorization: str | None = Header(default=None), db: Session = Depends(get_db)
) -> TestSession:
    """The candidate's session, found from the bearer token alone (routes with no session id in
    the path: heartbeat, pre-check). Not locked: these arrive every few seconds and must never
    queue behind a candidate answering a question."""
    token = bearer_token(authorization)
    session = (
        db.scalar(select(TestSession).where(TestSession.access_token_hash == hash_token(token)))
        if token
        else None
    )
    if session is None:
        raise ApiError(401, "unauthorized")
    return session


def session_from_any_token(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
    settings: Settings = Depends(get_settings),
) -> TestSession:
    """The candidate's session from either token: the test's own, or the upload-only one that
    POST /session/resume issues. For the routes that keep working while the video uploads
    (events, chunks, complaints). Once the resume window after finishing has passed, 410."""
    token = bearer_token(authorization)
    session = None
    if token:
        digest = hash_token(token)
        session = db.scalar(
            select(TestSession).where(
                or_(
                    TestSession.access_token_hash == digest,
                    TestSession.upload_token_hash == digest,
                )
            )
        )
    if session is None:
        raise ApiError(401, "unauthorized")
    window = timedelta(seconds=settings.resume_window_s)
    if session.finished_at is not None and clock.now() - session.finished_at > window:
        raise ApiError(410, "upload_window_closed")
    return session


def current_staff(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
    settings: Settings = Depends(get_settings),
) -> Reviewer:
    """The signed-in, active staff account for this request, or 401 `unauthorized`.

    The account row is read every time (one primary-key lookup), so a switched-off account or a
    changed password stops its tokens at once, and the role is never taken from the token.
    """
    scheme, _, token = (authorization or "").partition(" ")
    claims = None
    if scheme.lower() == "bearer":
        claims = read_staff_token(settings.session_secret, clock, token, settings.staff_token_ttl_s)
    reviewer = db.get(Reviewer, claims["sub"]) if claims else None
    if (
        reviewer is None
        or not reviewer.is_active
        or not fingerprint_matches(claims["pw"], reviewer.password_hash)
    ):
        raise ApiError(401, "unauthorized")
    return reviewer


def require_reviewer(staff: Reviewer = Depends(current_staff)) -> Reviewer:
    """Any active staff account; admins are included."""
    return staff


def require_admin(staff: Reviewer = Depends(current_staff)) -> Reviewer:
    if staff.role != "admin":
        raise ApiError(403, "forbidden")
    return staff
