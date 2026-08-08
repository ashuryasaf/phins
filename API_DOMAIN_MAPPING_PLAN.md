# PHINS Platform - API & Domain Connection Mapping Plan

## Executive Summary

This document provides a comprehensive mapping of all API connections, external service integrations, and domain validation requirements for the PHINS Insurance Management Platform. The goal is to enable production deployment with all external services properly connected.

**Status**: Ready for Review - DO NOT DEPLOY until confirmed

---

## Table of Contents

1. [Current Architecture Overview](#1-current-architecture-overview)
2. [Service Status Matrix](#2-service-status-matrix)
3. [External API Integrations](#3-external-api-integrations)
4. [Domain Validation Checklist](#4-domain-validation-checklist)
5. [Environment Variables Required](#5-environment-variables-required)
6. [Implementation Roadmap](#6-implementation-roadmap)
7. [Testing & Validation Plan](#7-testing--validation-plan)

---

## 1. Current Architecture Overview

### UML Component Structure (from `docs/uml/phins_platform_overview.puml`)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           PHINS PLATFORM                                     │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   PRESENTATION LAYER                                                        │
│   ├── Client Portal UI     - Customer self-service                         │
│   ├── Supplier Portal UI   - Supplier management                           │
│   ├── Admin Portal UI      - Admin operations                              │
│   ├── Actuary UI           - Actuarial tables & simulations                │
│   ├── Investment UI        - Portfolio management                          │
│   └── Banking/Custody UI   - Custody operations                            │
│                                                                             │
│   API / GATEWAY LAYER                                                       │
│   ├── REST API (Flask)     - web_portal/server.py                         │
│   └── AuthN/AuthZ Service  - Session-based authentication                  │
│                                                                             │
│   CORE SERVICES (services/)                                                 │
│   ├── Notification Service     ✅ Implemented (needs providers)            │
│   ├── OTP Security Service     ✅ Implemented (needs SMS/Email)            │
│   ├── Billing Service          ✅ Implemented                              │
│   ├── Payment Gateway Service  ✅ Implemented (sandbox mode)               │
│   ├── Actuarial Service        ✅ Implemented                              │
│   ├── Market Data Service      ✅ Implemented (CoinGecko/Stooq)            │
│   ├── Claims Service           ✅ Implemented                              │
│   ├── Underwriting Service     ✅ Implemented                              │
│   ├── Policy Service           ✅ Implemented                              │
│   └── Audit Service            ✅ Implemented                              │
│                                                                             │
│   DATA LAYER                                                                │
│   ├── PostgreSQL (prod)    - Primary database                              │
│   ├── SQLite (dev)         - Development database                          │
│   └── Repository Pattern   - Data access abstraction                       │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Service Status Matrix

### Core Services

| Service | File | Status | External Dependencies | Production Ready |
|---------|------|--------|----------------------|------------------|
| **Notification Service** | `services/notification_service.py` | ✅ Implemented | SMTP, SendGrid, AWS SES, Twilio | ⚠️ Needs Providers |
| **OTP Security Service** | `services/otp_security_service.py` | ✅ Implemented | hCaptcha, reCAPTCHA | ⚠️ Needs Providers |
| **Billing Service** | `services/billing_service.py` | ✅ Implemented | None | ✅ Ready |
| **Payment Gateway** | `services/payment_gateway_service.py` | ✅ Implemented | Stripe, PayPal, Crypto | ⚠️ Sandbox Only |
| **Actuarial Service** | `services/actuarial_service.py` | ✅ Implemented | None (internal) | ✅ Ready |
| **Market Data Service** | `services/market_data_service.py` | ✅ Implemented | CoinGecko, Stooq | ✅ Ready (free APIs) |
| **Claims Service** | `services/claims_service.py` | ✅ Implemented | None | ✅ Ready |
| **Underwriting Service** | `services/underwriting_service.py` | ✅ Implemented | None | ✅ Ready |
| **Policy Service** | `services/policy_service.py` | ✅ Implemented | None | ✅ Ready |
| **Audit Service** | `services/audit_service.py` | ✅ Implemented | None | ✅ Ready |

### Supporting Services

| Service | File | Status | External Dependencies | Production Ready |
|---------|------|--------|----------------------|------------------|
| **Reinsurance Service** | `services/reinsurance_service.py` | ✅ Implemented | None | ✅ Ready |
| **Investment Portfolio** | `services/investment_portfolio_service.py` | ✅ Implemented | Market Data | ✅ Ready |
| **Financial Reporting** | `services/financial_reporting_service.py` | ✅ Implemented | None | ✅ Ready |
| **Data Integrity** | `services/data_integrity_service.py` | ✅ Implemented | None | ✅ Ready |
| **Supplier Management** | `services/supplier_management_service.py` | ✅ Implemented | None | ✅ Ready |

---

## 3. External API Integrations

### 3.1 Email Services (Pick ONE)

#### Option A: SMTP (Self-hosted or Provider)
```
Provider: Any SMTP server (Gmail, Office365, Mailgun, etc.)
Status: ✅ Provider implemented
Config Required:
  - SMTP_HOST
  - SMTP_PORT
  - SMTP_USERNAME
  - SMTP_PASSWORD
  - SMTP_USE_TLS
  - EMAIL_FROM_ADDRESS
  - EMAIL_FROM_NAME
```

#### Option B: SendGrid
```
Provider: SendGrid (https://sendgrid.com)
Status: ✅ Provider implemented
Config Required:
  - SENDGRID_API_KEY
  - EMAIL_FROM_ADDRESS
Pricing: Free tier: 100 emails/day
```

#### Option C: AWS SES
```
Provider: Amazon Simple Email Service
Status: ✅ Provider implemented
Config Required:
  - AWS_ACCESS_KEY_ID
  - AWS_SECRET_ACCESS_KEY
  - AWS_SES_REGION
  - EMAIL_FROM_ADDRESS (must be verified)
Pricing: $0.10 per 1,000 emails
```

### 3.2 SMS/OTP Services (Pick ONE)

#### Option A: Twilio (Recommended)
```
Provider: Twilio (https://www.twilio.com)
Status: ✅ Provider implemented
Config Required:
  - TWILIO_ACCOUNT_SID
  - TWILIO_AUTH_TOKEN
  - TWILIO_FROM_NUMBER
Pricing: ~$0.0075 per SMS
Test Mode: Uses mock provider when credentials absent
```

#### Option B: AWS SNS
```
Provider: Amazon SNS
Status: ✅ Provider implemented
Config Required:
  - AWS_ACCESS_KEY_ID
  - AWS_SECRET_ACCESS_KEY
  - AWS_SNS_REGION
Pricing: $0.00645 per SMS (US)
```

#### Option C: Vonage (Nexmo)
```
Provider: Vonage (https://www.vonage.com)
Status: ✅ Provider implemented
Config Required:
  - VONAGE_API_KEY
  - VONAGE_API_SECRET
Pricing: ~$0.0078 per SMS
```

### 3.3 CAPTCHA Services (Pick ONE)

#### Option A: Simple CAPTCHA (Built-in)
```
Provider: Built-in math/text challenges
Status: ✅ Fully implemented
Config: CAPTCHA_TYPE=simple
Pricing: Free
Note: Basic protection, suitable for low-risk applications
```

#### Option B: hCaptcha (Recommended for privacy)
```
Provider: hCaptcha (https://www.hcaptcha.com)
Status: ✅ Verification implemented
Config Required:
  - HCAPTCHA_SECRET
  - HCAPTCHA_SITE_KEY
  - CAPTCHA_TYPE=hcaptcha
Pricing: Free tier available
```

#### Option C: Google reCAPTCHA
```
Provider: Google reCAPTCHA (https://www.google.com/recaptcha)
Status: ✅ Verification implemented
Config Required:
  - RECAPTCHA_SECRET
  - RECAPTCHA_SITE_KEY
  - CAPTCHA_TYPE=recaptcha
Pricing: Free for most use cases
```

### 3.4 Payment Gateways

#### Stripe (Credit Cards, Apple Pay, Google Pay)
```
Provider: Stripe (https://stripe.com)
Status: ✅ Test mode implemented
Config Required:
  - STRIPE_API_KEY (sk_live_xxx for production)
Test Cards:
  - Success: 4242424242424242
  - Decline: 4000000000000002
  - Insufficient: 4000000000009995
Pricing: 2.9% + $0.30 per transaction
```

#### PayPal
```
Provider: PayPal (https://www.paypal.com)
Status: ✅ Sandbox implemented
Config Required:
  - PAYPAL_CLIENT_ID
  - PAYPAL_CLIENT_SECRET
  - PAYPAL_SANDBOX=false (for production)
Pricing: 2.9% + $0.30 per transaction
```

#### Cryptocurrency
```
Provider: Built-in (CoinGecko for rates)
Status: ✅ Testnet implemented
Supported: BTC, ETH, USDC
Config Required:
  - Production wallet addresses
  - Blockchain node access (optional)
Note: Currently testnet only, needs mainnet config for production
```

### 3.5 Market Data APIs (Free)

#### CoinGecko (Crypto Prices)
```
Provider: CoinGecko (https://www.coingecko.com)
Status: ✅ Fully implemented
Config: None required (free API)
Rate Limit: 10-50 calls/minute
Supported: BTC, ETH, USDT, USDC, SOL, BNB, XRP, ADA, DOGE
```

#### Stooq (Index Quotes)
```
Provider: Stooq (https://stooq.com)
Status: ✅ Fully implemented
Config: None required (free API)
Supported: ^SPX (S&P 500), ^NDQ (NASDAQ), ^DJI (Dow Jones)
```

### 3.6 Database

#### PostgreSQL (Production)
```
Provider: Any PostgreSQL 12+ host
Status: ✅ Fully supported
Config Required:
  - DATABASE_URL=postgresql://<user>:<password>@<host>:5432/<dbname>
  - USE_DATABASE=1
Connection Pool: 20 connections + 10 overflow
```

#### SQLite (Development)
```
Provider: Local file
Status: ✅ Fully supported
Config Required:
  - USE_DATABASE=1
  - USE_SQLITE=1
File: phins.db in workspace root
```

---

## 4. Domain Validation Checklist

### 4.1 DNS & Domain Setup

| Task | Status | Notes |
|------|--------|-------|
| Domain registered (phins.ai) | ✅ Done | |
| DNS A record pointing to server | ⬜ Verify | |
| SSL/TLS certificate installed | ⬜ Verify | Use Let's Encrypt or provider cert |
| SPF record for email | ⬜ Required | For email deliverability |
| DKIM record for email | ⬜ Required | For email authentication |
| DMARC record for email | ⬜ Recommended | For email security |

### 4.2 Application Configuration

| Task | Status | Notes |
|------|--------|-------|
| SECRET_KEY set (random, long) | ⬜ Required | Session encryption |
| VAULT_KEY set (for actuarial data) | ⬜ Required | Data encryption |
| Production database URL | ⬜ Required | PostgreSQL connection |
| Email provider configured | ⬜ Required | One of: SMTP, SendGrid, SES |
| SMS provider configured | ⬜ Required | One of: Twilio, SNS, Vonage |

### 4.3 Security Validation

| Task | Status | Notes |
|------|--------|-------|
| Rate limiting enabled | ✅ Implemented | In-process, move to Redis for scale |
| CAPTCHA enabled | ✅ Implemented | For registration/login |
| Session timeout configured | ✅ Implemented | 30 minutes default |
| Audit logging enabled | ✅ Implemented | Full audit trail |
| CORS configured | ⬜ Verify | For API access |

### 4.4 External Service Testing

| Service | Test Endpoint | Expected Result |
|---------|--------------|-----------------|
| Database | `GET /api/diagnostics/db-test` | `{"database":"connected"}` |
| Email | Manual test send | Email delivered |
| SMS | Manual test send | SMS delivered |
| Stripe | `POST /api/payment/process` | Transaction created |
| PayPal | `POST /api/payment/paypal` | Order created |
| Market Data | `GET /api/market/crypto?symbols=BTC` | Price returned |

---

## 5. Environment Variables Required

### Critical (Must Set for Production)

```bash
# ============ DATABASE ============
USE_DATABASE=1
DATABASE_URL=postgresql://<user>:<password>@<host>:5432/phins

# ============ SECURITY ============
SECRET_KEY=<64-character-random-string>
VAULT_KEY=<32-character-encryption-key>
PHINS_ENCRYPTION_KEY=<fernet-key>

# ============ EMAIL (Choose One Provider) ============
# Option A: SMTP
EMAIL_PROVIDER=smtp
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USE_TLS=true
SMTP_USERNAME=your_username
SMTP_PASSWORD=<your_smtp_password>
EMAIL_FROM_ADDRESS=noreply@phins.ai
EMAIL_FROM_NAME=PHINS Insurance

# Option B: SendGrid
EMAIL_PROVIDER=sendgrid
SENDGRID_API_KEY=SG.xxxxx
EMAIL_FROM_ADDRESS=noreply@phins.ai

# ============ SMS (Choose One Provider) ============
# Option A: Twilio (Recommended)
SMS_PROVIDER=twilio
TWILIO_ACCOUNT_SID=ACxxxxx
TWILIO_AUTH_TOKEN=xxxxxx
TWILIO_FROM_NUMBER=+1234567890

# Option B: AWS SNS
SMS_PROVIDER=sns
AWS_ACCESS_KEY_ID=xxxxx
AWS_SECRET_ACCESS_KEY=xxxxx
AWS_SNS_REGION=us-east-1
```

### Optional (Enhance Functionality)

```bash
# ============ CAPTCHA ============
CAPTCHA_ENABLED=true
CAPTCHA_TYPE=simple  # or hcaptcha, recaptcha
HCAPTCHA_SECRET=xxxxx
HCAPTCHA_SITE_KEY=xxxxx
# OR
RECAPTCHA_SECRET=xxxxx
RECAPTCHA_SITE_KEY=xxxxx

# ============ PAYMENT GATEWAYS ============
# Stripe (for credit cards)
STRIPE_API_KEY=sk_live_xxxxx

# PayPal
PAYPAL_CLIENT_ID=xxxxx
PAYPAL_CLIENT_SECRET=xxxxx
PAYPAL_SANDBOX=false

# ============ OTP SETTINGS ============
OTP_LENGTH=6
OTP_EXPIRY_SECONDS=300
OTP_MAX_ATTEMPTS=5

# ============ RATE LIMITING ============
RATE_LIMIT_ENABLED=true
OTP_RATE_LIMIT_PER_MINUTE=3
EMAIL_RATE_LIMIT_PER_MINUTE=10
SMS_RATE_LIMIT_PER_MINUTE=5

# ============ SERVER ============
PORT=5000
PHINS_ENV=production
```

---

## 6. Implementation Roadmap

### Phase 1: Core Services Activation (Priority: Critical)

| Task | Effort | Dependency |
|------|--------|------------|
| 1.1 Configure Email Provider | 1 hour | SMTP/SendGrid/SES credentials |
| 1.2 Configure SMS Provider | 1 hour | Twilio/SNS credentials |
| 1.3 Set Security Keys | 30 min | Generate secrets |
| 1.4 Configure Production Database | 30 min | PostgreSQL URL |

### Phase 2: Payment Integration (Priority: High)

| Task | Effort | Dependency |
|------|--------|------------|
| 2.1 Stripe Live Mode | 1 hour | Stripe account + live keys |
| 2.2 PayPal Live Mode | 1 hour | PayPal business account |
| 2.3 Bank Transfer Integration | 4 hours | Bank API access |

### Phase 3: Enhanced Providers (Priority: Medium) ✅ COMPLETED

| Task | Effort | Dependency | Status |
|------|--------|------------|--------|
| 3.1 Implement SendGrid Provider | 2 hours | SendGrid API key | ✅ Done |
| 3.2 Implement AWS SES Provider | 2 hours | AWS credentials + domain verification | ✅ Done |
| 3.3 Implement Vonage SMS Provider | 2 hours | Vonage API credentials | ✅ Done |
| 3.4 Implement AWS SNS Provider | 2 hours | AWS credentials | ✅ Done |
| 3.5 Implement Mailgun Provider | 2 hours | Mailgun API key | ✅ Done |
| 3.6 Implement MessageBird Provider | 2 hours | MessageBird API key | ✅ Done |

### Phase 4: Scalability (Priority: Medium)

| Task | Effort | Dependency |
|------|--------|------------|
| 4.1 Move Sessions to Redis/DB | 4 hours | Redis instance or use existing DB |
| 4.2 Move Rate Limits to Redis | 2 hours | Redis instance |
| 4.3 Configure CDN for Static Assets | 2 hours | CDN provider |

### Phase 5: Advanced Features (Priority: Low)

| Task | Effort | Dependency |
|------|--------|------------|
| 5.1 Webhook Notifications | 4 hours | None |
| 5.2 Push Notifications | 8 hours | Firebase/APNS |
| 5.3 WhatsApp Integration | 4 hours | WhatsApp Business API |

---

## 7. Testing & Validation Plan

### 7.1 Pre-Deployment Checklist

```bash
# 1. Run database connection test
curl https://phins.ai/api/diagnostics/db-test

# 2. Run health check
curl https://phins.ai/api/health

# 3. Test email delivery (internal endpoint)
# Configure email, then test notification service

# 4. Test SMS delivery (internal endpoint)
# Configure SMS, then test OTP service

# 5. Run full test suite
pytest tests/ -v
```

### 7.2 Integration Test Scenarios

| Scenario | Steps | Expected Result |
|----------|-------|-----------------|
| Customer Registration | 1. Submit registration 2. Receive OTP email 3. Verify OTP | Account created, verified |
| Login with OTP | 1. Submit credentials 2. Receive OTP 3. Verify OTP | Session created |
| Bill Payment | 1. View bill 2. Process payment 3. Confirm receipt | Bill status = paid |
| Policy Application | 1. Submit application 2. Underwriting review 3. Approval | Policy created |
| Claim Filing | 1. File claim 2. Adjuster review 3. Approval | Claim paid |

### 7.3 Load Testing Recommendations

```bash
# Use Apache Bench or similar
# Test concurrent users
ab -n 1000 -c 100 https://phins.ai/api/health

# Expected: 
# - 95% requests < 500ms
# - 0 errors under normal load
```

---

## 8. API Endpoint Summary

### Authentication & Session
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/login` | User authentication |
| POST | `/api/logout` | End session |
| GET | `/api/session/validate` | Validate session token |
| POST | `/api/customer/register` | Customer registration |

### Customer Portal
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/customer/status` | Get customer status |
| GET | `/api/customer/summary` | Get account summary |
| GET | `/api/customer/allocation` | Get premium allocation |
| GET | `/api/policies` | List customer policies |
| GET | `/api/claims` | List customer claims |
| GET | `/api/billing` | List customer bills |

### Billing & Payments
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/billing` | List bills |
| POST | `/api/billing/pay` | Record payment |
| GET | `/api/billing/projections` | Get billing forecast |
| GET | `/api/payment/methods` | List payment methods |
| POST | `/api/payment/process` | Process payment |

### Actuarial & Risk
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/actuarial/tables` | Get rate tables |
| GET | `/api/actuarial/config` | Get underwriting config |
| POST | `/api/actuarial/simulate` | Run portfolio simulation |
| GET | `/api/risk-assessment/report` | Generate risk report |

### Market Data
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/market/crypto` | Get crypto prices |
| GET | `/api/market/index` | Get index quotes |

### Admin Operations
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/admin/customers` | List all customers |
| GET | `/api/admin/suppliers` | List suppliers |
| GET | `/api/audit` | View audit logs |
| GET | `/api/system/status` | System health status |

---

## 9. Recommended Provider Choices

Based on cost, reliability, and ease of implementation:

### Minimum Viable Production Setup

| Service | Recommended Provider | Monthly Cost (Est.) |
|---------|---------------------|---------------------|
| Email | SMTP (Gmail/Office365) | $0-50 |
| SMS/OTP | Twilio | ~$50-100 |
| CAPTCHA | Simple (built-in) | $0 |
| Payments | Stripe | % per transaction |
| Database | Railway PostgreSQL | ~$5-20 |

### Enterprise Setup

| Service | Recommended Provider | Monthly Cost (Est.) |
|---------|---------------------|---------------------|
| Email | AWS SES + SMTP fallback | ~$10-50 |
| SMS/OTP | Twilio + Vonage fallback | ~$100-500 |
| CAPTCHA | hCaptcha | $0 (free tier) |
| Payments | Stripe + PayPal | % per transaction |
| Database | AWS RDS PostgreSQL | ~$50-200 |
| Cache/Sessions | Redis (ElastiCache) | ~$15-50 |

---

## 10. Next Steps

1. **REVIEW** this document and confirm the selected providers
2. **OBTAIN** credentials for selected services:
   - Email provider API key
   - SMS provider credentials
   - Payment gateway keys (if enabling)
3. **SET** environment variables in deployment environment
4. **TEST** each integration individually before full deployment
5. **CONFIRM** all tests pass before enabling production traffic

---

**Document Version**: 1.0
**Created**: January 28, 2026
**Status**: Ready for Review - DO NOT DEPLOY until confirmed

---

*For questions or issues, refer to the AGENTS.md file for development guidelines.*
