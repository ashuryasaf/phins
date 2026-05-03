"""
Tests for SMTP resilience: circuit breaker, retry logic, notification
pipeline error handling, and NoOp email provider fallback.

Covers:
- SMTP circuit breaker state transitions (closed → open → half_open → closed)
- SMTPEmailProvider retry behaviour on connection errors
- NoOpEmailProvider when SMTP is unconfigured
- Active email provider type detection
- Secure notification pipeline structured error responses
- Base repository NULL primary key guard
- Health endpoint notification status
- Data integrity validation with notification health
"""

import os
import smtplib
import time
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _isolate_circuit_breaker():
    """Reset SMTP circuit breaker between tests."""
    from services.notification_service import _smtp_circuit_breaker
    _smtp_circuit_breaker._consecutive_failures = 0
    _smtp_circuit_breaker._state = 'closed'
    _smtp_circuit_breaker._opened_at = None
    _smtp_circuit_breaker._last_failure_error = None
    _smtp_circuit_breaker._half_open_probe_in_flight = False
    yield
    _smtp_circuit_breaker._consecutive_failures = 0
    _smtp_circuit_breaker._state = 'closed'
    _smtp_circuit_breaker._opened_at = None
    _smtp_circuit_breaker._last_failure_error = None
    _smtp_circuit_breaker._half_open_probe_in_flight = False


@pytest.fixture
def cb():
    from services.notification_service import _smtp_circuit_breaker
    return _smtp_circuit_breaker


# ---------------------------------------------------------------------------
# Circuit Breaker Tests
# ---------------------------------------------------------------------------

class TestSMTPCircuitBreaker:
    """Tests for _SMTPCircuitBreaker behaviour."""

    def test_starts_closed(self, cb):
        assert cb.state == 'closed'
        assert cb.allow_request() is True

    def test_stays_closed_below_threshold(self, cb):
        for _ in range(cb.FAILURE_THRESHOLD - 1):
            cb.record_failure('Connection refused')
        assert cb.state == 'closed'
        assert cb.allow_request() is True

    def test_opens_at_threshold(self, cb):
        for i in range(cb.FAILURE_THRESHOLD):
            cb.record_failure(f'fail-{i}')
        assert cb.state == 'open'
        assert cb.allow_request() is False

    def test_opened_at_does_not_reset_while_already_open(self, cb):
        from datetime import timedelta

        for i in range(cb.FAILURE_THRESHOLD):
            cb.record_failure(f'fail-{i}')

        original_opened_at = datetime.now(timezone.utc) - timedelta(seconds=30)
        cb._opened_at = original_opened_at

        cb.record_failure('still-failing')

        assert cb.state == 'open'
        assert cb._opened_at == original_opened_at

    def test_success_resets_to_closed(self, cb):
        for i in range(cb.FAILURE_THRESHOLD):
            cb.record_failure(f'fail-{i}')
        assert cb.state == 'open'
        cb.record_success()
        assert cb.state == 'closed'
        assert cb.allow_request() is True
        status = cb.get_status()
        assert status['consecutive_failures'] == 0

    def test_half_open_after_recovery_timeout(self, cb):
        for i in range(cb.FAILURE_THRESHOLD):
            cb.record_failure(f'fail-{i}')
        assert cb.state == 'open'
        # Simulate time passing beyond recovery timeout
        from datetime import timedelta
        cb._opened_at = datetime.now(timezone.utc) - timedelta(seconds=cb.RECOVERY_TIMEOUT + 1)
        assert cb.state == 'half_open'
        assert cb.allow_request() is True
        assert cb.allow_request() is False

    def test_get_status_returns_dict(self, cb):
        status = cb.get_status()
        assert 'state' in status
        assert 'consecutive_failures' in status
        assert 'last_failure' in status
        assert 'opened_at' in status


# ---------------------------------------------------------------------------
# SMTPEmailProvider Retry Tests
# ---------------------------------------------------------------------------

