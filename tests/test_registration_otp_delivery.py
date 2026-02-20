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


def test_handle_otp_request_uses_demo_fallback_for_non_production_registration(monkeypatch):
    monkeypatch.setattr(api_extensions, "OTP_SERVICE_AVAILABLE", True)
    monkeypatch.setattr(api_extensions, "EXPOSE_DEMO_OTP", False)
    monkeypatch.setenv("PHINS_ENV", "development")
    monkeypatch.delenv("PHINS_ALLOW_REGISTRATION_DEMO_OTP_FALLBACK", raising=False)

    class _FakeOtpResult:
        success = True

        @staticmethod
        def to_dict():
            return {
                "success": True,
                "data": {
                    "verification_id": "OTP_TEST_DEV_FALLBACK",
                    "otp_code": "654321",
                    "masked_email": "d***@example.com",
                    "expires_in_seconds": 300,
                },
            }

    class _FakeOtpService:
        @staticmethod
        def create_otp_verification(**_kwargs):
            return _FakeOtpResult()

    monkeypatch.setattr(api_extensions, "get_otp_security_service", lambda: _FakeOtpService())
    monkeypatch.setattr(
        api_extensions,
        "_send_otp_email",
        lambda **_kwargs: (False, "smtp: [Errno 111] Connection refused"),
    )

    status, payload = api_extensions.handle_otp_request(
        client_ip="127.0.0.1",
        body_data={
            "email": "dev-fallback@example.com",
            "purpose": "registration",
            "user_type": "customer",
        },
        user_agent="pytest",
    )

    assert status == 200
    assert payload.get("success") is True
    assert payload.get("delivery_mode") == "demo_otp_fallback"
    assert payload.get("demo_otp_code") == "654321"
    assert payload.get("notification_sent") is False
    assert payload.get("verification_id") == "OTP_TEST_DEV_FALLBACK"


def test_handle_otp_request_keeps_delivery_hard_fail_in_production(monkeypatch):
    monkeypatch.setattr(api_extensions, "OTP_SERVICE_AVAILABLE", True)
    monkeypatch.setattr(api_extensions, "EXPOSE_DEMO_OTP", False)
    monkeypatch.setenv("PHINS_ENV", "production")
    monkeypatch.delenv("PHINS_ALLOW_REGISTRATION_DEMO_OTP_FALLBACK", raising=False)

    class _FakeOtpResult:
        success = True

        @staticmethod
        def to_dict():
            return {
                "success": True,
                "data": {
                    "verification_id": "OTP_TEST_PROD_FAIL",
                    "otp_code": "123456",
                    "masked_email": "p***@example.com",
                    "expires_in_seconds": 300,
                },
            }

    class _FakeOtpService:
        @staticmethod
        def create_otp_verification(**_kwargs):
            return _FakeOtpResult()

    monkeypatch.setattr(api_extensions, "get_otp_security_service", lambda: _FakeOtpService())
    monkeypatch.setattr(
        api_extensions,
        "_send_otp_email",
        lambda **_kwargs: (False, "smtp: [Errno 111] Connection refused"),
    )

    status, payload = api_extensions.handle_otp_request(
        client_ip="127.0.0.1",
        body_data={
            "email": "prod-fail@example.com",
            "purpose": "registration",
            "user_type": "customer",
        },
        user_agent="pytest",
    )

    assert status == 503
    assert payload.get("success") is False
    assert payload.get("error_code") == "OTP_DELIVERY_FAILED"
    assert "demo_otp_code" not in payload


def test_configured_email_provider_types_supports_aliases_and_resend(monkeypatch):
    monkeypatch.setenv("EMAIL_PROVIDER", "aws_ses")
    monkeypatch.setenv("RESEND_API_KEY", "re_test_key")
    monkeypatch.delenv("SENDGRID_API_KEY", raising=False)
    monkeypatch.delenv("MAILGUN_API_KEY", raising=False)
    monkeypatch.delenv("MAILGUN_DOMAIN", raising=False)

    providers = api_extensions._configured_email_provider_types()
    assert providers[0] == "ses"
    assert "resend" in providers
    assert providers[-1] == "smtp"
