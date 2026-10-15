"""Staff accounts: sign-in checks, account creation and switching an account off.

Functions here flush but never commit; the caller (an endpoint or a CLI job) owns the transaction.
Problems a person can fix come back as ValueError with a message safe to print.
"""

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.clock import Clock
from app.core.passwords import MAX_BYTES, hash_password, spend_the_same_time, verify_password
from app.models import AuditLog, Reviewer

ROLES = ("reviewer", "admin")
MIN_PASSWORD_LENGTH = 12
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def normalise_email(raw: str) -> str:
    return raw.strip().lower()


def authenticate(db: Session, email: str, password: str) -> Reviewer | None:
    """The active account these credentials belong to, or None.

    An unknown email, a switched-off account and a wrong password all take one bcrypt check and
    give the same answer, so neither the time nor the reply says which emails exist.
    """
    reviewer = db.scalar(select(Reviewer).where(Reviewer.email == normalise_email(email)))
    if reviewer is None or not reviewer.is_active:
        spend_the_same_time(password)
        return None
    return reviewer if verify_password(password, reviewer.password_hash) else None


def record_action(
    db: Session, clock: Clock, reviewer: Reviewer, action: str, detail: str | None = None
) -> None:
    """One audit row for something a signed-in person did. Flushed, committed by the caller."""
    db.add(AuditLog(reviewer_id=reviewer.id, action=action, ts=clock.now(), detail=detail))
    db.flush()


def record_login(db: Session, clock: Clock, reviewer: Reviewer) -> None:
    record_action(db, clock, reviewer, "login")


def _check_password(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"the password must be at least {MIN_PASSWORD_LENGTH} characters")
    if len(password.encode()) > MAX_BYTES:
        raise ValueError(f"the password must be at most {MAX_BYTES} bytes")


def create_reviewer(
    db: Session,
    clock: Clock,
    *,
    email: str,
    password: str,
    role: str = "reviewer",
    update: bool = False,
) -> tuple[Reviewer, bool]:
    """Create an account, or with update=True reset an existing one. Returns (account, created)."""
    email = normalise_email(email)
    if not _EMAIL.match(email) or len(email) > 254:
        raise ValueError("that does not look like an email address")
    if role not in ROLES:
        raise ValueError(f"the role must be one of: {', '.join(ROLES)}")
    _check_password(password)

    existing = db.scalar(select(Reviewer).where(Reviewer.email == email))
    if existing is not None and not update:
        raise ValueError(f"{email} already has an account; pass --update to reset it")
    if existing is not None:
        # a new password hash changes the token fingerprint, so older tokens stop working
        existing.password_hash = hash_password(password)
        existing.role = role
        existing.is_active = True
        db.flush()
        return existing, False

    reviewer = Reviewer(
        email=email,
        password_hash=hash_password(password),
        role=role,
        is_active=True,
        created_at=clock.now(),
    )
    db.add(reviewer)
    db.flush()
    return reviewer, True


def deactivate_reviewer(db: Session, email: str) -> Reviewer:
    reviewer = db.scalar(select(Reviewer).where(Reviewer.email == normalise_email(email)))
    if reviewer is None:
        raise ValueError(f"no account for {normalise_email(email)}")
    reviewer.is_active = False
    db.flush()
    return reviewer