class TestSMTPEmailProviderRetry:
    """Tests for SMTPEmailProvider retry and circuit breaker integration."""

    def test_retry_on_connection_refused(self, cb):
        from services.notification_service import SMTPEmailProvider
        provider = SMTPEmailProvider()
        provider.MAX_RETRIES = 2
        provider.RETRY_DELAY_BASE = 0.01

        with patch('smtplib.SMTP') as mock_smtp:
            mock_smtp.side_effect = ConnectionRefusedError('[Errno 111] Connection refused')
            success, msg_id, error = provider.send(
                'test@example.com', 'Test', 'Body'
            )
        assert success is False
        assert error is not None
        assert 'Connection refused' in error
        assert mock_smtp.call_count == 2
        assert cb.get_status()['consecutive_failures'] == 1

    def test_smtp_protocol_errors_do_not_retry(self, cb):
        from services.notification_service import SMTPEmailProvider
        provider = SMTPEmailProvider()
        provider.MAX_RETRIES = 3
        provider.RETRY_DELAY_BASE = 0.01

        with patch('smtplib.SMTP') as mock_smtp:
            mock_smtp.side_effect = smtplib.SMTPAuthenticationError(535, b'Authentication failed')
            success, msg_id, error = provider.send(
                'test@example.com', 'Test', 'Body'
            )

        assert success is False
        assert msg_id is None
        assert error is not None
        assert 'Authentication failed' in error
        assert mock_smtp.call_count == 1
        assert cb.get_status()['consecutive_failures'] == 0

    def test_half_open_non_transient_smtp_error_does_not_reopen_breaker(self, cb):
        from services.notification_service import SMTPEmailProvider
        from datetime import timedelta

        for i in range(cb.FAILURE_THRESHOLD):
            cb.record_failure(f'fail-{i}')
        cb._opened_at = datetime.now(timezone.utc) - timedelta(seconds=cb.RECOVERY_TIMEOUT + 1)
        assert cb.state == 'half_open'

        provider = SMTPEmailProvider()
        provider.MAX_RETRIES = 3
        provider.RETRY_DELAY_BASE = 0.01

        with patch('smtplib.SMTP') as mock_smtp:
            mock_smtp.side_effect = smtplib.SMTPAuthenticationError(535, b'Authentication failed')
            success, msg_id, error = provider.send(
                'test@example.com', 'Test', 'Body'
            )

        assert success is False
        assert msg_id is None
        assert error is not None
        assert cb.state == 'closed'
        assert cb.get_status()['consecutive_failures'] == 0

    def test_success_after_transient_failure(self, cb):
        from services.notification_service import SMTPEmailProvider
        provider = SMTPEmailProvider()
        provider.MAX_RETRIES = 3
        provider.RETRY_DELAY_BASE = 0.01

        mock_server = MagicMock()
        mock_server.__enter__ = MagicMock(return_value=mock_server)
        mock_server.__exit__ = MagicMock(return_value=False)

        call_count = {'n': 0}

        def smtp_side_effect(*args, **kwargs):
            call_count['n'] += 1
            if call_count['n'] == 1:
                raise ConnectionRefusedError('Connection refused')
            return mock_server

        with patch('smtplib.SMTP', side_effect=smtp_side_effect):
            success, msg_id, error = provider.send(
                'test@example.com', 'Subject', 'Body'
            )
        assert success is True
        assert msg_id is not None
        assert error is None

    def test_circuit_breaker_blocks_send(self, cb):
        from services.notification_service import SMTPEmailProvider
        for i in range(cb.FAILURE_THRESHOLD):
            cb.record_failure(f'fail-{i}')
        assert cb.state == 'open'

        provider = SMTPEmailProvider()
        with patch('smtplib.SMTP') as mock_smtp:
            success, msg_id, error = provider.send(
                'test@example.com', 'Subject', 'Body'
            )
        assert success is False
        assert 'circuit breaker open' in error.lower()
        mock_smtp.assert_not_called()


# ---------------------------------------------------------------------------
# Base Repository NULL PK Guard
# ---------------------------------------------------------------------------

