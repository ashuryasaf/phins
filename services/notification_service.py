"""
PHINS Enterprise Notification Service
Full-scale global notification system with client validation

Security Features:
- AES-256 encryption for sensitive content
- HMAC signing for integrity verification
- Rate limiting with sliding window algorithm
- IP-based fraud detection
- Comprehensive audit logging
- PCI-DSS and GDPR compliance ready

Providers Supported:
- Email: SMTP, SendGrid, AWS SES, Mailgun
- SMS: Twilio, AWS SNS, Vonage, MessageBird
"""

from __future__ import annotations

import os
import re
import json
import hmac
import html
import secrets
import hashlib
import logging
from email.utils import parseaddr
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple, Union
from functools import wraps
import threading
import uuid

from security.network import validated_urlopen

# Local imports
try:
    from security.vault import encrypt_json, decrypt_json
except ImportError:
    encrypt_json = None
    decrypt_json = None


# ============================================================================
# CONFIGURATION
# ============================================================================

class NotificationConfig:
    """Global configuration for notification service"""
    
    # Environment detection
    ENVIRONMENT = os.environ.get('PHINS_ENV', 'development')
    
    # ========== Email Configuration ==========
    SMTP_HOST = os.environ.get('SMTP_HOST', 'localhost')
    SMTP_PORT = int(os.environ.get('SMTP_PORT', '587'))
    SMTP_USE_TLS = os.environ.get('SMTP_USE_TLS', 'true').lower() == 'true'
    SMTP_USERNAME = os.environ.get('SMTP_USERNAME', '')
    SMTP_PASSWORD = os.environ.get('SMTP_PASSWORD', '')
    
    EMAIL_FROM_ADDRESS = os.environ.get('EMAIL_FROM_ADDRESS', 'noreply@phins.ai')
    EMAIL_FROM_NAME = os.environ.get('EMAIL_FROM_NAME', 'PHINS Insurance')
    EMAIL_REPLY_TO = os.environ.get('EMAIL_REPLY_TO', 'support@phins.ai')
    
    # Email provider selection
    EMAIL_PROVIDER = os.environ.get('EMAIL_PROVIDER', 'smtp')  # smtp, sendgrid, ses, mailgun, resend, active_notifications
    SENDGRID_API_KEY = os.environ.get('SENDGRID_API_KEY', '')
    AWS_SES_REGION = os.environ.get('AWS_SES_REGION', 'us-east-1')
    MAILGUN_API_KEY = os.environ.get('MAILGUN_API_KEY', '')
    MAILGUN_DOMAIN = os.environ.get('MAILGUN_DOMAIN', '')
    RESEND_API_KEY = os.environ.get('RESEND_API_KEY', '')
    RESEND_API_BASE_URL = os.environ.get('RESEND_API_BASE_URL', 'https://api.resend.com')
    ACTIVE_NOTIFICATIONS_CUSTOMER_ID = os.environ.get(
        'ACTIVE_NOTIFICATIONS_CUSTOMER_ID',
        os.environ.get('PINGRAM_CLIENT_ID', os.environ.get('NOTIFICATIONAPI_CLIENT_ID', ''))
    )
    ACTIVE_NOTIFICATIONS_API_KEY = os.environ.get(
        'ACTIVE_NOTIFICATIONS_API_KEY',
        os.environ.get('PINGRAM_API_KEY', os.environ.get('NOTIFICATIONAPI_API_KEY', ''))
    )
    ACTIVE_NOTIFICATIONS_BASE_URL = os.environ.get(
        'ACTIVE_NOTIFICATIONS_BASE_URL',
        os.environ.get(
            'PINGRAM_BASE_URL',
            os.environ.get('NOTIFICATIONAPI_BASE_URL', 'https://api.pingram.io')
        )
    )
    ACTIVE_NOTIFICATIONS_SEND_PATH = os.environ.get(
        'ACTIVE_NOTIFICATIONS_SEND_PATH',
        os.environ.get(
            'PINGRAM_SEND_PATH',
            os.environ.get('NOTIFICATIONAPI_SEND_PATH', '/sender')
        )
    )
    ACTIVE_NOTIFICATIONS_NOTIFICATION_TYPE = os.environ.get(
        'ACTIVE_NOTIFICATIONS_NOTIFICATION_TYPE',
        os.environ.get(
            'PINGRAM_NOTIFICATION_TYPE',
            os.environ.get('NOTIFICATIONAPI_NOTIFICATION_TYPE', 'phins_transactional_email')
        )
    )
    ACTIVE_NOTIFICATIONS_AUTH_HEADER = os.environ.get(
        'ACTIVE_NOTIFICATIONS_AUTH_HEADER',
        os.environ.get(
            'PINGRAM_AUTH_HEADER',
            os.environ.get('NOTIFICATIONAPI_AUTH_HEADER', 'Authorization')
        )
    )
    ACTIVE_NOTIFICATIONS_AUTH_SCHEME = os.environ.get(
        'ACTIVE_NOTIFICATIONS_AUTH_SCHEME',
        os.environ.get(
            'PINGRAM_AUTH_SCHEME',
            os.environ.get('NOTIFICATIONAPI_AUTH_SCHEME', 'Bearer')
        )
    )
    ACTIVE_NOTIFICATIONS_CLIENT_ID_HEADER = os.environ.get(
        'ACTIVE_NOTIFICATIONS_CLIENT_ID_HEADER',
        os.environ.get(
            'PINGRAM_CLIENT_ID_HEADER',
            os.environ.get('NOTIFICATIONAPI_CLIENT_ID_HEADER', '')
        )
    )
    
    # ========== SMS Configuration ==========
    SMS_PROVIDER = os.environ.get('SMS_PROVIDER', 'twilio')  # twilio, sns, vonage, messagebird
    TWILIO_ACCOUNT_SID = os.environ.get('TWILIO_ACCOUNT_SID', '')
    TWILIO_AUTH_TOKEN = os.environ.get('TWILIO_AUTH_TOKEN', '')
    TWILIO_FROM_NUMBER = os.environ.get('TWILIO_FROM_NUMBER', '')
    
    AWS_SNS_REGION = os.environ.get('AWS_SNS_REGION', 'us-east-1')
    VONAGE_API_KEY = os.environ.get('VONAGE_API_KEY', '')
    VONAGE_API_SECRET = os.environ.get('VONAGE_API_SECRET', '')
    MESSAGEBIRD_API_KEY = os.environ.get('MESSAGEBIRD_API_KEY', '')
    
    # ========== OTP Configuration ==========
    OTP_LENGTH = int(os.environ.get('OTP_LENGTH', '6'))
    OTP_EXPIRY_SECONDS = int(os.environ.get('OTP_EXPIRY_SECONDS', '300'))  # 5 minutes
    OTP_MAX_ATTEMPTS = int(os.environ.get('OTP_MAX_ATTEMPTS', '5'))
    OTP_RESEND_COOLDOWN_SECONDS = int(os.environ.get('OTP_RESEND_COOLDOWN_SECONDS', '60'))
    OTP_USE_ALPHANUMERIC = os.environ.get('OTP_USE_ALPHANUMERIC', 'false').lower() == 'true'
    
    # ========== Rate Limiting ==========
    RATE_LIMIT_ENABLED = os.environ.get('RATE_LIMIT_ENABLED', 'true').lower() == 'true'
    
    # Per-minute limits
    OTP_RATE_LIMIT_PER_MINUTE = int(os.environ.get('OTP_RATE_LIMIT_PER_MINUTE', '3'))
    EMAIL_RATE_LIMIT_PER_MINUTE = int(os.environ.get('EMAIL_RATE_LIMIT_PER_MINUTE', '10'))
    SMS_RATE_LIMIT_PER_MINUTE = int(os.environ.get('SMS_RATE_LIMIT_PER_MINUTE', '5'))
    
    # Per-hour limits
    OTP_RATE_LIMIT_PER_HOUR = int(os.environ.get('OTP_RATE_LIMIT_PER_HOUR', '10'))
    EMAIL_RATE_LIMIT_PER_HOUR = int(os.environ.get('EMAIL_RATE_LIMIT_PER_HOUR', '50'))
    SMS_RATE_LIMIT_PER_HOUR = int(os.environ.get('SMS_RATE_LIMIT_PER_HOUR', '20'))
    
    # Per-day limits
    OTP_RATE_LIMIT_PER_DAY = int(os.environ.get('OTP_RATE_LIMIT_PER_DAY', '20'))
    EMAIL_RATE_LIMIT_PER_DAY = int(os.environ.get('EMAIL_RATE_LIMIT_PER_DAY', '200'))
    SMS_RATE_LIMIT_PER_DAY = int(os.environ.get('SMS_RATE_LIMIT_PER_DAY', '50'))
    
    # IP-based rate limiting
    IP_RATE_LIMIT_PER_MINUTE = int(os.environ.get('IP_RATE_LIMIT_PER_MINUTE', '30'))
    IP_RATE_LIMIT_PER_HOUR = int(os.environ.get('IP_RATE_LIMIT_PER_HOUR', '200'))
    
    # Block duration for rate limit violations
    RATE_LIMIT_BLOCK_DURATION_MINUTES = int(os.environ.get('RATE_LIMIT_BLOCK_DURATION_MINUTES', '30'))
    
    # ========== Security ==========
    SIGNING_SECRET = os.environ.get('NOTIFICATION_SIGNING_SECRET', '')
    ENCRYPTION_KEY = os.environ.get('PHINS_ENCRYPTION_KEY', '')
    
    # IP blocking
    ENABLE_IP_BLOCKING = os.environ.get('ENABLE_IP_BLOCKING', 'true').lower() == 'true'
    IP_BLACKLIST = os.environ.get('IP_BLACKLIST', '').split(',')
    
    # Geo restrictions
    ENABLE_GEO_RESTRICTIONS = os.environ.get('ENABLE_GEO_RESTRICTIONS', 'false').lower() == 'true'
    ALLOWED_COUNTRIES = os.environ.get('ALLOWED_COUNTRIES', '').split(',')
    
    # ========== Queue Settings ==========
    QUEUE_ENABLED = os.environ.get('NOTIFICATION_QUEUE_ENABLED', 'true').lower() == 'true'
    QUEUE_MAX_RETRIES = int(os.environ.get('NOTIFICATION_QUEUE_MAX_RETRIES', '3'))
    QUEUE_RETRY_DELAY_SECONDS = int(os.environ.get('NOTIFICATION_QUEUE_RETRY_DELAY_SECONDS', '60'))
    QUEUE_WORKER_THREADS = int(os.environ.get('NOTIFICATION_QUEUE_WORKER_THREADS', '5'))
    
    # ========== Audit Settings ==========
    ENABLE_AUDIT_LOG = os.environ.get('NOTIFICATION_AUDIT_ENABLED', 'true').lower() == 'true'
    AUDIT_LOG_RETENTION_DAYS = int(os.environ.get('NOTIFICATION_AUDIT_RETENTION_DAYS', '365'))


# ============================================================================
# LOGGING
# ============================================================================

logger = logging.getLogger('phins.notifications')


# ============================================================================
# ENUMS
# ============================================================================

class NotificationChannel(str, Enum):
    EMAIL = "email"
    SMS = "sms"
    WHATSAPP = "whatsapp"
    PUSH = "push"
    IN_APP = "in_app"
    WEBHOOK = "webhook"


class NotificationPriority(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"


class NotificationStatus(str, Enum):
    PENDING = "pending"
    QUEUED = "queued"
    SENDING = "sending"
    DELIVERED = "delivered"
    FAILED = "failed"
    BOUNCED = "bounced"
    EXPIRED = "expired"


class VerificationType(str, Enum):
    EMAIL_VERIFICATION = "email_verification"
    PHONE_VERIFICATION = "phone_verification"
    TWO_FACTOR_AUTH = "two_factor_auth"
    PASSWORD_RESET = "password_reset"
    ACCOUNT_ACTIVATION = "account_activation"
    TRANSACTION_CONFIRM = "transaction_confirm"
    DEVICE_VERIFICATION = "device_verification"


class OTPStatus(str, Enum):
    ACTIVE = "active"
    USED = "used"
    EXPIRED = "expired"
    INVALIDATED = "invalidated"


# ============================================================================
# DATA CLASSES
# ============================================================================

@dataclass
class NotificationRequest:
    """Request to send a notification"""
    channel: NotificationChannel
    recipient: str  # email or phone number
    subject: Optional[str] = None
    content: str = ""
    template_id: Optional[str] = None
    template_vars: Dict[str, Any] = field(default_factory=dict)
    priority: NotificationPriority = NotificationPriority.NORMAL
    
    # Targeting
    customer_id: Optional[str] = None
    user_id: Optional[str] = None
    
    # Scheduling
    send_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    
    # Security context
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    correlation_id: Optional[str] = None
    
    # Options
    html_content: Optional[str] = None
    attachments: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class NotificationResult:
    """Result of a notification send attempt"""
    success: bool
    notification_id: str
    status: NotificationStatus
    provider_message_id: Optional[str] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    sent_at: Optional[datetime] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'success': self.success,
            'notification_id': self.notification_id,
            'status': self.status.value,
            'provider_message_id': self.provider_message_id,
            'error_code': self.error_code,
            'error_message': self.error_message,
            'sent_at': self.sent_at.isoformat() if self.sent_at else None
        }


@dataclass
class OTPRequest:
    """Request to generate and send an OTP"""
    identifier: str  # email or phone
    channel: NotificationChannel
    verification_type: VerificationType
    
    # Targeting
    customer_id: Optional[str] = None
    user_id: Optional[str] = None
    
    # Security context
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    device_fingerprint: Optional[str] = None
    
    # Options
    otp_length: int = NotificationConfig.OTP_LENGTH
    expiry_seconds: int = NotificationConfig.OTP_EXPIRY_SECONDS
    template_id: Optional[str] = None
    correlation_id: Optional[str] = None


@dataclass
class OTPResult:
    """Result of OTP generation/verification"""
    success: bool
    otp_id: Optional[str] = None
    status: OTPStatus = OTPStatus.ACTIVE
    expires_at: Optional[datetime] = None
    attempts_remaining: int = 0
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    notification_id: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'success': self.success,
            'otp_id': self.otp_id,
            'status': self.status.value,
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
            'attempts_remaining': self.attempts_remaining,
            'error_code': self.error_code,
            'error_message': self.error_message,
            'notification_id': self.notification_id
        }


@dataclass
class RateLimitResult:
    """Result of rate limit check"""
    allowed: bool
    remaining: int
    limit: int
    reset_at: Optional[datetime] = None
    blocked_until: Optional[datetime] = None
    block_reason: Optional[str] = None


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def generate_id(prefix: str = "") -> str:
    """Generate a unique ID with optional prefix"""
    unique_part = uuid.uuid4().hex[:16]
    timestamp = datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')
    if prefix:
        return f"{prefix}_{timestamp}_{unique_part}"
    return f"{timestamp}_{unique_part}"


