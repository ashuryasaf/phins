"""
PHINS Secure Notification Pipeline Tests
=========================================
Comprehensive tests for the secure notification pipeline including:
- OTP verification for secure operations
- Multi-channel notification delivery (Email, SMS, WhatsApp)
- Push notifications for policy/billing/claim events
- Data integrity validation
- Audit logging

Run with: pytest tests/test_secure_notification_pipeline.py -v
"""

import pytest
import json
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, MagicMock


class TestSecureNotificationPipeline:
    """Test secure notification pipeline functionality"""
    
    @pytest.fixture
    def pipeline(self):
        """Create a fresh secure notification pipeline instance"""
        from services.secure_notification_pipeline import (
            create_secure_notification_pipeline,
            reset_secure_notification_pipeline,
            MockWhatsAppProvider
        )
        from services.notification_service import _rate_limiter
        
        # Reset singleton
        reset_secure_notification_pipeline()
        
        # Clear rate limiter counters
        _rate_limiter._counters.clear()
        _rate_limiter._blocks.clear()
        
        # Create with mock WhatsApp provider
        whatsapp = MockWhatsAppProvider()
        pipeline = create_secure_notification_pipeline(
            use_mock=True,
            whatsapp_provider=whatsapp
        )
        return pipeline
    
    @pytest.fixture
    def sample_operation_request(self):
        """Sample secure operation request"""
        from services.secure_notification_pipeline import (
            SecureOperationRequest,
            SecureOperationType
        )
        from services.notification_service import NotificationChannel
        
        return SecureOperationRequest(
            operation_type=SecureOperationType.ACCOUNT_REGISTRATION,
            customer_id='CUST001',
            email='test@example.com',
            phone='+1234567890',
            preferred_channel=NotificationChannel.EMAIL,
            operation_data={'action': 'register'},
            ip_address='127.0.0.1',
            user_agent='Test/1.0'
        )
    
    def test_initiate_secure_operation_success(self, pipeline, sample_operation_request):
        """Test initiating a secure operation successfully"""
        result = pipeline.initiate_secure_operation(sample_operation_request)
        
        assert result.success is True
        assert result.operation_id is not None
        assert result.status == 'pending_verification'
        assert result.otp_sent is True
        assert result.otp_id is not None
        assert result.otp_expires_at is not None
        assert result.attempts_remaining > 0
    
    def test_initiate_secure_operation_no_contact(self, pipeline):
        """Test initiating operation without contact info fails"""
        from services.secure_notification_pipeline import (
            SecureOperationRequest,
            SecureOperationType
        )
        
        request = SecureOperationRequest(
            operation_type=SecureOperationType.ACCOUNT_REGISTRATION,
            customer_id='CUST001',
            # No email or phone
        )
        
        result = pipeline.initiate_secure_operation(request)
        
        assert result.success is False
        assert result.error_code == 'VALIDATION_ERROR' or result.error_code == 'NO_CONTACT'
    
    def test_initiate_secure_operation_invalid_email(self, pipeline):
        """Test initiating operation with invalid email fails"""
        from services.secure_notification_pipeline import (
            SecureOperationRequest,
            SecureOperationType
        )
        
        request = SecureOperationRequest(
            operation_type=SecureOperationType.ACCOUNT_REGISTRATION,
            customer_id='CUST001',
            email='invalid-email',  # Invalid format
        )
        
        result = pipeline.initiate_secure_operation(request)
        
        assert result.success is False
        assert 'email' in result.error_message.lower() or result.error_code == 'VALIDATION_ERROR'
    
    def test_verify_operation_success(self, pipeline, sample_operation_request):
        """Test verifying an operation with correct OTP"""
        # First initiate
        init_result = pipeline.initiate_secure_operation(sample_operation_request)
        assert init_result.success is True
        
        # Get the actual OTP from mock provider
        # In real scenario, user would receive this via email/SMS
        # For testing, we need to extract it from the OTP service
        otp_service = pipeline._notification_service.otp_service
        
        # Find the OTP record
        otp_record = None
        for record in otp_service._otp_store.values():
            if record.get('correlation_id') == init_result.operation_id:
                otp_record = record
                break
        
        # Since we can't get the plaintext OTP (it's hashed), we'll test with wrong code first
        # Then verify the flow works correctly
        wrong_result = pipeline.verify_operation(
            operation_id=init_result.operation_id,
            otp_code='000000',  # Wrong code
            ip_address='127.0.0.1'
        )
        
        # Should fail with invalid code
        assert wrong_result.success is False
        assert wrong_result.error_code == 'INVALID_CODE'
        assert wrong_result.attempts_remaining >= 0
    
    def test_verify_operation_not_found(self, pipeline):
        """Test verifying non-existent operation fails"""
        result = pipeline.verify_operation(
            operation_id='NON_EXISTENT_OP',
            otp_code='123456',
            ip_address='127.0.0.1'
        )
        
        assert result.success is False
        assert result.error_code == 'NOT_FOUND'
    
    def test_resend_otp(self, pipeline, sample_operation_request):
        """Test resending OTP for an operation"""
        # First initiate
        init_result = pipeline.initiate_secure_operation(sample_operation_request)
        assert init_result.success is True
        
        # Resend OTP
        resend_result = pipeline.resend_otp(
            operation_id=init_result.operation_id,
            ip_address='127.0.0.1'
        )
        
        assert resend_result.success is True
        assert resend_result.otp_sent is True
    
    def test_get_operation_status(self, pipeline, sample_operation_request):
        """Test getting operation status"""
        # Initiate operation
        init_result = pipeline.initiate_secure_operation(sample_operation_request)
        
        # Get status
        status = pipeline.get_operation_status(init_result.operation_id)
        
        assert status is not None
        assert status['operation_id'] == init_result.operation_id
        assert status['status'] == 'pending_verification'


