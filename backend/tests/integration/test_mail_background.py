"""The parts of mail that run on their own: the background sender that follows a request, and
launching it. The queue and SMTP themselves are covered in test_candidate_emails.py and
test_smtp_mailer.py. Nothing here reaches a mail server."""

import contextlib
import smtplib
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.models import EmailOutbox
from app.services import mail
from app.services.mail import launch_sending as real_launch_sending  # conftest stubs the module's
from tests.integration.test_candidate_emails import FakeMailer
from tests.unit.test_smtp_mailer import FakeSmtp, fake_smtp, mailer  # noqa: F401  (fixture)


def waiting_mail(db, clock, count=2):
    for n in range(count):
        mail.queue(
            db, clock, candidate_id=None, kind=f"note{n}", to=f"p{n}@example.org",
            subject="Hello", body="Body\n",
        )
    db.flush()


def statuses(db):
    return [row.status for row in db.scalars(select(EmailOutbox).order_by(EmailOutbox.id))]


@pytest.fixture
def background(db, settings, monkeypatch):
    """The sender opens its own session and sleeps between tries: use the test's and never sleep."""
    monkeypatch.setattr(mail, "SessionLocal", lambda: contextlib.nullcontext(db))
    naps: list[float] = []
    monkeypatch.setattr(mail.time, "sleep", naps.append)
    return naps


# ----------------------------------------------------------------------- the background sender


def test_it_sends_everything_waiting_and_stops_as_soon_as_the_queue_is_empty(
    background, db, clock, settings, monkeypatch
):
    waiting_mail(db, clock, count=3)
    fake = FakeMailer()
    monkeypatch.setattr(mail, "get_mailer", lambda s: fake)

    mail._send_in_background(settings, clock)

    assert len(fake.sent) == 3 and statuses(db) == ["sent"] * 3
    assert background == [0]  # one look, no waiting: nothing was left to retry
    assert mail._sending.acquire(blocking=False)  # the lock is free again
    mail._sending.release()


def test_a_server_that_is_down_is_tried_again_after_a_pause_and_then_left_for_an_admin(
    background, db, clock, settings, monkeypatch
):
    waiting_mail(db, clock, count=1)
    down = FakeMailer(fail=99)
    monkeypatch.setattr(mail, "get_mailer", lambda s: down)

    mail._send_in_background(settings, clock)

    assert background == list(mail.RETRY_PAUSES_S)  # 0, then 5 s, then 30 s
    assert statuses(db) == ["failed"]  # three tries, then it waits for an admin to ask again


def test_a_server_that_comes_back_between_tries_still_gets_the_mail(
    background, db, clock, settings, monkeypatch
):
    waiting_mail(db, clock, count=1)
    flaky = FakeMailer(fail=1)
    monkeypatch.setattr(mail, "get_mailer", lambda s: flaky)

    mail._send_in_background(settings, clock)

    assert len(flaky.sent) == 1 and statuses(db) == ["sent"]
    assert background == [0, 5]  # the second try, after the first pause, went through


def test_only_one_sender_runs_at_a_time_and_the_second_leaves_the_mail_to_the_first(
    background, db, clock, settings, monkeypatch
):
    waiting_mail(db, clock, count=1)
    fake = FakeMailer()
    monkeypatch.setattr(mail, "get_mailer", lambda s: fake)

    assert mail._sending.acquire(blocking=False)  # a sender is already running
    try:
        mail._send_in_background(settings, clock)
    finally:
        mail._sending.release()

    assert fake.sent == [] and statuses(db) == ["queued"]


def test_a_crash_in_the_sender_is_logged_not_raised_and_the_lock_is_released(
    background, db, clock, settings, monkeypatch, caplog
):
    def explode(settings):
        raise RuntimeError("the mail settings are broken")

    monkeypatch.setattr(mail, "get_mailer", explode)

    mail._send_in_background(settings, clock)  # a thread must not die with a traceback on stderr

    assert "sending queued mail stopped" in caplog.text
    assert mail._sending.acquire(blocking=False)
    mail._sending.release()


# ---------------------------------------------------------------------------------- launching


def test_nothing_starts_while_mail_is_not_set_up(settings, monkeypatch):
    started = []
    monkeypatch.setattr(mail, "get_settings", lambda: settings)  # smtp_host is empty in tests
    monkeypatch.setattr(mail, "threading", SimpleNamespace(Thread=lambda **kw: started.append(kw)))

    real_launch_sending()

    assert started == []


def test_with_mail_set_up_a_named_daemon_thread_runs_the_sender(settings, clock, monkeypatch):
    configured = settings.model_copy(update={"smtp_host": "smtp.test", "mail_from": "me@test"})
    monkeypatch.setattr(mail, "get_settings", lambda: configured)
    made = {}

    class Recorded:
        def __init__(self, **kwargs):
            made.update(kwargs)

        def start(self):
            made["started"] = True

    monkeypatch.setattr(mail, "threading", SimpleNamespace(Thread=Recorded))

    real_launch_sending(clock)

    assert made["target"] is mail._send_in_background
    assert made["args"] == (configured, clock)
    assert made["name"] == "mail" and made["daemon"] is True and made["started"] is True


# ------------------------------------------------------------------------ small connection cases


def test_a_connection_that_will_not_close_cleanly_is_closed_anyway(fake_smtp):  # noqa: F811
    sender = mailer()
    with sender.keep_open():
        sender.send("a@example.org", "Hello", "Body")
        smtp = FakeSmtp.instances[0]
        smtp.quit = lambda: (_ for _ in ()).throw(smtplib.SMTPServerDisconnected("gone"))

    assert smtp.calls[-1] == "close"  # quit failed, so the socket was closed instead


def test_a_failure_while_sending_drops_the_connection_so_the_next_email_starts_clean(
    fake_smtp,  # noqa: F811
):
    sender = mailer()
    with sender.keep_open():
        sender.send("a@example.org", "Hello", "Body")
        held = FakeSmtp.instances[0]

        def broken_pipe(message):
            raise OSError("broken pipe")

        held.send_message = broken_pipe
        with pytest.raises(mail.MailError, match="broken pipe"):
            sender.send("b@example.org", "Hello", "Body")
        sender.send("c@example.org", "Hello", "Body")

    assert len(FakeSmtp.instances) == 2  # a new connection for the email after the failure
    assert FakeSmtp.instances[1].message["To"] == "c@example.org"


def test_addresses_are_masked_and_a_value_that_is_not_an_address_is_left_alone():
    assert mail.mask("ada@example.org") == "a***@example.org"
    assert mail.mask(None) is None and mail.mask("not-an-address") == "not-an-address"
