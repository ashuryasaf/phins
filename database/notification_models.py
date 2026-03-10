"""
PHINS Notification Service Database Models
Enterprise-grade notification system for email, SMS, and OTP verification

Security Features:
- Encrypted OTP codes stored as hashed values
- Rate limiting tracking per client
- Comprehensive audit trail
- Multi-channel delivery tracking
"""

from sqlalchemy import (
    Column, String, Integer, Float, DateTime, Boolean, Text, 
    ForeignKey, Index, Enum as SQLEnum
)
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime, timezone
import enum

from database.models import Base


# ============================================================================
# ENUMS - Notification Types and Statuses
# ============================================================================

class NotificationChannel(str, enum.Enum):
    """Supported notification delivery channels"""
    EMAIL = "email"
    SMS = "sms"
    WHATSAPP = "whatsapp"
    PUSH = "push"
    IN_APP = "in_app"
    WEBHOOK = "webhook"


class NotificationPriority(str, enum.Enum):
    """Notification priority levels for queue management"""
    CRITICAL = "critical"  # Immediate delivery (OTP, security alerts)
    HIGH = "high"          # Within 1 minute
    NORMAL = "normal"      # Within 5 minutes
    LOW = "low"            # Batch delivery acceptable


class NotificationStatus(str, enum.Enum):
    """Delivery status tracking"""
    PENDING = "pending"
    QUEUED = "queued"
    SENDING = "sending"
    DELIVERED = "delivered"
    FAILED = "failed"
    BOUNCED = "bounced"
    SPAM_BLOCKED = "spam_blocked"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class VerificationType(str, enum.Enum):
    """Types of client verification"""
    EMAIL_VERIFICATION = "email_verification"
    PHONE_VERIFICATION = "phone_verification"
    TWO_FACTOR_AUTH = "two_factor_auth"
    PASSWORD_RESET = "password_reset"
    ACCOUNT_ACTIVATION = "account_activation"
    TRANSACTION_CONFIRM = "transaction_confirm"
    DEVICE_VERIFICATION = "device_verification"
    IDENTITY_VERIFICATION = "identity_verification"


class OTPStatus(str, enum.Enum):
    """OTP lifecycle status"""
    ACTIVE = "active"
    USED = "used"
    EXPIRED = "expired"
    INVALIDATED = "invalidated"
    BLOCKED = "blocked"


class RateLimitAction(str, enum.Enum):
    """Rate limiting action types"""
    OTP_REQUEST = "otp_request"
    EMAIL_SEND = "email_send"
    SMS_SEND = "sms_send"
    LOGIN_ATTEMPT = "login_attempt"
    PASSWORD_RESET = "password_reset"
    API_CALL = "api_call"


# ============================================================================
# DATABASE MODELS
# ============================================================================

class NotificationTemplate(Base):
    """
    Notification templates with multi-language support.
    Templates use Jinja2-style placeholders: {{ variable_name }}
    """
    __tablename__ = 'notification_templates'
    
    id = Column(String(50), primary_key=True)
    name = Column(String(100), nullable=False, unique=True, index=True)
    channel = Column(String(20), nullable=False, index=True)  # NotificationChannel
    category = Column(String(50), nullable=False, index=True)  # otp, alert, marketing, transactional
    
    # Content
    subject = Column(String(500), nullable=True)  # For email
    body_template = Column(Text, nullable=False)  # Main template content
    html_template = Column(Text, nullable=True)   # HTML version for email
    
    # Internationalization
    language = Column(String(10), default='en', index=True)
    
    # Template configuration
    variables = Column(Text, nullable=True)  # JSON array of required variables
    priority = Column(String(20), default='normal')  # Default priority
    
    # Security
    requires_encryption = Column(Boolean, default=False)
    pii_fields = Column(Text, nullable=True)  # JSON array of PII field names
    
    # Status
    active = Column(Boolean, default=True, index=True)
    version = Column(Integer, default=1)
    
    # Metadata
    created_by = Column(String(100), nullable=True)
    created_date = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_date = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    
    def to_dict(self):
        import json as _json
        
        def safe_json_loads(val):
            if val is None:
                return []
            try:
                return _json.loads(val)
            except:
                return []
        
        return {
            'id': self.id,
            'name': self.name,
            'channel': self.channel,
            'category': self.category,
            'subject': self.subject,
            'body_template': self.body_template,
            'html_template': self.html_template,
            'language': self.language,
            'variables': safe_json_loads(self.variables),
            'priority': self.priority,
            'requires_encryption': self.requires_encryption,
            'pii_fields': safe_json_loads(self.pii_fields),
            'active': self.active,
            'version': self.version,
            'created_by': self.created_by,
            'created_date': self.created_date.isoformat() if self.created_date else None,
            'updated_date': self.updated_date.isoformat() if self.updated_date else None
        }


