"""
Tests for SMS and Email Validation for Customer Data Integrity

Covers:
- Customer model verification fields
- Phone format validation at registration
- OTP request via email and SMS channels
- OTP verification and customer record update
- Contact update with re-verification reset
- Data integrity invariants
"""

import os
import sys
import pytest
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

os.environ.setdefault('PHINS_TEST_MODE', '1')
os.environ.setdefault('PHINS_EXPOSE_DEMO_OTP', '1')

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.otp_security_service import (
    OTPSecurityService,
    OTPPurpose,
    VerificationStatus,
    OTPSecurityConfig,
    get_otp_security_service,
    reset_otp_security_service,
    generate_otp,
    hash_otp,
    mask_email,
)


@pytest.fixture(autouse=True)
def fresh_otp_service():
    """Reset OTP singleton before each test."""
    reset_otp_security_service()
    yield
    reset_otp_security_service()


# ============================================================================
# CUSTOMER MODEL VERIFICATION FIELDS
# ============================================================================

class TestCustomerModelVerificationFields:
    """Verify Customer model has verification columns."""

    def test_customer_model_has_email_verified(self):
        from database.models import Customer
        assert hasattr(Customer, 'email_verified')
        assert hasattr(Customer, 'email_verified_at')

    def test_customer_model_has_phone_verified(self):
        from database.models import Customer
        assert hasattr(Customer, 'phone_verified')
        assert hasattr(Customer, 'phone_verified_at')

    def test_to_dict_includes_verification(self):
        from database.models import Customer
        c = Customer(
            id='CUST-TEST-001',
            name='Test User',
            email='test@example.com',
        )
        d = c.to_dict()
        assert 'email_verified' in d
        assert 'phone_verified' in d
        assert 'email_verified_at' in d
        assert 'phone_verified_at' in d
        assert d['email_verified'] is False
        assert d['phone_verified'] is False


# ============================================================================
# CUSTOMER REPOSITORY VERIFICATION METHODS
# ============================================================================

class TestCustomerRepositoryMethods:
    """Verify repository has verification helper methods."""

    def test_repository_has_set_email_verified(self):
        from database.repositories.customer_repository import CustomerRepository
        assert hasattr(CustomerRepository, 'set_email_verified')

    def test_repository_has_set_phone_verified(self):
        from database.repositories.customer_repository import CustomerRepository
        assert hasattr(CustomerRepository, 'set_phone_verified')

    def test_repository_has_reset_email_verification(self):
        from database.repositories.customer_repository import CustomerRepository
        assert hasattr(CustomerRepository, 'reset_email_verification')

    def test_repository_has_reset_phone_verification(self):
        from database.repositories.customer_repository import CustomerRepository
        assert hasattr(CustomerRepository, 'reset_phone_verification')


# ============================================================================
# OTP SERVICE - EMAIL CHANNEL
# ============================================================================

