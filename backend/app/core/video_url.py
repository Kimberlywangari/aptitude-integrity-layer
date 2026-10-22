"""Signed, short-lived links to a recording.

A browser's <video> element cannot send an Authorization header, so the reviewer page cannot play
a recording through the staff token. Instead the candidate's page carries a link that names the
session and the segment and the reviewer it was made for, signed with the session secret. The
reviewer is looked up again on every request, so a switched-off account stops working at once.

As with the staff token, the signer takes its time from the injected clock.
"""

import hashlib
from typing import Any

from itsdangerous import BadData, TimestampSigner, URLSafeTimedSerializer

from app.clock import Clock

SALT = "video-url"
DEFAULT_TTL_S = 4 * 3600  # long enough to review a candidate without the link going stale


def _serializer(secret: str, clock: Clock) -> URLSafeTimedSerializer:
    class ClockSigner(TimestampSigner):
        def get_timestamp(self) -> int:
            return int(clock.now().timestamp())

    return URLSafeTimedSerializer(
        secret, salt=SALT, signer=ClockSigner, signer_kwargs={"digest_method": hashlib.sha256}
    )


def issue_video_token(
    secret: str, clock: Clock, reviewer_id: int, session_id: str, segment: int
) -> str:
    return _serializer(secret, clock).dumps({"r": reviewer_id, "s": session_id, "g": segment})


def read_video_token(
    secret: str, clock: Clock, token: str, max_age_s: int = DEFAULT_TTL_S
) -> dict[str, Any] | None:
    """The claims of a genuine, unexpired link, or None for anything else."""
    try:
        claims = _serializer(secret, clock).loads(token, max_age=max_age_s)
    except BadData:
        return None
    if (
        not isinstance(claims, dict)
        or not isinstance(claims.get("r"), int)
        or not isinstance(claims.get("s"), str)
        or not isinstance(claims.get("g"), int)
    ):
        return None
    return claims