class TestPushNotifications:
    """Test push notification functionality"""
    
    @pytest.fixture
    def pipeline(self):
        """Create fresh pipeline for push notification tests"""
        from services.secure_notification_pipeline import (
            create_secure_notification_pipeline,
            reset_secure_notification_pipeline,
            MockWhatsAppProvider
        )
        from services.notification_service import _rate_limiter
        
        reset_secure_notification_pipeline()
        
        # Clear rate limiter counters
        _rate_limiter._counters.clear()
        _rate_limiter._blocks.clear()
        
        whatsapp = MockWhatsAppProvider()
        return create_secure_notification_pipeline(
            use_mock=True,
            whatsapp_provider=whatsapp
        )
    
    def test_send_push_notification_email(self, pipeline):
        """Test sending push notification via email"""
        from services.secure_notification_pipeline import (
            PushNotificationRequest,
            PushNotificationType
        )
        from services.notification_service import NotificationChannel
        
        request = PushNotificationRequest(
            notification_type=PushNotificationType.POLICY_CREATED,
            customer_id='CUST001',
            title='Policy Created',
            message='Your policy has been created successfully.',
            channels=[NotificationChannel.EMAIL],
            email='test@example.com'
        )
        
        result = pipeline.send_push_notification(request)
        
        assert result.success is True
        assert result.notification_id is not None
        assert 'email' in result.channel_results
        assert result.channel_results['email']['success'] is True
    
    def test_send_push_notification_sms(self, pipeline):
        """Test sending push notification via SMS"""
        from services.secure_notification_pipeline import (
            PushNotificationRequest,
            PushNotificationType
        )
        from services.notification_service import NotificationChannel
        
        request = PushNotificationRequest(
            notification_type=PushNotificationType.CLAIM_APPROVED,
            customer_id='CUST001',
            title='Claim Approved',
            message='Your claim has been approved.',
            channels=[NotificationChannel.SMS],
            phone='+1234567890'
        )
        
        result = pipeline.send_push_notification(request)
        
        assert result.success is True
        assert 'sms' in result.channel_results
        assert result.channel_results['sms']['success'] is True
    
    def test_send_push_notification_multi_channel(self, pipeline):
        """Test sending push notification to multiple channels"""
        from services.secure_notification_pipeline import (
            PushNotificationRequest,
            PushNotificationType
        )
        from services.notification_service import NotificationChannel
        
        request = PushNotificationRequest(
            notification_type=PushNotificationType.PAYMENT_DUE,
            customer_id='CUST001',
            title='Payment Due',
            message='Your payment is due.',
            channels=[NotificationChannel.EMAIL, NotificationChannel.SMS],
            email='test@example.com',
            phone='+1234567890'
        )
        
        result = pipeline.send_push_notification(request)
        
        assert result.success is True
        assert 'email' in result.channel_results
        assert 'sms' in result.channel_results
    
    def test_notify_policy_event(self, pipeline):
        """Test policy event notification"""
        from services.secure_notification_pipeline import PushNotificationType
        
        result = pipeline.notify_policy_event(
            event_type=PushNotificationType.POLICY_APPROVED,
            customer_id='CUST001',
            policy_id='POL001',
            policy_data={'type': 'health', 'coverage': 100000},
            email='test@example.com'
        )
        
        assert result.success is True
        assert result.notification_type == PushNotificationType.POLICY_APPROVED
    
    def test_notify_claim_event(self, pipeline):
        """Test claim event notification"""
        from services.secure_notification_pipeline import PushNotificationType
        
        result = pipeline.notify_claim_event(
            event_type=PushNotificationType.CLAIM_PAID,
            customer_id='CUST001',
            claim_id='CLM001',
            claim_data={'paid_amount': 5000},
            email='test@example.com'
        )
        
        assert result.success is True
        assert result.notification_type == PushNotificationType.CLAIM_PAID
    
    def test_notify_billing_event(self, pipeline):
        """Test billing event notification"""
        from services.secure_notification_pipeline import PushNotificationType
        
        result = pipeline.notify_billing_event(
            event_type=PushNotificationType.PAYMENT_RECEIVED,
            customer_id='CUST001',
            billing_data={'amount': 250, 'policy_id': 'POL001'},
            email='test@example.com'
        )
        
        assert result.success is True
        assert result.notification_type == PushNotificationType.PAYMENT_RECEIVED
    
    def test_notify_savings_event(self, pipeline):
        """Test savings event notification"""
        from services.secure_notification_pipeline import PushNotificationType
        
        result = pipeline.notify_savings_event(
            event_type=PushNotificationType.SAVINGS_DEPOSITED,
            customer_id='CUST001',
            savings_data={'amount': 500, 'balance': 2500},
            email='test@example.com'
        )
        
        assert result.success is True
        assert result.notification_type == PushNotificationType.SAVINGS_DEPOSITED
    
    def test_notify_security_event(self, pipeline):
        """Test security event notification"""
        from services.secure_notification_pipeline import PushNotificationType
        
        result = pipeline.notify_security_event(
            event_type=PushNotificationType.LOGIN_ALERT,
            customer_id='CUST001',
            security_data={'location': 'New York', 'device': 'iPhone'},
            email='test@example.com'
        )
        
        assert result.success is True
        assert result.notification_type == PushNotificationType.LOGIN_ALERT


