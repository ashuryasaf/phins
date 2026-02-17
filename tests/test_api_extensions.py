"""Targeted tests for OTP + API extension hardening."""

from __future__ import annotations

import uuid

import services.notification_service as notification_service
import services.otp_security_service as otp_security_service
import web_portal.api_extensions as api_extensions


def test_otp_delivery_falls_back_when_primary_provider_fails(monkeypatch):
    """
    OTP delivery should recover by trying another configured email provider.

    Scenario:
      - Primary provider is SMTP and fails.
      - SendGrid is configured and succeeds.
      - API still returns a successful OTP request.
    """
    monkeypatch.setenv('EMAIL_PROVIDER', 'smtp')
    monkeypatch.setattr(api_extensions, 'PHINS_TEST_MODE', False)
    monkeypatch.setattr(api_extensions, 'EXPOSE_DEMO_OTP', False)

    monkeypatch.setattr(notification_service.NotificationConfig, 'EMAIL_PROVIDER', 'smtp')
    monkeypatch.setattr(notification_service.NotificationConfig, 'SMTP_HOST', 'smtp.gmail.com')
    monkeypatch.setattr(notification_service.NotificationConfig, 'SMTP_USERNAME', 'smtp-user')
    monkeypatch.setattr(notification_service.NotificationConfig, 'SMTP_PASSWORD', 'smtp-pass')
    monkeypatch.setattr(notification_service.NotificationConfig, 'SENDGRID_API_KEY', 'SG.test_key')
    monkeypatch.setattr(notification_service.NotificationConfig, 'MAILGUN_API_KEY', '')
    monkeypatch.setattr(notification_service.NotificationConfig, 'MAILGUN_DOMAIN', '')

    otp_security_service.reset_otp_security_service()

    smtp_calls = {'count': 0}
    sendgrid_calls = {'count': 0}

    def failing_smtp_send(self, *args, **kwargs):
        smtp_calls['count'] += 1
        return False, None, 'smtp unavailable'

    def successful_sendgrid_send(self, *args, **kwargs):
        sendgrid_calls['count'] += 1
        return True, 'sg-message-id', None

    monkeypatch.setattr(notification_service.SMTPEmailProvider, 'send', failing_smtp_send)
    monkeypatch.setattr(notification_service.SendGridEmailProvider, 'send', successful_sendgrid_send)

    email = f"otp-fallback-{uuid.uuid4().hex[:8]}@example.com"
    status, payload = api_extensions.handle_otp_request(
        client_ip='127.0.0.1',
        body_data={
            'email': email,
            'purpose': 'registration',
            'user_type': 'customer',
        },
        user_agent='pytest-agent'
    )

    assert status == 200
    assert payload.get('success') is True
    assert payload.get('notification_sent') is True
    assert smtp_calls['count'] >= 1
    assert sendgrid_calls['count'] >= 1
