"""
PHINS OTP Security Service
Enhanced OTP validation with CAPTCHA support for login/registration security

Security Features:
- Stricter OTP validation for new customers and logins
- CAPTCHA integration (hCaptcha/reCAPTCHA support)
- Device fingerprinting for trusted devices
- Risk-based authentication
- Brute force protection
- IP-based rate limiting
- Audit logging
"""

from __future__ import annotations

import os
import re
import hmac
import secrets
import hashlib
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
import threading
import uuid
import json

from security.network import validated_urlopen

logger = logging.getLogger('phins.otp_security')
PHINS_TEST_MODE = str(os.environ.get('PHINS_TEST_MODE', '')).lower() in ('1', 'true', 'yes', 'y')


# ============================================================================
# CONFIGURATION
# ============================================================================

class OTPSecurityConfig:
    """Configuration for OTP Security Service"""
    
    # OTP Settings
    OTP_LENGTH = int(os.environ.get('OTP_LENGTH', '6'))
    OTP_EXPIRY_SECONDS = int(os.environ.get('OTP_EXPIRY_SECONDS', '300'))  # 5 minutes
    OTP_MAX_ATTEMPTS = int(os.environ.get('OTP_MAX_ATTEMPTS', '5'))
    OTP_RESEND_COOLDOWN_SECONDS = int(os.environ.get('OTP_RESEND_COOLDOWN_SECONDS', '60'))
    
    # CAPTCHA Settings
    CAPTCHA_ENABLED = os.environ.get('CAPTCHA_ENABLED', 'true').lower() == 'true'
    CAPTCHA_TYPE = os.environ.get('CAPTCHA_TYPE', 'simple')  # simple, hcaptcha, recaptcha
    HCAPTCHA_SECRET = os.environ.get('HCAPTCHA_SECRET', '')
    HCAPTCHA_SITE_KEY = os.environ.get('HCAPTCHA_SITE_KEY', '')
    RECAPTCHA_SECRET = os.environ.get('RECAPTCHA_SECRET', '')
    RECAPTCHA_SITE_KEY = os.environ.get('RECAPTCHA_SITE_KEY', '')
    
    # Require CAPTCHA for these actions
    CAPTCHA_REQUIRED_ACTIONS = ['register', 'login', 'password_reset', 'otp_request']
    
    # Risk-based OTP triggers
    OTP_REQUIRED_FOR_NEW_DEVICE = os.environ.get('OTP_REQUIRED_NEW_DEVICE', 'true').lower() == 'true'
    OTP_REQUIRED_FOR_NEW_LOCATION = os.environ.get('OTP_REQUIRED_NEW_LOCATION', 'true').lower() == 'true'
    OTP_REQUIRED_FOR_REGISTRATION = os.environ.get('OTP_REQUIRED_REGISTRATION', 'true').lower() == 'true'
    
    # Device Trust Settings
    DEVICE_TRUST_DURATION_DAYS = int(os.environ.get('DEVICE_TRUST_DURATION_DAYS', '30'))
    MAX_TRUSTED_DEVICES = int(os.environ.get('MAX_TRUSTED_DEVICES', '5'))
    
    # Rate Limiting
    LOGIN_ATTEMPTS_PER_IP_HOUR = int(os.environ.get('LOGIN_ATTEMPTS_PER_IP_HOUR', '20'))
    OTP_REQUESTS_PER_IP_HOUR = int(
        os.environ.get('OTP_REQUESTS_PER_IP_HOUR', '2000' if PHINS_TEST_MODE else '10')
    )
    CAPTCHA_FAILURES_BEFORE_BLOCK = int(os.environ.get('CAPTCHA_FAILURES_BEFORE_BLOCK', '5'))
    
    # Block Duration
    IP_BLOCK_DURATION_MINUTES = int(os.environ.get('IP_BLOCK_DURATION_MINUTES', '30'))


# ============================================================================
# ENUMS
# ============================================================================

class OTPPurpose(str, Enum):
    """Purpose of OTP verification"""
    LOGIN = "login"
    REGISTRATION = "registration"
    PASSWORD_RESET = "password_reset"
    EMAIL_VERIFICATION = "email_verification"
    PHONE_VERIFICATION = "phone_verification"
    TRANSACTION = "transaction"
    DEVICE_VERIFICATION = "device_verification"


class ChallengeType(str, Enum):
    """Type of CAPTCHA challenge"""
    SIMPLE = "simple"  # Simple math/text challenge
    HCAPTCHA = "hcaptcha"
    RECAPTCHA = "recaptcha"


