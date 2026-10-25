"""Who is at the door.

A candidate made for an email signs in in one of two ways:

- **First time:** the invitation code and the email it was sent to, then a password of their own
  choosing. Whoever completes this first owns the password, which is the trust the code and email
  already carried.
- **After that:** email and password. The code is no longer needed (it can still be given).

A candidate made without an email (practice, an old invitation) needs the code alone, as before.

The start page and the resume page both come through `find_candidate`, so they cannot disagree.
Every way of being wrong (no such code, a wrong email, a wrong or missing password, an email
nobody has) gives the same answer, `invalid_invitation`, counts against the same wrong-attempt
limit, and spends about the same time, so nobody can learn which part was right. The one exception
is an invitation whose code and email are right but which has no password yet: `password_needed`,
which only someone holding both could ever see.
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.passwords import MAX_BYTES, hash_password, spend_the_same_time, verify_password
from app.core.security import hash_token, normalise_invite_code
from app.errors import ApiError
from app.models import Candidate, Sitting

MIN_PASSWORD_CHARS = 8
# an email on several invitations (several sittings) is checked against this many, newest first
MAX_PASSWORDS_TRIED = 5


def _refuse(password: str | None) -> None:
    """The one answer for every kind of wrong, after the same bcrypt work a right guess costs."""
    spend_the_same_time(password or "")
    raise ApiError(401, "invalid_invitation")


def check_new_password(password: str) -> None:
    if len(password.strip()) < MIN_PASSWORD_CHARS:
        raise ApiError(422, "password_too_short", min=MIN_PASSWORD_CHARS)
    if len(password.encode()) > MAX_BYTES:
        raise ApiError(422, "password_too_long", max=MAX_BYTES)


def find_candidate(
    db: Session,
    invite_code: str | None,
    email: str | None,
    password: str | None = None,
    new_password: str | None = None,
) -> Candidate:
    address = (email or "").strip().lower()
    code = (invite_code or "").strip()

    if not code:
        return _by_email_and_password(db, address, password)

    candidate = db.scalar(
        select(Candidate).where(
            Candidate.invite_token_hash == hash_token(normalise_invite_code(code))
        )
    )
    if candidate is None:
        _refuse(password or new_password)
    if not candidate.email:  # made without an email: the code alone is enough
        return candidate
    if address != candidate.email:
        _refuse(password or new_password)

    if candidate.password_hash is None:  # the code and email are right and nothing is chosen yet
        if new_password is None:
            raise ApiError(409, "password_needed", min=MIN_PASSWORD_CHARS)
        check_new_password(new_password)
        candidate.password_hash = hash_password(new_password)
        db.flush()
        return candidate

    if not password or not verify_password(password, candidate.password_hash):
        _refuse(password)
    return candidate


def _by_email_and_password(db: Session, address: str, password: str | None) -> Candidate:
    if not address or not password:
        _refuse(password)
    invited = list(
        db.scalars(
            select(Candidate)
            .where(Candidate.email == address, Candidate.password_hash.is_not(None))
            .order_by(func.length(Candidate.id).desc(), Candidate.id.desc())
            .limit(MAX_PASSWORDS_TRIED)
        )
    )
    if not invited:
        _refuse(password)
    matches = [c for c in invited if verify_password(password, c.password_hash or "")]
    if not matches:
        raise ApiError(401, "invalid_invitation")
    # someone invited to several sittings is signed in to the one that is open
    open_sittings = set(
        db.scalars(
            select(Sitting.id).where(
                Sitting.status == "open", Sitting.id.in_([c.sitting_id for c in matches])
            )
        )
    )
    return next((c for c in matches if c.sitting_id in open_sittings), matches[0])
