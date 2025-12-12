# PHINS Security Features Documentation

## Overview

The PHINS insurance management system includes comprehensive security features to protect against malicious attacks, unauthorized access, and data breaches. This document details all implemented security measures.

## Security Architecture

### Multi-Layer Defense Strategy
1. **Input Validation** - All user inputs validated for malicious content
2. **Rate Limiting** - Prevents abuse and DDoS attacks
3. **IP Blocking** - Automatic blocking of malicious actors
4. **Authentication** - Session-based auth with password hashing
5. **Authorization** - Role-based access control (RBAC)
6. **Monitoring** - Real-time threat detection and logging

## Implemented Security Features

### 1. Injection Attack Prevention

#### SQL Injection Protection
- **Patterns Detected:**
  - `' OR '1'='1`
  - `admin'--`
  - `UNION SELECT`
  - `DROP TABLE`
  - Comment markers (`--`, `/*`, `*/`)

- **Action:** Immediate rejection with 400 error, logged as malicious attempt

#### XSS (Cross-Site Scripting) Protection
- **Patterns Detected:**
  - `<script>` tags
  - `javascript:` protocol
  - `onerror`, `onload` event handlers
  - `<iframe>` injections
  - SVG-based attacks

- **Action:** Input rejected, threat logged

#### Command Injection Protection
- **Patterns Detected:**
  - Shell operators (`;`, `|`, `&&`, `||`)
  - Command substitution (backticks, `$(...)`)
  - Pipe operators

- **Action:** Blocked immediately, IP flagged

#### Path Traversal Protection
- **Patterns Detected:**
  - `../` and `..\\` sequences
  - `....//` evasion attempts
  - URL-encoded traversal (`%2e%2e%2f`)

- **Action:** 404 error, attempt logged

### 2. Rate Limiting

**Configuration:**
- **Limit:** 60 requests per minute per IP
- **Window:** 60-second rolling window
- **Response:** 429 Too Many Requests

**Implementation:**
```python
REQUEST_COUNTS = {}  # {ip: [(timestamp, count), ...]}
RATE_LIMIT = 60  # requests per minute
```

**Enforcement Points:**
- All API endpoints
- Static file requests
- Login attempts

### 3. IP Blocking System

#### Automatic Blocking
- **Trigger:** 10 malicious attempts from same IP
- **Duration:** Permanent for severe threats, temporary for suspicious activity
- **Bypass:** Admin can manually unblock via security dashboard

#### Block Types
1. **Permanent Block**
   - Severe injection attempts
   - Authentication bypass attempts
   - Repeated attacks after warnings

2. **Temporary Block**
   - Suspicious patterns
   - Minor violations
   - Duration: 1-24 hours depending on severity

#### Data Structure
```python
BLOCKED_IPS = {
    'ip_address': {
        'permanent': True/False,
        'reason': 'Description of threat',
        'timestamp': 'ISO timestamp',
        'attempts': 15
    }
}
```

### 4. Authentication & Authorization

#### Password Security
- **Hashing:** PBKDF2 with SHA-256
- **Salt:** Unique 32-byte salt per user
- **Iterations:** 100,000 rounds

#### Session Management
- **Token:** UUID-based session tokens
- **Storage:** Server-side session store
- **Timeout:** Configurable per role
- **Validation:** Every request validates token

#### Login Protection
- **Lockout:** 5 failed attempts = 15-minute lockout
- **Tracking:** Per-IP failed login counter
- **Logging:** All failed attempts logged with IP and timestamp

### 5. Request Validation

#### Size Limits
- **Maximum Request Size:** 10 MB
- **Enforcement:** Content-Length header check
- **Response:** 413 Payload Too Large

#### Content Type Validation
- Strict content-type checking
- Multipart form data validation
- JSON schema validation

### 6. Threat Detection & Logging

#### Malicious Attempt Tracking
```python
MALICIOUS_ATTEMPTS = [
    {
        'timestamp': 'ISO timestamp',
        'ip': 'IP address',
        'threat_type': 'sql_injection|xss|path_traversal|...',
        'endpoint': 'Attacked endpoint',
        'payload': 'Attack payload (truncated)',
        'blocked': True/False
    }
]
```

#### Threat Categories
- `sql_injection` - SQL injection attempts
- `xss_attack` - Cross-site scripting
- `path_traversal` - Directory traversal
- `command_injection` - OS command injection
- `auth_bypass` - Authentication bypass
- `rate_limit_exceeded` - Rate limit violations
- `oversized_request` - Payload size attacks

### 7. Security Monitoring Dashboard

#### Admin Endpoint: `/api/security/threats`

**Access:** Admin role required

**Response:**
```json
{
  "malicious_attempts": [...],
  "blocked_ips": {...},
  "failed_logins": {...},
  "statistics": {
    "total_malicious_attempts": 0,
    "total_blocked_ips": 0,
    "permanent_blocks": 0,
    "active_lockouts": 0
  }
}
```

**Features:**
- Real-time threat monitoring
- IP blocking management
- Attack pattern analysis
- Historical data (last 100 attempts)

## Security Testing

