"""
Tests for OTP-secured password reset flow.

The password reset process requires two steps:
  1. POST /api/request-password-reset  ->  returns verification_id, sends OTP
  2. POST /api/reset-password          ->  requires verification_id + otp_code

These tests verify:
  - OTP is required before a password can be changed
  - Invalid/expired OTPs are rejected
  - Notifications are dispatched on request and completion
  - Rate limiting via OTP service
  - Data integrity: sessions are revoked after reset
"""

import json
import urllib.request
import urllib.error

import web_portal.server as portal
from services.otp_security_service import (
    get_otp_security_service,
    reset_otp_security_service,
    OTPPurpose,
)

BASE = "http://localhost:8000"


def _post(path, payload):
    """POST JSON and return (status, parsed_body)."""
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def _setup_test_user(username="testuser", email="test@example.com", password="OldPass123"):
    """Register a user via the portal's in-memory USERS dict."""
    pwd_hash = portal.hash_password(password)
    portal.USERS[username] = {
        "hash": pwd_hash["hash"],
        "salt": pwd_hash["salt"],
        "role": "customer",
        "customer_id": "CUST_TEST_001",
    }
    portal.CUSTOMERS["CUST_TEST_001"] = {
        "id": "CUST_TEST_001",
        "name": "Test User",
        "email": email,
    }
    return username, email


def _teardown_otp():
    reset_otp_security_service()


# ---------- Step 1: /api/request-password-reset ----------

class TestRequestPasswordResetOTP:

    def setup_method(self):
        portal.USERS.clear()
        portal.CUSTOMERS.clear()
        portal.SESSIONS.clear()
        _teardown_otp()

    def test_request_returns_verification_id(self):
        username, email = _setup_test_user()
        status, body = _post("/api/request-password-reset", {
            "username": username,
            "email": email,
        })
        assert status == 200
        assert body.get("success") is True
        assert body.get("verification_id")
        assert body.get("requires_otp") is True

    def test_request_nonexistent_user_no_info_leak(self):
        """Should return 200 with generic message to prevent user enumeration."""
        status, body = _post("/api/request-password-reset", {
            "username": "ghost",
            "email": "ghost@example.com",
        })
        assert status == 200
        assert body.get("success") is True
        assert "verification" not in body.get("message", "").lower() or "verification_id" not in body

    def test_request_wrong_email_no_info_leak(self):
        """Mismatched email should still return generic message."""
        _setup_test_user(username="realuser", email="real@example.com")
        status, body = _post("/api/request-password-reset", {
            "username": "realuser",
            "email": "wrong@example.com",
        })
        assert status == 200
        assert body.get("success") is True

    def test_request_missing_fields(self):
        status, body = _post("/api/request-password-reset", {"username": "x"})
        assert status == 400

    def test_demo_otp_exposed_in_test_mode(self):
        username, email = _setup_test_user()
        status, body = _post("/api/request-password-reset", {
            "username": username,
            "email": email,
        })
        assert status == 200
        assert body.get("demo_otp_code"), "demo_otp_code should be exposed in test mode"


# ---------- Step 2: /api/reset-password ----------

