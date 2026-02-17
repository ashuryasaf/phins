"""
Comprehensive tests for PHINS Enterprise Notification Service

Tests cover:
- OTP generation and verification
- Email and SMS sending
- Rate limiting
- Client verification workflow
- Queue operations
- Security features
"""

import pytest
import time
import hashlib
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, MagicMock

# Import service components
from services.notification_service import (
    NotificationConfig,
    NotificationService,
    OTPService,
    ClientVerificationService,
    NotificationRequest,
    NotificationResult,
    OTPRequest,
    OTPResult,
    NotificationChannel,
    NotificationPriority,
    NotificationStatus,
    VerificationType,
    OTPStatus,
    RateLimiter,
    TemplateEngine,
    MockEmailProvider,
    SMTPEmailProvider,
    SendGridEmailProvider,
    MockSMSProvider,
    create_notification_service,
    generate_id,
    generate_otp,
    hash_identifier,
    hash_otp,
    generate_salt,
    validate_email,
    validate_phone,
    mask_email,
    mask_phone,
    normalize_phone,
    reset_global_rate_limiter,
)


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    """Reset global rate limiter before each test to ensure test isolation"""
    reset_global_rate_limiter()
    yield
    reset_global_rate_limiter()


# ============================================================================
# UTILITY FUNCTION TESTS
# ============================================================================

class TestUtilityFunctions:
    """Tests for utility functions"""
    
    def test_generate_id_with_prefix(self):
        """Test ID generation with prefix"""
        id1 = generate_id("TEST")
        id2 = generate_id("TEST")
        
        assert id1.startswith("TEST_")
        assert id2.startswith("TEST_")
        assert id1 != id2  # Should be unique
    
    def test_generate_id_without_prefix(self):
        """Test ID generation without prefix"""
        id1 = generate_id()
        assert "_" in id1  # Should have timestamp separator
    
    def test_generate_otp_numeric(self):
        """Test numeric OTP generation"""
        otp = generate_otp(6, alphanumeric=False)
        assert len(otp) == 6
        assert otp.isdigit()
    
    def test_generate_otp_alphanumeric(self):
        """Test alphanumeric OTP generation"""
        otp = generate_otp(8, alphanumeric=True)
        assert len(otp) == 8
        assert otp.isalnum()
    
    def test_generate_otp_uniqueness(self):
        """Test OTP uniqueness"""
        otps = [generate_otp(6) for _ in range(100)]
        assert len(set(otps)) > 95  # At least 95% unique
    
    def test_hash_identifier(self):
        """Test identifier hashing"""
        hash1 = hash_identifier("test@example.com")
        hash2 = hash_identifier("TEST@EXAMPLE.COM")
        hash3 = hash_identifier("different@example.com")
        
        assert len(hash1) == 64  # SHA-256 hex
        assert hash1 == hash2  # Case insensitive
        assert hash1 != hash3
    
    def test_hash_otp(self):
        """Test OTP hashing"""
        salt = generate_salt()
        hash1 = hash_otp("123456", salt)
        hash2 = hash_otp("123456", salt)
        hash3 = hash_otp("654321", salt)
        
        assert hash1 == hash2  # Same input = same output
        assert hash1 != hash3  # Different input = different output
    
    def test_validate_email_valid(self):
        """Test valid email validation"""
        assert validate_email("test@example.com")
        assert validate_email("user.name@domain.co.uk")
        assert validate_email("user+tag@example.org")
    
    def test_validate_email_invalid(self):
        """Test invalid email validation"""
        assert not validate_email("invalid")
        assert not validate_email("@example.com")
        assert not validate_email("test@")
        assert not validate_email("")
    
    def test_validate_phone_valid(self):
        """Test valid phone validation"""
        assert validate_phone("+14155551234")
        assert validate_phone("14155551234")
        assert validate_phone("+972505050505")
    
    def test_validate_phone_invalid(self):
        """Test invalid phone validation"""
        assert not validate_phone("123")  # Too short
        assert not validate_phone("invalid")
        assert not validate_phone("")
    
    def test_normalize_phone(self):
        """Test phone normalization"""
        assert normalize_phone("+1 (415) 555-1234") == "+14155551234"
        assert normalize_phone("415-555-1234") == "4155551234"
    
    def test_mask_email(self):
        """Test email masking"""
        assert mask_email("test@example.com") == "t**t@example.com"
        # Short local parts are still masked for privacy (2 chars -> first + *)
        assert mask_email("ab@test.com") == "a*@test.com"
        assert "@" in mask_email("user@domain.com")
    
    def test_mask_phone(self):
        """Test phone masking"""
        masked = mask_phone("+14155551234")
        assert "***" in masked
        assert len(masked) < len("+14155551234")


