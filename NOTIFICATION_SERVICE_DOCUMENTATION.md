# PHINS Enterprise Notification Service

## Overview

The PHINS Enterprise Notification Service is a full-scale, global notification system designed for client validation through email and OTP services. Built with enterprise security as the paramount concern, this service provides:

- **Multi-channel delivery**: Email, SMS, Push notifications
- **OTP/2FA verification**: Secure one-time password generation and validation
- **Rate limiting**: Protection against abuse and brute force attacks
- **Queue management**: Async delivery with retry logic
- **Client verification workflows**: Complete verification process management
- **Comprehensive audit logging**: Full security event tracking

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    PHINS Notification Service Architecture                   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐        │
│  │  Client Portal  │    │  Admin Portal   │    │   API Gateway   │        │
│  └────────┬────────┘    └────────┬────────┘    └────────┬────────┘        │
│           │                      │                      │                  │
│           └──────────────────────┼──────────────────────┘                  │
│                                  │                                          │
│                                  ▼                                          │
│  ┌───────────────────────────────────────────────────────────────────┐     │
│  │                     Notification Service                          │     │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐       │     │
│  │  │ Rate Limiter│  │ Validator   │  │ Preference Manager  │       │     │
│  │  └─────────────┘  └─────────────┘  └─────────────────────┘       │     │
│  └───────────────────────────────────────────────────────────────────┘     │
│                                  │                                          │
│           ┌──────────────────────┼──────────────────────┐                  │
│           ▼                      ▼                      ▼                  │
│  ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐        │
│  │   OTP Service   │    │  Email Service  │    │   SMS Service   │        │
│  │ ┌─────────────┐ │    │ ┌─────────────┐ │    │ ┌─────────────┐ │        │
│  │ │ Generator   │ │    │ │  Templates  │ │    │ │  Providers  │ │        │
│  │ │ Validator   │ │    │ │  Providers  │ │    │ │  • Twilio   │ │        │
│  │ │ Hash Store  │ │    │ │  • SMTP     │ │    │ │  • AWS SNS  │ │        │
│  │ └─────────────┘ │    │ │  • SendGrid │ │    │ │  • Vonage   │ │        │
│  └─────────────────┘    │ │  • AWS SES  │ │    │ └─────────────┘ │        │
│                         │ └─────────────┘ │    └─────────────────┘        │
│                         └─────────────────┘                                │
│                                  │                                          │
│                                  ▼                                          │
│  ┌───────────────────────────────────────────────────────────────────┐     │
│  │                    Notification Queue                             │     │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐       │     │
│  │  │Priority Heap│  │ Retry Logic │  │ Dead Letter Queue   │       │     │
│  │  └─────────────┘  └─────────────┘  └─────────────────────┘       │     │
│  └───────────────────────────────────────────────────────────────────┘     │
│                                  │                                          │
│                                  ▼                                          │
│  ┌───────────────────────────────────────────────────────────────────┐     │
│  │                    Security & Audit Layer                         │     │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐       │     │
│  │  │ Encryption  │  │   Signing   │  │    Audit Logger     │       │     │
│  │  └─────────────┘  └─────────────┘  └─────────────────────┘       │     │
│  └───────────────────────────────────────────────────────────────────┘     │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Security Features

### 1. OTP Security

| Feature | Implementation |
|---------|----------------|
| **Secure Generation** | Cryptographically secure random using `secrets` module |
| **Hash Storage** | OTP codes stored as salted PBKDF2-HMAC-SHA256 hashes |
| **Timing-Safe Comparison** | Uses `hmac.compare_digest()` to prevent timing attacks |
| **Auto-Expiry** | Configurable expiry (default: 5 minutes) |
| **Max Attempts** | Automatic lockout after 5 failed attempts |
| **One-Time Use** | OTP marked as used immediately upon successful verification |

### 2. Rate Limiting

```python
# Default Rate Limits
OTP_RATE_LIMIT_PER_MINUTE = 3
OTP_RATE_LIMIT_PER_HOUR = 10
OTP_RATE_LIMIT_PER_DAY = 20

EMAIL_RATE_LIMIT_PER_MINUTE = 10
EMAIL_RATE_LIMIT_PER_HOUR = 50
EMAIL_RATE_LIMIT_PER_DAY = 200

SMS_RATE_LIMIT_PER_MINUTE = 5
SMS_RATE_LIMIT_PER_HOUR = 20
SMS_RATE_LIMIT_PER_DAY = 50
```

### 3. Data Protection

- **Identifier Hashing**: All email/phone identifiers hashed for storage
- **Content Encryption**: Optional AES-256 encryption for sensitive content
- **PII Masking**: Automatic masking in logs and audit trails
- **Suppression Lists**: Hard/soft bounce handling for email deliverability

