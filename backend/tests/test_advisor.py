"""Pure coverage for the advisor's key encryption. The anonymized-summary and
generation paths are verified against the live stack (they need a DB + a key)."""
from app.services import advisor


def test_key_encrypt_decrypt_roundtrip():
    token = advisor.encrypt_key("sk-secret-123")
    assert isinstance(token, bytes)
    assert b"sk-secret-123" not in token  # actually encrypted, not just encoded
    assert advisor.decrypt_key(token) == "sk-secret-123"


def test_decrypt_garbage_returns_none():
    assert advisor.decrypt_key(b"not-a-valid-token") is None
