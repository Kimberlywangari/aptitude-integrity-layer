from fastapi import APIRouter, Depends, Header, Request, Response
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.deps import (
    client_key,
    current_staff,
    get_clock,
    get_login_limiter,
    get_video_store,
    require_reviewer,
)
from app.clock import Clock
from app.config import Settings, get_settings
from app.core.staff_token import issue_staff_token
from app.core.video_url import read_video_token
from app.db import get_db
from app.errors import ApiError
from app.models import Reviewer, Sitting, TestSession, VideoSegment
from app.schemas.review import (
    ActionLog,
    AuditResponse,
    BulkPassRequest,
    BulkPassResponse,
    CandidateDetail,
    CandidatesResponse,
    DecisionRequest,
    DecisionResponse,
    LoginRequest,
    LoginResponse,
    MeResponse,
    OutcomesResponse,
    OverviewResponse,
    QueueResponse,
    ResendRequest,
    ResultRequest,
    ResultResponse,
    ShortlistResponse,
    VideoViewRequest,
)
from app.services import mail, outcomes, staff_auth
from app.services import overview as overview_service
from app.services import review as review_service
from app.services.rate_limit import AttemptLimiter
from app.services.video import ffmpeg
from app.services.video.assemble import ensure_assembled
from app.services.video.store import VideoStore

router = APIRouter(prefix="/review", tags=["review"])


@router.post("/login", response_model=LoginResponse)
def login(
    body: LoginRequest,
    request: Request,
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
    settings: Settings = Depends(get_settings),
    limiter: AttemptLimiter = Depends(get_login_limiter),
) -> LoginResponse:
    email = staff_auth.normalise_email(body.email)
    # Counted twice: per address (one machine guessing) and per email (many machines, one account).
    keys = (f"ip:{client_key(request, settings)}", f"email:{email}")
    now = clock.now()
    wait = max(limiter.retry_after_s(key, now) for key in keys)
    if wait > 0:
        raise ApiError(429, "too_many_attempts", retry_after_s=wait)

    reviewer = staff_auth.authenticate(db, email, body.password)
    if reviewer is None:
        for key in keys:
            limiter.record_failure(key, now)
        raise ApiError(401, "invalid_credentials")

    staff_auth.record_login(db, clock, reviewer)
    db.commit()
    token = issue_staff_token(settings.session_secret, clock, reviewer.id, reviewer.password_hash)
    return LoginResponse(token=token, email=reviewer.email, role=reviewer.role)


@router.get("/me", response_model=MeResponse)
def me(staff: Reviewer = Depends(require_reviewer)) -> MeResponse:
    return MeResponse(email=staff.email, role=staff.role)


# ------------------------------------------------------------------------- the review screens
# Every route here needs a signed-in staff account. Candidate IDs only, never names.


@router.get("/queue", response_model=QueueResponse)
def get_queue(
    sitting: int | None = None,
    _: Reviewer = Depends(require_reviewer),
    db: Session = Depends(get_db),
) -> QueueResponse:
    return QueueResponse.model_validate(review_service.queue(db, sitting))


