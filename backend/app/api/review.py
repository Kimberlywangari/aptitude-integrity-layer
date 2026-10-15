from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from app.api.deps import client_key, get_clock, get_login_limiter, require_reviewer
from app.clock import Clock
from app.config import Settings, get_settings
from app.core.staff_token import issue_staff_token
from app.db import get_db
from app.errors import ApiError
from app.models import Reviewer
from app.schemas.review import (
    AuditResponse,
    CandidateDetail,
    DecisionRequest,
    DecisionResponse,
    LoginRequest,
    LoginResponse,
    MeResponse,
    QueueResponse,
    ShortlistResponse,
    VideoViewRequest,
)
from app.services import review as review_service
from app.services import staff_auth
from app.services.rate_limit import AttemptLimiter

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


@router.get("/candidates/{candidate_id}", response_model=CandidateDetail)
def get_candidate(
    candidate_id: str,
    sitting: int | None = None,
    _: Reviewer = Depends(require_reviewer),
    db: Session = Depends(get_db),
) -> CandidateDetail:
    detail = review_service.candidate_detail(db, candidate_id, sitting)
    return CandidateDetail.model_validate(detail)


@router.post("/candidates/{candidate_id}/shortlist", response_model=ShortlistResponse)
def shortlist(
    candidate_id: str,
    sitting: int | None = None,
    reviewer: Reviewer = Depends(require_reviewer),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> ShortlistResponse:
    now_on = review_service.toggle_shortlist(db, clock, reviewer, candidate_id, sitting)
    db.commit()
    return ShortlistResponse(shortlisted=now_on)


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


@router.get("/audit", response_model=AuditResponse)
def audit(
    _: Reviewer = Depends(require_reviewer), db: Session = Depends(get_db)
) -> AuditResponse:
    return AuditResponse.model_validate({"entries": review_service.audit_entries(db)})
