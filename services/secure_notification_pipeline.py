"""
PHINS Secure Notification Pipeline
===================================
Enterprise-grade notification pipeline with OTP validation for data integrity.

This service provides:
1. OTP validation for critical registry events:
   - Account registration
   - Add savings / deposits
   - New claims
   - New policies
   - Transaction confirmations

2. Multi-channel secure notifications:
   - WhatsApp (via Meta Business API / Twilio)
   - SMS (via Twilio, Vonage, AWS SNS)
   - Email (via SMTP, SendGrid, AWS SES)

3. Push notifications for:
   - New policy documents
   - Monthly/annual billing reports
   - Claim status updates
   - Payment reminders
   - Security alerts

4. Data integrity validation:
   - Pre-operation validation
   - Transaction verification
   - Audit trail
   - Pipeline integrity checks

Security Features:
- All sensitive operations require OTP verification
- Rate limiting per identifier and IP
- Device fingerprinting support
- Comprehensive audit logging
- Encryption of sensitive data
"""

from __future__ import annotations

import os
import json
import hmac
import hashlib
import secrets
import logging
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple, Callable
from functools import wraps
import uuid

# Import notification service
try:
    from services.notification_service import (
        NotificationService,
        NotificationRequest,
        NotificationResult,
        NotificationChannel,
        NotificationPriority,
        NotificationStatus,
        OTPRequest,
        OTPResult,
        VerificationType,
        OTPStatus,
        create_notification_service,
        should_use_mock_notifications,
        generate_id,
        hash_identifier,
        validate_email,
        validate_phone,
        mask_email,
        mask_phone,
    )
except ImportError:
    # Define fallbacks if notification service not available
    NotificationService = None
    create_notification_service = lambda **kwargs: None
    should_use_mock_notifications = lambda: True


logger = logging.getLogger('phins.secure_notification_pipeline')


# ============================================================================
# CONFIGURATION
# ============================================================================

class SecureNotificationConfig:
    """Configuration for secure notification pipeline"""
    
    # Environment
    ENVIRONMENT = os.environ.get('PHINS_ENV', 'development')
    
    # WhatsApp Configuration
    WHATSAPP_ENABLED = os.environ.get('WHATSAPP_ENABLED', 'true').lower() == 'true'
    WHATSAPP_PROVIDER = os.environ.get('WHATSAPP_PROVIDER', 'twilio')  # twilio, meta
    
    # Twilio WhatsApp
    TWILIO_WHATSAPP_NUMBER = os.environ.get('TWILIO_WHATSAPP_NUMBER', '')
    TWILIO_ACCOUNT_SID = os.environ.get('TWILIO_ACCOUNT_SID', '')
    TWILIO_AUTH_TOKEN = os.environ.get('TWILIO_AUTH_TOKEN', '')
    
    # Meta WhatsApp Business API
    META_WHATSAPP_TOKEN = os.environ.get('META_WHATSAPP_TOKEN', '')
    META_WHATSAPP_PHONE_ID = os.environ.get('META_WHATSAPP_PHONE_ID', '')
    META_WHATSAPP_BUSINESS_ID = os.environ.get('META_WHATSAPP_BUSINESS_ID', '')
    
    # OTP Settings for Secure Operations
    SECURE_OTP_LENGTH = int(os.environ.get('SECURE_OTP_LENGTH', '6'))
    SECURE_OTP_EXPIRY_SECONDS = int(os.environ.get('SECURE_OTP_EXPIRY_SECONDS', '300'))  # 5 minutes
    SECURE_OTP_MAX_ATTEMPTS = int(os.environ.get('SECURE_OTP_MAX_ATTEMPTS', '3'))
    
    # Operations requiring OTP verification
    OTP_REQUIRED_OPERATIONS = os.environ.get(
        'OTP_REQUIRED_OPERATIONS', 
        'registration,savings_deposit,claim_submission,policy_purchase,high_value_transaction'
    ).split(',')
    
    # High-value transaction threshold (requires additional verification)
    HIGH_VALUE_THRESHOLD = float(os.environ.get('HIGH_VALUE_THRESHOLD', '10000'))
    
    # Push notification settings
    PUSH_NOTIFICATION_ENABLED = os.environ.get('PUSH_NOTIFICATION_ENABLED', 'true').lower() == 'true'
    
    # Audit settings
    AUDIT_ALL_OPERATIONS = os.environ.get('AUDIT_ALL_OPERATIONS', 'true').lower() == 'true'


# ============================================================================
# ENUMS
# ============================================================================

class SecureOperationType(str, Enum):
    """Types of secure operations requiring OTP verification"""
    ACCOUNT_REGISTRATION = "account_registration"
    EMAIL_VERIFICATION = "email_verification"
    PHONE_VERIFICATION = "phone_verification"
    SAVINGS_DEPOSIT = "savings_deposit"
    SAVINGS_WITHDRAWAL = "savings_withdrawal"
    CLAIM_SUBMISSION = "claim_submission"
    POLICY_PURCHASE = "policy_purchase"
    POLICY_RENEWAL = "policy_renewal"
    POLICY_CANCELLATION = "policy_cancellation"
    HIGH_VALUE_TRANSACTION = "high_value_transaction"
    BENEFICIARY_UPDATE = "beneficiary_update"
    CONTACT_UPDATE = "contact_update"
    PASSWORD_RESET = "password_reset"
    TWO_FACTOR_AUTH = "two_factor_auth"


class PushNotificationType(str, Enum):
    """Types of push notifications"""
    # Policy notifications
    POLICY_CREATED = "policy_created"
    POLICY_APPROVED = "policy_approved"
    POLICY_RENEWED = "policy_renewed"
    POLICY_EXPIRING = "policy_expiring"
    POLICY_DOCUMENT_READY = "policy_document_ready"
    
    # Billing notifications
    PAYMENT_DUE = "payment_due"
    PAYMENT_RECEIVED = "payment_received"
    PAYMENT_FAILED = "payment_failed"
    MONTHLY_STATEMENT = "monthly_statement"
    ANNUAL_STATEMENT = "annual_statement"
    
    # Claims notifications
    CLAIM_SUBMITTED = "claim_submitted"
    CLAIM_UNDER_REVIEW = "claim_under_review"
    CLAIM_APPROVED = "claim_approved"
    CLAIM_REJECTED = "claim_rejected"
    CLAIM_PAID = "claim_paid"
    CLAIM_DOCUMENT_REQUIRED = "claim_document_required"
    
    # Savings notifications
    SAVINGS_DEPOSITED = "savings_deposited"
    SAVINGS_WITHDRAWN = "savings_withdrawn"
    SAVINGS_GOAL_REACHED = "savings_goal_reached"
    INVESTMENT_UPDATE = "investment_update"
    
    # Security notifications
    LOGIN_ALERT = "login_alert"
    SUSPICIOUS_ACTIVITY = "suspicious_activity"
    PASSWORD_CHANGED = "password_changed"
    DEVICE_ADDED = "device_added"


