"""Regression tests for the cybersecurity hardening package.

These tests intentionally avoid spinning up the portal HTTP server: they cover
the security helpers in isolation so a failure pinpoints the broken primitive
(token format, secret policy, headers, repository auth) rather than bubbling
through hundreds of unrelated routes.
"""

from __future__ import annotations

import base64
import hmac as _hmac
import os
import time
from datetime import datetime, timedelta
from typing import List

import pytest


# ---------------------------------------------------------------------------
# auth_tokens
# ---------------------------------------------------------------------------


@pytest.fixture()
def token_secret(monkeypatch):
    """Configure a deterministic, sufficiently-long signing key for tests."""
    from security import auth_tokens

    primary = "a" * 48
    previous: List[str] = []

    def provider():
        return primary, list(previous)

    auth_tokens.set_secret_provider_for_tests(provider)
    yield primary, previous
    auth_tokens.set_secret_provider_for_tests(None)


def test_create_token_round_trips(token_secret):
    from security import auth_tokens

    expires = datetime.utcnow() + timedelta(hours=1)
    token, claims = auth_tokens.create_token("alice@phins.ai", "customer", "CUST-00001", expires)

    assert token.startswith("phins2_")
    assert "." in token
    assert claims.username == "alice@phins.ai"
    assert claims.role == "customer"
    assert claims.customer_id == "CUST-00001"

    verified = auth_tokens.verify_v2_token(token)
    assert verified is not None
    assert verified.username == "alice@phins.ai"
    assert verified.role == "customer"
    assert verified.jti == claims.jti


def test_create_token_uses_local_time_basis_for_default_iat(token_secret, monkeypatch):
    from security import auth_tokens

    original_tz = os.environ.get("TZ")
    monkeypatch.setenv("TZ", "Etc/GMT+5")
    time.tzset()
    try:
        expires = datetime.now() + timedelta(hours=1)
        token, claims = auth_tokens.create_token(
            "alice@phins.ai", "customer", "CUST-00001", expires
        )

        assert claims.issued_at <= time.time() + 300
        assert auth_tokens.verify_v2_token(token) is not None
    finally:
        if original_tz is None:
            monkeypatch.delenv("TZ", raising=False)
        else:
            monkeypatch.setenv("TZ", original_tz)
        time.tzset()


def test_v2_session_expires_matches_local_iso_format(token_secret, monkeypatch):
    from security import auth_tokens

    original_tz = os.environ.get("TZ")
    monkeypatch.setenv("TZ", "Etc/GMT-5")
    time.tzset()
    try:
        expires = datetime.now() + timedelta(hours=1)
        _token, claims = auth_tokens.create_token(
            "alice@phins.ai", "customer", "CUST-00001", expires
        )

        session = claims.to_session_dict()
        assert session["expires"] == datetime.fromtimestamp(claims.expires_at).isoformat()
    finally:
        if original_tz is None:
            monkeypatch.delenv("TZ", raising=False)
        else:
            monkeypatch.setenv("TZ", original_tz)
        time.tzset()


def test_create_token_requires_long_secret(monkeypatch):
    from security import auth_tokens

    auth_tokens.set_secret_provider_for_tests(lambda: ("short", []))
    try:
        with pytest.raises(auth_tokens.TokenSecretError):
            auth_tokens.create_token(
                "alice@phins.ai",
                "customer",
                None,
                datetime.utcnow() + timedelta(hours=1),
            )
    finally:
        auth_tokens.set_secret_provider_for_tests(None)


def test_create_token_requires_configured_secret(monkeypatch):
    from security import auth_tokens

    auth_tokens.set_secret_provider_for_tests(lambda: ("", []))
    try:
        with pytest.raises(auth_tokens.TokenSecretError):
            auth_tokens.create_token(
                "alice@phins.ai",
                "customer",
                None,
                datetime.utcnow() + timedelta(hours=1),
            )
    finally:
        auth_tokens.set_secret_provider_for_tests(None)


