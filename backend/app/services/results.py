"""The result emails, as the admin's sitting page summarises them.

Nothing is sent from here. A person records a candidate's result, or the pass-mark rule does for a
low score when the sitting is closed, and the email is queued at that moment (services/outcomes.py),
so this page only counts what has gone, what is waiting to go and who is still waiting for a
result. A candidate who did not finish is never written to.

The wording is in app/mail_templates and is written for the candidate. It never mentions flags,
video, rules or the AI; a candidate who is turned down after a review is told, in one plain
sentence a reviewer chose, what the reviewer weighed, and how to appeal.
"""

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.models import Sitting
from app.services import outcomes


@dataclass
class ResultsPlan:
    sitting_closed: bool
    pass_mark: int | None
    sent_passed: int = 0
    sent_not_passed: int = 0
    queued: int = 0  # result emails waiting to go
    failed: int = 0  # ... and those that ran out of tries
    held_back: list[str] = field(default_factory=list)  # finished, no result recorded yet
    did_not_finish: int = 0
    without_email: int = 0  # finished, but there is no address to write to


def plan(db: Session, sitting: Sitting) -> ResultsPlan:
    """Where the result emails of a sitting stand. Reads only."""
    summary = ResultsPlan(sitting_closed=sitting.status == "closed", pass_mark=sitting.pass_mark)
    for row in outcomes.load_rows(db, sitting):
        if row.session_status != "finished":
            summary.did_not_finish += 1
            continue
        if not row.has_email:
            summary.without_email += 1
        if row.email_state == "sent":
            if row.result == "pass":
                summary.sent_passed += 1
            else:
                summary.sent_not_passed += 1
        elif row.email_state == "queued":
            summary.queued += 1
        elif row.email_state == "failed":
            summary.failed += 1
        if row.result is None:
            summary.held_back.append(row.candidate_id)
    return summary
