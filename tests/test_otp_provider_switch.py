"""Infobip (default) vs Didit OTP delivery switch.

PHINS still mints a local unused code when ``OTP_PROVIDER=didit`` so
existing ``if otp_code:`` send gates fire. Didit mints the real code;
verify must call Didit check, never the local hash. Demo OTP exposure
is refused because PHINS never sees Didit's code.
"""

from __future__ import annotations

import pytest

from services.didit_service import DiditResult, set_didit_service_for_tests
from services.otp_provider import (
    didit_phone_channel,
    is_didit_otp,
    resolve_otp_provider,
    send_didit_otp,
    verify_didit_otp,
)
from services.otp_security_service import OTPPurpose, get_otp_security_service
import web_portal.api_extensions as api_extensions


def _result(ok=True, approved=None, error=None, endpoint="email/send"):
    return DiditResult(
        ok=ok,
        status_code=200 if ok else 400,
        request_id="req-1",
        payload={},
        error=error,
        endpoint=endpoint,
        approved=approved,
    )


class _FakeDidit:
    def __init__(self, enabled=True):
        self.enabled = enabled
        self.calls = []

    def is_enabled(self):
        return self.enabled

    def email_send(self, email, **fields):
        self.calls.append(("email_send", email, fields))
        return _result(endpoint="email/send")

    def phone_send(self, phone, channel=None, **fields):
        self.calls.append(("phone_send", phone, channel, fields))
        return _result(endpoint="phone/send")

    def email_check(self, email, code, **fields):
        self.calls.append(("email_check", email, code, fields))
        accepted = str(code) == "654321"
        return _result(
            ok=accepted,
            approved=accepted,
            error=None if accepted else "Invalid verification code",
            endpoint="email/check",
        )

    def phone_check(self, phone, code, **fields):
        self.calls.append(("phone_check", phone, code, fields))
        accepted = str(code) == "654321"
        return _result(
            ok=accepted,
            approved=accepted,
            error=None if accepted else "Invalid verification code",
            endpoint="phone/check",
        )


@pytest.fixture
def fake_didit():
    svc = _FakeDidit()
    set_didit_service_for_tests(svc)
    yield svc
    set_didit_service_for_tests(None)


def test_resolve_otp_provider_defaults_to_infobip(monkeypatch):
    monkeypatch.delenv("OTP_PROVIDER", raising=False)
    assert resolve_otp_provider() == "infobip"
    assert is_didit_otp() is False


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("didit", "didit"),
        ("Didit.me", "didit"),
        ("didit_me", "didit"),
        ("INFOBIP", "infobip"),
        ("local", "infobip"),
        ("unknown", "infobip"),
    ],
)
def test_resolve_otp_provider_aliases(monkeypatch, raw, expected):
    monkeypatch.setenv("OTP_PROVIDER", raw)
    assert resolve_otp_provider() == expected


def test_didit_phone_channel_override(monkeypatch):
    monkeypatch.delenv("OTP_DIDIT_PHONE_CHANNEL", raising=False)
    assert didit_phone_channel("sms") == "sms"
    assert didit_phone_channel("whatsapp") == "whatsapp"
    monkeypatch.setenv("OTP_DIDIT_PHONE_CHANNEL", "telegram")
    assert didit_phone_channel("sms") == "telegram"


def test_send_didit_otp_email_and_sms(fake_didit):
    ok, err = send_didit_otp(
        delivery_channel="email",
        email="user@example.com",
        phone=None,
        vendor_data="OTP_1",
    )
    assert ok is True
    assert err is None
    assert fake_didit.calls[0][0] == "email_send"
    assert fake_didit.calls[0][2]["vendor_data"] == "OTP_1"

    ok, err = send_didit_otp(
        delivery_channel="sms",
        email=None,
        phone="+15551234567",
    )
    assert ok is True
    assert fake_didit.calls[-1][0] == "phone_send"
    assert fake_didit.calls[-1][2] == "sms"


def test_send_didit_otp_whatsapp_and_both(fake_didit):
    ok, err = send_didit_otp(
        delivery_channel="whatsapp",
        email=None,
        phone="+15551234567",
    )
    assert ok is True
    assert fake_didit.calls[-1][2] == "whatsapp"

    ok, err = send_didit_otp(
        delivery_channel="both",
        email="user@example.com",
        phone="+15551234567",
        vendor_data="OTP_BOTH",
    )
    assert ok is True
    kinds = [call[0] for call in fake_didit.calls]
    assert "email_send" in kinds
    assert kinds.count("phone_send") >= 1


def test_send_didit_otp_fails_when_disabled(fake_didit):
    fake_didit.enabled = False
    ok, err = send_didit_otp(
        delivery_channel="email",
        email="user@example.com",
        phone=None,
    )
    assert ok is False
    assert "DIDIT_API_KEY" in (err or "")


def test_verify_didit_otp_email_accepts_vendor_code(fake_didit):
    ok, err = verify_didit_otp(
        delivery_channel="email",
        email="user@example.com",
        phone=None,
        code="654321",
    )
    assert ok is True
    assert err is None

    ok, err = verify_didit_otp(
        delivery_channel="email",
        email="user@example.com",
        phone=None,
        code="000000",
    )
    assert ok is False
    assert err