class NotificationQueue(Base):
    """
    Notification queue for async delivery with retry support.
    Implements dead-letter queue pattern for failed deliveries.
    """
    __tablename__ = 'notification_queue'
    
    id = Column(String(50), primary_key=True)
    
    # Recipient information
    customer_id = Column(String(50), nullable=True, index=True)
    user_id = Column(String(50), nullable=True, index=True)
    recipient_identifier = Column(String(255), nullable=False)  # email/phone
    
    # Notification details
    channel = Column(String(20), nullable=False, index=True)
    template_id = Column(String(50), nullable=True, index=True)
    priority = Column(String(20), default='normal', index=True)
    
    # Content
    subject = Column(String(500), nullable=True)
    content = Column(Text, nullable=False)
    content_encrypted = Column(Boolean, default=False)
    
    # Variables for template rendering (JSON)
    variables = Column(Text, nullable=True)
    
    # Status tracking
    status = Column(String(20), default='pending', index=True)
    
    # Scheduling
    scheduled_at = Column(DateTime, nullable=True, index=True)
    send_after = Column(DateTime, nullable=True)  # Minimum time before sending
    expires_at = Column(DateTime, nullable=True, index=True)  # Don't send after this time
    
    # Retry management
    attempt_count = Column(Integer, default=0)
    max_attempts = Column(Integer, default=3)
    last_attempt_at = Column(DateTime, nullable=True)
    next_retry_at = Column(DateTime, nullable=True, index=True)
    
    # Response tracking
    provider_response = Column(Text, nullable=True)  # JSON
    provider_message_id = Column(String(255), nullable=True, index=True)
    
    # Error handling
    error_code = Column(String(50), nullable=True)
    error_message = Column(Text, nullable=True)
    
    # Metadata
    correlation_id = Column(String(100), nullable=True, index=True)
    source_system = Column(String(50), nullable=True)
    ip_address = Column(String(45), nullable=True)
    
    # Timestamps
    created_date = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False, index=True)
    updated_date = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    delivered_at = Column(DateTime, nullable=True)
    
    # Indexes for queue processing
    __table_args__ = (
        Index('idx_notification_queue_processing', 
              'status', 'priority', 'scheduled_at', 'next_retry_at'),
        Index('idx_notification_queue_cleanup', 
              'status', 'expires_at'),
    )
    
    def to_dict(self):
        import json as _json
        
        def safe_json_loads(val):
            if val is None:
                return {}
            try:
                return _json.loads(val)
            except:
                return {}
        
        return {
            'id': self.id,
            'customer_id': self.customer_id,
            'user_id': self.user_id,
            'recipient_identifier': self.recipient_identifier,
            'channel': self.channel,
            'template_id': self.template_id,
            'priority': self.priority,
            'subject': self.subject,
            'content': self.content if not self.content_encrypted else '[ENCRYPTED]',
            'status': self.status,
            'scheduled_at': self.scheduled_at.isoformat() if self.scheduled_at else None,
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
            'attempt_count': self.attempt_count,
            'max_attempts': self.max_attempts,
            'last_attempt_at': self.last_attempt_at.isoformat() if self.last_attempt_at else None,
            'provider_message_id': self.provider_message_id,
            'error_code': self.error_code,
            'error_message': self.error_message,
            'correlation_id': self.correlation_id,
            'created_date': self.created_date.isoformat() if self.created_date else None,
            'delivered_at': self.delivered_at.isoformat() if self.delivered_at else None
        }


