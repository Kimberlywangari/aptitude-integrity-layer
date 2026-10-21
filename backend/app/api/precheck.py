from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_clock, session_from_token
from app.clock import Clock
from app.db import get_db
from app.models import TestSession
from app.schemas.recording import PrecheckRequest, PrecheckResponse
from app.services import precheck as precheck_service

router = APIRouter(prefix="/precheck", tags=["precheck"])


@router.post("/result", response_model=PrecheckResponse)
def result(
    body: PrecheckRequest,
    session: TestSession = Depends(session_from_token),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> PrecheckResponse:
    return PrecheckResponse(passed=precheck_service.record_result(db, clock, session, body))