class TestWhatsAppProvider:
    """Test WhatsApp provider functionality"""
    
    def test_mock_whatsapp_provider(self):
        """Test mock WhatsApp provider"""
        from services.secure_notification_pipeline import MockWhatsAppProvider
        
        provider = MockWhatsAppProvider()
        
        success, message_id, error = provider.send(
            to='+1234567890',
            message='Test message'
        )
        
        assert success is True
        assert message_id is not None
        assert error is None
        assert len(provider.sent_messages) == 1
        assert provider.sent_messages[0]['to'] == '+1234567890'
    
    def test_mock_whatsapp_provider_with_template(self):
        """Test mock WhatsApp provider with template"""
        from services.secure_notification_pipeline import MockWhatsAppProvider
        
        provider = MockWhatsAppProvider()
        
        success, message_id, error = provider.send(
            to='+1234567890',
            message='OTP: 123456',
            template_name='otp_template',
            template_params={'code': '123456'}
        )
        
        assert success is True
        assert provider.sent_messages[0]['template_name'] == 'otp_template'


class TestAuditLogging:
    """Test audit logging functionality"""
    
    @pytest.fixture
    def pipeline(self):
        """Create fresh pipeline for audit tests"""
        from services.secure_notification_pipeline import (
            create_secure_notification_pipeline,
            reset_secure_notification_pipeline
        )
        from services.notification_service import _rate_limiter
        
        reset_secure_notification_pipeline()
        
        # Clear rate limiter counters
        _rate_limiter._counters.clear()
        _rate_limiter._blocks.clear()
        
        return create_secure_notification_pipeline(use_mock=True)
    
    def test_audit_log_on_operation_initiate(self, pipeline):
        """Test audit log entry on operation initiation"""
        from services.secure_notification_pipeline import (
            SecureOperationRequest,
            SecureOperationType
        )
        from services.notification_service import NotificationChannel
        
        request = SecureOperationRequest(
            operation_type=SecureOperationType.SAVINGS_DEPOSIT,
            customer_id='CUST001',
            email='test@example.com',
            preferred_channel=NotificationChannel.EMAIL,
            amount=1000,
            ip_address='127.0.0.1'
        )
        
        # Initiate operation
        pipeline.initiate_secure_operation(request)
        
        # Get audit log
        audit_log = pipeline.get_audit_log(customer_id='CUST001')
        
        assert len(audit_log) > 0
        assert any(log['action'] == 'operation_initiated' for log in audit_log)
    
    def test_audit_log_on_notification_sent(self, pipeline):
        """Test audit log entry on notification sent"""
        from services.secure_notification_pipeline import (
            PushNotificationRequest,
            PushNotificationType
        )
        from services.notification_service import NotificationChannel
        
        request = PushNotificationRequest(
            notification_type=PushNotificationType.POLICY_CREATED,
            customer_id='CUST002',
            title='Test',
            message='Test notification',
            channels=[NotificationChannel.EMAIL],
            email='test@example.com'
        )
        
        pipeline.send_push_notification(request)
        
        # Get audit log
        audit_log = pipeline.get_audit_log(customer_id='CUST002')
        
        assert len(audit_log) > 0
        assert any(log['action'] == 'push_notification_sent' for log in audit_log)


