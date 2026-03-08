# tests/service_c/test_auth_service.py
"""Unit tests for JWT authentication service."""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../../"))

import time
import pytest
import jwt

from services.service_c.app.services.auth_service import (
    hash_password,
    verify_password,
    create_access_token,
    decode_access_token,
    generate_api_key,
    JWT_SECRET,
    JWT_ALGORITHM,
    TokenPayload,
)


# ── hash_password / verify_password ──────────────────────────────────────────

class TestPasswordHashing:
    def test_hash_is_not_plaintext(self):
        h = hash_password("mysecret")
        assert h != "mysecret"

    def test_hash_starts_with_bcrypt_prefix(self):
        h = hash_password("mysecret")
        assert h.startswith("$2b$")

    def test_correct_password_verifies(self):
        h = hash_password("correct-horse-battery-staple")
        assert verify_password("correct-horse-battery-staple", h) is True

    def test_wrong_password_fails(self):
        h = hash_password("correct")
        assert verify_password("wrong", h) is False

    def test_two_hashes_of_same_password_differ(self):
        """bcrypt generates unique salts."""
        h1 = hash_password("same")
        h2 = hash_password("same")
        assert h1 != h2

    def test_both_hashes_verify_against_original(self):
        h1 = hash_password("same")
        h2 = hash_password("same")
        assert verify_password("same", h1) is True
        assert verify_password("same", h2) is True

    def test_empty_password_hashes(self):
        h = hash_password("")
        assert verify_password("", h) is True

    def test_unicode_password(self):
        h = hash_password("motdepassé€")
        assert verify_password("motdepassé€", h) is True

    def test_long_password_under_72_bytes(self):
        """bcrypt silently truncates at 72 bytes — passwords up to 72 chars work fine."""
        pwd = "a" * 72
        h = hash_password(pwd)
        assert verify_password(pwd, h) is True

    def test_password_over_72_bytes_raises(self):
        """bcrypt raises ValueError for passwords > 72 bytes (known limitation)."""
        pwd = "a" * 100
        with pytest.raises(ValueError, match="72 bytes"):
            hash_password(pwd)


# ── create_access_token ───────────────────────────────────────────────────────

class TestCreateToken:
    def test_returns_string(self):
        token = create_access_token("uuid-1", "a@b.com", "Alice")
        assert isinstance(token, str)

    def test_token_is_valid_jwt(self):
        token = create_access_token("uuid-1", "a@b.com", "Alice")
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        assert payload["sub"] == "uuid-1"

    def test_payload_contains_email(self):
        token = create_access_token("uuid-1", "alice@example.com", "Alice")
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        assert payload["email"] == "alice@example.com"

    def test_payload_contains_name(self):
        token = create_access_token("uuid-1", "a@b.com", "Bob")
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        assert payload["name"] == "Bob"

    def test_default_plan_is_free(self):
        token = create_access_token("uuid-1", "a@b.com", "Alice")
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        assert payload["plan"] == "free"

    def test_custom_plan(self):
        token = create_access_token("uuid-1", "a@b.com", "Alice", plan="pro")
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        assert payload["plan"] == "pro"

    def test_default_type_is_individual(self):
        token = create_access_token("uuid-1", "a@b.com", "Alice")
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        assert payload["type"] == "individual"

    def test_custom_type_organization(self):
        token = create_access_token("uuid-1", "a@b.com", "Alice", type_="organization")
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        assert payload["type"] == "organization"

    def test_exp_field_present(self):
        token = create_access_token("uuid-1", "a@b.com", "Alice")
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        assert "exp" in payload

    def test_iat_field_present(self):
        token = create_access_token("uuid-1", "a@b.com", "Alice")
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        assert "iat" in payload

    def test_exp_is_in_future(self):
        token = create_access_token("uuid-1", "a@b.com", "Alice")
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        assert payload["exp"] > time.time()


# ── decode_access_token ───────────────────────────────────────────────────────

class TestDecodeToken:
    def test_valid_token_returns_payload(self):
        token = create_access_token("uuid-1", "a@b.com", "Alice")
        result = decode_access_token(token)
        assert result is not None
        assert isinstance(result, TokenPayload)

    def test_decoded_sub_matches(self):
        token = create_access_token("my-uuid", "a@b.com", "Alice")
        result = decode_access_token(token)
        assert result.sub == "my-uuid"

    def test_decoded_email_matches(self):
        token = create_access_token("uuid-1", "user@test.com", "Alice")
        result = decode_access_token(token)
        assert result.email == "user@test.com"

    def test_invalid_token_returns_none(self):
        result = decode_access_token("not.a.valid.token")
        assert result is None

    def test_tampered_token_returns_none(self):
        token = create_access_token("uuid-1", "a@b.com", "Alice")
        tampered = token[:-5] + "XXXXX"
        assert decode_access_token(tampered) is None

    def test_expired_token_returns_none(self, monkeypatch):
        """Force expiry in the past."""
        from datetime import datetime, timedelta, timezone
        import services.service_c.app.services.auth_service as svc

        original = svc.JWT_EXPIRATION_DAYS
        monkeypatch.setattr(svc, "JWT_EXPIRATION_DAYS", -1)
        token = svc.create_access_token("uuid-1", "a@b.com", "Alice")
        result = decode_access_token(token)
        assert result is None
        monkeypatch.setattr(svc, "JWT_EXPIRATION_DAYS", original)

    def test_empty_string_returns_none(self):
        assert decode_access_token("") is None

    def test_wrong_secret_returns_none(self):
        payload = {"sub": "x", "email": "e@e.com", "name": "E",
                   "plan": "free", "type": "individual",
                   "exp": int(time.time()) + 3600, "iat": int(time.time())}
        token = jwt.encode(payload, "wrong-secret", algorithm=JWT_ALGORITHM)
        assert decode_access_token(token) is None


# ── generate_api_key ──────────────────────────────────────────────────────────

class TestGenerateApiKey:
    def test_starts_with_gr_prefix(self):
        key = generate_api_key()
        assert key.startswith("gr_")

    def test_length_is_59_chars(self):
        key = generate_api_key()
        # "gr_" (3) + 56 hex chars (28 bytes * 2)
        assert len(key) == 59

    def test_keys_are_unique(self):
        keys = {generate_api_key() for _ in range(100)}
        assert len(keys) == 100

    def test_key_is_alphanumeric_after_prefix(self):
        key = generate_api_key()
        suffix = key[3:]
        assert suffix.isalnum()
