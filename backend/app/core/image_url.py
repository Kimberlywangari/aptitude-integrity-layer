"""Signed links to the picture a question depends on.

An <img> element cannot send an Authorization header, so the candidate's page cannot fetch a picture
with their bearer token. Instead the question comes with a link that names the session and the one
picture, signed with the session secret. Only the pictures of the question being shown are ever
linked, and the server still checks that the picture belongs to a question on that session's paper.

As with the staff token and the recording links, the signer takes its time from the injected clock.
"""

import hashlib
from typing import Any

from itsdangerous import BadData, TimestampSigner, URLSafeTimedSerializer

from app.clock import Clock

SALT = "question-image"
DEFAULT_TTL_S = 6 * 3600  # longer than any sitting, so a link on screen never goes stale mid-test


def _serializer(secret: str, clock: Clock) -> URLSafeTimedSerializer:
    class ClockSigner(TimestampSigner):
        def get_timestamp(self) -> int:
            return int(clock.now().timestamp())

    return URLSafeTimedSerializer(
        secret, salt=SALT, signer=ClockSigner, signer_kwargs={"digest_method": hashlib.sha256}
    )


def issue_image_token(secret: str, clock: Clock, session_id: str, image_id: int) -> str:
    return _serializer(secret, clock).dumps({"s": session_id, "i": image_id})


def read_image_token(
    secret: str, clock: Clock, token: str, max_age_s: int = DEFAULT_TTL_S
) -> dict[str, Any] | None:
    """The claims of a genuine, unexpired link, or None for anything else."""
    try:
        claims = _serializer(secret, clock).loads(token, max_age=max_age_s)
    except BadData:
        return None
    if (
        not isinstance(claims, dict)
        or not isinstance(claims.get("s"), str)
        or not isinstance(claims.get("i"), int)
    ):
        return None
    return claims
