"""
WhatsApp-channel OTP delivery.

The OTP service already supports email / SMS / both. These tests lock the
WhatsApp channel so apply-chat can offer it without weakening identity
binding:

- ``create_otp_verification`` accepts ``delivery_channel='whatsapp'`` and
  requires a phone.
- ``_send_otp_via_channel`` dispatches WhatsApp separately from SMS/email.
- The generic ``/api/security/otp/request`` still refuses WhatsApp: it only
  knows a caller-supplied phone and cannot prove the caller controls it.
- ``consume_verification`` can bind the verified phone so a code minted for
  one number cannot unlock a different session.
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
    monkeypatch.setenv('PHINS_TEST_MODE', 'true')
    monkeypatch.setenv('PHINS_USE_MOCK_NOTIFICATIONS', 'true')
    yield


def test_otp_security_service_records_whatsapp_channel():
    service = get_otp_security_service()
    result = service.create_otp_verification(
        user_type='applicant',
        user_id='CHAPP-WA-1',
        email='wa-user@example.com',
        purpose=OTPPurpose.PHONE_VERIFICATION,
        ip_address='127.0.0.1',
        phone='+15551234567',
        delivery_channel='whatsapp',
    )
    assert result.success
    data = result.data or {}
    assert data['delivery_channel'] == 'whatsapp'
    assert data['phone'] == '+15551234567'
    assert data['masked_phone'] == _mask_phone('+15551234567')
    assert 'otp_code' in data


def test_otp_security_service_rejects_whatsapp_without_phone():
    service = get_otp_security_service()
    result = service.create_otp_verification(
        user_type='applicant',
        user_id='CHAPP-WA-2',
        email='no-phone@example.com',
        purpose=OTPPurpose.PHONE_VERIFICATION,
        ip_address='127.0.0.1',
        delivery_channel='whatsapp',
    )
    assert result.success is False
    assert result.error_code == 'MISSING_PHONE'


def test_handle_otp_request_refuses_whatsapp_channel():
    # Same hijack reason as SMS: this endpoint trusts a caller-supplied phone.
    status, payload = api_extensions.handle_otp_request(
        client_ip='127.0.0.1',
        body_data={
            'email': 'wa-route@example.com',
            'phone': '+15551237890',
            'delivery_channel': 'whatsapp',
            'purpose': 'login',
            'user_type': 'customer',
        },
        user_agent='pytest',
    )
    assert status == 400
    assert payload.get('error_code') == 'UNSUPPORTED_CHANNEL'


def test_send_otp_via_channel_whatsapp_only_path(monkeypatch):
    sent = {'email': False, 'sms': False, 'whatsapp': False}

    def _fake_email(**kwargs):
        sent['email'] = kwargs
        return True, None

    def _fake_sms(**kwargs):
        sent['sms'] = kwargs
        return True, None

    def _fake_whatsapp(**kwargs):
        sent['whatsapp'] = kwargs
        return True, None

    monkeypatch.setattr(api_extensions, '_send_otp_email', _fake_email)
    monkeypatch.setattr(api_extensions, '_send_otp_sms', _fake_sms)
    monkeypatch.setattr(api_extensions, '_send_otp_whatsapp', _fake_whatsapp)

    success, error = api_extensions._send_otp_via_channel(
        delivery_channel='whatsapp',
        otp_code='123456',
        expiry_seconds=300,
        purpose='phone_verification',
        email='only-wa@example.com',
        phone='+15551112222',
    )
    assert success is True
    assert error is None
    assert sent['whatsapp']['phone'] == '+15551112222'
    assert sent['whatsapp']['otp_code'] == '123456'
    assert sent['email'] is False
    assert sent['sms'] is False


def test_send_otp_via_channel_whatsapp_requires_phone(monkeypatch):
    monkeypatch.setattr(
        api_extensions, '_send_otp_email', lambda **kwargs: (True, None)
    )
    success, error = api_extensions._send_otp_via_channel(
        delivery_channel='whatsapp',
        otp_code='123456',
        expiry_seconds=300,
        purpose='phone_verification',
        email='no-phone@example.com',
        phone=None,
    )
    assert success is False
    assert 'WhatsApp' in (error or '') or 'phone' in (error or '').lower()


def test_consume_verification_binds_expected_phone():
    service = get_otp_security_service()
    created = service.create_otp_verification(
        user_type='applicant',
        user_id='CHAPP-WA-BIND',
        email='bind@example.com',
        purpose=OTPPurpose.PHONE_VERIFICATION,
        ip_address='127.0.0.1',
        phone='+15550001111',
        delivery_channel='whatsapp',
    )
    assert created.success
    code = created.data['otp_code']
    vid = created.verification_id
    verified = service.verify_otp(vid, code, ip_address='127.0.0.1')
    assert verified.success

    mismatch = service.consume_verification(
        vid,
        expected_email='bind@example.com',
        expected_purpose=OTPPurpose.PHONE_VERIFICATION,
        expected_phone='+15559998888',
        expected_user_type='applicant',
    )
    assert mismatch.success is False
    assert mismatch.error_code == 'PHONE_MISMATCH'

    ok = service.consume_verification(
        vid,
        expected_email='bind@example.com',
        expected_purpose=OTPPurpose.PHONE_VERIFICATION,
        expected_phone='+1-555-000-1111',
        expected_user_type='applicant',
    )
    assert ok.success
