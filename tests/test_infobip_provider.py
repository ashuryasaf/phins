"""
Unit tests for the Infobip notification provider (email + SMS).

Infobip authenticates with ``Authorization: App <INFOBIP_API_KEY>`` against an
account-specific base URL (``INFOBIP_BASE_URL``). These tests fake the HTTPS
layer, so they verify request shape (URL, auth header, payload), success and
rejection handling, provider selection/auto-detection, and diagnostics -
without any live network traffic.
"""

import io
import json
from unittest.mock import patch

import pytest

import services.notification_service as ns


API_KEY = "test-infobip-key-123"
BASE_URL = "https://abc123.api.infobip.com"


class _FakeResponse:
    def __init__(self, status=200, body=None):
        self.status = status
        self._body = json.dumps(body or {}).encode("utf-8")

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
    monkeypatch.setenv("INFOBIP_FROM_ADDRESS", "noreply@phins.ai")
    # Isolate from any other provider config that might exist in the env.
    for var in ("SENDGRID_API_KEY", "MAILGUN_API_KEY", "MAILGUN_DOMAIN",
                "RESEND_API_KEY", "ACTIVE_NOTIFICATIONS_API_KEY",
                "PINGRAM_API_KEY", "NOTIFICATIONAPI_API_KEY", "EMAIL_PROVIDER"):
        monkeypatch.delenv(var, raising=False)
    yield monkeypatch


def _email_success_body():
    return {"messages": [{"to": "a@b.co", "messageId": "ib-msg-1",
                          "status": {"groupName": "PENDING"}}]}


def test_infobip_email_send_builds_correct_request(infobip_env):
    captured = {}

    def fake_urlopen(req, timeout=30, allowed_schemes=("https",)):
        captured["url"] = req.full_url
        captured["auth"] = req.get_header("Authorization")
        captured["content_type"] = req.get_header("Content-type")
        captured["body"] = req.data.decode("utf-8")
        return _FakeResponse(200, _email_success_body())

    with patch.object(ns, "validated_urlopen", side_effect=fake_urlopen):
        ok, message_id, error = ns.InfobipEmailProvider().send(
            to="applicant@example.com",
            subject="Your PHINS verification code",
            body="Code: 123456",
            html_body="<b>Code: 123456</b>",
        )

    assert ok is True and error is None
    assert message_id == "ib-msg-1"
    assert captured["url"] == f"{BASE_URL}/email/3/send"
    assert captured["auth"] == f"App {API_KEY}"
    assert captured["content_type"].startswith("multipart/form-data; boundary=")
    for expected in ('name="from"', 'name="to"', 'name="subject"',
                     'name="text"', 'name="html"', "applicant@example.com",
                     "Code: 123456"):
        assert expected in captured["body"]


def test_infobip_email_rejection_is_reported(infobip_env):
    rejected = {"messages": [{"messageId": "ib-msg-2", "status": {
        "groupName": "REJECTED", "description": "Sender domain not verified"}}]}
    with patch.object(ns, "validated_urlopen",
                      return_value=_FakeResponse(200, rejected)):
        ok, _, error = ns.InfobipEmailProvider().send(
            to="a@b.co", subject="s", body="b")
    assert ok is False
    assert "Sender domain not verified" in error


def test_infobip_email_requires_key_and_base_url(monkeypatch):
    monkeypatch.delenv("INFOBIP_API_KEY", raising=False)
    monkeypatch.delenv("INFOBIP_BASE_URL", raising=False)
    ok, _, error = ns.InfobipEmailProvider().send(to="a@b.co", subject="s", body="b")
    assert ok is False
    assert "INFOBIP_API_KEY" in error and "INFOBIP_BASE_URL" in error
    assert "portal.infobip.com" in error


def test_infobip_base_url_scheme_is_normalized(infobip_env):
    infobip_env.setenv("INFOBIP_BASE_URL", "abc123.api.infobip.com/")
    api_key, base_url, error = ns._infobip_credentials()
    assert error is None
    assert base_url == "https://abc123.api.infobip.com"


