"""What the recruiter's setup screens do: sittings, invitation codes and the question bank.

Functions flush but never commit; the endpoint owns the transaction. Problems a person can fix
come back as ApiError with a code the screens switch on.
"""

import random
import time
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import Integer, and_, case, cast, delete, exists, func, or_, select, update
from sqlalchemy.orm import Session

from app.clock import Clock
from app.config import Settings
from app.core.security import format_invite_code, hash_token, new_invite_code
from app.errors import ApiError
from app.models import (
    AuditLog,
    Candidate,
    Decision,
    EmailOutbox,
    Question,
    QuestionStats,
    SessionQuestion,
    Sitting,
    TestSession,
)
from app.services import candidate_list, mail, test_flow
from app.services.flags.engine import compute_sitting_flags
from app.services.qgen import jobs, pipeline
from app.services.qgen.categories import CATEGORIES, MAX_PER_CATEGORY, MAX_TOTAL
from app.services.qgen.writers import QuestionWriter, WriterError, get_writer
from app.services.question_modes import MODES, STORED_MODES, stored_questions
from app.services.shuffle import most_asked_of_a_section

MAX_INVITES = 500
NAME_MAX = 100


@dataclass(frozen=True)
class SittingCounts:
    finished: int
    in_progress: int
    not_started: int
    papers_pending: int = 0  # AI sittings: candidates whose questions are still being written
    papers_failed: int = 0  # ... and those whose questions could not be written


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
    open, every candidate invited to it who has no session yet. A closed sitting counts only the
    first kind, so candidates invited later do not show up as "not started" in an old sitting.

    An invitation made for a sitting counts for that sitting only. One made before sittings had
    their own opens the newest open sitting, so it is counted there and nowhere else.
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
    invited_to: dict[int, int] = dict(
        db.execute(
            select(Candidate.sitting_id, func.count())
            .where(Candidate.sitting_id.is_not(None))
            .group_by(Candidate.sitting_id)
        ).all()  # type: ignore[arg-type]
    )
    unassigned = (
        db.scalar(
            select(func.count()).select_from(Candidate).where(Candidate.sitting_id.is_(None))
        )
        or 0
    )
    newest_open = db.scalar(
        select(Sitting.id).where(Sitting.status == "open").order_by(Sitting.id.desc()).limit(1)
    )
    paper_states: dict[tuple[int, str], int] = {}
    for sitting_id, paper_status, n in db.execute(
        select(TestSession.sitting_id, TestSession.paper_status, func.count())
        .where(
            TestSession.sitting_id.in_([s.id for s in sittings]),
            TestSession.paper_status != "ready",
        )
        .group_by(TestSession.sitting_id, TestSession.paper_status)
    ):
        paper_states[(sitting_id, paper_status)] = n

    result: dict[int, SittingCounts] = {}
    for sitting in sittings:
        finished = by_status.get((sitting.id, "finished"), 0)
        in_progress = by_status.get((sitting.id, "in_progress"), 0)
        created = by_status.get((sitting.id, "created"), 0)
        invited = invited_to.get(sitting.id, 0) + (unassigned if sitting.id == newest_open else 0)
        without_session = max(0, invited - finished - in_progress - created)
        not_started = created + (without_session if sitting.status == "open" else 0)
        result[sitting.id] = SittingCounts(
            finished,
            in_progress,
            not_started,
            paper_states.get((sitting.id, "pending"), 0),
            paper_states.get((sitting.id, "failed"), 0),
        )
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
    question_count: int | None = None,
    per_section: dict[str, int] | None = None,
    question_mode: str = "bank",
) -> Sitting:
    """A new sitting. Its paper is either `per_section` (how many questions each section
    contributes: the blueprint) or `question_count` spread evenly over the sections.

    With `question_mode="ai"` the blueprint counts questions of each category (one of the
    seven in qgen/categories.py) to be written for each candidate, so the stored bank is not
    involved."""
    name = name.strip()
    if not name:
        raise ApiError(422, "name_required")
    if len(name) > NAME_MAX:
        raise ApiError(422, "name_too_long", max=NAME_MAX)
    opens_at, closes_at = _aware(opens_at), _aware(closes_at)
    if opens_at and closes_at and closes_at <= opens_at:
        raise ApiError(422, "invalid_window")

    if question_mode not in MODES:
        raise ApiError(422, "invalid_question_mode")
    in_bank: dict[str, int] = {}
    if question_mode in STORED_MODES:
        in_bank = dict(
            db.execute(
                select(Question.section, func.count())
                .where(stored_questions(question_mode))
                .group_by(Question.section)
            ).all()
        )
        if question_mode == "cytonn" and not in_bank:
            # nothing to draw from: say how to fix it, not "no such section"
            raise ApiError(409, "cytonn_not_loaded")
    blueprint: dict[str, int] | None = None
    if question_mode == "ai":
        if not per_section or any(n < 0 for n in per_section.values()):
            raise ApiError(422, "invalid_question_count")
        blueprint = {section: n for section, n in per_section.items() if n > 0}
        if not blueprint:
            raise ApiError(422, "invalid_question_count")
        unknown = sorted(section for section in blueprint if section not in CATEGORIES)
        if unknown:
            raise ApiError(422, "unknown_section", sections=unknown)
        if any(n > MAX_PER_CATEGORY for n in blueprint.values()):
            raise ApiError(422, "too_many_questions", max_per_category=MAX_PER_CATEGORY)
        question_count = sum(blueprint.values())
        if question_count > MAX_TOTAL:
            raise ApiError(422, "too_many_questions", max_total=MAX_TOTAL)
    elif per_section is not None:
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
        duration_s=question_count * test_flow.QUESTION_SECONDS,
        question_count=question_count,
        blueprint=blueprint,
        question_mode=question_mode,
        status="open",
    )
    db.add(sitting)
    db.flush()
    return sitting