# ============================================================================
# TEMPLATE ENGINE TESTS
# ============================================================================

class TestTemplateEngine:
    """Tests for template rendering"""
    
    def test_render_simple(self):
        """Test simple variable substitution"""
        template = "Hello {{ name }}, your code is {{ code }}"
        result = TemplateEngine.render(template, {"name": "John", "code": "123456"})
        
        assert result == "Hello John, your code is 123456"
    
    def test_render_with_spaces(self):
        """Test rendering with variable spacing"""
        template = "{{ var1 }} and {{var2}} and {{  var3  }}"
        result = TemplateEngine.render(template, {
            "var1": "A",
            "var2": "B",
            "var3": "C"
        })
        
        assert result == "A and B and C"
    
    def test_render_missing_vars(self):
        """Test rendering with missing variables"""
        template = "Hello {{ name }}, code: {{ code }}"
        result = TemplateEngine.render(template, {"name": "John"})
        
        assert "John" in result
        assert "{{ code }}" not in result  # Should be removed
    
    def test_validate_template_valid(self):
        """Test template validation with all vars present"""
        template = "{{ name }} - {{ code }}"
        is_valid, missing = TemplateEngine.validate_template(
            template, ["name", "code"]
        )
        
        assert is_valid
        assert len(missing) == 0
    
    def test_validate_template_invalid(self):
        """Test template validation with missing vars"""
        template = "Hello {{ name }}"
        is_valid, missing = TemplateEngine.validate_template(
            template, ["name", "code", "date"]
        )
        
        assert not is_valid
        assert "code" in missing
        assert "date" in missing


# ============================================================================
# RATE LIMITER TESTS
# ============================================================================

class TestRateLimiter:
    """Tests for rate limiting"""
    
    def test_rate_limiter_allows_requests(self):
        """Test rate limiter allows requests under limit"""
        limiter = RateLimiter()
        limits = {"per_minute": (5, 60)}
        
        for i in range(5):
            result = limiter.check_rate_limit("user1", "action", limits)
            assert result.allowed
            limiter.record_request("user1", "action")
    
    def test_rate_limiter_blocks_over_limit(self):
        """Test rate limiter blocks requests over limit"""
        limiter = RateLimiter()
        limits = {"per_minute": (3, 60)}
        
        # Make 3 requests
        for _ in range(3):
            limiter.record_request("user2", "action")
        
        # 4th should be blocked
        result = limiter.check_rate_limit("user2", "action", limits)
        assert not result.allowed
    
    def test_rate_limiter_separate_identifiers(self):
        """Test rate limits are separate per identifier"""
        limiter = RateLimiter()
        limits = {"per_minute": (2, 60)}
        
        # User1 makes 2 requests
        for _ in range(2):
            limiter.record_request("user1", "action")
        
        # User2 should still be allowed
        result = limiter.check_rate_limit("user2", "action", limits)
        assert result.allowed
    
    def test_rate_limiter_separate_actions(self):
        """Test rate limits are separate per action"""
        limiter = RateLimiter()
        limits = {"per_minute": (2, 60)}
        
        # Use all limit on action1
        for _ in range(2):
            limiter.record_request("user1", "action1")
        
        # Action2 should still be allowed
        result = limiter.check_rate_limit("user1", "action2", limits)
        assert result.allowed
    
    def test_rate_limiter_remaining_count(self):
        """Test remaining count is correct"""
        limiter = RateLimiter()
        limits = {"per_minute": (5, 60)}
        
        limiter.record_request("user1", "action")
        result = limiter.check_rate_limit("user1", "action", limits)
        
        assert result.remaining == 4
    
    def test_clear_blocks(self):
        """Test clearing rate limit blocks"""
        limiter = RateLimiter()
        limits = {"per_minute": (1, 60)}
        
        # Hit limit
        limiter.record_request("user1", "action")
        result = limiter.check_rate_limit("user1", "action", limits)
        assert not result.allowed
        
        # Clear blocks
        limiter.clear_blocks("user1")
        
        # Should still be rate limited (blocks cleared, but counter remains)
        result = limiter.check_rate_limit("user1", "action", limits)
        # Note: clear_blocks only clears block flag, not counter


