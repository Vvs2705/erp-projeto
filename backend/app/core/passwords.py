"""Password hashing using Argon2id (OWASP-recommended algorithm).

A single module-level ``PasswordHasher`` holds the cost parameters so they can
be tuned in one place. ``needs_rehash`` lets the login flow transparently
upgrade stored hashes when parameters change.
"""

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

_hasher = PasswordHasher()


def hash_password(plain: str) -> str:
    """Return an Argon2id hash for ``plain``."""
    return _hasher.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """Return ``True`` iff ``plain`` matches ``hashed``; never raises."""
    try:
        _hasher.verify(hashed, plain)
    except (VerifyMismatchError, InvalidHashError):
        return False
    return True


def needs_rehash(hashed: str) -> bool:
    """Return ``True`` when ``hashed`` should be re-computed with current params."""
    return _hasher.check_needs_rehash(hashed)