### Test Suite: `test_security.py`

**Tests Included:**
1. SQL Injection Protection (5 attack vectors)
2. XSS Attack Protection (5 payloads)
3. Path Traversal Protection (5 attempts)
4. Command Injection Protection (5 vectors)
5. Authentication Bypass Prevention (3 methods)
6. Request Size Limiting (oversized payload)
7. Rate Limiting (70 rapid requests)
8. Security Monitoring Endpoint

**Run Tests:**
```bash
python test_security.py
```

### Expected Results
- All injection attempts should be blocked (100%)
- Rate limiting should activate after 60 requests
- Oversized requests rejected
- Security endpoint requires admin auth

## Security Reports

### Generate Security Report

**Command:**
```bash
python generate_security_report.py [admin_token]
```

**Report Contents:**
- Total malicious attempts
- Blocked IP addresses
- Threat type distribution
- Top attacking IPs
- Recent attack timeline
- Failed login statistics

**Output:**
- Console display with formatted tables
- JSON file: `security_report_YYYYMMDD_HHMMSS.json`

## Deployment Security Checklist

### Pre-Deployment
- [ ] Run full security test suite
- [ ] Review and clear test/demo credentials
- [ ] Configure rate limits for production load
- [ ] Set up external logging (Syslog, Splunk, etc.)
- [ ] Configure SSL/TLS certificates
- [ ] Review CORS settings
- [ ] Enable security headers (CSP, HSTS, X-Frame-Options)

### Production Configuration
```python
# Recommended production settings
RATE_LIMIT = 120  # Higher for production
MAX_MALICIOUS_ATTEMPTS = 5  # More aggressive
BLOCK_DURATION_TEMP = 3600  # 1 hour
SESSION_TIMEOUT = 1800  # 30 minutes
```

### Monitoring
- Set up alerts for:
  - IP blocks exceeding threshold
  - Sustained attack patterns
  - Authentication failures spike
  - Unusual traffic patterns

## Incident Response

### Handling Active Attack

1. **Identify:** Check `/api/security/threats` for patterns
2. **Block:** Automatic IP blocking after 10 attempts
3. **Review:** Analyze attack vectors in security report
4. **Patch:** Update detection patterns if needed
5. **Report:** Document incident for compliance

### Manual IP Unblock

**Currently:** Admin must directly modify `BLOCKED_IPS` dict
**Future:** Add `/api/security/unblock` endpoint

### False Positive Handling

If legitimate users are blocked:
1. Review `MALICIOUS_ATTEMPTS` log for their IP
2. Check if input contained suspicious patterns
3. Adjust detection thresholds if needed
4. Whitelist IP if necessary

## Security Maintenance

### Regular Tasks

**Daily:**
- Review malicious attempt logs
- Check for new blocked IPs
- Monitor failed login rates

**Weekly:**
- Generate security report
- Analyze attack trends
- Update detection patterns

**Monthly:**
- Review all permanent IP blocks
- Update password policies
- Security training for team

### Log Rotation

Implement log rotation to prevent memory issues:
```python
# Keep only last 1000 malicious attempts
if len(MALICIOUS_ATTEMPTS) > 1000:
    MALICIOUS_ATTEMPTS = MALICIOUS_ATTEMPTS[-1000:]
```

## Compliance & Standards

### Data Protection
- GDPR: User consent for data processing
- HIPAA: Health data encryption and access logs
- PCI DSS: Payment data security (if applicable)

### Security Standards
- OWASP Top 10 protections implemented
- CWE Common Weakness Enumeration addressed
- NIST Cybersecurity Framework alignment

## Known Limitations

1. **In-Memory Storage:** All security data lost on restart
   - **Solution:** Implement persistent storage (database)

2. **No Geographic Blocking:** Cannot block by country/region
   - **Solution:** Integrate GeoIP service

3. **Limited DoS Protection:** Application-level rate limiting only
   - **Solution:** Use WAF (CloudFlare, AWS WAF)

4. **No Automated Threat Intelligence:** Detection based on static patterns
   - **Solution:** Integrate threat intelligence feeds

## Future Enhancements

### Planned Features
- [ ] Two-factor authentication (2FA)
- [ ] CAPTCHA for login after 3 failed attempts
- [ ] Honeypot fields to trap bots
- [ ] Real-time email alerts for admins
- [ ] Security event webhooks
- [ ] Machine learning anomaly detection
- [ ] Automated backup of security logs
- [ ] Integration with SIEM systems

### Integration Recommendations
- **WAF:** CloudFlare, AWS WAF, or ModSecurity
- **SIEM:** Splunk, ELK Stack, or ArcSight
- **Threat Intel:** AlienVault OTX, VirusTotal API
- **Monitoring:** Datadog, New Relic, or Prometheus

## Support & Resources

### Documentation
- Security Testing: `test_security.py`
- Report Generation: `generate_security_report.py`
- Main Server: `web_portal/server.py`

### Contact
For security vulnerabilities, contact: security@phins.com
For general questions: support@phins.com

---

**Last Updated:** 2024
**Version:** 1.0
**Status:** Production Ready