class NotificationHistory(Base):
    """
    Complete audit trail of all sent notifications.
    Required for compliance and debugging.
    """
    __tablename__ = 'notification_history'
    
    id = Column(String(50), primary_key=True)
    queue_id = Column(String(50), nullable=True, index=True)
    
    # Recipient
    customer_id = Column(String(50), nullable=True, index=True)
    user_id = Column(String(50), nullable=True, index=True)
    recipient_identifier = Column(String(255), nullable=False)
    recipient_identifier_hash = Column(String(64), nullable=True, index=True)  # For privacy-safe lookups
    
    # Notification details
    channel = Column(String(20), nullable=False, index=True)
    template_id = Column(String(50), nullable=True)
    notification_type = Column(String(50), nullable=True, index=True)  # otp, alert, marketing
    priority = Column(String(20), nullable=True)
    
    # Content (may be redacted for security)
    subject = Column(String(500), nullable=True)
    content_hash = Column(String(64), nullable=True)  # SHA-256 of content for verification
    content_size_bytes = Column(Integer, nullable=True)
    
    # Delivery status
    status = Column(String(20), nullable=False, index=True)
    attempt_count = Column(Integer, default=1)
    
    # Provider details
    provider = Column(String(50), nullable=True)
    provider_message_id = Column(String(255), nullable=True, index=True)
    provider_response_code = Column(String(50), nullable=True)
    
    # Timing
    queued_at = Column(DateTime, nullable=True)
    sent_at = Column(DateTime, nullable=True, index=True)
    delivered_at = Column(DateTime, nullable=True)
    opened_at = Column(DateTime, nullable=True)  # For email tracking
    clicked_at = Column(DateTime, nullable=True)  # For link tracking
    
    # Error details
    error_code = Column(String(50), nullable=True)
    error_category = Column(String(50), nullable=True)  # hard_bounce, soft_bounce, blocked, etc.
    
    # Security
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(String(500), nullable=True)
    
    # Correlation
    correlation_id = Column(String(100), nullable=True, index=True)
    parent_notification_id = Column(String(50), nullable=True)  # For retry chains
    
    # Timestamps
    created_date = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False, index=True)
    
    __table_args__ = (
        Index('idx_notification_history_lookup',
              'customer_id', 'channel', 'sent_at'),
        Index('idx_notification_history_analytics',
              'notification_type', 'status', 'sent_at'),
    )
    
    def to_dict(self):
        return {
            'id': self.id,
            'queue_id': self.queue_id,
            'customer_id': self.customer_id,
            'user_id': self.user_id,
            'recipient_identifier': self.recipient_identifier,
            'channel': self.channel,
            'template_id': self.template_id,
            'notification_type': self.notification_type,
            'priority': self.priority,
            'subject': self.subject,
            'status': self.status,
            'attempt_count': self.attempt_count,
            'provider': self.provider,
            'provider_message_id': self.provider_message_id,
            'queued_at': self.queued_at.isoformat() if self.queued_at else None,
            'sent_at': self.sent_at.isoformat() if self.sent_at else None,
            'delivered_at': self.delivered_at.isoformat() if self.delivered_at else None,
            'opened_at': self.opened_at.isoformat() if self.opened_at else None,
            'error_code': self.error_code,
            'error_category': self.error_category,
            'correlation_id': self.correlation_id,
            'created_date': self.created_date.isoformat() if self.created_date else None
        }


