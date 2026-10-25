import smtplib

import pytest

from app.services import mail


class FakeSmtp:
    """Stands in for smtplib.SMTP and remembers what it was asked."""

    instances: list["FakeSmtp"] = []
    refuse_login = False

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
        self.calls.append("send")
        self.message = message


@pytest.fixture(autouse=True)
def fake_smtp(monkeypatch):
    FakeSmtp.instances, FakeSmtp.refuse_login = [], False
    monkeypatch.setattr(mail.smtplib, "SMTP", FakeSmtp)


def mailer():
    return mail.SmtpMailer(
        "smtp.test", 587, "me@test", "app-password-1234", "me@test", "Cytonn Tests"
    )


def test_it_encrypts_logs_in_and_sends_a_plain_text_message_from_the_named_sender():
    mailer().send("ada@example.org", "Hello", "Body text\n")
    (smtp,) = FakeSmtp.instances
    assert (smtp.host, smtp.port) == ("smtp.test", 587)
    assert smtp.calls == ["starttls", "login", "send"]  # encrypted before any password is sent
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