class NotificationDeliveryStatus(str, Enum):
    """Delivery status for tracking"""
    PENDING = "pending"
    SENT = "sent"
    DELIVERED = "delivered"
    READ = "read"
    FAILED = "failed"
    EXPIRED = "expired"


# ============================================================================
# DATA CLASSES
# ============================================================================

@dataclass
class SecureOperationRequest:
    """Request to perform a secure operation requiring OTP verification"""
    operation_type: SecureOperationType
    customer_id: str
    
    # Contact details
    email: Optional[str] = None
    phone: Optional[str] = None
    preferred_channel: NotificationChannel = NotificationChannel.EMAIL
    
    # Operation details
    operation_data: Dict[str, Any] = field(default_factory=dict)
    amount: Optional[float] = None  # For financial operations
    
    # Security context
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    device_fingerprint: Optional[str] = None
    session_id: Optional[str] = None
    
    # Callback
    callback_url: Optional[str] = None
    correlation_id: Optional[str] = None


@dataclass
class SecureOperationResult:
    """Result of a secure operation request"""
    success: bool
    operation_id: str
    operation_type: SecureOperationType
    status: str  # pending_verification, verified, failed, expired
    
    # OTP details
    otp_sent: bool = False
    otp_id: Optional[str] = None
    otp_expires_at: Optional[datetime] = None
    verification_channel: Optional[NotificationChannel] = None
    
    # Error details
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    
    # Verification info
    attempts_remaining: int = 0
    can_resend_at: Optional[datetime] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'success': self.success,
            'operation_id': self.operation_id,
            'operation_type': self.operation_type.value,
            'status': self.status,
            'otp_sent': self.otp_sent,
            'otp_id': self.otp_id,
            'otp_expires_at': self.otp_expires_at.isoformat() if self.otp_expires_at else None,
            'verification_channel': self.verification_channel.value if self.verification_channel else None,
            'error_code': self.error_code,
            'error_message': self.error_message,
            'attempts_remaining': self.attempts_remaining,
            'can_resend_at': self.can_resend_at.isoformat() if self.can_resend_at else None
        }


@dataclass
class PushNotificationRequest:
    """Request to send a push notification"""
    notification_type: PushNotificationType
    customer_id: str
    
    # Content
    title: str
    message: str
    data: Dict[str, Any] = field(default_factory=dict)
    
    # Channels - can send to multiple
    channels: List[NotificationChannel] = field(default_factory=lambda: [NotificationChannel.EMAIL])
    
    # Contact overrides
    email: Optional[str] = None
    phone: Optional[str] = None
    
    # Scheduling
    send_immediately: bool = True
    scheduled_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    
    # Priority
    priority: NotificationPriority = NotificationPriority.NORMAL
    
    # Metadata
    correlation_id: Optional[str] = None
    reference_id: Optional[str] = None  # policy_id, claim_id, etc.


@dataclass
class PushNotificationResult:
    """Result of push notification"""
    success: bool
    notification_id: str
    notification_type: PushNotificationType
    
    # Delivery status per channel
    channel_results: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    
    # Error details
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'success': self.success,
            'notification_id': self.notification_id,
            'notification_type': self.notification_type.value,
            'channel_results': self.channel_results,
            'error_code': self.error_code,
            'error_message': self.error_message
        }


@dataclass
class IntegrityCheckpoint:
    """Checkpoint for data integrity validation"""
    checkpoint_id: str
    operation_id: str
    customer_id: str
    operation_type: str
    
    # Pre-operation state
    pre_state: Dict[str, Any] = field(default_factory=dict)
    
    # Post-operation state (filled after completion)
    post_state: Dict[str, Any] = field(default_factory=dict)
    
    # Integrity validation
    integrity_valid: bool = True
    integrity_hash: str = ""
    discrepancies: List[str] = field(default_factory=list)
    
    # Timestamps
    created_at: datetime = field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    
    def compute_hash(self) -> str:
        """Compute integrity hash of pre/post states"""
        data = json.dumps({
            'pre': self.pre_state,
            'post': self.post_state
        }, sort_keys=True, default=str)
        self.integrity_hash = hashlib.sha256(data.encode()).hexdigest()[:32]
        return self.integrity_hash


# ============================================================================
# WHATSAPP PROVIDER
# ============================================================================

