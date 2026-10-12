"""Safe Exam Browser request verification.

SEB adds a header to every request it makes: the SHA-256 of (absolute request URL + key),
where the key is the Browser Exam Key (header X-SafeExamBrowser-RequestHash) or the Config Key
(header X-SafeExamBrowser-ConfigKeyHash). The URL is the one the browser requested, which is why
`PUBLIC_BASE_URL` must match what the candidate's browser shows (master plan A6, R7).

Which key type to use is decided by the D2 spike; SEB_ALLOWED_KEYS holds the chosen key(s), and a
request passes if either header matches any allowed key.
"""

import hashlib
import hmac
import logging
from collections.abc import Mapping
from dataclasses import dataclass

from fastapi import Depends, Request

from app.config import Settings, get_settings
from app.errors import ApiError

logger = logging.getLogger("integrity.seb")

REQUEST_HASH_HEADER = "x-safeexambrowser-requesthash"  # Browser Exam Key
CONFIG_KEY_HEADER = "x-safeexambrowser-configkeyhash"  # Config Key


@dataclass(frozen=True)
class SebCheck:
    verified: bool
    reason: str  # ok | no_keys_configured | no_header | mismatch


def request_hash(url: str, key: str) -> str:
    return hashlib.sha256((url + key).encode()).hexdigest()


def public_request_url(request: Request, settings: Settings) -> str:
    """The URL as the candidate's browser requested it: public base + path + raw query."""
    url = settings.public_base_url.rstrip("/") + request.url.path
    query = request.scope.get("query_string", b"").decode("latin-1")
    return f"{url}?{query}" if query else url


def check_seb(url: str, headers: Mapping[str, str], keys: list[str]) -> SebCheck:
    """Pure check: do the SEB headers match sha256(url + key) for any allowed key?"""
    if not keys:
        return SebCheck(False, "no_keys_configured")
    received = [
        value.strip().lower()
        for name in (REQUEST_HASH_HEADER, CONFIG_KEY_HEADER)
        if (value := headers.get(name))
    ]
    if not received:
        return SebCheck(False, "no_header")
    for key in keys:
        expected = request_hash(url, key)
        if any(hmac.compare_digest(expected, got) for got in received):
            return SebCheck(True, "ok")
    return SebCheck(False, "mismatch")


def verify_seb(request: Request, settings: Settings) -> bool:
    url = public_request_url(request, settings)
    return check_seb(url, request.headers, settings.seb_keys).verified


def require_seb(request: Request, settings: Settings = Depends(get_settings)) -> bool:
    """Dependency for start, answer and skip. Returns whether this request was SEB-verified.

    off     : never blocks (local dev); the result is still returned so it can be recorded.
    log     : never blocks, but prints mismatches so they can be studied before enforcing.
    enforce : 403 {"code": "seb_required"} unless verified.
    """
    url = public_request_url(request, settings)
    result = check_seb(url, request.headers, settings.seb_keys)
    if result.verified or settings.seb_mode == "off":
        return result.verified
    if settings.seb_mode == "log":
        logger.warning("SEB check failed (%s) for %s %s", result.reason, request.method, url)
        return False
    raise ApiError(403, "seb_required")