class OTPCode(Base):
    """
    Secure OTP code storage for client verification.
    
    SECURITY:
    - OTP codes are stored as salted hashes (not plaintext)
    - Maximum attempts tracked to prevent brute force
    - Short expiry times enforced
    - Rate limiting integration
    """
    __tablename__ = 'otp_codes'
    
    id = Column(String(50), primary_key=True)
    
    # Target identification
    customer_id = Column(String(50), nullable=True, index=True)
    user_id = Column(String(50), nullable=True, index=True)
    identifier = Column(String(255), nullable=False)  # email or phone
    identifier_hash = Column(String(64), nullable=False, index=True)  # For secure lookup
    
    # OTP storage (NEVER store plaintext)
    code_hash = Column(String(255), nullable=False)  # Argon2/bcrypt hash
    code_salt = Column(String(255), nullable=False)
    code_length = Column(Integer, default=6)
    
    # Type and purpose
    verification_type = Column(String(50), nullable=False, index=True)
    channel = Column(String(20), nullable=False)  # email or sms
    
    # Status
    status = Column(String(20), default='active', index=True)
    
    # Lifecycle
    expires_at = Column(DateTime, nullable=False, index=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    used_at = Column(DateTime, nullable=True)
    invalidated_at = Column(DateTime, nullable=True)
    
    # Security counters
    attempt_count = Column(Integer, default=0)
    max_attempts = Column(Integer, default=5)
    
    # Context
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(String(500), nullable=True)
    device_fingerprint = Column(String(255), nullable=True, index=True)
    
    # Correlation
    session_id = Column(String(100), nullable=True)
    correlation_id = Column(String(100), nullable=True, index=True)
    notification_id = Column(String(50), nullable=True)  # Reference to notification sent
    
    # Geographic context
    country_code = Column(String(5), nullable=True)
    region = Column(String(50), nullable=True)
    
    __table_args__ = (
        Index('idx_otp_lookup',
              'identifier_hash', 'verification_type', 'status', 'expires_at'),
        Index('idx_otp_security',
              'ip_address', 'created_at'),
    )
    
    def to_dict(self):
        """Convert to dict (NEVER include hash/salt)"""
        return {
            'id': self.id,
            'customer_id': self.customer_id,
            'user_id': self.user_id,
            'identifier_masked': self._mask_identifier(),
            'verification_type': self.verification_type,
            'channel': self.channel,
            'status': self.status,
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'used_at': self.used_at.isoformat() if self.used_at else None,
            'attempt_count': self.attempt_count,
            'max_attempts': self.max_attempts,
            'correlation_id': self.correlation_id
        }
    
    def _mask_identifier(self) -> str:
        """Mask identifier for security (show partial only)"""
        if '@' in self.identifier:  # Email
            parts = self.identifier.split('@')
            local = parts[0]
            domain = parts[1] if len(parts) > 1 else ''
            masked_local = local[0] + '*' * (len(local) - 2) + local[-1] if len(local) > 2 else local
            return f"{masked_local}@{domain}"
        else:  # Phone
            if len(self.identifier) > 6:
                return self.identifier[:3] + '*' * (len(self.identifier) - 6) + self.identifier[-3:]
            return '***'


class ClientVerification(Base):
    """
    Client verification workflow tracking.
    Manages multi-step verification processes.
    """
    __tablename__ = 'client_verifications'
    
    id = Column(String(50), primary_key=True)
    
    # Client identification
    customer_id = Column(String(50), nullable=True, index=True)
    user_id = Column(String(50), nullable=True, index=True)
    
    # Verification details
    verification_type = Column(String(50), nullable=False, index=True)
    identifier = Column(String(255), nullable=False)
    identifier_hash = Column(String(64), nullable=False, index=True)
    
    # Status
    status = Column(String(20), default='pending', index=True)  # pending, verified, failed, expired
    verification_level = Column(Integer, default=1)  # For multi-level verification
    
    # Timestamps
    initiated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    verified_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True)
    
    # Verification metadata
    otp_codes_sent = Column(Integer, default=0)
    otp_codes_used = Column(Integer, default=0)
    total_attempts = Column(Integer, default=0)
    successful_attempts = Column(Integer, default=0)
    
    # Security context
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(String(500), nullable=True)
    device_fingerprint = Column(String(255), nullable=True)
    
    # Geographic verification
    country_code = Column(String(5), nullable=True)
    is_geo_matched = Column(Boolean, nullable=True)  # Does location match user profile?
    
    # Risk assessment
    risk_score = Column(Float, nullable=True)  # 0.0 to 1.0
    risk_factors = Column(Text, nullable=True)  # JSON array
    
    # Metadata
    extra_metadata = Column(Text, nullable=True)  # JSON (renamed from 'metadata' — reserved in SQLAlchemy)
    notes = Column(Text, nullable=True)
    
    # Correlation
    correlation_id = Column(String(100), nullable=True, index=True)
    session_id = Column(String(100), nullable=True)
    
    # Timestamps
    created_date = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_date = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    
    __table_args__ = (
        Index('idx_verification_lookup',
              'customer_id', 'verification_type', 'status'),
    )
    
    def to_dict(self):
        import json as _json
        
        def safe_json_loads(val):
            if val is None:
                return []
            try:
                return _json.loads(val)
            except:
                return []
        
        return {
            'id': self.id,
            'customer_id': self.customer_id,
            'user_id': self.user_id,
            'verification_type': self.verification_type,
            'status': self.status,
            'verification_level': self.verification_level,
            'initiated_at': self.initiated_at.isoformat() if self.initiated_at else None,
            'verified_at': self.verified_at.isoformat() if self.verified_at else None,
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
            'otp_codes_sent': self.otp_codes_sent,
            'total_attempts': self.total_attempts,
            'successful_attempts': self.successful_attempts,
            'risk_score': self.risk_score,
            'risk_factors': safe_json_loads(self.risk_factors),
            'correlation_id': self.correlation_id,
            'created_date': self.created_date.isoformat() if self.created_date else None,
            'updated_date': self.updated_date.isoformat() if self.updated_date else None
        }