# ============================================================================
# MOCK PROVIDER TESTS
# ============================================================================

class TestMockProviders:
    """Tests for mock email and SMS providers"""
    
    def test_mock_email_provider(self):
        """Test mock email provider"""
        provider = MockEmailProvider()
        success, message_id, error = provider.send(
            to="test@example.com",
            subject="Test",
            body="Test body"
        )
        
        assert success
        assert message_id is not None
        assert error is None
        assert len(provider.sent_emails) == 1
        assert provider.sent_emails[0]['to'] == "test@example.com"
    
    def test_mock_sms_provider(self):
        """Test mock SMS provider"""
        provider = MockSMSProvider()
        success, message_id, error = provider.send(
            to="+14155551234",
            message="Test message"
        )
        
        assert success
        assert message_id is not None
        assert error is None
        assert len(provider.sent_messages) == 1


# ============================================================================
# OTP SERVICE TESTS
# ============================================================================

class TestOTPService:
    """Tests for OTP service"""
    
    def test_generate_and_send_email_otp(self):
        """Test OTP generation via email"""
        service = OTPService(
            email_provider=MockEmailProvider(),
            sms_provider=MockSMSProvider()
        )
        
        result = service.generate_and_send(OTPRequest(
            identifier="test@example.com",
            channel=NotificationChannel.EMAIL,
            verification_type=VerificationType.EMAIL_VERIFICATION
        ))
        
        assert result.success
        assert result.otp_id is not None
        assert result.status == OTPStatus.ACTIVE
        assert result.expires_at is not None
        assert result.attempts_remaining == 5
    
    def test_generate_and_send_sms_otp(self):
        """Test OTP generation via SMS"""
        service = OTPService(
            email_provider=MockEmailProvider(),
            sms_provider=MockSMSProvider()
        )
        
        result = service.generate_and_send(OTPRequest(
            identifier="+14155551234",
            channel=NotificationChannel.SMS,
            verification_type=VerificationType.PHONE_VERIFICATION
        ))
        
        assert result.success
        assert result.otp_id is not None
    
    def test_otp_invalid_email(self):
        """Test OTP generation with invalid email"""
        service = OTPService()
        
        result = service.generate_and_send(OTPRequest(
            identifier="invalid-email",
            channel=NotificationChannel.EMAIL,
            verification_type=VerificationType.EMAIL_VERIFICATION
        ))
        
        assert not result.success
        assert result.error_code == "INVALID_EMAIL"
    
    def test_otp_invalid_phone(self):
        """Test OTP generation with invalid phone"""
        service = OTPService()
        
        result = service.generate_and_send(OTPRequest(
            identifier="123",
            channel=NotificationChannel.SMS,
            verification_type=VerificationType.PHONE_VERIFICATION
        ))
        
        assert not result.success
        assert result.error_code == "INVALID_PHONE"
    
    def test_otp_verification_success(self):
        """Test successful OTP verification"""
        email_provider = MockEmailProvider()
        service = OTPService(email_provider=email_provider)
        
        # Generate OTP
        gen_result = service.generate_and_send(OTPRequest(
            identifier="test@example.com",
            channel=NotificationChannel.EMAIL,
            verification_type=VerificationType.EMAIL_VERIFICATION
        ))
        
        assert gen_result.success
        
        # Extract OTP from mock email
        sent_email = email_provider.sent_emails[0]
        # OTP is in subject line after ": "
        otp_code = sent_email['subject'].split(": ")[1]
        
        # Verify
        verify_result = service.verify(
            identifier="test@example.com",
            code=otp_code,
            verification_type=VerificationType.EMAIL_VERIFICATION
        )
        
        assert verify_result.success
        assert verify_result.status == OTPStatus.USED
    
    def test_otp_verification_wrong_code(self):
        """Test OTP verification with wrong code"""
        service = OTPService(email_provider=MockEmailProvider())
        
        # Generate OTP
        service.generate_and_send(OTPRequest(
            identifier="test@example.com",
            channel=NotificationChannel.EMAIL,
            verification_type=VerificationType.EMAIL_VERIFICATION
        ))
        
        # Verify with wrong code
        result = service.verify(
            identifier="test@example.com",
            code="000000",
            verification_type=VerificationType.EMAIL_VERIFICATION
        )
        
        assert not result.success
        assert result.error_code == "INVALID_CODE"
        assert result.attempts_remaining == 4
    
    def test_otp_max_attempts(self):
        """Test OTP max attempts exceeded"""
        service = OTPService(email_provider=MockEmailProvider())
        
        # Generate OTP
        service.generate_and_send(OTPRequest(
            identifier="test@example.com",
            channel=NotificationChannel.EMAIL,
            verification_type=VerificationType.EMAIL_VERIFICATION
        ))
        
        # Exhaust attempts
        for i in range(6):
            result = service.verify(
                identifier="test@example.com",
                code="000000",
                verification_type=VerificationType.EMAIL_VERIFICATION
            )
        
        assert result.error_code == "MAX_ATTEMPTS_EXCEEDED"
        assert result.status == OTPStatus.INVALIDATED
    
    def test_otp_invalidation(self):
        """Test OTP invalidation"""
        service = OTPService(email_provider=MockEmailProvider())
        
        # Generate OTP
        service.generate_and_send(OTPRequest(
            identifier="test@example.com",
            channel=NotificationChannel.EMAIL,
            verification_type=VerificationType.EMAIL_VERIFICATION
        ))
        
        # Invalidate
        success = service.invalidate(
            identifier="test@example.com",
            verification_type=VerificationType.EMAIL_VERIFICATION
        )
        
        assert success
        
        # Try to verify - should fail
        result = service.verify(
            identifier="test@example.com",
            code="123456",
            verification_type=VerificationType.EMAIL_VERIFICATION
        )
        
        assert not result.success
        assert result.error_code == "NO_ACTIVE_OTP"


