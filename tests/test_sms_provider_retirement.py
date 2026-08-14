"""Regression tests for the Telesign SMS provider retirement.

Telesign was decommissioned; OTP/verification SMS traffic must never be
routed to it again, even when stale ``TELESIGN_*`` credentials or a stale
``SMS_PROVIDER=telesign`` setting linger in a deployment environment. These
tests pin the replacement behavior: Infobip is auto-detected first, retired
provider names re-route gracefully, and no Telesign code path remains.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

import services.notification_service as ns


API_KEY = "test-infobip-key-123"
BASE_URL = "https://abc123.api.infobip.com"


@pytest.fixture(autouse=True)
def _live_delivery_env(monkeypatch):
    """Force live (non-mock) provider selection and clear SMS provider env."""
    monkeypatch.setenv("PHINS_TEST_MODE", "false")
    monkeypatch.setenv("PHINS_USE_MOCK_NOTIFICATIONS", "false")
    for var in (
        "SMS_PROVIDER",
        "INFOBIP_API_KEY",
        "INFOBIP_BASE_URL",
        "TELESIGN_CUSTOMER_ID",
        "TELESIGN_API_KEY",
        "TWILIO_ACCOUNT_SID",
        "TWILIO_AUTH_TOKEN",
        "TWILIO_FROM_NUMBER",
        "VONAGE_API_KEY",
        "VONAGE_API_SECRET",
        "MESSAGEBIRD_API_KEY",
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(ns.NotificationConfig, "SMS_PROVIDER", "twilio")
    monkeypatch.setattr(ns.NotificationConfig, "INFOBIP_API_KEY", "")
    monkeypatch.setattr(ns.NotificationConfig, "INFOBIP_BASE_URL", "")
    monkeypatch.setattr(ns.NotificationConfig, "TWILIO_ACCOUNT_SID", "")
    monkeypatch.setattr(ns.NotificationConfig, "TWILIO_AUTH_TOKEN", "")
    monkeypatch.setattr(ns.NotificationConfig, "TWILIO_FROM_NUMBER", "")
    monkeypatch.setattr(ns.NotificationConfig, "VONAGE_API_KEY", "")
    monkeypatch.setattr(ns.NotificationConfig, "VONAGE_API_SECRET", "")
    monkeypatch.setattr(ns.NotificationConfig, "MESSAGEBIRD_API_KEY", "")
    yield monkeypatch


def _configure_infobip(monkeypatch):
    monkeypatch.setenv("INFOBIP_API_KEY", API_KEY)
    monkeypatch.setenv("INFOBIP_BASE_URL", BASE_URL)


def test_telesign_provider_class_is_removed():
    assert not hasattr(ns, "TelesignSMSProvider")
    assert "TelesignSMSProvider" not in ns.__all__
    assert "telesign" not in ns._SMS_PROVIDER_TYPES
    assert "telesign" in ns._RETIRED_SMS_PROVIDERS


def test_telesign_never_reported_configured():
    """Stale TELESIGN_* env vars must not make telesign look deliverable."""
    import os
    os.environ["TELESIGN_CUSTOMER_ID"] = "CUST-STALE"
    os.environ["TELESIGN_API_KEY"] = "stale-key"
    try:
        assert ns._sms_provider_is_configured("telesign") is False
        assert ns._detect_configured_sms_provider() is None
    finally:
        del os.environ["TELESIGN_CUSTOMER_ID"]
        del os.environ["TELESIGN_API_KEY"]


def test_stale_telesign_creds_do_not_shadow_infobip(_live_delivery_env):
    """The outage scenario: Telesign creds still present, Infobip configured.

    Before the retirement, auto-detection preferred Telesign and OTP SMS
    silently went to the dead account. Infobip must win now.
    """
    monkeypatch = _live_delivery_env
    monkeypatch.setenv("TELESIGN_CUSTOMER_ID", "CUST-STALE")
    monkeypatch.setenv("TELESIGN_API_KEY", "stale-key")
    _configure_infobip(monkeypatch)

    assert ns._detect_configured_sms_provider() == "infobip"
    assert ns.get_active_sms_provider_type() == "infobip"

    service = ns.create_notification_service(use_mock=False)
    assert isinstance(service._sms_provider, ns.InfobipSMSProvider)


def test_sms_provider_telesign_setting_reroutes_to_infobip(_live_delivery_env):
    """SMS_PROVIDER=telesign left in the environment must re-route, not break."""
    monkeypatch = _live_delivery_env
    monkeypatch.setattr(ns.NotificationConfig, "SMS_PROVIDER", "telesign")
    _configure_infobip(monkeypatch)

    assert ns._select_sms_provider_type() == "infobip"
    assert ns.get_active_sms_provider_type() == "infobip"

    service = ns.create_notification_service(use_mock=False)
    assert isinstance(service._sms_provider, ns.InfobipSMSProvider)


def test_sms_provider_telesign_with_nothing_else_reports_noop(_live_delivery_env):
    monkeypatch = _live_delivery_env
    monkeypatch.setattr(ns.NotificationConfig, "SMS_PROVIDER", "telesign")

    assert ns.get_active_sms_provider_type() == "noop"

    diagnostics = ns.get_notification_provider_diagnostics()
    assert diagnostics["sms"]["will_deliver"] is False
    recommendation = diagnostics.get("recommendation") or ""
    assert "retired" in recommendation
    assert "infobip" in recommendation.lower()


def test_diagnostics_no_longer_report_telesign(_live_delivery_env):
    _configure_infobip(_live_delivery_env)
    diagnostics = ns.get_notification_provider_diagnostics()
    assert "telesign" not in diagnostics["sms"]["providers"]
    assert diagnostics["sms"]["providers"]["infobip"]["configured"] is True


def test_infobip_auto_selected_when_provider_left_at_twilio_default(_live_delivery_env):
    """Infobip creds present but SMS_PROVIDER left at 'twilio' -> auto-select."""
    _configure_infobip(_live_delivery_env)

    assert ns.get_active_sms_provider_type() == "infobip"

    diagnostics = ns.get_notification_provider_diagnostics()
    sms = diagnostics["sms"]
    assert sms["configured_provider"] == "twilio"
    assert sms["active_provider"] == "infobip"
    assert sms["will_deliver"] is True
    assert sms["auto_selected"] is True


def test_sms_stays_noop_when_no_provider_configured():
    """No SMS provider configured at all -> 'noop' (no false fallback)."""
    assert ns.get_active_sms_provider_type() == "noop"

    diagnostics = ns.get_notification_provider_diagnostics()
    assert diagnostics["sms"]["will_deliver"] is False
    assert diagnostics["sms"]["auto_selected"] is False


def test_otp_sms_send_goes_through_infobip(_live_delivery_env):
    """End-to-end: an OTP SMS send must hit the Infobip endpoint."""
    _configure_infobip(_live_delivery_env)
    captured = {}

    def fake_urlopen(req, timeout=30, allowed_schemes=("https",)):
        captured["url"] = req.full_url
        captured["auth"] = req.get_header("Authorization")

        class _Resp:
            status = 200

            def read(self):
                import json
                return json.dumps({"messages": [{
                    "messageId": "ib-otp-1",
                    "status": {"groupName": "PENDING"},
                }]}).encode("utf-8")

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        return _Resp()

    service = ns.create_notification_service(use_mock=False)
    with patch.object(ns, "validated_urlopen", side_effect=fake_urlopen):
        ok, message_id, error = service._sms_provider.send(
            to="+15551234567", message="PHINS verification code: 654321"
        )

    assert ok is True and error is None
    assert message_id == "ib-otp-1"
    assert captured["url"] == f"{BASE_URL}/sms/2/text/advanced"
    assert captured["auth"] == f"App {API_KEY}"


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
