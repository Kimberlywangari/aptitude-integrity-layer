import hashlib
import hmac
import re
import secrets

# Invitation codes are typed by hand inside SEB (clipboard is off), so they are short and forgiving:
# 8 characters from Crockford's base32 alphabet (no I, L, O or U), shown as XXXX-XXXX. The browser
# applies the same normalisation (frontend/src/lib/inviteCode.ts); keep the two in step.
INVITE_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
INVITE_LENGTH = 8
_SEPARATORS = re.compile(r"[\s_-]")
_LOOKALIKES = str.maketrans({"O": "0", "I": "1", "L": "1"})


def new_token() -> str:
    """A random bearer token (256 bits). Only its hash is ever stored."""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    # The tokens are long and random, so a plain SHA-256 is enough (no password-style stretching).
    return hashlib.sha256(token.encode()).hexdigest()


def tokens_match(token: str, stored_hash: str | None) -> bool:
    if not stored_hash:
        return False
    return hmac.compare_digest(hash_token(token), stored_hash)


def new_invite_code() -> str:
    """A random short invitation code (40 bits). Only its hash is ever stored."""
    return "".join(secrets.choice(INVITE_ALPHABET) for _ in range(INVITE_LENGTH))


def invite_code_from_digest(digest: bytes) -> str:
    """Map the first 40 bits of a digest to a code, so the seed can rebuild the same invites."""
    value = int.from_bytes(digest[:5], "big")
    shifts = range(5 * (INVITE_LENGTH - 1), -1, -5)
    return "".join(INVITE_ALPHABET[(value >> shift) & 31] for shift in shifts)


def normalise_invite_code(raw: str) -> str:
    """Case, spaces, dashes and underscores are ignored; O, I and L read as 0, 1 and 1.

    Anything that does not come out as a short code (the long hex tokens from the first seed) is
    returned as typed, trimmed, so existing invitations keep working.
    """
    trimmed = raw.strip()
    if not trimmed.isascii():
        return trimmed
    cleaned = _SEPARATORS.sub("", trimmed).upper().translate(_LOOKALIKES)
    if len(cleaned) == INVITE_LENGTH and all(c in INVITE_ALPHABET for c in cleaned):
        return cleaned
    return trimmed


def format_invite_code(code: str) -> str:
    """XXXX-XXXX for a canonical short code; anything else unchanged."""
    half = INVITE_LENGTH // 2
    if len(code) == INVITE_LENGTH and all(c in INVITE_ALPHABET for c in code):
        return f"{code[:half]}-{code[half:]}"
    return code
