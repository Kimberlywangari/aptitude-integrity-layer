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


Band = Literal["high", "moderate", "low"]


class QueueItem(BaseModel):
    candidate_id: str
    rank: int
    rule_score: float
    ai_strength: int | None
    ai_status: AiStatus
    strength: int  # 1 to 5: the AI's when it answered, else the rules'
    band: Band  # a label for the queue; it orders attention and sets no one aside
    flag_count: int
    flag_kinds: list[str]
    decision: Outcome | None
    shortlisted: bool
    logging_only: bool


class QueueResponse(BaseModel):
    sittings: list[SittingRef]
    sitting_id: int
    items: list[QueueItem]


SessionStatus = Literal["created", "in_progress", "finished"]


class CandidateRow(BaseModel):
    """One line of the list of everyone in a sitting; `in_queue` says if the queue shows them."""

    candidate_id: str
    status: SessionStatus
    resolved: int  # questions answered or skipped so far
    total: int
    flag_count: int
    flag_kinds: list[str]
    in_queue: bool
    decision: Outcome | None
    shortlisted: bool


class CandidatesResponse(BaseModel):
    sittings: list[SittingRef]
    sitting_id: int
    items: list[CandidateRow]


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


EmailState = Literal["none", "queued", "sent", "failed"]
ResultKind = Literal["pass", "fail"]


class ReasonOption(BaseModel):
    key: str
    text: str


class ResultPanel(BaseModel):
    """Score, pass mark and what was decided, for the page's result panel. No name, no address."""

    score: int
    total: int
    pass_mark: int | None
    status: str
    result: ResultKind | None
    basis: Literal["score", "review"] | None
    reason: str | None
    decided_by: str | None  # a staff email, "pass-mark rule" or "removed account"
    decided_at: datetime | None
    email_state: EmailState
    can_record: bool
    blocked_by: str | None  # not_finished | already_emailed | no_email | review_first
    reasons: list[ReasonOption]


class CandidateDetail(BaseModel):
    session_id: str
    candidate_id: str
    rank: int
    strength: int
    band: Band
    rule_score: float
    rule_breakdown: list[BreakdownLine]
    score: int
    pace_s_per_q: float
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
    video_available: bool  # false: not flagged and not shortlisted, so the recording stays closed
    segments: list[VideoSegment]
    video_deleted_at: datetime | None
    video_purge_on: datetime | None
    result: ResultPanel


class LogEvent(BaseModel):
    type: str
    at_s: float | None  # seconds from the start of the test; negative before the timer ran
    question: int | None  # the question the candidate was on
    detail: dict[str, Any]


class LogQuestion(BaseModel):
    position: int
    section: str
    difficulty: str | None
    opened_s: float | None
    answered_s: float | None
    time_s: float | None
    result: Literal["correct", "wrong", "skipped", "unanswered"]
    # Set when an AI wrote this question for this candidate, such as "ollama:qwen2.5:7b"
    written_by: str | None = None
    # How long everyone else took, as context for the time above and never a flag by itself. The
    # same question when enough others answered it, else the same section, else empty.
    sitting_median_s: float | None = None
    median_of: Literal["question", "section"] | None = None
    median_n: int = 0  # how many answers the median is made of


class Timing(BaseModel):
    """The whole test's time against the sitting. Evidence for a person to weigh, nothing more."""

    total_s: float | None
    sitting_median_total_s: float | None  # None while fewer than `min_others` others finished
    others: int
    min_others: int
    # False in a sitting whose questions are written for each candidate: no two share a question
    same_questions: bool


class ActionLog(BaseModel):
    candidate_id: str
    status: SessionStatus
    started_at: datetime | None
    finished_at: datetime | None
    total_events: int
    truncated: bool  # more events were stored than are listed
    heartbeats: int
    events: list[LogEvent]
    questions: list[LogQuestion]
    timing: Timing


class DecisionRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=32)
    outcome: str = Field(max_length=40)
    reason: str = Field(max_length=MAX_REASON_CHARS * 2)


class DecisionResponse(BaseModel):
    decided_at: datetime


class ShortlistResponse(BaseModel):
    shortlisted: bool
    # true when a result email to this candidate is already queued or sent, so changing the
    # shortlist now will not change what they were told. Never an address, never a name.
    result_email_sent: bool = False


class OutcomeItem(BaseModel):
    candidate_id: str
    status: str
    score: int | None
    total: int | None
    flag_count: int
    email_state: EmailState
    has_email: bool  # whether there is an address to write to; never the address
    result_at: datetime | None
    can_mark_passed: bool


class OutcomesResponse(BaseModel):
    sittings: list[SittingRef]
    sitting_id: int
    pass_mark: int | None
    question_count: int
    sitting_closed: bool
    counts: dict[str, int]  # by status, over the whole sitting
    email_counts: dict[str, int]
    total: int
    matching: int
    page: int
    page_size: int
    items: list[OutcomeItem]


class ResultRequest(BaseModel):
    result: ResultKind
    # a failed candidate is told a reason: one of the fixed ones, or one line typed by the person
    reason_key: str | None = Field(default=None, max_length=20)
    reason_text: str | None = Field(default=None, max_length=1000)


class ResultResponse(BaseModel):
    status: str


class ResendRequest(BaseModel):
    confirm: bool = False


class BulkPassRequest(BaseModel):
    sitting_id: int
    candidate_ids: list[str] = Field(min_length=1, max_length=500)


class Refusal(BaseModel):
    candidate_id: str
    code: str


class BulkPassResponse(BaseModel):
    queued: int
    refused: list[Refusal]


class VideoViewRequest(BaseModel):
    flag_id: str | None = Field(default=None, max_length=20)


class OverviewTiles(BaseModel):
    sat: int  # started or finished
    finished: int
    flagged: int  # the review queue
    reviewed: int  # of those, how many have a written decision
    videos_uploaded: int
    videos_expected: int
    videos_decided_not_deleted: int  # decided, so on the clock for deletion


class FlagKindCount(BaseModel):
    kind: str
    count: int


class HealthCheck(BaseModel):
    key: str
    label: str
    state: Literal["ok", "warn", "off", "note"]
    detail: str


class NextUp(BaseModel):
    candidate_id: str
    band: Band
    flag_count: int
    first_kind: str


class OverviewResponse(BaseModel):
    sittings: list[SittingRef]
    sitting_id: int
    sitting_status: Literal["open", "closed"] | None
    tiles: OverviewTiles
    flags_by_kind: list[FlagKindCount]
    pending: int  # queue candidates still without a decision
    next_up: list[NextUp]
    checks: list[HealthCheck]


class AuditEntry(BaseModel):
    id: str
    ts: datetime
    reviewer: str
    action: Literal["login", "decision", "video_view", "video_purged", "admin"]
    candidate_id: str | None
    detail: str


class AuditResponse(BaseModel):
    entries: list[AuditEntry]
