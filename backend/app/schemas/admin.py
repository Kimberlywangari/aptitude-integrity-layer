from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

# A summary of a few thousand questions is well under this; it only stops an absurd upload.
MAX_CSV_CHARS = 5_000_000


class SittingCountsOut(BaseModel):
    finished: int
    in_progress: int
    not_started: int


class SittingOut(BaseModel):
    id: int
    name: str
    opens_at: datetime | None
    closes_at: datetime | None
    duration_s: int
    question_count: int
    status: Literal["open", "closed"]
    counts: SittingCountsOut


class SittingsResponse(BaseModel):
    sittings: list[SittingOut]


class CreateSittingRequest(BaseModel):
    # The real limits live in the service, so the screens get a code they can word.
    name: str = Field(max_length=1000)
    opens_at: datetime | None = None
    closes_at: datetime | None = None
    duration_s: int
    question_count: int


class CloseSittingRequest(BaseModel):
    force: bool = False


class CloseSittingResponse(BaseModel):
    status: Literal["closed"]
    forced: bool


class InvitesRequest(BaseModel):
    count: int


class InviteOut(BaseModel):
    candidate_id: str
    code: str  # shown once; only its hash is stored


class InvitesResponse(BaseModel):
    invites: list[InviteOut]


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