def test_expired_token_rejected(token_secret):
    from security import auth_tokens

    expires = datetime.utcnow() - timedelta(seconds=1)
    token, _ = auth_tokens.create_token("a", "customer", None, expires)
    assert auth_tokens.verify_v2_token(token) is None


def test_tampered_payload_rejected(token_secret):
    from security import auth_tokens

    token, _ = auth_tokens.create_token(
        "alice@phins.ai", "customer", None, datetime.utcnow() + timedelta(hours=1)
    )
    payload_b64, sig = token[len("phins2_"):].rsplit(".", 1)
    decoded = base64.urlsafe_b64decode(payload_b64 + "==")
    tampered = decoded.replace(b"customer", b"admin___", 1)
    tampered_b64 = base64.urlsafe_b64encode(tampered).rstrip(b"=").decode("ascii")
    tampered_token = f"phins2_{tampered_b64}.{sig}"

    assert auth_tokens.verify_v2_token(tampered_token) is None


def test_tampered_signature_rejected(token_secret):
    from security import auth_tokens

    token, _ = auth_tokens.create_token(
        "alice@phins.ai", "customer", None, datetime.utcnow() + timedelta(hours=1)
    )
    payload_b64, _sig = token[len("phins2_"):].rsplit(".", 1)
    bad_sig = "A" * 43  # valid length but wrong contents
    assert auth_tokens.verify_v2_token(f"phins2_{payload_b64}.{bad_sig}") is None


def test_revoke_token_blocks_future_verification(token_secret):
    from security import auth_tokens

    expires = datetime.utcnow() + timedelta(hours=1)
    token, claims = auth_tokens.create_token("alice@phins.ai", "customer", None, expires)

    auth_tokens.revoke_token(claims.jti, claims.expires_at)
    assert auth_tokens.verify_v2_token(token) is None


def test_revocation_expires_with_token(token_secret):
    from security import auth_tokens

    expires_at = time.time() - 10
    auth_tokens.revoke_token("jti-past", expires_at)
    assert auth_tokens.is_revoked("jti-past") is False


def test_prune_revocations_removes_expired_entries(token_secret):
    from security import auth_tokens

    now = time.time()
    auth_tokens.revoke_token("jti-expired", now - 5)
    auth_tokens.revoke_token("jti-live", now + 60)

    removed = auth_tokens.prune_revocations(now=now)

    assert removed >= 1
    assert auth_tokens.is_revoked("jti-expired") is False
    assert auth_tokens.is_revoked("jti-live") is True


def test_key_rotation_allows_previous_key(monkeypatch):
    """Tokens minted with the previous key still verify after rotation."""
    from security import auth_tokens

    old_primary = "o" * 48
    auth_tokens.set_secret_provider_for_tests(lambda: (old_primary, []))
    try:
        expires = datetime.utcnow() + timedelta(hours=1)
        token, _claims = auth_tokens.create_token("alice@phins.ai", "customer", None, expires)

        new_primary = "n" * 48
        auth_tokens.set_secret_provider_for_tests(lambda: (new_primary, [old_primary]))
        verified = auth_tokens.verify_v2_token(token)
        assert verified is not None
        assert verified.username == "alice@phins.ai"

        auth_tokens.set_secret_provider_for_tests(lambda: (new_primary, []))
        assert auth_tokens.verify_v2_token(token) is None
    finally:
        auth_tokens.set_secret_provider_for_tests(None)


def test_legacy_verifier_is_used_for_v1_tokens(token_secret):
    from security import auth_tokens

    calls: List[str] = []

    def legacy(token: str):
        calls.append(token)
        if token == "phins_legacy_token":
            return {"username": "legacy@phins.ai", "role": "admin"}
        return None

    auth_tokens.register_legacy_verifier(legacy)
    try:
        assert auth_tokens.verify_any_token("phins_legacy_token") == {
            "username": "legacy@phins.ai",
            "role": "admin",
        }
        assert auth_tokens.verify_any_token("phins_bogus") is None
        assert calls == ["phins_legacy_token", "phins_bogus"]
    finally:
        auth_tokens.register_legacy_verifier(None)