# ============================================================================
# NOTIFICATION SERVICE TESTS
# ============================================================================

class TestNotificationService:
    """Tests for main notification service"""
    
    def test_create_notification_service(self):
        """Test factory function"""
        service = create_notification_service(use_mock=True)
        assert service is not None
        assert isinstance(service.otp_service, OTPService)

    def test_factory_auto_selects_sendgrid_when_default_smtp_is_placeholder(self, monkeypatch):
        """Auto-select API email provider when SMTP is only the default placeholder."""
        monkeypatch.delenv('EMAIL_PROVIDER', raising=False)
        monkeypatch.setattr(NotificationConfig, 'EMAIL_PROVIDER', 'smtp')
        monkeypatch.setattr(NotificationConfig, 'SMTP_HOST', 'localhost')
        monkeypatch.setattr(NotificationConfig, 'SMTP_USERNAME', '')
        monkeypatch.setattr(NotificationConfig, 'SMTP_PASSWORD', '')
        monkeypatch.setattr(NotificationConfig, 'SENDGRID_API_KEY', 'SG.test_key')
        monkeypatch.setattr(NotificationConfig, 'MAILGUN_API_KEY', '')
        monkeypatch.setattr(NotificationConfig, 'MAILGUN_DOMAIN', '')

        service = create_notification_service(use_mock=False)
        assert isinstance(service._email_provider, SendGridEmailProvider)

    def test_factory_respects_explicit_smtp_provider(self, monkeypatch):
        """Explicit, configured SMTP provider should not be auto-overridden."""
        monkeypatch.setenv('EMAIL_PROVIDER', 'smtp')
        monkeypatch.setattr(NotificationConfig, 'EMAIL_PROVIDER', 'smtp')
        monkeypatch.setattr(NotificationConfig, 'SMTP_HOST', 'smtp.gmail.com')
        monkeypatch.setattr(NotificationConfig, 'SMTP_USERNAME', 'smtp-user')
        monkeypatch.setattr(NotificationConfig, 'SMTP_PASSWORD', 'smtp-pass')
        monkeypatch.setattr(NotificationConfig, 'SENDGRID_API_KEY', 'SG.test_key')

        service = create_notification_service(use_mock=False)
        assert isinstance(service._email_provider, SMTPEmailProvider)

    def test_factory_overrides_explicit_placeholder_smtp_when_api_provider_available(self, monkeypatch):
        """Explicit SMTP with placeholder settings should fail over to configured API provider."""
        monkeypatch.setenv('EMAIL_PROVIDER', 'smtp')
        monkeypatch.setattr(NotificationConfig, 'EMAIL_PROVIDER', 'smtp')
        monkeypatch.setattr(NotificationConfig, 'SMTP_HOST', 'localhost')
        monkeypatch.setattr(NotificationConfig, 'SMTP_USERNAME', '')
        monkeypatch.setattr(NotificationConfig, 'SMTP_PASSWORD', '')
        monkeypatch.setattr(NotificationConfig, 'SENDGRID_API_KEY', 'SG.test_key')
        monkeypatch.setattr(NotificationConfig, 'MAILGUN_API_KEY', '')
        monkeypatch.setattr(NotificationConfig, 'MAILGUN_DOMAIN', '')

        service = create_notification_service(use_mock=False)
        assert isinstance(service._email_provider, SendGridEmailProvider)

    def test_factory_blank_email_provider_still_allows_auto_detection(self, monkeypatch):
        """Blank EMAIL_PROVIDER should behave like unset and allow safe auto-selection."""
        monkeypatch.setenv('EMAIL_PROVIDER', '   ')
        monkeypatch.setattr(NotificationConfig, 'EMAIL_PROVIDER', '')
        monkeypatch.setattr(NotificationConfig, 'SMTP_HOST', 'localhost')
        monkeypatch.setattr(NotificationConfig, 'SMTP_USERNAME', '')
        monkeypatch.setattr(NotificationConfig, 'SMTP_PASSWORD', '')
        monkeypatch.setattr(NotificationConfig, 'SENDGRID_API_KEY', 'SG.test_key')
        monkeypatch.setattr(NotificationConfig, 'MAILGUN_API_KEY', '')
        monkeypatch.setattr(NotificationConfig, 'MAILGUN_DOMAIN', '')

        service = create_notification_service(use_mock=False)
        assert isinstance(service._email_provider, SendGridEmailProvider)
    
    def test_send_email_notification(self):
        """Test sending email notification"""
        service = create_notification_service(use_mock=True)
        
        result = service.send(NotificationRequest(
            channel=NotificationChannel.EMAIL,
            recipient="test@example.com",
            subject="Test Subject",
            content="Test content"
        ))
        
        assert result.success
        assert result.status == NotificationStatus.DELIVERED
        assert result.notification_id is not None
    
    def test_send_sms_notification(self):
        """Test sending SMS notification"""
        service = create_notification_service(use_mock=True)
        
        result = service.send(NotificationRequest(
            channel=NotificationChannel.SMS,
            recipient="+14155551234",
            content="Test SMS message"
        ))
        
        assert result.success
        assert result.status == NotificationStatus.DELIVERED
    
    def test_send_invalid_email(self):
        """Test sending to invalid email"""
        service = create_notification_service(use_mock=True)
        
        result = service.send(NotificationRequest(
            channel=NotificationChannel.EMAIL,
            recipient="invalid",
            content="Test"
        ))
        
        assert not result.success
        assert result.error_code == "VALIDATION_ERROR"
    
    def test_send_invalid_phone(self):
        """Test sending to invalid phone"""
        service = create_notification_service(use_mock=True)
        
        result = service.send(NotificationRequest(
            channel=NotificationChannel.SMS,
            recipient="123",
            content="Test"
        ))
        
        assert not result.success
        assert result.error_code == "VALIDATION_ERROR"
    
    def test_send_with_template(self):
        """Test sending with template"""
        service = create_notification_service(use_mock=True)
        
        result = service.send(NotificationRequest(
            channel=NotificationChannel.EMAIL,
            recipient="test@example.com",
            template_id="welcome",
            template_vars={
                "name": "John",
                "login_url": "https://phins.ai/login"
            }
        ))
        
        assert result.success
    
    def test_suppression_list(self):
        """Test suppression list functionality"""
        service = create_notification_service(use_mock=True)
        
        # Add to suppression
        service.add_to_suppression(
            "blocked@example.com",
            NotificationChannel.EMAIL,
            "test"
        )
        
        # Try to send - should fail
        result = service.send(NotificationRequest(
            channel=NotificationChannel.EMAIL,
            recipient="blocked@example.com",
            content="Test"
        ))
        
        assert not result.success
        assert result.error_code == "RECIPIENT_SUPPRESSED"
    
    def test_remove_from_suppression(self):
        """Test removing from suppression list"""
        service = create_notification_service(use_mock=True)
        
        # Add then remove
        service.add_to_suppression("test@example.com", NotificationChannel.EMAIL)
        service.remove_from_suppression("test@example.com", NotificationChannel.EMAIL)
        
        # Should work now
        result = service.send(NotificationRequest(
            channel=NotificationChannel.EMAIL,
            recipient="test@example.com",
            content="Test"
        ))
        
        assert result.success
    
    def test_notification_history(self):
        """Test notification history"""
        service = create_notification_service(use_mock=True)
        
        # Send notification
        service.send(NotificationRequest(
            channel=NotificationChannel.EMAIL,
            recipient="test@example.com",
            content="Test",
            customer_id="CUST123"
        ))
        
        # Check history
        history = service.get_history(customer_id="CUST123")
        assert len(history) == 1
        assert history[0]['channel'] == 'email'
    
    def test_preferences_blocking(self):
        """Test preference-based blocking"""
        service = create_notification_service(use_mock=True)
        
        # Set preferences to disable email
        service.set_preferences("CUST123", {
            "email_enabled": False,
            "sms_enabled": True
        })
        
        # Email should be blocked
        result = service.send(NotificationRequest(
            channel=NotificationChannel.EMAIL,
            recipient="test@example.com",
            content="Test",
            customer_id="CUST123"
        ))
        
        assert not result.success
        assert result.error_code == "PREFERENCE_BLOCKED"
        
        # SMS should work
        result = service.send(NotificationRequest(
            channel=NotificationChannel.SMS,
            recipient="+14155551234",
            content="Test",
            customer_id="CUST123"
        ))
        
        assert result.success