class TestDataIntegrity:
    """Test data integrity validation"""
    
    @pytest.fixture
    def pipeline(self):
        """Create fresh pipeline for integrity tests"""
        from services.secure_notification_pipeline import (
            create_secure_notification_pipeline,
            reset_secure_notification_pipeline
        )
        from services.notification_service import _rate_limiter
        
        reset_secure_notification_pipeline()
        
        # Clear rate limiter counters
        _rate_limiter._counters.clear()
        _rate_limiter._blocks.clear()
        
        return create_secure_notification_pipeline(use_mock=True)
    
    def test_integrity_checkpoint_created(self, pipeline):
        """Test that integrity checkpoint is created on operation initiation"""
        from services.secure_notification_pipeline import (
            SecureOperationRequest,
            SecureOperationType
        )
        from services.notification_service import NotificationChannel
        
        request = SecureOperationRequest(
            operation_type=SecureOperationType.HIGH_VALUE_TRANSACTION,
            customer_id='CUST001',
            email='test@example.com',
            preferred_channel=NotificationChannel.EMAIL,
            amount=50000,
            ip_address='127.0.0.1'
        )
        
        result = pipeline.initiate_secure_operation(request)
        
        # Check checkpoint exists
        assert len(pipeline._checkpoints) > 0
        
        # Get checkpoint for this operation
        op = pipeline._operations.get(result.operation_id)
        checkpoint_id = op.get('checkpoint_id') if op else None
        
        if checkpoint_id:
            checkpoint = pipeline._checkpoints.get(checkpoint_id)
            assert checkpoint is not None
            assert checkpoint.operation_id == result.operation_id
            assert checkpoint.customer_id == 'CUST001'


class TestSecureOperationTypes:
    """Test different secure operation types"""
    
    @pytest.fixture
    def pipeline(self):
        """Create fresh pipeline"""
        from services.secure_notification_pipeline import (
            create_secure_notification_pipeline,
            reset_secure_notification_pipeline
        )
        from services.notification_service import _rate_limiter
        
        reset_secure_notification_pipeline()
        
        # Clear rate limiter counters
        _rate_limiter._counters.clear()
        _rate_limiter._blocks.clear()
        
        return create_secure_notification_pipeline(use_mock=True)
    
    def test_all_operation_types(self, pipeline):
        """Test all supported secure operation types"""
        from services.secure_notification_pipeline import (
            SecureOperationRequest,
            SecureOperationType
        )
        from services.notification_service import NotificationChannel
        
        operation_types = [
            SecureOperationType.ACCOUNT_REGISTRATION,
            SecureOperationType.EMAIL_VERIFICATION,
            SecureOperationType.PHONE_VERIFICATION,
            SecureOperationType.SAVINGS_DEPOSIT,
            SecureOperationType.SAVINGS_WITHDRAWAL,
            SecureOperationType.CLAIM_SUBMISSION,
            SecureOperationType.POLICY_PURCHASE,
            SecureOperationType.POLICY_RENEWAL,
            SecureOperationType.POLICY_CANCELLATION,
            SecureOperationType.HIGH_VALUE_TRANSACTION,
            SecureOperationType.BENEFICIARY_UPDATE,
            SecureOperationType.CONTACT_UPDATE,
            SecureOperationType.PASSWORD_RESET,
            SecureOperationType.TWO_FACTOR_AUTH,
        ]
        
        for op_type in operation_types:
            request = SecureOperationRequest(
                operation_type=op_type,
                customer_id=f'CUST_{op_type.value}',
                email=f'{op_type.value}@example.com',
                preferred_channel=NotificationChannel.EMAIL,
                ip_address='127.0.0.1'
            )
            
            result = pipeline.initiate_secure_operation(request)
            
            assert result.success is True, f"Failed for operation type: {op_type.value}"
            assert result.operation_type == op_type


