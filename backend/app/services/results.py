"""The result emails: "you passed" and "you did not pass".

A person decides, never the system and never the AI: a reviewer shortlists (that already exists),
and an admin presses send. Pass emails go to the shortlisted. Not-passed emails go, once the
sitting is closed, to everyone else who finished, except a candidate still under review: one the
queue flagged with no decision recorded, or whose latest decision is "refer for follow-up". Those
are held back until a person has decided. Nobody who did not finish is written to.

The wording is in app/mail_templates and never mentions flags, video, review or AI. Each candidate
gets at most one of the two (the outbox holds one row per candidate and kind, and a candidate who
already has the other is skipped), because an email cannot be taken back.
"""

from dataclasses import dataclass, field

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.clock import Clock
from app.errors import ApiError
from app.models import Candidate, EmailOutbox, Sitting, TestSession
from app.services import mail
from app.services.review import _latest_decisions, ordered_queue

KINDS = ("passed", "not_passed")


@dataclass
class Recipient:
    candidate_id: str
    name: str
    email: str


@dataclass
class ResultsPlan:
    sitting_closed: bool
    passed: list[Recipient] = field(default_factory=list)  # to send now
    not_passed: list[Recipient] = field(default_factory=list)  # to send once the sitting is closed
    held_back: list[str] = field(default_factory=list)  # candidate ids still under review
    sent_passed: int = 0
    sent_not_passed: int = 0
    did_not_finish: int = 0
    without_email: int = 0  # finished and decided, but there is no address to write to


def plan(db: Session, sitting: Sitting) -> ResultsPlan:
    """Who would get which email if an admin pressed send now. Reads only."""
    result = ResultsPlan(sitting_closed=sitting.status == "closed")
    rows = db.execute(
        select(
            Candidate.id,
            Candidate.full_name,
            Candidate.email,
            TestSession.id,
            TestSession.status,
            TestSession.shortlisted,
        )
        .select_from(Candidate)
        .outerjoin(
            TestSession,
            and_(TestSession.candidate_id == Candidate.id, TestSession.sitting_id == sitting.id),
        )
        .where(Candidate.sitting_id == sitting.id)
        .order_by(Candidate.id)
    ).all()
    sent: dict[str, set[str]] = {}
    for candidate_id, kind in db.execute(
        select(EmailOutbox.candidate_id, EmailOutbox.kind).where(
            EmailOutbox.kind.in_(KINDS), EmailOutbox.candidate_id.in_([r[0] for r in rows])
        )
    ):
        sent.setdefault(candidate_id, set()).add(kind)

    entries = ordered_queue(db, sitting.id)
    decisions = _latest_decisions(db, [e.ranked.session.id for e in entries])
    under_review = {
        e.ranked.session.id
        for e in entries
        if (d := decisions.get(e.ranked.session.id)) is None or d.outcome == "refer_for_follow_up"
    }

    for candidate_id, name, email, session_id, status, shortlisted in rows:
        if status != "finished":
            result.did_not_finish += 1
            continue
        already = sent.get(candidate_id, set())
        if shortlisted:
            kind, bucket = "passed", result.passed
        elif session_id in under_review:
            result.held_back.append(candidate_id)
            continue
        else:
            kind, bucket = "not_passed", result.not_passed
        if already:
            if kind in already:
                if kind == "passed":
                    result.sent_passed += 1
                else:
                    result.sent_not_passed += 1
            continue  # the other kind already went: it cannot be taken back
        if not email:
            result.without_email += 1
        else:
            bucket.append(Recipient(candidate_id, name or "", email))
    return result


def preview(kind: str) -> dict[str, str]:
    """The email as a candidate would read it, with a stand-in for the name."""
    subject, body = mail.render(kind, name="[candidate's name]")
    return {"subject": subject, "body": body}


def send(db: Session, clock: Clock, sitting: Sitting, kind: str) -> int:
    """Queue the `kind` email for everyone the plan says should get it. Returns how many.
    Flushes, never commits; the caller commits and then starts the sender."""
    if kind not in KINDS:
        raise ApiError(422, "invalid_kind")
    if kind == "not_passed" and sitting.status != "closed":
        raise ApiError(409, "sitting_not_closed")
    todo = plan(db, sitting)
    for person in todo.passed if kind == "passed" else todo.not_passed:
        subject, body = mail.render(kind, name=person.name)
        mail.queue(
            db,
            clock,
            candidate_id=person.candidate_id,
            kind=kind,
            to=person.email,
            subject=subject,
            body=body,
        )
    return len(todo.passed if kind == "passed" else todo.not_passed)


def result_email_exists(db: Session, candidate_id: str) -> bool:
    """Whether a result email has been queued or sent to this candidate, so a reviewer who
    changes the shortlist afterwards can be told it will not change what the candidate read."""
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