class RateLimitRecord(Base):
    """
    Rate limiting tracking for abuse prevention.
    Uses sliding window algorithm.
    """
    __tablename__ = 'rate_limit_records'
    
    id = Column(String(50), primary_key=True)
    
    # Identifier (can be customer_id, ip_address, email, phone)
    identifier = Column(String(255), nullable=False, index=True)
    identifier_type = Column(String(50), nullable=False)  # customer, ip, email, phone, device
    
    # Action being limited
    action = Column(String(50), nullable=False, index=True)
    
    # Window tracking
    window_start = Column(DateTime, nullable=False, index=True)
    window_size_seconds = Column(Integer, nullable=False)
    
    # Counts
    request_count = Column(Integer, default=1)
    limit = Column(Integer, nullable=False)
    
    # Status
    is_blocked = Column(Boolean, default=False, index=True)
    blocked_until = Column(DateTime, nullable=True)
    block_reason = Column(String(255), nullable=True)
    
    # Last request details
    last_request_at = Column(DateTime, nullable=True)
    last_request_ip = Column(String(45), nullable=True)
    
    # Timestamps
    created_date = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_date = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    
    __table_args__ = (
        Index('idx_rate_limit_lookup',
              'identifier', 'action', 'window_start'),
        Index('idx_rate_limit_blocked',
              'is_blocked', 'blocked_until'),
    )
    
    def to_dict(self):
        return {
            'id': self.id,
            'identifier': self.identifier,
            'identifier_type': self.identifier_type,
            'action': self.action,
            'window_start': self.window_start.isoformat() if self.window_start else None,
            'window_size_seconds': self.window_size_seconds,
            'request_count': self.request_count,
            'limit': self.limit,
            'is_blocked': self.is_blocked,
            'blocked_until': self.blocked_until.isoformat() if self.blocked_until else None,
            'block_reason': self.block_reason,
            'created_date': self.created_date.isoformat() if self.created_date else None
        }


