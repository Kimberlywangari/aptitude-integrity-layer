from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_clock, session_from_any_token, session_from_token
from app.clock import Clock
from app.db import get_db
from app.models import TestSession
from app.schemas.recording import EventsRequest, EventsResponse, HeartbeatResponse
from app.services import events as event_service
from app.services import heartbeat as heartbeat_service

router = APIRouter(tags=["events"])


@router.post("/events", response_model=EventsResponse)
def post_events(
    body: EventsRequest,
    session: TestSession = Depends(session_from_any_token),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> EventsResponse:
    result = event_service.ingest(db, clock, session, body.events)
    return EventsResponse(
        accepted=result.accepted,
        duplicates=result.duplicates,
        rejected=result.rejected,
        warn=result.warn,
    )


@router.post("/heartbeat", response_model=HeartbeatResponse)
def post_heartbeat(
    session: TestSession = Depends(session_from_token),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> HeartbeatResponse:
    tick = heartbeat_service.record(db, clock, session)
    return HeartbeatResponse(
        server_time=tick.server_time, remaining_s=tick.remaining_s, status=tick.status
    )
