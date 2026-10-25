"""Who passed, who failed and who is waiting: the one place a candidate's status is worked out.

The outcomes list, its counts, the candidate page's result panel and the result emails all read
`status_of`, so they cannot disagree. A candidate's result is only ever one of two things:

* a person's call (a reviewer or an admin pressed pass or fail), or
* the pass-mark rule, for a score below a mark an admin chose. It runs when a sitting is closed
  and when a closed sitting's mark is changed, and it never looks at flags.

Nothing here decides anything about integrity. A flagged candidate has no result until a person
has recorded a decision and then pressed pass or fail. The AI sets no mark and sends no email.

Names: the rows can carry a name and an address (`with_names`) for the admin's list and for the
emails. The reviewer routes never ask for them, and the audit text never holds one.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.clock import Clock
from app.config import Settings
from app.errors import ApiError
from app.models import (
    AuditLog,
    Candidate,
    EmailOutbox,
    Flag,
    Reviewer,
    SessionQuestion,
    Sitting,
    TestSession,
)
from app.services import mail
from app.services.review import (
    _find_session,
    _latest_decisions,
    ordered_queue,
    sittings_and_choice,
)
from app.services.staff_auth import record_action

KINDS = ("passed", "not_passed")  # the outbox kinds; the wording variant is chosen in `compose`

STATUSES = (
    "invited",
    "in_progress",
    "waiting_review",
    "in_review",
    "ready",
    "passed",
    "failed_score",
    "failed_review",
    "under_appeal",
    "incomplete",
)
EMAIL_STATES = ("none", "queued", "sent", "failed")
PAGE_SIZE = 50

# The reasons a reviewer can give a candidate who is turned down after a review. They describe what
# a person saw in plain words; no rule names, no numbers. Anything else is one line typed by them.
REASONS = {
    "focus": "During the test your screen left the test page or left full screen more than once.",
    "copy": "The record shows attempts to copy from, or paste into, the test page.",
    "recording": "Your camera or microphone recording was missing for a large part of the test.",
}
OTHER_MAX = 200


@dataclass
class Row:
    """One invited candidate in a sitting, with everything a status needs."""

    candidate_id: str
    has_email: bool
    name: str | None
    email: str | None  # both only filled in when asked for (`with_names`)
    session_id: str | None
    session_status: str | None
    score: int
    total: int
    result: str | None
    basis: str | None
    reason: str | None
    result_by: int | None
    result_at: datetime | None
    appeal_at: datetime | None
    flag_count: int = 0
    flagged: bool = False  # in the review queue
    decided: bool = False  # a decision is recorded
    email_state: str = "none"


def below_mark(row: Row, pass_mark: int | None) -> bool:
    return pass_mark is not None and row.session_status == "finished" and row.score < pass_mark


def status_of(row: Row, *, closed: bool, pass_mark: int | None) -> str:
    """The one status a candidate is in. A score under the mark counts as failed as soon as the
    candidate has finished, so the list shows what the close will send; until then it is only a
    reading, and a person can still pass them."""
    result, basis = row.result, row.basis
    if result is None and below_mark(row, pass_mark):
        result, basis = "fail", "score"
    if result == "fail" and row.appeal_at is not None:
        return "under_appeal"
    if result == "pass":
        return "passed"
    if result == "fail":
        return "failed_score" if basis == "score" else "failed_review"
    if row.session_status == "finished":
        if row.flagged:
            return "in_review" if row.decided else "waiting_review"
        return "ready"
    if closed:
        return "incomplete"
    return "in_progress" if row.session_status == "in_progress" else "invited"


# ---------------------------------------------------------------------------------- reading


def load_rows(db: Session, sitting: Sitting, *, with_names: bool = False) -> list[Row]:
    """Every candidate of a sitting in invitation order. A fixed number of queries however many
    candidates there are (the sitting's size is the only thing that grows)."""
    totals = (
        select(
            SessionQuestion.session_id.label("sid"),
            func.count().label("total"),
            func.count().filter(SessionQuestion.correct.is_(True)).label("score"),
        )
        .group_by(SessionQuestion.session_id)
        .subquery()
    )
    found = db.execute(
        select(
            Candidate.id,
            Candidate.full_name,
            Candidate.email,
            TestSession.id,
            TestSession.status,
            TestSession.result,
            TestSession.result_basis,
            TestSession.result_reason,
            TestSession.result_by,
            TestSession.result_at,
            TestSession.appeal_at,
            totals.c.score,
            totals.c.total,
        )
        .select_from(Candidate)
        .outerjoin(
            TestSession,
            and_(TestSession.candidate_id == Candidate.id, TestSession.sitting_id == sitting.id),
        )
        .outerjoin(totals, totals.c.sid == TestSession.id)
        .where(or_(Candidate.sitting_id == sitting.id, TestSession.id.is_not(None)))
        .order_by(func.length(Candidate.id), Candidate.id)
    ).all()
    rows = [
        Row(
            candidate_id=cid,
            has_email=bool(email),
            name=name if with_names else None,
            email=email if with_names else None,
            session_id=sid,
            session_status=status,
            score=score or 0,
            total=total or 0,
            result=result,
            basis=basis,
            reason=reason,
            result_by=by,
            result_at=at,
            appeal_at=appeal,
        )
        for (cid, name, email, sid, status, result, basis, reason, by, at, appeal, score, total)
        in found
    ]
    session_ids = [r.session_id for r in rows if r.session_id]
    if not rows:
        return rows

    flag_counts = dict(
        db.execute(
            select(Flag.session_id, func.count())
            .where(Flag.session_id.in_(session_ids))
            .group_by(Flag.session_id)
        ).all()
    )
    queue = {e.ranked.session.id for e in ordered_queue(db, sitting.id)}
    decisions = _latest_decisions(db, [s for s in session_ids if s in queue])
    ids = [r.candidate_id for r in rows]
    mail_state: dict[str, str] = {}
    for candidate_id, state in db.execute(
        select(EmailOutbox.candidate_id, EmailOutbox.status).where(
            EmailOutbox.kind.in_(KINDS), EmailOutbox.candidate_id.in_(ids)
        )
    ):
        mail_state[candidate_id] = state
    for row in rows:
        if row.session_id:
            row.flag_count = flag_counts.get(row.session_id, 0)
            row.flagged = row.session_id in queue
            row.decided = row.session_id in decisions
        row.email_state = mail_state.get(row.candidate_id, "none")
    return rows


def _item(row: Row, status: str, *, with_names: bool) -> dict[str, Any]:
    finished = row.session_status == "finished"
    item: dict[str, Any] = {
        "candidate_id": row.candidate_id,
        "status": status,
        "score": row.score if finished else None,
        "total": row.total if finished else None,
        "flag_count": row.flag_count,
        "email_state": row.email_state,
        "has_email": row.has_email,
        "result_at": row.result_at,
        "can_mark_passed": (
            status in ("ready", "in_review") and row.has_email and row.email_state == "none"
        ),
    }
    if with_names:
        item["name"] = row.name
        item["email"] = mail.mask(row.email)
    return item


def list_outcomes(
    db: Session,
    sitting: Sitting,
    *,
    with_names: bool = False,
    status: str | None = None,
    email_state: str | None = None,
    search: str | None = None,
    page: int = 1,
) -> dict[str, Any]:
    """The outcomes list: counts over the whole sitting, then one page of the filtered rows."""
    if status is not None and status not in STATUSES:
        raise ApiError(422, "invalid_status")
    if email_state is not None and email_state not in EMAIL_STATES:
        raise ApiError(422, "invalid_email_state")
    closed = sitting.status == "closed"
    rows = load_rows(db, sitting, with_names=with_names)
    statuses = [status_of(r, closed=closed, pass_mark=sitting.pass_mark) for r in rows]
    counts = dict.fromkeys(STATUSES, 0)
    email_counts = dict.fromkeys(EMAIL_STATES, 0)
    for row, state in zip(rows, statuses, strict=True):
        counts[state] += 1
        email_counts[row.email_state] += 1

    needle = (search or "").strip().lower()
    chosen = [
        (row, state)
        for row, state in zip(rows, statuses, strict=True)
        if (status is None or state == status)
        and (email_state is None or row.email_state == email_state)
        and (not needle or needle in row.candidate_id.lower())
    ]
    page = max(1, page)
    window = chosen[(page - 1) * PAGE_SIZE : page * PAGE_SIZE]
    return {
        "pass_mark": sitting.pass_mark,
        "question_count": sitting.question_count,
        "sitting_closed": closed,
        "counts": counts,
        "email_counts": email_counts,
        "total": len(rows),
        "matching": len(chosen),
        "page": page,
        "page_size": PAGE_SIZE,
        "items": [_item(row, state, with_names=with_names) for row, state in window],
    }


def view(db: Session, sitting_id: int | None, **options: Any) -> dict[str, Any]:
    """The outcomes screen for the sitting asked for (else the usual default), with the list of
    sittings to choose from. `options` are the filters and `with_names` of `list_outcomes`."""
    sittings, chosen = sittings_and_choice(db, sitting_id)
    sitting = db.get(Sitting, chosen) if chosen else None
    if sitting is None:
        empty = {
            "pass_mark": None, "question_count": 0, "sitting_closed": False,
            "counts": dict.fromkeys(STATUSES, 0), "email_counts": dict.fromkeys(EMAIL_STATES, 0),
            "total": 0, "matching": 0, "page": 1, "page_size": PAGE_SIZE, "items": [],
        }  # fmt: skip
        return {"sittings": sittings, "sitting_id": 0, **empty}
    return {"sittings": sittings, "sitting_id": chosen, **list_outcomes(db, sitting, **options)}


def export_rows(db: Session, sitting: Sitting) -> list[tuple[Row, str]]:
    """Every candidate with the status they are in, names and addresses included (admin only)."""
    closed = sitting.status == "closed"
    return [
        (row, status_of(row, closed=closed, pass_mark=sitting.pass_mark))
        for row in load_rows(db, sitting, with_names=True)
    ]


# ----------------------------------------------------------------------------------- the emails


def compose(
    settings: Settings,
    *,
    name: str,
    candidate_id: str,
    score: int,
    total: int,
    pass_mark: int | None,
    result: str,
    basis: str | None,
    reason: str | None,
) -> tuple[str, str, str]:
    """(outbox kind, subject, body) of the result email. The name is in the greeting and nowhere
    else; the reason is a person's sentence, never a rule name or a number from the rules."""
    line = f"Your result: {score} of {total} questions correct."
    if pass_mark is not None:
        line += f" The pass mark for this sitting was {pass_mark}."
    values = {
        "name": name,
        "result_line": line,
        "appeal_email": settings.appeal_email
        or settings.mail_from
        or "the address this email came from",
        "candidate_id": candidate_id,
        "reason": reason or "",
    }
    if result == "pass":
        template, kind = "passed", "passed"
    elif basis == "score":
        template, kind = "not_passed_score", "not_passed"
    else:
        template, kind = "not_passed_review", "not_passed"
    subject, body = mail.render(template, **values)
    return kind, subject, body


def previews() -> dict[str, dict[str, str]]:
    """The three emails with stand-ins, for the admin to read."""
    values = {
        "name": "[candidate's name]",
        "result_line": (
            "Your result: [score] of [total] questions correct. "
            "The pass mark for this sitting was [pass mark]."
        ),
        "appeal_email": "[appeal address]",
        "candidate_id": "[reference]",
        "reason": "[the reason the reviewer chose]",
    }
    out = {}
    for key in ("passed", "not_passed_score", "not_passed_review"):
        subject, body = mail.render(key, **values)
        out[key] = {"subject": subject, "body": body}
    return out


def result_email_exists(db: Session, candidate_id: str) -> bool:
    """Whether a result email has been queued or sent to this candidate, so nobody is written to
    twice and a reviewer who changes the shortlist afterwards can be told it will not change what
    the candidate read."""
    return (
        db.scalar(
            select(EmailOutbox.id).where(
                EmailOutbox.candidate_id == candidate_id,
                EmailOutbox.kind.in_(KINDS),
                EmailOutbox.status.in_(("queued", "sent")),
            )
        )
        is not None
    )


def _score_of(db: Session, session_id: str) -> tuple[int, int]:
    total, score = db.execute(
        select(func.count(), func.count().filter(SessionQuestion.correct.is_(True))).where(
            SessionQuestion.session_id == session_id
        )
    ).one()
    return int(score), int(total)


# ------------------------------------------------------------------------- a person's decision


def resolve_reason(result: str, key: str | None, text: str | None) -> str | None:
    """The sentence a failed candidate is told. A pass has none."""
    if result == "pass":
        return None
    if key in REASONS:
        return REASONS[key]
    if key not in (None, "other"):
        raise ApiError(422, "invalid_reason")
    typed = (text or "").strip()
    if not typed:
        raise ApiError(422, "reason_required")
    if len(typed) > OTHER_MAX:
        raise ApiError(422, "reason_too_long", max=OTHER_MAX)
    return typed


def blocker(
    session_status: str, *, has_email: bool, flagged: bool, decided: bool, emailed: bool
) -> str | None:
    """Why a result cannot be recorded and sent for this candidate right now, or None."""
    if session_status != "finished":
        return "not_finished"
    if emailed:
        return "already_emailed"
    if not has_email:
        return "no_email"
    if flagged and not decided:
        return "review_first"
    return None


def _record(
    db: Session,
    clock: Clock,
    settings: Settings,
    staff: Reviewer,
    session: TestSession,
    sitting: Sitting,
    result: str,
    reason: str | None,
    row: Row,
) -> None:
    """Store a person's result and queue its email, in the caller's transaction."""
    problem = blocker(
        session.status,
        has_email=row.has_email,
        flagged=row.flagged,
        decided=row.decided,
        emailed=row.email_state in ("queued", "sent"),
    )
    if problem:
        raise ApiError(409, problem)
    candidate = db.get(Candidate, session.candidate_id)
    score, total = _score_of(db, session.id)
    now = clock.now()
    session.result, session.result_basis, session.result_reason = result, "review", reason
    session.result_by, session.result_at, session.appeal_at = staff.id, now, None
    kind, subject, body = compose(
        settings,
        name=candidate.full_name or "",
        candidate_id=candidate.id,
        score=score,
        total=total,
        pass_mark=sitting.pass_mark,
        result=result,
        basis="review",
        reason=reason,
    )
    mail.queue(
        db, clock, candidate_id=candidate.id, kind=kind, to=candidate.email,
        subject=subject, body=body,
    )
    # the audit line names the candidate by ID only
    db.add(
        AuditLog(
            reviewer_id=staff.id,
            action="decision",
            session_id=session.id,
            ts=now,
            detail=f"{'pass' if result == 'pass' else 'fail'} email queued",
        )
    )
    db.flush()


def _row_for(db: Session, sitting: Sitting, session: TestSession) -> Row:
    rows = load_rows(db, sitting)
    for row in rows:
        if row.session_id == session.id:
            return row
    raise ApiError(404, "candidate_not_found")


def record_result(
    db: Session,
    clock: Clock,
    settings: Settings,
    staff: Reviewer,
    candidate_id: str,
    sitting_id: int | None,
    result: str,
    reason_key: str | None,
    reason_text: str | None,
) -> str:
    """A reviewer or an admin turns one candidate down or passes them, and the system sends the
    email. Returns the new status. Refused (409) until the candidate has finished and, if they
    are flagged, until a decision is recorded; once an email has gone it cannot be changed."""
    if result not in ("pass", "fail"):
        raise ApiError(422, "invalid_result")
    reason = resolve_reason(result, reason_key, reason_text)
    session = _find_session(db, candidate_id, sitting_id)
    sitting = db.get(Sitting, session.sitting_id)
    row = _row_for(db, sitting, session)
    _record(db, clock, settings, staff, session, sitting, result, reason, row)
    return "passed" if result == "pass" else "failed_review"


def bulk_pass(
    db: Session,
    clock: Clock,
    settings: Settings,
    staff: Reviewer,
    sitting: Sitting,
    candidate_ids: list[str],
) -> dict[str, Any]:
    """Pass several candidates in one go. Each one is held to the same rules as a single pass; the
    ones that are not allowed are listed with the reason and nothing is done for them."""
    rows = {r.candidate_id: r for r in load_rows(db, sitting)}
    queued = 0
    refused: list[dict[str, str]] = []
    for candidate_id in dict.fromkeys(candidate_ids):  # once each, in the order given
        row = rows.get(candidate_id)
        if row is None or row.session_id is None:
            refused.append({"candidate_id": candidate_id, "code": "candidate_not_found"})
            continue
        try:
            _record(
                db, clock, settings, staff, db.get(TestSession, row.session_id), sitting,
                "pass", None, row,
            )
        except ApiError as problem:
            refused.append({"candidate_id": candidate_id, "code": problem.code})
        else:
            queued += 1
    return {"queued": queued, "refused": refused}


def resend(
    db: Session,
    clock: Clock,
    settings: Settings,
    staff: Reviewer,
    candidate_id: str,
    sitting_id: int | None,
    confirm: bool,
) -> None:
    """Send the same result email again. It needs the person to say they are sure, and it reuses
    the one outbox row for this candidate, so nobody can end up with two."""
    if not confirm:
        raise ApiError(422, "confirmation_required")
    session = _find_session(db, candidate_id, sitting_id)
    if session.result is None:
        raise ApiError(409, "no_result")
    sitting = db.get(Sitting, session.sitting_id)
    candidate = db.get(Candidate, session.candidate_id)
    existing = db.scalar(
        select(EmailOutbox).where(
            EmailOutbox.candidate_id == candidate.id, EmailOutbox.kind.in_(KINDS)
        )
    )
    if existing is None or not candidate.email:
        raise ApiError(409, "no_email")
    score, total = _score_of(db, session.id)
    # shortcut: a resend names the sitting's pass mark as it is now; upgrade if marks are changed
    # after emails have gone and the first wording must be kept word for word.
    kind, subject, body = compose(
        settings,
        name=candidate.full_name or "",
        candidate_id=candidate.id,
        score=score,
        total=total,
        pass_mark=sitting.pass_mark,
        result=session.result,
        basis=session.result_basis,
        reason=session.result_reason,
    )
    if existing.kind != kind:
        raise ApiError(409, "already_emailed")
    mail.requeue_row(existing, subject, body)
    db.add(
        AuditLog(
            reviewer_id=staff.id,
            action="decision",
            session_id=session.id,
            ts=clock.now(),
            detail=f"{session.result} email sent again",
        )
    )
    db.flush()


def set_appeal(
    db: Session,
    clock: Clock,
    admin: Reviewer,
    candidate_id: str,
    sitting_id: int | None,
    under_appeal: bool,
) -> None:
    """An admin notes by hand that a candidate who failed has written to ask for a second look.
    There is no appeals system; this only keeps them visible in the list."""
    session = _find_session(db, candidate_id, sitting_id)
    if session.result != "fail":
        raise ApiError(409, "not_failed")
    session.appeal_at = clock.now() if under_appeal else None
    db.add(
        AuditLog(
            reviewer_id=admin.id,
            action="decision",
            session_id=session.id,
            ts=clock.now(),
            detail="marked under appeal" if under_appeal else "appeal closed",
        )
    )
    db.flush()


# ------------------------------------------------------------------------------ the pass mark


def check_mark(sitting: Sitting, value: int | None) -> None:
    if value is not None and not 1 <= value <= sitting.question_count:
        raise ApiError(422, "invalid_pass_mark", min=1, max=sitting.question_count)


def _movable(row: Row) -> bool:
    """The rule may still change this candidate: finished, no email sent, and no person has
    decided (a person's result, pass or fail, is never touched by the rule)."""
    return (
        row.session_status == "finished"
        and row.email_state == "none"
        and (row.result is None or row.basis == "score")
    )


def preview_mark(db: Session, sitting: Sitting, value: int | None) -> dict[str, Any]:
    """How many candidates would newly fall below `value`, and how many would stop being below
    it. Only people the rule may still change are counted; anyone already emailed, or decided by
    a person, is left alone whatever the mark."""
    check_mark(sitting, value)
    newly = cleared = 0
    for row in load_rows(db, sitting):
        if not _movable(row):
            continue
        now_below = below_mark(row, sitting.pass_mark) or (
            row.result == "fail" and row.basis == "score"
        )
        will_be = value is not None and row.score < value
        newly += will_be and not now_below
        cleared += now_below and not will_be
    closed = sitting.status == "closed"
    return {
        "current": sitting.pass_mark,
        "value": value,
        "newly_below": newly,
        "no_longer_below": cleared,
        "sitting_closed": closed,
        # a closed sitting sends the new rejections now; an open one waits for the close
        "emails_now": newly if closed else 0,
    }


def apply_score_rule(db: Session, clock: Clock, settings: Settings, sitting: Sitting) -> int:
    """Turn down, for their score alone, every finished candidate under the mark who a person has
    not decided and who has not been emailed, and queue their email. Anyone the rule turned down
    earlier who is now at or above the mark has that undone. Returns how many emails it queued.
    Flushes, never commits. Flags are never read here."""
    queued = 0
    now = clock.now()
    for row in load_rows(db, sitting, with_names=True):
        if not _movable(row):
            continue
        session = db.get(TestSession, row.session_id)
        below = sitting.pass_mark is not None and row.score < sitting.pass_mark
        if below and row.result is None:
            session.result, session.result_basis = "fail", "score"
            session.result_reason = f"{row.score} of {row.total}; pass mark {sitting.pass_mark}"
            session.result_by, session.result_at = None, now
            if row.has_email:
                kind, subject, body = compose(
                    settings,
                    name=row.name or "",
                    candidate_id=row.candidate_id,
                    score=row.score,
                    total=row.total,
                    pass_mark=sitting.pass_mark,
                    result="fail",
                    basis="score",
                    reason=None,
                )
                mail.queue(
                    db, clock, candidate_id=row.candidate_id, kind=kind, to=row.email,
                    subject=subject, body=body,
                )
                queued += 1
        elif not below and row.result == "fail" and row.basis == "score":
            session.result = session.result_basis = session.result_reason = None
            session.result_at = session.appeal_at = None
    db.flush()
    return queued


def set_pass_mark(
    db: Session,
    clock: Clock,
    settings: Settings,
    admin: Reviewer,
    sitting: Sitting,
    value: int | None,
) -> dict[str, Any]:
    """Change the pass mark. On a closed sitting the rule runs at once; on an open one it waits
    for the close, so the mark can be tuned before any email goes. Written to the audit log."""
    check_mark(sitting, value)
    before = sitting.pass_mark
    sitting.pass_mark = value
    queued = apply_score_rule(db, clock, settings, sitting) if sitting.status == "closed" else 0
    record_action(
        db,
        clock,
        admin,
        "admin",
        f'pass mark of "{sitting.name}" changed from {before} to {value}; '
        f"{queued} rejection emails queued",
    )
    return {"pass_mark": value, "queued": queued}


# --------------------------------------------------------------------------- one candidate


def panel(
    db: Session, session: TestSession, *, flagged: bool, decided: bool
) -> dict[str, Any]:
    """What the candidate's page shows about the result: the score, the mark, what was decided,
    whether the email has gone, and whether a result can be recorded now (and if not, why)."""
    sitting = db.get(Sitting, session.sitting_id)
    candidate = db.get(Candidate, session.candidate_id)
    score, total = _score_of(db, session.id)
    state = db.scalar(
        select(EmailOutbox.status).where(
            EmailOutbox.candidate_id == session.candidate_id, EmailOutbox.kind.in_(KINDS)
        )
    )
    deciders = (
        db.scalar(select(Reviewer.email).where(Reviewer.id == session.result_by))
        if session.result_by
        else None
    )
    email_state = state or "none"
    row_like = Row(
        candidate_id=session.candidate_id, has_email=bool(candidate.email), name=None, email=None,
        session_id=session.id, session_status=session.status, score=score, total=total,
        result=session.result, basis=session.result_basis, reason=session.result_reason,
        result_by=session.result_by, result_at=session.result_at, appeal_at=session.appeal_at,
        flagged=flagged, decided=decided, email_state=email_state,
    )
    status = status_of(row_like, closed=sitting.status == "closed", pass_mark=sitting.pass_mark)
    why_not = blocker(
        session.status,
        has_email=row_like.has_email,
        flagged=flagged,
        decided=decided,
        emailed=email_state in ("queued", "sent"),
    )
    return {
        "score": score,
        "total": total,
        "pass_mark": sitting.pass_mark,
        "status": status,
        "result": session.result,
        "basis": session.result_basis,
        "reason": session.result_reason,
        "decided_by": (
            None
            if session.result is None
            else "pass-mark rule"
            if session.result_basis == "score"
            else deciders or "removed account"
        ),
        "decided_at": session.result_at,
        "email_state": email_state,
        "can_record": why_not is None,
        "blocked_by": why_not,
        "reasons": [{"key": key, "text": text} for key, text in REASONS.items()],
    }