class TestOTPEmailVerification:
    """OTP verification via email channel."""

    def test_create_email_otp(self):
        svc = get_otp_security_service()
        result = svc.create_otp_verification(
            user_type='customer',
            user_id='CUST-001',
            email='user@example.com',
            purpose=OTPPurpose.EMAIL_VERIFICATION,
            ip_address='127.0.0.1',
        )
        assert result.success is True
        assert result.verification_id is not None
        assert result.data is not None
        assert 'otp_code' in result.data

    def test_verify_email_otp_success(self):
        svc = get_otp_security_service()
        create = svc.create_otp_verification(
            user_type='customer',
            user_id='CUST-002',
            email='user2@example.com',
            purpose=OTPPurpose.EMAIL_VERIFICATION,
        )
        otp_code = create.data['otp_code']

        verify = svc.verify_otp(
            verification_id=create.verification_id,
            otp_code=otp_code,
        )
        assert verify.success is True
        assert verify.data['purpose'] == 'email_verification'

    def test_verify_email_otp_wrong_code(self):
        svc = get_otp_security_service()
        create = svc.create_otp_verification(
            user_type='customer',
            user_id='CUST-003',
            email='user3@example.com',
            purpose=OTPPurpose.EMAIL_VERIFICATION,
        )

        verify = svc.verify_otp(
            verification_id=create.verification_id,
            otp_code='000000',
        )
        assert verify.success is False
        assert verify.error_code == 'INVALID_OTP'

    def test_consume_verification_success(self):
        svc = get_otp_security_service()
        create = svc.create_otp_verification(
            user_type='customer',
            user_id='CUST-004',
            email='user4@example.com',
            purpose=OTPPurpose.EMAIL_VERIFICATION,
        )
        otp_code = create.data['otp_code']
        svc.verify_otp(verification_id=create.verification_id, otp_code=otp_code)

        consume = svc.consume_verification(
            verification_id=create.verification_id,
            expected_email='user4@example.com',
            expected_purpose=OTPPurpose.EMAIL_VERIFICATION,
        )
        assert consume.success is True

    def test_consume_verification_prevents_replay(self):
        svc = get_otp_security_service()
        create = svc.create_otp_verification(
            user_type='customer',
            user_id='CUST-005',
            email='user5@example.com',
            purpose=OTPPurpose.EMAIL_VERIFICATION,
        )
        otp_code = create.data['otp_code']
        svc.verify_otp(verification_id=create.verification_id, otp_code=otp_code)

        first = svc.consume_verification(
            verification_id=create.verification_id,
            expected_purpose=OTPPurpose.EMAIL_VERIFICATION,
        )
        assert first.success is True

        second = svc.consume_verification(
            verification_id=create.verification_id,
            expected_purpose=OTPPurpose.EMAIL_VERIFICATION,
        )
        assert second.success is False
        assert second.error_code == 'OTP_ALREADY_USED'


# ============================================================================
# OTP SERVICE - PHONE / SMS CHANNEL
# ============================================================================

class TestOTPPhoneVerification:
    """OTP verification for phone/SMS purpose."""

    def test_create_phone_otp(self):
        svc = get_otp_security_service()
        result = svc.create_otp_verification(
            user_type='customer',
            user_id='CUST-010',
            email='+15551234567',
            purpose=OTPPurpose.PHONE_VERIFICATION,
            ip_address='127.0.0.1',
        )
        assert result.success is True
        assert 'otp_code' in result.data

    def test_verify_phone_otp_success(self):
        svc = get_otp_security_service()
        create = svc.create_otp_verification(
            user_type='customer',
            user_id='CUST-011',
            email='+15551234568',
            purpose=OTPPurpose.PHONE_VERIFICATION,
        )
        otp_code = create.data['otp_code']

        verify = svc.verify_otp(
            verification_id=create.verification_id,
            otp_code=otp_code,
        )
        assert verify.success is True
        assert verify.data['purpose'] == 'phone_verification'


# ============================================================================
# OTP REQUEST HANDLER - MULTI-CHANNEL
# ============================================================================

class TestHandleOTPRequestMultiChannel:
    """Test that handle_otp_request supports email and sms channels."""

    def test_email_channel_default(self):
        from web_portal.api_extensions import handle_otp_request
        status, data = handle_otp_request(
            client_ip='127.0.0.1',
            body_data={
                'email': 'chan@example.com',
                'purpose': 'email_verification',
            },
        )
        assert status == 200
        assert data.get('success') is True
        assert data.get('channel', 'email') == 'email'

    def test_sms_channel(self):
        from web_portal.api_extensions import handle_otp_request
        status, data = handle_otp_request(
            client_ip='127.0.0.1',
            body_data={
                'channel': 'sms',
                'phone': '+15559990001',
                'purpose': 'phone_verification',
            },
        )
        assert status == 200
        assert data.get('success') is True
        assert data.get('channel') == 'sms'

    def test_sms_channel_requires_phone(self):
        from web_portal.api_extensions import handle_otp_request
        status, data = handle_otp_request(
            client_ip='127.0.0.1',
            body_data={
                'channel': 'sms',
                'purpose': 'phone_verification',
            },
        )
        assert status == 400
        assert 'Phone' in data.get('error', '') or 'phone' in data.get('error', '').lower()


# ============================================================================
# CUSTOMER VERIFY-CONTACT HANDLER
# ============================================================================