def test_token_signature_is_full_length(token_secret):
    from security import auth_tokens

    token, _ = auth_tokens.create_token(
        "alice@phins.ai", "customer", None, datetime.utcnow() + timedelta(hours=1)
    )
    _, sig_b64 = token[len("phins2_"):].rsplit(".", 1)
    # 32 bytes (SHA-256) base64-url encoded without padding ⇒ 43 chars.
    assert len(sig_b64) == 43, "v2 signature must be full HMAC-SHA256"


# ---------------------------------------------------------------------------
# secrets_policy
# ---------------------------------------------------------------------------


def test_secrets_policy_fails_on_missing_session_key_in_prod():
    from security.secrets_policy import audit_environment_secrets

    report = audit_environment_secrets({
        "ENVIRONMENT": "production",
        "SESSION_SECRET_KEY": "",
    })
    assert report.production_mode is True
    assert not report.ok
    assert any("SESSION_SECRET_KEY" in e for e in report.errors)


def test_secrets_policy_rejects_known_insecure_defaults():
    from security.secrets_policy import audit_environment_secrets

    report = audit_environment_secrets({
        "ENVIRONMENT": "production",
        "SESSION_SECRET_KEY": "a" * 48,
        "PHINS_EMERGENCY_UNLOCK_KEY": "phins-emergency-unlock-2026",
    })
    assert not report.ok
    assert any("PHINS_EMERGENCY_UNLOCK_KEY" in e for e in report.errors)


def test_secrets_policy_forbids_legacy_demo_passwords_in_prod():
    from security.secrets_policy import audit_environment_secrets

    report = audit_environment_secrets({
        "ENVIRONMENT": "production",
        "SESSION_SECRET_KEY": "a" * 48,
        "ALLOW_LEGACY_DEMO_PASSWORDS": "true",
    })
    assert not report.ok
    assert any("ALLOW_LEGACY_DEMO_PASSWORDS" in e for e in report.errors)


def test_secrets_policy_ok_in_test_mode():
    from security.secrets_policy import audit_environment_secrets

    report = audit_environment_secrets({
        "PHINS_TEST_MODE": "true",
        "SESSION_SECRET_KEY": "",
    })
    assert report.production_mode is False
    # Missing key in test mode is a warning, not an error.
    assert report.ok
    assert any("SESSION_SECRET_KEY" in w for w in report.warnings)


def test_secrets_policy_treats_short_test_mode_flag_as_non_production():
    from security.secrets_policy import audit_environment_secrets

    report = audit_environment_secrets({
        "PHINS_TEST_MODE": "y",
        "RAILWAY_ENVIRONMENT": "production",
        "SESSION_SECRET_KEY": "",
    })
    assert report.production_mode is False
    assert report.ok
    assert any("SESSION_SECRET_KEY" in w for w in report.warnings)


def test_secrets_policy_downgrades_forbidden_default_in_test_mode():
    """A forbidden-default value is an error in prod but only a warning in
    test/dev so the test runner still starts. Both conditions must appear
    in the warnings list in test mode (known-default + too-short)."""
    from security.secrets_policy import audit_environment_secrets

    report = audit_environment_secrets({
        "PHINS_TEST_MODE": "true",
        "SESSION_SECRET_KEY": "change-me",
        "PHINS_EMERGENCY_UNLOCK_KEY": "phins-emergency-unlock-2026",
        "PHINS_ADMIN_PASSWORD": "admin",
    })
    assert report.production_mode is False
    assert report.ok
    joined = " | ".join(report.warnings)
    assert "SESSION_SECRET_KEY matches a known-insecure default" in joined
    assert "SESSION_SECRET_KEY is shorter than 32 bytes" in joined
    assert "PHINS_EMERGENCY_UNLOCK_KEY matches a known-insecure default" in joined
    assert "PHINS_ADMIN_PASSWORD matches a known-insecure default" in joined