def close_sitting(
    db: Session, sitting_id: int, *, force: bool, clock: Clock
) -> tuple[Sitting, int]:
    """Close a sitting and work out its flags, the group checks included. Returns
    (sitting, unfinished it was closed with).

    A session whose time has already run out is finished first, at the moment it ran out, so a
    candidate who simply closed the tab does not hold the sitting open. Candidates still sitting
    or never started block the close unless `force` is set; the caller audits a forced close.
    """
    sitting = db.get(Sitting, sitting_id)
    if sitting is None:
        raise ApiError(404, "sitting_not_found")
    if sitting.status == "closed":
        raise ApiError(409, "already_closed")
    test_flow.finish_expired(db, clock, sitting.id)
    counts = _counts_for(db, [sitting])[sitting.id]
    unfinished = counts.in_progress + counts.not_started
    if unfinished > 0 and not force:
        raise ApiError(409, "sessions_unfinished", unfinished=unfinished)
    sitting.status = "closed"
    db.flush()
    # The group checks only run on a closed sitting, so this is where they happen.
    compute_sitting_flags(db, sitting.id, clock=clock)
    return sitting, unfinished


def has_open_sitting(db: Session) -> bool:
    """Whether any sitting that draws on the stored bank is open. An AI sitting does not use
    the bank, so it never holds up a change to it."""
    return (
        db.scalar(
            select(Sitting.id)
            .where(Sitting.status == "open", Sitting.question_mode != "ai")
            .limit(1)
        )
        is not None
    )


# ------------------------------------------------------------------- one sitting, in detail


@dataclass(frozen=True)
class SittingCandidate:
    candidate_id: str
    state: str  # not_opened | opened | started | finished
    answered: int
    paper_status: str | None  # None until the candidate has opened their link
    paper_error: str | None
    waited_s: int | None  # a pending paper: seconds the candidate has waited for it
    opened_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None
    name: str | None = None  # admin-only
    email: str | None = None  # masked
    invite_mail: str | None = None  # queued | sent | failed
    result_mail: str | None = None  # passed | not_passed once queued
    result_mail_status: str | None = None


