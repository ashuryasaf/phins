# PHINS Admin Access Level Analysis

## Overview
This document analyzes the access control system across all PHINS dashboards and API endpoints.

## User Roles

### 1. Admin (`admin`)
**Full system access** - Can access all dashboards and API endpoints.

**Credentials:**
- Username: `admin`
- Password: `$PHINS_ADMIN_PASSWORD`

**Dashboard Access:**
- ✅ Admin Dashboard (`/admin.html`)
- ✅ Underwriter Dashboard (`/underwriter-dashboard.html`)
- ✅ Claims Adjuster Dashboard (`/claims-adjuster-dashboard.html`)
- ✅ Billing Dashboard (`/billing.html`)
- ✅ Accountant Dashboard (`/accountant-dashboard.html`)
- ✅ Customer Dashboard (`/dashboard.html`)
- ✅ Investments (`/savings-portfolio.html`)
- ✅ Algo Trading (`/algo-trading.html`)

**API Access:**
- ✅ All security monitoring (`/api/security/*`)
- ✅ Audit logs (`/api/audit`)
- ✅ BI Dashboard (`/api/bi/*`)
- ✅ Financial reporting (`/api/financial/*`)
- ✅ Actuarial tables (`/api/admin/actuarial-tables`)
- ✅ User management (`/api/admin/users`)
- ✅ All customer operations
- ✅ Unified balance management

---

### 2. Underwriter (`underwriter`)
**Policy underwriting and risk assessment**

**Credentials:**
- Username: `underwriter`
- Password: `$PHINS_UNDERWRITER_PASSWORD`

**Dashboard Access:**
- ✅ Underwriter Dashboard (`/underwriter-dashboard.html`)
- ⚠️ Limited Admin views

**API Access:**
- ✅ BI Underwriting (`/api/bi/underwriting`)
- ✅ BI Dashboard (`/api/bi/dashboard`)
- ✅ BI Actuary (`/api/bi/actuary`)
- ✅ Financial projections (`/api/financial/customer-projection`)
- ✅ Premium calculator (`/api/financial/premium-calculator`)
- ✅ Market data (`/api/market/*`)
- ✅ Underwriting approve/reject/refer endpoints
- ❌ Security threats
- ❌ Audit logs
- ❌ User management

**Key Functions:**
- Review pending applications
- Approve/Reject/Refer policies
- Assess risk scores
- View underwriting analytics

---

### 3. Claims Adjuster (`claims`)
**Claims processing and payments**

**Credentials:**
- Username: `claims_adjuster`
- Password: `$PHINS_CLAIMS_PASSWORD`

**Dashboard Access:**
- ✅ Claims Adjuster Dashboard (`/claims-adjuster-dashboard.html`)

**API Access:**
- ✅ Financial dashboard summary (`/api/financial/dashboard-summary`)
- ✅ Market data (`/api/market/*`)
- ✅ Claims approve/reject/pay endpoints
- ✅ Claims payments (`/api/billing/pay-claim`)
- ❌ Security threats
- ❌ Audit logs
- ❌ BI analytics
- ❌ User management

**Key Functions:**
- Review pending claims
- Approve/Reject claims
- Process claim payments
- View claims analytics

---

### 4. Accountant (`accountant`)
**Financial management and billing**

**Credentials:**
- Username: `accountant`
- Password: `$PHINS_ACCOUNTANT_PASSWORD`

**Dashboard Access:**
- ✅ Billing Dashboard (`/billing.html`)
- ✅ Accountant Dashboard (`/accountant-dashboard.html`)

**API Access:**
- ✅ BI Dashboard (`/api/bi/dashboard`)
- ✅ BI Actuary (`/api/bi/actuary`)
- ✅ BI Accounting (`/api/bi/accounting`)
- ✅ Financial portfolio report (`/api/financial/portfolio-report`)
- ✅ Financial forecast (`/api/financial/forecast`)
- ✅ Data integrity (`/api/financial/data-integrity`)
- ✅ Premium calculator (`/api/financial/premium-calculator`)
- ✅ Market data (`/api/market/*`)
- ✅ Billing endpoints (`/api/billing/*`)
- ✅ Metric endpoints (`/api/metrics/*`)
- ❌ Security threats
- ❌ Audit logs (admin only)
- ❌ User management

**Key Functions:**
- View billing metrics
- Process payments
- Financial reporting
- Revenue analytics
- Fraud detection

---

### 5. Customer (`customer`)
**Policy holder portal access**

**Credentials:**
- Registered customer email + password
- Default: `asaf@assurance.co.il` / `customer123`

**Dashboard Access:**
- ✅ Customer Dashboard (`/dashboard.html`)
- ✅ Investments (`/savings-portfolio.html`)
- ✅ Algo Trading (`/algo-trading.html`)