def test_secrets_policy_still_hard_fails_forbidden_default_in_production():
    from security.secrets_policy import audit_environment_secrets

    report = audit_environment_secrets({
        "ENVIRONMENT": "production",
        "SESSION_SECRET_KEY": "change-me",
    })
    assert not report.ok
    joined = " | ".join(report.errors)
    assert "SESSION_SECRET_KEY matches a known-insecure default" in joined


def test_secrets_policy_rejects_short_emergency_key_in_prod():
    from security.secrets_policy import audit_environment_secrets

    report = audit_environment_secrets({
        "ENVIRONMENT": "production",
        "SESSION_SECRET_KEY": "a" * 48,
        "PHINS_EMERGENCY_UNLOCK_KEY": "shortkey",
    })
    assert not report.ok
    assert any("PHINS_EMERGENCY_UNLOCK_KEY" in e for e in report.errors)


# ---------------------------------------------------------------------------
# headers
# ---------------------------------------------------------------------------


def test_json_security_headers_include_hardening_set():
    from security.headers import json_security_headers

    names = {name for name, _ in json_security_headers()}
    for required in (
        "X-Content-Type-Options",
        "X-Frame-Options",
        "Strict-Transport-Security",
        "Content-Security-Policy",
        "Referrer-Policy",
        "Permissions-Policy",
        "Cross-Origin-Opener-Policy",
        "Cross-Origin-Resource-Policy",
        "Cache-Control",
    ):
        assert required in names, f"missing required header {required}"


def test_json_csp_has_no_unsafe_inline():
    from security.headers import JSON_CSP

    assert "unsafe-inline" not in JSON_CSP
    assert "frame-ancestors 'none'" in JSON_CSP


def test_html_csp_forbids_objects_and_allows_same_origin_frames():
    from security.headers import HTML_CSP

    assert "object-src 'none'" in HTML_CSP
    assert "frame-ancestors 'self'" in HTML_CSP
    assert "base-uri 'self'" in HTML_CSP
    assert "'unsafe-eval'" not in HTML_CSP
    assert "connect-src 'self';" in HTML_CSP
    assert "img-src 'self' data: blob: https://api.qrserver.com;" in HTML_CSP


def test_permissions_policy_blocks_sensitive_features():
    from security.headers import PERMISSIONS_POLICY

    for feature in ("camera=()", "microphone=()", "geolocation=()", "payment=()", "usb=()"):
        assert feature in PERMISSIONS_POLICY


# ---------------------------------------------------------------------------
# User repository authenticate
# ---------------------------------------------------------------------------


def test_user_repository_authenticate_rejects_empty_inputs():
    from database.repositories.user_repository import UserRepository

    repo = UserRepository.__new__(UserRepository)
    assert repo.authenticate("", "hash") is None
    assert repo.authenticate("alice", "") is None


def test_user_repository_authenticate_matches_hashes(monkeypatch):
    """Broken tautology fix: authenticate must compare the provided hash
    against the stored hash instead of ``hash == hash``."""
    from database.repositories.user_repository import UserRepository

    class _User:
        def __init__(self, password_hash):
            self.password_hash = password_hash

    repo = UserRepository.__new__(UserRepository)
    stored = _User("deadbeefcafefeed")
    monkeypatch.setattr(repo, "get_by_username", lambda username: stored)

    assert repo.authenticate("alice", "deadbeefcafefeed") is stored
    assert repo.authenticate("alice", "wrong-hash") is None


def test_user_repository_authenticate_ignores_missing_user(monkeypatch):
    from database.repositories.user_repository import UserRepository

    repo = UserRepository.__new__(UserRepository)
    monkeypatch.setattr(repo, "get_by_username", lambda username: None)
    assert repo.authenticate("ghost", "deadbeef") is None
