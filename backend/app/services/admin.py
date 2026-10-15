"""What the recruiter's setup screens do: sittings, invitation codes and the question bank.

Functions flush but never commit; the endpoint owns the transaction. Problems a person can fix
come back as ApiError with a code the screens switch on.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import Integer, cast, func, select
from sqlalchemy.orm import Session

from app.core.security import hash_token, new_invite_code
from app.errors import ApiError
from app.models import Candidate, Question, QuestionStats, SessionQuestion, Sitting, TestSession

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
    question_count: int,
) -> Sitting:
    name = name.strip()
    if not name:
        raise ApiError(422, "name_required")
    if len(name) > NAME_MAX:
        raise ApiError(422, "name_too_long", max=NAME_MAX)
    if duration_s < MIN_DURATION_S:
        raise ApiError(422, "invalid_duration")
    if question_count < 1:
        raise ApiError(422, "invalid_question_count")
    opens_at, closes_at = _aware(opens_at), _aware(closes_at)
    if opens_at and closes_at and closes_at <= opens_at:
        raise ApiError(422, "invalid_window")

    available = db.scalar(select(func.count()).select_from(Question)) or 0
    if question_count > available:
        raise ApiError(409, "question_bank_too_small", available=available)
    if db.scalar(select(Sitting.id).where(Sitting.name == name)) is not None:
        raise ApiError(409, "name_taken")

    sitting = Sitting(
        name=name,
        opens_at=opens_at,
        closes_at=closes_at,
        duration_s=duration_s,
        question_count=question_count,
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


# ---------------------------------------------------------------------------------- the bank


def bank_summary(db: Session) -> BankSummary:
    rows = db.execute(
        select(Question.section, QuestionStats.source, func.count())
        .outerjoin(QuestionStats, QuestionStats.question_id == Question.id)
        .group_by(Question.section, QuestionStats.source)
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


def retire_synthetic(db: Session) -> tuple[int, int]:
    """Remove placeholder questions. Returns (removed, kept): a placeholder that an earlier
    session already drew is kept, because that session's paper still points at it."""
    placeholders = select(QuestionStats.question_id).where(QuestionStats.source == "synthetic")
    drawn = select(SessionQuestion.question_id)

    kept = (
        db.scalar(
            select(func.count())
            .select_from(Question)
            .where(Question.id.in_(placeholders), Question.id.in_(drawn))
        )
        or 0
    )
    removable = db.scalars(
        select(Question).where(Question.id.in_(placeholders), Question.id.not_in(drawn))
    ).all()
    for question in removable:
        db.delete(question)  # its options and stats go with it
    db.flush()
    return len(removable), kept


def audit_detail_for_close(sitting: Sitting, unfinished: int) -> str:
    if unfinished:
        return f'closed sitting "{sitting.name}" (forced, {unfinished} unfinished)'
    return f'closed sitting "{sitting.name}"'