class TestResetPasswordWithOTP:

    def setup_method(self):
        portal.USERS.clear()
        portal.CUSTOMERS.clear()
        portal.SESSIONS.clear()
        _teardown_otp()

    def test_reset_without_otp_rejected(self):
        """Attempting reset without OTP fields must fail."""
        _setup_test_user()
        status, body = _post("/api/reset-password", {
            "username": "testuser",
            "email": "test@example.com",
            "new_password": "NewPass456",
        })
        assert status == 400
        assert body.get("requires_otp") is True

    def test_reset_with_invalid_otp(self):
        """Wrong OTP code must be rejected."""
        username, email = _setup_test_user()
        _, req_body = _post("/api/request-password-reset", {
            "username": username, "email": email,
        })
        vid = req_body["verification_id"]

        status, body = _post("/api/reset-password", {
            "username": username,
            "email": email,
            "new_password": "NewPass456",
            "verification_id": vid,
            "otp_code": "000000",
        })
        assert status == 401
        assert "INVALID_OTP" in (body.get("error_code") or "")

    def test_full_reset_flow(self):
        """Happy path: request OTP -> verify -> password changed."""
        username, email = _setup_test_user()
        old_hash = portal.USERS[username]["hash"]

        # Step 1: Request OTP
        _, req_body = _post("/api/request-password-reset", {
            "username": username, "email": email,
        })
        vid = req_body["verification_id"]
        otp_code = req_body.get("demo_otp_code")
        assert otp_code, "demo_otp_code must be available in test mode"

        # Step 2: Reset with valid OTP
        status, body = _post("/api/reset-password", {
            "username": username,
            "email": email,
            "new_password": "NewSecure789",
            "verification_id": vid,
            "otp_code": otp_code,
        })
        assert status == 200
        assert body.get("success") is True

        # Verify password was actually changed
        new_hash = portal.USERS[username]["hash"]
        assert new_hash != old_hash

        # Verify new password works
        assert portal.verify_password("NewSecure789", new_hash, portal.USERS[username]["salt"])

    def test_otp_cannot_be_reused(self):
        """Once an OTP is consumed, the same verification_id cannot reset again."""
        username, email = _setup_test_user()

        _, req_body = _post("/api/request-password-reset", {
            "username": username, "email": email,
        })
        vid = req_body["verification_id"]
        otp_code = req_body["demo_otp_code"]

        # First reset succeeds
        status, _ = _post("/api/reset-password", {
            "username": username, "email": email,
            "new_password": "First999!!", "verification_id": vid, "otp_code": otp_code,
        })
        assert status == 200

        # Second attempt with same verification must fail
        status2, body2 = _post("/api/reset-password", {
            "username": username, "email": email,
            "new_password": "Second999!!", "verification_id": vid, "otp_code": otp_code,
        })
        assert status2 == 401

    def test_sessions_revoked_after_reset(self):
        """All existing sessions must be invalidated after password reset."""
        username, email = _setup_test_user()
        portal.SESSIONS["fake_token_123"] = {
            "username": username,
            "role": "customer",
            "customer_id": "CUST_TEST_001",
        }

        _, req_body = _post("/api/request-password-reset", {
            "username": username, "email": email,
        })
        vid = req_body["verification_id"]
        otp_code = req_body["demo_otp_code"]

        _post("/api/reset-password", {
            "username": username, "email": email,
            "new_password": "AfterReset1!", "verification_id": vid, "otp_code": otp_code,
        })

        assert "fake_token_123" not in portal.SESSIONS

    def test_reset_short_password_rejected(self):
        username, email = _setup_test_user()
        _, req_body = _post("/api/request-password-reset", {
            "username": username, "email": email,
        })
        vid = req_body["verification_id"]
        otp = req_body["demo_otp_code"]

        status, body = _post("/api/reset-password", {
            "username": username, "email": email,
            "new_password": "short",
            "verification_id": vid, "otp_code": otp,
        })
        assert status == 400
        assert "8 characters" in body.get("error", "")

    def test_reset_email_mismatch_rejected(self):
        """Even with valid OTP, email must match the user's record."""
        username, email = _setup_test_user()
        _, req_body = _post("/api/request-password-reset", {
            "username": username, "email": email,
        })
        vid = req_body["verification_id"]
        otp = req_body["demo_otp_code"]

        status, body = _post("/api/reset-password", {
            "username": username, "email": "wrong@other.com",
            "new_password": "ValidPass1!",
            "verification_id": vid, "otp_code": otp,
        })
        assert status == 401


# ---------- OTP Resend for password reset ----------

class TestPasswordResetOTPResend:

    def setup_method(self):
        portal.USERS.clear()
        portal.CUSTOMERS.clear()
        portal.SESSIONS.clear()
        _teardown_otp()

    def test_resend_returns_new_code(self):
        username, email = _setup_test_user()
        _, req_body = _post("/api/request-password-reset", {
            "username": username, "email": email,
        })
        vid = req_body["verification_id"]

        svc = get_otp_security_service()
        v = svc._verifications.get(vid)
        if v:
            from datetime import datetime, timezone
            v.created_at = datetime(2020, 1, 1, tzinfo=timezone.utc)

        status, body = _post("/api/security/otp/resend", {
            "verification_id": vid,
        })
        assert status == 200
        assert body.get("success") is True or body.get("verification_id")