class EmailSuppressionList(Base):
    """
    Email suppression list for bounces, unsubscribes, and complaints.
    Required for email deliverability and compliance.
    """
    __tablename__ = 'email_suppression_list'
    
    id = Column(String(50), primary_key=True)
    email = Column(String(254), nullable=False)
    email_hash = Column(String(64), nullable=False, unique=True, index=True)
    
    # Suppression reason
    reason = Column(String(50), nullable=False, index=True)  # hard_bounce, soft_bounce, complaint, unsubscribe
    sub_reason = Column(String(100), nullable=True)  # More specific reason
    
    # Source
    provider = Column(String(50), nullable=True)  # Which provider reported this
    original_notification_id = Column(String(50), nullable=True)
    
    # Timestamps
    suppressed_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False, index=True)
    expires_at = Column(DateTime, nullable=True)  # For soft bounces that can retry
    
    # Metadata
    bounce_code = Column(String(50), nullable=True)
    bounce_message = Column(Text, nullable=True)
    
    # Re-engagement
    removal_requested = Column(Boolean, default=False)
    removal_requested_at = Column(DateTime, nullable=True)
    removal_approved = Column(Boolean, default=False)
    
    created_date = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    
    def to_dict(self):
        return {
            'id': self.id,
            'email_hash': self.email_hash,
            'reason': self.reason,
            'sub_reason': self.sub_reason,
            'provider': self.provider,
            'suppressed_at': self.suppressed_at.isoformat() if self.suppressed_at else None,
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
            'removal_requested': self.removal_requested,
            'created_date': self.created_date.isoformat() if self.created_date else None
        }


class SMSSuppressionList(Base):
    """
    SMS suppression list for undeliverable numbers and opt-outs.
    """
    __tablename__ = 'sms_suppression_list'
    
    id = Column(String(50), primary_key=True)
    phone_number = Column(String(20), nullable=False)
    phone_hash = Column(String(64), nullable=False, unique=True, index=True)
    
    # Suppression reason
    reason = Column(String(50), nullable=False, index=True)  # invalid, opted_out, carrier_blocked
    sub_reason = Column(String(100), nullable=True)
    
    # Source
    provider = Column(String(50), nullable=True)
    original_notification_id = Column(String(50), nullable=True)
    
    # Timestamps
    suppressed_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False, index=True)
    expires_at = Column(DateTime, nullable=True)
    
    # Carrier info
    carrier = Column(String(100), nullable=True)
    carrier_error_code = Column(String(50), nullable=True)
    
    created_date = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    
    def to_dict(self):
        return {
            'id': self.id,
            'phone_hash': self.phone_hash,
            'reason': self.reason,
            'sub_reason': self.sub_reason,
            'provider': self.provider,
            'suppressed_at': self.suppressed_at.isoformat() if self.suppressed_at else None,
            'carrier': self.carrier,
            'created_date': self.created_date.isoformat() if self.created_date else None
        }


