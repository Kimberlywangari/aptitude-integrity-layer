"""Outgoing mail: the queue (the email_outbox table) and the one door to SMTP.

An email is first written to the outbox, in the same transaction as whatever caused it (a list of
candidates saved, a result sent). A sender then works through the queue: right after the request
(a background thread) and again every round of the worker, so a restart or a mail server that is
down loses nothing. Each (candidate, kind) is one row, so nobody is sent the same email twice.

Nothing here reads a candidate's results. The wording lives in app/mail_templates/*.txt and never
mentions flags, video or the AI; the one email sent after a person reviewed a sitting says, in a
sentence that person chose, what they weighed.
"""

import logging
import smtplib
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr
from pathlib import Path
from typing import Protocol

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.clock import Clock
from app.config import Settings, get_settings
from app.db import SessionLocal
from app.models import EmailOutbox

log = logging.getLogger(__name__)

TEMPLATES = Path(__file__).resolve().parents[1] / "mail_templates"
MAX_ATTEMPTS = 3
SEND_BATCH = 100
SMTP_TIMEOUT_S = 30


class MailError(Exception):
    """The mail server refused or could not be reached. The message is safe to show an admin."""


class Mailer(Protocol):
    def send(self, to: str, subject: str, body: str) -> None:
        """Send one plain-text email. Raises MailError."""
        ...


class SmtpMailer:
    """Sends over SMTP with STARTTLS. On its own each `send` makes a connection and closes it.
    Inside `keep_open()` one connection serves every email in the run, which is what makes a batch
    fast: the connect, the encryption and the login are paid once, not once per email."""

    def __init__(
        self, host: str, port: int, user: str, password: str, from_address: str, from_name: str
    ) -> None:
        self._host, self._port = host, port
        self._user, self._password = user, password
        self._sender = formataddr((from_name, from_address)) if from_name else from_address
        self._conn: smtplib.SMTP | None = None
        self._holding = False

    def _connect(self) -> smtplib.SMTP:
        smtp = smtplib.SMTP(self._host, self._port, timeout=SMTP_TIMEOUT_S)
        try:
            smtp.starttls()
            if self._user:
                smtp.login(self._user, self._password)
        except BaseException:
            smtp.close()
            raise
        return smtp

    def _drop(self) -> None:
        conn, self._conn = self._conn, None
        if conn is not None:
            try:
                conn.quit()
            except (smtplib.SMTPException, OSError):
                conn.close()

    @contextmanager
    def keep_open(self) -> Iterator["SmtpMailer"]:
        """Hold one connection for the emails sent inside the block."""
        self._holding = True
        try:
            yield self
        finally:
            self._holding = False
            self._drop()

    def send(self, to: str, subject: str, body: str) -> None:
        message = EmailMessage()
        message["From"], message["To"], message["Subject"] = self._sender, to, subject
        message.set_content(body)
        try:
            try:
                smtp = self._conn or self._connect()
                smtp.send_message(message)
            except smtplib.SMTPServerDisconnected:
                # a server closes a connection that sat idle: one fresh connection, one more try
                self._conn = None
                smtp = self._connect()
                smtp.send_message(message)
            self._conn = smtp if self._holding else None
            if not self._holding:
                smtp.quit()
        except (smtplib.SMTPException, OSError) as problem:
            # whatever state the connection is in, the next email starts from a clean one
            self._drop()
            # never the password: SMTPAuthenticationError text carries the server's words only
            raise MailError(f"{type(problem).__name__}: {problem}"[:300]) from problem


def mail_is_set_up(settings: Settings) -> bool:
    return bool(settings.smtp_host and settings.mail_from)


def get_mailer(settings: Settings) -> Mailer | None:
    """The configured mailer, or None while mail is not set up."""
    if not mail_is_set_up(settings):
        return None
    return SmtpMailer(
        settings.smtp_host,
        settings.smtp_port,
        settings.smtp_user,
        settings.smtp_password,
        settings.mail_from,
        settings.mail_from_name,
    )


def render(kind: str, **values: str) -> tuple[str, str]:
    """(subject, body) from app/mail_templates/<kind>.txt. The first line is `Subject: ...`."""
    text = (TEMPLATES / f"{kind}.txt").read_text(encoding="utf-8")
    head, _, body = text.partition("\n\n")
    subject = head.removeprefix("Subject:").strip()
    # values are put in by name; a brace inside a candidate's name is just text
    return subject.format_map(values), body.format_map(values).rstrip() + "\n"