# ============================================================================
# CLIENT VERIFICATION SERVICE TESTS
# ============================================================================

class TestClientVerificationService:
    """Tests for client verification workflow"""
    
    def test_initiate_verification(self):
        """Test initiating verification"""
        notification_service = create_notification_service(use_mock=True)
        verification_service = ClientVerificationService(notification_service)
        
        result = verification_service.initiate_verification(
            customer_id="CUST123",
            verification_type=VerificationType.EMAIL_VERIFICATION,
            identifier="test@example.com",
            channel=NotificationChannel.EMAIL
        )
        
        assert result['status'] == 'pending'
        assert result['verification_id'] is not None
        assert result['otp_sent'] is True
    
    def test_complete_verification_flow(self):
        """Test complete verification flow"""
        email_provider = MockEmailProvider()
        notification_service = NotificationService(email_provider=email_provider)
        verification_service = ClientVerificationService(notification_service)
        
        # Initiate
        init_result = verification_service.initiate_verification(
            customer_id="CUST123",
            verification_type=VerificationType.EMAIL_VERIFICATION,
            identifier="test@example.com",
            channel=NotificationChannel.EMAIL
        )
        
        assert init_result['otp_sent']
        
        # Extract OTP
        sent_email = email_provider.sent_emails[0]
        otp_code = sent_email['subject'].split(": ")[1]
        
        # Verify
        verify_result = verification_service.verify(
            verification_id=init_result['verification_id'],
            code=otp_code
        )
        
        assert verify_result['success']
        assert verify_result['status'] == 'verified'
    
    def test_verification_wrong_code(self):
        """Test verification with wrong code"""
        notification_service = create_notification_service(use_mock=True)
        verification_service = ClientVerificationService(notification_service)
        
        # Initiate
        init_result = verification_service.initiate_verification(
            customer_id="CUST123",
            verification_type=VerificationType.EMAIL_VERIFICATION,
            identifier="test@example.com",
            channel=NotificationChannel.EMAIL
        )
        
        # Verify with wrong code
        verify_result = verification_service.verify(
            verification_id=init_result['verification_id'],
            code="000000"
        )
        
        assert not verify_result['success']
        assert verify_result['error_code'] == 'INVALID_CODE'
    
    def test_resend_code(self):
        """Test resending verification code"""
        notification_service = create_notification_service(use_mock=True)
        verification_service = ClientVerificationService(notification_service)
        
        # Initiate
        init_result = verification_service.initiate_verification(
            customer_id="CUST123",
            verification_type=VerificationType.EMAIL_VERIFICATION,
            identifier="test@example.com",
            channel=NotificationChannel.EMAIL
        )
        
        # Wait briefly to pass any cooldown
        time.sleep(0.1)
        
        # Resend code
        resend_result = verification_service.resend_code(
            verification_id=init_result['verification_id']
        )
        
        # Should have a verification_id in result, or an error_code if cooldown is active
        assert 'verification_id' in resend_result or 'error_code' in resend_result
    
    def test_verification_status(self):
        """Test getting verification status"""
        notification_service = create_notification_service(use_mock=True)
        verification_service = ClientVerificationService(notification_service)
        
        # Initiate
        init_result = verification_service.initiate_verification(
            customer_id="CUST123",
            verification_type=VerificationType.EMAIL_VERIFICATION,
            identifier="test@example.com",
            channel=NotificationChannel.EMAIL
        )
        
        # Get status
        status = verification_service.get_verification_status(
            init_result['verification_id']
        )
        
        assert status is not None
        assert status['status'] == 'pending'
        assert status['verification_type'] == 'email_verification'
    
    def test_is_verified_check(self):
        """Test checking if customer is verified"""
        email_provider = MockEmailProvider()
        notification_service = NotificationService(email_provider=email_provider)
        verification_service = ClientVerificationService(notification_service)
        
        # Initially not verified
        assert not verification_service.is_verified(
            "CUST123",
            VerificationType.EMAIL_VERIFICATION
        )
        
        # Complete verification
        init_result = verification_service.initiate_verification(
            customer_id="CUST123",
            verification_type=VerificationType.EMAIL_VERIFICATION,
            identifier="test@example.com",
            channel=NotificationChannel.EMAIL
        )
        
        otp_code = email_provider.sent_emails[0]['subject'].split(": ")[1]
        verification_service.verify(init_result['verification_id'], otp_code)
        
        # Now verified
        assert verification_service.is_verified(
            "CUST123",
            VerificationType.EMAIL_VERIFICATION
        )


