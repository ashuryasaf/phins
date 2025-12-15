# Database Security Guide

This document outlines security considerations for the PHINS database implementation.

## Critical Security Actions for Production

### 1. Change Default Passwords Immediately

The system seeds default users with well-known passwords for development:

| Username | Default Password | **MUST CHANGE** |
|----------|-----------------|-----------------|
| admin | admin123 | ✅ Required |
| underwriter | under123 | ✅ Required |
| claims_adjuster | claims123 | ✅ Required |
| accountant | acct123 | ✅ Required |

**How to change passwords:**

```python
from database.manager import DatabaseManager
import hashlib
import secrets

def hash_password(password: str) -> dict:
    salt = secrets.token_hex(16)
    hashed = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 100000)
    return {'hash': hashed.hex(), 'salt': salt}

# Change password
with DatabaseManager() as db:
    user = db.users.get_by_username('admin')
    new_pwd = hash_password('your_secure_password_here')
    db.users.update('admin', 
                    password_hash=new_pwd['hash'],
                    password_salt=new_pwd['salt'])
```

### 2. Database Connection Security

#### PostgreSQL Connection String

Always use environment variables, never hardcode credentials:

```bash
# Good - using environment variables
export DATABASE_URL="postgresql://user:password@host:port/database"

# Bad - hardcoded in code (NEVER DO THIS)
DATABASE_URL = "postgresql://user:password@localhost:5432/phins"
```

#### SSL/TLS for Production

For Railway and other cloud providers, ensure SSL is enforced:

```python
# In database/config.py, for production PostgreSQL:
connect_args = {
    'sslmode': 'require',  # Enforce SSL connection
    'options': '-c statement_timeout=30000'  # 30 second query timeout
}
```

### 3. SQL Query Logging

**NEVER** enable `ECHO_SQL` in production:

```python
# database/config.py
ECHO_SQL = False  # Keep False in production

# SQL echo logs contain sensitive data:
# - User passwords (even if hashed)
# - Personal information (PII)
# - Financial data
# - Session tokens
```

If debugging is needed in production, use application-level logging instead.

### 4. Database User Privileges

Use principle of least privilege for database users:

```sql
-- Create application user with limited privileges
CREATE USER phins_app WITH PASSWORD 'secure_password';

-- Grant only necessary permissions
GRANT CONNECT ON DATABASE phins TO phins_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO phins_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO phins_app;

-- Do NOT grant these in production:
-- REVOKE CREATE ON SCHEMA public FROM phins_app;
-- REVOKE DROP ON ALL TABLES FROM phins_app;
```

### 5. Connection Pooling Security

Configure secure connection pool settings:

```python
# database/config.py
POOL_SIZE = 20          # Limit concurrent connections
MAX_OVERFLOW = 10       # Cap maximum connections
POOL_TIMEOUT = 30       # Timeout for getting connection
POOL_RECYCLE = 3600     # Recycle connections hourly (prevents stale connections)
```

### 6. Audit Logging

All operations are logged to `audit_logs` table:

```python
# Automatically logged:
- User authentication attempts
- Policy creation/modification
- Claim approval/rejection
- Billing transactions
- Administrative actions
```

**Monitor audit logs regularly** for suspicious activity:

```sql
-- Check recent failed authentications
SELECT * FROM audit_logs 
WHERE action = 'login_failed' 
AND timestamp > NOW() - INTERVAL '1 hour'
ORDER BY timestamp DESC;

-- Check admin actions
SELECT * FROM audit_logs 
WHERE username = 'admin' 
ORDER BY timestamp DESC 
LIMIT 100;
```

### 7. Backup and Recovery

#### Automated Backups

Railway provides automatic daily backups. For manual backups:

```bash
# PostgreSQL backup
pg_dump -h $DB_HOST -U $DB_USER -d $DB_NAME -F c -f backup_$(date +%Y%m%d).dump

# Encrypt backup
gpg --encrypt --recipient your@email.com backup_*.dump
```

#### Backup Security

- **Encrypt all backups** before storing
- **Store backups securely** (separate from database)
- **Test restores regularly** to ensure backups work
- **Retain backups** according to compliance requirements