class RiskLevel(str, Enum):
    """Risk level assessment"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class VerificationStatus(str, Enum):
    """Verification status"""
    PENDING = "pending"
    VERIFIED = "verified"
    EXPIRED = "expired"
    FAILED = "failed"
    BLOCKED = "blocked"


# ============================================================================
# DATA CLASSES
# ============================================================================

@dataclass
class CaptchaChallenge:
    """CAPTCHA challenge data"""
    challenge_id: str
    challenge_type: str
    challenge_question: Optional[str] = None
    expected_answer: Optional[str] = None  # For simple CAPTCHA
    site_key: Optional[str] = None  # For hCaptcha/reCAPTCHA
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc) + timedelta(minutes=5))
    verified: bool = False
    
    def to_client_dict(self) -> Dict[str, Any]:
        """Return client-safe data (no answer)"""
        return {
            'challenge_id': self.challenge_id,
            'challenge_type': self.challenge_type,
            'challenge_question': self.challenge_question,
            'site_key': self.site_key,
            'expires_at': self.expires_at.isoformat()
        }


@dataclass
class OTPVerification:
    """OTP verification record"""
    verification_id: str
    user_type: str  # customer, supplier, staff
    user_id: str
    email: str
    purpose: OTPPurpose
    otp_hash: str
    otp_salt: str
    status: VerificationStatus = VerificationStatus.PENDING
    attempts: int = 0
    max_attempts: int = 5
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    device_fingerprint: Optional[str] = None
    is_new_device: bool = False
    is_new_location: bool = False
    risk_score: float = 0.0
    # Delivery channel for the OTP. 'email' (default), 'sms', or 'both'.
    # When 'sms' or 'both' is requested, the phone field carries the
    # destination number in E.164 format.
    delivery_channel: str = 'email'
    phone: Optional[str] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc) + timedelta(minutes=5))
    verified_at: Optional[datetime] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'verification_id': self.verification_id,
            'user_type': self.user_type,
            'user_id': self.user_id,
            'email': self.email,
            'purpose': self.purpose.value,
            'status': self.status.value,
            'attempts': self.attempts,
            'max_attempts': self.max_attempts,
            'is_new_device': self.is_new_device,
            'is_new_location': self.is_new_location,
            'risk_score': self.risk_score,
            'delivery_channel': self.delivery_channel,
            'phone': self.phone,
            'created_at': self.created_at.isoformat(),
            'expires_at': self.expires_at.isoformat(),
            'verified_at': self.verified_at.isoformat() if self.verified_at else None
        }


@dataclass
class TrustedDevice:
    """Trusted device record"""
    device_id: str
    user_type: str
    user_id: str
    device_fingerprint: str
    device_name: Optional[str] = None
    user_agent: Optional[str] = None
    is_active: bool = True
    trust_level: int = 1
    first_seen: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_seen: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    trusted_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    revoked_at: Optional[datetime] = None


@dataclass
class SecurityResult:
    """Result of security operations"""
    success: bool
    message: Optional[str] = None
    error_code: Optional[str] = None
    data: Optional[Dict[str, Any]] = None
    requires_otp: bool = False
    requires_captcha: bool = False
    verification_id: Optional[str] = None
    challenge: Optional[CaptchaChallenge] = None
    
    def to_dict(self) -> Dict[str, Any]:
        result = {
            'success': self.success,
            'message': self.message,
            'error_code': self.error_code,
            'data': self.data,
            'requires_otp': self.requires_otp,
            'requires_captcha': self.requires_captcha,
            'verification_id': self.verification_id
        }
        if self.challenge:
            result['challenge'] = self.challenge.to_client_dict()
        return result


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def generate_id(prefix: str = "") -> str:
    """Generate a unique ID"""
    unique_part = uuid.uuid4().hex[:16]
    timestamp = datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')
    if prefix:
        return f"{prefix}_{timestamp}_{unique_part}"
    return f"{timestamp}_{unique_part}"


def generate_otp(length: int = 6) -> str:
    """Generate a cryptographically secure OTP"""
    return ''.join(str(secrets.randbelow(10)) for _ in range(length))


def hash_otp(code: str, salt: str) -> str:
    """Hash OTP code with salt"""
    return hashlib.pbkdf2_hmac(
        'sha256',
        code.encode('utf-8'),
        salt.encode('utf-8'),
        100000
    ).hex()


def generate_salt() -> str:
    """Generate cryptographically secure salt"""
    return secrets.token_hex(32)


def generate_device_fingerprint(
    user_agent: str,
    ip_address: str,
    additional_data: str = ""
) -> str:
    """Generate device fingerprint from available data"""
    data = f"{user_agent}:{ip_address}:{additional_data}"
    return hashlib.sha256(data.encode('utf-8')).hexdigest()


def mask_email(email: str) -> str:
    """Mask email for display"""
    if '@' not in email:
        return '***'
    local, domain = email.split('@', 1)
    if len(local) <= 2:
        masked = local[0] + '*' * max(len(local) - 1, 1)
    else:
        masked = local[0] + '*' * (len(local) - 2) + local[-1]
    return f"{masked}@{domain}"


def _mask_phone(phone: Optional[str]) -> str:
    """Mask phone for display (keeps country code + last two digits)."""
    if not phone:
        return '***'
    digits = re.sub(r'\D', '', phone)
    if len(digits) <= 4:
        return '***'
    plus = '+' if str(phone).strip().startswith('+') else ''
    return f"{plus}{digits[:2]}{'*' * (len(digits) - 4)}{digits[-2:]}"


# ============================================================================
# SIMPLE CAPTCHA GENERATOR
# ============================================================================

class SimpleCaptchaGenerator:
    """CAPTCHA generator with multi-step math and contextual challenges"""
    
    OPERATIONS = ['+', '-', 'x']
    TEMPLATES = [
        "What is {} {} {}?",
        "Calculate: {} {} {}",
        "Solve: {} {} {} = ?",
    ]
    
    TEXT_QUESTIONS = [
        ("What color is the sky on a clear day?", ["blue", "azure"]),
        ("What comes after 'one, two, ...'?", ["three", "3"]),
        ("Enter the current year:", [str(datetime.now().year)]),
        ("How many days are in a week?", ["seven", "7"]),
        ("What is the capital of France?", ["paris"]),
        ("How many months are in a year?", ["twelve", "12"]),
        ("What planet do we live on?", ["earth"]),
    ]
    
    @classmethod
    def generate(cls) -> Tuple[str, str]:
        """Generate a CAPTCHA challenge, biased toward math"""
        roll = secrets.randbelow(100)
        if roll < 50:
            return cls._generate_math_question()
        elif roll < 80:
            return cls._generate_two_step_math()
        else:
            return cls._generate_text_question()
    
    @classmethod
    def _generate_math_question(cls) -> Tuple[str, str]:
        """Generate a single-operation math CAPTCHA with wider ranges"""
        a = secrets.randbelow(40) + 5   # 5-44
        b = secrets.randbelow(30) + 3   # 3-32
        op = secrets.choice(cls.OPERATIONS)
        
        if op == '-' and b > a:
            a, b = b, a
        if op == 'x':
            a = secrets.randbelow(9) + 2   # 2-10
            b = secrets.randbelow(9) + 2   # 2-10

        template = secrets.choice(cls.TEMPLATES)
        if op == '+':
            answer = a + b
        elif op == '-':
            answer = a - b
        else:
            answer = a * b
        
        return template.format(a, op, b), str(answer)
    
    @classmethod
    def _generate_two_step_math(cls) -> Tuple[str, str]:
        """Generate a two-operation math challenge, e.g. (a + b) x c"""
        a = secrets.randbelow(10) + 2
        b = secrets.randbelow(10) + 2
        c = secrets.randbelow(5) + 2
        op1 = secrets.choice(['+', '-'])
        if op1 == '-' and b > a:
            a, b = b, a
        step1 = a + b if op1 == '+' else a - b
        answer = step1 * c
        question = f"({a} {op1} {b}) x {c} = ?"
        return question, str(answer)
    
    @classmethod
    def _generate_text_question(cls) -> Tuple[str, str]:
        """Generate a text CAPTCHA"""
        question, answers = secrets.choice(cls.TEXT_QUESTIONS)
        return question, answers[0]
    
    @classmethod
    def verify(cls, expected: str, provided: str) -> bool:
        """Verify CAPTCHA answer with timing-safe comparison for numeric answers"""
        expected_clean = expected.lower().strip()
        provided_clean = provided.lower().strip()
        
        if hmac.compare_digest(expected_clean, provided_clean):
            return True
        
        for _question, answers in cls.TEXT_QUESTIONS:
            normalized_answers = [a.lower() for a in answers]
            if expected_clean == normalized_answers[0]:
                return provided_clean in normalized_answers
        
        return False


# ============================================================================
# OTP SECURITY SERVICE
# ============================================================================

class OTPSecurityService:
    """
    Enhanced OTP Security Service
    
    Provides stricter OTP validation with CAPTCHA support for:
    - New customer registration
    - Login from new devices/locations
    - Password reset
    - Sensitive transactions
    """
    
    def __init__(self):
        self._lock = threading.Lock()
        
        # In-memory storage (use database in production)
        self._challenges: Dict[str, CaptchaChallenge] = {}
        self._verifications: Dict[str, OTPVerification] = {}
        self._consumed_verifications: set[str] = set()
        self._trusted_devices: Dict[str, TrustedDevice] = {}
        self._rate_limits: Dict[str, List[datetime]] = {}
        self._blocked_ips: Dict[str, datetime] = {}
        self._audit_log: List[Dict[str, Any]] = []
    
    # ========== CAPTCHA ==========
    
    def _cleanup_expired_challenges(self) -> None:
        """Remove expired challenges to prevent memory buildup. Caller must hold _lock."""
        now = datetime.now(timezone.utc)
        expired = [
            cid for cid, ch in self._challenges.items()
            if now > ch.expires_at
        ]
        for cid in expired:
            del self._challenges[cid]

    def create_captcha_challenge(
        self,
        action: str,
        ip_address: Optional[str] = None,
        session_id: Optional[str] = None
    ) -> SecurityResult:
        """Create a CAPTCHA challenge"""
        if ip_address and self._is_ip_blocked(ip_address):
            return SecurityResult(
                success=False,
                error_code="IP_BLOCKED",
                message="Too many failed attempts. Please try again later."
            )
        
        challenge_id = generate_id("CAPTCHA")
        challenge_type = OTPSecurityConfig.CAPTCHA_TYPE
        
        if challenge_type == 'simple':
            question, answer = SimpleCaptchaGenerator.generate()
            challenge = CaptchaChallenge(
                challenge_id=challenge_id,
                challenge_type='simple',
                challenge_question=question,
                expected_answer=answer
            )
        elif challenge_type == 'hcaptcha':
            challenge = CaptchaChallenge(
                challenge_id=challenge_id,
                challenge_type='hcaptcha',
                site_key=OTPSecurityConfig.HCAPTCHA_SITE_KEY
            )
        elif challenge_type == 'recaptcha':
            challenge = CaptchaChallenge(
                challenge_id=challenge_id,
                challenge_type='recaptcha',
                site_key=OTPSecurityConfig.RECAPTCHA_SITE_KEY
            )
        else:
            # Default to simple
            question, answer = SimpleCaptchaGenerator.generate()
            challenge = CaptchaChallenge(
                challenge_id=challenge_id,
                challenge_type='simple',
                challenge_question=question,
                expected_answer=answer
            )
        
        with self._lock:
            if len(self._challenges) > 100:
                self._cleanup_expired_challenges()
            self._challenges[challenge_id] = challenge
        
        self._log_audit(
            action="captcha_created",
            ip_address=ip_address,
            details={"challenge_id": challenge_id, "type": challenge_type, "purpose": action}
        )
        
        return SecurityResult(
            success=True,
            challenge=challenge,
            data={"challenge_id": challenge_id}
        )
    
    def verify_captcha(
        self,
        challenge_id: str,
        response: str,
        ip_address: Optional[str] = None
    ) -> SecurityResult:
        """Verify a CAPTCHA response"""
        with self._lock:
            challenge = self._challenges.get(challenge_id)
        
        if not challenge:
            return SecurityResult(
                success=False,
                error_code="INVALID_CHALLENGE",
                message="Invalid or expired CAPTCHA challenge"
            )
        
        # Check expiry
        if datetime.now(timezone.utc) > challenge.expires_at:
            return SecurityResult(
                success=False,
                error_code="CHALLENGE_EXPIRED",
                message="CAPTCHA challenge has expired"
            )
        
        # Already verified
        if challenge.verified:
            return SecurityResult(
                success=True,
                message="Already verified"
            )
        
        verified = False
        
        if challenge.challenge_type == 'simple':
            verified = SimpleCaptchaGenerator.verify(
                challenge.expected_answer,
                response
            )
        elif challenge.challenge_type == 'hcaptcha':
            verified = self._verify_hcaptcha(response)
        elif challenge.challenge_type == 'recaptcha':
            verified = self._verify_recaptcha(response)
        
        if verified:
            challenge.verified = True
            self._log_audit(
                action="captcha_verified",
                ip_address=ip_address,
                details={"challenge_id": challenge_id},
                success=True
            )
            return SecurityResult(
                success=True,
                message="CAPTCHA verified successfully"
            )
        else:
            # Record failure for rate limiting
            if ip_address:
                self._record_captcha_failure(ip_address)
            
            self._log_audit(
                action="captcha_failed",
                ip_address=ip_address,
                details={"challenge_id": challenge_id},
                success=False
            )
            return SecurityResult(
                success=False,
                error_code="CAPTCHA_FAILED",
                message="CAPTCHA verification failed. Please try again."
            )
    
    def _verify_hcaptcha(self, token: str) -> bool:
        """Verify hCaptcha token"""
        if not OTPSecurityConfig.HCAPTCHA_SECRET:
            logger.warning("hCaptcha secret not configured, accepting token")
            return True
        
        try:
            import urllib.request
            import urllib.parse
            
            data = urllib.parse.urlencode({
                'secret': OTPSecurityConfig.HCAPTCHA_SECRET,
                'response': token
            }).encode()
            
            req = urllib.request.Request(
                'https://hcaptcha.com/siteverify',
                data=data,
                method='POST'
            )
            
            with validated_urlopen(req, timeout=5, allowed_schemes=('https',)) as resp:
                result = json.loads(resp.read().decode())
                return result.get('success', False)
        except Exception as e:
            logger.error(f"hCaptcha verification error: {e}")
            return False
    
    def _verify_recaptcha(self, token: str) -> bool:
        """Verify reCAPTCHA token"""
        if not OTPSecurityConfig.RECAPTCHA_SECRET:
            logger.warning("reCAPTCHA secret not configured, accepting token")
            return True
        
        try:
            import urllib.request
            import urllib.parse
            
            data = urllib.parse.urlencode({
                'secret': OTPSecurityConfig.RECAPTCHA_SECRET,
                'response': token
            }).encode()
            
            req = urllib.request.Request(
                'https://www.google.com/recaptcha/api/siteverify',
                data=data,
                method='POST'
            )
            
            with validated_urlopen(req, timeout=5, allowed_schemes=('https',)) as resp:
                result = json.loads(resp.read().decode())
                return result.get('success', False)
        except Exception as e:
            logger.error(f"reCAPTCHA verification error: {e}")
            return False
    
    def _record_captcha_failure(self, ip_address: str) -> None:
        """Record CAPTCHA failure for rate limiting"""
        key = f"captcha_fail:{ip_address}"
        with self._lock:
            if key not in self._rate_limits:
                self._rate_limits[key] = []
            self._rate_limits[key].append(datetime.now(timezone.utc))
            
            # Check if should block
            recent_failures = [
                t for t in self._rate_limits[key]
                if datetime.now(timezone.utc) - t < timedelta(hours=1)
            ]
            
            if len(recent_failures) >= OTPSecurityConfig.CAPTCHA_FAILURES_BEFORE_BLOCK:
                self._blocked_ips[ip_address] = datetime.now(timezone.utc) + timedelta(
                    minutes=OTPSecurityConfig.IP_BLOCK_DURATION_MINUTES
                )
    
    # ========== OTP ==========
    
    def create_otp_verification(
        self,
        user_type: str,
        user_id: str,
        email: str,
        purpose: OTPPurpose,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        device_fingerprint: Optional[str] = None,
        phone: Optional[str] = None,
        delivery_channel: str = 'email'
    ) -> SecurityResult:
        """Create OTP verification request.

        ``delivery_channel`` selects how the code will reach the user
        (``'email'``, ``'sms'``, or ``'both'``). When SMS delivery is
        requested, ``phone`` must be a non-empty E.164-style number.
        """
        # Check rate limits
        if ip_address and not self._check_rate_limit(ip_address, "otp_request"):
            return SecurityResult(
                success=False,
                error_code="RATE_LIMITED",
                message="Too many OTP requests. Please try again later."
            )

        normalized_channel = (delivery_channel or 'email').strip().lower()
        if normalized_channel not in ('email', 'sms', 'both'):
            normalized_channel = 'email'

        normalized_phone = (phone or '').strip() or None
        if normalized_channel in ('sms', 'both') and not normalized_phone:
            return SecurityResult(
                success=False,
                error_code="MISSING_PHONE",
                message="A phone number is required for SMS verification."
            )
        
        # Check if device is trusted
        is_trusted = False
        is_new_device = True
        
        if device_fingerprint:
            trusted = self._get_trusted_device(user_type, user_id, device_fingerprint)
            if trusted:
                is_trusted = True
                is_new_device = False
        
        # Calculate risk score
        risk_score = self._calculate_risk_score(
            is_new_device=is_new_device,
            ip_address=ip_address,
            user_agent=user_agent
        )
        
        # Generate OTP
        otp_code = generate_otp(OTPSecurityConfig.OTP_LENGTH)
        salt = generate_salt()
        otp_hash = hash_otp(otp_code, salt)
        
        verification = OTPVerification(
            verification_id=generate_id("OTP"),
            user_type=user_type,
            user_id=user_id,
            email=email,
            purpose=purpose,
            otp_hash=otp_hash,
            otp_salt=salt,
            ip_address=ip_address,
            user_agent=user_agent,
            device_fingerprint=device_fingerprint,
            is_new_device=is_new_device,
            risk_score=risk_score,
            delivery_channel=normalized_channel,
            phone=normalized_phone,
            expires_at=datetime.now(timezone.utc) + timedelta(
                seconds=OTPSecurityConfig.OTP_EXPIRY_SECONDS
            )
        )
        
        with self._lock:
            # Invalidate any existing verifications for this user/purpose
            for v in self._verifications.values():
                if (v.user_id == user_id and 
                    v.purpose == purpose and 
                    v.status == VerificationStatus.PENDING):
                    v.status = VerificationStatus.EXPIRED
            
            self._verifications[verification.verification_id] = verification
        
        self._log_audit(
            action="otp_created",
            user_type=user_type,
            user_id=user_id,
            ip_address=ip_address,
            details={
                "verification_id": verification.verification_id,
                "purpose": purpose.value,
                "risk_score": risk_score,
                "is_new_device": is_new_device
            }
        )

        return SecurityResult(
            success=True,
            verification_id=verification.verification_id,
            data={
                "verification_id": verification.verification_id,
                "otp_code": otp_code,  # delivered via email/SMS by the caller
                "masked_email": mask_email(email),
                "expires_in_seconds": OTPSecurityConfig.OTP_EXPIRY_SECONDS,
                "is_new_device": is_new_device,
                "risk_level": "high" if risk_score > 0.7 else ("medium" if risk_score > 0.4 else "low"),
                "delivery_channel": normalized_channel,
                "phone": normalized_phone,
                "masked_phone": _mask_phone(normalized_phone) if normalized_phone else None,
            }
        )

    def resend_otp(
        self,
        verification_id: str,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> SecurityResult:
        """Resend OTP for an existing verification request."""
        with self._lock:
            verification = self._verifications.get(verification_id)
            if not verification:
                return SecurityResult(
                    success=False,
                    error_code="INVALID_VERIFICATION",
                    message="Invalid verification request"
                )

            if verification.status == VerificationStatus.BLOCKED:
                return SecurityResult(
                    success=False,
                    error_code="MAX_ATTEMPTS",
                    message="Verification is blocked due to too many attempts"
                )

            if verification.status == VerificationStatus.VERIFIED:
                return SecurityResult(
                    success=False,
                    error_code="ALREADY_VERIFIED",
                    message="Verification already completed"
                )

            now = datetime.now(timezone.utc)
            cooldown_until = verification.created_at + timedelta(
                seconds=OTPSecurityConfig.OTP_RESEND_COOLDOWN_SECONDS
            )
            if now < cooldown_until:
                retry_after = max(1, int((cooldown_until - now).total_seconds()))
                return SecurityResult(
                    success=False,
                    error_code="RESEND_COOLDOWN",
                    message=f"Please wait {retry_after} seconds before resending",
                    data={"retry_after_seconds": retry_after}
                )

            otp_code = generate_otp(OTPSecurityConfig.OTP_LENGTH)
            salt = generate_salt()
            verification.otp_salt = salt
            verification.otp_hash = hash_otp(otp_code, salt)
            verification.status = VerificationStatus.PENDING
            verification.attempts = 0
            verification.created_at = now
            verification.expires_at = now + timedelta(
                seconds=OTPSecurityConfig.OTP_EXPIRY_SECONDS
            )
            if ip_address:
                verification.ip_address = ip_address
            if user_agent:
                verification.user_agent = user_agent

        self._log_audit(
            action="otp_resent",
            user_type=verification.user_type,
            user_id=verification.user_id,
            ip_address=ip_address,
            details={
                "verification_id": verification_id,
                "purpose": verification.purpose.value
            },
            success=True
        )

        return SecurityResult(
            success=True,
            message="OTP resent successfully",
            verification_id=verification_id,
            data={
                "verification_id": verification_id,
                "email": verification.email,
                "masked_email": mask_email(verification.email),
                "otp_code": otp_code,
                "expires_in_seconds": OTPSecurityConfig.OTP_EXPIRY_SECONDS,
                "purpose": verification.purpose.value,
                "delivery_channel": verification.delivery_channel,
                "phone": verification.phone,
                "masked_phone": _mask_phone(verification.phone) if verification.phone else None,
            }
        )
    
    def verify_otp(
        self,
        verification_id: str,
        otp_code: str,
        ip_address: Optional[str] = None,
        trust_device: bool = False
    ) -> SecurityResult:
        """Verify OTP code"""
        with self._lock:
            verification = self._verifications.get(verification_id)
        
        if not verification:
            return SecurityResult(
                success=False,
                error_code="INVALID_VERIFICATION",
                message="Invalid verification request"
            )
        
        # Check status
        if verification.status != VerificationStatus.PENDING:
            return SecurityResult(
                success=False,
                error_code="INVALID_STATUS",
                message=f"Verification is {verification.status.value}"
            )
        
        # Check expiry
        if datetime.now(timezone.utc) > verification.expires_at:
            verification.status = VerificationStatus.EXPIRED
            return SecurityResult(
                success=False,
                error_code="OTP_EXPIRED",
                message="OTP has expired. Please request a new one."
            )
        
        # Check attempts
        verification.attempts += 1
        
        if verification.attempts > verification.max_attempts:
            verification.status = VerificationStatus.BLOCKED
            return SecurityResult(
                success=False,
                error_code="MAX_ATTEMPTS",
                message="Maximum verification attempts exceeded"
            )
        
        # Verify code (timing-safe comparison)
        code_hash = hash_otp(otp_code, verification.otp_salt)
        if not hmac.compare_digest(code_hash, verification.otp_hash):
            remaining = verification.max_attempts - verification.attempts
            self._log_audit(
                action="otp_failed",
                user_type=verification.user_type,
                user_id=verification.user_id,
                ip_address=ip_address,
                details={
                    "verification_id": verification_id,
                    "attempts_remaining": remaining
                },
                success=False
            )
            return SecurityResult(
                success=False,
                error_code="INVALID_OTP",
                message=f"Invalid OTP code. {remaining} attempts remaining."
            )
        
        # Success
        verification.status = VerificationStatus.VERIFIED
        verification.verified_at = datetime.now(timezone.utc)
        
        # Trust device if requested
        device_id = None
        if trust_device and verification.device_fingerprint:
            device_id = self._trust_device(
                user_type=verification.user_type,
                user_id=verification.user_id,
                device_fingerprint=verification.device_fingerprint,
                user_agent=verification.user_agent
            )
        
        self._log_audit(
            action="otp_verified",
            user_type=verification.user_type,
            user_id=verification.user_id,
            ip_address=ip_address,
            details={
                "verification_id": verification_id,
                "device_trusted": device_id is not None
            },
            success=True
        )
        
        return SecurityResult(
            success=True,
            message="OTP verified successfully",
            verification_id=verification_id,
            data={
                "user_id": verification.user_id,
                "user_type": verification.user_type,
                "purpose": verification.purpose.value,
                "device_trusted": device_id is not None,
                "device_id": device_id
            }
        )

    def consume_verification(
        self,
        verification_id: str,
        expected_email: Optional[str] = None,
        expected_purpose: Optional[OTPPurpose] = None,
        ip_address: Optional[str] = None,
        expected_user_type: Optional[str] = None
    ) -> SecurityResult:
        """
        Mark a verified OTP as consumed for one-time backend operations.
        This prevents replay of a previously verified registration token.
        """
        with self._lock:
            verification = self._verifications.get(verification_id)
            if not verification:
                return SecurityResult(
                    success=False,
                    error_code="INVALID_VERIFICATION",
                    message="Invalid verification request"
                )

            if verification_id in self._consumed_verifications:
                return SecurityResult(
                    success=False,
                    error_code="OTP_ALREADY_USED",
                    message="Verification token has already been consumed"
                )

            if verification.status != VerificationStatus.VERIFIED:
                return SecurityResult(
                    success=False,
                    error_code="OTP_NOT_VERIFIED",
                    message="OTP verification is required before continuing"
                )

            if expected_email and verification.email.lower() != expected_email.lower():
                return SecurityResult(
                    success=False,
                    error_code="EMAIL_MISMATCH",
                    message="Verified email does not match registration email"
                )

            if expected_user_type and verification.user_type != expected_user_type:
                return SecurityResult(
                    success=False,
                    error_code="USER_TYPE_MISMATCH",
                    message="Verification does not match this account type"
                )

            if expected_purpose and verification.purpose != expected_purpose:
                if not (
                    expected_purpose == OTPPurpose.REGISTRATION
                    and verification.purpose == OTPPurpose.EMAIL_VERIFICATION
                ):
                    return SecurityResult(
                        success=False,
                        error_code="PURPOSE_MISMATCH",
                        message="Verification purpose does not match this operation"
                    )

            verified_at = verification.verified_at or verification.created_at
            max_age_seconds = max(OTPSecurityConfig.OTP_EXPIRY_SECONDS, 300)
            if datetime.now(timezone.utc) - verified_at > timedelta(seconds=max_age_seconds):
                return SecurityResult(
                    success=False,
                    error_code="VERIFICATION_EXPIRED",
                    message="Verification window has expired. Please request a new OTP."
                )

            self._consumed_verifications.add(verification_id)

        self._log_audit(
            action="otp_consumed",
            user_type=verification.user_type,
            user_id=verification.user_id,
            ip_address=ip_address,
            details={
                "verification_id": verification_id,
                "purpose": verification.purpose.value
            },
            success=True
        )

        return SecurityResult(
            success=True,
            message="Verification consumed successfully",
            verification_id=verification_id,
            data={
                "user_id": verification.user_id,
                "user_type": verification.user_type,
                "purpose": verification.purpose.value
            }
        )
    
    # ========== DEVICE TRUST ==========
    
    def _get_trusted_device(
        self,
        user_type: str,
        user_id: str,
        device_fingerprint: str
    ) -> Optional[TrustedDevice]:
        """Get trusted device if exists"""
        for device in self._trusted_devices.values():
            if (device.user_type == user_type and
                device.user_id == user_id and
                device.device_fingerprint == device_fingerprint and
                device.is_active):
                return device
        return None
    
    def _trust_device(
        self,
        user_type: str,
        user_id: str,
        device_fingerprint: str,
        user_agent: Optional[str] = None
    ) -> str:
        """Mark a device as trusted"""
        device_id = generate_id("DEVICE")
        
        # Parse user agent for device name
        device_name = "Unknown Device"
        if user_agent:
            if "Windows" in user_agent:
                device_name = "Windows PC"
            elif "Mac" in user_agent:
                device_name = "Mac"
            elif "iPhone" in user_agent:
                device_name = "iPhone"
            elif "Android" in user_agent:
                device_name = "Android Device"
            elif "Linux" in user_agent:
                device_name = "Linux PC"
            
            # Add browser
            if "Chrome" in user_agent:
                device_name += " - Chrome"
            elif "Firefox" in user_agent:
                device_name += " - Firefox"
            elif "Safari" in user_agent and "Chrome" not in user_agent:
                device_name += " - Safari"
        
        device = TrustedDevice(
            device_id=device_id,
            user_type=user_type,
            user_id=user_id,
            device_fingerprint=device_fingerprint,
            device_name=device_name,
            user_agent=user_agent
        )
        
        with self._lock:
            # Check device limit
            user_devices = [
                d for d in self._trusted_devices.values()
                if d.user_type == user_type and d.user_id == user_id and d.is_active
            ]
            
            if len(user_devices) >= OTPSecurityConfig.MAX_TRUSTED_DEVICES:
                # Remove oldest device
                oldest = min(user_devices, key=lambda d: d.trusted_at)
                oldest.is_active = False
                oldest.revoked_at = datetime.now(timezone.utc)
            
            self._trusted_devices[device_id] = device
        
        return device_id
    
    def get_trusted_devices(
        self,
        user_type: str,
        user_id: str
    ) -> List[Dict[str, Any]]:
        """Get list of trusted devices for a user"""
        devices = []
        for device in self._trusted_devices.values():
            if (device.user_type == user_type and
                device.user_id == user_id and
                device.is_active):
                devices.append({
                    'device_id': device.device_id,
                    'device_name': device.device_name,
                    'first_seen': device.first_seen.isoformat(),
                    'last_seen': device.last_seen.isoformat(),
                    'trusted_at': device.trusted_at.isoformat()
                })
        return devices
    
    def revoke_device(
        self,
        user_type: str,
        user_id: str,
        device_id: str
    ) -> bool:
        """Revoke a trusted device"""
        device = self._trusted_devices.get(device_id)
        if (device and
            device.user_type == user_type and
            device.user_id == user_id):
            device.is_active = False
            device.revoked_at = datetime.now(timezone.utc)
            return True
        return False
    
    # ========== RISK ASSESSMENT ==========
    
    def _calculate_risk_score(
        self,
        is_new_device: bool,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> float:
        """Calculate risk score (0.0 to 1.0)"""
        score = 0.0
        
        # New device is higher risk
        if is_new_device:
            score += 0.3
        
        # Check IP reputation (simplified)
        if ip_address:
            # Check for suspicious patterns
            if ip_address.startswith("10.") or ip_address.startswith("192.168."):
                score += 0.1  # Internal IP might be proxy
            
            # Check recent failures from this IP
            key = f"login_fail:{ip_address}"
            if key in self._rate_limits:
                recent = [
                    t for t in self._rate_limits[key]
                    if datetime.now(timezone.utc) - t < timedelta(hours=1)
                ]
                if len(recent) > 3:
                    score += 0.2
        
        # Normalize
        return min(score, 1.0)
    
    def check_login_requirements(
        self,
        user_type: str,
        user_id: str,
        email: str,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        device_fingerprint: Optional[str] = None
    ) -> SecurityResult:
        """Check what security requirements are needed for login"""
        requires_otp = False
        requires_captcha = OTPSecurityConfig.CAPTCHA_ENABLED
        
        # Check if device is trusted
        is_trusted = False
        if device_fingerprint:
            trusted = self._get_trusted_device(user_type, user_id, device_fingerprint)
            if trusted:
                is_trusted = True
                # Update last seen
                trusted.last_seen = datetime.now(timezone.utc)
        
        # Require OTP for new devices
        if not is_trusted and OTPSecurityConfig.OTP_REQUIRED_FOR_NEW_DEVICE:
            requires_otp = True
        
        # Calculate risk
        risk_score = self._calculate_risk_score(
            is_new_device=not is_trusted,
            ip_address=ip_address,
            user_agent=user_agent
        )
        
        # High risk always requires OTP
        if risk_score > 0.5:
            requires_otp = True
        
        return SecurityResult(
            success=True,
            requires_otp=requires_otp,
            requires_captcha=requires_captcha,
            data={
                "is_trusted_device": is_trusted,
                "risk_score": risk_score,
                "risk_level": "high" if risk_score > 0.7 else ("medium" if risk_score > 0.4 else "low")
            }
        )
    
    # ========== RATE LIMITING ==========
    
    def _check_rate_limit(self, identifier: str, action: str) -> bool:
        """Check if action is within rate limits"""
        key = f"{action}:{identifier}"
        now = datetime.now(timezone.utc)
        
        with self._lock:
            if key not in self._rate_limits:
                self._rate_limits[key] = []
            
            # Clean old entries
            one_hour_ago = now - timedelta(hours=1)
            self._rate_limits[key] = [
                t for t in self._rate_limits[key] if t > one_hour_ago
            ]
            
            # Get limit based on action
            if action == "otp_request":
                limit = OTPSecurityConfig.OTP_REQUESTS_PER_IP_HOUR
            elif action == "login":
                limit = OTPSecurityConfig.LOGIN_ATTEMPTS_PER_IP_HOUR
            else:
                limit = 50  # Default
            
            if len(self._rate_limits[key]) >= limit:
                return False
            
            self._rate_limits[key].append(now)
            return True
    
    def _is_ip_blocked(self, ip_address: str) -> bool:
        """Check if IP is blocked"""
        with self._lock:
            if ip_address in self._blocked_ips:
                if datetime.now(timezone.utc) < self._blocked_ips[ip_address]:
                    return True
                else:
                    del self._blocked_ips[ip_address]
            return False
    
    # ========== AUDIT LOGGING ==========
    
    def _log_audit(
        self,
        action: str,
        user_type: Optional[str] = None,
        user_id: Optional[str] = None,
        ip_address: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        success: bool = True
    ) -> None:
        """Log security event"""
        event = {
            'id': generate_id('AUDIT'),
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'action': action,
            'user_type': user_type,
            'user_id': user_id,
            'ip_address': ip_address,
            'details': details or {},
            'success': success
        }
        
        with self._lock:
            self._audit_log.append(event)
            # Keep last 10000 events
            if len(self._audit_log) > 10000:
                self._audit_log = self._audit_log[-10000:]
        
        log_level = logging.INFO if success else logging.WARNING
        logger.log(log_level, f"SECURITY: {action} - {json.dumps(event)}")
    
    def get_audit_log(
        self,
        limit: int = 100,
        user_id: Optional[str] = None,
        action: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Get audit log entries"""
        with self._lock:
            events = self._audit_log.copy()
        
        if user_id:
            events = [e for e in events if e.get('user_id') == user_id]
        if action:
            events = [e for e in events if e.get('action') == action]
        
        return events[-limit:]


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_otp_security_service: Optional[OTPSecurityService] = None


def get_otp_security_service() -> OTPSecurityService:
    """Get or create the OTP security service singleton"""
    global _otp_security_service
    if _otp_security_service is None:
        _otp_security_service = OTPSecurityService()
    return _otp_security_service


def reset_otp_security_service() -> None:
    """Reset the OTP security service (for testing)"""
    global _otp_security_service
    _otp_security_service = None


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    'OTPSecurityConfig',
    'OTPPurpose',
    'ChallengeType',
    'RiskLevel',
    'VerificationStatus',
    'CaptchaChallenge',
    'OTPVerification',
    'TrustedDevice',
    'SecurityResult',
    'SimpleCaptchaGenerator',
    'OTPSecurityService',
    'get_otp_security_service',
    'reset_otp_security_service',
    'generate_otp',
    'generate_device_fingerprint',
    'mask_email'
]
