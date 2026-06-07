"""
Tests for the SMS-channel OTP delivery path (forgot password / login OTP).

The platform used to support email-only OTP. These tests cover the new
behavior:

- ``OTPSecurityService.create_otp_verification`` accepts ``phone`` and
  ``delivery_channel`` and exposes them in the result data.
- ``api_extensions._send_otp_via_channel`` dispatches to email, SMS, or
  both, surfacing a partial-failure error when 'both' is chosen and one
  channel fails.
- ``handle_otp_request`` returns ``masked_phone`` and routes via SMS
  when the caller asks for it.
- ``handle_otp_request`` rejects SMS requests that don't supply a phone.
"""

from __future__ import annotations

import pytest

import web_portal.api_extensions as api_extensions
from services.otp_security_service import (
    OTPPurpose,
    _mask_phone,
    get_otp_security_service,
)


@pytest.fixture(autouse=True)
def _reset_otp_state(monkeypatch):
    """Force test-mode mocks so the SMS provider returns success."""
    monkeypatch.setenv('PHINS_TEST_MODE', 'true')
    monkeypatch.setenv('PHINS_USE_MOCK_NOTIFICATIONS', 'true')
    yield


def test_otp_security_service_records_phone_and_channel():
    service = get_otp_security_service()
    result = service.create_otp_verification(
        user_type='customer',
        user_id='sms-user@example.com',
        email='sms-user@example.com',
        purpose=OTPPurpose.PASSWORD_RESET,
        ip_address='127.0.0.1',
        phone='+15551234567',
        delivery_channel='sms',
    )
    assert result.success
    data = result.data or {}
    assert data['delivery_channel'] == 'sms'
    assert data['phone'] == '+15551234567'
    assert data['masked_phone'] == _mask_phone('+15551234567')


def test_otp_security_service_rejects_sms_without_phone():
    service = get_otp_security_service()
    result = service.create_otp_verification(
        user_type='customer',
        user_id='no-phone@example.com',
        email='no-phone@example.com',
        purpose=OTPPurpose.PASSWORD_RESET,
        ip_address='127.0.0.1',
        delivery_channel='sms',
    )
    assert result.success is False
    assert result.error_code == 'MISSING_PHONE'


def test_handle_otp_request_returns_masked_phone_for_sms_channel():
    status, payload = api_extensions.handle_otp_request(
        client_ip='127.0.0.1',
        body_data={
            'email': 'sms-route@example.com',
            'phone': '+15551237890',
            'delivery_channel': 'sms',
            'purpose': 'login',
            'user_type': 'customer',
        },
        user_agent='pytest',
    )
    assert status == 200
    assert payload['notification_sent'] is True
    assert payload['delivery_channel'] == 'sms'
    assert payload['masked_phone'].endswith('90')


def test_handle_otp_request_rejects_sms_without_phone():
    status, payload = api_extensions.handle_otp_request(
        client_ip='127.0.0.1',
        body_data={
            'email': 'sms-missing@example.com',
            'delivery_channel': 'sms',
            'purpose': 'login',
            'user_type': 'customer',
        },
        user_agent='pytest',
    )
    assert status == 400
    assert payload.get('error_code') == 'MISSING_PHONE'


def test_send_otp_via_channel_email_only_path(monkeypatch):
    sent = {'email': False, 'sms': False}

    def _fake_email(**kwargs):
        sent['email'] = kwargs
        return True, None

    def _fake_sms(**kwargs):
        sent['sms'] = kwargs
        return True, None

    monkeypatch.setattr(api_extensions, '_send_otp_email', _fake_email)
    monkeypatch.setattr(api_extensions, '_send_otp_sms', _fake_sms)

    success, error = api_extensions._send_otp_via_channel(
        delivery_channel='email',
        otp_code='123456',
        expiry_seconds=300,
        purpose='login',
        email='only-email@example.com',
        phone='+15551112222',
    )
    assert success is True
    assert error is None
    assert sent['email']['email'] == 'only-email@example.com'
    assert sent['sms'] is False  # SMS not invoked


def test_send_otp_via_channel_both_succeeds_if_either_succeeds(monkeypatch):
    monkeypatch.setattr(
        api_extensions,
        '_send_otp_email',
        lambda **kwargs: (False, 'sendgrid down'),
    )
    monkeypatch.setattr(
        api_extensions,
        '_send_otp_sms',
        lambda **kwargs: (True, None),
    )

    success, error = api_extensions._send_otp_via_channel(
        delivery_channel='both',
        otp_code='123456',
        expiry_seconds=300,
        purpose='login',
        email='partial@example.com',
        phone='+15551112222',
    )
    assert success is True
    # Partial failure is surfaced so operators can see which channel failed.
    assert error is not None
    assert 'sendgrid down' in error


def test_send_otp_via_channel_both_fails_when_both_channels_fail(monkeypatch):
    monkeypatch.setattr(
        api_extensions,
        '_send_otp_email',
        lambda **kwargs: (False, 'email error'),
    )
    monkeypatch.setattr(
        api_extensions,
        '_send_otp_sms',
        lambda **kwargs: (False, 'sms error'),
    )

    success, error = api_extensions._send_otp_via_channel(
        delivery_channel='both',
        otp_code='123456',
        expiry_seconds=300,
        purpose='login',
        email='both-fail@example.com',
        phone='+15551112222',
    )
    assert success is False
    assert error is not None
    assert 'email error' in error
    assert 'sms error' in error


def test_send_otp_via_channel_sms_requires_phone(monkeypatch):
    monkeypatch.setattr(
        api_extensions,
        '_send_otp_email',
        lambda **kwargs: (True, None),
    )
    success, error = api_extensions._send_otp_via_channel(
        delivery_channel='sms',
        otp_code='123456',
        expiry_seconds=300,
        purpose='login',
        email='no-phone@example.com',
        phone=None,
    )
    assert success is False
    assert 'Phone number is required' in (error or '')