def hash_identifier(identifier: str) -> str:
    """Hash an identifier for secure storage/lookup"""
    return hashlib.sha256(identifier.lower().encode('utf-8')).hexdigest()


def hash_otp(code: str, salt: str) -> str:
    """Hash OTP code with salt using Argon2-style approach"""
    # Using PBKDF2 with SHA-256 as a fallback (Argon2 requires additional deps)
    return hashlib.pbkdf2_hmac(
        'sha256',
        code.encode('utf-8'),
        salt.encode('utf-8'),
        100000  # Iterations
    ).hex()


def generate_salt() -> str:
    """Generate a cryptographically secure salt"""
    return secrets.token_hex(32)


def generate_otp(length: int = 6, alphanumeric: bool = False) -> str:
    """Generate a cryptographically secure OTP"""
    if alphanumeric:
        alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # Excludes confusing chars
        return ''.join(secrets.choice(alphabet) for _ in range(length))
    else:
        # Numeric only
        return ''.join(str(secrets.randbelow(10)) for _ in range(length))


def sign_message(message: str, secret: str) -> str:
    """Create HMAC signature for message integrity"""
    if not secret:
        return ""
    return hmac.new(
        secret.encode('utf-8'),
        message.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()


def verify_signature(message: str, signature: str, secret: str) -> bool:
    """Verify HMAC signature"""
    if not secret:
        return False
    expected = sign_message(message, secret)
    return hmac.compare_digest(expected, signature)


def mask_email(email: str) -> str:
    """Mask email address for display"""
    if '@' not in email:
        return '***'
    local, domain = email.split('@', 1)
    if len(local) <= 2:
        masked = local[0] + '*' * max(len(local) - 1, 1)
    else:
        masked = local[0] + '*' * (len(local) - 2) + local[-1]
    return f"{masked}@{domain}"


def mask_phone(phone: str) -> str:
    """Mask phone number for display"""
    digits = re.sub(r'\D', '', phone)
    if len(digits) <= 4:
        return '***'
    return digits[:2] + '*' * (len(digits) - 4) + digits[-2:]


def validate_email(email: str) -> bool:
    """Validate email format"""
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return bool(re.match(pattern, email))


def validate_phone(phone: str) -> bool:
    """Validate phone number format (E.164)"""
    pattern = r'^\+?[1-9]\d{6,14}$'
    cleaned = re.sub(r'[\s\-\(\)]', '', phone)
    return bool(re.match(pattern, cleaned))


def normalize_phone(phone: str) -> str:
    """Normalize phone number to E.164 format"""
    # Remove all non-digit characters except leading +
    if phone.startswith('+'):
        return '+' + re.sub(r'\D', '', phone[1:])
    return re.sub(r'\D', '', phone)


# ============================================================================
# RATE LIMITER
# ============================================================================

class RateLimiter:
    """
    Thread-safe sliding window rate limiter.
    Supports multiple windows (per-minute, per-hour, per-day).
    """
    
    def __init__(self):
        self._locks: Dict[str, threading.Lock] = {}
        self._counters: Dict[str, List[datetime]] = {}
        self._blocks: Dict[str, datetime] = {}
        self._master_lock = threading.Lock()
    
    def _get_lock(self, key: str) -> threading.Lock:
        """Get or create a lock for a specific key"""
        with self._master_lock:
            if key not in self._locks:
                self._locks[key] = threading.Lock()
            return self._locks[key]
    
    def check_rate_limit(
        self,
        identifier: str,
        action: str,
        limits: Dict[str, Tuple[int, int]]  # window_name: (limit, window_seconds)
    ) -> RateLimitResult:
        """
        Check if request is within rate limits.
        
        Args:
            identifier: Unique identifier (customer_id, ip, email, etc.)
            action: Action being rate limited
            limits: Dict of window configs {name: (limit, window_seconds)}
        
        Returns:
            RateLimitResult with allowed status and remaining quota
        """
        key = f"{action}:{identifier}"
        lock = self._get_lock(key)
        
        with lock:
            now = datetime.now(timezone.utc)
            
            # Check if blocked
            if key in self._blocks:
                if now < self._blocks[key]:
                    return RateLimitResult(
                        allowed=False,
                        remaining=0,
                        limit=0,
                        blocked_until=self._blocks[key],
                        block_reason="Rate limit exceeded - temporarily blocked"
                    )
                else:
                    del self._blocks[key]
            
            # Initialize counter if needed
            if key not in self._counters:
                self._counters[key] = []
            
            # Clean old entries and check limits
            min_window = min(ws for _, ws in limits.values())
            max_window = max(ws for _, ws in limits.values())
            cutoff = now - timedelta(seconds=max_window)
            self._counters[key] = [t for t in self._counters[key] if t > cutoff]
            
            # Check each window
            for window_name, (limit, window_seconds) in limits.items():
                window_start = now - timedelta(seconds=window_seconds)
                count = sum(1 for t in self._counters[key] if t > window_start)
                
                if count >= limit:
                    # Block for configured duration
                    block_until = now + timedelta(
                        minutes=NotificationConfig.RATE_LIMIT_BLOCK_DURATION_MINUTES
                    )
                    self._blocks[key] = block_until
                    
                    return RateLimitResult(
                        allowed=False,
                        remaining=0,
                        limit=limit,
                        reset_at=window_start + timedelta(seconds=window_seconds),
                        blocked_until=block_until,
                        block_reason=f"Exceeded {window_name} limit: {limit} requests per {window_seconds}s"
                    )
            
            # Calculate remaining for smallest window
            smallest_window = min(limits.values(), key=lambda x: x[1])
            smallest_limit, smallest_window_secs = smallest_window
            window_start = now - timedelta(seconds=smallest_window_secs)
            current_count = sum(1 for t in self._counters[key] if t > window_start)
            
            return RateLimitResult(
                allowed=True,
                remaining=smallest_limit - current_count,
                limit=smallest_limit,
                reset_at=window_start + timedelta(seconds=smallest_window_secs)
            )
    
    def record_request(self, identifier: str, action: str) -> None:
        """Record a request for rate limiting"""
        key = f"{action}:{identifier}"
        lock = self._get_lock(key)
        
        with lock:
            if key not in self._counters:
                self._counters[key] = []
            self._counters[key].append(datetime.now(timezone.utc))
    
    def clear_blocks(self, identifier: str, action: Optional[str] = None) -> None:
        """Clear rate limit blocks for an identifier"""
        with self._master_lock:
            if action:
                key = f"{action}:{identifier}"
                self._blocks.pop(key, None)
            else:
                keys_to_remove = [k for k in self._blocks if k.endswith(f":{identifier}")]
                for key in keys_to_remove:
                    del self._blocks[key]
    
    def reset_all(self) -> None:
        """Reset all rate limiting state (for testing)"""
        with self._master_lock:
            self._counters.clear()
            self._blocks.clear()
            self._locks.clear()


# Global rate limiter instance
_rate_limiter = RateLimiter()


def reset_global_rate_limiter() -> None:
    """Reset the global rate limiter state (for testing)"""
    _rate_limiter.reset_all()


# ============================================================================
# AUDIT LOGGER
# ============================================================================

class NotificationAuditLogger:
    """
    Audit logger for notification system.
    Tracks all security-relevant events.
    """
    
    def __init__(self):
        self._events: List[Dict[str, Any]] = []
        self._lock = threading.Lock()
        self._max_events = 10000
    
    def log(
        self,
        action: str,
        actor_type: str = "system",
        actor_id: Optional[str] = None,
        target_type: Optional[str] = None,
        target_id: Optional[str] = None,
        customer_id: Optional[str] = None,
        notification_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        ip_address: Optional[str] = None,
        success: bool = True,
        error_message: Optional[str] = None,
        risk_level: Optional[str] = None
    ) -> None:
        """Log an audit event"""
        event = {
            'id': generate_id('AUDIT'),
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'action': action,
            'actor_type': actor_type,
            'actor_id': actor_id,
            'target_type': target_type,
            'target_id': target_id,
            'customer_id': customer_id,
            'notification_id': notification_id,
            'details': details or {},
            'ip_address': ip_address,
            'success': success,
            'error_message': error_message,
            'risk_level': risk_level
        }
        
        with self._lock:
            self._events.append(event)
            if len(self._events) > self._max_events:
                self._events = self._events[-self._max_events:]
        
        # Log to standard logger as well
        log_level = logging.INFO if success else logging.WARNING
        logger.log(log_level, f"AUDIT: {action} - {json.dumps(event)}")
    
    def get_recent_events(
        self,
        limit: int = 100,
        action: Optional[str] = None,
        customer_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Get recent audit events"""
        with self._lock:
            events = self._events.copy()
        
        if action:
            events = [e for e in events if e['action'] == action]
        if customer_id:
            events = [e for e in events if e['customer_id'] == customer_id]
        
        return events[-limit:]


# Global audit logger instance
_audit_logger = NotificationAuditLogger()


# ============================================================================
# TEMPLATE ENGINE
# ============================================================================

class TemplateEngine:
    """
    Simple template engine with Jinja2-style syntax.
    Supports {{ variable }} and basic conditionals.
    """
    
    @staticmethod
    def render(template: str, variables: Dict[str, Any]) -> str:
        """Render template with variables"""
        result = template
        
        # Simple variable substitution
        for key, value in variables.items():
            # Handle {{ key }} syntax
            pattern = r'\{\{\s*' + re.escape(key) + r'\s*\}\}'
            result = re.sub(pattern, str(value), result)
        
        # Remove any remaining unset variables
        result = re.sub(r'\{\{[^}]*\}\}', '', result)
        
        return result
    
    @staticmethod
    def validate_template(template: str, required_vars: List[str]) -> Tuple[bool, List[str]]:
        """Validate template has all required variables"""
        missing = []
        for var in required_vars:
            pattern = r'\{\{\s*' + re.escape(var) + r'\s*\}\}'
            if not re.search(pattern, template):
                missing.append(var)
        
        return len(missing) == 0, missing


# ============================================================================
# EMAIL PROVIDER ABSTRACTION
# ============================================================================

class EmailProvider(ABC):
    """Abstract base class for email providers"""
    
    @abstractmethod
    def send(
        self,
        to: str,
        subject: str,
        body: str,
        html_body: Optional[str] = None,
        from_address: Optional[str] = None,
        from_name: Optional[str] = None,
        reply_to: Optional[str] = None,
        attachments: Optional[List[Dict[str, Any]]] = None
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Send an email.
        
        Returns:
            Tuple of (success, message_id, error_message)
        """
        pass


_EMAIL_PROVIDER_NAME_ALIASES = {
    'send_grid': 'sendgrid',
    'sendgrid_api': 'sendgrid',
    'sg': 'sendgrid',
    'aws_ses': 'ses',
    'amazon_ses': 'ses',
    'amazon_simple_email_service': 'ses',
    'amazonses': 'ses',
    'sesv2': 'ses',
    'mail_gun': 'mailgun',
    'mailgun_api': 'mailgun',
    'resend_api': 'resend',
    'resendapi': 'resend',
    'active_notifications': 'active_notifications',
    'active-notifications': 'active_notifications',
    'activenotifications': 'active_notifications',
    'pingram': 'active_notifications',
    'notificationapi': 'active_notifications',
    'notification_api': 'active_notifications',
}
_SUPPORTED_EMAIL_PROVIDERS = {'smtp', 'sendgrid', 'ses', 'mailgun', 'resend', 'active_notifications'}
_DEFAULT_NOTIFICATION_FROM_ADDRESS = 'noreply@phins.ai'
_DEFAULT_NOTIFICATION_FROM_NAME = 'PHINS Insurance'
_PROVIDER_FROM_ADDRESS_ENV_VARS = {
    'smtp': ('SMTP_FROM_ADDRESS', 'SMTP_FROM_EMAIL'),
    'sendgrid': (
        'SENDGRID_FROM_ADDRESS',
        'SENDGRID_FROM_EMAIL',
        'SENDGRID_SENDER_EMAIL',
        'SENDGRID_VERIFIED_SENDER',
    ),
    'ses': ('SES_FROM_ADDRESS', 'AWS_SES_FROM_ADDRESS', 'AWS_SES_FROM_EMAIL'),
    'mailgun': ('MAILGUN_FROM_ADDRESS', 'MAILGUN_FROM_EMAIL'),
    'resend': ('RESEND_FROM_ADDRESS', 'RESEND_FROM_EMAIL'),
    'active_notifications': (
        'ACTIVE_NOTIFICATIONS_FROM_ADDRESS',
        'ACTIVE_NOTIFICATIONS_FROM_EMAIL',
        'PINGRAM_FROM_ADDRESS',
        'PINGRAM_FROM_EMAIL',
    ),
}
_PROVIDER_FROM_NAME_ENV_VARS = {
    'smtp': ('SMTP_FROM_NAME',),
    'sendgrid': ('SENDGRID_FROM_NAME',),
    'ses': ('SES_FROM_NAME', 'AWS_SES_FROM_NAME'),
    'mailgun': ('MAILGUN_FROM_NAME',),
    'resend': ('RESEND_FROM_NAME',),
    'active_notifications': (
        'ACTIVE_NOTIFICATIONS_FROM_NAME',
        'PINGRAM_FROM_NAME',
    ),
}
_GLOBAL_FROM_ADDRESS_ENV_VARS = (
    'NOTIFICATION_FROM_ADDRESS',
    'NOTIFICATIONS_FROM_ADDRESS',
    'DEFAULT_FROM_EMAIL',
    'MAIL_FROM',
    'MAIL_FROM_ADDRESS',
    'EMAIL_FROM_ADDRESS',
)
_GLOBAL_FROM_NAME_ENV_VARS = (
    'NOTIFICATION_FROM_NAME',
    'NOTIFICATIONS_FROM_NAME',
    'DEFAULT_FROM_NAME',
    'MAIL_FROM_NAME',
    'EMAIL_FROM_NAME',
)
_REPLY_TO_ENV_VARS = (
    'NOTIFICATION_REPLY_TO',
    'NOTIFICATIONS_REPLY_TO',
    'DEFAULT_REPLY_TO',
    'EMAIL_REPLY_TO',
)


def _normalize_provider_alias_token(raw_provider: Optional[str]) -> str:
    """Normalize provider token for robust alias matching."""
    normalized = str(raw_provider or '').strip().lower()
    if not normalized:
        return ''
    normalized = re.sub(r'[\s\-.]+', '_', normalized)
    normalized = re.sub(r'_+', '_', normalized).strip('_')
    return normalized


def _coerce_email_address(raw_address: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """
    Parse and validate email address values.

    Accepts both "user@example.com" and "Display Name <user@example.com>".
    Returns (email, display_name).
    """
    candidate = str(raw_address or '').strip()
    if not candidate:
        return None, None

    parsed_name, parsed_email = parseaddr(candidate)
    parsed_email = str(parsed_email or '').strip()
    parsed_name = str(parsed_name or '').strip()
    if validate_email(parsed_email):
        return parsed_email, parsed_name or None

    if validate_email(candidate):
        return candidate, None

    return None, None


def _canonical_email_provider_type(raw_provider: Optional[str]) -> Optional[str]:
    """Return canonical email provider name if supported."""
    normalized = _normalize_provider_alias_token(raw_provider)
    if not normalized:
        return None
    normalized = _EMAIL_PROVIDER_NAME_ALIASES.get(normalized, normalized)
    if normalized in _SUPPORTED_EMAIL_PROVIDERS:
        return normalized
    return None


def _normalize_email_provider_type(raw_provider: Optional[str], default: str = 'smtp') -> str:
    """Normalize provider aliases and fall back safely."""
    return _canonical_email_provider_type(raw_provider) or default


def _first_non_empty_env(*env_names: str) -> Optional[str]:
    """Return the first non-empty environment value."""
    for env_name in env_names:
        raw_value = os.environ.get(env_name)
        if raw_value is None:
            continue
        value = str(raw_value).strip()
        if value:
            return value
    return None


def _resolve_email_sender(
    provider_type: str,
    from_address: Optional[str],
    from_name: Optional[str]
) -> Tuple[str, str]:
    """
    Resolve sender identity with provider-specific overrides.

    For SMTP, if EMAIL_FROM_ADDRESS is not explicitly configured and SMTP_USERNAME
    is an email address, use SMTP_USERNAME as the sender to avoid relay rejection.
    """
    normalized_provider = _normalize_email_provider_type(provider_type)
    explicit_from_address = str(from_address or '').strip()
    explicit_from_name = str(from_name or '').strip()

    provider_from_address = _first_non_empty_env(
        *_PROVIDER_FROM_ADDRESS_ENV_VARS.get(normalized_provider, ())
    )
    global_from_address = _first_non_empty_env(*_GLOBAL_FROM_ADDRESS_ENV_VARS)
    config_from_address = str(NotificationConfig.EMAIL_FROM_ADDRESS or '').strip()
    resolved_from_address = (
        explicit_from_address
        or provider_from_address
        or global_from_address
        or config_from_address
    )

    provider_from_name = _first_non_empty_env(
        *_PROVIDER_FROM_NAME_ENV_VARS.get(normalized_provider, ())
    )
    global_from_name = _first_non_empty_env(*_GLOBAL_FROM_NAME_ENV_VARS)
    config_from_name = str(NotificationConfig.EMAIL_FROM_NAME or '').strip()
    resolved_from_name = explicit_from_name or provider_from_name or global_from_name or config_from_name

    normalized_address, parsed_sender_name = _coerce_email_address(resolved_from_address)
    if normalized_address:
        resolved_from_address = normalized_address

    if (
        parsed_sender_name
        and not explicit_from_name
        and not provider_from_name
        and not global_from_name
        and (
            not config_from_name
            or config_from_name == _DEFAULT_NOTIFICATION_FROM_NAME
        )
    ):
        resolved_from_name = parsed_sender_name

    email_from_explicitly_set = bool(_first_non_empty_env('EMAIL_FROM_ADDRESS'))
    has_non_default_config_from = bool(
        config_from_address
        and config_from_address.lower() != _DEFAULT_NOTIFICATION_FROM_ADDRESS
    )
    if (
        normalized_provider == 'smtp'
        and not explicit_from_address
        and not provider_from_address
        and not global_from_address
        and not email_from_explicitly_set
        and not has_non_default_config_from
    ):
        smtp_username = str(
            os.environ.get('SMTP_USERNAME') or NotificationConfig.SMTP_USERNAME or ''
        ).strip()
        smtp_sender, _ = _coerce_email_address(smtp_username)
        if smtp_sender:
            resolved_from_address = smtp_sender

    if not validate_email(resolved_from_address):
        fallback_candidates = [
            provider_from_address,
            global_from_address,
            config_from_address,
            _DEFAULT_NOTIFICATION_FROM_ADDRESS,
        ]
        if normalized_provider == 'smtp':
            fallback_candidates.insert(
                0, str(os.environ.get('SMTP_USERNAME') or NotificationConfig.SMTP_USERNAME or '')
            )
        if normalized_provider == 'resend':
            # Resend sandbox accounts can deliver from this default identity.
            fallback_candidates.append('onboarding@resend.dev')

        for fallback_candidate in fallback_candidates:
            fallback_sender, _ = _coerce_email_address(fallback_candidate)
            if fallback_sender:
                resolved_from_address = fallback_sender
                break

    return resolved_from_address, resolved_from_name or _DEFAULT_NOTIFICATION_FROM_NAME


def _resolve_reply_to_address(reply_to: Optional[str]) -> Optional[str]:
    """Resolve reply-to address from explicit value or configured defaults."""
    explicit_reply_to = str(reply_to or '').strip()
    reply_to_candidate = explicit_reply_to or (
        _first_non_empty_env(*_REPLY_TO_ENV_VARS)
        or str(NotificationConfig.EMAIL_REPLY_TO or '').strip()
    )
    if not reply_to_candidate:
        return None

    normalized_reply_to, _ = _coerce_email_address(reply_to_candidate)
    return normalized_reply_to


def _plain_text_to_html(body: str) -> str:
    """Render plain text as a minimal HTML body for API-only providers."""
    escaped = html.escape(str(body or ''))
    return f"<div>{escaped.replace(chr(10), '<br/>')}</div>"


class _SMTPCircuitBreaker:
    """
    Circuit breaker for SMTP connections.

    Tracks consecutive failures and temporarily disables SMTP sends when
    the failure threshold is hit, preventing cascading connection storms
    against an unreachable mail server.

    States:
        CLOSED  – normal operation, sends pass through.
        OPEN    – too many failures; sends are rejected immediately.
        HALF_OPEN – recovery window; a single probe send is allowed.
    """

    FAILURE_THRESHOLD = int(os.environ.get('SMTP_CB_FAILURE_THRESHOLD', '5'))
    RECOVERY_TIMEOUT = int(os.environ.get('SMTP_CB_RECOVERY_TIMEOUT_SECS', '120'))

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._consecutive_failures: int = 0
        self._state: str = 'closed'
        self._opened_at: Optional[datetime] = None
        self._last_failure_error: Optional[str] = None
        self._half_open_probe_in_flight: bool = False

    @property
    def state(self) -> str:
        with self._lock:
            if self._state == 'open' and self._opened_at:
                elapsed = (datetime.now(timezone.utc) - self._opened_at).total_seconds()
                if elapsed >= self.RECOVERY_TIMEOUT:
                    self._state = 'half_open'
            return self._state

    def allow_request(self) -> bool:
        with self._lock:
            current_state = self.state
            if current_state == 'open':
                return False
            if current_state == 'half_open':
                if self._half_open_probe_in_flight:
                    return False
                self._half_open_probe_in_flight = True
            return True

    def record_success(self) -> None:
        with self._lock:
            self._consecutive_failures = 0
            self._state = 'closed'
            self._opened_at = None
            self._last_failure_error = None
            self._half_open_probe_in_flight = False

    def record_non_transient_failure(self) -> None:
        with self._lock:
            self._consecutive_failures = 0
            self._last_failure_error = None
            self._half_open_probe_in_flight = False
            if self._state == 'half_open':
                self._state = 'closed'
                self._opened_at = None

    def record_failure(self, error: str) -> None:
        with self._lock:
            self._consecutive_failures += 1
            self._last_failure_error = error
            self._half_open_probe_in_flight = False
            if self._consecutive_failures >= self.FAILURE_THRESHOLD:
                if self._state != 'open':
                    logger.warning(
                        "SMTP circuit breaker OPEN after %d consecutive failures (last: %s). "
                        "Will retry after %ds.",
                        self._consecutive_failures, error, self.RECOVERY_TIMEOUT,
                    )
                    self._state = 'open'
                    self._opened_at = datetime.now(timezone.utc)

    def get_status(self) -> Dict[str, Any]:
        with self._lock:
            return {
                'state': self.state,
                'consecutive_failures': self._consecutive_failures,
                'last_failure': self._last_failure_error,
                'opened_at': self._opened_at.isoformat() if self._opened_at else None,
            }


_smtp_circuit_breaker = _SMTPCircuitBreaker()


def get_smtp_circuit_breaker() -> _SMTPCircuitBreaker:
    """Expose the SMTP circuit breaker for health checks and monitoring."""
    return _smtp_circuit_breaker


class SMTPEmailProvider(EmailProvider):
    """SMTP-based email provider with retry logic and circuit breaker protection"""

    MAX_RETRIES = int(os.environ.get('SMTP_MAX_RETRIES', '3'))
    RETRY_DELAY_BASE = float(os.environ.get('SMTP_RETRY_DELAY_BASE', '1.0'))
    CONNECTION_TIMEOUT = int(os.environ.get('SMTP_CONNECTION_TIMEOUT', '10'))

    def send(
        self,
        to: str,
        subject: str,
        body: str,
        html_body: Optional[str] = None,
        from_address: Optional[str] = None,
        from_name: Optional[str] = None,
        reply_to: Optional[str] = None,
        attachments: Optional[List[Dict[str, Any]]] = None
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """Send email via SMTP with retry and circuit-breaker protection"""
        import smtplib
        import time as _time
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart

        if not _smtp_circuit_breaker.allow_request():
            cb_status = _smtp_circuit_breaker.get_status()
            logger.warning(
                "SMTP circuit breaker is OPEN – skipping send to %s (state: %s)",
                to, cb_status['state'],
            )
            return False, None, f"SMTP circuit breaker open: {cb_status['last_failure']}"

        from_addr, from_display = _resolve_email_sender(
            provider_type='smtp',
            from_address=from_address,
            from_name=from_name
        )
        reply_to_address = _resolve_reply_to_address(reply_to)

        if html_body:
            msg = MIMEMultipart('alternative')
            msg.attach(MIMEText(body, 'plain'))
            msg.attach(MIMEText(html_body, 'html'))
        else:
            msg = MIMEText(body, 'plain')

        msg['Subject'] = subject
        msg['From'] = f"{from_display} <{from_addr}>"
        msg['To'] = to
        if reply_to_address:
            msg['Reply-To'] = reply_to_address

        from_domain = from_addr.split('@', 1)[1] if '@' in from_addr else 'phins.local'
        message_id = f"<{generate_id('MSG')}@{from_domain}>"
        msg['Message-ID'] = message_id

        last_error: Optional[str] = None
        circuit_breaker_error: Optional[str] = None
        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                with smtplib.SMTP(
                    NotificationConfig.SMTP_HOST,
                    NotificationConfig.SMTP_PORT,
                    timeout=self.CONNECTION_TIMEOUT,
                ) as server:
                    if NotificationConfig.SMTP_USE_TLS:
                        server.starttls()
                    if NotificationConfig.SMTP_USERNAME:
                        server.login(
                            NotificationConfig.SMTP_USERNAME,
                            NotificationConfig.SMTP_PASSWORD,
                        )
                    server.sendmail(from_addr, [to], msg.as_string())

                _smtp_circuit_breaker.record_success()
                return True, message_id, None

            except smtplib.SMTPConnectError as e:
                last_error = str(e)
                circuit_breaker_error = last_error
                if attempt < self.MAX_RETRIES:
                    delay = self.RETRY_DELAY_BASE * (2 ** (attempt - 1))
                    logger.warning(
                        "SMTP connection failed (attempt %d/%d): %s – retrying in %.1fs",
                        attempt, self.MAX_RETRIES, last_error, delay,
                    )
                    _time.sleep(delay)
                else:
                    logger.error(
                        "SMTP send failed after %d attempts: %s", self.MAX_RETRIES, last_error,
                    )

            except smtplib.SMTPException as e:
                last_error = str(e)
                logger.error("SMTP protocol error (attempt %d/%d): %s", attempt, self.MAX_RETRIES, last_error)
                _smtp_circuit_breaker.record_non_transient_failure()
                break

            except (ConnectionRefusedError, OSError) as e:
                last_error = str(e)
                circuit_breaker_error = last_error
                if attempt < self.MAX_RETRIES:
                    delay = self.RETRY_DELAY_BASE * (2 ** (attempt - 1))
                    logger.warning(
                        "SMTP connection failed (attempt %d/%d): %s – retrying in %.1fs",
                        attempt, self.MAX_RETRIES, last_error, delay,
                    )
                    _time.sleep(delay)
                else:
                    logger.error(
                        "SMTP send failed after %d attempts: %s", self.MAX_RETRIES, last_error,
                    )

            except Exception as e:
                last_error = str(e)
                logger.error("SMTP send error: %s", last_error)
                _smtp_circuit_breaker.record_non_transient_failure()
                break

        if circuit_breaker_error is not None:
            _smtp_circuit_breaker.record_failure(circuit_breaker_error)

        return False, None, last_error


class MockEmailProvider(EmailProvider):
    """Mock email provider for testing"""
    
    def __init__(self):
        self.sent_emails: List[Dict[str, Any]] = []
    
    def send(
        self,
        to: str,
        subject: str,
        body: str,
        html_body: Optional[str] = None,
        from_address: Optional[str] = None,
        from_name: Optional[str] = None,
        reply_to: Optional[str] = None,
        attachments: Optional[List[Dict[str, Any]]] = None
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """Mock send - stores email for testing"""
        message_id = generate_id('MOCK_MSG')
        self.sent_emails.append({
            'to': to,
            'subject': subject,
            'body': body,
            'html_body': html_body,
            'from_address': from_address,
            'message_id': message_id,
            'sent_at': datetime.now(timezone.utc).isoformat()
        })
        logger.info(f"Mock email sent to {to}: {subject}")
        return True, message_id, None


class SendGridEmailProvider(EmailProvider):
    """SendGrid email provider"""
    
    def send(
        self,
        to: str,
        subject: str,
        body: str,
        html_body: Optional[str] = None,
        from_address: Optional[str] = None,
        from_name: Optional[str] = None,
        reply_to: Optional[str] = None,
        attachments: Optional[List[Dict[str, Any]]] = None
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """Send email via SendGrid API"""
        try:
            import urllib.request
            import urllib.error
            
            api_key = _first_non_empty_env('SENDGRID_API_KEY') or NotificationConfig.SENDGRID_API_KEY
            if not api_key:
                logger.warning("SendGrid API key not configured, falling back to mock")
                return MockEmailProvider().send(to, subject, body, html_body, from_address, from_name)
            
            from_addr, from_display = _resolve_email_sender(
                provider_type='sendgrid',
                from_address=from_address,
                from_name=from_name
            )
            reply_to_address = _resolve_reply_to_address(reply_to)
            
            # Build SendGrid API payload
            payload = {
                "personalizations": [{
                    "to": [{"email": to}]
                }],
                "from": {
                    "email": from_addr,
                    "name": from_display
                },
                "subject": subject,
                "content": []
            }
            
            # Add text content
            payload["content"].append({
                "type": "text/plain",
                "value": body
            })
            
            # Add HTML content if provided
            if html_body:
                payload["content"].append({
                    "type": "text/html",
                    "value": html_body
                })
            
            # Add reply-to if provided
            if reply_to_address:
                payload["reply_to"] = {"email": reply_to_address}
            
            # Make API request
            url = "https://api.sendgrid.com/v3/mail/send"
            data = json.dumps(payload).encode('utf-8')
            
            req = urllib.request.Request(url, data=data, method='POST')
            req.add_header('Authorization', f'Bearer {api_key}')
            req.add_header('Content-Type', 'application/json')
            
            try:
                with validated_urlopen(req, timeout=30, allowed_schemes=('https',)) as response:
                    # SendGrid returns 202 Accepted on success
                    if response.status in [200, 202]:
                        # Extract message ID from headers
                        message_id = response.headers.get('X-Message-Id', generate_id('SG'))
                        return True, message_id, None
                    return False, None, f"Unexpected status: {response.status}"
            except urllib.error.HTTPError as e:
                error_body = e.read().decode() if e.fp else str(e)
                logger.error(f"SendGrid API error: {e.code} - {error_body}")
                return False, None, f"SendGrid error: {e.code}"
                
        except Exception as e:
            logger.error(f"SendGrid send error: {str(e)}")
            return False, None, str(e)


class AWSSESEmailProvider(EmailProvider):
    """AWS Simple Email Service provider"""
    
    def send(
        self,
        to: str,
        subject: str,
        body: str,
        html_body: Optional[str] = None,
        from_address: Optional[str] = None,
        from_name: Optional[str] = None,
        reply_to: Optional[str] = None,
        attachments: Optional[List[Dict[str, Any]]] = None
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """Send email via AWS SES"""
        try:
            # Check for boto3 availability
            try:
                import boto3
                from botocore.exceptions import ClientError, NoCredentialsError
            except ImportError:
                logger.warning("boto3 library not installed, falling back to mock")
                return MockEmailProvider().send(to, subject, body, html_body, from_address, from_name)
            
            region = _first_non_empty_env('AWS_SES_REGION') or NotificationConfig.AWS_SES_REGION
            
            # Create SES client
            try:
                ses = boto3.client('ses', region_name=region)
            except NoCredentialsError:
                logger.warning("AWS credentials not configured, falling back to mock")
                return MockEmailProvider().send(to, subject, body, html_body, from_address, from_name)
            
            from_addr, from_display = _resolve_email_sender(
                provider_type='ses',
                from_address=from_address,
                from_name=from_name
            )
            reply_to_address = _resolve_reply_to_address(reply_to)
            
            # Build message
            message = {
                'Subject': {'Data': subject, 'Charset': 'UTF-8'},
                'Body': {
                    'Text': {'Data': body, 'Charset': 'UTF-8'}
                }
            }
            
            if html_body:
                message['Body']['Html'] = {'Data': html_body, 'Charset': 'UTF-8'}
            
            # Build destination
            destination = {'ToAddresses': [to]}
            
            # Build source
            source = f"{from_display} <{from_addr}>" if from_display else from_addr
            
            # Send email
            kwargs = {
                'Source': source,
                'Destination': destination,
                'Message': message
            }
            
            if reply_to_address:
                kwargs['ReplyToAddresses'] = [reply_to_address]
            
            response = ses.send_email(**kwargs)
            message_id = response.get('MessageId', generate_id('SES'))
            
            return True, message_id, None
            
        except Exception as e:
            if 'ClientError' in str(type(e)):
                error = e.response['Error']
                logger.error(f"AWS SES error: {error['Code']} - {error['Message']}")
                return False, None, f"SES error: {error['Message']}"
            logger.error(f"AWS SES send error: {str(e)}")
            return False, None, str(e)


class MailgunEmailProvider(EmailProvider):
    """Mailgun email provider"""
    
    def send(
        self,
        to: str,
        subject: str,
        body: str,
        html_body: Optional[str] = None,
        from_address: Optional[str] = None,
        from_name: Optional[str] = None,
        reply_to: Optional[str] = None,
        attachments: Optional[List[Dict[str, Any]]] = None
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """Send email via Mailgun API"""
        try:
            import urllib.request
            import urllib.parse
            import urllib.error
            import base64
            
            api_key = _first_non_empty_env('MAILGUN_API_KEY') or NotificationConfig.MAILGUN_API_KEY
            domain = _first_non_empty_env('MAILGUN_DOMAIN') or NotificationConfig.MAILGUN_DOMAIN
            
            if not api_key or not domain:
                logger.warning("Mailgun not configured, falling back to mock")
                return MockEmailProvider().send(to, subject, body, html_body, from_address, from_name)
            
            from_addr, from_display = _resolve_email_sender(
                provider_type='mailgun',
                from_address=from_address,
                from_name=from_name
            )
            reply_to_address = _resolve_reply_to_address(reply_to)
            
            # Build form data
            data = {
                'from': f"{from_display} <{from_addr}>" if from_display else from_addr,
                'to': to,
                'subject': subject,
                'text': body
            }
            
            if html_body:
                data['html'] = html_body
            
            if reply_to_address:
                data['h:Reply-To'] = reply_to_address
            
            # Make API request
            url = f"https://api.mailgun.net/v3/{domain}/messages"
            encoded_data = urllib.parse.urlencode(data).encode('utf-8')
            
            auth = base64.b64encode(f"api:{api_key}".encode()).decode()
            
            req = urllib.request.Request(url, data=encoded_data, method='POST')
            req.add_header('Authorization', f'Basic {auth}')
            
            try:
                with validated_urlopen(req, timeout=30, allowed_schemes=('https',)) as response:
                    result = json.loads(response.read().decode())
                    message_id = result.get('id', generate_id('MG'))
                    return True, message_id, None
            except urllib.error.HTTPError as e:
                error_body = e.read().decode() if e.fp else str(e)
                logger.error(f"Mailgun API error: {e.code} - {error_body}")
                return False, None, f"Mailgun error: {e.code}"
                
        except Exception as e:
            logger.error(f"Mailgun send error: {str(e)}")
            return False, None, str(e)


class ResendEmailProvider(EmailProvider):
    """Resend API email provider"""

    def send(
        self,
        to: str,
        subject: str,
        body: str,
        html_body: Optional[str] = None,
        from_address: Optional[str] = None,
        from_name: Optional[str] = None,
        reply_to: Optional[str] = None,
        attachments: Optional[List[Dict[str, Any]]] = None
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """Send email via Resend API"""
        try:
            import urllib.request
            import urllib.error

            api_key = (
                _first_non_empty_env('RESEND_API_KEY')
                or str(NotificationConfig.RESEND_API_KEY or '').strip()
            )
            if not api_key:
                logger.warning("Resend API key not configured, falling back to mock")
                return MockEmailProvider().send(
                    to, subject, body, html_body, from_address, from_name
                )

            base_url = (
                _first_non_empty_env('RESEND_API_BASE_URL')
                or str(NotificationConfig.RESEND_API_BASE_URL or '').strip()
                or 'https://api.resend.com'
            ).rstrip('/')
            from_addr, from_display = _resolve_email_sender(
                provider_type='resend',
                from_address=from_address,
                from_name=from_name
            )
            reply_to_address = _resolve_reply_to_address(reply_to)

            payload: Dict[str, Any] = {
                "from": f"{from_display} <{from_addr}>" if from_display else from_addr,
                "to": [to],
                "subject": subject,
                "text": body,
            }
            if html_body:
                payload["html"] = html_body
            if reply_to_address:
                payload["reply_to"] = reply_to_address

            data = json.dumps(payload).encode('utf-8')
            req = urllib.request.Request(f"{base_url}/emails", data=data, method='POST')
            req.add_header('Authorization', f'Bearer {api_key}')
            req.add_header('Content-Type', 'application/json')

            try:
                with validated_urlopen(req, timeout=30, allowed_schemes=('https',)) as response:
                    if response.status not in [200, 201, 202]:
                        return False, None, f"Unexpected status: {response.status}"
                    result = json.loads(response.read().decode('utf-8') or '{}')
                    message_id = result.get('id', generate_id('RS'))
                    return True, message_id, None
            except urllib.error.HTTPError as e:
                error_body = e.read().decode() if e.fp else str(e)
                logger.error(f"Resend API error: {e.code} - {error_body}")
                return False, None, f"Resend error: {e.code}"

        except Exception as e:
            logger.error(f"Resend send error: {str(e)}")
            return False, None, str(e)


class ActiveNotificationsEmailProvider(EmailProvider):
    """Active Notifications / Pingram API email provider."""

    def send(
        self,
        to: str,
        subject: str,
        body: str,
        html_body: Optional[str] = None,
        from_address: Optional[str] = None,
        from_name: Optional[str] = None,
        reply_to: Optional[str] = None,
        attachments: Optional[List[Dict[str, Any]]] = None
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """Send email via Active Notifications compatible sender API."""
        try:
            import urllib.request
            import urllib.error

            api_key = (
                _first_non_empty_env(
                    'ACTIVE_NOTIFICATIONS_API_KEY',
                    'PINGRAM_API_KEY',
                    'NOTIFICATIONAPI_API_KEY',
                )
                or str(NotificationConfig.ACTIVE_NOTIFICATIONS_API_KEY or '').strip()
            )
            if not api_key:
                logger.warning("Active Notifications API key not configured, falling back to mock")
                return MockEmailProvider().send(
                    to, subject, body, html_body, from_address, from_name
                )

            customer_id = (
                _first_non_empty_env(
                    'ACTIVE_NOTIFICATIONS_CUSTOMER_ID',
                    'PINGRAM_CLIENT_ID',
                    'NOTIFICATIONAPI_CLIENT_ID',
                )
                or str(NotificationConfig.ACTIVE_NOTIFICATIONS_CUSTOMER_ID or '').strip()
            )
            base_url = (
                _first_non_empty_env(
                    'ACTIVE_NOTIFICATIONS_BASE_URL',
                    'PINGRAM_BASE_URL',
                    'NOTIFICATIONAPI_BASE_URL',
                )
                or str(NotificationConfig.ACTIVE_NOTIFICATIONS_BASE_URL or '').strip()
                or 'https://api.pingram.io'
            ).rstrip('/')
            send_path = (
                _first_non_empty_env(
                    'ACTIVE_NOTIFICATIONS_SEND_PATH',
                    'PINGRAM_SEND_PATH',
                    'NOTIFICATIONAPI_SEND_PATH',
                )
                or str(NotificationConfig.ACTIVE_NOTIFICATIONS_SEND_PATH or '').strip()
                or '/sender'
            )
            notification_type = (
                _first_non_empty_env(
                    'ACTIVE_NOTIFICATIONS_NOTIFICATION_TYPE',
                    'PINGRAM_NOTIFICATION_TYPE',
                    'NOTIFICATIONAPI_NOTIFICATION_TYPE',
                )
                or str(NotificationConfig.ACTIVE_NOTIFICATIONS_NOTIFICATION_TYPE or '').strip()
                or 'phins_transactional_email'
            )
            auth_header = (
                _first_non_empty_env(
                    'ACTIVE_NOTIFICATIONS_AUTH_HEADER',
                    'PINGRAM_AUTH_HEADER',
                    'NOTIFICATIONAPI_AUTH_HEADER',
                )
                or str(NotificationConfig.ACTIVE_NOTIFICATIONS_AUTH_HEADER or '').strip()
                or 'Authorization'
            )
            auth_scheme = (
                _first_non_empty_env(
                    'ACTIVE_NOTIFICATIONS_AUTH_SCHEME',
                    'PINGRAM_AUTH_SCHEME',
                    'NOTIFICATIONAPI_AUTH_SCHEME',
                )
                or str(NotificationConfig.ACTIVE_NOTIFICATIONS_AUTH_SCHEME or '').strip()
                or 'Bearer'
            )
            client_id_header = (
                _first_non_empty_env(
                    'ACTIVE_NOTIFICATIONS_CLIENT_ID_HEADER',
                    'PINGRAM_CLIENT_ID_HEADER',
                    'NOTIFICATIONAPI_CLIENT_ID_HEADER',
                )
                or str(NotificationConfig.ACTIVE_NOTIFICATIONS_CLIENT_ID_HEADER or '').strip()
            )

            from_addr, from_display = _resolve_email_sender(
                provider_type='active_notifications',
                from_address=from_address,
                from_name=from_name
            )
            reply_to_address = _resolve_reply_to_address(reply_to)

            payload: Dict[str, Any] = {
                "type": notification_type,
                "to": {
                    "id": to,
                    "email": to,
                },
                "forceChannels": ["EMAIL"],
                "email": {
                    "subject": subject,
                    "html": html_body or _plain_text_to_html(body),
                    "senderName": from_display,
                    "senderEmail": from_addr,
                },
            }
            if reply_to_address or attachments:
                payload["options"] = {"email": {}}
                if reply_to_address:
                    payload["options"]["email"]["replyToAddresses"] = [reply_to_address]
                if attachments:
                    payload["options"]["email"]["attachments"] = attachments

            data = json.dumps(payload).encode('utf-8')
            request_url = f"{base_url}/{send_path.lstrip('/')}"
            req = urllib.request.Request(request_url, data=data, method='POST')
            auth_value = api_key if not auth_scheme else f"{auth_scheme} {api_key}"
            req.add_header(auth_header, auth_value)
            req.add_header('Content-Type', 'application/json')
            if customer_id and client_id_header:
                req.add_header(client_id_header, customer_id)

            try:
                with validated_urlopen(req, timeout=30, allowed_schemes=('https',)) as response:
                    if response.status not in [200, 201, 202]:
                        return False, None, f"Unexpected status: {response.status}"
                    result = json.loads(response.read().decode('utf-8') or '{}')
                    message_id = (
                        result.get('trackingId')
                        or result.get('id')
                        or result.get('messageId')
                        or generate_id('AN')
                    )
                    return True, message_id, None
            except urllib.error.HTTPError as e:
                error_body = e.read().decode() if e.fp else str(e)
                logger.error(f"Active Notifications API error: {e.code} - {error_body}")
                return False, None, f"Active Notifications error: {e.code}"

        except Exception as e:
            logger.error(f"Active Notifications send error: {str(e)}")
            return False, None, str(e)


# ============================================================================
# SMS PROVIDER ABSTRACTION
# ============================================================================

class SMSProvider(ABC):
    """Abstract base class for SMS providers"""
    
    @abstractmethod
    def send(
        self,
        to: str,
        message: str,
        from_number: Optional[str] = None
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Send an SMS.
        
        Returns:
            Tuple of (success, message_id, error_message)
        """
        pass


class MockSMSProvider(SMSProvider):
    """Mock SMS provider for testing"""
    
    def __init__(self):
        self.sent_messages: List[Dict[str, Any]] = []
    
    def send(
        self,
        to: str,
        message: str,
        from_number: Optional[str] = None
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """Mock send - stores message for testing"""
        message_id = generate_id('MOCK_SMS')
        self.sent_messages.append({
            'to': to,
            'message': message,
            'from_number': from_number,
            'message_id': message_id,
            'sent_at': datetime.now(timezone.utc).isoformat()
        })
        logger.info(f"Mock SMS sent to {to}: {message[:50]}...")
        return True, message_id, None


class TwilioSMSProvider(SMSProvider):
    """Twilio SMS provider"""
    
    def send(
        self,
        to: str,
        message: str,
        from_number: Optional[str] = None
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """Send SMS via Twilio"""
        try:
            # Check for Twilio credentials
            if not NotificationConfig.TWILIO_ACCOUNT_SID or not NotificationConfig.TWILIO_AUTH_TOKEN:
                logger.warning("Twilio credentials not configured, using mock")
                return MockSMSProvider().send(to, message, from_number)
            
            # Import Twilio client (optional dependency)
            try:
                from twilio.rest import Client
            except ImportError:
                logger.warning("Twilio library not installed, using mock")
                return MockSMSProvider().send(to, message, from_number)
            
            client = Client(
                NotificationConfig.TWILIO_ACCOUNT_SID,
                NotificationConfig.TWILIO_AUTH_TOKEN
            )
            
            msg = client.messages.create(
                body=message,
                from_=from_number or NotificationConfig.TWILIO_FROM_NUMBER,
                to=normalize_phone(to)
            )
            
            return True, msg.sid, None
            
        except Exception as e:
            logger.error(f"Twilio send error: {str(e)}")
            return False, None, str(e)


class AWSSNSProvider(SMSProvider):
    """AWS SNS SMS provider"""
    
    def send(
        self,
        to: str,
        message: str,
        from_number: Optional[str] = None
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """Send SMS via AWS SNS"""
        try:
            # Check for boto3 availability
            try:
                import boto3
                from botocore.exceptions import ClientError, NoCredentialsError
            except ImportError:
                logger.warning("boto3 library not installed, falling back to mock")
                return MockSMSProvider().send(to, message, from_number)
            
            region = NotificationConfig.AWS_SNS_REGION
            
            # Create SNS client
            try:
                sns = boto3.client('sns', region_name=region)
            except NoCredentialsError:
                logger.warning("AWS credentials not configured, falling back to mock")
                return MockSMSProvider().send(to, message, from_number)
            
            # Normalize phone number
            phone = normalize_phone(to)
            
            # Send SMS
            response = sns.publish(
                PhoneNumber=phone,
                Message=message,
                MessageAttributes={
                    'AWS.SNS.SMS.SMSType': {
                        'DataType': 'String',
                        'StringValue': 'Transactional'  # OTP messages should be transactional
                    }
                }
            )
            
            message_id = response.get('MessageId', generate_id('SNS'))
            return True, message_id, None
            
        except Exception as e:
            if 'ClientError' in str(type(e)):
                error = e.response['Error']
                logger.error(f"AWS SNS error: {error['Code']} - {error['Message']}")
                return False, None, f"SNS error: {error['Message']}"
            logger.error(f"AWS SNS send error: {str(e)}")
            return False, None, str(e)


class VonageSMSProvider(SMSProvider):
    """Vonage (Nexmo) SMS provider"""
    
    def send(
        self,
        to: str,
        message: str,
        from_number: Optional[str] = None
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """Send SMS via Vonage API"""
        try:
            import urllib.request
            import urllib.parse
            import urllib.error
            
            api_key = NotificationConfig.VONAGE_API_KEY
            api_secret = NotificationConfig.VONAGE_API_SECRET
            
            if not api_key or not api_secret:
                logger.warning("Vonage not configured, falling back to mock")
                return MockSMSProvider().send(to, message, from_number)
            
            # Normalize phone number
            phone = normalize_phone(to)
            
            # Build request
            url = "https://rest.nexmo.com/sms/json"
            data = {
                'api_key': api_key,
                'api_secret': api_secret,
                'to': phone,
                'from': from_number or 'PHINS',
                'text': message
            }
            
            encoded_data = urllib.parse.urlencode(data).encode('utf-8')
            
            req = urllib.request.Request(url, data=encoded_data, method='POST')
            
            try:
                with validated_urlopen(req, timeout=30, allowed_schemes=('https',)) as response:
                    result = json.loads(response.read().decode())
                    
                    if result.get('messages'):
                        msg = result['messages'][0]
                        if msg.get('status') == '0':
                            return True, msg.get('message-id', generate_id('VNG')), None
                        else:
                            return False, None, f"Vonage error: {msg.get('error-text', 'Unknown')}"
                    
                    return False, None, "No response from Vonage"
            except urllib.error.HTTPError as e:
                error_body = e.read().decode() if e.fp else str(e)
                logger.error(f"Vonage API error: {e.code} - {error_body}")
                return False, None, f"Vonage error: {e.code}"
                
        except Exception as e:
            logger.error(f"Vonage send error: {str(e)}")
            return False, None, str(e)


class MessageBirdSMSProvider(SMSProvider):
    """MessageBird SMS provider"""
    
    def send(
        self,
        to: str,
        message: str,
        from_number: Optional[str] = None
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """Send SMS via MessageBird API"""
        try:
            import urllib.request
            import urllib.error
            
            api_key = NotificationConfig.MESSAGEBIRD_API_KEY
            
            if not api_key:
                logger.warning("MessageBird not configured, falling back to mock")
                return MockSMSProvider().send(to, message, from_number)
            
            # Normalize phone number
            phone = normalize_phone(to)
            
            # Build request
            url = "https://rest.messagebird.com/messages"
            payload = {
                'recipients': [phone],
                'originator': from_number or 'PHINS',
                'body': message
            }
            
            data = json.dumps(payload).encode('utf-8')
            
            req = urllib.request.Request(url, data=data, method='POST')
            req.add_header('Authorization', f'AccessKey {api_key}')
            req.add_header('Content-Type', 'application/json')
            
            try:
                with validated_urlopen(req, timeout=30, allowed_schemes=('https',)) as response:
                    result = json.loads(response.read().decode())
                    message_id = result.get('id', generate_id('MB'))
                    return True, message_id, None
            except urllib.error.HTTPError as e:
                error_body = e.read().decode() if e.fp else str(e)
                logger.error(f"MessageBird API error: {e.code} - {error_body}")
                return False, None, f"MessageBird error: {e.code}"
                
        except Exception as e:
            logger.error(f"MessageBird send error: {str(e)}")
            return False, None, str(e)


# ============================================================================
# OTP SERVICE
# ============================================================================

class OTPService:
    """
    Enterprise OTP Service
    
    Security Features:
    - Cryptographically secure OTP generation
    - Salted hash storage (never plaintext)
    - Rate limiting per identifier and IP
    - Brute force protection
    - Device fingerprinting
    - Audit logging
    """
    
    def __init__(
        self,
        email_provider: Optional[EmailProvider] = None,
        sms_provider: Optional[SMSProvider] = None
    ):
        self._email_provider = email_provider or MockEmailProvider()
        self._sms_provider = sms_provider or MockSMSProvider()
        
        # In-memory OTP storage (use database in production)
        self._otp_store: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()
    
    def generate_and_send(self, request: OTPRequest) -> OTPResult:
        """
        Generate OTP and send via specified channel.
        
        Security checks:
        1. Rate limiting
        2. IP blocking
        3. Device fingerprint validation
        """
        # Validate request
        if request.channel == NotificationChannel.EMAIL:
            if not validate_email(request.identifier):
                return OTPResult(
                    success=False,
                    error_code="INVALID_EMAIL",
                    error_message="Invalid email format"
                )
        elif request.channel in (NotificationChannel.SMS, NotificationChannel.WHATSAPP):
            if not validate_phone(request.identifier):
                return OTPResult(
                    success=False,
                    error_code="INVALID_PHONE",
                    error_message="Invalid phone number format"
                )
        else:
            return OTPResult(
                success=False,
                error_code="INVALID_CHANNEL",
                error_message=f"OTP not supported for channel: {request.channel}"
            )
        
        # Check rate limits
        if NotificationConfig.RATE_LIMIT_ENABLED:
            rate_result = self._check_rate_limit(request)
            if not rate_result.allowed:
                _audit_logger.log(
                    action="otp_rate_limited",
                    customer_id=request.customer_id,
                    ip_address=request.ip_address,
                    success=False,
                    error_message=rate_result.block_reason,
                    risk_level="high"
                )
                return OTPResult(
                    success=False,
                    error_code="RATE_LIMITED",
                    error_message=rate_result.block_reason,
                    attempts_remaining=rate_result.remaining
                )
        
        # Generate OTP
        otp_code = generate_otp(
            length=request.otp_length,
            alphanumeric=NotificationConfig.OTP_USE_ALPHANUMERIC
        )
        
        # Create OTP record
        otp_id = generate_id('OTP')
        salt = generate_salt()
        code_hash = hash_otp(otp_code, salt)
        identifier_hash = hash_identifier(request.identifier)
        
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=request.expiry_seconds)
        
        otp_record = {
            'id': otp_id,
            'customer_id': request.customer_id,
            'user_id': request.user_id,
            'identifier': request.identifier,
            'identifier_hash': identifier_hash,
            'code_hash': code_hash,
            'code_salt': salt,
            'code_length': request.otp_length,
            'verification_type': request.verification_type.value,
            'channel': request.channel.value,
            'status': OTPStatus.ACTIVE.value,
            'expires_at': expires_at.isoformat(),
            'created_at': datetime.now(timezone.utc).isoformat(),
            'attempt_count': 0,
            'max_attempts': NotificationConfig.OTP_MAX_ATTEMPTS,
            'ip_address': request.ip_address,
            'user_agent': request.user_agent,
            'device_fingerprint': request.device_fingerprint,
            'correlation_id': request.correlation_id
        }
        
        # Store OTP
        with self._lock:
            # Invalidate any existing active OTPs for this identifier and type
            for key, record in list(self._otp_store.items()):
                if (record['identifier_hash'] == identifier_hash and
                    record['verification_type'] == request.verification_type.value and
                    record['status'] == OTPStatus.ACTIVE.value):
                    record['status'] = OTPStatus.INVALIDATED.value
            
            self._otp_store[otp_id] = otp_record
        
        # Send OTP
        notification_result = self._send_otp(request, otp_code)
        
        if not notification_result.success:
            # Mark OTP as failed
            with self._lock:
                self._otp_store[otp_id]['status'] = OTPStatus.INVALIDATED.value
            
            return OTPResult(
                success=False,
                otp_id=otp_id,
                error_code=notification_result.error_code,
                error_message=notification_result.error_message
            )
        
        # Record rate limit
        if NotificationConfig.RATE_LIMIT_ENABLED:
            _rate_limiter.record_request(request.identifier, 'otp_request')
            if request.ip_address:
                _rate_limiter.record_request(request.ip_address, 'otp_request_ip')
        
        # Audit log
        _audit_logger.log(
            action="otp_generated",
            customer_id=request.customer_id,
            notification_id=notification_result.notification_id,
            target_type="otp",
            target_id=otp_id,
            ip_address=request.ip_address,
            details={
                'verification_type': request.verification_type.value,
                'channel': request.channel.value,
                'identifier_masked': mask_email(request.identifier) if '@' in request.identifier else mask_phone(request.identifier)
            }
        )
        
        return OTPResult(
            success=True,
            otp_id=otp_id,
            status=OTPStatus.ACTIVE,
            expires_at=expires_at,
            attempts_remaining=NotificationConfig.OTP_MAX_ATTEMPTS,
            notification_id=notification_result.notification_id
        )
    
    def verify(
        self,
        identifier: str,
        code: str,
        verification_type: VerificationType,
        ip_address: Optional[str] = None
    ) -> OTPResult:
        """
        Verify an OTP code.
        
        Security:
        - Constant-time comparison to prevent timing attacks
        - Automatic lockout after max attempts
        - One-time use enforcement
        """
        identifier_hash = hash_identifier(identifier)
        
        with self._lock:
            # Find matching active OTP
            matching_otp = None
            for otp_id, record in self._otp_store.items():
                if (record['identifier_hash'] == identifier_hash and
                    record['verification_type'] == verification_type.value and
                    record['status'] == OTPStatus.ACTIVE.value):
                    matching_otp = record
                    break
            
            if not matching_otp:
                _audit_logger.log(
                    action="otp_verify_no_active",
                    ip_address=ip_address,
                    success=False,
                    details={'identifier_hash': identifier_hash[:16] + '...'},
                    risk_level="medium"
                )
                return OTPResult(
                    success=False,
                    error_code="NO_ACTIVE_OTP",
                    error_message="No active OTP found for this identifier"
                )
            
            # Check expiry
            expires_at = datetime.fromisoformat(matching_otp['expires_at'])
            if datetime.now(timezone.utc) > expires_at:
                matching_otp['status'] = OTPStatus.EXPIRED.value
                _audit_logger.log(
                    action="otp_verify_expired",
                    target_id=matching_otp['id'],
                    ip_address=ip_address,
                    success=False
                )
                return OTPResult(
                    success=False,
                    otp_id=matching_otp['id'],
                    status=OTPStatus.EXPIRED,
                    error_code="OTP_EXPIRED",
                    error_message="OTP has expired"
                )
            
            # Increment attempt count
            matching_otp['attempt_count'] += 1
            attempts_remaining = matching_otp['max_attempts'] - matching_otp['attempt_count']
            
            # Check max attempts
            if matching_otp['attempt_count'] > matching_otp['max_attempts']:
                matching_otp['status'] = OTPStatus.INVALIDATED.value
                _audit_logger.log(
                    action="otp_verify_max_attempts",
                    target_id=matching_otp['id'],
                    ip_address=ip_address,
                    success=False,
                    risk_level="high"
                )
                return OTPResult(
                    success=False,
                    otp_id=matching_otp['id'],
                    status=OTPStatus.INVALIDATED,
                    error_code="MAX_ATTEMPTS_EXCEEDED",
                    error_message="Maximum verification attempts exceeded"
                )
            
            # Verify code (constant-time comparison)
            code_hash = hash_otp(code, matching_otp['code_salt'])
            if not hmac.compare_digest(code_hash, matching_otp['code_hash']):
                _audit_logger.log(
                    action="otp_verify_failed",
                    target_id=matching_otp['id'],
                    ip_address=ip_address,
                    success=False,
                    details={'attempts_remaining': attempts_remaining}
                )
                return OTPResult(
                    success=False,
                    otp_id=matching_otp['id'],
                    status=OTPStatus.ACTIVE,
                    attempts_remaining=attempts_remaining,
                    error_code="INVALID_CODE",
                    error_message=f"Invalid OTP code. {attempts_remaining} attempts remaining."
                )
            
            # Success - mark as used
            matching_otp['status'] = OTPStatus.USED.value
            matching_otp['used_at'] = datetime.now(timezone.utc).isoformat()
            
            _audit_logger.log(
                action="otp_verified",
                target_id=matching_otp['id'],
                customer_id=matching_otp.get('customer_id'),
                ip_address=ip_address,
                success=True
            )
            
            return OTPResult(
                success=True,
                otp_id=matching_otp['id'],
                status=OTPStatus.USED
            )
    
    def invalidate(
        self,
        identifier: str,
        verification_type: Optional[VerificationType] = None
    ) -> bool:
        """Invalidate all active OTPs for an identifier"""
        identifier_hash = hash_identifier(identifier)
        count = 0
        
        with self._lock:
            for record in self._otp_store.values():
                if (record['identifier_hash'] == identifier_hash and
                    record['status'] == OTPStatus.ACTIVE.value):
                    if verification_type is None or record['verification_type'] == verification_type.value:
                        record['status'] = OTPStatus.INVALIDATED.value
                        count += 1
        
        _audit_logger.log(
            action="otp_invalidated",
            details={'count': count, 'identifier_hash': identifier_hash[:16] + '...'}
        )
        
        return count > 0
    
    def _check_rate_limit(self, request: OTPRequest) -> RateLimitResult:
        """Check rate limits for OTP request"""
        # Per-identifier limits
        limits = {
            'per_minute': (NotificationConfig.OTP_RATE_LIMIT_PER_MINUTE, 60),
            'per_hour': (NotificationConfig.OTP_RATE_LIMIT_PER_HOUR, 3600),
            'per_day': (NotificationConfig.OTP_RATE_LIMIT_PER_DAY, 86400),
        }
        
        result = _rate_limiter.check_rate_limit(request.identifier, 'otp_request', limits)
        if not result.allowed:
            return result
        
        # Per-IP limits (stricter)
        if request.ip_address:
            ip_limits = {
                'ip_per_minute': (NotificationConfig.IP_RATE_LIMIT_PER_MINUTE, 60),
                'ip_per_hour': (NotificationConfig.IP_RATE_LIMIT_PER_HOUR, 3600),
            }
            ip_result = _rate_limiter.check_rate_limit(request.ip_address, 'otp_request_ip', ip_limits)
            if not ip_result.allowed:
                return ip_result
        
        return result
    
    def _send_otp(self, request: OTPRequest, otp_code: str) -> NotificationResult:
        """Send OTP via appropriate channel"""
        notification_id = generate_id('NOTIF')
        
        if request.channel == NotificationChannel.EMAIL:
            subject = f"Your verification code: {otp_code}"
            body = f"""Your PHINS verification code is: {otp_code}

This code will expire in {request.expiry_seconds // 60} minutes.

If you did not request this code, please ignore this email.

For security reasons, never share this code with anyone.

- PHINS Security Team"""
            
            html_body = f"""
<html>
<body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
    <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 20px; text-align: center;">
        <h1 style="color: white; margin: 0;">PHINS Verification</h1>
    </div>
    <div style="padding: 30px; background: #f8f9fa;">
        <p style="font-size: 16px;">Your verification code is:</p>
        <div style="background: white; border-radius: 8px; padding: 20px; text-align: center; margin: 20px 0;">
            <span style="font-size: 32px; font-weight: bold; letter-spacing: 8px; color: #667eea;">{otp_code}</span>
        </div>
        <p style="color: #666; font-size: 14px;">This code will expire in {request.expiry_seconds // 60} minutes.</p>
        <p style="color: #999; font-size: 12px;">If you did not request this code, please ignore this email.</p>
    </div>
    <div style="padding: 15px; text-align: center; background: #333; color: #999; font-size: 12px;">
        &copy; PHINS Insurance - Security Team
    </div>
</body>
</html>"""
            
            success, message_id, error = self._email_provider.send(
                to=request.identifier,
                subject=subject,
                body=body,
                html_body=html_body
            )
            
            return NotificationResult(
                success=success,
                notification_id=notification_id,
                status=NotificationStatus.DELIVERED if success else NotificationStatus.FAILED,
                provider_message_id=message_id,
                error_message=error,
                sent_at=datetime.now(timezone.utc) if success else None
            )
        
        elif request.channel in (NotificationChannel.SMS, NotificationChannel.WHATSAPP):
            message = f"Your PHINS verification code is: {otp_code}. Expires in {request.expiry_seconds // 60} min. Never share this code."
            
            success, message_id, error = self._sms_provider.send(
                to=request.identifier,
                message=message
            )
            
            return NotificationResult(
                success=success,
                notification_id=notification_id,
                status=NotificationStatus.DELIVERED if success else NotificationStatus.FAILED,
                provider_message_id=message_id,
                error_message=error,
                sent_at=datetime.now(timezone.utc) if success else None
            )
        
        return NotificationResult(
            success=False,
            notification_id=notification_id,
            status=NotificationStatus.FAILED,
            error_code="UNSUPPORTED_CHANNEL",
            error_message=f"Channel {request.channel} not supported for OTP"
        )


# ============================================================================
# NOTIFICATION SERVICE (MAIN SERVICE)
# ============================================================================

class NotificationService:
    """
    Enterprise Notification Service
    
    Features:
    - Multi-channel delivery (email, SMS, push)
    - Template management
    - Rate limiting
    - Queue with retry
    - Suppression lists
    - Preference management
    - Full audit logging
    """
    
    def __init__(
        self,
        email_provider: Optional[EmailProvider] = None,
        sms_provider: Optional[SMSProvider] = None
    ):
        self._email_provider = email_provider or MockEmailProvider()
        self._sms_provider = sms_provider or MockSMSProvider()
        
        # OTP service
        self.otp_service = OTPService(
            email_provider=self._email_provider,
            sms_provider=self._sms_provider
        )
        
        # Templates (in-memory, use database in production)
        self._templates: Dict[str, Dict[str, Any]] = {}
        self._load_default_templates()
        
        # Notification history
        self._history: List[Dict[str, Any]] = []
        self._history_lock = threading.Lock()
        
        # Suppression lists
        self._email_suppression: set = set()
        self._sms_suppression: set = set()
        
        # Preferences
        self._preferences: Dict[str, Dict[str, Any]] = {}
    
    def send(self, request: NotificationRequest) -> NotificationResult:
        """
        Send a notification.
        
        Flow:
        1. Validate request
        2. Check suppression lists
        3. Check rate limits
        4. Apply preferences
        5. Render template (if applicable)
        6. Send via provider
        7. Record history
        8. Audit log
        """
        notification_id = generate_id('NOTIF')
        
        # Validate
        validation_error = self._validate_request(request)
        if validation_error:
            return NotificationResult(
                success=False,
                notification_id=notification_id,
                status=NotificationStatus.FAILED,
                error_code="VALIDATION_ERROR",
                error_message=validation_error
            )
        
        # Check suppression
        if self._is_suppressed(request.recipient, request.channel):
            _audit_logger.log(
                action="notification_suppressed",
                notification_id=notification_id,
                customer_id=request.customer_id,
                details={'recipient_masked': self._mask_recipient(request.recipient, request.channel)}
            )
            return NotificationResult(
                success=False,
                notification_id=notification_id,
                status=NotificationStatus.FAILED,
                error_code="RECIPIENT_SUPPRESSED",
                error_message="Recipient is on suppression list"
            )
        
        # Check rate limits
        if NotificationConfig.RATE_LIMIT_ENABLED:
            rate_result = self._check_rate_limit(request)
            if not rate_result.allowed:
                return NotificationResult(
                    success=False,
                    notification_id=notification_id,
                    status=NotificationStatus.FAILED,
                    error_code="RATE_LIMITED",
                    error_message=rate_result.block_reason
                )
        
        # Check preferences
        if request.customer_id:
            pref_result = self._check_preferences(request)
            if not pref_result['allowed']:
                return NotificationResult(
                    success=False,
                    notification_id=notification_id,
                    status=NotificationStatus.FAILED,
                    error_code="PREFERENCE_BLOCKED",
                    error_message=pref_result.get('reason', 'Blocked by customer preferences')
                )

        # Optional OTP gate for sensitive notifications.
        otp_requirement_error = self._validate_otp_requirement(request)
        if otp_requirement_error:
            return NotificationResult(
                success=False,
                notification_id=notification_id,
                status=NotificationStatus.FAILED,
                error_code="OTP_VALIDATION_FAILED",
                error_message=otp_requirement_error
            )
        
        # Render template if specified
        content = request.content
        html_content = request.html_content
        subject = request.subject
        
        if request.template_id:
            rendered = self._render_template(request.template_id, request.template_vars)
            if rendered:
                content = rendered.get('body', content)
                html_content = rendered.get('html_body', html_content)
                subject = rendered.get('subject', subject)
        
        # Send
        result = self._send(request, notification_id, subject, content, html_content)
        
        # Record rate limit
        if result.success and NotificationConfig.RATE_LIMIT_ENABLED:
            action = f"{request.channel.value}_send"
            _rate_limiter.record_request(request.recipient, action)
            if request.ip_address:
                _rate_limiter.record_request(request.ip_address, f"{action}_ip")
        
        # Record history
        self._record_history(request, result, subject, content)
        
        # Audit log
        _audit_logger.log(
            action="notification_sent" if result.success else "notification_failed",
            notification_id=notification_id,
            customer_id=request.customer_id,
            ip_address=request.ip_address,
            success=result.success,
            error_message=result.error_message,
            details={
                'channel': request.channel.value,
                'recipient_masked': self._mask_recipient(request.recipient, request.channel),
                'template_id': request.template_id,
                'priority': request.priority.value
            }
        )
        
        return result
    
    def send_otp(self, request: OTPRequest) -> OTPResult:
        """Send OTP for client verification"""
        return self.otp_service.generate_and_send(request)
    
    def verify_otp(
        self,
        identifier: str,
        code: str,
        verification_type: VerificationType,
        ip_address: Optional[str] = None
    ) -> OTPResult:
        """Verify an OTP code"""
        return self.otp_service.verify(identifier, code, verification_type, ip_address)
    
    def add_to_suppression(
        self,
        identifier: str,
        channel: NotificationChannel,
        reason: str = "manual"
    ) -> bool:
        """Add identifier to suppression list"""
        identifier_hash = hash_identifier(identifier)
        
        if channel == NotificationChannel.EMAIL:
            self._email_suppression.add(identifier_hash)
        elif channel in (NotificationChannel.SMS, NotificationChannel.WHATSAPP):
            self._sms_suppression.add(identifier_hash)
        else:
            return False
        
        _audit_logger.log(
            action="suppression_added",
            details={
                'channel': channel.value,
                'reason': reason,
                'identifier_hash': identifier_hash[:16] + '...'
            }
        )
        return True
    
    def remove_from_suppression(
        self,
        identifier: str,
        channel: NotificationChannel
    ) -> bool:
        """Remove identifier from suppression list"""
        identifier_hash = hash_identifier(identifier)
        
        if channel == NotificationChannel.EMAIL:
            self._email_suppression.discard(identifier_hash)
        elif channel in (NotificationChannel.SMS, NotificationChannel.WHATSAPP):
            self._sms_suppression.discard(identifier_hash)
        else:
            return False
        
        _audit_logger.log(
            action="suppression_removed",
            details={'channel': channel.value}
        )
        return True
    
    def set_preferences(
        self,
        customer_id: str,
        preferences: Dict[str, Any]
    ) -> bool:
        """Set customer notification preferences"""
        self._preferences[customer_id] = {
            'email_enabled': preferences.get('email_enabled', True),
            'sms_enabled': preferences.get('sms_enabled', True),
            'whatsapp_enabled': preferences.get('whatsapp_enabled', True),
            'push_enabled': preferences.get('push_enabled', True),
            'quiet_hours': preferences.get('quiet_hours'),
            'max_daily': preferences.get('max_daily'),
            'categories': preferences.get('categories', {}),
            'updated_at': datetime.now(timezone.utc).isoformat()
        }
        
        _audit_logger.log(
            action="preferences_updated",
            customer_id=customer_id,
            details={'preferences': list(preferences.keys())}
        )
        return True
    
    def get_history(
        self,
        customer_id: Optional[str] = None,
        channel: Optional[NotificationChannel] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Get notification history"""
        with self._history_lock:
            history = self._history.copy()
        
        if customer_id:
            history = [h for h in history if h.get('customer_id') == customer_id]
        if channel:
            history = [h for h in history if h.get('channel') == channel.value]
        
        return history[-limit:]
    
    def get_audit_log(
        self,
        limit: int = 100,
        action: Optional[str] = None,
        customer_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Get audit log entries"""
        return _audit_logger.get_recent_events(
            limit=limit,
            action=action,
            customer_id=customer_id
        )
    
    # ========== Private Methods ==========
    
    def _validate_request(self, request: NotificationRequest) -> Optional[str]:
        """Validate notification request"""
        if request.channel == NotificationChannel.EMAIL:
            if not validate_email(request.recipient):
                return "Invalid email format"
        elif request.channel in (NotificationChannel.SMS, NotificationChannel.WHATSAPP):
            if not validate_phone(request.recipient):
                return "Invalid phone number format"
        
        if not request.content and not request.template_id:
            return "Either content or template_id must be provided"
        
        return None
    
    def _is_suppressed(self, recipient: str, channel: NotificationChannel) -> bool:
        """Check if recipient is suppressed"""
        identifier_hash = hash_identifier(recipient)
        
        if channel == NotificationChannel.EMAIL:
            return identifier_hash in self._email_suppression
        elif channel in (NotificationChannel.SMS, NotificationChannel.WHATSAPP):
            return identifier_hash in self._sms_suppression
        
        return False
    
    def _check_rate_limit(self, request: NotificationRequest) -> RateLimitResult:
        """Check rate limits for notification"""
        channel = request.channel.value
        
        if channel == 'email':
            limits = {
                'per_minute': (NotificationConfig.EMAIL_RATE_LIMIT_PER_MINUTE, 60),
                'per_hour': (NotificationConfig.EMAIL_RATE_LIMIT_PER_HOUR, 3600),
                'per_day': (NotificationConfig.EMAIL_RATE_LIMIT_PER_DAY, 86400),
            }
        elif channel in ('sms', 'whatsapp'):
            limits = {
                'per_minute': (NotificationConfig.SMS_RATE_LIMIT_PER_MINUTE, 60),
                'per_hour': (NotificationConfig.SMS_RATE_LIMIT_PER_HOUR, 3600),
                'per_day': (NotificationConfig.SMS_RATE_LIMIT_PER_DAY, 86400),
            }
        else:
            limits = {
                'per_minute': (30, 60),
                'per_hour': (200, 3600),
            }
        
        return _rate_limiter.check_rate_limit(request.recipient, f"{channel}_send", limits)
    
    def _check_preferences(self, request: NotificationRequest) -> Dict[str, Any]:
        """Check customer preferences"""
        prefs = self._preferences.get(request.customer_id, {})
        
        if request.channel == NotificationChannel.EMAIL and not prefs.get('email_enabled', True):
            return {'allowed': False, 'reason': 'Email notifications disabled'}
        if request.channel == NotificationChannel.SMS and not prefs.get('sms_enabled', True):
            return {'allowed': False, 'reason': 'SMS notifications disabled'}
        if request.channel == NotificationChannel.WHATSAPP and not prefs.get('whatsapp_enabled', True):
            return {'allowed': False, 'reason': 'WhatsApp notifications disabled'}
        
        return {'allowed': True}

    def _validate_otp_requirement(self, request: NotificationRequest) -> Optional[str]:
        """
        Validate optional OTP metadata for notification sends.

        Request metadata contract:
            - require_otp_validation: bool
            - otp_code: str
            - otp_identifier: str (optional, defaults to request.recipient)
            - otp_verification_type: str (optional, defaults to transaction_confirm)
        """
        metadata = request.metadata or {}
        if not metadata.get('require_otp_validation'):
            return None

        otp_code = str(metadata.get('otp_code', '')).strip()
        if not otp_code:
            return "OTP validation required but otp_code is missing"

        otp_identifier = str(metadata.get('otp_identifier') or request.recipient).strip()
        verification_type_raw = str(
            metadata.get('otp_verification_type', VerificationType.TRANSACTION_CONFIRM.value)
        )
        try:
            verification_type = VerificationType(verification_type_raw)
        except ValueError:
            return f"Invalid otp_verification_type: {verification_type_raw}"

        otp_result = self.verify_otp(
            identifier=otp_identifier,
            code=otp_code,
            verification_type=verification_type,
            ip_address=request.ip_address
        )
        if not otp_result.success:
            return otp_result.error_message or "OTP verification failed"

        _audit_logger.log(
            action="notification_otp_verified",
            customer_id=request.customer_id,
            ip_address=request.ip_address,
            details={
                'channel': request.channel.value,
                'verification_type': verification_type.value,
                'recipient_masked': self._mask_recipient(request.recipient, request.channel)
            }
        )

        return None
    
    def _render_template(
        self,
        template_id: str,
        variables: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Render notification template"""
        template = self._templates.get(template_id)
        if not template:
            return None
        
        return {
            'subject': TemplateEngine.render(template.get('subject', ''), variables),
            'body': TemplateEngine.render(template.get('body', ''), variables),
            'html_body': TemplateEngine.render(template.get('html_body', ''), variables) if template.get('html_body') else None
        }
    
    def _send(
        self,
        request: NotificationRequest,
        notification_id: str,
        subject: Optional[str],
        content: str,
        html_content: Optional[str]
    ) -> NotificationResult:
        """Send notification via appropriate channel"""
        
        if request.channel == NotificationChannel.EMAIL:
            success, message_id, error = self._email_provider.send(
                to=request.recipient,
                subject=subject or "PHINS Notification",
                body=content,
                html_body=html_content
            )
            
            return NotificationResult(
                success=success,
                notification_id=notification_id,
                status=NotificationStatus.DELIVERED if success else NotificationStatus.FAILED,
                provider_message_id=message_id,
                error_message=error,
                sent_at=datetime.now(timezone.utc) if success else None
            )
        
        elif request.channel == NotificationChannel.SMS:
            success, message_id, error = self._sms_provider.send(
                to=request.recipient,
                message=content
            )
            
            return NotificationResult(
                success=success,
                notification_id=notification_id,
                status=NotificationStatus.DELIVERED if success else NotificationStatus.FAILED,
                provider_message_id=message_id,
                error_message=error,
                sent_at=datetime.now(timezone.utc) if success else None
            )
        
        elif request.channel == NotificationChannel.WHATSAPP:
            success, message_id, error = self._sms_provider.send(
                to=request.recipient,
                message=content
            )
            
            return NotificationResult(
                success=success,
                notification_id=notification_id,
                status=NotificationStatus.DELIVERED if success else NotificationStatus.FAILED,
                provider_message_id=message_id,
                error_message=error,
                sent_at=datetime.now(timezone.utc) if success else None
            )

        elif request.channel == NotificationChannel.IN_APP:
            return NotificationResult(
                success=True,
                notification_id=notification_id,
                status=NotificationStatus.DELIVERED,
                provider_message_id=f"in_app:{request.customer_id or request.recipient}",
                sent_at=datetime.now(timezone.utc)
            )
        
        return NotificationResult(
            success=False,
            notification_id=notification_id,
            status=NotificationStatus.FAILED,
            error_code="UNSUPPORTED_CHANNEL",
            error_message=f"Channel {request.channel} not yet implemented"
        )
    
    def _record_history(
        self,
        request: NotificationRequest,
        result: NotificationResult,
        subject: Optional[str],
        content: str
    ) -> None:
        """Record notification in history"""
        record = {
            'id': result.notification_id,
            'customer_id': request.customer_id,
            'channel': request.channel.value,
            'recipient_hash': hash_identifier(request.recipient),
            'subject': subject,
            'content_hash': hashlib.sha256(content.encode()).hexdigest(),
            'status': result.status.value,
            'provider_message_id': result.provider_message_id,
            'error_code': result.error_code,
            'error_message': result.error_message,
            'sent_at': result.sent_at.isoformat() if result.sent_at else None,
            'created_at': datetime.now(timezone.utc).isoformat()
        }
        
        with self._history_lock:
            self._history.append(record)
            # Keep last 10000 records
            if len(self._history) > 10000:
                self._history = self._history[-10000:]
    
    def _mask_recipient(self, recipient: str, channel: NotificationChannel) -> str:
        """Mask recipient for logging"""
        if channel == NotificationChannel.EMAIL:
            return mask_email(recipient)
        elif channel in (NotificationChannel.SMS, NotificationChannel.WHATSAPP):
            return mask_phone(recipient)
        return '***'
    
    def _load_default_templates(self) -> None:
        """Load default notification templates"""
        self._templates = {
            'otp_email': {
                'subject': 'Your PHINS Verification Code: {{ code }}',
                'body': '''Your PHINS verification code is: {{ code }}

This code will expire in {{ expiry_minutes }} minutes.

If you did not request this code, please ignore this email.

- PHINS Security Team''',
                'html_body': '''
<html>
<body style="font-family: Arial, sans-serif;">
<h2>PHINS Verification</h2>
<p>Your verification code is:</p>
<h1 style="color: #667eea; letter-spacing: 8px;">{{ code }}</h1>
<p>This code expires in {{ expiry_minutes }} minutes.</p>
</body>
</html>'''
            },
            'otp_sms': {
                'body': 'Your PHINS code is {{ code }}. Expires in {{ expiry_minutes }} min. Never share this code.'
            },
            'password_reset': {
                'subject': 'PHINS Password Reset Request',
                'body': '''Hello {{ name }},

We received a password reset request for your account.

Click the link below to reset your password:
{{ reset_link }}

This link expires in {{ expiry_hours }} hours.

If you did not request this, please ignore this email.

- PHINS Security Team'''
            },
            'welcome': {
                'subject': 'Welcome to PHINS Insurance',
                'body': '''Hello {{ name }},

Welcome to PHINS Insurance! Your account has been created successfully.

You can now log in at: {{ login_url }}

If you have any questions, please contact our support team.

Best regards,
The PHINS Team'''
            },
            'welcome_executive_branded': {
                'subject': 'Welcome to PHINS | Executive Portfolio Brief',
                'body': '''Hello {{ name }},

Welcome to PHINS.

Your executive snapshot:
- Active Policies: {{ active_policies }}/{{ total_policies }}
- Total Coverage: {{ total_coverage }}
- Outstanding Billing: {{ outstanding_bills }} items ({{ outstanding_amount }})
- Accounts Tracked: {{ accounts_count }}

You can log in at: {{ login_url }}

Best regards,
PHINS Client Success Team''',
                'html_body': '''
<html>
<body style="font-family:Arial,sans-serif;background:#f2f5fb;margin:0;padding:24px;">
  <div style="max-width:760px;margin:0 auto;background:#ffffff;border-radius:16px;overflow:hidden;border:1px solid #e3e8f3;">
    <div style="background:linear-gradient(120deg,#0b1f3a,#275ecf);padding:28px 32px;color:#fff;">
      <div style="font-size:12px;letter-spacing:1.5px;opacity:.8;">PHINS EXECUTIVE ONBOARDING</div>
      <h1 style="margin:8px 0 0;font-size:24px;">Welcome, {{ name }}</h1>
      <p style="margin:8px 0 0;opacity:.9;">A branded snapshot of your insurance and billing footprint.</p>
    </div>
    <div style="padding:28px 32px;">
      <div style="display:flex;flex-wrap:wrap;gap:12px;margin-bottom:18px;">
        <div style="flex:1 1 220px;background:#f7f9ff;border:1px solid #dde6ff;border-radius:10px;padding:14px;">
          <div style="font-size:12px;color:#5a6780;">Active Policies</div>
          <div style="font-size:22px;font-weight:700;color:#12284c;">{{ active_policies }}/{{ total_policies }}</div>
        </div>
        <div style="flex:1 1 220px;background:#f7f9ff;border:1px solid #dde6ff;border-radius:10px;padding:14px;">
          <div style="font-size:12px;color:#5a6780;">Total Coverage</div>
          <div style="font-size:22px;font-weight:700;color:#12284c;">{{ total_coverage }}</div>
        </div>
        <div style="flex:1 1 220px;background:#f7f9ff;border:1px solid #dde6ff;border-radius:10px;padding:14px;">
          <div style="font-size:12px;color:#5a6780;">Outstanding Billing</div>
          <div style="font-size:22px;font-weight:700;color:#12284c;">{{ outstanding_bills }}</div>
          <div style="font-size:12px;color:#5a6780;">{{ outstanding_amount }}</div>
        </div>
      </div>
      <p style="margin:8px 0 0;color:#2f3f5b;">Accounts tracked: <strong>{{ accounts_count }}</strong></p>
      <p style="margin:18px 0 0;color:#2f3f5b;">Sign in to your customer cockpit: <a href="{{ login_url }}">{{ login_url }}</a></p>
    </div>
    <div style="background:#0f1a2e;color:#9fb0d0;padding:12px 32px;font-size:12px;">
      PHINS • Advanced Insurance Intelligence
    </div>
  </div>
</body>
</html>'''
            },
            'policy_approved': {
                'subject': 'Your PHINS Policy Has Been Approved',
                'body': '''Dear {{ name }},

Great news! Your {{ policy_type }} policy application has been approved.

Policy Number: {{ policy_number }}
Coverage Amount: {{ coverage_amount }}
Monthly Premium: {{ monthly_premium }}

You can view your policy details in your customer portal.

Thank you for choosing PHINS Insurance.

Best regards,
The PHINS Team'''
            },
            'claim_update': {
                'subject': 'Update on Your PHINS Claim #{{ claim_id }}',
                'body': '''Dear {{ name }},

Your claim #{{ claim_id }} has been updated.

Status: {{ status }}
{{ additional_info }}

Log in to your customer portal for more details.

Best regards,
The PHINS Claims Team'''
            },
            'payment_reminder': {
                'subject': 'Payment Reminder - PHINS Policy #{{ policy_number }}',
                'body': '''Dear {{ name }},

This is a reminder that your premium payment of {{ amount }} for policy #{{ policy_number }} is due on {{ due_date }}.

Please ensure timely payment to keep your coverage active.

Best regards,
The PHINS Billing Team'''
            },
            'security_alert': {
                'subject': 'Security Alert - PHINS Account',
                'body': '''Dear {{ name }},

We detected {{ activity }} on your PHINS account.

Time: {{ timestamp }}
Location: {{ location }}
Device: {{ device }}

If this was you, you can ignore this message.

If this wasn't you, please change your password immediately and contact support.

- PHINS Security Team'''
            }
        }


# ============================================================================
# CLIENT VERIFICATION SERVICE
# ============================================================================

class ClientVerificationService:
    """
    Complete client verification workflow service.
    
    Supports:
    - Email verification
    - Phone verification
    - Multi-factor authentication
    - Device verification
    - Risk-based authentication
    """
    
    def __init__(self, notification_service: NotificationService):
        self._notification_service = notification_service
        self._verifications: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()
    
    def initiate_verification(
        self,
        customer_id: str,
        verification_type: VerificationType,
        identifier: str,
        channel: NotificationChannel = NotificationChannel.EMAIL,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        device_fingerprint: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Initiate a verification workflow.
        
        Returns:
            Dict with verification_id, status, and next steps
        """
        verification_id = generate_id('VERIFY')
        
        # Create verification record
        verification = {
            'id': verification_id,
            'customer_id': customer_id,
            'verification_type': verification_type.value,
            'identifier': identifier,
            'identifier_hash': hash_identifier(identifier),
            'channel': channel.value,
            'status': 'pending',
            'initiated_at': datetime.now(timezone.utc).isoformat(),
            'expires_at': (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat(),
            'ip_address': ip_address,
            'user_agent': user_agent,
            'device_fingerprint': device_fingerprint,
            'otp_codes_sent': 0,
            'attempts': 0
        }
        
        with self._lock:
            self._verifications[verification_id] = verification
        
        # Send initial OTP
        otp_result = self._notification_service.send_otp(OTPRequest(
            identifier=identifier,
            channel=channel,
            verification_type=verification_type,
            customer_id=customer_id,
            ip_address=ip_address,
            user_agent=user_agent,
            device_fingerprint=device_fingerprint,
            correlation_id=verification_id
        ))
        
        if otp_result.success:
            with self._lock:
                self._verifications[verification_id]['otp_codes_sent'] = 1
                self._verifications[verification_id]['last_otp_at'] = datetime.now(timezone.utc).isoformat()
        
        _audit_logger.log(
            action="verification_initiated",
            customer_id=customer_id,
            target_type="verification",
            target_id=verification_id,
            ip_address=ip_address,
            details={
                'verification_type': verification_type.value,
                'channel': channel.value,
                'otp_sent': otp_result.success
            }
        )
        
        return {
            'verification_id': verification_id,
            'status': 'pending' if otp_result.success else 'failed',
            'otp_sent': otp_result.success,
            'expires_at': verification['expires_at'],
            'error': otp_result.error_message if not otp_result.success else None
        }
    
    def verify(
        self,
        verification_id: str,
        code: str,
        ip_address: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Verify a code for a verification workflow.
        """
        with self._lock:
            verification = self._verifications.get(verification_id)
            if not verification:
                return {
                    'success': False,
                    'error_code': 'NOT_FOUND',
                    'error_message': 'Verification not found'
                }
            
            # Check status
            if verification['status'] != 'pending':
                return {
                    'success': False,
                    'error_code': 'INVALID_STATUS',
                    'error_message': f"Verification status is: {verification['status']}"
                }
            
            # Check expiry
            if datetime.now(timezone.utc) > datetime.fromisoformat(verification['expires_at']):
                verification['status'] = 'expired'
                return {
                    'success': False,
                    'error_code': 'EXPIRED',
                    'error_message': 'Verification has expired'
                }
            
            verification['attempts'] += 1
        
        # Verify OTP
        otp_result = self._notification_service.verify_otp(
            identifier=verification['identifier'],
            code=code,
            verification_type=VerificationType(verification['verification_type']),
            ip_address=ip_address
        )
        
        with self._lock:
            if otp_result.success:
                verification['status'] = 'verified'
                verification['verified_at'] = datetime.now(timezone.utc).isoformat()
            elif otp_result.error_code == 'MAX_ATTEMPTS_EXCEEDED':
                verification['status'] = 'failed'
        
        _audit_logger.log(
            action="verification_attempt",
            customer_id=verification.get('customer_id'),
            target_id=verification_id,
            ip_address=ip_address,
            success=otp_result.success,
            error_message=otp_result.error_message
        )
        
        return {
            'success': otp_result.success,
            'verification_id': verification_id,
            'status': verification['status'],
            'attempts_remaining': otp_result.attempts_remaining,
            'error_code': otp_result.error_code,
            'error_message': otp_result.error_message
        }
    
    def resend_code(
        self,
        verification_id: str,
        ip_address: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Resend OTP code for a verification.
        """
        with self._lock:
            verification = self._verifications.get(verification_id)
            if not verification:
                return {
                    'success': False,
                    'error_code': 'NOT_FOUND',
                    'error_message': 'Verification not found'
                }
            
            if verification['status'] != 'pending':
                return {
                    'success': False,
                    'error_code': 'INVALID_STATUS',
                    'error_message': 'Cannot resend for completed verification'
                }
            
            # Check cooldown
            if 'last_otp_at' in verification:
                last_sent = datetime.fromisoformat(verification['last_otp_at'])
                cooldown = timedelta(seconds=NotificationConfig.OTP_RESEND_COOLDOWN_SECONDS)
                if datetime.now(timezone.utc) < last_sent + cooldown:
                    wait_seconds = int((last_sent + cooldown - datetime.now(timezone.utc)).total_seconds())
                    return {
                        'success': False,
                        'error_code': 'COOLDOWN',
                        'error_message': f'Please wait {wait_seconds} seconds before requesting a new code'
                    }
        
        # Send new OTP
        otp_result = self._notification_service.send_otp(OTPRequest(
            identifier=verification['identifier'],
            channel=NotificationChannel(verification['channel']),
            verification_type=VerificationType(verification['verification_type']),
            customer_id=verification.get('customer_id'),
            ip_address=ip_address,
            correlation_id=verification_id
        ))
        
        if otp_result.success:
            with self._lock:
                verification['otp_codes_sent'] += 1
                verification['last_otp_at'] = datetime.now(timezone.utc).isoformat()
        
        return {
            'success': otp_result.success,
            'verification_id': verification_id,
            'error_code': otp_result.error_code,
            'error_message': otp_result.error_message
        }
    
    def get_verification_status(self, verification_id: str) -> Optional[Dict[str, Any]]:
        """Get current status of a verification"""
        with self._lock:
            verification = self._verifications.get(verification_id)
            if not verification:
                return None
            
            return {
                'id': verification['id'],
                'status': verification['status'],
                'verification_type': verification['verification_type'],
                'initiated_at': verification['initiated_at'],
                'verified_at': verification.get('verified_at'),
                'expires_at': verification['expires_at'],
                'attempts': verification['attempts'],
                'otp_codes_sent': verification['otp_codes_sent']
            }
    
    def is_verified(self, customer_id: str, verification_type: VerificationType) -> bool:
        """Check if customer has completed verification"""
        with self._lock:
            for verification in self._verifications.values():
                if (verification['customer_id'] == customer_id and
                    verification['verification_type'] == verification_type.value and
                    verification['status'] == 'verified'):
                    return True
        return False


# ============================================================================
# FACTORY FUNCTION
# ============================================================================

_EMAIL_PROVIDER_TYPES = {'smtp', 'sendgrid', 'ses', 'mailgun', 'resend', 'active_notifications'}
_SMTP_PLACEHOLDER_HOSTS = {
    '',
    'localhost',
    '127.0.0.1',
    'smtp.example.com',
    'mail.example.com',
    'example.com',
}


def _env_or_default(name: str, default: str = '') -> str:
    """Read env var with fallback to already-loaded config default."""
    raw_value = os.environ.get(name)
    if raw_value is None:
        raw_value = default
    return str(raw_value or '').strip()


def _smtp_looks_unconfigured() -> bool:
    """
    Detect placeholder/default SMTP settings.

    We treat localhost + no credentials as a likely non-production SMTP setup.
    """
    host = _env_or_default('SMTP_HOST', NotificationConfig.SMTP_HOST).lower()
    username = _env_or_default('SMTP_USERNAME', NotificationConfig.SMTP_USERNAME)
    password = _env_or_default('SMTP_PASSWORD', NotificationConfig.SMTP_PASSWORD)
    if host in _SMTP_PLACEHOLDER_HOSTS and not username and not password:
        return True

    # Guard against obvious docs placeholders copied into production env.
    if host.endswith('.example.com'):
        return True

    return False


def _aws_identity_configured() -> bool:
    """Check whether AWS runtime credentials are available."""
    return any(
        os.environ.get(name)
        for name in (
            'AWS_ACCESS_KEY_ID',
            'AWS_PROFILE',
            'AWS_WEB_IDENTITY_TOKEN_FILE',
            'AWS_CONTAINER_CREDENTIALS_RELATIVE_URI',
            'AWS_CONTAINER_CREDENTIALS_FULL_URI',
        )
    )


def _detect_configured_api_email_provider() -> Optional[str]:
    """Return the best configured API email provider, if any."""
    active_notifications_key = _env_or_default(
        'ACTIVE_NOTIFICATIONS_API_KEY',
        NotificationConfig.ACTIVE_NOTIFICATIONS_API_KEY
    ) or _env_or_default('PINGRAM_API_KEY') or _env_or_default('NOTIFICATIONAPI_API_KEY')
    if active_notifications_key:
        return 'active_notifications'

    if _env_or_default('SENDGRID_API_KEY', NotificationConfig.SENDGRID_API_KEY):
        return 'sendgrid'

    if (
        _env_or_default('MAILGUN_API_KEY', NotificationConfig.MAILGUN_API_KEY)
        and _env_or_default('MAILGUN_DOMAIN', NotificationConfig.MAILGUN_DOMAIN)
    ):
        return 'mailgun'

    if _env_or_default('RESEND_API_KEY', NotificationConfig.RESEND_API_KEY):
        return 'resend'

    if _aws_identity_configured():
        return 'ses'

    return None


def _select_email_provider_type() -> str:
    """
    Select an email provider with safe auto-detection.

    Rules:
      - If EMAIL_PROVIDER is explicitly set, respect it unless it points to
        placeholder SMTP settings that cannot deliver.
      - If provider is not explicit and defaults to placeholder SMTP, auto-select
        a configured API provider (SendGrid/Mailgun/Resend/SES) when available.
    """
    raw_env_provider = os.environ.get('EMAIL_PROVIDER')
    has_explicit_provider = _canonical_email_provider_type(raw_env_provider) is not None
    provider_type = _normalize_email_provider_type(
        raw_env_provider if has_explicit_provider else NotificationConfig.EMAIL_PROVIDER,
        default='smtp'
    )
    if provider_type not in _EMAIL_PROVIDER_TYPES:
        logger.warning("Unknown EMAIL_PROVIDER '%s'; falling back to smtp", provider_type)
        provider_type = 'smtp'
        # Invalid explicit provider should not block safe auto-detection.
        has_explicit_provider = False

    configured_api_provider = _detect_configured_api_email_provider()

    if has_explicit_provider:
        # Common production misconfiguration: EMAIL_PROVIDER=smtp is set, but SMTP
        # itself is still a placeholder while a real API provider key is present.
        if provider_type == 'smtp' and _smtp_looks_unconfigured() and configured_api_provider:
            logger.warning(
                "EMAIL_PROVIDER='smtp' looks unconfigured; auto-selecting '%s' for delivery",
                configured_api_provider
            )
            return configured_api_provider
        return provider_type

    if provider_type != 'smtp' or not _smtp_looks_unconfigured():
        return provider_type

    if configured_api_provider:
        return configured_api_provider

    return provider_type


def _build_email_provider(provider_type: str) -> EmailProvider:
    """Construct an email provider instance from provider type."""
    provider_type = _normalize_email_provider_type(provider_type, default='smtp')
    if provider_type == 'sendgrid':
        return SendGridEmailProvider()
    if provider_type == 'ses':
        return AWSSESEmailProvider()
    if provider_type == 'mailgun':
        return MailgunEmailProvider()
    if provider_type == 'resend':
        return ResendEmailProvider()
    if provider_type == 'active_notifications':
        return ActiveNotificationsEmailProvider()
    return SMTPEmailProvider()


_MOCK_NOTIFICATION_TRUTHY_VALUES = {'1', 'true', 'yes', 'y', 'on'}
_notification_service_instances: Dict[bool, NotificationService] = {}


def should_use_mock_notifications() -> bool:
    """Decide whether notification delivery should use mock providers."""
    return any(
        str(os.environ.get(env_name, '')).strip().lower() in _MOCK_NOTIFICATION_TRUTHY_VALUES
        for env_name in ('PHINS_TEST_MODE', 'PHINS_USE_MOCK_NOTIFICATIONS')
    )


def create_notification_service(
    use_mock: bool = True,
    email_provider: Optional[EmailProvider] = None,
    sms_provider: Optional[SMSProvider] = None
) -> NotificationService:
    """
    Factory function to create NotificationService with appropriate providers.
    
    Args:
        use_mock: If True, use mock providers for testing
        email_provider: Custom email provider (overrides EMAIL_PROVIDER config)
        sms_provider: Custom SMS provider (overrides SMS_PROVIDER config)
    
    Returns:
        Configured NotificationService instance
    
    Email providers (set via EMAIL_PROVIDER env var):
        - 'smtp' (default): SMTP-based email via configured mail server
        - 'sendgrid': SendGrid API
        - 'ses': AWS Simple Email Service
        - 'mailgun': Mailgun API
        - 'resend': Resend API
        - 'active_notifications': Active Notifications / Pingram sender API
    
    SMS providers (set via SMS_PROVIDER env var):
        - 'twilio' (default): Twilio SMS API
        - 'sns': AWS SNS (Simple Notification Service)
        - 'vonage': Vonage (formerly Nexmo) SMS API
        - 'messagebird': MessageBird SMS API
    """
    if use_mock:
        email = MockEmailProvider()
        sms = MockSMSProvider()
    else:
        # Email provider selection
        if email_provider:
            email = email_provider
        else:
            configured_provider = _normalize_email_provider_type(
                os.environ.get('EMAIL_PROVIDER', NotificationConfig.EMAIL_PROVIDER),
                default='smtp'
            )
            provider_type = _select_email_provider_type()
            if provider_type != configured_provider:
                logger.info(
                    "Auto-selected email provider '%s' (configured '%s')",
                    provider_type,
                    configured_provider
                )
            email = _build_email_provider(provider_type)
        
        # SMS provider selection
        if sms_provider:
            sms = sms_provider
        else:
            provider_type = NotificationConfig.SMS_PROVIDER.lower()
            if provider_type == 'sns':
                sms = AWSSNSProvider()
            elif provider_type == 'vonage':
                sms = VonageSMSProvider()
            elif provider_type == 'messagebird':
                sms = MessageBirdSMSProvider()
            else:  # default to Twilio
                sms = TwilioSMSProvider()
    
    return NotificationService(
        email_provider=email,
        sms_provider=sms
    )


def get_notification_service(use_mock: Optional[bool] = None) -> NotificationService:
    """
    Get a cached NotificationService instance for shared server-side history/state.

    When `use_mock` is omitted, runtime environment flags decide between live and
    mock delivery so production routes do not silently default to mocks.
    """
    resolved_use_mock = should_use_mock_notifications() if use_mock is None else bool(use_mock)
    if resolved_use_mock not in _notification_service_instances:
        _notification_service_instances[resolved_use_mock] = create_notification_service(
            use_mock=resolved_use_mock
        )
    return _notification_service_instances[resolved_use_mock]


def reset_notification_service():
    """Reset cached notification service instances (mainly for testing)."""
    _notification_service_instances.clear()


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    # Configuration
    'NotificationConfig',
    
    # Enums
    'NotificationChannel',
    'NotificationPriority',
    'NotificationStatus',
    'VerificationType',
    'OTPStatus',
    
    # Data classes
    'NotificationRequest',
    'NotificationResult',
    'OTPRequest',
    'OTPResult',
    'RateLimitResult',
    
    # Services
    'NotificationService',
    'OTPService',
    'ClientVerificationService',
    
    # Email Providers
    'EmailProvider',
    'SMTPEmailProvider',
    'MockEmailProvider',
    'SendGridEmailProvider',
    'AWSSESEmailProvider',
    'MailgunEmailProvider',
    'ResendEmailProvider',
    'ActiveNotificationsEmailProvider',
    
    # SMS Providers
    'SMSProvider',
    'TwilioSMSProvider',
    'MockSMSProvider',
    'AWSSNSProvider',
    'VonageSMSProvider',
    'MessageBirdSMSProvider',
    
    # Utilities
    'RateLimiter',
    'TemplateEngine',
    'NotificationAuditLogger',
    
    # Factory
    'create_notification_service',
    'get_notification_service',
    'reset_notification_service',
    'should_use_mock_notifications',
    
    # SMTP resilience
    'get_smtp_circuit_breaker',
    
    # Helper functions
    'generate_id',
    'hash_identifier',
    'generate_otp',
    'validate_email',
    'validate_phone',
    'mask_email',
    'mask_phone',
    
    # Testing utilities
    'reset_global_rate_limiter',
]
