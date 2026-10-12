import hashlib
import hmac
import secrets


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
