"""Staff tokens, driven by the fake clock."""

from app.clock import FakeClock
from app.core import staff_token
from app.core.staff_token import (
    _serializer,
    fingerprint_matches,
    issue_staff_token,
    password_fingerprint,
    read_staff_token,
)

SECRET = "test-secret"
MAX_AGE = 8 * 3600
HASH = "$2b$04$abcdefghijklmnopqrstuuABCDEFGHIJKLMNOPQRSTUVWXYZ012345"


def test_a_token_carries_the_account_id_and_a_password_fingerprint():
    clock = FakeClock()
    token = issue_staff_token(SECRET, clock, 7, HASH)
    claims = read_staff_token(SECRET, clock, token, MAX_AGE)
    assert claims == {"sub": 7, "pw": password_fingerprint(HASH)}


def test_a_token_is_good_up_to_its_lifetime_and_not_a_second_after():
    clock = FakeClock()
    token = issue_staff_token(SECRET, clock, 7, HASH)
    clock.advance(MAX_AGE)
    assert read_staff_token(SECRET, clock, token, MAX_AGE) is not None
    clock.advance(1)
    assert read_staff_token(SECRET, clock, token, MAX_AGE) is None


def test_a_token_signed_with_another_secret_is_refused():
    clock = FakeClock()
    token = issue_staff_token("some-other-secret", clock, 7, HASH)
    assert read_staff_token(SECRET, clock, token, MAX_AGE) is None


def _swap(token: str, index: int) -> str:
    return token[:index] + ("A" if token[index] != "A" else "B") + token[index + 1 :]


def test_a_token_with_a_changed_payload_or_signature_is_refused():
    clock = FakeClock()
    token = issue_staff_token(SECRET, clock, 7, HASH)
    payload, _, rest = token.partition(".")
    signature_start = len(payload) + 1 + len(rest.partition(".")[0]) + 1

    assert read_staff_token(SECRET, clock, _swap(token, 3), MAX_AGE) is None  # the payload
    assert read_staff_token(SECRET, clock, _swap(token, signature_start), MAX_AGE) is None


def test_garbage_is_refused_without_an_error():
    clock = FakeClock()
    for junk in ("", "x", "a.b.c", "not a token at all", "." * 40):
        assert read_staff_token(SECRET, clock, junk, MAX_AGE) is None


def test_a_token_made_for_another_purpose_is_refused(monkeypatch):
    clock = FakeClock()
    monkeypatch.setattr(staff_token, "SALT", "some-other-salt")
    token = issue_staff_token(SECRET, clock, 7, HASH)  # same secret, same clock, different salt
    monkeypatch.undo()
    assert read_staff_token(SECRET, clock, token, MAX_AGE) is None


def test_a_signed_token_with_the_wrong_shape_is_refused():
    clock = FakeClock()
    for claims in ({"sub": "7", "pw": "x"}, {"sub": 7}, ["sub", 7], "just a string"):
        token = _serializer(SECRET, clock).dumps(claims)
        assert read_staff_token(SECRET, clock, token, MAX_AGE) is None


def test_the_fingerprint_changes_with_the_password_hash():
    other = HASH[:-1] + ("0" if HASH[-1] != "0" else "1")
    assert password_fingerprint(HASH) != password_fingerprint(other)
    assert fingerprint_matches(password_fingerprint(HASH), HASH)
    assert not fingerprint_matches(password_fingerprint(HASH), other)
