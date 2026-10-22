from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

Role = Literal["reviewer", "admin"]
AiStatus = Literal["ok", "retried", "fallback", "not_run"]
Outcome = Literal["no_concern", "concern_noted", "refer_for_follow_up"]
MIN_REASON_CHARS = 20  # a decision needs a real reason (master plan D13)
MAX_REASON_CHARS = 2000


class LoginRequest(BaseModel):
    email: str = Field(min_length=1, max_length=254)
    password: str = Field(min_length=1, max_length=256)


class LoginResponse(BaseModel):
    token: str
    email: str
    role: Role


class MeResponse(BaseModel):
    email: str
    role: Role


# ---- the queue and the candidate page. Field names match frontend/src/lib/reviewTypes.ts.
# Candidate IDs only, never names.


class SittingRef(BaseModel):
    id: int
    name: str


class QueueItem(BaseModel):
    candidate_id: str
    rank: int
    rule_score: float
    ai_strength: int | None
    ai_status: AiStatus
    flag_kinds: list[str]
    decision: Outcome | None
    shortlisted: bool
    logging_only: bool


class QueueResponse(BaseModel):
    sittings: list[SittingRef]
    sitting_id: int
    items: list[QueueItem]


class VideoSeek(BaseModel):
    segment: int
    seek_s: float


class FlagItem(BaseModel):
    id: str
    kind: str
    server_ts: datetime
    elapsed_s: int
    question_number: int | None
    detail: dict[str, Any]
    video_seek: VideoSeek | None


class MicSilence(BaseModel):
    id: str
    start_s: int
    end_s: int
    duration_s: int
    layers: list[Literal["browser", "server"]]
    video_seek: VideoSeek | None


class BreakdownLine(BaseModel):
    label: str
    points: float


class SelfReport(BaseModel):
    had_technical_issues: bool
    note: str | None


class Explanation(BaseModel):
    source: Literal["ai", "rules"]
    status: AiStatus
    text: str
    strength: int | None
    flags_support_each_other: Literal["yes", "partly", "no"] | None


class ComplaintItem(BaseModel):
    id: str
    category: Literal["camera", "upload", "other"]
    text: str
    created_at: datetime
    status: Literal["open", "reviewed"]


class PastDecision(BaseModel):
    outcome: Outcome
    reason: str
    reviewer: str
    decided_at: datetime


class VideoSegment(BaseModel):
    segment: int
    url: str | None
    start_s: float
    duration_s: float


class CandidateDetail(BaseModel):
    session_id: str
    candidate_id: str
    rank: int
    rule_score: float
    rule_breakdown: list[BreakdownLine]
    score: int
    pace_s_per_q: float
    history_source: Literal["cytonn", "synthetic", "none"]
    flags: list[FlagItem]
    # only the keys that apply are present, as the page expects (cohort_skipped, or percentiles)
    vs_sitting: dict[str, Any]
    innocent_signals: list[dict[str, Any]]
    mic_silence: list[MicSilence]
    self_report: SelfReport | None
    explanation: Explanation
    complaints: list[ComplaintItem]
    decisions: list[PastDecision]
    shortlisted: bool
    segments: list[VideoSegment]
    video_deleted_at: datetime | None
    video_purge_on: datetime | None


class DecisionRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=32)
    outcome: str = Field(max_length=40)
    reason: str = Field(max_length=MAX_REASON_CHARS * 2)


class DecisionResponse(BaseModel):
    decided_at: datetime


class ShortlistResponse(BaseModel):
    shortlisted: bool


class VideoViewRequest(BaseModel):
    flag_id: str | None = Field(default=None, max_length=20)


class AuditEntry(BaseModel):
    id: str
    ts: datetime
    reviewer: str
    action: Literal["login", "decision", "video_view", "video_purged", "admin"]
    candidate_id: str | None
    detail: str


class AuditResponse(BaseModel):
    entries: list[AuditEntry]
