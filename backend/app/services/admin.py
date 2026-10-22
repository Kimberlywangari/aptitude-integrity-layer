"""What the recruiter's setup screens do: sittings, invitation codes and the question bank.

Functions flush but never commit; the endpoint owns the transaction. Problems a person can fix
come back as ApiError with a code the screens switch on.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import Integer, case, cast, func, select
from sqlalchemy.orm import Session

from app.core.security import hash_token, new_invite_code
from app.errors import ApiError
from app.models import (
    Candidate,
    Question,
    QuestionStats,
    SessionQuestion,
    Sitting,
    TestSession,
)
from app.services.shuffle import most_asked_of_a_section

MAX_INVITES = 500
MIN_DURATION_S = 60
NAME_MAX = 100


@dataclass(frozen=True)
class SittingCounts:
    finished: int
    in_progress: int
    not_started: int


@dataclass(frozen=True)
class SittingView:
    sitting: Sitting
    counts: SittingCounts


@dataclass(frozen=True)
class SectionSummary:
    section: str
    count: int
    cytonn: int
    synthetic: int


@dataclass(frozen=True)
class BankSummary:
    total: int
    cytonn: int
    synthetic: int
    by_section: list[SectionSummary]


# ---------------------------------------------------------------------------------- sittings


def _counts_for(db: Session, sittings: list[Sitting]) -> dict[int, SittingCounts]:
    """Finished, in progress and not started, for each sitting, in two small queries.

    "Not started" is a session that was opened but whose timer never ran, plus, while a sitting is
    open, every invited candidate who has no session yet. A closed sitting counts only the first
    kind, so candidates invited later do not show up as "not started" in an old sitting.
    """
    if not sittings:
        return {}
    by_status: dict[tuple[int, str], int] = {}
    rows = db.execute(
        select(TestSession.sitting_id, TestSession.status, func.count())
        .where(TestSession.sitting_id.in_([s.id for s in sittings]))
        .group_by(TestSession.sitting_id, TestSession.status)
    )
    for sitting_id, status, n in rows:
        by_status[(sitting_id, status)] = n
    invited = db.scalar(select(func.count()).select_from(Candidate)) or 0

    result: dict[int, SittingCounts] = {}
    for sitting in sittings:
        finished = by_status.get((sitting.id, "finished"), 0)
        in_progress = by_status.get((sitting.id, "in_progress"), 0)
        created = by_status.get((sitting.id, "created"), 0)
        without_session = max(0, invited - finished - in_progress - created)
        not_started = created + (without_session if sitting.status == "open" else 0)
        result[sitting.id] = SittingCounts(finished, in_progress, not_started)
    return result


def view_of(db: Session, sitting: Sitting) -> SittingView:
    return SittingView(sitting, _counts_for(db, [sitting])[sitting.id])


def list_sittings(db: Session) -> list[SittingView]:
    sittings = list(db.scalars(select(Sitting).order_by(Sitting.id.desc())))
    counts = _counts_for(db, sittings)
    return [SittingView(s, counts[s.id]) for s in sittings]


def _aware(value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def create_sitting(
    db: Session,
    *,
    name: str,
    opens_at: datetime | None,
    closes_at: datetime | None,
    duration_s: int,
    question_count: int | None = None,
    per_section: dict[str, int] | None = None,
) -> Sitting:
    """A new sitting. Its paper is either `per_section` (how many questions each section
    contributes: the blueprint) or `question_count` spread evenly over the sections."""
    name = name.strip()
    if not name:
        raise ApiError(422, "name_required")
    if len(name) > NAME_MAX:
        raise ApiError(422, "name_too_long", max=NAME_MAX)
    if duration_s < MIN_DURATION_S:
        raise ApiError(422, "invalid_duration")
    opens_at, closes_at = _aware(opens_at), _aware(closes_at)
    if opens_at and closes_at and closes_at <= opens_at:
        raise ApiError(422, "invalid_window")

    in_bank = dict(
        db.execute(select(Question.section, func.count()).group_by(Question.section)).all()
    )
    blueprint: dict[str, int] | None = None
    if per_section is not None:
        if any(n < 0 for n in per_section.values()):
            raise ApiError(422, "invalid_question_count")
        blueprint = {section: n for section, n in per_section.items() if n > 0}
        if not blueprint:
            raise ApiError(422, "invalid_question_count")
        unknown = sorted(section for section in blueprint if section not in in_bank)
        if unknown:
            raise ApiError(422, "unknown_section", sections=unknown)
        question_count = sum(blueprint.values())
        short = [
            {"section": section, "available": in_bank[section], "needed": wanted}
            for section, wanted in sorted(blueprint.items())
            if in_bank[section] < wanted
        ]
        if short:
            raise ApiError(409, "section_too_small", sections=short)
    else:
        if question_count is None or question_count < 1:
            raise ApiError(422, "invalid_question_count")
        available = sum(in_bank.values())
        if question_count > available:
            raise ApiError(409, "question_bank_too_small", available=available)
        # a paper is spread over the sections, so a small one would fail a candidate's start later
        needed = most_asked_of_a_section(question_count, len(in_bank))
        short = [
            {"section": section, "available": count, "needed": needed}
            for section, count in sorted(in_bank.items())
            if count < needed
        ]
        if short:
            raise ApiError(409, "section_too_small", needed=needed, sections=short)
    if db.scalar(select(Sitting.id).where(Sitting.name == name)) is not None:
        raise ApiError(409, "name_taken")

    sitting = Sitting(
        name=name,
        opens_at=opens_at,
        closes_at=closes_at,
        duration_s=duration_s,
        question_count=question_count,
        blueprint=blueprint,
        status="open",
    )
    db.add(sitting)
    db.flush()
    return sitting


def close_sitting(db: Session, sitting_id: int, *, force: bool) -> tuple[Sitting, int]:
    """Close a sitting. Returns (sitting, unfinished it was closed with).

    Candidates still sitting or never started block the close unless `force` is set; the
    caller audits a forced close.
    """
    sitting = db.get(Sitting, sitting_id)
    if sitting is None:
        raise ApiError(404, "sitting_not_found")
    if sitting.status == "closed":
        raise ApiError(409, "already_closed")
    counts = _counts_for(db, [sitting])[sitting.id]
    unfinished = counts.in_progress + counts.not_started
    if unfinished > 0 and not force:
        raise ApiError(409, "sessions_unfinished", unfinished=unfinished)
    sitting.status = "closed"
    db.flush()
    return sitting, unfinished


def has_open_sitting(db: Session) -> bool:
    return db.scalar(select(Sitting.id).where(Sitting.status == "open").limit(1)) is not None


# ---------------------------------------------------------------------------------- invitations


def generate_invites(db: Session, count: int) -> list[tuple[str, str]]:
    """New candidates with their codes: [(candidate_id, code)]. Only each code's hash is stored,
    so this is the one time the code exists in the clear."""
    if not 1 <= count <= MAX_INVITES:
        raise ApiError(422, "invalid_count", min=1, max=MAX_INVITES)

    highest = db.scalar(
        select(func.max(cast(func.substr(Candidate.id, 6), Integer))).where(
            Candidate.id.op("~")(r"^cand-[0-9]+$")
        )
    )
    first = (highest or 0) + 1

    invites: list[tuple[str, str]] = []
    seen: set[str] = set()
    for number in range(first, first + count):
        code = new_invite_code()
        while code in seen:  # 40 bits: a repeat inside one batch is not going to happen
            code = new_invite_code()
        seen.add(code)
        candidate_id = f"cand-{number:03d}"
        db.add(Candidate(id=candidate_id, invite_token_hash=hash_token(code)))
        invites.append((candidate_id, code))
    db.flush()
    return invites


# Where a candidate is, read off their newest session: no session yet means the code has not been
# used, a created one means they opened the link but have not started the timer.
INVITE_STATUS = {"created": "opened", "in_progress": "started", "finished": "finished"}
INVITES_SHOWN = 500


def list_invites(db: Session, limit: int = INVITES_SHOWN) -> tuple[list[tuple[str, str]], int]:
    """The newest `limit` candidates with where each one is, and how many candidates there are.
    Codes are never here: only a hash is stored."""
    total = db.scalar(select(func.count()).select_from(Candidate)) or 0
    ids = list(
        db.scalars(
            select(Candidate.id)
            .order_by(func.length(Candidate.id).desc(), Candidate.id.desc())
            .limit(limit)
        )
    )
    newest: dict[str, str] = {}
    rows = db.execute(
        select(TestSession.candidate_id, TestSession.status)
        .where(TestSession.candidate_id.in_(ids))
        .order_by(TestSession.created_at)
    )
    for candidate_id, status in rows:
        newest[candidate_id] = status  # later sessions replace earlier ones
    return [(i, INVITE_STATUS.get(newest.get(i, ""), "not_opened")) for i in ids], total


def reissue_invite(db: Session, candidate_id: str) -> str:
    """A new code for one candidate, to resend a lost link. The old code stops working at once."""
    candidate = db.get(Candidate, candidate_id)
    if candidate is None:
        raise ApiError(404, "candidate_not_found")
    code = new_invite_code()
    candidate.invite_token_hash = hash_token(code)
    db.flush()
    return code


# ---------------------------------------------------------------------------------- the bank


def bank_summary(db: Session) -> BankSummary:
    rows = db.execute(
        select(Question.section, Question.source, func.count()).group_by(
            Question.section, Question.source
        )
    )
    sections: dict[str, list[int]] = {}  # section -> [count, cytonn, synthetic]
    for section, source, n in rows:
        entry = sections.setdefault(section, [0, 0, 0])
        entry[0] += n
        if source == "cytonn":
            entry[1] += n
        elif source == "synthetic":
            entry[2] += n
    by_section = [SectionSummary(name, *sections[name]) for name in sorted(sections)]
    return BankSummary(
        total=sum(s.count for s in by_section),
        cytonn=sum(s.cytonn for s in by_section),
        synthetic=sum(s.synthetic for s in by_section),
        by_section=by_section,
    )


QUESTIONS_PAGE = 100
QUESTIONS_PAGE_MAX = 500
PREVIEW_CHARS = 200


@dataclass(frozen=True)
class QuestionRow:
    id: str
    section: str
    difficulty: str | None
    source: str
    preview: str  # the start of the text: the table never needs the whole question
    # Cytonn's own figure, as a percentage; None until a past-sitting summary has been loaded. The
    # made-up estimates are never shown here (and are stored as fractions, not percentages).
    pct_correct: float | None
    n: int | None


def list_questions(
    db: Session, section: str | None, limit: int = QUESTIONS_PAGE, offset: int = 0
) -> tuple[list[QuestionRow], int]:
    """One page of the bank, and how many questions match. Only the columns the table shows are
    fetched, and only the start of each text."""
    limit = max(1, min(limit, QUESTIONS_PAGE_MAX))
    where = [Question.section == section] if section else []
    total = db.scalar(select(func.count()).select_from(Question).where(*where)) or 0
    rows = db.execute(
        select(
            Question.id,
            Question.section,
            Question.difficulty,
            Question.source,
            func.left(Question.text, PREVIEW_CHARS),
            case((QuestionStats.source == "cytonn", QuestionStats.pct_correct), else_=None),
            case((QuestionStats.source == "cytonn", QuestionStats.n), else_=None),
        )
        .outerjoin(QuestionStats, QuestionStats.question_id == Question.id)
        .where(*where)
        .order_by(Question.section, Question.id)
        .limit(limit)
        .offset(max(0, offset))
    ).all()
    return [QuestionRow(*row) for row in rows], total


def retire_synthetic(db: Session) -> tuple[int, int]:
    """Remove placeholder questions. Returns (removed, kept): a placeholder that an earlier
    session already drew is kept, because that session's paper still points at it."""
    drawn = select(SessionQuestion.question_id)

    kept = (
        db.scalar(
            select(func.count())
            .select_from(Question)
            .where(Question.source == "synthetic", Question.id.in_(drawn))
        )
        or 0
    )
    removable = db.scalars(
        select(Question).where(Question.source == "synthetic", Question.id.not_in(drawn))
    ).all()
    for question in removable:
        db.delete(question)  # its options and stats go with it
    db.flush()
    return len(removable), kept


def audit_detail_for_close(sitting: Sitting, unfinished: int) -> str:
    if unfinished:
        return f'closed sitting "{sitting.name}" (forced, {unfinished} unfinished)'
    return f'closed sitting "{sitting.name}"'
