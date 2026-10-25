"""Request and response bodies for what the candidate's page sends while the test runs and after:
the action log, the heartbeat, the pre-check result, video chunks, complaints and resume.
Field names match frontend/src/lib/api.ts."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.session import SignIn

MAX_AGE_MS = 48 * 3600 * 1000  # an event can wait offline for the whole resume window
MAX_EVENTS_PER_BATCH = 100
MAX_COMPLAINT_CHARS = 1000


# ------------------------------------------------------------------------------------- events


class EventIn(BaseModel):
    client_seq: int = Field(ge=0, le=2_000_000_000)
    type: str = Field(max_length=40)
    # How long ago the page saw it. The server works out when it really happened from its own
    # clock, so an event queued while offline keeps its true moment.
    age_ms: int = Field(default=0, ge=0, le=MAX_AGE_MS)
    # Cleaned per event type on the way in; anything the type does not define is dropped.
    payload: dict | None = None


class EventsRequest(BaseModel):
    events: list[EventIn] = Field(min_length=1, max_length=MAX_EVENTS_PER_BATCH)


class EventsResponse(BaseModel):
    accepted: int
    duplicates: int  # sent before: a retry after a lost reply is not an error
    rejected: int  # a type the server does not know; sending it again will not help


class HeartbeatResponse(BaseModel):
    server_time: datetime
    remaining_s: float  # 0 unless the test is running; lets the page re-sync its countdown
    status: Literal["created", "in_progress", "finished"]


# ---------------------------------------------------------------------------------- pre-check


class BrowserInfo(BaseModel):
    name: str = Field(default="", max_length=64)
    version: str = Field(default="", max_length=32)


class DeviceLabels(BaseModel):
    camera: str = Field(default="", max_length=200)
    mic: str = Field(default="", max_length=200)


class VideoSize(BaseModel):
    width: int = Field(default=0, ge=0, le=20000)
    height: int = Field(default=0, ge=0, le=20000)


class PrecheckRequest(BaseModel):
    camera_ok: bool
    mic_ok: bool
    notifications_off_confirmed: bool = False
    fullscreen_ok: bool = False
    # False when the microphone step was left out for testing: `mic_ok` then means "not checked",
    # never "failed", so a reviewer can tell the two apart.
    mic_checked: bool = True
    browser: BrowserInfo = BrowserInfo()
    device_labels: DeviceLabels = DeviceLabels()
    mic_peak: float = Field(default=0.0, ge=0.0, le=10.0)
    video_size: VideoSize = VideoSize()


class PrecheckResponse(BaseModel):
    passed: bool


# ------------------------------------------------------------------------------------- chunks


class ChunkResponse(BaseModel):
    status: Literal["stored", "duplicate"]


class ManifestResponse(BaseModel):
    """Counts only: a chunk every 10 s makes the list of sequence numbers long for no gain."""

    expected: int | None  # None until the test has finished and the page has said how many
    received: int
    missing: int
    bytes: int
    complete: bool


# ---------------------------------------------------------------------- complaints and resume


class ComplaintRequest(BaseModel):
    # Checked in the service, so a bad value answers 422 `invalid_complaint` like the fixtures do.
    # The generous limit here only stops an absurd body from being read.
    category: str = Field(max_length=40)
    text: str = Field(max_length=MAX_COMPLAINT_CHARS * 4)


class FinishRequest(BaseModel):
    chunks_total: int | None = Field(default=None, ge=0, le=100_000)


class ResumeRequest(SignIn):
    """The same credentials as the start page."""


class ResumeResponse(BaseModel):
    session_id: str
    access_token: str  # upload-only: chunks, events and complaints, nothing else
    status: Literal["finished"]
    expires_at: datetime
