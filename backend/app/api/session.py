from dataclasses import asdict

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_clock, get_start_limiter
from app.clock import Clock
from app.config import Settings, get_settings
from app.core.seb import require_seb
from app.core.security import tokens_match
from app.db import get_db
from app.errors import ApiError
from app.models import TestSession
from app.schemas.session import (
    AnswerRequest,
    BeginRequest,
    BeginResponse,
    FinishResponse,
    OptionView,
    QuestionResponse,
    ResolveResponse,
    SelfReportRequest,
    SkipRequest,
    StartRequest,
    StartResponse,
)
from app.services import test_flow
from app.services.rate_limit import AttemptLimiter

router = APIRouter(prefix="/session", tags=["session"])


def current_session(
    session_id: str,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> TestSession:
    """Resolve the session from the path and check the bearer token belongs to *that* session.

    The row is locked for the rest of the request, so two taps on Submit can't both win.
    """
    scheme, _, token = (authorization or "").partition(" ")
    session = db.scalar(select(TestSession).where(TestSession.id == session_id).with_for_update())
    valid = (
        scheme.lower() == "bearer"
        and session is not None
        and tokens_match(token, session.access_token_hash)
    )
    if not valid:
        raise ApiError(401, "unauthorized")
    return session


def client_key(request: Request, settings: Settings) -> str:
    """Who is asking, for the wrong-code limit.

    Behind our own reverse proxy the real client is the last X-Forwarded-For entry (the one the
    proxy appended; earlier entries are whatever the client claimed). Otherwise it is the peer.
    """
    if settings.trust_forwarded_for:
        last = request.headers.get("x-forwarded-for", "").split(",")[-1].strip()
        if last:
            return last
    return request.client.host if request.client else "unknown"


@router.post("/start", response_model=StartResponse)
def start(
    body: StartRequest,
    request: Request,
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
    seb_verified: bool = Depends(require_seb),
    limiter: AttemptLimiter = Depends(get_start_limiter),
    settings: Settings = Depends(get_settings),
) -> StartResponse:
    key = client_key(request, settings)
    wait = limiter.retry_after_s(key, clock.now())
    if wait > 0:
        raise ApiError(429, "too_many_attempts", retry_after_s=wait)
    try:
        result = test_flow.start_session(db, clock, body.token, seb_verified)
    except ApiError as exc:
        if exc.code == "invalid_invitation":
            limiter.record_failure(key, clock.now())
        raise
    return StartResponse(
        session_id=result.session.id,
        access_token=result.access_token,
        status=result.session.status,
    )


@router.post("/{session_id}/begin", response_model=BeginResponse)
def begin(
    body: BeginRequest,
    session: TestSession = Depends(current_session),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> BeginResponse:
    test_flow.begin(db, clock, session, body.accepted)
    remaining = (session.ends_at - clock.now()).total_seconds()
    return BeginResponse(status=session.status, remaining_s=max(0.0, round(remaining, 1)))


@router.get("/{session_id}/question", response_model=QuestionResponse)
def question(
    session: TestSession = Depends(current_session),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> QuestionResponse:
    view = test_flow.get_question(db, clock, session)
    return QuestionResponse(
        position=view.position,
        total=view.total,
        section=view.section,
        text=view.text,
        options=[OptionView(id=oid, text=text) for oid, text in view.options],
        remaining_s=view.remaining_s,
    )


@router.post("/{session_id}/answer", response_model=ResolveResponse)
def answer(
    body: AnswerRequest,
    session: TestSession = Depends(current_session),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
    seb_verified: bool = Depends(require_seb),
) -> ResolveResponse:
    done, remaining = test_flow.answer(
        db, clock, session, body.position, body.option_id, seb_verified
    )
    return ResolveResponse(done=done, remaining_s=remaining)


@router.post("/{session_id}/skip", response_model=ResolveResponse)
def skip(
    body: SkipRequest,
    session: TestSession = Depends(current_session),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
    seb_verified: bool = Depends(require_seb),
) -> ResolveResponse:
    done, remaining = test_flow.skip(db, clock, session, body.position, seb_verified)
    return ResolveResponse(done=done, remaining_s=remaining)


@router.post("/{session_id}/finish", response_model=FinishResponse)
def finish(
    session: TestSession = Depends(current_session),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> FinishResponse:
    summary = test_flow.finish(db, clock, session)
    return FinishResponse(status=session.status, **asdict(summary))


@router.post("/{session_id}/self-report", status_code=204)
def self_report(
    body: SelfReportRequest,
    session: TestSession = Depends(current_session),
    db: Session = Depends(get_db),
) -> None:
    test_flow.save_self_report(db, session, body.had_technical_issues, body.note)
