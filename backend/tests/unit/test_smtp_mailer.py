import smtplib

import pytest

from app.services import mail


class FakeSmtp:
    """Stands in for smtplib.SMTP and remembers what it was asked."""

    instances: list["FakeSmtp"] = []
    refuse_login = False
    drop_on_send: set[int] = set()  # the nth send overall: the server has closed the connection
    sends = 0
    refuse_recipient = False

    def __init__(self, host, port, timeout):
        self.host, self.port, self.timeout = host, port, timeout
        self.calls: list[str] = []
        self.message = None
        FakeSmtp.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self):
        self.calls.append("starttls")

    def login(self, user, password):
        self.calls.append("login")
        if FakeSmtp.refuse_login:
            raise smtplib.SMTPAuthenticationError(535, b"5.7.8 Username and Password not accepted")

    def send_message(self, message):
        FakeSmtp.sends += 1
        if FakeSmtp.sends in FakeSmtp.drop_on_send:
            raise smtplib.SMTPServerDisconnected("Connection unexpectedly closed")
        if FakeSmtp.refuse_recipient:
            FakeSmtp.refuse_recipient = False
            raise smtplib.SMTPRecipientsRefused({"x@example.org": (550, b"no such user")})
        self.calls.append("send")
        self.message = message

    def quit(self):
        self.calls.append("quit")
        return 221, b"bye"

    def close(self):
        self.calls.append("close")


@pytest.fixture(autouse=True)
def fake_smtp(monkeypatch):
    FakeSmtp.instances, FakeSmtp.refuse_login = [], False
    FakeSmtp.drop_on_send, FakeSmtp.sends, FakeSmtp.refuse_recipient = set(), 0, False
    monkeypatch.setattr(mail.smtplib, "SMTP", FakeSmtp)


def mailer():
    return mail.SmtpMailer(
        "smtp.test", 587, "me@test", "app-password-1234", "me@test", "Cytonn Tests"
    )


def test_it_encrypts_logs_in_and_sends_a_plain_text_message_from_the_named_sender():
    mailer().send("ada@example.org", "Hello", "Body text\n")
    (smtp,) = FakeSmtp.instances
    assert (smtp.host, smtp.port) == ("smtp.test", 587)
    # encrypted before any password is sent, and the connection is closed afterwards
    assert smtp.calls == ["starttls", "login", "send", "quit"]
    assert smtp.message["To"] == "ada@example.org" and smtp.message["Subject"] == "Hello"
    assert smtp.message["From"] == "Cytonn Tests <me@test>"
    assert smtp.message.get_content().strip() == "Body text"


def test_a_server_that_refuses_is_reported_without_the_password():
    FakeSmtp.refuse_login = True
    with pytest.raises(mail.MailError) as caught:
        mailer().send("ada@example.org", "Hello", "Body")
    assert "535" in str(caught.value) and "app-password-1234" not in str(caught.value)


def test_a_server_that_cannot_be_reached_is_a_mail_error_too(monkeypatch):
    def unreachable(*args, **kwargs):
        raise OSError("connection refused")

    monkeypatch.setattr(mail.smtplib, "SMTP", unreachable)
    with pytest.raises(mail.MailError, match="connection refused"):
        mailer().send("ada@example.org", "Hello", "Body")


def test_a_run_of_emails_inside_keep_open_uses_one_connection():
    sender = mailer()
    with sender.keep_open():
        for n in range(5):
            sender.send(f"p{n}@example.org", "Hello", "Body")
    (smtp,) = FakeSmtp.instances  # not five
    assert smtp.calls == ["starttls", "login", "send", "send", "send", "send", "send", "quit"]


def test_outside_keep_open_every_email_still_closes_its_own_connection():
    sender = mailer()
    sender.send("a@example.org", "Hello", "Body")
    sender.send("b@example.org", "Hello", "Body")
    assert len(FakeSmtp.instances) == 2
    assert all(i.calls[-1] == "quit" for i in FakeSmtp.instances)


def test_a_connection_the_server_closed_is_replaced_once_and_the_email_still_goes():
    FakeSmtp.drop_on_send = {2}
    sender = mailer()
    with sender.keep_open():
        sender.send("a@example.org", "Hello", "Body")
        sender.send("b@example.org", "Hello", "Body")  # the server hung up before this one
        sender.send("c@example.org", "Hello", "Body")
    first, second = FakeSmtp.instances
    assert first.calls.count("send") == 1 and second.calls.count("send") == 2
    assert first.message["To"] == "a@example.org" and second.message["To"] == "c@example.org"


def test_a_refused_recipient_does_not_poison_the_emails_after_it():
    FakeSmtp.refuse_recipient = True
    sender = mailer()
    with sender.keep_open():
        with pytest.raises(mail.MailError, match="SMTPRecipientsRefused"):
            sender.send("x@example.org", "Hello", "Body")
        sender.send("y@example.org", "Hello", "Body")  # a clean connection, not the refused one
    assert len(FakeSmtp.instances) == 2
    assert FakeSmtp.instances[1].message["To"] == "y@example.org"
