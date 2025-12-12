# Security Enhancements Applied to PHINS Web Portal

## Overview
Comprehensive security protections have been added to the web portal server to protect against common vulnerabilities and attacks.

## Security Features Implemented

### 1. **Session-Based Authentication**
- Secure token generation using `secrets.token_urlsafe(32)`
- 24-hour session expiration
- Session validation on every protected request
- Session tracking includes IP address and creation timestamp

### 2. **Rate Limiting**
- **60 requests per minute** per IP address
- Automatic reset after 60 seconds
- Returns HTTP 429 (Too Many Requests) with `Retry-After` header
- Protects against DoS attacks and brute force attempts

### 3. **Login Protection**
- **Maximum 5 failed login attempts** before lockout
- **15-minute lockout period** after exceeding max attempts
- Lockout counter resets on successful login
- Prevents brute force password attacks

### 4. **Password Security**
- Passwords hashed using PBKDF2-HMAC-SHA256 (100,000 iterations)
- Unique salt per password (32 bytes)
- Constant-time comparison using `secrets.compare_digest()`
- Minimum 6-character password requirement

### 5. **Role-Based Access Control (RBAC)**
- Admin-only access to BI dashboard endpoints:
  - `/api/bi/actuary` - Admin, Accountant, Underwriter only
  - `/api/bi/underwriting` - Admin, Underwriter only
  - `/api/bi/accounting` - Admin, Accountant only
- Returns HTTP 403 (Forbidden) for unauthorized access
- Session validation required for protected endpoints

### 6. **Security Headers**
All responses include protective HTTP headers:
- `X-Content-Type-Options: nosniff` - Prevents MIME-type sniffing
- `X-Frame-Options: DENY/SAMEORIGIN` - Prevents clickjacking
- `X-XSS-Protection: 1; mode=block` - Enables XSS filter
- `Strict-Transport-Security` - Enforces HTTPS (31536000 seconds)
- `Content-Security-Policy` - Restricts resource loading

### 7. **Input Validation & Sanitization**
- **Email validation**: RFC-compliant regex pattern, max 254 characters
- **Amount validation**: Numeric range 0 to 100,000,000
- **String sanitization**: Removes dangerous characters `< > " ' \ \x00 \n \r \t`
- **Max length enforcement**: 255 chars default, 100 for names, 254 for emails
- Prevents SQL injection, XSS, and command injection attacks

### 8. **Error Handling**
- Generic error messages to prevent information disclosure
- JSON decode errors return HTTP 400
- Internal errors return HTTP 500 without stack traces
- Authentication failures use same error message (timing attack prevention)

## User Credentials (Demo)

### Staff Accounts
```
Username: admin           | Password: admin123      | Role: Admin
Username: underwriter     | Password: under123      | Role: Underwriter
Username: claims_adjuster | Password: claims123     | Role: Claims Adjuster
Username: accountant      | Password: acct123       | Role: Accountant
```

### Customer Accounts
Customer accounts are auto-generated on policy creation with email as username.

## API Authentication

### Login Request
```bash
curl -X POST http://localhost:8000/api/login \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "admin123"}'
```

### Authenticated Request
```bash
curl http://localhost:8000/api/bi/actuary \
  -H "Authorization: Bearer phins_[token_from_login]"
```

## Rate Limiting Examples

### Within Limit (Success)
```
Request 1-60: HTTP 200 OK
```

### Exceeded Limit
```
Request 61+: HTTP 429 Too Many Requests
Retry-After: 60
{"error": "Too many requests. Please try again later."}
```

## Login Lockout Examples

### Failed Attempts
```
Attempt 1-4: HTTP 401 {"error": "Invalid credentials"}
Attempt 5+: HTTP 429 {"error": "Too many failed login attempts. Try again in 900 seconds."}
```

## Protected Endpoints

### Requires Authentication
- All `/api/bi/*` endpoints (BI dashboards)
- Role-specific access enforced

### Public Endpoints
- `/api/login` - Authentication
- `/api/policies` - Policy list (filtered by session)
- `/api/claims` - Claims list (filtered by session)
- Static files (HTML, CSS, JS)

## Security Best Practices Applied

1. ✅ Never store passwords in plaintext
2. ✅ Use secure random token generation
3. ✅ Implement rate limiting on all endpoints
4. ✅ Validate and sanitize all user inputs
5. ✅ Use constant-time comparison for passwords
6. ✅ Set security headers on all responses
7. ✅ Lock out accounts after failed login attempts
8. ✅ Expire sessions after inactivity
9. ✅ Log security events (failed logins, lockouts)
10. ✅ Return generic error messages

## Testing Security Features

### Test Rate Limiting
```bash
for i in {1..65}; do 
  curl -s http://localhost:8000/api/policies | head -1
done
```

### Test Login Lockout
```bash
for i in {1..6}; do
  curl -X POST http://localhost:8000/api/login \
    -H "Content-Type: application/json" \
    -d '{"username": "admin", "password": "wrong"}'
  echo ""
done
```

### Test Input Validation
```bash
# Invalid email
curl -X POST http://localhost:8000/api/policies/create \
  -H "Content-Type: application/json" \
  -d '{"customer_name": "Test", "customer_email": "invalid"}'

# Invalid amount
curl -X POST http://localhost:8000/api/policies/create \
  -H "Content-Type: application/json" \
  -d '{"customer_name": "Test", "coverage_amount": -1000}'
```

## Monitoring & Logging

Track the following in production:
- Failed login attempts per IP
- Rate limit violations per IP
- Session creation/expiration
- Unauthorized access attempts
- Input validation failures

## Future Enhancements

Consider adding:
- CAPTCHA after 3 failed login attempts
- Two-factor authentication (2FA)
- IP whitelisting for admin access
- Audit logging to database
- Intrusion detection system (IDS)
- API key authentication for service-to-service calls
- JWT tokens with refresh tokens
- Redis/Memcached for distributed rate limiting

## Compliance

These security measures help meet requirements for:
- OWASP Top 10 protection
- PCI DSS (payment card data)
- HIPAA (health information)
- GDPR (data protection)
- SOC 2 Type II (security controls)

## Support

For security issues or questions:
- Review code in `/workspaces/phins/web_portal/server.py`
- Check server logs: `/tmp/phins_server.log`
- Test endpoints with provided curl examples