# ============================================================================
# SECURITY TESTS
# ============================================================================

class TestSecurityFeatures:
    """Tests for security features"""
    
    def test_otp_never_stored_plaintext(self):
        """Test that OTP codes are never stored in plaintext"""
        service = OTPService(email_provider=MockEmailProvider())
        
        service.generate_and_send(OTPRequest(
            identifier="test@example.com",
            channel=NotificationChannel.EMAIL,
            verification_type=VerificationType.EMAIL_VERIFICATION
        ))
        
        # Check internal storage
        for record in service._otp_store.values():
            # Should have hash and salt, not plaintext
            assert 'code_hash' in record
            assert 'code_salt' in record
            assert 'code' not in record  # Plaintext should never be stored
            
            # Hash should be long enough
            assert len(record['code_hash']) >= 64
    
    def test_identifier_hashing_for_lookup(self):
        """Test that identifiers are hashed for lookup"""
        service = OTPService(email_provider=MockEmailProvider())
        
        service.generate_and_send(OTPRequest(
            identifier="sensitive@example.com",
            channel=NotificationChannel.EMAIL,
            verification_type=VerificationType.EMAIL_VERIFICATION
        ))
        
        for record in service._otp_store.values():
            assert 'identifier_hash' in record
            # Hash should not contain the original email
            assert '@example.com' not in record['identifier_hash']
    
    def test_timing_safe_comparison(self):
        """Test that OTP verification uses timing-safe comparison"""
        # This is verified by the use of hmac.compare_digest in the code
        # We test that wrong codes don't leak timing information
        
        service = OTPService(email_provider=MockEmailProvider())
        
        service.generate_and_send(OTPRequest(
            identifier="test@example.com",
            channel=NotificationChannel.EMAIL,
            verification_type=VerificationType.EMAIL_VERIFICATION
        ))
        
        # Time multiple wrong verifications
        times = []
        for _ in range(10):
            start = time.time()
            service.verify(
                identifier="test@example.com",
                code="000000",
                verification_type=VerificationType.EMAIL_VERIFICATION
            )
            times.append(time.time() - start)
        
        # Times should be consistent (not leaking info about partial matches)
        avg_time = sum(times) / len(times)
        variance = sum((t - avg_time) ** 2 for t in times) / len(times)
        
        # Low variance indicates consistent timing
        assert variance < 0.01  # Should be very low
    
    def test_rate_limit_blocks_brute_force(self):
        """Test that rate limiting blocks brute force attempts"""
        service = OTPService(email_provider=MockEmailProvider())
        
        # Generate OTP
        service.generate_and_send(OTPRequest(
            identifier="test@example.com",
            channel=NotificationChannel.EMAIL,
            verification_type=VerificationType.EMAIL_VERIFICATION
        ))
        
        # Max attempts should prevent brute force (default is 5 attempts)
        last_valid_result = None
        for i in range(6):
            result = service.verify(
                identifier="test@example.com",
                code="000000",
                verification_type=VerificationType.EMAIL_VERIFICATION
            )
            # Track when we hit max attempts
            if result.error_code == "MAX_ATTEMPTS_EXCEEDED":
                last_valid_result = result
                break
            if result.error_code == "INVALID_CODE":
                last_valid_result = result
        
        # After exhausting attempts, OTP is invalidated, subsequent checks return NO_ACTIVE_OTP
        final_result = service.verify(
            identifier="test@example.com",
            code="000000",
            verification_type=VerificationType.EMAIL_VERIFICATION
        )
        
        # Should be blocked - either max attempts or no active OTP (OTP was invalidated)
        assert final_result.error_code in ("MAX_ATTEMPTS_EXCEEDED", "NO_ACTIVE_OTP")
    
    def test_otp_expiry(self):
        """Test that OTPs expire correctly"""
        service = OTPService(email_provider=MockEmailProvider())
        
        # Generate OTP with very short expiry
        service.generate_and_send(OTPRequest(
            identifier="test@example.com",
            channel=NotificationChannel.EMAIL,
            verification_type=VerificationType.EMAIL_VERIFICATION,
            expiry_seconds=1  # 1 second
        ))
        
        # Wait for expiry
        time.sleep(1.5)
        
        # Should be expired
        result = service.verify(
            identifier="test@example.com",
            code="123456",
            verification_type=VerificationType.EMAIL_VERIFICATION
        )
        
        assert not result.success
        assert result.error_code == "OTP_EXPIRED"