def sitting_candidates(db: Session, sitting: Sitting, clock: Clock) -> list[SittingCandidate]:
    """Everyone invited to a sitting, oldest code first, with where each one is: the code not
    used yet, the link opened, the timer running, or finished. Only the columns shown are read.

    A code made before invitations belonged to a sitting opens the newest open sitting, so it is
    listed there, as `_counts_for` counts it."""
    newest_open = db.scalar(
        select(Sitting.id).where(Sitting.status == "open").order_by(Sitting.id.desc()).limit(1)
    )
    belongs = or_(
        Candidate.sitting_id == sitting.id,
        TestSession.id.is_not(None),
        and_(Candidate.sitting_id.is_(None), newest_open == sitting.id),
    )
    rows = db.execute(
        select(
            Candidate.id,
            Candidate.full_name,
            Candidate.email,
            TestSession.id,
            TestSession.status,
            TestSession.paper_status,
            TestSession.paper_error,
            TestSession.paper_requested_at,
            TestSession.created_at,
            TestSession.started_at,
            TestSession.finished_at,
        )
        .select_from(Candidate)
        .outerjoin(
            TestSession,
            and_(TestSession.candidate_id == Candidate.id, TestSession.sitting_id == sitting.id),
        )
        .where(belongs)
        .order_by(func.length(Candidate.id), Candidate.id)
    ).all()

    answered: dict[str, int] = dict(
        db.execute(
            select(SessionQuestion.session_id, func.count())
            .join(TestSession, TestSession.id == SessionQuestion.session_id)
            .where(
                TestSession.sitting_id == sitting.id,
                or_(SessionQuestion.answered_at.is_not(None), SessionQuestion.skipped),
            )
            .group_by(SessionQuestion.session_id)
        ).all()  # type: ignore[arg-type]
    )
    now = clock.now()
    mails = mail_statuses(db, [r[0] for r in rows])
    found: list[SittingCandidate] = []
    for (
        cid, full_name, email, sid, status, paper_status, paper_error,
        requested, created, started, finished,
    ) in rows:
        sent = mails.get(cid, {})
        result_kind = next((k for k in ("passed", "not_passed") if k in sent), None)
        waited = None
        if paper_status == "pending":
            waited = max(0, int((now - (requested or created)).total_seconds()))
        found.append(
            SittingCandidate(
                candidate_id=cid,
                state=INVITE_STATUS.get(status or "", "not_opened"),
                answered=answered.get(sid, 0),
                paper_status=paper_status,
                paper_error=paper_error,
                waited_s=waited,
                opened_at=created,
                started_at=started,
                finished_at=finished,
                name=full_name,
                email=mail.mask(email),
                invite_mail=sent.get("invite"),
                result_mail=result_kind,
                result_mail_status=sent.get(result_kind) if result_kind else None,
            )
        )
    return found


@dataclass(frozen=True)
class DeleteResult:
    session_ids: list[str]  # so the caller can remove their video files after the commit
    sessions: int
    candidates: int
    questions: int  # written for them by the AI, which belonged to no one else
    finished: int
    decisions: int


def delete_sitting(db: Session, sitting_id: int, confirm_name: str, clock: Clock) -> DeleteResult:
    """Remove a sitting and everything that belongs to it: its candidates and their codes, every
    session with its answers, events, flags, decisions and recordings' records, and the questions
    written for them. The audit trail stays, with the session links cleared.

    The name must be typed as it is written. A sitting with a test running is refused: deleting
    under someone who is answering would throw their work away. Does not commit; video files are
    removed by the caller once the commit has happened."""
    sitting = db.get(Sitting, sitting_id)
    if sitting is None:
        raise ApiError(404, "sitting_not_found")
    if confirm_name.strip() != sitting.name:
        raise ApiError(422, "name_does_not_match")

    now = clock.now()
    session_ids = list(
        db.scalars(select(TestSession.id).where(TestSession.sitting_id == sitting_id))
    )
    running = (
        db.scalar(
            select(func.count())
            .select_from(TestSession)
            .where(
                TestSession.sitting_id == sitting_id,
                TestSession.status == "in_progress",
                TestSession.ends_at > now,
            )
        )
        or 0
    )
    if running:
        raise ApiError(409, "sessions_in_progress", in_progress=running)

    finished = (
        db.scalar(
            select(func.count())
            .select_from(TestSession)
            .where(TestSession.sitting_id == sitting_id, TestSession.status == "finished")
        )
        or 0
    )
    decisions = 0
    if session_ids:
        decisions = (
            db.scalar(
                select(func.count())
                .select_from(Decision)
                .where(Decision.session_id.in_(session_ids))
            )
            or 0
        )
        db.execute(
            update(AuditLog).where(AuditLog.session_id.in_(session_ids)).values(session_id=None)
        )
        # the database removes everything hanging off a session with it
        db.execute(delete(TestSession).where(TestSession.id.in_(session_ids)))

    # Written questions belong to one candidate's paper; with the paper gone nothing reads them.
    # A stored question is never touched: only source "ai", and only if no paper holds it now.
    questions = db.execute(
        delete(Question).where(
            Question.source == "ai",
            ~exists().where(SessionQuestion.question_id == Question.id),
        )
    ).rowcount
    # Candidates of this sitting, unless one also sat another (an old invitation could have).
    elsewhere = exists().where(
        TestSession.candidate_id == Candidate.id, TestSession.sitting_id != sitting_id
    )
    candidates = db.execute(
        delete(Candidate).where(Candidate.sitting_id == sitting_id, ~elsewhere)
    ).rowcount
    db.execute(update(Candidate).where(Candidate.sitting_id == sitting_id).values(sitting_id=None))
    db.execute(delete(Sitting).where(Sitting.id == sitting_id))
    db.flush()
    return DeleteResult(session_ids, len(session_ids), candidates, questions, finished, decisions)


