"""
Tests for notification provider safety: providers must NOT silently fall
back to mock delivery when their credentials are missing.

This guards against the most common reason verification codes (forgot
password, OTP, billing alerts) fail to reach users in production: an
operator selects an API provider but forgets to set its API key, and the
old code silently swapped in MockEmailProvider/MockSMSProvider, returning
"sent: True" for emails/SMS that never left the building.
"""

from __future__ import annotations

import os

import pytest

from services.notification_service import (
    ActiveNotificationsEmailProvider,
    AWSSESEmailProvider,
    AWSSNSProvider,
    MailgunEmailProvider,
    MessageBirdSMSProvider,
    NotificationConfig,
    ResendEmailProvider,
    SendGridEmailProvider,
    TwilioSMSProvider,
    VonageSMSProvider,
    get_active_email_provider_type,
    get_active_sms_provider_type,
    get_notification_provider_diagnostics,
)


@pytest.fixture(autouse=True)
def _isolate_provider_env(monkeypatch):
    """Clear all provider env vars and config so each test starts blank."""
    env_vars = (
        'SENDGRID_API_KEY',
        'MAILGUN_API_KEY',
        'MAILGUN_DOMAIN',
        'RESEND_API_KEY',
        'RESEND_API_BASE_URL',
        'ACTIVE_NOTIFICATIONS_API_KEY',
        'PINGRAM_API_KEY',
        'NOTIFICATIONAPI_API_KEY',
        'TWILIO_ACCOUNT_SID',
        'TWILIO_AUTH_TOKEN',
        'TWILIO_FROM_NUMBER',
        'VONAGE_API_KEY',
        'VONAGE_API_SECRET',
        'MESSAGEBIRD_API_KEY',
        'AWS_ACCESS_KEY_ID',
        'AWS_PROFILE',
        'AWS_WEB_IDENTITY_TOKEN_FILE',
        'AWS_CONTAINER_CREDENTIALS_RELATIVE_URI',
        'AWS_CONTAINER_CREDENTIALS_FULL_URI',
    )
    for name in env_vars:
        monkeypatch.delenv(name, raising=False)

    # PHINS_TEST_MODE is forced to "true" by the root conftest, but these
    # tests verify production-mode safety — turn it off explicitly.
    monkeypatch.setenv('PHINS_TEST_MODE', 'false')
    monkeypatch.setenv('PHINS_USE_MOCK_NOTIFICATIONS', 'false')

    monkeypatch.setattr(NotificationConfig, 'SENDGRID_API_KEY', '')
    monkeypatch.setattr(NotificationConfig, 'MAILGUN_API_KEY', '')
    monkeypatch.setattr(NotificationConfig, 'MAILGUN_DOMAIN', '')
    monkeypatch.setattr(NotificationConfig, 'RESEND_API_KEY', '')
    monkeypatch.setattr(NotificationConfig, 'ACTIVE_NOTIFICATIONS_API_KEY', '')
    monkeypatch.setattr(NotificationConfig, 'TWILIO_ACCOUNT_SID', '')
    monkeypatch.setattr(NotificationConfig, 'TWILIO_AUTH_TOKEN', '')
    monkeypatch.setattr(NotificationConfig, 'TWILIO_FROM_NUMBER', '')
    monkeypatch.setattr(NotificationConfig, 'VONAGE_API_KEY', '')
    monkeypatch.setattr(NotificationConfig, 'VONAGE_API_SECRET', '')
    monkeypatch.setattr(NotificationConfig, 'MESSAGEBIRD_API_KEY', '')


# ---------------------------------------------------------------------------
# Email providers must surface a real failure when credentials are missing.
# ---------------------------------------------------------------------------


def test_sendgrid_provider_returns_failure_when_api_key_missing():
    success, message_id, error = SendGridEmailProvider().send(
        to='user@example.com', subject='subj', body='body'
    )
    assert success is False
    assert message_id is None
    assert 'SENDGRID_API_KEY' in (error or '')


def test_mailgun_provider_returns_failure_when_api_key_or_domain_missing():
    success, _, error = MailgunEmailProvider().send(
        to='user@example.com', subject='subj', body='body'
    )
    assert success is False
    assert 'MAILGUN_API_KEY' in (error or '')
    assert 'MAILGUN_DOMAIN' in (error or '')


def test_resend_provider_returns_failure_when_api_key_missing():
    success, _, error = ResendEmailProvider().send(
        to='user@example.com', subject='subj', body='body'
    )
    assert success is False
    assert 'RESEND_API_KEY' in (error or '')


