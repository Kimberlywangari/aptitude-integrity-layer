from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

# A summary of a few thousand questions is well under this; it only stops an absurd upload.
MAX_CSV_CHARS = 5_000_000


# cytonn: Cytonn's own questions. practice: the made-up bank. bank: any stored question (what
# every sitting was before there were modes). ai: written for each candidate.
QuestionMode = Literal["bank", "practice", "cytonn", "ai"]


class SittingCountsOut(BaseModel):
    finished: int
    in_progress: int
    not_started: int
    papers_pending: int = 0  # AI sittings: questions still being written for a candidate
    papers_failed: int = 0  # ... and those that could not be written


class SittingOut(BaseModel):
    id: int
    name: str
    opens_at: datetime | None
    closes_at: datetime | None
    duration_s: int
    question_count: int
    blueprint: dict[str, int] | None
    question_mode: QuestionMode
    status: Literal["open", "closed"]
    counts: SittingCountsOut


class SittingsResponse(BaseModel):
    sittings: list[SittingOut]


class CreateSittingRequest(BaseModel):
    # The real limits live in the service, so the screens get a code they can word.
    name: str = Field(max_length=1000)
    opens_at: datetime | None = None
    closes_at: datetime | None = None
    # Either a total spread evenly over the sections, or how many each section contributes.
    question_count: int | None = None
    per_section: dict[str, int] | None = Field(default=None, max_length=50)
    # where the questions come from; per_section counts questions of each section (or, for `ai`,
    # of each category)
    question_mode: QuestionMode = "bank"


class RetryPapersResponse(BaseModel):
    restarted: int


class SittingCandidateOut(BaseModel):
    candidate_id: str
    state: Literal["not_opened", "opened", "started", "finished"]
    answered: int
    # None until the candidate has opened their link. An AI sitting's paper is written after that.
    paper_status: Literal["pending", "ready", "failed"] | None = None
    paper_error: str | None = None
    waited_s: int | None = None
    opened_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    name: str | None = None
    email: str | None = None  # masked
    invite_mail: Literal["queued", "sent", "failed"] | None = None
    result_mail: Literal["passed", "not_passed"] | None = None
    result_mail_status: Literal["queued", "sent", "failed"] | None = None


class SittingDetailResponse(BaseModel):
    sitting: SittingOut
    candidates: list[SittingCandidateOut]


class DeleteSittingRequest(BaseModel):
    confirm_name: str = Field(max_length=200)  # the sitting's name, typed out


class DeleteSittingResponse(BaseModel):
    sessions: int
    candidates: int
    questions: int


class AiCategoryOut(BaseModel):
    key: str
    label: str
    brief: str


class AiStatusResponse(BaseModel):
    provider: Literal["ollama", "claude"]
    model: str
    available: bool
    detail: str  # a sentence a person can act on
    max_per_category: int
    max_total: int
    categories: list[AiCategoryOut]


class SampleRequest(BaseModel):
    category: str = Field(max_length=40)
    difficulty: Literal["easy", "medium", "hard"] = "medium"


class SampleResponse(BaseModel):
    category: str
    difficulty: str
    text: str
    options: list[str]
    correct_index: int
    explanation: str
    written_by: str
    seconds: float
    rounds: int
    rejected: list[str]


class CloseSittingRequest(BaseModel):
    force: bool = False


class CloseSittingResponse(BaseModel):
    status: Literal["closed"]
    forced: bool


class InvitesRequest(BaseModel):
    # Either how many anonymous codes to make (scripts and practice), or the pasted list of people,
    # one `name, email` per line: then one candidate is made for each, with their email attached.
    count: int | None = None
    list_text: str | None = Field(default=None, max_length=200_000)
    # The sitting these invitations are for. Optional only while exactly one sitting is open.
    sitting_id: int | None = None


class InviteOut(BaseModel):
    candidate_id: str
    code: str  # shown once; only its hash is stored
    name: str | None = None
    email: str | None = None  # in full: the admin typed it, and needs it beside the code


class PersonOut(BaseModel):
    line: int
    name: str
    email: str


class ListProblemOut(BaseModel):
    line: int
    reason: Literal["bad_email", "name_missing", "name_too_long", "repeated", "already_invited"]
    text: str


class PreviewListRequest(BaseModel):
    list_text: str = Field(max_length=200_000)
    sitting_id: int | None = None


class PreviewListResponse(BaseModel):
    people: list[PersonOut]
    problems: list[ListProblemOut]
    sitting_id: int
    sitting_name: str


class InvitesResponse(BaseModel):
    invites: list[InviteOut]
    # the sitting these codes open: every one of them starts that sitting's paper
    sitting_id: int
    sitting_name: str


class InviteStatusOut(BaseModel):
    candidate_id: str
    status: Literal["not_opened", "opened", "started", "finished"]
    # None for a code made before invitations belonged to a sitting: it opens the newest one
    sitting_id: int | None = None
    sitting_name: str | None = None
    name: str | None = None
    email: str | None = None  # masked
    invite_mail: Literal["queued", "sent", "failed"] | None = None


class InviteListResponse(BaseModel):
    invites: list[InviteStatusOut]
    total: int  # all candidates; `invites` holds the newest ones


class QuestionRowOut(BaseModel):
    id: str
    section: str
    difficulty: Literal["easy", "medium", "hard"] | None
    source: Literal["cytonn", "synthetic"]
    preview: str
    pct_correct: float | None
    n: int | None


class QuestionListResponse(BaseModel):
    questions: list[QuestionRowOut]
    total: int


class SectionSummaryOut(BaseModel):
    section: str
    count: int
    cytonn: int
    synthetic: int


class BankSummaryOut(BaseModel):
    total: int
    cytonn: int
    synthetic: int
    by_section: list[SectionSummaryOut]


class ImportRequest(BaseModel):
    filename: str = Field(default="summary.csv", max_length=200)
    summary_csv: str = Field(max_length=MAX_CSV_CHARS)
    bank_csv: str | None = Field(default=None, max_length=MAX_CSV_CHARS)


class RejectedRowOut(BaseModel):
    row: int
    question_id: str | None
    reason: str


class ImportReportOut(BaseModel):
    filename: str
    rows: int
    imported: int
    rejected: list[RejectedRowOut]
    warnings: list[str]
    difficulty_derived: int


class RetireResponse(BaseModel):
    removed: int
    kept: int


class MailStatusResponse(BaseModel):
    set_up: bool  # false: SMTP_HOST or MAIL_FROM is empty, so emails wait in the outbox
    from_address: str | None  # masked
    queued: int
    sent: int
    failed: int


class TestMailRequest(BaseModel):
    to: str = Field(max_length=254)


class EmailTextOut(BaseModel):
    subject: str
    body: str


class ResultsPlanResponse(BaseModel):
    sitting_closed: bool
    passed: int  # would get the "passed" email now
    not_passed: int  # would get the "not passed" email (needs the sitting closed)
    held_back: list[str]  # candidate ids still under review; a person must decide first
    sent_passed: int
    sent_not_passed: int
    did_not_finish: int
    without_email: int
    preview_passed: EmailTextOut
    preview_not_passed: EmailTextOut


class SendResultsRequest(BaseModel):
    kind: Literal["passed", "not_passed"]


class SendResultsResponse(BaseModel):
    queued: int