class TestHandleCustomerVerifyContact:
    """Test POST /api/customer/verify-contact handler."""

    def _verified_verification_id(self, purpose=OTPPurpose.EMAIL_VERIFICATION, identifier='verify@test.com'):
        svc = get_otp_security_service()
        create = svc.create_otp_verification(
            user_type='customer',
            user_id='CUST-VERIFY-01',
            email=identifier,
            purpose=purpose,
        )
        svc.verify_otp(
            verification_id=create.verification_id,
            otp_code=create.data['otp_code'],
        )
        return create.verification_id

    def _session(self, customer_id='CUST-VERIFY-01'):
        return {'user': 'testuser', 'customer_id': customer_id}

    def test_verify_email_updates_customer(self):
        from web_portal.api_extensions import handle_customer_verify_contact
        vid = self._verified_verification_id()
        customers = {
            'CUST-VERIFY-01': {
                'id': 'CUST-VERIFY-01',
                'email': 'verify@test.com',
                'email_verified': False,
                'email_verified_at': None,
            }
        }

        status, data = handle_customer_verify_contact(
            client_ip='127.0.0.1',
            body_data={
                'verification_id': vid,
                'channel': 'email',
            },
            session_data=self._session('CUST-VERIFY-01'),
            customers_store=customers,
        )
        assert status == 200
        assert data['success'] is True
        assert data['email_verified'] is True
        assert customers['CUST-VERIFY-01']['email_verified'] is True
        assert customers['CUST-VERIFY-01']['email_verified_at'] is not None

    def test_verify_phone_updates_customer(self):
        from web_portal.api_extensions import handle_customer_verify_contact
        vid = self._verified_verification_id(
            purpose=OTPPurpose.PHONE_VERIFICATION,
            identifier='+15559990099'
        )
        customers = {
            'CUST-VERIFY-02': {
                'id': 'CUST-VERIFY-02',
                'phone': '+15559990099',
                'phone_verified': False,
                'phone_verified_at': None,
            }
        }

        status, data = handle_customer_verify_contact(
            client_ip='127.0.0.1',
            body_data={
                'verification_id': vid,
                'channel': 'sms',
            },
            session_data=self._session('CUST-VERIFY-02'),
            customers_store=customers,
        )
        assert status == 200
        assert data['success'] is True
        assert data['phone_verified'] is True
        assert customers['CUST-VERIFY-02']['phone_verified'] is True

    def test_reject_invalid_verification_id(self):
        from web_portal.api_extensions import handle_customer_verify_contact
        status, data = handle_customer_verify_contact(
            client_ip='127.0.0.1',
            body_data={
                'verification_id': 'BOGUS-ID',
                'channel': 'email',
            },
            session_data=self._session('CUST-001'),
        )
        assert status == 400
        assert data['success'] is False

    def test_reject_missing_fields(self):
        from web_portal.api_extensions import handle_customer_verify_contact
        status, data = handle_customer_verify_contact(
            client_ip='127.0.0.1',
            body_data={},
            session_data=self._session('CUST-001'),
        )
        assert status == 400

    def test_reject_unauthenticated(self):
        from web_portal.api_extensions import handle_customer_verify_contact
        status, data = handle_customer_verify_contact(
            client_ip='127.0.0.1',
            body_data={'verification_id': 'X', 'channel': 'email'},
        )
        assert status == 401


# ============================================================================
# CUSTOMER CONTACT UPDATE WITH RE-VERIFICATION
# ============================================================================

