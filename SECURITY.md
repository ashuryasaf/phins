# PHINS Platform Security Guide

## Table of Contents
- [Credential Management](#credential-management)
- [Environment Variables](#environment-variables)
- [Secrets Management](#secrets-management)
- [Security Best Practices](#security-best-practices)
- [Reporting Vulnerabilities](#reporting-vulnerabilities)

---

## Credential Management

### Overview

The PHINS platform uses **environment variables** for all sensitive credentials. This ensures:
- No secrets are hardcoded in source code
- Credentials can be rotated without code changes
- Different environments (dev/staging/prod) can use different credentials
- Secrets are not exposed in version control

### Setting Up Credentials

1. **Copy the example file:**
   ```bash
   cp .env.example .env
   ```

2. **Generate secure passwords:**
   ```bash
   # Generate a secure random password
   python3 -c "import secrets; print(secrets.token_urlsafe(24))"
   
   # Generate a 32-byte hex secret (for signing keys)
   python3 -c "import secrets; print(secrets.token_hex(32))"
   ```

3. **Fill in your `.env` file** with secure values

4. **Never commit `.env`** - it's already in `.gitignore`

---

## Environment Variables

### Required Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `PHINS_ADMIN_PASSWORD` | Admin user password | `Str0ng_P@ssw0rd!` |
| `PHINS_UNDERWRITER_PASSWORD` | Underwriter password | `Str0ng_P@ssw0rd!` |
| `PHINS_CLAIMS_PASSWORD` | Claims adjuster password | `Str0ng_P@ssw0rd!` |
| `PHINS_ACCOUNTANT_PASSWORD` | Accountant password | `Str0ng_P@ssw0rd!` |
| `PHINS_ACTUARY_PASSWORD` | Actuary password | `Str0ng_P@ssw0rd!` |
| `PHINS_SUPPLIER_PASSWORD` | Supplier password | `Str0ng_P@ssw0rd!` |
| `PHINS_MEDIA_PASSWORD` | Media admin password | `Str0ng_P@ssw0rd!` |

### Named User Accounts

| Variable | Description |
|----------|-------------|
| `PHINS_USER_ASAF_PHINS_PASSWORD` | asaf@phins.ai account |
| `PHINS_USER_ASAF_ASSURANCE_PASSWORD` | asaf@assurance.co.il account |
| `PHINS_USER_EFRAT_PASSWORD` | efrat@phins.ai account |
| `PHINS_USER_ASI_PASSWORD` | asi@phins.ai account |
| `PHINS_USER_SHOSH_PASSWORD` | shosh@phins.ai account |

### Optional Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `PHINS_DEFAULT_CUSTOMER_PASSWORD` | Default for new customers | Random (unusable) |
| `PHINS_TEST_CUSTOMER_PASSWORD` | Test customer accounts | Random (unusable) |
| `PHINS_UPLOAD_DIR` | File upload directory | `/workspace/uploads` |
| `WEBHOOK_SIGNING_SECRET` | Webhook signature secret | Auto-generated |
| `SESSION_SECRET_KEY` | Session signing key | Auto-generated |
| `GEMINI_API_KEY` | Gemini / Veo video generation API key | Not configured |
| `KLING_API_KEY` | Kling video generation API key | Not configured |

---

## Secrets Management

### For Development

Use a local `.env` file (never commit it):

```bash
# Development setup
cp .env.example .env
# Edit .env with your development credentials
```

### For Production

We recommend using a secrets manager:

#### AWS Secrets Manager

```python
import boto3
import json

def get_secret(secret_name):
    client = boto3.client('secretsmanager')
    response = client.get_secret_value(SecretId=secret_name)
    return json.loads(response['SecretString'])

# Usage
secrets = get_secret('phins/production/credentials')
os.environ['PHINS_ADMIN_PASSWORD'] = secrets['admin_password']
```

#### HashiCorp Vault

```python
import hvac

client = hvac.Client(url='https://vault.example.com')
client.token = os.environ['VAULT_TOKEN']

secret = client.secrets.kv.v2.read_secret_version(path='phins/credentials')
os.environ['PHINS_ADMIN_PASSWORD'] = secret['data']['data']['admin_password']
```

#### Railway/Vercel/Heroku

Use the platform's built-in environment variable management:
- Railway: Settings → Variables
- Vercel: Settings → Environment Variables
- Heroku: Settings → Config Vars

---

## Security Best Practices

### 1. Password Requirements

All passwords should meet these requirements:
- Minimum 12 characters
- Mix of uppercase, lowercase, numbers, and symbols
- No dictionary words
- Unique per account (no password reuse)

### 2. Credential Rotation

Rotate credentials regularly:
- **Production:** Every 90 days
- **After incidents:** Immediately
- **Staff changes:** When employees leave

### 3. Access Control

- Use principle of least privilege
- Separate credentials per environment
- Audit access logs regularly

### 4. Code Security

- Never hardcode credentials
- Use environment variables
- Review PRs for accidental secret exposure
- CI/CD pipeline includes credential scanning

### 5. File Security

These files should NEVER be committed:
- `.env` (any variant)
- `*.pem`, `*.key` (private keys)
- `credentials.json`
- `secrets.json`
- Database dumps

---

## CI/CD Security Scanning

The repository includes automated security scanning:

### Gitleaks
Scans for hardcoded secrets in commits:
```yaml
# Runs on every PR and push
- uses: gitleaks/gitleaks-action@v2
```

### Bandit
Python security linter:
```yaml
# Checks for common security issues
- run: bandit -r . --exclude tests
```

### Dependency Scanning
Checks for vulnerable dependencies:
```yaml
# Using safety and pip-audit
- run: safety check -r requirements.txt
- run: pip-audit -r requirements.txt
```

---

## Reporting Vulnerabilities

### Responsible Disclosure

If you discover a security vulnerability:

1. **DO NOT** create a public GitHub issue
2. Email security concerns to: security@phins.ai
3. Include:
   - Description of the vulnerability
   - Steps to reproduce
   - Potential impact
   - Suggested fix (if any)

### Response Timeline

- **Acknowledgment:** Within 24 hours
- **Initial Assessment:** Within 72 hours
- **Fix Timeline:** Based on severity
  - Critical: 24-48 hours
  - High: 7 days
  - Medium: 30 days
  - Low: 90 days

---

## Security Checklist

Before deploying to production:

- [ ] All environment variables set
- [ ] No hardcoded credentials in code
- [ ] `.env` file is NOT committed
- [ ] Database credentials are secure
- [ ] API keys are properly scoped
- [ ] SSL/TLS is enabled
- [ ] Security headers configured
- [ ] Rate limiting enabled
- [ ] Input validation in place
- [ ] SQL injection protection active
- [ ] XSS protection enabled
- [ ] CSRF protection enabled
- [ ] Session security configured
- [ ] Audit logging enabled
- [ ] Backup encryption enabled

---

## Contact

For security questions or concerns:
- **Security Team:** security@phins.ai
- **Emergency:** On-call security team via PagerDuty

---

*Last updated: January 2026*
