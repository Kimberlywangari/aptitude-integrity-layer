from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.api.deps import get_clock, session_from_any_token
from app.clock import Clock
from app.db import get_db
from app.models import TestSession
from app.schemas.recording import ComplaintRequest
from app.services import complaints as complaint_service

router = APIRouter(prefix="/complaints", tags=["complaints"])


@router.post("", status_code=204)
def file_complaint(
    body: ComplaintRequest,
    session: TestSession = Depends(session_from_any_token),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> Response:
    complaint_service.file_complaint(db, clock, session, body.category, body.text)
    return Response(status_code=204)