### 8. Session Security

Sessions are stored in database with expiration:

```python
# Configure session timeout (in seconds)
SESSION_TIMEOUT = 3600  # 1 hour

# Cleanup expired sessions regularly
from database.manager import DatabaseManager
with DatabaseManager() as db:
    count = db.sessions.delete_expired_sessions()
    print(f"Cleaned up {count} expired sessions")
```

### 9. SQL Injection Prevention

The ORM (SQLAlchemy) provides protection against SQL injection:

```python
# Safe - parameterized query
customer = db.customers.get_by_email(user_email)

# Also safe - ORM handles escaping
customers = db.customers.filter_by(city=user_city)

# Never do this (raw SQL with string concatenation):
# query = f"SELECT * FROM customers WHERE email = '{user_email}'"
```

### 10. Data Encryption

#### At Rest

Enable encryption at rest in your database provider:

- **Railway**: Encryption at rest enabled by default
- **AWS RDS**: Enable encryption when creating database
- **Self-hosted**: Use encrypted filesystem (LUKS, dm-crypt)

#### In Transit

Always use SSL/TLS for database connections:

```bash
# Force SSL in connection string
DATABASE_URL="postgresql://user:pass@host:5432/db?sslmode=require"
```

### 11. Access Control

Implement proper access control in your application:

```python
# Check user roles before operations
def require_admin(user):
    if user.role != 'admin':
        raise PermissionError("Admin access required")

# Audit administrative actions
with DatabaseManager() as db:
    db.audit.log_action(
        username=user.username,
        action='delete_customer',
        entity_type='customer',
        entity_id=customer_id,
        ip_address=request_ip
    )
```

### 12. Regular Security Audits

Schedule regular security reviews:

- **Weekly**: Review audit logs for anomalies
- **Monthly**: Check for suspicious database activity
- **Quarterly**: Update passwords and rotate secrets
- **Annually**: Full security audit and penetration testing

### 13. Environment Isolation

Keep environments strictly separated:

```bash
# Development
USE_DATABASE=1
USE_SQLITE=1
SQLITE_PATH=/tmp/dev.db

# Staging
USE_DATABASE=1
DATABASE_URL=postgresql://user:pass@staging-db:5432/phins_staging

# Production
USE_DATABASE=1
DATABASE_URL=postgresql://user:pass@prod-db:5432/phins_production
```

**Never** connect development tools to production database.

### 14. Incident Response

In case of security incident:

1. **Immediate**: Revoke compromised credentials
2. **Investigate**: Check audit logs for breach scope
3. **Contain**: Disable affected user accounts
4. **Notify**: Inform affected users per regulations
5. **Remediate**: Patch vulnerabilities
6. **Monitor**: Enhanced monitoring post-incident

### 15. Compliance Considerations

Depending on your jurisdiction:

- **GDPR**: Implement data deletion (right to be forgotten)
- **HIPAA**: Encrypt all PHI, maintain audit trails
- **PCI DSS**: Never store credit card data in application database
- **SOX**: Maintain audit logs for 7 years

## Security Checklist for Production

- [ ] Changed all default passwords
- [ ] Environment variables configured (no hardcoded credentials)
- [ ] SSL/TLS enabled for database connections
- [ ] ECHO_SQL disabled
- [ ] Database user has minimal required privileges
- [ ] Connection pool configured with appropriate limits
- [ ] Audit logging enabled and monitored
- [ ] Automated backups configured and tested
- [ ] Backup encryption enabled
- [ ] Session timeout configured
- [ ] Regular security audits scheduled
- [ ] Incident response plan documented
- [ ] Compliance requirements addressed

## Resources

- [OWASP Database Security Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Database_Security_Cheat_Sheet.html)
- [PostgreSQL Security Best Practices](https://www.postgresql.org/docs/current/ssl-tcp.html)
- [SQLAlchemy Security](https://docs.sqlalchemy.org/en/14/core/security.html)

## Questions or Concerns?

If you discover a security vulnerability, please report it responsibly:
1. Do not open a public GitHub issue
2. Email security concerns to security@phins.ai
3. Include detailed steps to reproduce
4. Allow time for patch before public disclosure
