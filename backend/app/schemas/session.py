from pydantic import BaseModel, Field


class StartRequest(BaseModel):
    token: str = Field(min_length=1, max_length=200)


class StartResponse(BaseModel):
    session_id: str
    access_token: str
    status: str  # created | in_progress | finished: where the client should route


class BeginRequest(BaseModel):
    accepted: bool


class BeginResponse(BaseModel):
    status: str
    remaining_s: float


class OptionView(BaseModel):
    id: int
    text: str  # no correct-answer marker, ever


class QuestionResponse(BaseModel):
    position: int
    total: int
    section: str
    text: str
    options: list[OptionView]
    remaining_s: float


class AnswerRequest(BaseModel):
    position: int = Field(ge=1)
    option_id: int


class SkipRequest(BaseModel):
    position: int = Field(ge=1)


class ResolveResponse(BaseModel):
    done: bool  # true when that was the last question and the test has finished
    remaining_s: float


class FinishResponse(BaseModel):
    status: str
    total: int
    answered: int
    skipped: int
    unanswered: int


class SelfReportRequest(BaseModel):
    had_technical_issues: bool
    note: str | None = Field(default=None, max_length=300)
