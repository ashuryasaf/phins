"""
Tests for the Telesign SMS provider integration.

Telesign credentials come from https://my.telesign.com → Settings → API
authentication and authenticate with HTTP Basic auth (customer ID :
api key) against ``POST {base_url}/v1/messaging``.
"""

from __future__ import annotations

import base64
import json
import urllib.parse
from typing import Dict, Optional
from unittest.mock import patch

import pytest

from services.notification_service import (
    NotificationConfig,
    TelesignSMSProvider,
    TwilioSMSProvider,
    create_notification_service,
    get_active_sms_provider_type,
    get_notification_provider_diagnostics,
)


@pytest.fixture(autouse=True)
def _clear_telesign_env(monkeypatch):
    for name in (
        'TELESIGN_CUSTOMER_ID',
        'TELESIGN_API_KEY',
        'TELESIGN_BASE_URL',
        'TELESIGN_SEND_PATH',
        'TELESIGN_MESSAGE_TYPE',
        'TELESIGN_SENDER_ID',
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv('PHINS_TEST_MODE', 'false')
    monkeypatch.setenv('PHINS_USE_MOCK_NOTIFICATIONS', 'false')
    monkeypatch.setattr(NotificationConfig, 'TELESIGN_CUSTOMER_ID', '')
    monkeypatch.setattr(NotificationConfig, 'TELESIGN_API_KEY', '')
    monkeypatch.setattr(NotificationConfig, 'TELESIGN_BASE_URL', 'https://rest-api.telesign.com')
    monkeypatch.setattr(NotificationConfig, 'TELESIGN_SEND_PATH', '/v1/messaging')
    monkeypatch.setattr(NotificationConfig, 'TELESIGN_MESSAGE_TYPE', 'OTP')
    monkeypatch.setattr(NotificationConfig, 'TELESIGN_SENDER_ID', '')
    yield


class _FakeResponse:
    def __init__(self, status: int = 200, payload: Optional[Dict] = None):
        self.status = status
        self._payload = payload or {
            'reference_id': 'TS-REF-0001',
            'status': {'code': 290, 'description': 'Message in progress'},
        }
        self.headers = {}

    def read(self) -> bytes:
        return json.dumps(self._payload).encode('utf-8')

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _capture_urlopen(captured):
    def _impl(req, timeout=None, allowed_schemes=None):
        captured['url'] = req.full_url
        captured['method'] = req.get_method()
        captured['headers'] = dict(req.header_items())
        captured['data'] = req.data.decode('utf-8') if req.data else ''
        return _FakeResponse()
    return _impl


def test_telesign_provider_returns_failure_when_credentials_missing():
    success, message_id, error = TelesignSMSProvider().send(
        to='+15551234567', message='Your code is 123456.'
    )
    assert success is False
    assert message_id is None
    assert 'TELESIGN_CUSTOMER_ID' in (error or '')
    assert 'TELESIGN_API_KEY' in (error or '')
    # The error should point operators at the dashboard.
    assert 'my.telesign.com' in (error or '')


def test_telesign_provider_sends_basic_auth_form_encoded(monkeypatch):
    monkeypatch.setattr(NotificationConfig, 'TELESIGN_CUSTOMER_ID', 'CUST-001')
    monkeypatch.setattr(NotificationConfig, 'TELESIGN_API_KEY', 'apikey_secret==')

    captured: Dict = {}
    with patch(
        'services.notification_service.validated_urlopen',
        _capture_urlopen(captured),
    ):
        success, message_id, error = TelesignSMSProvider().send(
            to='+1 (555) 123-4567',
            message='PHINS verification code: 654321',
        )

    assert success is True
    assert error is None
    assert message_id == 'TS-REF-0001'

    assert captured['method'] == 'POST'
    assert captured['url'] == 'https://rest-api.telesign.com/v1/messaging'

    expected_basic = 'Basic ' + base64.b64encode(
        b'CUST-001:apikey_secret==',
    ).decode('ascii')
    assert captured['headers']['Authorization'] == expected_basic
    # The HTTP client lower-cases the header key in `header_items()`.
    assert captured['headers']['Content-type'] == 'application/x-www-form-urlencoded'

    form = dict(urllib.parse.parse_qsl(captured['data']))
    assert form['phone_number'] == '15551234567'  # digits only, no '+' or punctuation
    assert form['message_type'] == 'OTP'
    assert form['message'] == 'PHINS verification code: 654321'
    assert 'sender_id' not in form  # not configured


def test_telesign_provider_includes_sender_id_when_configured(monkeypatch):
    monkeypatch.setattr(NotificationConfig, 'TELESIGN_CUSTOMER_ID', 'CUST-002')
    monkeypatch.setattr(NotificationConfig, 'TELESIGN_API_KEY', 'apikey2')
    monkeypatch.setattr(NotificationConfig, 'TELESIGN_SENDER_ID', 'PHINS')
    monkeypatch.setattr(NotificationConfig, 'TELESIGN_MESSAGE_TYPE', 'ARN')

    captured: Dict = {}
    with patch(
        'services.notification_service.validated_urlopen',
        _capture_urlopen(captured),
    ):
        success, _, _ = TelesignSMSProvider().send(
            to='+15551234567',
            message='hi',
        )

    assert success is True
    form = dict(urllib.parse.parse_qsl(captured['data']))
    assert form['sender_id'] == 'PHINS'
    assert form['message_type'] == 'ARN'


def test_telesign_provider_treats_non_290_status_codes_as_failure(monkeypatch):
    monkeypatch.setattr(NotificationConfig, 'TELESIGN_CUSTOMER_ID', 'CUST-003')
    monkeypatch.setattr(NotificationConfig, 'TELESIGN_API_KEY', 'apikey3')

    def _failing_urlopen(req, timeout=None, allowed_schemes=None):
        return _FakeResponse(
            status=200,
            payload={
                'reference_id': 'X',
                'status': {'code': 500, 'description': 'Carrier rejected'},
            },
        )

    with patch(
        'services.notification_service.validated_urlopen',
        _failing_urlopen,
    ):
        success, _, error = TelesignSMSProvider().send(
            to='+15551234567', message='hi'
        )

    assert success is False
    assert 'Telesign error' in (error or '')
    assert 'Carrier rejected' in (error or '')


def test_telesign_provider_surfaces_http_errors(monkeypatch):
    """A 401 from Telesign should report the documented status code."""
    import urllib.error

    monkeypatch.setattr(NotificationConfig, 'TELESIGN_CUSTOMER_ID', 'CUST-004')
    monkeypatch.setattr(NotificationConfig, 'TELESIGN_API_KEY', 'bad_key')

    error_payload = json.dumps({
        'reference_id': 'X',
        'status': {'code': 10022, 'description': 'Invalid API key'},
    }).encode('utf-8')

    class _Body:
        def __init__(self, data: bytes):
            self._data = data

        def read(self) -> bytes:
            return self._data

        def close(self) -> None:  # urllib's HTTPError tries to close fp on cleanup.
            pass

    def _401_urlopen(req, timeout=None, allowed_schemes=None):
        raise urllib.error.HTTPError(
            url=req.full_url,
            code=401,
            msg='Unauthorized',
            hdrs=None,  # type: ignore[arg-type]
            fp=_Body(error_payload),
        )

    with patch(
        'services.notification_service.validated_urlopen',
        _401_urlopen,
    ):
        success, _, error = TelesignSMSProvider().send(
            to='+15551234567', message='hi'
        )

    assert success is False
    assert 'HTTP 401' in (error or '')
    assert '10022' in (error or '')
    assert 'Invalid API key' in (error or '')


def test_create_notification_service_picks_telesign(monkeypatch):
    monkeypatch.setattr(NotificationConfig, 'SMS_PROVIDER', 'telesign')
    monkeypatch.setattr(NotificationConfig, 'TELESIGN_CUSTOMER_ID', 'CUST-005')
    monkeypatch.setattr(NotificationConfig, 'TELESIGN_API_KEY', 'apikey5')

    service = create_notification_service(use_mock=False)
    assert isinstance(service._sms_provider, TelesignSMSProvider)


def test_diagnostics_reports_telesign_configured(monkeypatch):
    monkeypatch.setattr(NotificationConfig, 'SMS_PROVIDER', 'telesign')
    monkeypatch.setattr(NotificationConfig, 'TELESIGN_CUSTOMER_ID', 'CUST-006')
    monkeypatch.setattr(NotificationConfig, 'TELESIGN_API_KEY', 'apikey6')

    assert get_active_sms_provider_type() == 'telesign'

    diagnostics = get_notification_provider_diagnostics()
    telesign = diagnostics['sms']['providers']['telesign']
    assert telesign['configured'] is True
    assert telesign['base_url'] == 'https://rest-api.telesign.com'
    assert telesign['message_type'] == 'OTP'
    assert diagnostics['sms']['active_provider'] == 'telesign'
    assert diagnostics['sms']['will_deliver'] is True


def test_diagnostics_recommends_telesign_creds_when_selected_but_missing(monkeypatch):
    monkeypatch.setattr(NotificationConfig, 'SMS_PROVIDER', 'telesign')
    # No credentials set.
    diagnostics = get_notification_provider_diagnostics()
    assert diagnostics['sms']['active_provider'] == 'noop'
    assert diagnostics['sms']['will_deliver'] is False
    recommendation = diagnostics.get('recommendation') or ''
    assert 'Telesign is selected' in recommendation
    assert 'TELESIGN_CUSTOMER_ID' in recommendation
    assert 'TELESIGN_API_KEY' in recommendation
    assert 'my.telesign.com' in recommendation


def _clear_twilio(monkeypatch):
    """Ensure Twilio looks unconfigured regardless of the host environment."""
    monkeypatch.setattr(NotificationConfig, 'TWILIO_ACCOUNT_SID', '')
    monkeypatch.setattr(NotificationConfig, 'TWILIO_AUTH_TOKEN', '')
    monkeypatch.setattr(NotificationConfig, 'TWILIO_FROM_NUMBER', '')
    for name in ('TWILIO_ACCOUNT_SID', 'TWILIO_AUTH_TOKEN', 'TWILIO_FROM_NUMBER'):
        monkeypatch.delenv(name, raising=False)


def test_sms_auto_selects_telesign_when_provider_left_at_twilio_default(monkeypatch):
    """Telesign creds present on Railway but SMS_PROVIDER left at 'twilio'.

    The configured provider (twilio) cannot deliver, so the fully-configured
    Telesign provider should be auto-selected instead of silently failing.
    """
    monkeypatch.setattr(NotificationConfig, 'SMS_PROVIDER', 'twilio')
    _clear_twilio(monkeypatch)
    monkeypatch.setattr(NotificationConfig, 'TELESIGN_CUSTOMER_ID', 'CUST-AUTO')
    monkeypatch.setattr(NotificationConfig, 'TELESIGN_API_KEY', 'apikey-auto')

    assert get_active_sms_provider_type() == 'telesign'

    service = create_notification_service(use_mock=False)
    assert isinstance(service._sms_provider, TelesignSMSProvider)


def test_diagnostics_flags_auto_selected_telesign(monkeypatch):
    monkeypatch.setattr(NotificationConfig, 'SMS_PROVIDER', 'twilio')
    _clear_twilio(monkeypatch)
    monkeypatch.setattr(NotificationConfig, 'TELESIGN_CUSTOMER_ID', 'CUST-AUTO2')
    monkeypatch.setattr(NotificationConfig, 'TELESIGN_API_KEY', 'apikey-auto2')

    diagnostics = get_notification_provider_diagnostics()
    sms = diagnostics['sms']
    assert sms['configured_provider'] == 'twilio'
    assert sms['active_provider'] == 'telesign'
    assert sms['will_deliver'] is True
    assert sms['auto_selected'] is True

    recommendation = diagnostics.get('recommendation') or ''
    assert "SMS_PROVIDER='twilio'" in recommendation
    assert 'SMS_PROVIDER=telesign' in recommendation


def test_sms_stays_noop_when_no_provider_configured(monkeypatch):
    """No SMS provider configured at all -> still 'noop' (no false fallback)."""
    monkeypatch.setattr(NotificationConfig, 'SMS_PROVIDER', 'twilio')
    _clear_twilio(monkeypatch)
    # Telesign creds already cleared by the autouse fixture.

    assert get_active_sms_provider_type() == 'noop'

    diagnostics = get_notification_provider_diagnostics()
    assert diagnostics['sms']['will_deliver'] is False
    assert diagnostics['sms']['auto_selected'] is False