### 4. Audit Logging

All security-relevant events are logged:
- OTP generation and verification attempts
- Rate limit violations
- Suppression list additions
- Preference changes
- Delivery successes and failures

---

## Quick Start

### Basic Usage

```python
from services.notification_service import (
    create_notification_service,
    NotificationRequest,
    OTPRequest,
    NotificationChannel,
    VerificationType,
)

# Create service instance
service = create_notification_service(use_mock=False)

# Send an email notification
result = service.send(NotificationRequest(
    channel=NotificationChannel.EMAIL,
    recipient="user@example.com",
    subject="Welcome to PHINS",
    content="Thank you for joining PHINS Insurance!"
))

print(f"Sent: {result.success}, ID: {result.notification_id}")
```

### OTP Verification Flow

```python
# Step 1: Generate and send OTP
otp_result = service.send_otp(OTPRequest(
    identifier="user@example.com",
    channel=NotificationChannel.EMAIL,
    verification_type=VerificationType.EMAIL_VERIFICATION,
    customer_id="CUST001"
))

if otp_result.success:
    print(f"OTP sent! Expires at: {otp_result.expires_at}")

# Step 2: User enters OTP code...

# Step 3: Verify the OTP
verify_result = service.verify_otp(
    identifier="user@example.com",
    code="123456",  # User-provided code
    verification_type=VerificationType.EMAIL_VERIFICATION
)

if verify_result.success:
    print("Email verified successfully!")
else:
    print(f"Verification failed: {verify_result.error_message}")
    print(f"Attempts remaining: {verify_result.attempts_remaining}")
```

### Client Verification Workflow

```python
from services.notification_service import ClientVerificationService

# Initialize
verification_service = ClientVerificationService(notification_service)

# Start verification
init_result = verification_service.initiate_verification(
    customer_id="CUST001",
    verification_type=VerificationType.EMAIL_VERIFICATION,
    identifier="user@example.com",
    channel=NotificationChannel.EMAIL,
    ip_address=request.remote_addr  # For security tracking
)

# User receives email with OTP...

# Complete verification
verify_result = verification_service.verify(
    verification_id=init_result['verification_id'],
    code="123456"
)

# Check if customer is verified
if verification_service.is_verified("CUST001", VerificationType.EMAIL_VERIFICATION):
    print("Customer email is verified!")
```

---

## Configuration

### Environment Variables

```bash
# Email Configuration
EMAIL_PROVIDER=smtp          # smtp, sendgrid, ses, mailgun
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USE_TLS=true
SMTP_USERNAME=your_username
SMTP_PASSWORD=your_password
EMAIL_FROM_ADDRESS=noreply@phins.ai
EMAIL_FROM_NAME=PHINS Insurance

# SMS Configuration
SMS_PROVIDER=twilio          # twilio, sns, vonage, messagebird
TWILIO_ACCOUNT_SID=your_sid
TWILIO_AUTH_TOKEN=your_token
TWILIO_FROM_NUMBER=+14155551234

# OTP Configuration
OTP_LENGTH=6
OTP_EXPIRY_SECONDS=300       # 5 minutes
OTP_MAX_ATTEMPTS=5
OTP_RESEND_COOLDOWN_SECONDS=60

# Security
NOTIFICATION_SIGNING_SECRET=your_secret_key
PHINS_ENCRYPTION_KEY=your_fernet_key

# Rate Limiting
RATE_LIMIT_ENABLED=true
RATE_LIMIT_BLOCK_DURATION_MINUTES=30

# Queue Settings
NOTIFICATION_QUEUE_ENABLED=true
NOTIFICATION_QUEUE_MAX_RETRIES=3
NOTIFICATION_QUEUE_WORKER_THREADS=5
```

---

## API Reference

### NotificationService

| Method | Description |
|--------|-------------|
| `send(request)` | Send a notification |
| `send_otp(request)` | Generate and send OTP |
| `verify_otp(identifier, code, type)` | Verify an OTP |
| `add_to_suppression(identifier, channel)` | Add to suppression list |
| `remove_from_suppression(identifier, channel)` | Remove from suppression |
| `set_preferences(customer_id, prefs)` | Set notification preferences |
| `get_history(customer_id, limit)` | Get notification history |
| `get_audit_log(limit, action)` | Get audit log entries |

### OTPService

| Method | Description |
|--------|-------------|
| `generate_and_send(request)` | Generate OTP and deliver via channel |
| `verify(identifier, code, type)` | Verify OTP code |
| `invalidate(identifier, type)` | Invalidate all active OTPs |

### ClientVerificationService

