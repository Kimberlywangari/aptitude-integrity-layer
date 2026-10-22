"""Password hashing for staff accounts (bcrypt)."""

from functools import lru_cache

import bcrypt

# bcrypt's cost. Tests lower it (tests/conftest.py) so a hash does not take a quarter of a second.
ROUNDS = 12
# bcrypt reads at most 72 bytes; version 5 raises on anything longer, so we refuse it up front.
MAX_BYTES = 72


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt(rounds=ROUNDS)).decode()


def verify_password(plain: str, hashed: str) -> bool:
    encoded = plain.encode()
    if len(encoded) > MAX_BYTES:
        return False
    try:
        return bcrypt.checkpw(encoded, hashed.encode())
    except ValueError:  # a stored hash that is not valid bcrypt
        return False


@lru_cache
def _decoy_hash() -> str:
    return hash_password("not-a-real-password")


def spend_the_same_time(plain: str) -> None:
    """Run one check against a decoy, so an unknown email takes as long as a known one."""
    verify_password(plain, _decoy_hash())