@router.get("/overview", response_model=OverviewResponse)
def get_overview(
    sitting: int | None = None,
    _: Reviewer = Depends(require_reviewer),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> OverviewResponse:
    return OverviewResponse.model_validate(overview_service.overview(db, sitting, settings))


@router.get("/candidates", response_model=CandidatesResponse)
def get_candidates(
    sitting: int | None = None,
    _: Reviewer = Depends(require_reviewer),
    db: Session = Depends(get_db),
) -> CandidatesResponse:
    return CandidatesResponse.model_validate(review_service.candidates_in_sitting(db, sitting))


@router.get("/candidates/{candidate_id}/events", response_model=ActionLog)
def get_action_log(
    candidate_id: str,
    sitting: int | None = None,
    _: Reviewer = Depends(require_reviewer),
    db: Session = Depends(get_db),
) -> ActionLog:
    return ActionLog.model_validate(review_service.action_log(db, candidate_id, sitting))


@router.get("/candidates/{candidate_id}", response_model=CandidateDetail)
def get_candidate(
    candidate_id: str,
    sitting: int | None = None,
    reviewer: Reviewer = Depends(require_reviewer),
    db: Session = Depends(get_db),
    store: VideoStore = Depends(get_video_store),
    clock: Clock = Depends(get_clock),
    settings: Settings = Depends(get_settings),
) -> CandidateDetail:
    video = review_service.VideoContext(store, clock, settings, reviewer.id)
    detail = review_service.candidate_detail(
        db, candidate_id, sitting, video=video, retention_days=settings.retention_days
    )
    return CandidateDetail.model_validate(detail)


@router.get("/candidates/{candidate_id}/video")
def get_video(
    candidate_id: str,
    segment: int = 0,
    t: str | None = None,
    sitting: int | None = None,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
    store: VideoStore = Depends(get_video_store),
    clock: Clock = Depends(get_clock),
    settings: Settings = Depends(get_settings),
) -> FileResponse:
    """One part of a candidate's recording, with range support so the player can scrub.

    A <video> element cannot send an Authorization header, so the candidate's page carries links
    signed for the reviewer (`t`); the staff token works too, for anything that can send it.
    """
    claims = read_video_token(settings.session_secret, clock, t) if t else None
    if t and claims is None:
        raise ApiError(401, "unauthorized")
    if claims is not None:
        reviewer = db.get(Reviewer, claims["r"])
        session = db.get(TestSession, claims["s"])
        if (
            reviewer is None
            or not reviewer.is_active
            or session is None
            or session.candidate_id != candidate_id
            or claims["g"] != segment
        ):
            raise ApiError(401, "unauthorized")
    else:
        reviewer = current_staff(authorization=authorization, db=db, clock=clock, settings=settings)
        session = review_service._find_session(db, candidate_id, sitting)

    if not review_service.can_view_video(db, session):
        raise ApiError(403, "video_not_available")
    if session.video_deleted_at is not None:
        raise ApiError(410, "video_deleted")

    row = db.get(VideoSegment, (session.id, segment))
    if row is None or row.path is None or not store.exists(row.path):
        try:
            ensure_assembled(db, store, clock, settings, session.id)
        except ffmpeg.FfmpegMissing as missing:
            raise ApiError(503, "ffmpeg_missing") from missing
        row = db.get(VideoSegment, (session.id, segment), populate_existing=True)
        if row is None or row.path is None:
            raise ApiError(404, "no_such_segment")

    review_service.note_video_playback(db, clock, reviewer.id, session, segment)
    return FileResponse(
        store.local_path(row.path),
        media_type="video/webm",
        headers={"Cache-Control": "private, no-store"},
    )


@router.post("/candidates/{candidate_id}/shortlist", response_model=ShortlistResponse)
def shortlist(
    candidate_id: str,
    sitting: int | None = None,
    reviewer: Reviewer = Depends(require_reviewer),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> ShortlistResponse:
    now_on = review_service.toggle_shortlist(db, clock, reviewer, candidate_id, sitting)
    emailed = outcomes.result_email_exists(db, candidate_id)
    db.commit()
    return ShortlistResponse(shortlisted=now_on, result_email_sent=emailed)


@router.post("/candidates/{candidate_id}/video-view", status_code=204)
def video_view(
    candidate_id: str,
    body: VideoViewRequest | None = None,
    sitting: int | None = None,
    reviewer: Reviewer = Depends(require_reviewer),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> Response:
    flag_id = body.flag_id if body else None
    review_service.record_video_view(db, clock, reviewer, candidate_id, flag_id, sitting)
    db.commit()
    return Response(status_code=204)


@router.post("/decisions", response_model=DecisionResponse)
def decide(
    body: DecisionRequest,
    reviewer: Reviewer = Depends(require_reviewer),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> DecisionResponse:
    decided_at = review_service.record_decision(
        db, clock, reviewer, body.session_id, body.outcome, body.reason
    )
    db.commit()
    return DecisionResponse(decided_at=decided_at)


# ------------------------------------------------------------ results and the outcomes list
# A reviewer or an admin records a result and the system sends the email. IDs only, never names.


@router.get("/outcomes", response_model=OutcomesResponse)
def get_outcomes(
    sitting: int | None = None,
    status: str | None = None,
    email: str | None = None,
    q: str | None = None,
    page: int = 1,
    _: Reviewer = Depends(require_reviewer),
    db: Session = Depends(get_db),
) -> OutcomesResponse:
    data = outcomes.view(db, sitting, status=status, email_state=email, search=q, page=page)
    return OutcomesResponse.model_validate(data)


@router.post("/candidates/{candidate_id}/result", response_model=ResultResponse)
def record_result(
    candidate_id: str,
    body: ResultRequest,
    sitting: int | None = None,
    reviewer: Reviewer = Depends(require_reviewer),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
    settings: Settings = Depends(get_settings),
) -> ResultResponse:
    status = outcomes.record_result(
        db, clock, settings, reviewer, candidate_id, sitting,
        body.result, body.reason_key, body.reason_text,
    )  # fmt: skip
    db.commit()
    mail.launch_sending(clock)
    return ResultResponse(status=status)


@router.post("/candidates/{candidate_id}/result/resend", status_code=204)
def resend_result(
    candidate_id: str,
    body: ResendRequest,
    sitting: int | None = None,
    reviewer: Reviewer = Depends(require_reviewer),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
    settings: Settings = Depends(get_settings),
) -> Response:
    outcomes.resend(db, clock, settings, reviewer, candidate_id, sitting, body.confirm)
    db.commit()
    mail.launch_sending(clock)
    return Response(status_code=204)


@router.post("/results/bulk-pass", response_model=BulkPassResponse)
def bulk_pass(
    body: BulkPassRequest,
    reviewer: Reviewer = Depends(require_reviewer),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
    settings: Settings = Depends(get_settings),
) -> BulkPassResponse:
    sitting = db.get(Sitting, body.sitting_id)
    if sitting is None:
        raise ApiError(404, "sitting_not_found")
    done = outcomes.bulk_pass(db, clock, settings, reviewer, sitting, body.candidate_ids)
    db.commit()
    mail.launch_sending(clock)
    return BulkPassResponse.model_validate(done)


@router.get("/audit", response_model=AuditResponse)
def audit(
    _: Reviewer = Depends(require_reviewer), db: Session = Depends(get_db)
) -> AuditResponse:
    return AuditResponse.model_validate({"entries": review_service.audit_entries(db)})
