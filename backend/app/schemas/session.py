from pydantic import BaseModel, Field


class SignIn(BaseModel):
    """What the start and resume pages send. What each combination means is in services/login.py:
    code and email for the first sign-in (with `new_password` to choose a password), email and
    password after that, and the code alone for a candidate made without an email."""

    token: str | None = Field(default=None, max_length=200)  # the invitation code
    email: str | None = Field(default=None, max_length=254)
    password: str | None = Field(default=None, max_length=200)
    new_password: str | None = Field(default=None, max_length=200)


class StartRequest(SignIn):
    pass


class StartResponse(BaseModel):
    session_id: str
    access_token: str
    status: str  # created | in_progress | finished: where the client should route


class PaperResponse(BaseModel):
    """How far the candidate's questions have got. Always `ready` for a bank sitting."""

    status: str  # pending | ready | failed
    written: int
    total: int
    # seconds waited so far while pending, and whether the candidate may ask again (after a
    # failure, or after waiting longer than the limit)
    waited_s: int | None = None
    can_retry: bool = False
    # The candidate's own name, so the page can say whose test this is. Read only with their own
    # session's token; it goes nowhere else (not to reviewers, packets or the AI).
    candidate_name: str | None = None


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
    question_remaining_s: float  # at 0 the server closes the question and the next one opens
    # Addresses of the pictures the text's [[image N]] markers stand for (N counts from 1). Empty
    # unless the question depends on a picture.
    images: list[str] = []


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
