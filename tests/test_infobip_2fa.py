"""Infobip 2FA PIN API: create application, send PIN, verify PIN."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

import services.infobip_2fa_service as twofa
import services.notification_service as ns
from services.otp_security_service import OTPPurpose, get_otp_security_service


API_KEY = "test-infobip-key-123"
BASE_URL = "https://abc123.api.infobip.com"


class _FakeResponse:
    def __init__(self, status=200, body=None):
        self.status = status
        self._body = json.dumps(body if body is not None else {}).encode("utf-8")

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


@pytest.fixture
def infobip_env(monkeypatch):
    monkeypatch.setenv("INFOBIP_API_KEY", API_KEY)
    monkeypatch.setenv("INFOBIP_BASE_URL", BASE_URL)
    monkeypatch.setenv("INFOBIP_SMS_SENDER", "ServiceSMS")
    monkeypatch.setenv("INFOBIP_2FA_ENABLED", "true")
    monkeypatch.setenv("INFOBIP_2FA_APPLICATION_ID", "app-phins")
    monkeypatch.setenv("INFOBIP_2FA_MESSAGE_ID", "msg-phins")
    twofa.reset_infobip_2fa_cache()
    yield monkeypatch
    twofa.reset_infobip_2fa_cache()


def test_send_2fa_pin_matches_infobip_curl(infobip_env):
    captured = {}

    def fake_urlopen(req, timeout=30, allowed_schemes=("https",)):
        captured["url"] = req.full_url
        captured["auth"] = req.get_header("Authorization")
        captured["content_type"] = req.get_header("Content-type")
        captured["accept"] = req.get_header("Accept")
        captured["payload"] = json.loads(req.data.decode("utf-8"))
        return _FakeResponse(200, {
            "pinId": "pin-abc",
            "to": "972500000000",
            "smsStatus": "MESSAGE_SENT",
        })

    with patch.object(ns, "validated_urlopen", side_effect=fake_urlopen):
        ok, pin_id, error = twofa.send_2fa_pin("972500000000")

    assert ok is True and error is None
    assert pin_id == "pin-abc"
    assert captured["url"] == f"{BASE_URL}/2fa/2/pin"
    assert captured["auth"] == f"App {API_KEY}"
    assert captured["content_type"] == "application/json"
    assert captured["accept"] == "application/json"
    assert captured["payload"] == {
        "applicationId": "app-phins",
        "messageId": "msg-phins",
        "from": "ServiceSMS",
        "to": "972500000000",
    }


def test_verify_2fa_pin_matches_infobip_curl(infobip_env):
    captured = {}

    def fake_urlopen(req, timeout=30, allowed_schemes=("https",)):
        captured["url"] = req.full_url
        captured["payload"] = json.loads(req.data.decode("utf-8"))
        return _FakeResponse(200, {"pinId": "pin-abc", "verified": True})

    with patch.object(ns, "validated_urlopen", side_effect=fake_urlopen):
        ok, error, details = twofa.verify_2fa_pin("pin-abc", "440906")

    assert ok is True and error is None
    assert details["verified"] is True
    assert captured["url"] == f"{BASE_URL}/2fa/2/pin/pin-abc/verify"
    assert captured["payload"] == {"pin": "440906"}


def test_ensure_creates_application_and_message_when_missing(infobip_env):
    infobip_env.delenv("INFOBIP_2FA_APPLICATION_ID")
    infobip_env.delenv("INFOBIP_2FA_MESSAGE_ID")
    twofa.reset_infobip_2fa_cache()
    calls = []

    def fake_urlopen(req, timeout=30, allowed_schemes=("https",)):
        path = req.full_url.replace(BASE_URL, "")
        body = json.loads(req.data.decode("utf-8")) if req.data else None
        calls.append((req.get_method(), path, body))
        if path == "/2fa/2/applications" and req.get_method() == "GET":
            return _FakeResponse(200, [])
        if path == "/2fa/2/applications" and req.get_method() == "POST":
            assert body["name"] == "PHINS OTP"
            assert body["enabled"] is True
            assert body["configuration"]["pinAttempts"] == 10
            assert body["configuration"]["allowMultiplePinVerifications"] is True
            assert body["configuration"]["pinTimeToLive"] == "15m"
            return _FakeResponse(200, {"applicationId": "created-app"})
        if path == "/2fa/2/applications/created-app/messages" and req.get_method() == "GET":
            return _FakeResponse(200, [])
        if path == "/2fa/2/applications/created-app/messages" and req.get_method() == "POST":
            assert "{{pin}}" in body["messageText"]
            assert body["senderId"] == "ServiceSMS"
            assert body["pinLength"] == 6
            return _FakeResponse(200, {"messageId": "created-msg"})
        raise AssertionError(f"unexpected {req.get_method()} {path}")

    with patch.object(ns, "validated_urlopen", side_effect=fake_urlopen):
        app_id, message_id, error = twofa.ensure_2fa_ids()

    assert error is None
    assert app_id == "created-app"
    assert message_id == "created-msg"
    methods = [item[0] for item in calls]
    assert methods == ["GET", "POST", "GET", "POST"]


def test_ensure_reuses_existing_2fa_test_application(infobip_env):
    infobip_env.delenv("INFOBIP_2FA_APPLICATION_ID")
    infobip_env.delenv("INFOBIP_2FA_MESSAGE_ID")
    twofa.reset_infobip_2fa_cache()

    def fake_urlopen(req, timeout=30, allowed_schemes=("https",)):
        path = req.full_url.replace(BASE_URL, "")
        if path == "/2fa/2/applications":
            return _FakeResponse(200, [{
                "applicationId": "legacy-app",
                "name": "2fa test application",
                "enabled": True,
            }])
        if path == "/2fa/2/applications/legacy-app/messages":
            return _FakeResponse(200, [{
                "messageId": "legacy-msg",
                "messageText": "Your pin is {{pin}}",
                "senderId": "ServiceSMS",
            }])
        raise AssertionError(path)

    with patch.object(ns, "validated_urlopen", side_effect=fake_urlopen):
        app_id, message_id, error = twofa.ensure_2fa_ids()

    assert error is None
    assert app_id == "legacy-app"
    assert message_id == "legacy-msg"


def test_otp_verify_uses_infobip_when_pin_id_attached(infobip_env):
    service = get_otp_security_service()
    created = service.create_otp_verification(
        user_type="applicant",
        user_id="CHAPP-2FA",
        email="twofa@example.com",
        purpose=OTPPurpose.PHONE_VERIFICATION,
        phone="+972500000000",
        delivery_channel="sms",
    )
    assert created.success
    vid = created.verification_id
    local_code = created.data["otp_code"]
    assert service.attach_external_pin(vid, "pin-live")

    with patch.object(twofa, "verify_2fa_pin", return_value=(True, None, {"verified": True})):
        result = service.verify_otp(vid, "999111")
    assert result.success is True
    # Local hash is not the Infobip PIN and must not be required.
    assert local_code != "999111"


def test_otp_verify_rejects_wrong_infobip_pin(infobip_env):
    service = get_otp_security_service()
    created = service.create_otp_verification(
        user_type="applicant",
        user_id="CHAPP-2FA-BAD",
        email="twofa.bad@example.com",
        purpose=OTPPurpose.PHONE_VERIFICATION,
        phone="+972500000000",
        delivery_channel="sms",
    )
    service.attach_external_pin(created.verification_id, "pin-live")
    with patch.object(
        twofa, "verify_2fa_pin",
        return_value=(False, "Infobip 2FA PIN was not verified", {"verified": False}),
    ):
        result = service.verify_otp(created.verification_id, created.data["otp_code"])
    assert result.success is False
    assert result.error_code == "INVALID_OTP"


def test_send_otp_sms_uses_2fa_when_live(monkeypatch):
    monkeypatch.setenv("PHINS_TEST_MODE", "false")
    monkeypatch.setenv("PHINS_USE_MOCK_NOTIFICATIONS", "false")
    monkeypatch.setenv("INFOBIP_2FA_ENABLED", "true")

    from web_portal import api_extensions

    with patch.object(ns, "should_use_mock_notifications", return_value=False), \
         patch.object(twofa, "infobip_2fa_enabled", return_value=True), \
         patch.object(twofa, "send_2fa_pin", return_value=(True, "pin-xyz", None)):
        ok, error = api_extensions._send_otp_sms(
            phone="+972500000000",
            otp_code="123456",
            expiry_seconds=300,
            purpose="phone_verification",
            verification_id=None,
        )
    assert ok is True and error is None


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