def retry_papers(db: Session, sitting_id: int, clock: Clock, wait_limit_s: int) -> int:
    """Ask again for every candidate in an AI sitting whose paper failed, or has been pending
    longer than `wait_limit_s` (stuck). A paper still being written within the limit is left
    alone. Returns how many. What was already written is kept; `launch_papers` starts the
    writing after the commit."""
    sitting = db.get(Sitting, sitting_id)
    if sitting is None:
        raise ApiError(404, "sitting_not_found")
    if sitting.question_mode != "ai":
        raise ApiError(409, "not_an_ai_sitting")
    now = clock.now()
    sessions = [
        session
        for session in db.scalars(
            select(TestSession).where(
                TestSession.sitting_id == sitting_id, TestSession.paper_status != "ready"
            )
        )
        if session.paper_status == "failed"
        or (test_flow.waited_s(session, now) or 0) >= wait_limit_s
    ]
    for session in sessions:
        session.paper_status = "pending"
        session.paper_error = None
        session.paper_requested_at = now
        jobs.abandon(session.id)
    db.flush()
    return len(sessions)


def launch_papers(db: Session, sitting_id: int) -> int:
    """Hand every pending paper of a sitting to the background writer (after the commit)."""
    ids = list(
        db.scalars(
            select(TestSession.id).where(
                TestSession.sitting_id == sitting_id, TestSession.paper_status == "pending"
            )
        )
    )
    return sum(1 for session_id in ids if jobs.launch(session_id))


# ---------------------------------------------------------------------------------- invitations


def sitting_for_invites(db: Session, sitting_id: int | None) -> Sitting:
    """The sitting a batch of invitations is for. Named, it must exist and be open. Not named,
    it is the only open sitting; with none or several open the caller has to say which, because
    an invitation that opens the wrong paper cannot be told apart from a good one."""
    if sitting_id is not None:
        sitting = db.get(Sitting, sitting_id)
        if sitting is None:
            raise ApiError(404, "sitting_not_found")
        if sitting.status != "open":
            raise ApiError(409, "sitting_closed")
        return sitting
    open_ones = list(db.scalars(select(Sitting).where(Sitting.status == "open")))
    if not open_ones:
        raise ApiError(409, "no_open_sitting")
    if len(open_ones) > 1:
        raise ApiError(422, "sitting_required", sittings=[s.id for s in open_ones])
    return open_ones[0]


def generate_invites(
    db: Session,
    count: int,
    sitting: Sitting | None = None,
    people: list[candidate_list.Person] | None = None,
) -> list[tuple[str, str]]:
    """New candidates for one sitting, with their codes: [(candidate_id, code)]. Each opens that
    sitting's paper, for as long as that sitting says. Only each code's hash is stored, so this
    is the one time the code exists in the clear. With `people`, one candidate is made for each,
    in order, with their name and email attached (and `count` is ignored)."""
    if people is not None:
        count = len(people)
    if not 1 <= count <= MAX_INVITES:
        raise ApiError(422, "invalid_count", min=1, max=MAX_INVITES)
    sitting = sitting or sitting_for_invites(db, None)

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
        person = people[number - first] if people is not None else None
        db.add(
            Candidate(
                id=candidate_id,
                invite_token_hash=hash_token(code),
                sitting_id=sitting.id,
                full_name=person.name if person else None,
                email=person.email if person else None,
            )
        )
        invites.append((candidate_id, code))
    db.flush()
    return invites


def invited_emails(db: Session, sitting: Sitting) -> frozenset[str]:
    """The emails this sitting already has a candidate for."""
    return frozenset(
        db.scalars(
            select(Candidate.email).where(
                Candidate.sitting_id == sitting.id, Candidate.email.is_not(None)
            )
        )
    )


