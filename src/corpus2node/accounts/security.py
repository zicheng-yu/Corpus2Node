from __future__ import annotations

import hashlib
import secrets

from pwdlib import PasswordHash

_PASSWORD_HASH = PasswordHash.recommended()
_DUMMY_HASH = _PASSWORD_HASH.hash("not-a-real-password")


def normalize_email(value: str) -> str:
    return value.strip().casefold()


def hash_password(value: str) -> str:
    return _PASSWORD_HASH.hash(value)


def verify_password(value: str, encoded: str) -> bool:
    try:
        return _PASSWORD_HASH.verify(value, encoded or _DUMMY_HASH)
    except Exception:
        return False


def random_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()