class WhatsAppProvider(ABC):
    """Abstract base class for WhatsApp providers"""
    
    @abstractmethod
    def send(
        self,
        to: str,
        message: str,
        template_name: Optional[str] = None,
        template_params: Optional[Dict[str, str]] = None
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Send a WhatsApp message.
        
        Returns:
            Tuple of (success, message_id, error_message)
        """
        pass


class TwilioWhatsAppProvider(WhatsAppProvider):
    """Twilio-based WhatsApp provider"""
    
    def send(
        self,
        to: str,
        message: str,
        template_name: Optional[str] = None,
        template_params: Optional[Dict[str, str]] = None
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """Send WhatsApp message via Twilio"""
        try:
            # Check credentials
            if not SecureNotificationConfig.TWILIO_ACCOUNT_SID:
                logger.warning("Twilio credentials not configured, using mock")
                return self._mock_send(to, message)
            
            # Import Twilio client
            try:
                from twilio.rest import Client
            except ImportError:
                logger.warning("Twilio library not installed, using mock")
                return self._mock_send(to, message)
            
            client = Client(
                SecureNotificationConfig.TWILIO_ACCOUNT_SID,
                SecureNotificationConfig.TWILIO_AUTH_TOKEN
            )
            
            # Format WhatsApp number
            if not to:
                logger.warning("[BILLING] WhatsApp send called with None/empty recipient")
                return False, None, "Recipient phone number is required"
            whatsapp_to = f"whatsapp:{to}" if not to.startswith('whatsapp:') else to
            whatsapp_from = SecureNotificationConfig.TWILIO_WHATSAPP_NUMBER or ''
            if not whatsapp_from.startswith('whatsapp:'):
                whatsapp_from = f"whatsapp:{whatsapp_from}"
            
            msg = client.messages.create(
                body=message,
                from_=whatsapp_from,
                to=whatsapp_to
            )
            
            return True, msg.sid, None
            
        except Exception as e:
            logger.error(f"Twilio WhatsApp send error: {str(e)}")
            return False, None, str(e)
    
    def _mock_send(self, to: str, message: str) -> Tuple[bool, Optional[str], Optional[str]]:
        """Mock send for development/testing"""
        message_id = f"MOCK_WA_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{secrets.token_hex(4)}"
        logger.info(f"Mock WhatsApp to {to}: {message[:50]}...")
        return True, message_id, None


class MetaWhatsAppProvider(WhatsAppProvider):
    """Meta Business API WhatsApp provider"""
    
    def send(
        self,
        to: str,
        message: str,
        template_name: Optional[str] = None,
        template_params: Optional[Dict[str, str]] = None
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """Send WhatsApp message via Meta Business API"""
        try:
            import requests
            
            # Check credentials
            if not SecureNotificationConfig.META_WHATSAPP_TOKEN:
                logger.warning("Meta WhatsApp credentials not configured, using mock")
                return self._mock_send(to, message)
            
            phone_id = SecureNotificationConfig.META_WHATSAPP_PHONE_ID
            token = SecureNotificationConfig.META_WHATSAPP_TOKEN
            
            url = f"https://graph.facebook.com/v17.0/{phone_id}/messages"
            
            headers = {
                'Authorization': f'Bearer {token}',
                'Content-Type': 'application/json'
            }
            
            # Clean phone number
            clean_phone = ''.join(c for c in to if c.isdigit())
            
            if template_name and template_params:
                # Template message
                payload = {
                    'messaging_product': 'whatsapp',
                    'to': clean_phone,
                    'type': 'template',
                    'template': {
                        'name': template_name,
                        'language': {'code': 'en'},
                        'components': [{
                            'type': 'body',
                            'parameters': [
                                {'type': 'text', 'text': v}
                                for v in template_params.values()
                            ]
                        }]
                    }
                }
            else:
                # Text message
                payload = {
                    'messaging_product': 'whatsapp',
                    'to': clean_phone,
                    'type': 'text',
                    'text': {'body': message}
                }
            
            response = requests.post(url, headers=headers, json=payload, timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                message_id = data.get('messages', [{}])[0].get('id')
                return True, message_id, None
            else:
                error = response.json().get('error', {}).get('message', response.text)
                return False, None, error
                
        except Exception as e:
            logger.error(f"Meta WhatsApp send error: {str(e)}")
            return False, None, str(e)
    
    def _mock_send(self, to: str, message: str) -> Tuple[bool, Optional[str], Optional[str]]:
        """Mock send for development/testing"""
        message_id = f"MOCK_META_WA_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{secrets.token_hex(4)}"
        logger.info(f"Mock Meta WhatsApp to {to}: {message[:50]}...")
        return True, message_id, None


class MockWhatsAppProvider(WhatsAppProvider):
    """Mock WhatsApp provider for testing"""
    
    def __init__(self):
        self.sent_messages: List[Dict[str, Any]] = []
    
    def send(
        self,
        to: str,
        message: str,
        template_name: Optional[str] = None,
        template_params: Optional[Dict[str, str]] = None
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """Store message for testing"""
        message_id = f"MOCK_WA_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{secrets.token_hex(4)}"
        self.sent_messages.append({
            'to': to,
            'message': message,
            'template_name': template_name,
            'template_params': template_params,
            'message_id': message_id,
            'sent_at': datetime.now(timezone.utc).isoformat()
        })
        logger.info(f"Mock WhatsApp to {to}: {message[:50]}...")
        return True, message_id, None


# ============================================================================
# SECURE NOTIFICATION PIPELINE SERVICE
# ============================================================================

class SecureNotificationPipeline:
    """
    Enterprise Secure Notification Pipeline
    
    Features:
    - OTP verification for critical operations
    - Multi-channel delivery (Email, SMS, WhatsApp)
    - Push notifications for updates
    - Data integrity validation
    - Comprehensive audit logging
    """
    
    def __init__(
        self,
        notification_service: Optional[NotificationService] = None,
        whatsapp_provider: Optional[WhatsAppProvider] = None,
        data_integrity_service=None,
        pipeline_integrity_service=None
    ):
        # Core notification service
        self._notification_service = notification_service or create_notification_service(
            use_mock=should_use_mock_notifications()
        )
        
        # WhatsApp provider
        if whatsapp_provider:
            self._whatsapp = whatsapp_provider
        elif SecureNotificationConfig.WHATSAPP_PROVIDER == 'meta':
            self._whatsapp = MetaWhatsAppProvider()
        elif SecureNotificationConfig.WHATSAPP_PROVIDER == 'twilio':
            self._whatsapp = TwilioWhatsAppProvider()
        else:
            self._whatsapp = MockWhatsAppProvider()
        
        # Integrity services
        self._data_integrity = data_integrity_service
        self._pipeline_integrity = pipeline_integrity_service
        
        # Operation tracking
        self._operations: Dict[str, Dict[str, Any]] = {}
        self._operations_lock = threading.Lock()
        
        # Integrity checkpoints
        self._checkpoints: Dict[str, IntegrityCheckpoint] = {}
        
        # Audit log
        self._audit_log: List[Dict[str, Any]] = []
        self._audit_lock = threading.Lock()
        
        # Event callbacks
        self._event_callbacks: Dict[str, List[Callable]] = {
            'operation_initiated': [],
            'operation_verified': [],
            'operation_completed': [],
            'operation_failed': [],
            'notification_sent': [],
        }
        
        # Notification templates
        self._templates = self._load_templates()
    
    # ========== SECURE OPERATIONS API ==========
    
    def initiate_secure_operation(
        self,
        request: SecureOperationRequest
    ) -> SecureOperationResult:
        """
        Initiate a secure operation that requires OTP verification.
        
        Flow:
        1. Validate request
        2. Check if operation requires OTP
        3. Create integrity checkpoint
        4. Generate and send OTP
        5. Return operation ID for verification
        """
        operation_id = f"OP_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{secrets.token_hex(6)}"
        
        # Validate request
        validation = self._validate_operation_request(request)
        if not validation['valid']:
            return SecureOperationResult(
                success=False,
                operation_id=operation_id,
                operation_type=request.operation_type,
                status='failed',
                error_code='VALIDATION_ERROR',
                error_message=validation['error']
            )
        
        # Determine verification channel
        channel = request.preferred_channel
        identifier = request.email if channel == NotificationChannel.EMAIL else request.phone
        
        if not identifier:
            # Fallback to available contact
            if request.email:
                identifier = request.email
                channel = NotificationChannel.EMAIL
            elif request.phone:
                identifier = request.phone
                channel = NotificationChannel.SMS
            else:
                return SecureOperationResult(
                    success=False,
                    operation_id=operation_id,
                    operation_type=request.operation_type,
                    status='failed',
                    error_code='NO_CONTACT',
                    error_message='No email or phone number provided for verification'
                )
        
        # Create integrity checkpoint (pre-operation state)
        checkpoint = self._create_checkpoint(operation_id, request)
        
        # Map operation type to verification type
        verification_type = self._map_to_verification_type(request.operation_type)
        
        # Generate and send OTP
        otp_request = OTPRequest(
            identifier=identifier,
            channel=channel,
            verification_type=verification_type,
            customer_id=request.customer_id,
            ip_address=request.ip_address,
            user_agent=request.user_agent,
            device_fingerprint=request.device_fingerprint,
            otp_length=SecureNotificationConfig.SECURE_OTP_LENGTH,
            expiry_seconds=SecureNotificationConfig.SECURE_OTP_EXPIRY_SECONDS,
            correlation_id=operation_id
        )
        
        otp_result = self._notification_service.send_otp(otp_request)
        
        if not otp_result.success:
            self._audit_operation(
                action='operation_initiation_failed',
                operation_id=operation_id,
                customer_id=request.customer_id,
                details={'error': otp_result.error_message},
                success=False
            )
            return SecureOperationResult(
                success=False,
                operation_id=operation_id,
                operation_type=request.operation_type,
                status='failed',
                error_code=otp_result.error_code,
                error_message=otp_result.error_message
            )
        
        # Store operation details
        with self._operations_lock:
            self._operations[operation_id] = {
                'id': operation_id,
                'customer_id': request.customer_id,
                'operation_type': request.operation_type.value,
                'status': 'pending_verification',
                'identifier': identifier,
                'channel': channel.value,
                'otp_id': otp_result.otp_id,
                'request_data': request.operation_data,
                'amount': request.amount,
                'ip_address': request.ip_address,
                'user_agent': request.user_agent,
                'device_fingerprint': request.device_fingerprint,
                'checkpoint_id': checkpoint.checkpoint_id,
                'created_at': datetime.now(timezone.utc).isoformat(),
                'expires_at': otp_result.expires_at.isoformat() if otp_result.expires_at else None,
                'verified_at': None
            }
        
        # Audit log
        self._audit_operation(
            action='operation_initiated',
            operation_id=operation_id,
            customer_id=request.customer_id,
            details={
                'operation_type': request.operation_type.value,
                'channel': channel.value,
                'identifier_masked': mask_email(identifier) if '@' in identifier else mask_phone(identifier)
            }
        )
        
        # Trigger callbacks
        self._trigger_event('operation_initiated', operation_id, request)
        
        return SecureOperationResult(
            success=True,
            operation_id=operation_id,
            operation_type=request.operation_type,
            status='pending_verification',
            otp_sent=True,
            otp_id=otp_result.otp_id,
            otp_expires_at=otp_result.expires_at,
            verification_channel=channel,
            attempts_remaining=SecureNotificationConfig.SECURE_OTP_MAX_ATTEMPTS,
            can_resend_at=datetime.now(timezone.utc) + timedelta(seconds=60)
        )
    
    def verify_operation(
        self,
        operation_id: str,
        otp_code: str,
        ip_address: Optional[str] = None
    ) -> SecureOperationResult:
        """
        Verify an operation using OTP code.
        
        Flow:
        1. Validate operation exists and is pending
        2. Verify OTP code
        3. Update operation status
        4. Complete integrity checkpoint
        5. Execute post-verification callbacks
        """
        # Get operation
        with self._operations_lock:
            operation = self._operations.get(operation_id)
        
        if not operation:
            return SecureOperationResult(
                success=False,
                operation_id=operation_id,
                operation_type=SecureOperationType.ACCOUNT_REGISTRATION,
                status='failed',
                error_code='NOT_FOUND',
                error_message='Operation not found'
            )
        
        # Check status
        if operation['status'] != 'pending_verification':
            return SecureOperationResult(
                success=False,
                operation_id=operation_id,
                operation_type=SecureOperationType(operation['operation_type']),
                status=operation['status'],
                error_code='INVALID_STATUS',
                error_message=f"Operation is not pending verification (status: {operation['status']})"
            )
        
        # Verify OTP
        verification_type = self._map_to_verification_type(
            SecureOperationType(operation['operation_type'])
        )
        
        otp_result = self._notification_service.verify_otp(
            identifier=operation['identifier'],
            code=otp_code,
            verification_type=verification_type,
            ip_address=ip_address
        )
        
        if not otp_result.success:
            self._audit_operation(
                action='operation_verification_failed',
                operation_id=operation_id,
                customer_id=operation['customer_id'],
                ip_address=ip_address,
                details={
                    'error': otp_result.error_message,
                    'attempts_remaining': otp_result.attempts_remaining
                },
                success=False
            )
            
            return SecureOperationResult(
                success=False,
                operation_id=operation_id,
                operation_type=SecureOperationType(operation['operation_type']),
                status='pending_verification',
                error_code=otp_result.error_code,
                error_message=otp_result.error_message,
                attempts_remaining=otp_result.attempts_remaining
            )
        
        # Update operation status
        with self._operations_lock:
            operation['status'] = 'verified'
            operation['verified_at'] = datetime.now(timezone.utc).isoformat()
        
        # Complete integrity checkpoint
        checkpoint = self._checkpoints.get(operation.get('checkpoint_id'))
        if checkpoint:
            checkpoint.completed_at = datetime.now(timezone.utc)
            checkpoint.compute_hash()
        
        # Audit log
        self._audit_operation(
            action='operation_verified',
            operation_id=operation_id,
            customer_id=operation['customer_id'],
            ip_address=ip_address,
            details={'operation_type': operation['operation_type']}
        )
        
        # Trigger callbacks
        self._trigger_event('operation_verified', operation_id, operation)
        
        return SecureOperationResult(
            success=True,
            operation_id=operation_id,
            operation_type=SecureOperationType(operation['operation_type']),
            status='verified',
            otp_id=otp_result.otp_id
        )
    
    def resend_otp(
        self,
        operation_id: str,
        channel: Optional[NotificationChannel] = None,
        ip_address: Optional[str] = None
    ) -> SecureOperationResult:
        """Resend OTP for an operation"""
        with self._operations_lock:
            operation = self._operations.get(operation_id)
        
        if not operation:
            return SecureOperationResult(
                success=False,
                operation_id=operation_id,
                operation_type=SecureOperationType.ACCOUNT_REGISTRATION,
                status='failed',
                error_code='NOT_FOUND',
                error_message='Operation not found'
            )
        
        if operation['status'] != 'pending_verification':
            return SecureOperationResult(
                success=False,
                operation_id=operation_id,
                operation_type=SecureOperationType(operation['operation_type']),
                status=operation['status'],
                error_code='INVALID_STATUS',
                error_message='Cannot resend OTP for this operation'
            )
        
        # Use new channel if provided, otherwise use original
        use_channel = channel or NotificationChannel(operation['channel'])
        identifier = operation['identifier']
        
        verification_type = self._map_to_verification_type(
            SecureOperationType(operation['operation_type'])
        )
        
        otp_request = OTPRequest(
            identifier=identifier,
            channel=use_channel,
            verification_type=verification_type,
            customer_id=operation['customer_id'],
            ip_address=ip_address,
            correlation_id=operation_id
        )
        
        otp_result = self._notification_service.send_otp(otp_request)
        
        if otp_result.success:
            with self._operations_lock:
                operation['otp_id'] = otp_result.otp_id
                operation['channel'] = use_channel.value
                operation['expires_at'] = otp_result.expires_at.isoformat() if otp_result.expires_at else None
        
        self._audit_operation(
            action='otp_resent',
            operation_id=operation_id,
            customer_id=operation['customer_id'],
            ip_address=ip_address,
            details={'channel': use_channel.value},
            success=otp_result.success
        )
        
        return SecureOperationResult(
            success=otp_result.success,
            operation_id=operation_id,
            operation_type=SecureOperationType(operation['operation_type']),
            status='pending_verification',
            otp_sent=otp_result.success,
            otp_id=otp_result.otp_id,
            otp_expires_at=otp_result.expires_at,
            verification_channel=use_channel,
            error_code=otp_result.error_code,
            error_message=otp_result.error_message,
            can_resend_at=datetime.now(timezone.utc) + timedelta(seconds=60)
        )
    
    def get_operation_status(self, operation_id: str) -> Optional[Dict[str, Any]]:
        """Get the current status of an operation"""
        with self._operations_lock:
            operation = self._operations.get(operation_id)
            if operation:
                return {
                    'operation_id': operation['id'],
                    'operation_type': operation['operation_type'],
                    'status': operation['status'],
                    'created_at': operation['created_at'],
                    'verified_at': operation.get('verified_at'),
                    'expires_at': operation.get('expires_at')
                }
        return None
    
    # ========== PUSH NOTIFICATIONS API ==========
    
    def send_push_notification(
        self,
        request: PushNotificationRequest
    ) -> PushNotificationResult:
        """
        Send push notification across multiple channels.
        
        Supports: Email, SMS, WhatsApp
        """
        notification_id = f"PUSH_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{secrets.token_hex(6)}"
        
        channel_results = {}
        any_success = False
        
        for channel in request.channels:
            result = self._send_to_channel(
                channel=channel,
                notification_type=request.notification_type,
                customer_id=request.customer_id,
                title=request.title,
                message=request.message,
                email=request.email,
                phone=request.phone,
                data=request.data,
                priority=request.priority
            )
            channel_results[channel.value] = result
            if result.get('success'):
                any_success = True
        
        # Audit
        self._audit_operation(
            action='push_notification_sent',
            notification_id=notification_id,
            customer_id=request.customer_id,
            details={
                'notification_type': request.notification_type.value,
                'channels': [c.value for c in request.channels],
                'success_count': sum(1 for r in channel_results.values() if r.get('success'))
            },
            success=any_success
        )
        
        # Trigger callback
        self._trigger_event('notification_sent', notification_id, request)
        
        return PushNotificationResult(
            success=any_success,
            notification_id=notification_id,
            notification_type=request.notification_type,
            channel_results=channel_results
        )
    
    def notify_policy_event(
        self,
        event_type: PushNotificationType,
        customer_id: str,
        policy_id: str,
        policy_data: Dict[str, Any],
        email: Optional[str] = None,
        phone: Optional[str] = None
    ) -> PushNotificationResult:
        """Convenience method for policy-related notifications"""
        templates = {
            PushNotificationType.POLICY_CREATED: {
                'title': 'Policy Created',
                'message': f"Your {policy_data.get('type', 'insurance')} policy has been created. Policy ID: {policy_id}"
            },
            PushNotificationType.POLICY_APPROVED: {
                'title': 'Policy Approved',
                'message': f"Your policy {policy_id} has been approved and is now active."
            },
            PushNotificationType.POLICY_RENEWED: {
                'title': 'Policy Renewed',
                'message': f"Your policy {policy_id} has been successfully renewed."
            },
            PushNotificationType.POLICY_EXPIRING: {
                'title': 'Policy Expiring Soon',
                'message': f"Your policy {policy_id} will expire on {policy_data.get('end_date', 'soon')}. Please renew to maintain coverage."
            },
            PushNotificationType.POLICY_DOCUMENT_READY: {
                'title': 'Policy Document Ready',
                'message': f"Your policy document for {policy_id} is now available for download."
            }
        }
        
        template = templates.get(event_type, {
            'title': 'Policy Update',
            'message': f'Your policy {policy_id} has been updated.'
        })
        
        return self.send_push_notification(PushNotificationRequest(
            notification_type=event_type,
            customer_id=customer_id,
            title=template['title'],
            message=template['message'],
            data={'policy_id': policy_id, **policy_data},
            channels=[NotificationChannel.EMAIL, NotificationChannel.SMS],
            email=email,
            phone=phone,
            priority=NotificationPriority.NORMAL,
            reference_id=policy_id
        ))
    
    def notify_claim_event(
        self,
        event_type: PushNotificationType,
        customer_id: str,
        claim_id: str,
        claim_data: Dict[str, Any],
        email: Optional[str] = None,
        phone: Optional[str] = None
    ) -> PushNotificationResult:
        """Convenience method for claim-related notifications"""
        templates = {
            PushNotificationType.CLAIM_SUBMITTED: {
                'title': 'Claim Submitted',
                'message': f"Your claim {claim_id} has been submitted and is pending review."
            },
            PushNotificationType.CLAIM_UNDER_REVIEW: {
                'title': 'Claim Under Review',
                'message': f"Your claim {claim_id} is currently under review by our team."
            },
            PushNotificationType.CLAIM_APPROVED: {
                'title': 'Claim Approved',
                'message': f"Great news! Your claim {claim_id} has been approved for ${claim_data.get('approved_amount', 0):,.2f}."
            },
            PushNotificationType.CLAIM_REJECTED: {
                'title': 'Claim Decision',
                'message': f"Your claim {claim_id} has been reviewed. Please log in to view the details."
            },
            PushNotificationType.CLAIM_PAID: {
                'title': 'Claim Payment Processed',
                'message': f"Payment for claim {claim_id} has been processed. Amount: ${claim_data.get('paid_amount', 0):,.2f}"
            },
            PushNotificationType.CLAIM_DOCUMENT_REQUIRED: {
                'title': 'Additional Documents Required',
                'message': f"Please provide additional documentation for claim {claim_id}."
            }
        }
        
        template = templates.get(event_type, {
            'title': 'Claim Update',
            'message': f'Your claim {claim_id} has been updated.'
        })
        
        return self.send_push_notification(PushNotificationRequest(
            notification_type=event_type,
            customer_id=customer_id,
            title=template['title'],
            message=template['message'],
            data={'claim_id': claim_id, **claim_data},
            channels=[NotificationChannel.EMAIL, NotificationChannel.SMS],
            email=email,
            phone=phone,
            priority=NotificationPriority.HIGH,
            reference_id=claim_id
        ))
    
    def notify_billing_event(
        self,
        event_type: PushNotificationType,
        customer_id: str,
        billing_data: Dict[str, Any],
        email: Optional[str] = None,
        phone: Optional[str] = None
    ) -> PushNotificationResult:
        """Convenience method for billing-related notifications"""
        amount = billing_data.get('amount', 0)
        due_date = billing_data.get('due_date', 'soon')
        policy_id = billing_data.get('policy_id', '')
        
        templates = {
            PushNotificationType.PAYMENT_DUE: {
                'title': 'Payment Due',
                'message': f"Your premium payment of ${amount:,.2f} for policy {policy_id} is due on {due_date}."
            },
            PushNotificationType.PAYMENT_RECEIVED: {
                'title': 'Payment Received',
                'message': f"Thank you! Your payment of ${amount:,.2f} has been received."
            },
            PushNotificationType.PAYMENT_FAILED: {
                'title': 'Payment Failed',
                'message': f"Your payment of ${amount:,.2f} could not be processed. Please update your payment method."
            },
            PushNotificationType.MONTHLY_STATEMENT: {
                'title': 'Monthly Statement Available',
                'message': f"Your monthly insurance statement for {billing_data.get('period', 'this month')} is now available."
            },
            PushNotificationType.ANNUAL_STATEMENT: {
                'title': 'Annual Statement Available',
                'message': f"Your annual insurance statement for {billing_data.get('year', 'this year')} is now available."
            }
        }
        
        template = templates.get(event_type, {
            'title': 'Billing Update',
            'message': 'Your billing information has been updated.'
        })
        
        return self.send_push_notification(PushNotificationRequest(
            notification_type=event_type,
            customer_id=customer_id,
            title=template['title'],
            message=template['message'],
            data=billing_data,
            channels=[NotificationChannel.EMAIL],
            email=email,
            phone=phone,
            priority=NotificationPriority.HIGH if event_type in [
                PushNotificationType.PAYMENT_DUE,
                PushNotificationType.PAYMENT_FAILED
            ] else NotificationPriority.NORMAL
        ))
    
    def notify_savings_event(
        self,
        event_type: PushNotificationType,
        customer_id: str,
        savings_data: Dict[str, Any],
        email: Optional[str] = None,
        phone: Optional[str] = None
    ) -> PushNotificationResult:
        """Convenience method for savings-related notifications"""
        amount = savings_data.get('amount', 0)
        balance = savings_data.get('balance', 0)
        
        templates = {
            PushNotificationType.SAVINGS_DEPOSITED: {
                'title': 'Savings Deposit Confirmed',
                'message': f"${amount:,.2f} has been deposited to your savings. New balance: ${balance:,.2f}"
            },
            PushNotificationType.SAVINGS_WITHDRAWN: {
                'title': 'Withdrawal Processed',
                'message': f"${amount:,.2f} has been withdrawn from your savings. New balance: ${balance:,.2f}"
            },
            PushNotificationType.SAVINGS_GOAL_REACHED: {
                'title': 'Congratulations!',
                'message': f"You've reached your savings goal of ${savings_data.get('goal', 0):,.2f}!"
            },
            PushNotificationType.INVESTMENT_UPDATE: {
                'title': 'Investment Portfolio Update',
                'message': f"Your investment portfolio has been updated. Current value: ${balance:,.2f}"
            }
        }
        
        template = templates.get(event_type, {
            'title': 'Savings Update',
            'message': 'Your savings information has been updated.'
        })
        
        return self.send_push_notification(PushNotificationRequest(
            notification_type=event_type,
            customer_id=customer_id,
            title=template['title'],
            message=template['message'],
            data=savings_data,
            channels=[NotificationChannel.EMAIL, NotificationChannel.SMS],
            email=email,
            phone=phone,
            priority=NotificationPriority.NORMAL
        ))
    
    def notify_security_event(
        self,
        event_type: PushNotificationType,
        customer_id: str,
        security_data: Dict[str, Any],
        email: Optional[str] = None,
        phone: Optional[str] = None
    ) -> PushNotificationResult:
        """Send security-related notifications (always high priority)"""
        templates = {
            PushNotificationType.LOGIN_ALERT: {
                'title': 'New Login Detected',
                'message': f"New login from {security_data.get('location', 'unknown location')} using {security_data.get('device', 'unknown device')}."
            },
            PushNotificationType.SUSPICIOUS_ACTIVITY: {
                'title': 'Security Alert',
                'message': "Suspicious activity detected on your account. Please verify your recent activity."
            },
            PushNotificationType.PASSWORD_CHANGED: {
                'title': 'Password Changed',
                'message': "Your password has been successfully changed. If this wasn't you, contact support immediately."
            },
            PushNotificationType.DEVICE_ADDED: {
                'title': 'New Device Added',
                'message': f"A new device has been added to your account: {security_data.get('device_name', 'Unknown device')}"
            }
        }
        
        template = templates.get(event_type, {
            'title': 'Security Notice',
            'message': 'Your account security has been updated.'
        })
        
        return self.send_push_notification(PushNotificationRequest(
            notification_type=event_type,
            customer_id=customer_id,
            title=template['title'],
            message=template['message'],
            data=security_data,
            channels=[NotificationChannel.EMAIL, NotificationChannel.SMS],
            email=email,
            phone=phone,
            priority=NotificationPriority.CRITICAL
        ))
    
    # ========== DATA INTEGRITY API ==========
    
    def validate_operation_integrity(
        self,
        operation_id: str
    ) -> Dict[str, Any]:
        """
        Validate data integrity for an operation.
        Returns integrity report including pre/post state comparison.
        """
        checkpoint = self._checkpoints.get(
            self._operations.get(operation_id, {}).get('checkpoint_id')
        )
        
        if not checkpoint:
            return {
                'valid': False,
                'error': 'No integrity checkpoint found'
            }
        
        return {
            'valid': checkpoint.integrity_valid,
            'checkpoint_id': checkpoint.checkpoint_id,
            'operation_id': checkpoint.operation_id,
            'integrity_hash': checkpoint.integrity_hash,
            'discrepancies': checkpoint.discrepancies,
            'created_at': checkpoint.created_at.isoformat(),
            'completed_at': checkpoint.completed_at.isoformat() if checkpoint.completed_at else None
        }
    
    def run_pipeline_integrity_check(
        self,
        customer_id: str
    ) -> Dict[str, Any]:
        """Run comprehensive pipeline integrity check for a customer"""
        if self._pipeline_integrity:
            # Get all policies for customer and validate
            return self._pipeline_integrity.validate_all_policies()
        
        return {
            'status': 'skipped',
            'message': 'Pipeline integrity service not configured'
        }
    
    def run_data_integrity_check(
        self,
        customer_id: str,
        auto_correct: bool = False
    ) -> Dict[str, Any]:
        """Run data integrity check for a customer"""
        if self._data_integrity:
            report = self._data_integrity.validate_customer_integrity(
                customer_id=customer_id,
                auto_correct=auto_correct
            )
            return report.to_dict() if hasattr(report, 'to_dict') else report
        
        return {
            'status': 'skipped',
            'message': 'Data integrity service not configured'
        }
    
    # ========== AUDIT API ==========
    
    def get_audit_log(
        self,
        customer_id: Optional[str] = None,
        operation_type: Optional[str] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Get audit log entries"""
        with self._audit_lock:
            logs = self._audit_log.copy()
        
        if customer_id:
            logs = [l for l in logs if l.get('customer_id') == customer_id]
        if operation_type:
            logs = [l for l in logs if l.get('operation_type') == operation_type]
        
        return logs[-limit:]
    
    # ========== EVENT CALLBACKS ==========
    
    def on_event(self, event_type: str, callback: Callable):
        """Register callback for pipeline events"""
        if event_type in self._event_callbacks:
            self._event_callbacks[event_type].append(callback)
    
    # ========== PRIVATE METHODS ==========
    
    def _validate_operation_request(
        self,
        request: SecureOperationRequest
    ) -> Dict[str, Any]:
        """Validate operation request"""
        if not request.customer_id:
            return {'valid': False, 'error': 'Customer ID is required'}
        
        if not request.email and not request.phone:
            return {'valid': False, 'error': 'Either email or phone is required'}
        
        if request.email and not validate_email(request.email):
            return {'valid': False, 'error': 'Invalid email format'}
        
        if request.phone and not validate_phone(request.phone):
            return {'valid': False, 'error': 'Invalid phone number format'}
        
        # Check if high-value transaction
        if request.amount and request.amount >= SecureNotificationConfig.HIGH_VALUE_THRESHOLD:
            # High-value transactions may require additional verification
            pass
        
        return {'valid': True}
    
    def _create_checkpoint(
        self,
        operation_id: str,
        request: SecureOperationRequest
    ) -> IntegrityCheckpoint:
        """Create an integrity checkpoint before operation"""
        checkpoint_id = f"CKP_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{secrets.token_hex(4)}"
        
        # Capture pre-operation state
        pre_state = {
            'customer_id': request.customer_id,
            'operation_type': request.operation_type.value,
            'amount': request.amount,
            'timestamp': datetime.now(timezone.utc).isoformat()
        }
        
        # Get customer's current state from data integrity service
        if self._data_integrity:
            try:
                integrity_report = self._data_integrity.get_verified_total(request.customer_id)
                pre_state['balances'] = {
                    'total_savings': integrity_report.get('total_savings', 0),
                    'wallet_balance': integrity_report.get('wallet_balance', 0),
                    'investment_balance': integrity_report.get('investment_balance', 0)
                }
            except Exception:
                pass
        
        checkpoint = IntegrityCheckpoint(
            checkpoint_id=checkpoint_id,
            operation_id=operation_id,
            customer_id=request.customer_id,
            operation_type=request.operation_type.value,
            pre_state=pre_state
        )
        
        self._checkpoints[checkpoint_id] = checkpoint
        return checkpoint
    
    def _map_to_verification_type(
        self,
        operation_type: SecureOperationType
    ) -> VerificationType:
        """Map secure operation type to verification type"""
        mapping = {
            SecureOperationType.ACCOUNT_REGISTRATION: VerificationType.ACCOUNT_ACTIVATION,
            SecureOperationType.EMAIL_VERIFICATION: VerificationType.EMAIL_VERIFICATION,
            SecureOperationType.PHONE_VERIFICATION: VerificationType.PHONE_VERIFICATION,
            SecureOperationType.SAVINGS_DEPOSIT: VerificationType.TRANSACTION_CONFIRM,
            SecureOperationType.SAVINGS_WITHDRAWAL: VerificationType.TRANSACTION_CONFIRM,
            SecureOperationType.CLAIM_SUBMISSION: VerificationType.TRANSACTION_CONFIRM,
            SecureOperationType.POLICY_PURCHASE: VerificationType.TRANSACTION_CONFIRM,
            SecureOperationType.POLICY_RENEWAL: VerificationType.TRANSACTION_CONFIRM,
            SecureOperationType.POLICY_CANCELLATION: VerificationType.TRANSACTION_CONFIRM,
            SecureOperationType.HIGH_VALUE_TRANSACTION: VerificationType.TRANSACTION_CONFIRM,
            SecureOperationType.BENEFICIARY_UPDATE: VerificationType.TRANSACTION_CONFIRM,
            SecureOperationType.CONTACT_UPDATE: VerificationType.TRANSACTION_CONFIRM,
            SecureOperationType.PASSWORD_RESET: VerificationType.PASSWORD_RESET,
            SecureOperationType.TWO_FACTOR_AUTH: VerificationType.TWO_FACTOR_AUTH,
        }
        return mapping.get(operation_type, VerificationType.TRANSACTION_CONFIRM)
    
    def _send_to_channel(
        self,
        channel: NotificationChannel,
        notification_type: PushNotificationType,
        customer_id: str,
        title: str,
        message: str,
        email: Optional[str] = None,
        phone: Optional[str] = None,
        data: Optional[Dict[str, Any]] = None,
        priority: NotificationPriority = NotificationPriority.NORMAL
    ) -> Dict[str, Any]:
        """Send notification to a specific channel"""
        sanitized_data = dict(data or {})
        recipient_for_validation = email if channel == NotificationChannel.EMAIL else phone
        otp_error = self._validate_push_notification_otp(
            channel=channel,
            customer_id=customer_id,
            recipient=recipient_for_validation,
            data=sanitized_data
        )
        if otp_error:
            return {
                'success': False,
                'error_code': 'OTP_VALIDATION_FAILED',
                'error': otp_error
            }

        # OTP fields are consumed by validation and should not be forwarded.
        for otp_field in (
            'require_otp_validation',
            'otp_code',
            'otp_identifier',
            'otp_verification_type',
        ):
            sanitized_data.pop(otp_field, None)
        
        if channel == NotificationChannel.EMAIL:
            if not email:
                return {'success': False, 'error': 'No email address provided'}
            
            request = NotificationRequest(
                channel=NotificationChannel.EMAIL,
                recipient=email,
                subject=title,
                content=message,
                customer_id=customer_id,
                priority=priority,
                metadata={'notification_type': notification_type.value, **sanitized_data}
            )
            result = self._notification_service.send(request)
            return {
                'success': result.success,
                'message_id': result.notification_id,
                'error': result.error_message
            }
        
        elif channel == NotificationChannel.SMS:
            if not phone:
                return {'success': False, 'error': 'No phone number provided'}
            
            # Truncate for SMS
            sms_message = f"{title}: {message}"[:160]
            
            request = NotificationRequest(
                channel=NotificationChannel.SMS,
                recipient=phone,
                content=sms_message,
                customer_id=customer_id,
                priority=priority,
                metadata={'notification_type': notification_type.value, **sanitized_data}
            )
            result = self._notification_service.send(request)
            return {
                'success': result.success,
                'message_id': result.notification_id,
                'error': result.error_message
            }
        
        elif channel.value == 'whatsapp':
            if not phone:
                return {'success': False, 'error': 'No phone number provided'}
            
            whatsapp_message = f"*{title}*\n\n{message}"
            success, message_id, error = self._whatsapp.send(phone, whatsapp_message)
            return {
                'success': success,
                'message_id': message_id,
                'error': error
            }
        
        return {'success': False, 'error': f'Unsupported channel: {channel.value}'}

    def _validate_push_notification_otp(
        self,
        channel: NotificationChannel,
        customer_id: str,
        recipient: Optional[str],
        data: Dict[str, Any]
    ) -> Optional[str]:
        """Validate optional OTP requirement for push notifications."""
        if not data.get('require_otp_validation'):
            return None

        otp_code = str(data.get('otp_code', '')).strip()
        if not otp_code:
            return "OTP validation required but otp_code is missing"

        otp_identifier = str(data.get('otp_identifier') or recipient or '').strip()
        if not otp_identifier:
            return "OTP validation required but otp_identifier is missing"

        verification_type_raw = str(
            data.get('otp_verification_type', VerificationType.TRANSACTION_CONFIRM.value)
        )
        try:
            verification_type = VerificationType(verification_type_raw)
        except ValueError:
            return f"Invalid otp_verification_type: {verification_type_raw}"

        ip_address = data.get('ip_address')
        otp_result = self._notification_service.verify_otp(
            identifier=otp_identifier,
            code=otp_code,
            verification_type=verification_type,
            ip_address=ip_address
        )
        if not otp_result.success:
            return otp_result.error_message or "OTP verification failed"

        self._audit_operation(
            action='push_notification_otp_verified',
            customer_id=customer_id,
            ip_address=ip_address,
            details={
                'channel': channel.value,
                'verification_type': verification_type.value
            }
        )
        return None
    
    def _audit_operation(
        self,
        action: str,
        operation_id: Optional[str] = None,
        notification_id: Optional[str] = None,
        customer_id: Optional[str] = None,
        ip_address: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        success: bool = True
    ):
        """Record audit log entry"""
        if not SecureNotificationConfig.AUDIT_ALL_OPERATIONS:
            return
        
        entry = {
            'id': f"AUDIT_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{secrets.token_hex(4)}",
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'action': action,
            'operation_id': operation_id,
            'notification_id': notification_id,
            'customer_id': customer_id,
            'ip_address': ip_address,
            'details': details or {},
            'success': success
        }
        
        with self._audit_lock:
            self._audit_log.append(entry)
            # Keep last 10000 entries
            if len(self._audit_log) > 10000:
                self._audit_log = self._audit_log[-10000:]
        
        logger.info(f"AUDIT: {action} - {json.dumps(entry)}")
    
    def _trigger_event(self, event_type: str, *args):
        """Trigger event callbacks"""
        for callback in self._event_callbacks.get(event_type, []):
            try:
                callback(*args)
            except Exception as e:
                logger.error(f"Event callback error ({event_type}): {str(e)}")
    
    def _load_templates(self) -> Dict[str, Dict[str, str]]:
        """Load notification templates"""
        return {
            'otp_email': {
                'subject': 'Your PHINS Verification Code',
                'body': '''Your verification code is: {{ code }}

This code expires in {{ expiry_minutes }} minutes.

If you didn't request this code, please ignore this message.

- PHINS Security Team'''
            },
            'otp_sms': {
                'body': 'PHINS: Your code is {{ code }}. Expires in {{ expiry_minutes }} min. Never share this code.'
            },
            'otp_whatsapp': {
                'body': '''*PHINS Verification*

Your verification code is: *{{ code }}*

This code expires in {{ expiry_minutes }} minutes.

If you didn't request this, please ignore.'''
            }
        }


# ============================================================================
# FACTORY FUNCTION
# ============================================================================

def create_secure_notification_pipeline(
    notification_service: Optional[NotificationService] = None,
    whatsapp_provider: Optional[WhatsAppProvider] = None,
    data_integrity_service=None,
    pipeline_integrity_service=None,
    use_mock: Optional[bool] = None
) -> SecureNotificationPipeline:
    """
    Factory function to create SecureNotificationPipeline with all dependencies.
    """
    if not notification_service:
        resolved_use_mock = should_use_mock_notifications() if use_mock is None else bool(use_mock)
        notification_service = create_notification_service(use_mock=resolved_use_mock)
    
    return SecureNotificationPipeline(
        notification_service=notification_service,
        whatsapp_provider=whatsapp_provider,
        data_integrity_service=data_integrity_service,
        pipeline_integrity_service=pipeline_integrity_service
    )


# Singleton instance
_secure_pipeline: Optional[SecureNotificationPipeline] = None


def get_secure_notification_pipeline(**kwargs) -> SecureNotificationPipeline:
    """Get singleton instance of secure notification pipeline"""
    global _secure_pipeline
    if _secure_pipeline is None:
        _secure_pipeline = create_secure_notification_pipeline(**kwargs)
    return _secure_pipeline


def reset_secure_notification_pipeline():
    """Reset the singleton (mainly for testing)"""
    global _secure_pipeline
    _secure_pipeline = None


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    # Configuration
    'SecureNotificationConfig',
    
    # Enums
    'SecureOperationType',
    'PushNotificationType',
    'NotificationDeliveryStatus',
    
    # Data Classes
    'SecureOperationRequest',
    'SecureOperationResult',
    'PushNotificationRequest',
    'PushNotificationResult',
    'IntegrityCheckpoint',
    
    # WhatsApp Providers
    'WhatsAppProvider',
    'TwilioWhatsAppProvider',
    'MetaWhatsAppProvider',
    'MockWhatsAppProvider',
    
    # Main Service
    'SecureNotificationPipeline',
    
    # Factory Functions
    'create_secure_notification_pipeline',
    'get_secure_notification_pipeline',
    'reset_secure_notification_pipeline',
]
