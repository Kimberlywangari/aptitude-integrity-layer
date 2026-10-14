from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.deps import client_key, get_clock, get_login_limiter, require_reviewer
from app.clock import Clock
from app.config import Settings, get_settings
from app.core.staff_token import issue_staff_token
from app.db import get_db
from app.errors import ApiError
from app.models import Reviewer
from app.schemas.review import LoginRequest, LoginResponse, MeResponse
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
