from types import SimpleNamespace

import web_portal.api_extensions as api_extensions


def test_send_otp_email_uses_provider_fallback_on_delivery_failure(monkeypatch):
    monkeypatch.setattr(api_extensions, "PHINS_TEST_MODE", False)
    monkeypatch.setenv("PHINS_USE_MOCK_NOTIFICATIONS", "false")
    monkeypatch.setattr(
        api_extensions,
        "_configured_email_provider_types",
        lambda: ["sendgrid", "mailgun"],
    )

    attempts = []

    class _FakeNotificationService:
        def __init__(self, label, success, error_message):
            self.label = label
            self.success = success
            self.error_message = error_message

        def send(self, _request):
            attempts.append(self.label)
            return SimpleNamespace(
                success=self.success,
                error_message=self.error_message,
            )

    def _factory(use_mock_notifications, provider_type=None):
        assert not use_mock_notifications
        if provider_type is None:
            return _FakeNotificationService("auto", False, "auto failed")
        if provider_type == "sendgrid":
            return _FakeNotificationService("sendgrid", False, "sendgrid failed")
        if provider_type == "mailgun":
            return _FakeNotificationService("mailgun", True, None)
        return _FakeNotificationService(str(provider_type), False, "unexpected provider")

    monkeypatch.setattr(api_extensions, "_create_notification_service_for_provider", _factory)

    sent, error = api_extensions._send_otp_email(
        email="fallback@example.com",
        otp_code="123456",
        expiry_seconds=300,
        purpose="registration",
        ip_address="127.0.0.1",
    )

    assert sent is True
    assert error is None
    assert attempts == ["auto", "sendgrid", "mailgun"]


def test_send_otp_email_returns_combined_errors_when_all_providers_fail(monkeypatch):
    monkeypatch.setattr(api_extensions, "PHINS_TEST_MODE", False)
    monkeypatch.setenv("PHINS_USE_MOCK_NOTIFICATIONS", "false")
    monkeypatch.setattr(
        api_extensions,
        "_configured_email_provider_types",
        lambda: ["sendgrid"],
    )

    class _AlwaysFailService:
        def __init__(self, label):
            self.label = label

        def send(self, _request):
            return SimpleNamespace(success=False, error_message=f"{self.label} failed")

    def _factory(use_mock_notifications, provider_type=None):
        assert not use_mock_notifications
        return _AlwaysFailService("auto" if provider_type is None else provider_type)

    monkeypatch.setattr(api_extensions, "_create_notification_service_for_provider", _factory)

    sent, error = api_extensions._send_otp_email(
        email="failed@example.com",
        otp_code="123456",
        expiry_seconds=300,
        purpose="registration",
        ip_address="127.0.0.1",
    )

    assert sent is False
    assert isinstance(error, str)
    assert "auto:" in error
    assert "sendgrid:" in error
