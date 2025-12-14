# PHINS Railway Deployment Guide - Complete Edition

## Table of Contents
1. [Prerequisites](#prerequisites)
2. [Quick Start](#quick-start)
3. [Environment Variables](#environment-variables)
4. [Deployment Steps](#deployment-steps)
5. [Health Check Verification](#health-check-verification)
6. [API Endpoint Reference](#api-endpoint-reference)
7. [Security Configuration](#security-configuration)
8. [Performance Tuning](#performance-tuning)
9. [Monitoring Setup](#monitoring-setup)
10. [Troubleshooting Guide](#troubleshooting-guide)

---

## Prerequisites

### Required Software
- **Python 3.11+** - Runtime environment
- **Git** - Version control
- **Railway CLI** (optional but recommended)
  ```bash
  npm i -g @railway/cli
  # or
  brew install railway
  ```

### Required Accounts
- GitHub account (for repository)
- Railway account (sign up at https://railway.app)

### Local Development Setup
```bash
# Clone repository
git clone https://github.com/ashuryasaf/phins.git
cd phins

# Install dependencies
pip install -r requirements.txt

# Run tests
python -m pytest tests/ -v

# Test server locally
python web_portal/server.py
```

---

## Quick Start

### Option 1: Automated Deployment (Recommended)
```bash
# Validate configuration
python3 validate_railway_config.py

# Run all tests
./test_all_pipelines.sh

# Deploy with verification
./deploy_railway_verified.sh
```

### Option 2: Manual Deployment
```bash
# Login to Railway
railway login

# Create new project or link existing
railway init  # or railway link

# Deploy
railway up

# Get deployment URL
railway domain
```

### Option 3: GitHub Integration
1. Push code to GitHub
2. Connect Railway to GitHub repository
3. Railway auto-deploys on push to main branch

---

## Environment Variables

### Required Variables
None - the application runs with sensible defaults.

### Optional Variables

#### Server Configuration
```bash
PORT=8000                    # Server port (default: 8000)
PYTHONUNBUFFERED=1           # Python output buffering
```

#### Security Settings
```bash
MAX_REQUESTS_PER_MINUTE=60   # Rate limit (default: 60)
MAX_LOGIN_ATTEMPTS=5         # Failed login limit (default: 5)
SESSION_TIMEOUT=3600         # Session timeout in seconds (default: 3600)
CONNECTION_TIMEOUT=30        # Connection timeout (default: 30)
```

#### Feature Flags
```bash
BILLING_ENABLED=true         # Enable billing engine (default: true if available)
AUDIT_ENABLED=true           # Enable audit logging (default: true if available)
```

### Setting Environment Variables in Railway

#### Via Railway Dashboard:
1. Go to your project
2. Click on "Variables"
3. Add environment variables
4. Redeploy

#### Via Railway CLI:
```bash
railway variables set PORT=8000
railway variables set PYTHONUNBUFFERED=1
```

---

## Deployment Steps

### Step 1: Pre-Deployment Validation
```bash
# Validate configuration
python3 validate_railway_config.py

# Run comprehensive tests
./test_all_pipelines.sh

# Check for uncommitted changes
git status
```

### Step 2: Prepare for Deployment
```bash
# Commit all changes
git add .
git commit -m "Prepare for Railway deployment"
git push origin main
```

### Step 3: Deploy to Railway

#### Using Railway CLI:
```bash
# Login
railway login

# Link to project
railway link

# Deploy
railway up

# Check deployment status
railway status

# View logs
railway logs
```

#### Using GitHub Integration:
1. Connect Railway to GitHub repository
2. Select branch to deploy (main/master)
3. Railway automatically builds and deploys
4. Monitor deployment in Railway dashboard

### Step 4: Verify Deployment
```bash
# Get deployment URL
RAILWAY_URL=$(railway domain)

# Run health check
python3 railway_health_check.py "https://$RAILWAY_URL"
```

### Step 5: Post-Deployment Testing
```bash
# Test login
curl -X POST https://$RAILWAY_URL/api/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin123"}'

# Test policy creation
curl -X POST https://$RAILWAY_URL/api/policies/create \
  -H "Content-Type: application/json" \
  -d '{
    "customer_name": "Test Customer",
    "customer_email": "test@example.com",
    "type": "life",
    "coverage_amount": 100000
  }'

# Test metrics endpoint
curl https://$RAILWAY_URL/api/metrics
```

---

## Health Check Verification

### Automated Health Check
```bash
python3 railway_health_check.py https://your-app.railway.app
```

### Manual Health Checks

#### 1. Server Responds
```bash
curl https://your-app.railway.app/api/metrics
# Should return JSON with metrics
```

#### 2. Authentication Works
```bash
curl -X POST https://your-app.railway.app/api/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin123"}'
# Should return token starting with "phins_"
```

#### 3. Security Headers Present
```bash
curl -I https://your-app.railway.app/api/metrics
# Check for:
# X-Content-Type-Options: nosniff
# X-Frame-Options: DENY
# X-XSS-Protection: 1; mode=block
# Content-Security-Policy: ...
```

#### 4. Rate Limiting Active
```bash
# Make 65 requests quickly
for i in {1..65}; do
  curl https://your-app.railway.app/api/metrics
done
# Should get 429 Too Many Requests before completing all requests
```

---

## API Endpoint Reference

### Authentication Endpoints

#### POST /api/login
```bash
curl -X POST https://your-app.railway.app/api/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin123"}'
```
**Response:**
```json
{
  "token": "phins_abc123...",
  "username": "admin",
  "role": "admin",
  "customer_id": null
}
```

#### POST /api/register
```bash
curl -X POST https://your-app.railway.app/api/register \
  -H "Content-Type: application/json" \
  -d '{
    "name": "New Customer",
    "email": "customer@example.com",
    "password": "SecurePass123",
    "phone": "555-1234",
    "dob": "1990-01-01"
  }'
```

#### GET /api/profile
```bash
curl https://your-app.railway.app/api/profile \
  -H "Authorization: Bearer <token>"
```

### Policy Management

#### POST /api/policies/create
```bash
curl -X POST https://your-app.railway.app/api/policies/create \
  -H "Content-Type: application/json" \
  -d '{
    "customer_name": "John Doe",
    "customer_email": "john@example.com",
    "type": "life",
    "coverage_amount": 500000,
    "risk_score": "medium"
  }'
```

#### GET /api/policies
```bash
# List all policies with pagination
curl "https://your-app.railway.app/api/policies?page=1&page_size=50"

# Get specific policy
curl "https://your-app.railway.app/api/policies?id=POL-20231214-1234"
```

### Underwriting

#### GET /api/underwriting
```bash
curl https://your-app.railway.app/api/underwriting \
  -H "Authorization: Bearer <underwriter_token>"
```

#### POST /api/underwriting/approve
```bash
curl -X POST https://your-app.railway.app/api/underwriting/approve \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <underwriter_token>" \
  -d '{"id": "UW-20231214-1234", "approved_by": "underwriter"}'
```

### Claims Management

#### POST /api/claims/create
```bash
curl -X POST https://your-app.railway.app/api/claims/create \
  -H "Content-Type: application/json" \
  -d '{
    "policy_id": "POL-20231214-1234",
    "customer_id": "CUST-12345",
    "type": "medical",
    "description": "Emergency surgery",
    "claimed_amount": 50000
  }'
```

#### POST /api/claims/approve
```bash
curl -X POST https://your-app.railway.app/api/claims/approve \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <claims_token>" \
  -d '{
    "id": "CLM-20231214-1234",
    "approved_amount": 45000,
    "approved_by": "claims_adjuster",
    "notes": "Approved after review"
  }'
```

### Business Intelligence

#### GET /api/bi/actuary
```bash
curl https://your-app.railway.app/api/bi/actuary \
  -H "Authorization: Bearer <admin_token>"
```

#### GET /api/bi/underwriting
```bash
curl https://your-app.railway.app/api/bi/underwriting \
  -H "Authorization: Bearer <underwriter_token>"
```

#### GET /api/bi/accounting
```bash
curl https://your-app.railway.app/api/bi/accounting \
  -H "Authorization: Bearer <accountant_token>"
```

### Admin Endpoints

#### GET /api/audit
```bash
curl "https://your-app.railway.app/api/audit?page=1&page_size=50" \
  -H "Authorization: Bearer <admin_token>"
```

#### GET /api/security/threats
```bash
curl https://your-app.railway.app/api/security/threats \
  -H "Authorization: Bearer <admin_token>"
```

---

## Security Configuration

### Built-in Security Features

#### 1. Rate Limiting
- **Limit:** 60 requests per minute per IP
- **Response:** HTTP 429 Too Many Requests
- **Retry-After:** 60 seconds

#### 2. Input Validation
- SQL injection detection and blocking
- XSS prevention
- Path traversal blocking
- Command injection detection
- Malicious payload detection

#### 3. Session Management
- Token-based authentication (phins_* prefix)
- Session timeout: 3600 seconds (1 hour)
- Secure password hashing (PBKDF2)
- Failed login tracking (5 attempts → 15 min lockout)

#### 4. Security Headers
```
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
X-XSS-Protection: 1; mode=block
Strict-Transport-Security: max-age=31536000; includeSubDomains
Content-Security-Policy: default-src 'self'; script-src 'self' 'unsafe-inline'
```

#### 5. IP Blocking
- Automatic blocking after malicious attempts
- Temporary blocks (24 hours)
- Permanent blocks after 10+ violations

### Best Practices

1. **Use HTTPS in Production**
   - Railway provides HTTPS by default
   - Never expose plain HTTP endpoints

2. **Rotate Credentials Regularly**
   - Change admin password after deployment
   - Update default user passwords

3. **Monitor Security Alerts**
   ```bash
   # Check security threats
   curl https://your-app.railway.app/api/security/threats \
     -H "Authorization: Bearer <admin_token>"
   ```

4. **Enable Audit Logging**
   ```bash
   # Review audit logs regularly
   curl "https://your-app.railway.app/api/audit?page=1" \
     -H "Authorization: Bearer <admin_token>"
   ```

5. **Limit Admin Access**
   - Use role-based access control
   - Grant minimum necessary permissions

---

## Performance Tuning

### Railway Configuration

#### Resource Allocation
```json
{
  "deploy": {
    "startCommand": "python3 web_portal/server.py",
    "restartPolicyType": "ON_FAILURE",
    "restartPolicyMaxRetries": 10
  }
}
```

### Optimization Tips

#### 1. Connection Pooling
```python
# In web_portal/server.py
CONNECTION_TIMEOUT = 30
MAX_SESSIONS_PER_IP = 10
```

#### 2. Cleanup Intervals
```python
CLEANUP_INTERVAL = 300  # 5 minutes
```

#### 3. Pagination Defaults
```python
DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 100
```

### Performance Monitoring

#### Response Time Targets
- **/api/metrics**: < 100ms
- **/api/login**: < 200ms
- **/api/policies/create**: < 300ms
- **/api/claims/approve**: < 200ms

#### Memory Usage
- Typical: 100-200MB
- Peak: < 500MB

---

## Monitoring Setup

### Railway Built-in Monitoring

#### View Logs
```bash
railway logs
# or
railway logs --follow
```

#### Check Deployment Status
```bash
railway status
```

### Custom Monitoring

#### Health Check Cron
Set up a cron job to run health checks:
```bash
# crontab -e
*/5 * * * * python3 /path/to/railway_health_check.py https://your-app.railway.app
```

#### Metrics Collection
```bash
# Collect metrics every hour
0 * * * * curl https://your-app.railway.app/api/metrics >> /var/log/phins-metrics.log
```

### Alerts and Notifications

#### Railway Webhooks
Configure webhooks in Railway dashboard for:
- Deployment failures
- Application crashes
- Resource limits exceeded

---

## Troubleshooting Guide

### Common Issues

#### 1. Server Won't Start
**Symptoms:** Deployment fails, "Application crashed" error

**Solutions:**
```bash
# Check logs
railway logs

# Verify Python version
python3 --version  # Should be 3.11+

# Test locally
python3 web_portal/server.py

# Check requirements
pip install -r requirements.txt
```

#### 2. 404 Errors on All Endpoints
**Symptoms:** All API calls return 404

**Solutions:**
- Verify deployment completed successfully
- Check Railway domain is correct
- Ensure `startCommand` in railway.json is correct
- Test with `/api/metrics` first (simplest endpoint)

#### 3. 500 Internal Server Error
**Symptoms:** Server responds but returns 500

**Solutions:**
```bash
# Check server logs
railway logs

# Look for Python exceptions
# Common causes:
# - Missing dependencies
# - Import errors
# - Database connection issues
```

#### 4. Rate Limiting Too Aggressive
**Symptoms:** Getting 429 errors frequently

**Solutions:**
```python
# In web_portal/server.py, adjust:
MAX_REQUESTS_PER_MINUTE = 120  # Increase from 60
```

#### 5. Authentication Issues
**Symptoms:** Login returns 401, tokens don't work

**Solutions:**
- Verify credentials are correct
- Check token format (should start with "phins_")
- Verify session hasn't expired (1 hour timeout)
- Check for IP blocking:
  ```bash
  curl https://your-app.railway.app/api/security/threats \
    -H "Authorization: Bearer <admin_token>"
  ```

#### 6. Slow Performance
**Symptoms:** Requests take > 1 second

**Solutions:**
- Check Railway resource usage
- Increase memory allocation if needed
- Review cleanup interval settings
- Monitor with:
  ```bash
  railway logs | grep "seconds"
  ```

### Debug Mode

#### Enable Verbose Logging
```bash
# Set in Railway environment variables
PYTHONUNBUFFERED=1
DEBUG=true
```

#### Test Locally with Production Settings
```bash
PORT=8000 python3 web_portal/server.py
```

### Getting Help

#### Railway Support
- Dashboard: https://railway.app
- Discord: https://discord.gg/railway
- Docs: https://docs.railway.app

#### PHINS Support
- GitHub Issues: https://github.com/ashuryasaf/phins/issues
- Documentation: Check README.md and other docs

---

## Appendix

### Default User Accounts

| Username | Password | Role |
|----------|----------|------|
| admin | admin123 | admin |
| underwriter | under123 | underwriter |
| claims_adjuster | claims123 | claims |
| accountant | acct123 | accountant |

**⚠️ IMPORTANT:** Change these passwords immediately after deployment!

### File Structure
```
phins/
├── web_portal/
│   ├── server.py              # Main server file
│   ├── connectors.py          # External service connectors
│   └── static/                # Static files
├── tests/
│   ├── test_e2e_insurance_pipeline.py
│   ├── test_api_integration.py
│   ├── test_security_performance.py
│   ├── test_smoke_critical_paths.py
│   └── test_data_persistence.py
├── railway.json               # Railway configuration
├── Dockerfile                 # Container configuration
├── requirements.txt           # Python dependencies
├── railway_health_check.py    # Health check script
├── validate_railway_config.py # Config validator
├── deploy_railway_verified.sh # Deployment script
└── test_all_pipelines.sh     # Test runner
```

### Additional Resources
- [Railway Documentation](https://docs.railway.app)
- [Python HTTP Server](https://docs.python.org/3/library/http.server.html)
- [PHINS GitHub Repository](https://github.com/ashuryasaf/phins)

---

**Last Updated:** 2024-12-14
**Version:** 1.0.0
**Author:** PHINS Development Team