class NotificationPreference(Base):
    """
    Customer notification preferences for opt-in/opt-out management.
    """
    __tablename__ = 'notification_preferences'
    
    id = Column(String(50), primary_key=True)
    customer_id = Column(String(50), nullable=False, index=True)
    
    # Channel preferences
    email_enabled = Column(Boolean, default=True)
    sms_enabled = Column(Boolean, default=True)
    push_enabled = Column(Boolean, default=True)
    whatsapp_enabled = Column(Boolean, default=True)
    in_app_enabled = Column(Boolean, default=True)
    webhook_enabled = Column(Boolean, default=True)
    
    # Category preferences (JSON object)
    category_preferences = Column(Text, nullable=True)
    
    # Quiet hours
    quiet_hours_enabled = Column(Boolean, default=False)
    quiet_hours_start = Column(String(5), nullable=True)  # HH:MM format
    quiet_hours_end = Column(String(5), nullable=True)
    quiet_hours_timezone = Column(String(50), nullable=True)
    
    # Frequency limits
    max_daily_notifications = Column(Integer, nullable=True)
    max_weekly_notifications = Column(Integer, nullable=True)
    
    # Language preference
    preferred_language = Column(String(10), default='en')
    
    # Timestamps
    created_date = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_date = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    
    def to_dict(self):
        import json as _json
        
        def safe_json_loads(val):
            if val is None:
                return {}
            try:
                return _json.loads(val)
            except:
                return {}
        
        return {
            'id': self.id,
            'customer_id': self.customer_id,
            'email_enabled': self.email_enabled,
            'sms_enabled': self.sms_enabled,
            'push_enabled': self.push_enabled,
            'whatsapp_enabled': self.whatsapp_enabled,
            'in_app_enabled': self.in_app_enabled,
            'webhook_enabled': self.webhook_enabled,
            'category_preferences': safe_json_loads(self.category_preferences),
            'quiet_hours_enabled': self.quiet_hours_enabled,
            'quiet_hours_start': self.quiet_hours_start,
            'quiet_hours_end': self.quiet_hours_end,
            'quiet_hours_timezone': self.quiet_hours_timezone,
            'max_daily_notifications': self.max_daily_notifications,
            'max_weekly_notifications': self.max_weekly_notifications,
            'preferred_language': self.preferred_language,
            'created_date': self.created_date.isoformat() if self.created_date else None,
            'updated_date': self.updated_date.isoformat() if self.updated_date else None
        }


class NotificationAuditLog(Base):
    """
    Comprehensive audit logging for notification system.
    Tracks all security-relevant events.
    """
    __tablename__ = 'notification_audit_log'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False, index=True)
    
    # Actor
    actor_type = Column(String(20), nullable=False)  # system, user, admin, api
    actor_id = Column(String(100), nullable=True, index=True)
    
    # Action
    action = Column(String(100), nullable=False, index=True)
    action_category = Column(String(50), nullable=True)  # otp, email, sms, config, security
    
    # Target
    target_type = Column(String(50), nullable=True)
    target_id = Column(String(100), nullable=True, index=True)
    
    # Context
    customer_id = Column(String(50), nullable=True, index=True)
    notification_id = Column(String(50), nullable=True)
    
    # Details
    details = Column(Text, nullable=True)  # JSON
    
    # Security context
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(String(500), nullable=True)
    
    # Result
    success = Column(Boolean, default=True)
    error_message = Column(Text, nullable=True)
    
    # Risk indicators
    risk_level = Column(String(20), nullable=True)  # low, medium, high, critical
    flagged_for_review = Column(Boolean, default=False)
    
    __table_args__ = (
        Index('idx_notification_audit_lookup',
              'action', 'timestamp'),
        Index('idx_notification_audit_security',
              'flagged_for_review', 'risk_level', 'timestamp'),
    )
    
    def to_dict(self):
        import json as _json
        
        def safe_json_loads(val):
            if val is None:
                return {}
            try:
                return _json.loads(val)
            except:
                return {}
        
        return {
            'id': self.id,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
            'actor_type': self.actor_type,
            'actor_id': self.actor_id,
            'action': self.action,
            'action_category': self.action_category,
            'target_type': self.target_type,
            'target_id': self.target_id,
            'customer_id': self.customer_id,
            'notification_id': self.notification_id,
            'details': safe_json_loads(self.details),
            'ip_address': self.ip_address,
            'success': self.success,
            'error_message': self.error_message,
            'risk_level': self.risk_level,
            'flagged_for_review': self.flagged_for_review
        }


# Export all models
__all__ = [
    'NotificationChannel',
    'NotificationPriority', 
    'NotificationStatus',
    'VerificationType',
    'OTPStatus',
    'RateLimitAction',
    'NotificationTemplate',
    'NotificationQueue',
    'NotificationHistory',
    'OTPCode',
    'ClientVerification',
    'RateLimitRecord',
    'EmailSuppressionList',
    'SMSSuppressionList',
    'NotificationPreference',
    'NotificationAuditLog',
]