| Method | Description |
|--------|-------------|
| `initiate_verification(...)` | Start verification workflow |
| `verify(verification_id, code)` | Complete verification |
| `resend_code(verification_id)` | Resend OTP code |
| `get_verification_status(id)` | Get verification status |
| `is_verified(customer_id, type)` | Check if verified |

---

## Notification Templates

### Built-in Templates

| Template ID | Description | Variables |
|-------------|-------------|-----------|
| `otp_email` | Email OTP | `code`, `expiry_minutes` |
| `otp_sms` | SMS OTP | `code`, `expiry_minutes` |
| `password_reset` | Password reset | `name`, `reset_link`, `expiry_hours` |
| `welcome` | Welcome message | `name`, `login_url` |
| `policy_approved` | Policy approval | `name`, `policy_type`, `policy_number`, ... |
| `claim_update` | Claim status update | `name`, `claim_id`, `status`, `additional_info` |
| `payment_reminder` | Payment due | `name`, `amount`, `policy_number`, `due_date` |
| `security_alert` | Security notification | `name`, `activity`, `timestamp`, `location`, `device` |

### Custom Templates

```python
# Templates use Jinja2-style {{ variable }} syntax
template = """
Dear {{ name }},

Your policy {{ policy_number }} has been renewed.

New Premium: {{ premium }}
Coverage: {{ coverage }}

Thank you for choosing PHINS Insurance.
"""

# Use with NotificationRequest
service.send(NotificationRequest(
    channel=NotificationChannel.EMAIL,
    recipient="user@example.com",
    template_id="policy_renewed",  # Custom template ID
    template_vars={
        "name": "John Smith",
        "policy_number": "POL-12345",
        "premium": "$150/month",
        "coverage": "$500,000"
    }
))
```

---

## Queue Service

### Priority-Based Processing

```python
from services.notification_queue_service import (
    NotificationQueueService,
    QueueStats
)

# Create queue service
queue = NotificationQueueService(
    notification_service=service,
    worker_count=5,
    auto_start=True
)

# Enqueue with priority
queue.enqueue(
    request=NotificationRequest(...),
    priority=NotificationPriority.CRITICAL  # Processed first
)

# Get queue stats
stats = queue.get_stats()
print(f"Pending: {stats.pending}")
print(f"Processing: {stats.processing}")
print(f"Success Rate: {stats.success_rate:.2%}")
```

### Retry Logic

- **Exponential Backoff**: Retry delays double each attempt
- **Maximum Retries**: Default 3 attempts
- **Dead Letter Queue**: Failed messages preserved for analysis

---

## Database Models

The service includes database models for persistent storage:

```python
from database.notification_models import (
    NotificationTemplate,    # Template storage
    NotificationQueue,       # Queue items
    NotificationHistory,     # Delivery history
    OTPCode,                 # OTP storage (hashed)
    ClientVerification,      # Verification workflows
    RateLimitRecord,         # Rate limit tracking
    EmailSuppressionList,    # Bounced/unsubscribed emails
    SMSSuppressionList,      # Invalid phone numbers
    NotificationPreference,  # Customer preferences
    NotificationAuditLog,    # Security audit trail
)
```

---

## Testing

Run the comprehensive test suite:

```bash
# Run all notification tests
pytest tests/test_notification_service.py -v

# Run specific test categories
pytest tests/test_notification_service.py -k "TestOTPService" -v
pytest tests/test_notification_service.py -k "TestSecurityFeatures" -v
```

---

## Compliance & Standards

| Standard | Implementation |
|----------|----------------|
| **GDPR** | Data minimization, consent tracking, audit logs |
| **PCI-DSS** | Secure credential storage, encryption |
| **SOC 2** | Access controls, audit logging |
| **HIPAA** | PHI encryption, access audit |

---

## Monitoring & Alerts

### Health Checks

```python
stats = queue.get_stats()

if not stats.is_healthy:
    for issue in stats.health_issues:
        alert(f"Queue health issue: {issue}")

# Monitor success rate
if stats.success_rate < 0.95:
    alert(f"Low delivery success rate: {stats.success_rate:.2%}")

# Monitor dead letter queue
if stats.dead_letter > 100:
    alert(f"High dead letter count: {stats.dead_letter}")
```

---

## Best Practices

1. **Always use HTTPS** for production deployments
2. **Rotate signing secrets** regularly
3. **Monitor rate limit violations** for potential attacks
4. **Review dead letter queue** daily
5. **Keep audit logs** for compliance (365 days recommended)
6. **Use templates** for consistent messaging
7. **Test with mock providers** before production deployment

---

## Support

For issues or questions, contact the PHINS development team or refer to the internal documentation portal.

---

*PHINS Enterprise Notification Service - Secure, Scalable, Global*