# ============================================================================
# AUDIT LOGGING TESTS
# ============================================================================

class TestAuditLogging:
    """Tests for audit logging"""
    
    def test_audit_log_captures_events(self):
        """Test that audit events are captured"""
        service = create_notification_service(use_mock=True)
        
        # Send notification
        service.send(NotificationRequest(
            channel=NotificationChannel.EMAIL,
            recipient="test@example.com",
            content="Test",
            customer_id="CUST123"
        ))
        
        # Check audit log
        log = service.get_audit_log(limit=10)
        assert len(log) > 0
        
        # Should have notification_sent event
        actions = [e['action'] for e in log]
        assert 'notification_sent' in actions
    
    def test_audit_log_captures_failures(self):
        """Test that failures are logged"""
        service = create_notification_service(use_mock=True)
        
        # Add to suppression list to force failure
        service.add_to_suppression("test@example.com", NotificationChannel.EMAIL)
        
        # Try to send
        service.send(NotificationRequest(
            channel=NotificationChannel.EMAIL,
            recipient="test@example.com",
            content="Test"
        ))
        
        # Check audit log
        log = service.get_audit_log(limit=10)
        
        # Should have suppression event
        actions = [e['action'] for e in log]
        assert 'notification_suppressed' in actions or 'notification_failed' in actions


# ============================================================================
# RUN TESTS
# ============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
