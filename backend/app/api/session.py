from dataclasses import asdict

from fastapi import APIRouter, Depends, Header, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session, undefer

from app.api.deps import client_key, get_clock, get_start_limiter
from app.clock import Clock
from app.config import Settings, get_settings
from app.core.image_url import issue_image_token, read_image_token
from app.core.security import tokens_match
from app.db import get_db
from app.errors import ApiError
from app.models import Candidate, QuestionImage, SessionQuestion, TestSession
from app.schemas.recording import FinishRequest, ResumeRequest, ResumeResponse
from app.schemas.session import (
    AnswerRequest,
    BeginRequest,
    BeginResponse,
    FinishResponse,
    OptionView,
    PaperResponse,
    QuestionResponse,
    ResolveResponse,
    SelfReportRequest,
    SkipRequest,
    StartRequest,
    StartResponse,
)
from app.services import resume as resume_service
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


def _name_of(db: Session, session: TestSession) -> str | None:
    """The candidate's own name, for their own page only."""
    return db.scalar(select(Candidate.full_name).where(Candidate.id == session.candidate_id))


@router.post("/start", response_model=StartResponse)
def start(
    body: StartRequest,
    request: Request,
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
    limiter: AttemptLimiter = Depends(get_start_limiter),
    settings: Settings = Depends(get_settings),
) -> StartResponse:
    key = client_key(request, settings)
    wait = limiter.retry_after_s(key, clock.now())
    if wait > 0:
        raise ApiError(429, "too_many_attempts", retry_after_s=wait)
    try:
        result = test_flow.start_session(
            db, clock, body.token, body.email, body.password, body.new_password
        )
    except ApiError as exc:
        if exc.code == "invalid_invitation":
            limiter.record_failure(key, clock.now())
        raise
    return StartResponse(
        session_id=result.session.id,
        access_token=result.access_token,
        status=result.session.status,
    )


@router.post("/resume", response_model=ResumeResponse)
def resume(
    body: ResumeRequest,
    request: Request,
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
    limiter: AttemptLimiter = Depends(get_start_limiter),
    settings: Settings = Depends(get_settings),
) -> ResumeResponse:
    """Finish uploading after the test: an invitation code in, an upload-only token out, for up to
    48 hours after finishing. Wrong codes count against the same limit as the start page."""
    key = client_key(request, settings)
    wait = limiter.retry_after_s(key, clock.now())
    if wait > 0:
        raise ApiError(429, "too_many_attempts", retry_after_s=wait)
    try:
        result = resume_service.issue_upload_token(
            db,
            clock,
            body.token,
            settings.resume_window_s,
            body.email,
            body.password,
            body.new_password,
        )
    except ApiError as exc:
        if exc.code == "invalid_invitation":
            limiter.record_failure(key, clock.now())
        raise
    return ResumeResponse(
        session_id=result.session.id,
        access_token=result.upload_token,
        status="finished",
        expires_at=result.expires_at,
    )


@router.get("/{session_id}/paper", response_model=PaperResponse)
def paper(
    session: TestSession = Depends(current_session),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
    settings: Settings = Depends(get_settings),
) -> PaperResponse:
    view = test_flow.paper_view(db, clock, session, settings.question_wait_limit_s)
    return PaperResponse(**asdict(view), candidate_name=_name_of(db, session))


@router.post("/{session_id}/paper/retry", response_model=PaperResponse)
def retry_paper(
    session: TestSession = Depends(current_session),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
    settings: Settings = Depends(get_settings),
) -> PaperResponse:
    view = test_flow.retry_paper(db, clock, session, settings.question_wait_limit_s)
    return PaperResponse(**asdict(view), candidate_name=_name_of(db, session))


@router.post("/{session_id}/begin", response_model=BeginResponse)
def begin(
    body: BeginRequest,
    session: TestSession = Depends(current_session),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
    settings: Settings = Depends(get_settings),
) -> BeginResponse:
    test_flow.begin(db, clock, session, body.accepted, settings.precheck_gate)
    remaining = (session.ends_at - clock.now()).total_seconds()
    return BeginResponse(status=session.status, remaining_s=max(0.0, round(remaining, 1)))


@router.get("/{session_id}/question", response_model=QuestionResponse)
def question(
    session: TestSession = Depends(current_session),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
    settings: Settings = Depends(get_settings),
) -> QuestionResponse:
    view = test_flow.get_question(db, clock, session)
    return QuestionResponse(
        position=view.position,
        total=view.total,
        section=view.section,
        text=view.text,
        options=[OptionView(id=oid, text=text) for oid, text in view.options],
        remaining_s=view.remaining_s,
        question_remaining_s=view.question_remaining_s,
        images=[
            f"/api/session/{session.id}/image/{image_id}"
            f"?t={issue_image_token(settings.session_secret, clock, session.id, image_id)}"
            for image_id in view.images
        ],
    )


@router.get("/{session_id}/image/{image_id}")
def question_image(
    session_id: str,
    image_id: int,
    t: str = "",
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
    settings: Settings = Depends(get_settings),
) -> Response:
    """A picture of the question being shown. The browser's <img> cannot send the bearer token, so
    the link carries a signed token for this session and this picture, and the picture must belong
    to a question on the session's own paper."""
    claims = read_image_token(settings.session_secret, clock, t)
    if claims is None or claims["s"] != session_id or claims["i"] != image_id:
        raise ApiError(403, "invalid_image_link")
    image = db.scalar(
        select(QuestionImage)
        .where(QuestionImage.id == image_id)
        .options(undefer(QuestionImage.data))
    )
    on_paper = image is not None and db.scalar(
        select(SessionQuestion.position).where(
            SessionQuestion.session_id == session_id,
            SessionQuestion.question_id == image.question_id,
        )
    )
    if image is None or not on_paper:
        raise ApiError(404, "image_not_found")
    return Response(
        content=image.data,
        media_type=image.content_type,
        headers={
            "Cache-Control": "private, max-age=21600",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post("/{session_id}/answer", response_model=ResolveResponse)
def answer(
    body: AnswerRequest,
    session: TestSession = Depends(current_session),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> ResolveResponse:
    done, remaining = test_flow.answer(db, clock, session, body.position, body.option_id)
    return ResolveResponse(done=done, remaining_s=remaining)


@router.post("/{session_id}/skip", response_model=ResolveResponse)
def skip(
    body: SkipRequest,
    session: TestSession = Depends(current_session),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> ResolveResponse:
    done, remaining = test_flow.skip(db, clock, session, body.position)
    return ResolveResponse(done=done, remaining_s=remaining)


@router.post("/{session_id}/finish", response_model=FinishResponse)
def finish(
    body: FinishRequest | None = None,
    session: TestSession = Depends(current_session),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> FinishResponse:
    summary = test_flow.finish(db, clock, session, body.chunks_total if body else None)
    return FinishResponse(status=session.status, **asdict(summary))


@router.post("/{session_id}/self-report", status_code=204)
def self_report(
    body: SelfReportRequest,
    session: TestSession = Depends(current_session),
    db: Session = Depends(get_db),
) -> None:
    test_flow.save_self_report(db, session, body.had_technical_issues, body.note)
