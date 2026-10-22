"""Signed bearer tokens for staff (reviewers and admins).

A token carries the account id and a short fingerprint of the password hash, signed with the
session secret. Nothing else is trusted from it: the account row is read on every request, so the
role and the active flag always come from the database, and changing a password (or switching an
account off) stops older tokens at once.

itsdangerous reads time.time() on its own; the signer below takes the time from the injected
clock instead, so expiry is testable and follows the same rule as the rest of the code.
"""

import hashlib
import hmac
from typing import Any

from itsdangerous import BadData, TimestampSigner, URLSafeTimedSerializer

from app.clock import Clock
from app.core.security import hash_token

SALT = "staff-token"


def password_fingerprint(password_hash: str) -> str:
    """Changes whenever the password does; not reversible to anything useful."""
    return hash_token(password_hash)[:12]


def _serializer(secret: str, clock: Clock) -> URLSafeTimedSerializer:
    class ClockSigner(TimestampSigner):
        def get_timestamp(self) -> int:
            return int(clock.now().timestamp())

    return URLSafeTimedSerializer(
        secret, salt=SALT, signer=ClockSigner, signer_kwargs={"digest_method": hashlib.sha256}
    )


def issue_staff_token(secret: str, clock: Clock, reviewer_id: int, password_hash: str) -> str:
    claims = {"sub": reviewer_id, "pw": password_fingerprint(password_hash)}
    return _serializer(secret, clock).dumps(claims)


def read_staff_token(
    secret: str, clock: Clock, token: str, max_age_s: int
) -> dict[str, Any] | None:
    """The claims of a genuine, unexpired token, or None for anything else."""
    try:
        claims = _serializer(secret, clock).loads(token, max_age=max_age_s)
    except BadData:  # bad signature, malformed, or expired
        return None
    if (
        not isinstance(claims, dict)
        or not isinstance(claims.get("sub"), int)
        or not isinstance(claims.get("pw"), str)
    ):
        return None
    return claims


def fingerprint_matches(claimed: str, password_hash: str) -> bool:
    return hmac.compare_digest(claimed, password_fingerprint(password_hash))