def mask(address: str | None) -> str | None:
    """j***@gmail.com: enough for an admin to recognise it, not enough to read it out."""
    if not address or "@" not in address:
        return address
    local, _, domain = address.partition("@")
    return f"{local[:1]}***@{domain}"


# ------------------------------------------------------------------------------------ the queue


def queue(
    db: Session,
    clock: Clock,
    *,
    candidate_id: str | None,
    kind: str,
    to: str,
    subject: str,
    body: str,
) -> EmailOutbox:
    """Add one email to the outbox, or return the one already there for this candidate and kind
    (so asking twice sends once). Flushes, never commits."""
    if candidate_id is not None:
        existing = db.scalar(
            select(EmailOutbox).where(
                EmailOutbox.candidate_id == candidate_id, EmailOutbox.kind == kind
            )
        )
        if existing is not None:
            return existing
    row = EmailOutbox(
        candidate_id=candidate_id,
        kind=kind,
        to_address=to,
        subject=subject,
        body=body,
        created_at=clock.now(),
    )
    db.add(row)
    db.flush()
    return row


def requeue_row(row: EmailOutbox, subject: str, body: str) -> None:
    """Put an email that already has its one outbox row back in the queue with new text. The
    unique (candidate, kind) key means a resend can never become a second row."""
    row.subject, row.body = subject, body
    row.status, row.attempts, row.error, row.sent_at = "queued", 0, None, None


def requeue_failed(db: Session) -> int:
    """Give every email that ran out of tries another three. Returns how many."""
    return db.execute(
        update(EmailOutbox)
        .where(EmailOutbox.status == "failed")
        .values(status="queued", attempts=0, error=None)
    ).rowcount


@dataclass(frozen=True)
class SendReport:
    sent: int
    failed: int  # emails that have now run out of tries


def send_queued(
    db: Session, clock: Clock, mailer: Mailer, limit: int = SEND_BATCH
) -> SendReport:
    """Send what is waiting, oldest first. Each email is committed as it goes, so a crash after a
    send never sends the earlier ones again. A failure is counted; at MAX_ATTEMPTS the email is
    marked failed and stops being tried until an admin asks again."""
    rows = list(
        db.scalars(
            select(EmailOutbox)
            .where(EmailOutbox.status == "queued", EmailOutbox.body.is_not(None))
            .order_by(EmailOutbox.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
    )
    sent = failed = 0
    keep_open = getattr(mailer, "keep_open", None)  # a mailer that can reuse one connection
    with keep_open() if keep_open else nullcontext():
        for row in rows:
            row.attempts += 1
            try:
                mailer.send(row.to_address, row.subject, row.body or "")
            except MailError as problem:
                row.error = str(problem)[:300]
                if row.attempts >= MAX_ATTEMPTS:
                    row.status = "failed"
                    failed += 1
            else:
                row.status, row.sent_at, row.error = "sent", clock.now(), None
                row.body = None  # an invite's body holds a live code: do not keep it once read
                sent += 1
            db.commit()
    return SendReport(sent, failed)


# ------------------------------------------------------------------- sending after a request

_sending = threading.Lock()
RETRY_PAUSES_S = (0, 5, 30)  # three tries a minute apart at most, then an admin decides


def waiting(db: Session) -> bool:
    return (
        db.scalar(
            select(EmailOutbox.id)
            .where(EmailOutbox.status == "queued", EmailOutbox.body.is_not(None))
            .limit(1)
        )
        is not None
    )


def _send_in_background(settings: Settings, clock: Clock) -> None:
    if not _sending.acquire(blocking=False):  # one sender at a time; it picks up new mail too
        return
    try:
        mailer = get_mailer(settings)
        for pause in RETRY_PAUSES_S:
            time.sleep(pause)
            with SessionLocal() as db:
                while waiting(db) and send_queued(db, clock, mailer).sent:
                    pass
                if not waiting(db):
                    return
    except Exception:
        log.exception("sending queued mail stopped")
    finally:
        _sending.release()


def launch_sending(clock: Clock | None = None) -> None:
    """Start sending the queue in a background thread. Call after the request has committed.
    Tests replace this (see conftest) so nothing leaves the test database."""
    from app.clock import SystemClock

    settings = get_settings()
    if not mail_is_set_up(settings):
        return
    threading.Thread(
        target=_send_in_background,
        args=(settings, clock or SystemClock()),
        name="mail",
        daemon=True,
    ).start()