def test_create_stamps_delivery_provider(monkeypatch):
    monkeypatch.delenv("OTP_PROVIDER", raising=False)
    service = get_otp_security_service()
    result = service.create_otp_verification(
        user_type="customer",
        user_id="switch-infobip@example.com",
        email="switch-infobip@example.com",
        purpose=OTPPurpose.LOGIN,
        ip_address="127.0.0.1",
    )
    assert result.success
    assert result.data["delivery_provider"] == "infobip"

    monkeypatch.setenv("OTP_PROVIDER", "didit")
    result = service.create_otp_verification(
        user_type="customer",
        user_id="switch-didit@example.com",
        email="switch-didit@example.com",
        purpose=OTPPurpose.LOGIN,
        ip_address="127.0.0.1",
    )
    assert result.success
    assert result.data["delivery_provider"] == "didit"
    assert result.data.get("otp_code")  # still minted so send gates fire


def test_verify_uses_didit_not_local_hash(monkeypatch, fake_didit):
    monkeypatch.setenv("OTP_PROVIDER", "didit")
    service = get_otp_security_service()
    created = service.create_otp_verification(
        user_type="customer",
        user_id="didit-verify@example.com",
        email="didit-verify@example.com",
        purpose=OTPPurpose.LOGIN,
        ip_address="127.0.0.1",
    )
    local_code = created.data["otp_code"]
    vid = created.verification_id

    rejected = service.verify_otp(vid, local_code, ip_address="127.0.0.1")
    assert rejected.success is False
    assert rejected.error_code == "INVALID_OTP"

    accepted = service.verify_otp(vid, "654321", ip_address="127.0.0.1")
    assert accepted.success is True
    assert any(call[0] == "email_check" for call in fake_didit.calls)


def test_send_via_channel_uses_didit_when_selected(monkeypatch, fake_didit):
    monkeypatch.setenv("OTP_PROVIDER", "didit")
    email_called = {"n": 0}

    def _should_not_use_infobip(**_kwargs):
        email_called["n"] += 1
        return True, None

    monkeypatch.setattr(api_extensions, "_send_otp_email", _should_not_use_infobip)
    ok, err = api_extensions._send_otp_via_channel(
        delivery_channel="email",
        otp_code="111111",
        expiry_seconds=300,
        purpose="login",
        email="didit-send@example.com",
        verification_id="OTP_SWITCH",
    )
    assert ok is True
    assert err is None
    assert email_called["n"] == 0
    assert fake_didit.calls[0][0] == "email_send"


def test_send_email_direct_uses_didit_when_selected(monkeypatch, fake_didit):
    monkeypatch.setenv("OTP_PROVIDER", "didit")
    ok, err = api_extensions._send_otp_email(
        email="supplier-reset@example.com",
        otp_code="111111",
        expiry_seconds=300,
        purpose="supplier_password_reset",
        verification_id="OTP_SUP",
    )
    assert ok is True
    assert fake_didit.calls[0][0] == "email_send"


def test_demo_otp_not_exposed_when_didit(monkeypatch):
    monkeypatch.setenv("OTP_PROVIDER", "didit")
    monkeypatch.setattr(api_extensions, "EXPOSE_DEMO_OTP", True)
    monkeypatch.setattr(api_extensions, "PHINS_TEST_MODE", True)
    raw = {
        "success": True,
        "data": {
            "verification_id": "OTP_HIDE",
            "otp_code": "123456",
            "delivery_provider": "didit",
            "masked_email": "d***@example.com",
        },
    }
    sanitized, otp_code, _context = api_extensions._prepare_otp_client_response(raw)
    assert otp_code == "123456"
    assert "demo_otp_code" not in sanitized
    assert sanitized.get("delivery_provider") == "didit"


def test_registration_fallback_refuses_didit(monkeypatch):
    monkeypatch.setenv("OTP_PROVIDER", "didit")
    monkeypatch.setattr(api_extensions, "EXPOSE_DEMO_OTP", False)
    monkeypatch.setattr(api_extensions, "PHINS_TEST_MODE", False)
    monkeypatch.setenv("PHINS_ENVIRONMENT", "development")
    response = {}
    applied = api_extensions._apply_registration_demo_otp_fallback(
        response, "999888", "registration"
    )
    assert applied is False
    assert "demo_otp_code" not in response


def test_handle_otp_request_didit_path(monkeypatch, fake_didit):
    monkeypatch.setenv("OTP_PROVIDER", "didit")
    monkeypatch.setattr(api_extensions, "EXPOSE_DEMO_OTP", True)
    monkeypatch.setattr(api_extensions, "PHINS_TEST_MODE", True)

    status, payload = api_extensions.handle_otp_request(
        client_ip="127.0.0.1",
        body_data={
            "email": "didit-route@example.com",
            "purpose": "login",
        },
    )
    assert status == 200, payload
    assert payload.get("success") is True
    assert payload.get("notification_sent") is True
    assert "demo_otp_code" not in payload
    assert payload.get("delivery_provider") == "didit"
    assert any(call[0] == "email_send" for call in fake_didit.calls)

    vid = payload.get("verification_id")
    status, verified = api_extensions.handle_otp_verify(
        client_ip="127.0.0.1",
        body_data={"verification_id": vid, "otp_code": "654321"},
    )
    assert status == 200, verified
    assert verified.get("success") is True


def test_infobip_default_still_uses_notification_senders(monkeypatch):
    monkeypatch.delenv("OTP_PROVIDER", raising=False)
    sent = {"email": False}

    def _fake_email(**_kwargs):
        sent["email"] = True
        return True, None

    monkeypatch.setattr(api_extensions, "_send_otp_email", _fake_email)
    ok, err = api_extensions._send_otp_via_channel(
        delivery_channel="email",
        otp_code="123456",
        expiry_seconds=300,
        purpose="login",
        email="keep-infobip@example.com",
    )
    assert ok is True
    assert err is None
    assert sent["email"] is True