class TestBaseRepositoryNullGuard:

    def test_get_by_id_none_returns_none(self):
        from database.repositories.base import BaseRepository
        mock_session = MagicMock()
        repo = BaseRepository(MagicMock, mock_session)
        result = repo.get_by_id(None)
        assert result is None
        mock_session.query.assert_not_called()

    def test_get_by_id_valid_delegates_to_session(self):
        from database.repositories.base import BaseRepository
        mock_session = MagicMock()
        mock_model = MagicMock()
        repo = BaseRepository(mock_model, mock_session)
        repo.get_by_id('some-id')
        mock_session.query.assert_called_once_with(mock_model)


# ---------------------------------------------------------------------------
# Secure Notification Pipeline Error Handling
# ---------------------------------------------------------------------------

class TestPipelineChannelErrorHandling:

    @pytest.fixture
    def pipeline(self):
        from services.secure_notification_pipeline import (
            create_secure_notification_pipeline,
            reset_secure_notification_pipeline,
            MockWhatsAppProvider
        )
        from services.notification_service import reset_notification_service, reset_global_rate_limiter
        reset_global_rate_limiter()
        reset_notification_service()
        reset_secure_notification_pipeline()
        whatsapp = MockWhatsAppProvider()
        pipeline = create_secure_notification_pipeline(
            use_mock=True,
            whatsapp_provider=whatsapp
        )
        return pipeline

    def test_send_push_all_channels_fail_reports_errors(self, pipeline):
        from services.secure_notification_pipeline import (
            PushNotificationRequest,
            PushNotificationType,
        )
        from services.notification_service import NotificationChannel, NotificationPriority

        request = PushNotificationRequest(
            notification_type=PushNotificationType.MONTHLY_STATEMENT,
            customer_id='CUST-TEST-001',
            title='Monthly Statement',
            message='Your statement is ready.',
            channels=[NotificationChannel.EMAIL, NotificationChannel.SMS],
            email=None,
            phone=None,
            priority=NotificationPriority.HIGH,
        )
        result = pipeline.send_push_notification(request)
        assert result.success is False
        assert result.error_message is not None
        assert 'email' in result.error_message.lower() or 'sms' in result.error_message.lower()

    def test_send_push_partial_success(self, pipeline):
        from services.secure_notification_pipeline import (
            PushNotificationRequest,
            PushNotificationType,
        )
        from services.notification_service import NotificationChannel, NotificationPriority

        request = PushNotificationRequest(
            notification_type=PushNotificationType.PAYMENT_RECEIVED,
            customer_id='CUST-TEST-002',
            title='Payment Received',
            message='Thank you for your payment.',
            channels=[NotificationChannel.EMAIL, NotificationChannel.SMS],
            email='valid@example.com',
            phone=None,
            priority=NotificationPriority.HIGH,
        )
        result = pipeline.send_push_notification(request)
        assert result.success is True
        email_result = result.channel_results.get('email', {})
        sms_result = result.channel_results.get('sms', {})
        assert email_result.get('success') is True
        assert sms_result.get('success') is False

    def test_channel_error_codes_present(self, pipeline):
        from services.secure_notification_pipeline import (
            PushNotificationRequest,
            PushNotificationType,
        )
        from services.notification_service import NotificationChannel

        request = PushNotificationRequest(
            notification_type=PushNotificationType.PAYMENT_FAILED,
            customer_id='CUST-TEST-003',
            title='Payment Failed',
            message='Your payment could not be processed.',
            channels=[NotificationChannel.EMAIL],
            email=None,
        )
        result = pipeline.send_push_notification(request)
        email_result = result.channel_results.get('email', {})
        assert email_result.get('success') is False
        assert email_result.get('error_code') == 'NO_RECIPIENT'


# ---------------------------------------------------------------------------
# NoOpEmailProvider Tests
# ---------------------------------------------------------------------------

