"""Focused tests for OTP email delivery robustness in API extensions."""

from __future__ import annotations

import services.notification_service as notification_service
import web_portal.api_extensions as api_extensions


class _DummyResult:
    """Simple response object compatible with notification_service expectations."""

    def __init__(self, success: bool, error_message: str | None = None, error_code: str | None = None):
        self.success = success
        self.error_message = error_message
        self.error_code = error_code


def test_send_otp_email_uses_fallback_provider_when_primary_fails(monkeypatch):
    """Primary send failures should try configured alternate providers."""
    monkeypatch.setattr(api_extensions, "PHINS_TEST_MODE", False)
    monkeypatch.delenv("PHINS_USE_MOCK_NOTIFICATIONS", raising=False)

    primary_recipients = []
    fallback_calls = []

    class _PrimaryFailureService:
        def send(self, request):
            primary_recipients.append(request.recipient)
            return _DummyResult(success=False, error_message="primary transport unavailable")

    class _FallbackSuccessService:
        def __init__(self, provider_name: str):
            self.provider_name = provider_name

        def send(self, request):
            fallback_calls.append((self.provider_name, request.recipient))
            return _DummyResult(success=True)

    class _DummySendGridProvider:
        pass

    monkeypatch.setattr(
        notification_service,
        "create_notification_service",
        lambda use_mock=False: _PrimaryFailureService(),
    )
    monkeypatch.setattr(
        notification_service,
        "NotificationService",
        lambda email_provider=None, sms_provider=None: _FallbackSuccessService(
            type(email_provider).__name__
        ),
    )
    monkeypatch.setattr(notification_service, "SendGridEmailProvider", _DummySendGridProvider)
    monkeypatch.setattr(notification_service, "MockSMSProvider", lambda: object())

    monkeypatch.setattr(notification_service.NotificationConfig, "EMAIL_PROVIDER", "smtp")
    monkeypatch.setattr(notification_service.NotificationConfig, "SMTP_HOST", "localhost")
    monkeypatch.setattr(notification_service.NotificationConfig, "SENDGRID_API_KEY", "SG.test_key")
    monkeypatch.setattr(notification_service.NotificationConfig, "MAILGUN_API_KEY", "")
    monkeypatch.setattr(notification_service.NotificationConfig, "MAILGUN_DOMAIN", "")

    sent, error = api_extensions._send_otp_email(
        email="customer@example.com",
        otp_code="123456",
        expiry_seconds=300,
        purpose="registration",
        ip_address="203.0.113.10",
    )

    assert sent is True
    assert error is None
    assert primary_recipients == ["customer@example.com"]
    assert fallback_calls == [("_DummySendGridProvider", "customer@example.com")]


def test_send_otp_email_returns_failure_if_no_delivery_provider_available(monkeypatch):
    """OTP send should fail closed when no provider can deliver."""
    monkeypatch.setattr(api_extensions, "PHINS_TEST_MODE", False)
    monkeypatch.delenv("PHINS_USE_MOCK_NOTIFICATIONS", raising=False)

    class _AlwaysFailService:
        def send(self, _request):
            return _DummyResult(success=False, error_message="connection refused")

    monkeypatch.setattr(
        notification_service,
        "create_notification_service",
        lambda use_mock=False: _AlwaysFailService(),
    )

    monkeypatch.setattr(notification_service.NotificationConfig, "EMAIL_PROVIDER", "smtp")
    monkeypatch.setattr(notification_service.NotificationConfig, "SMTP_HOST", "localhost")
    monkeypatch.setattr(notification_service.NotificationConfig, "SENDGRID_API_KEY", "")
    monkeypatch.setattr(notification_service.NotificationConfig, "MAILGUN_API_KEY", "")
    monkeypatch.setattr(notification_service.NotificationConfig, "MAILGUN_DOMAIN", "")

    sent, error = api_extensions._send_otp_email(
        email="customer@example.com",
        otp_code="123456",
        expiry_seconds=300,
        purpose="registration",
        ip_address="203.0.113.10",
    )

    assert sent is False
    assert error is not None
    assert "primary:" in error


def test_send_otp_email_normalizes_recipient_email(monkeypatch):
    """Recipient should be trimmed/lowercased before send to avoid format rejects."""
    monkeypatch.setattr(api_extensions, "PHINS_TEST_MODE", True)

    captured_recipients = []

    class _CaptureService:
        def send(self, request):
            captured_recipients.append(request.recipient)
            return _DummyResult(success=True)

    monkeypatch.setattr(
        notification_service,
        "create_notification_service",
        lambda use_mock=False: _CaptureService(),
    )

    sent, error = api_extensions._send_otp_email(
        email="  User.Name+tag@Example.COM  ",
        otp_code="654321",
        expiry_seconds=300,
        purpose="registration",
        ip_address="203.0.113.11",
    )

    assert sent is True
    assert error is None
    assert captured_recipients == ["user.name+tag@example.com"]
