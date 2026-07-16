from app.core import security
from app.core.security import (
    FailedLoginTracker,
    hash_password,
    hash_token,
    verify_password,
)


def test_hash_and_verify_roundtrip():
    h = hash_password("correct horse battery staple")
    assert verify_password(h, "correct horse battery staple") is True


def test_verify_wrong_password_returns_false():
    h = hash_password("correct horse battery staple")
    assert verify_password(h, "wrong password") is False


def test_verify_garbage_hash_returns_false():
    assert verify_password("not-a-valid-hash", "anything") is False


def test_hash_token_is_deterministic_64_hex():
    t1 = hash_token("some-token-value")
    t2 = hash_token("some-token-value")
    assert t1 == t2
    assert len(t1) == 64
    assert all(c in "0123456789abcdef" for c in t1)


def test_lockout_after_max_failures_then_unlocks(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(security.time, "monotonic", lambda: now[0])

    tracker = FailedLoginTracker(max_failures=3, lockout_seconds=60)
    ip = "1.2.3.4"

    assert tracker.is_locked(ip) is False
    tracker.record_failure(ip)
    tracker.record_failure(ip)
    assert tracker.is_locked(ip) is False  # still under the threshold
    tracker.record_failure(ip)
    assert tracker.is_locked(ip) is True

    now[0] += 30
    assert tracker.is_locked(ip) is True  # window hasn't elapsed yet

    now[0] += 31
    assert tracker.is_locked(ip) is False  # window elapsed


def test_reset_clears_failures():
    tracker = FailedLoginTracker(max_failures=2, lockout_seconds=60)
    ip = "5.6.7.8"
    tracker.record_failure(ip)
    tracker.reset(ip)
    tracker.record_failure(ip)
    assert tracker.is_locked(ip) is False
