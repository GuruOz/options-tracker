"""Password hashing, session/CSRF token helpers, and brute-force lockout.

Session tokens are stored in the DB only as a sha256 hash — a DB leak alone
can't be replayed as a live session cookie.
"""
from __future__ import annotations

import hashlib
import secrets
import time

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_csrf_token() -> str:
    return secrets.token_urlsafe(32)


class FailedLoginTracker:
    """In-memory per-IP lockout after too many failed logins in a row.

    Process-local by design (single backend instance) — a restart clears it,
    which is an acceptable tradeoff for a single-shared-login homelab app.
    """

    def __init__(self, max_failures: int, lockout_seconds: int) -> None:
        self.max_failures = max_failures
        self.lockout_seconds = lockout_seconds
        self._failures: dict[str, int] = {}
        self._locked_until: dict[str, float] = {}

    def is_locked(self, ip: str) -> bool:
        until = self._locked_until.get(ip)
        if until is None:
            return False
        if time.monotonic() >= until:
            self._locked_until.pop(ip, None)
            self._failures.pop(ip, None)
            return False
        return True

    def record_failure(self, ip: str) -> None:
        count = self._failures.get(ip, 0) + 1
        self._failures[ip] = count
        if count >= self.max_failures:
            self._locked_until[ip] = time.monotonic() + self.lockout_seconds

    def reset(self, ip: str) -> None:
        self._failures.pop(ip, None)
        self._locked_until.pop(ip, None)


def _make_tracker() -> FailedLoginTracker:
    from app.core.config import get_settings

    settings = get_settings()
    return FailedLoginTracker(settings.auth_max_failed_logins, settings.auth_lockout_seconds)


login_tracker = _make_tracker()