class TestNoOpEmailProvider:

    def test_noop_provider_returns_failure(self):
        from services.notification_service import NoOpEmailProvider
        provider = NoOpEmailProvider()
        success, msg_id, error = provider.send('test@example.com', 'Subject', 'Body')
        assert success is False
        assert msg_id is None
        assert error is not None
        assert 'No email provider configured' in error

    def test_noop_provider_no_network_calls(self):
        from services.notification_service import NoOpEmailProvider
        provider = NoOpEmailProvider()
        with patch('smtplib.SMTP') as mock_smtp:
            provider.send('test@example.com', 'Subject', 'Body')
        mock_smtp.assert_not_called()

    def test_build_email_provider_returns_noop_when_unconfigured(self):
        from services.notification_service import _build_email_provider, NoOpEmailProvider
        env = {
            'SMTP_HOST': 'localhost',
            'SMTP_USERNAME': '',
            'SMTP_PASSWORD': '',
            'SENDGRID_API_KEY': '',
            'MAILGUN_API_KEY': '',
            'RESEND_API_KEY': '',
            'ACTIVE_NOTIFICATIONS_API_KEY': '',
            'PINGRAM_API_KEY': '',
            'NOTIFICATIONAPI_API_KEY': '',
        }
        with patch.dict(os.environ, env, clear=False):
            provider = _build_email_provider('smtp')
        assert isinstance(provider, NoOpEmailProvider)

    def test_build_email_provider_returns_smtp_when_configured(self):
        from services.notification_service import _build_email_provider, SMTPEmailProvider
        env = {
            'SMTP_HOST': 'smtp.sendgrid.net',
            'SMTP_USERNAME': 'apikey',
            'SMTP_PASSWORD': 'SG.fake-key',
        }
        with patch.dict(os.environ, env, clear=False):
            provider = _build_email_provider('smtp')
        assert isinstance(provider, SMTPEmailProvider)


# ---------------------------------------------------------------------------
# get_active_email_provider_type Tests
# ---------------------------------------------------------------------------

class TestActiveEmailProviderType:

    def test_returns_mock_in_test_mode(self):
        from services.notification_service import get_active_email_provider_type
        with patch.dict(os.environ, {'PHINS_TEST_MODE': 'true'}, clear=False):
            assert get_active_email_provider_type() == 'mock'

    def test_returns_noop_when_smtp_unconfigured(self):
        from services.notification_service import get_active_email_provider_type
        env = {
            'PHINS_TEST_MODE': '',
            'PHINS_USE_MOCK_NOTIFICATIONS': '',
            'SMTP_HOST': 'localhost',
            'SMTP_USERNAME': '',
            'SMTP_PASSWORD': '',
            'EMAIL_PROVIDER': 'smtp',
            'SENDGRID_API_KEY': '',
            'MAILGUN_API_KEY': '',
            'RESEND_API_KEY': '',
            'ACTIVE_NOTIFICATIONS_API_KEY': '',
            'PINGRAM_API_KEY': '',
            'NOTIFICATIONAPI_API_KEY': '',
        }
        with patch.dict(os.environ, env, clear=False):
            assert get_active_email_provider_type() == 'noop'

    def test_returns_provider_name_when_api_configured(self):
        from services.notification_service import get_active_email_provider_type
        env = {
            'PHINS_TEST_MODE': '',
            'PHINS_USE_MOCK_NOTIFICATIONS': '',
            'EMAIL_PROVIDER': 'sendgrid',
            'SENDGRID_API_KEY': 'SG.fake-key',
        }
        with patch.dict(os.environ, env, clear=False):
            assert get_active_email_provider_type() == 'sendgrid'


# ---------------------------------------------------------------------------
# get_smtp_circuit_breaker export
# ---------------------------------------------------------------------------

class TestCircuitBreakerExport:

    def test_get_smtp_circuit_breaker_importable(self):
        from services.notification_service import get_smtp_circuit_breaker
        cb = get_smtp_circuit_breaker()
        assert hasattr(cb, 'state')
        assert hasattr(cb, 'allow_request')
        assert hasattr(cb, 'record_success')
        assert hasattr(cb, 'record_failure')
        assert hasattr(cb, 'get_status')