**API Access:**
- ✅ Own policies (`/api/policies?customer_id=...`)
- ✅ Own claims (`/api/claims?customer_id=...`)
- ✅ Health wallet (`/api/health-wallet/*`)
- ✅ Savings & investments (`/api/savings/*`)
- ✅ Algo trading (`/api/algo/*`)
- ✅ Unified balance (`/api/balance/*`)
- ✅ NFT ledger (`/api/nft/*`)
- ✅ Financial dashboard summary (`/api/financial/dashboard-summary`)
- ✅ Premium calculator (`/api/financial/premium-calculator`)
- ✅ Market data (`/api/market/*`)
- ❌ Admin functions
- ❌ Other customers' data
- ❌ BI analytics

**Key Functions:**
- View own policies
- File claims
- Manage health wallet
- Investment portfolio
- Algo trading
- Billing & payments

---

## API Endpoint Authorization Matrix

| Endpoint Category | Admin | Underwriter | Claims | Accountant | Customer |
|-------------------|-------|-------------|--------|------------|----------|
| `/api/security/*` | ✅ | ❌ | ❌ | ❌ | ❌ |
| `/api/audit` | ✅ | ❌ | ❌ | ❌ | ❌ |
| `/api/admin/*` | ✅ | ❌ | ❌ | ❌ | ❌ |
| `/api/bi/dashboard` | ✅ | ✅ | ❌ | ✅ | ❌ |
| `/api/bi/underwriting` | ✅ | ✅ | ❌ | ❌ | ❌ |
| `/api/bi/accounting` | ✅ | ❌ | ❌ | ✅ | ❌ |
| `/api/bi/actuary` | ✅ | ✅ | ❌ | ✅ | ❌ |
| `/api/financial/portfolio-report` | ✅ | ❌ | ❌ | ✅ | ❌ |
| `/api/financial/forecast` | ✅ | ❌ | ❌ | ✅ | ❌ |
| `/api/financial/dashboard-summary` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `/api/financial/premium-calculator` | ✅ | ✅ | ❌ | ✅ | ✅ |
| `/api/underwriting/*` | ✅ | ✅ | ❌ | ❌ | ❌ |
| `/api/claims/*` | ✅ | ❌ | ✅ | ❌ | ✅* |
| `/api/billing/*` | ✅ | ❌ | ✅ | ✅ | ✅* |
| `/api/policies/*` | ✅ | ✅ | ❌ | ✅ | ✅* |
| `/api/market/*` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `/api/savings/*` | ✅ | ❌ | ❌ | ✅ | ✅* |
| `/api/algo/*` | ✅ | ❌ | ❌ | ✅ | ✅* |
| `/api/balance/*` | ✅ | ❌ | ❌ | ✅ | ✅* |
| `/api/health-wallet/*` | ✅ | ❌ | ❌ | ✅ | ✅* |

*\* Customer access limited to own data only*

---

## Security Features

### Authentication
- **Password Hashing**: SHA-256 with random salt
- **Session Management**: Secure tokens with 2-hour expiry
- **Login Lockout**: 5 failed attempts → 5 minute lockout

### Rate Limiting
- **Global**: 100 requests per minute per IP
- **Login**: Additional stricter limits

### Input Validation
- SQL injection prevention
- XSS protection via sanitization
- Request size limits (1MB max)

### Audit Logging
- All admin actions logged
- Underwriting decisions logged
- Claims actions logged
- All financial transactions logged on NFT & Transaction ledgers

---

## Recommendations

### Current Strengths ✅
1. Role-based access control (RBAC) implemented
2. Session-based authentication
3. Comprehensive audit logging
4. Ledger-based transaction recording (NFT + Transaction)
5. Rate limiting and lockout protection

### Potential Improvements ⚠️
1. Add 2FA for admin accounts
2. Implement JWT tokens for stateless authentication
3. Add API key support for service-to-service calls
4. Implement IP whitelisting for admin endpoints
5. Add session invalidation on password change
6. Consider role hierarchy (e.g., admin inherits all permissions)

---

## Dashboard Access Summary

| Dashboard | File | Required Role(s) |
|-----------|------|------------------|
| Admin Overview | `/admin.html` | admin |
| Underwriting | `/underwriter-dashboard.html` | admin, underwriter |
| Claims | `/claims-adjuster-dashboard.html` | admin, claims |
| Billing | `/billing.html` | admin, accountant |
| Accounting | `/accountant-dashboard.html` | admin, accountant |
| Customer Portal | `/dashboard.html` | customer (own data) |
| Investments | `/savings-portfolio.html` | customer (own data) |
| Algo Trading | `/algo-trading.html` | customer (own data) |

---

*Generated: December 30, 2025*
*PHINS Platform v2.0*