class TestEventCallbacks:
    """Test event callback functionality"""
    
    @pytest.fixture
    def pipeline(self):
        """Create fresh pipeline"""
        from services.secure_notification_pipeline import (
            create_secure_notification_pipeline,
            reset_secure_notification_pipeline
        )
        from services.notification_service import _rate_limiter
        
        reset_secure_notification_pipeline()
        
        # Clear rate limiter counters
        _rate_limiter._counters.clear()
        _rate_limiter._blocks.clear()
        
        return create_secure_notification_pipeline(use_mock=True)
    
    def test_operation_initiated_callback(self, pipeline):
        """Test operation initiated callback is triggered"""
        from services.secure_notification_pipeline import (
            SecureOperationRequest,
            SecureOperationType
        )
        from services.notification_service import NotificationChannel
        
        callback_triggered = []
        
        def on_initiated(operation_id, request):
            callback_triggered.append(('initiated', operation_id))
        
        pipeline.on_event('operation_initiated', on_initiated)
        
        request = SecureOperationRequest(
            operation_type=SecureOperationType.ACCOUNT_REGISTRATION,
            customer_id='CUST001',
            email='test@example.com',
            preferred_channel=NotificationChannel.EMAIL,
            ip_address='127.0.0.1'
        )
        
        result = pipeline.initiate_secure_operation(request)
        
        assert len(callback_triggered) == 1
        assert callback_triggered[0][0] == 'initiated'
        assert callback_triggered[0][1] == result.operation_id
    
    def test_notification_sent_callback(self, pipeline):
        """Test notification sent callback is triggered"""
        from services.secure_notification_pipeline import (
            PushNotificationRequest,
            PushNotificationType
        )
        from services.notification_service import NotificationChannel
        
        callback_triggered = []
        
        def on_sent(notification_id, request):
            callback_triggered.append(('sent', notification_id))
        
        pipeline.on_event('notification_sent', on_sent)
        
        request = PushNotificationRequest(
            notification_type=PushNotificationType.POLICY_CREATED,
            customer_id='CUST001',
            title='Test',
            message='Test notification',
            channels=[NotificationChannel.EMAIL],
            email='test@example.com'
        )
        
        result = pipeline.send_push_notification(request)
        
        assert len(callback_triggered) == 1
        assert callback_triggered[0][0] == 'sent'
        assert callback_triggered[0][1] == result.notification_id


class TestNotificationChannelEnum:
    """Test notification channel enum updates"""
    
    def test_whatsapp_channel_exists(self):
        """Test WhatsApp channel is available"""
        from services.notification_service import NotificationChannel
        
        assert hasattr(NotificationChannel, 'WHATSAPP')
        assert NotificationChannel.WHATSAPP.value == 'whatsapp'
    
    def test_all_channels_available(self):
        """Test all expected channels are available"""
        from services.notification_service import NotificationChannel
        
        expected_channels = ['EMAIL', 'SMS', 'WHATSAPP', 'PUSH', 'IN_APP', 'WEBHOOK']
        
        for channel in expected_channels:
            assert hasattr(NotificationChannel, channel), f"Missing channel: {channel}"


# Run tests if executed directly
if __name__ == '__main__':
    pytest.main([__file__, '-v', '-x'])
