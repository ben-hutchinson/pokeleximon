from __future__ import annotations

import hashlib
import re
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError


_password_hasher = PasswordHasher()
USERNAME_RE = re.compile(r"^[a-z0-9_]{3,32}$")


def normalize_username(value: str) -> str:
    return (value or "").strip().lower()


def validate_username(value: str) -> str:
    normalized = normalize_username(value)
    if not USERNAME_RE.fullmatch(normalized):
        raise ValueError("Username must be 3-32 characters using lowercase letters, numbers, or underscores")
    return normalized


def hash_password(password: str) -> str:
    raw = password or ""
    if len(raw) < 8:
        raise ValueError("Password must be at least 8 characters")
    return _password_hasher.hash(raw)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _password_hasher.verify(password_hash, password or "")
    except VerifyMismatchError:
        return False


def generate_session_token() -> str:
    return f"plxs_{secrets.token_urlsafe(32)}"


def hash_session_token(token: str) -> str:
    return hashlib.sha256((token or "").encode("utf-8")).hexdigest()
