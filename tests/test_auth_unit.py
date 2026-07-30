"""Unit tests for auth helpers."""

from __future__ import annotations

import pytest

from app.auth.jwt import create_access_token, decode_access_token
from app.auth.passwords import hash_password, verify_password
from app.config import get_settings


def test_password_hash_roundtrip():
    hashed = hash_password("SecretPass12!")
    assert hashed != "SecretPass12!"
    assert verify_password("SecretPass12!", hashed) is True
    assert verify_password("wrong", hashed) is False


def test_jwt_encode_decode(monkeypatch, tmp_path):
    monkeypatch.setenv("JWT_SECRET", "unit-test-secret")
    monkeypatch.setenv("CHROMA_PERSIST_DIR", str(tmp_path / "chroma"))
    get_settings.cache_clear()
    token = create_access_token(
        user_id="u1",
        email="a@ampcus.com",
        role="admin",
        name="Admin",
        expires_minutes=60,
    )
    claims = decode_access_token(token)
    assert claims["id"] == "u1"
    assert claims["email"] == "a@ampcus.com"
    assert claims["role"] == "admin"
    with pytest.raises(ValueError):
        decode_access_token("not-a-token")
    get_settings.cache_clear()