class TestHandleCustomerUpdateContact:
    """Test PUT /api/customer/contact handler."""

    def _session(self, customer_id):
        return {'user': 'testuser', 'customer_id': customer_id}

    def test_email_change_resets_verification(self):
        from web_portal.api_extensions import handle_customer_update_contact
        customers = {
            'CUST-UPD-01': {
                'id': 'CUST-UPD-01',
                'email': 'old@example.com',
                'email_verified': True,
                'email_verified_at': '2025-01-01T00:00:00',
                'phone': '+15551112222',
                'phone_verified': True,
                'phone_verified_at': '2025-01-01T00:00:00',
            }
        }

        status, data = handle_customer_update_contact(
            client_ip='127.0.0.1',
            body_data={
                'email': 'new@example.com',
            },
            session_data=self._session('CUST-UPD-01'),
            customers_store=customers,
        )
        assert status == 200
        assert data['success'] is True
        assert 'email' in data['verification_needed']
        assert customers['CUST-UPD-01']['email'] == 'new@example.com'
        assert customers['CUST-UPD-01']['email_verified'] is False
        assert customers['CUST-UPD-01']['email_verified_at'] is None
        # Phone should remain verified
        assert customers['CUST-UPD-01']['phone_verified'] is True

    def test_phone_change_resets_verification(self):
        from web_portal.api_extensions import handle_customer_update_contact
        customers = {
            'CUST-UPD-02': {
                'id': 'CUST-UPD-02',
                'email': 'user@example.com',
                'email_verified': True,
                'email_verified_at': '2025-01-01T00:00:00',
                'phone': '+15551112222',
                'phone_verified': True,
                'phone_verified_at': '2025-01-01T00:00:00',
            }
        }

        status, data = handle_customer_update_contact(
            client_ip='127.0.0.1',
            body_data={
                'phone': '+15559998888',
            },
            session_data=self._session('CUST-UPD-02'),
            customers_store=customers,
        )
        assert status == 200
        assert 'sms' in data['verification_needed']
        assert customers['CUST-UPD-02']['phone_verified'] is False
        # Email should remain verified
        assert customers['CUST-UPD-02']['email_verified'] is True

    def test_same_email_no_reset(self):
        from web_portal.api_extensions import handle_customer_update_contact
        customers = {
            'CUST-UPD-03': {
                'id': 'CUST-UPD-03',
                'email': 'same@example.com',
                'email_verified': True,
                'email_verified_at': '2025-01-01T00:00:00',
                'phone': '',
                'phone_verified': False,
                'phone_verified_at': None,
            }
        }

        status, data = handle_customer_update_contact(
            client_ip='127.0.0.1',
            body_data={
                'email': 'same@example.com',
            },
            session_data=self._session('CUST-UPD-03'),
            customers_store=customers,
        )
        assert status == 200
        assert len(data.get('verification_needed', [])) == 0
        assert customers['CUST-UPD-03']['email_verified'] is True

    def test_invalid_email_rejected(self):
        from web_portal.api_extensions import handle_customer_update_contact
        status, data = handle_customer_update_contact(
            client_ip='127.0.0.1',
            body_data={
                'email': 'not-an-email',
            },
            session_data=self._session('CUST-001'),
        )
        assert status == 400

    def test_invalid_phone_rejected(self):
        from web_portal.api_extensions import handle_customer_update_contact
        status, data = handle_customer_update_contact(
            client_ip='127.0.0.1',
            body_data={
                'phone': 'abc',
            },
            session_data=self._session('CUST-001'),
        )
        assert status == 400

    def test_reject_unauthenticated(self):
        from web_portal.api_extensions import handle_customer_update_contact
        status, data = handle_customer_update_contact(
            client_ip='127.0.0.1',
            body_data={'email': 'new@example.com'},
        )
        assert status == 401


# ============================================================================
# DATA INTEGRITY INVARIANTS
# ============================================================================