def read_list(
    db: Session, sitting: Sitting, raw: str
) -> tuple[list[candidate_list.Person], list[candidate_list.Problem]]:
    """The pasted list, parsed against what this sitting already has. Writes nothing."""
    return candidate_list.parse(raw, invited_emails(db, sitting))


def _window_line(sitting: Sitting) -> str:
    def show(moment: datetime) -> str:
        return moment.astimezone(UTC).strftime("%d %B %Y, %H:%M UTC")

    if sitting.opens_at and sitting.closes_at:
        opens, closes = show(sitting.opens_at), show(sitting.closes_at)
        return f"The test is open from {opens} until {closes}.\n"
    if sitting.closes_at:
        return f"The test closes on {show(sitting.closes_at)}.\n"
    if sitting.opens_at:
        return f"The test opens on {show(sitting.opens_at)}.\n"
    return ""


def invite_email(
    settings: Settings, sitting: Sitting, name: str, email: str, code: str
) -> tuple[str, str]:
    """(subject, body) of the invitation: the link, the code, and what to expect."""
    link = f"{settings.public_base_url.rstrip('/')}/?t={format_invite_code(code)}"
    return mail.render(
        "invite",
        name=name,
        email=email,
        code=format_invite_code(code),
        link=link,
        questions=str(sitting.question_count),
        minutes=str(-(-sitting.duration_s // 60)),
        window=_window_line(sitting),
    )


def queue_invitations(
    db: Session,
    clock: Clock,
    settings: Settings,
    sitting: Sitting,
    invites: list[tuple[str, str]],
    people: list[candidate_list.Person],
) -> None:
    """Write each person's invitation email to the outbox. The caller commits, then starts the
    sender (mail.launch_sending)."""
    for (candidate_id, code), person in zip(invites, people, strict=True):
        subject, body = invite_email(settings, sitting, person.name, person.email, code)
        mail.queue(
            db,
            clock,
            candidate_id=candidate_id,
            kind="invite",
            to=person.email,
            subject=subject,
            body=body,
        )


# Where a candidate is, read off their newest session: no session yet means the code has not been
# used, a created one means they opened the link but have not started the timer.
INVITE_STATUS = {"created": "opened", "in_progress": "started", "finished": "finished"}
INVITES_SHOWN = 500


@dataclass(frozen=True)
class InviteRow:
    candidate_id: str
    status: str
    sitting_id: int | None  # None: made before invitations belonged to a sitting
    sitting_name: str | None
    name: str | None  # admin-only: nothing a reviewer or the AI reads carries it
    email: str | None  # masked
    invite_mail: str | None  # queued | sent | failed, None when no email was ever queued


def mail_statuses(db: Session, candidate_ids: list[str]) -> dict[str, dict[str, str]]:
    """candidate id -> {email kind -> status}, for the ids asked about."""
    found: dict[str, dict[str, str]] = {}
    if not candidate_ids:
        return found
    for candidate_id, kind, status in db.execute(
        select(EmailOutbox.candidate_id, EmailOutbox.kind, EmailOutbox.status).where(
            EmailOutbox.candidate_id.in_(candidate_ids)
        )
    ):
        found.setdefault(candidate_id, {})[kind] = status
    return found


def list_invites(
    db: Session, limit: int = INVITES_SHOWN, sitting_id: int | None = None
) -> tuple[list[InviteRow], int]:
    """The newest `limit` candidates (of one sitting, if named) with where each one is, and how
    many candidates there are. Codes are never here: only a hash is stored."""
    where = [Candidate.sitting_id == sitting_id] if sitting_id is not None else []
    total = db.scalar(select(func.count()).select_from(Candidate).where(*where)) or 0
    found = db.execute(
        select(
            Candidate.id, Candidate.sitting_id, Sitting.name, Candidate.full_name, Candidate.email
        )
        .outerjoin(Sitting, Sitting.id == Candidate.sitting_id)
        .where(*where)
        .order_by(func.length(Candidate.id).desc(), Candidate.id.desc())
        .limit(limit)
    ).all()
    ids = [row[0] for row in found]
    mails = mail_statuses(db, ids)
    newest: dict[str, str] = {}
    rows = db.execute(
        select(TestSession.candidate_id, TestSession.status)
        .where(TestSession.candidate_id.in_(ids))
        .order_by(TestSession.created_at)
    )
    for candidate_id, status in rows:
        newest[candidate_id] = status  # later sessions replace earlier ones
    return [
        InviteRow(
            i,
            INVITE_STATUS.get(newest.get(i, ""), "not_opened"),
            sid,
            sitting_name,
            full_name,
            mail.mask(email),
            mails.get(i, {}).get("invite"),
        )
        for i, sid, sitting_name, full_name, email in found
    ], total


def reissue_invite(
    db: Session, candidate_id: str, clock: Clock | None = None, settings: Settings | None = None
) -> str:
    """A new code for one candidate, to resend a lost link. The old code stops working at once, and
    so does their password: this is also how a forgotten password is fixed, because they choose a
    new one the next time they sign in. A candidate who has an email is sent the new invitation
    (when the caller passes the clock and settings; the caller commits and then starts the
    sender)."""
    candidate = db.get(Candidate, candidate_id)
    if candidate is None:
        raise ApiError(404, "candidate_not_found")
    code = new_invite_code()
    candidate.invite_token_hash = hash_token(code)
    candidate.password_hash = None
    sitting = db.get(Sitting, candidate.sitting_id) if candidate.sitting_id else None
    # Someone who has finished is not invited again (the email would say they can sit the test):
    # the admin gets the new link on screen, to pass on, so they can still finish their upload.
    done = db.scalar(
        select(TestSession.id).where(
            TestSession.candidate_id == candidate.id, TestSession.status == "finished"
        )
    )
    if candidate.email and sitting and clock and settings and done is None:
        subject, body = invite_email(
            settings, sitting, candidate.full_name or "", candidate.email, code
        )
        row = mail.queue(
            db, clock, candidate_id=candidate.id, kind="invite", to=candidate.email,
            subject=subject, body=body,
        )
        # the row exists if the first invitation was sent: send the new one over it
        row.subject, row.body, row.status = subject, body, "queued"
        row.attempts, row.error, row.sent_at = 0, None, None
    db.flush()
    return code


# ---------------------------------------------------------------------------------- the bank


def bank_summary(db: Session) -> BankSummary:
    rows = db.execute(
        select(Question.section, Question.source, func.count())
        .where(Question.source != "ai")
        .group_by(Question.section, Question.source)
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
    where = [Question.source != "ai"]
    if section:
        where.append(Question.section == section)
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
    """Remove practice questions. Returns (removed, kept): a practice question that an earlier
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


# ---------------------------------------------------------------------------------- AI questions


@dataclass(frozen=True)
class SampleResult:
    category: str
    difficulty: str
    text: str
    options: list[str]
    correct_index: int
    explanation: str
    written_by: str
    seconds: float
    rounds: int
    rejected: list[str]  # why other questions were thrown away on the way


def sample_question(
    category: str, writer: QuestionWriter, difficulty: str = "medium", solves: int = pipeline.SOLVES
) -> SampleResult:
    """Write one real question the way a candidate's paper would, every check included, and give it
    back with its answer. Nothing is stored. This is the admin's "try the writer" button."""
    if category not in CATEGORIES:
        raise ApiError(422, "unknown_section", sections=[category])
    report = pipeline.Report()
    started = time.perf_counter()
    try:
        batches = pipeline.produce(
            writer, CATEGORIES[category], [difficulty], [], random.Random(), report, solves
        )
        written = next(iter(batches))[0]
    except (pipeline.PaperFailed, WriterError) as problem:
        raise ApiError(
            502,
            "question_writer_failed",
            detail=str(problem)[:300],
            rejected=report.rejected[-5:],
        ) from problem
    return SampleResult(
        category=category,
        difficulty=written.difficulty,
        text=written.text,
        options=list(written.options),
        correct_index=written.correct_index,
        explanation=written.explanation,
        written_by=f"{writer.name}:{writer.model}",
        seconds=round(time.perf_counter() - started, 1),
        rounds=report.rounds,
        rejected=report.rejected[-5:],
    )


def writer_for(settings: Settings) -> QuestionWriter:
    return get_writer(settings)


def audit_detail_for_close(sitting: Sitting, unfinished: int) -> str:
    if unfinished:
        return f'closed sitting "{sitting.name}" (forced, {unfinished} unfinished)'
    return f'closed sitting "{sitting.name}"'