def test_infobip_sms_send_builds_correct_request(infobip_env):
    infobip_env.setenv("INFOBIP_SMS_SENDER", "PHINS")
    captured = {}

    def fake_urlopen(req, timeout=30, allowed_schemes=("https",)):
        captured["url"] = req.full_url
        captured["auth"] = req.get_header("Authorization")
        captured["payload"] = json.loads(req.data.decode("utf-8"))
        return _FakeResponse(200, {"messages": [{
            "messageId": "ib-sms-1", "status": {"groupName": "PENDING"}}]})

    with patch.object(ns, "validated_urlopen", side_effect=fake_urlopen):
        ok, message_id, error = ns.InfobipSMSProvider().send(
            to="+15550100", message="PHINS code: 123456")

    assert ok is True and error is None
    assert message_id == "ib-sms-1"
    assert captured["url"] == f"{BASE_URL}/sms/2/text/advanced"
    assert captured["auth"] == f"App {API_KEY}"
    msg = captured["payload"]["messages"][0]
    assert msg["from"] == "PHINS"
    assert msg["destinations"] == [{"to": "15550100"}]
    assert msg["text"] == "PHINS code: 123456"


def test_infobip_sms_strips_plus_and_punctuation(infobip_env):
    """Infobip docs want international digits without a leading '+'."""
    captured = {}

    def fake_urlopen(req, timeout=30, allowed_schemes=("https",)):
        captured["payload"] = json.loads(req.data.decode("utf-8"))
        return _FakeResponse(200, {"messages": [{
            "messageId": "ib-sms-digits", "status": {"groupName": "PENDING"}}]})

    with patch.object(ns, "validated_urlopen", side_effect=fake_urlopen):
        ok, _, error = ns.InfobipSMSProvider().send(
            to="+1 (555) 123-4567", message="code")

    assert ok is True and error is None
    assert captured["payload"]["messages"][0]["destinations"] == [{"to": "15551234567"}]


def test_infobip_sms_requires_configuration(monkeypatch):
    monkeypatch.delenv("INFOBIP_API_KEY", raising=False)
    monkeypatch.delenv("INFOBIP_BASE_URL", raising=False)
    ok, _, error = ns.InfobipSMSProvider().send(to="+15550100", message="hi")
    assert ok is False
    assert "INFOBIP_API_KEY" in error


def test_email_provider_selection_and_aliases(infobip_env):
    assert ns._normalize_email_provider_type("infobip") == "infobip"
    assert ns._normalize_email_provider_type("Info-Bip") == "infobip"
    assert ns._normalize_email_provider_type("INFOBIP_API") == "infobip"

    infobip_env.setenv("EMAIL_PROVIDER", "infobip")
    assert ns._select_email_provider_type() == "infobip"
    assert isinstance(ns._build_email_provider("infobip"), ns.InfobipEmailProvider)

    # get_active_email_provider_type reports infobip once mock mode is off
    with patch.object(ns, "should_use_mock_notifications", return_value=False):
        assert ns.get_active_email_provider_type() == "infobip"
        # ...but without the base URL it must report noop (will not deliver)
        infobip_env.delenv("INFOBIP_BASE_URL")
        assert ns.get_active_email_provider_type() == "noop"


def test_email_auto_detection_prefers_configured_infobip(infobip_env):
    # No EMAIL_PROVIDER set and placeholder SMTP -> auto-detect Infobip.
    for var in ("SMTP_HOST", "SMTP_USERNAME", "SMTP_PASSWORD"):
        infobip_env.delenv(var, raising=False)
    with patch.object(ns.NotificationConfig, "SMTP_HOST", "localhost"), \
         patch.object(ns.NotificationConfig, "SMTP_USERNAME", ""), \
         patch.object(ns.NotificationConfig, "SMTP_PASSWORD", ""):
        assert ns._detect_configured_api_email_provider() == "infobip"
        assert ns._select_email_provider_type() == "infobip"


def test_sms_provider_configuration_detection(infobip_env):
    assert ns._sms_provider_is_configured("infobip") is True
    infobip_env.delenv("INFOBIP_BASE_URL")
    assert ns._sms_provider_is_configured("infobip") is False


def test_diagnostics_include_infobip(infobip_env):
    diagnostics = ns.get_notification_provider_diagnostics()
    assert diagnostics["email"]["providers"]["infobip"]["configured"] is True
    assert diagnostics["sms"]["providers"]["infobip"]["configured"] is True
    assert diagnostics["sms"]["providers"]["infobip"]["sender"] == "InfoSMS"


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