class TestDataIntegrityInvariants:
    """Ensure verification state transitions are consistent."""

    def test_verified_at_null_when_not_verified(self):
        from database.models import Customer
        c = Customer(id='CUST-DI-01', name='Test', email='di@test.com')
        d = c.to_dict()
        assert d['email_verified'] is False
        assert d['email_verified_at'] is None
        assert d['phone_verified'] is False
        assert d['phone_verified_at'] is None

    def test_otp_single_use_enforcement(self):
        """A consumed verification cannot be reused for a different customer."""
        svc = get_otp_security_service()
        create = svc.create_otp_verification(
            user_type='customer',
            user_id='CUST-DI-02',
            email='di2@test.com',
            purpose=OTPPurpose.EMAIL_VERIFICATION,
        )
        svc.verify_otp(verification_id=create.verification_id, otp_code=create.data['otp_code'])
        first = svc.consume_verification(verification_id=create.verification_id)
        assert first.success is True

        second = svc.consume_verification(verification_id=create.verification_id)
        assert second.success is False

    def test_expired_otp_cannot_verify(self):
        """Expired OTP must not be accepted."""
        svc = get_otp_security_service()
        create = svc.create_otp_verification(
            user_type='customer',
            user_id='CUST-DI-03',
            email='di3@test.com',
            purpose=OTPPurpose.EMAIL_VERIFICATION,
        )
        vid = create.verification_id

        # Manually expire
        with svc._lock:
            v = svc._verifications[vid]
            v.expires_at = datetime.now(timezone.utc) - __import__('datetime').timedelta(seconds=1)

        verify = svc.verify_otp(verification_id=vid, otp_code=create.data['otp_code'])
        assert verify.success is False
        assert verify.error_code == 'OTP_EXPIRED'

    def test_max_attempts_blocks_verification(self):
        """Exceeding max attempts must block the verification."""
        svc = get_otp_security_service()
        create = svc.create_otp_verification(
            user_type='customer',
            user_id='CUST-DI-04',
            email='di4@test.com',
            purpose=OTPPurpose.EMAIL_VERIFICATION,
        )
        vid = create.verification_id

        for _ in range(OTPSecurityConfig.OTP_MAX_ATTEMPTS + 1):
            svc.verify_otp(verification_id=vid, otp_code='999999')

        final = svc.verify_otp(verification_id=vid, otp_code=create.data['otp_code'])
        assert final.success is False

    def test_purpose_mismatch_rejected(self):
        """Consuming with wrong purpose must fail."""
        svc = get_otp_security_service()
        create = svc.create_otp_verification(
            user_type='customer',
            user_id='CUST-DI-05',
            email='di5@test.com',
            purpose=OTPPurpose.LOGIN,
        )
        svc.verify_otp(verification_id=create.verification_id, otp_code=create.data['otp_code'])

        consume = svc.consume_verification(
            verification_id=create.verification_id,
            expected_purpose=OTPPurpose.PHONE_VERIFICATION,
        )
        assert consume.success is False
        assert consume.error_code == 'PURPOSE_MISMATCH'


# ============================================================================
# PHONE FORMAT VALIDATION
# ============================================================================

class TestPhoneFormatValidation:
    """Test phone format validation from notification_service."""

    def test_valid_e164_phone(self):
        from services.notification_service import validate_phone
        assert validate_phone('+15551234567') is True

    def test_valid_international_phone(self):
        from services.notification_service import validate_phone
        assert validate_phone('+442071234567') is True

    def test_invalid_phone_too_short(self):
        from services.notification_service import validate_phone
        assert validate_phone('123') is False

    def test_invalid_phone_letters(self):
        from services.notification_service import validate_phone
        assert validate_phone('abcdefghij') is False

    def test_empty_phone(self):
        from services.notification_service import validate_phone
        assert validate_phone('') is False


# ============================================================================
# NOTIFICATION SERVICE SMS PATH
# ============================================================================

class TestNotificationServiceSMSPath:
    """Verify SMS OTP path exists in notification service."""

    def test_otp_service_handles_sms_channel(self):
        from services.notification_service import (
            OTPService, OTPRequest, NotificationChannel, VerificationType,
            MockSMSProvider, MockEmailProvider,
        )
        svc = OTPService(
            email_provider=MockEmailProvider(),
            sms_provider=MockSMSProvider(),
        )
        result = svc.generate_and_send(OTPRequest(
            identifier='+15551112222',
            channel=NotificationChannel.SMS,
            verification_type=VerificationType.PHONE_VERIFICATION,
            customer_id='CUST-SMS-01',
        ))
        assert result.success is True
        assert result.otp_id is not None

    def test_otp_service_rejects_invalid_phone_for_sms(self):
        from services.notification_service import (
            OTPService, OTPRequest, NotificationChannel, VerificationType,
            MockSMSProvider, MockEmailProvider,
        )
        svc = OTPService(
            email_provider=MockEmailProvider(),
            sms_provider=MockSMSProvider(),
        )
        result = svc.generate_and_send(OTPRequest(
            identifier='not-a-phone',
            channel=NotificationChannel.SMS,
            verification_type=VerificationType.PHONE_VERIFICATION,
        ))
        assert result.success is False
        assert result.error_code == 'INVALID_PHONE'