def test_active_notifications_provider_returns_failure_when_api_key_missing():
    success, _, error = ActiveNotificationsEmailProvider().send(
        to='user@example.com', subject='subj', body='body'
    )
    assert success is False
    assert 'ACTIVE_NOTIFICATIONS_API_KEY' in (error or '')


def test_aws_ses_provider_returns_failure_when_credentials_missing():
    # boto3 raises NoCredentialsError ("Unable to locate credentials") at
    # send time when no AWS identity is reachable; if boto3 itself isn't
    # installed, we return our own "AWS SES not configured" message. Both
    # surface as a real failure (not a silent mock success).
    success, _, error = AWSSESEmailProvider().send(
        to='user@example.com', subject='subj', body='body'
    )
    assert success is False
    assert error is not None
    assert 'AWS SES not configured' in error or 'credentials' in error.lower()


# ---------------------------------------------------------------------------
# SMS providers must surface a real failure when credentials are missing.
# ---------------------------------------------------------------------------


def test_twilio_provider_returns_failure_when_credentials_missing():
    success, _, error = TwilioSMSProvider().send(to='+15551234567', message='hi')
    assert success is False
    assert 'TWILIO_ACCOUNT_SID' in (error or '')
    assert 'TWILIO_AUTH_TOKEN' in (error or '')


def test_vonage_provider_returns_failure_when_credentials_missing():
    success, _, error = VonageSMSProvider().send(to='+15551234567', message='hi')
    assert success is False
    assert 'VONAGE_API_KEY' in (error or '')


def test_messagebird_provider_returns_failure_when_api_key_missing():
    success, _, error = MessageBirdSMSProvider().send(to='+15551234567', message='hi')
    assert success is False
    assert 'MESSAGEBIRD_API_KEY' in (error or '')


def test_aws_sns_provider_returns_failure_when_credentials_missing():
    success, _, error = AWSSNSProvider().send(to='+15551234567', message='hi')
    assert success is False
    assert error is not None
    assert 'AWS SNS not configured' in error or 'credentials' in error.lower()


# ---------------------------------------------------------------------------
# Operator-facing diagnostics
# ---------------------------------------------------------------------------


def test_diagnostics_flags_unconfigured_email_as_will_not_deliver(monkeypatch):
    monkeypatch.setattr(NotificationConfig, 'SMTP_HOST', 'localhost')
    monkeypatch.setattr(NotificationConfig, 'SMTP_USERNAME', '')
    monkeypatch.setattr(NotificationConfig, 'SMTP_PASSWORD', '')

    diagnostics = get_notification_provider_diagnostics()
    assert diagnostics['mock_mode'] is False
    assert diagnostics['email']['will_deliver'] is False
    assert diagnostics['email']['active_provider'] in ('noop', 'smtp')
    assert 'No email provider configured' in (diagnostics['recommendation'] or '')


def test_diagnostics_marks_sendgrid_as_will_deliver_when_configured(monkeypatch):
    monkeypatch.setenv('EMAIL_PROVIDER', 'sendgrid')
    monkeypatch.setenv('SENDGRID_API_KEY', 'SG.test_key_123')
    monkeypatch.setattr(NotificationConfig, 'EMAIL_PROVIDER', 'sendgrid')
    monkeypatch.setattr(NotificationConfig, 'SENDGRID_API_KEY', 'SG.test_key_123')

    diagnostics = get_notification_provider_diagnostics()
    assert diagnostics['email']['active_provider'] == 'sendgrid'
    assert diagnostics['email']['will_deliver'] is True
    assert diagnostics['email']['providers']['sendgrid']['configured'] is True
    assert diagnostics['recommendation'] is None


def test_active_email_and_sms_provider_helpers_report_noop_when_unconfigured():
    monkeypatch_host = NotificationConfig.SMTP_HOST
    try:
        # Force placeholder SMTP via NotificationConfig (we already cleared
        # API provider keys in the autouse fixture).
        NotificationConfig.SMTP_HOST = 'localhost'
        NotificationConfig.SMTP_USERNAME = ''
        NotificationConfig.SMTP_PASSWORD = ''
        assert get_active_email_provider_type() == 'noop'
        assert get_active_sms_provider_type() == 'noop'
    finally:
        NotificationConfig.SMTP_HOST = monkeypatch_host


def test_diagnostics_reports_mock_mode_when_test_mode_enabled(monkeypatch):
    monkeypatch.setenv('PHINS_TEST_MODE', 'true')
    diagnostics = get_notification_provider_diagnostics()
    assert diagnostics['mock_mode'] is True
    assert diagnostics['email']['active_provider'] == 'mock'
    assert diagnostics['email']['will_deliver'] is False
    assert diagnostics['sms']['active_provider'] == 'mock'
    assert 'Mock email provider' in (diagnostics['recommendation'] or '')
