# PHINS Secure Billing System Documentation

## Overview

The PHINS Billing System is a comprehensive, secure payment processing solution with fraud detection, PCI compliance patterns, and transaction monitoring capabilities.

## ✅ Security Features Implemented

### 1. Password Security
- **PBKDF2-HMAC-SHA256** hashing with 100,000 iterations
- Unique salt per password (32-character hex)
- Constant-time comparison to prevent timing attacks
- No plain-text password storage

### 2. Session Management
- Secure token generation using `secrets.token_urlsafe()`
- 24-hour session expiration
- Token invalidation on logout (when implemented)

### 3. Payment Card Security (PCI Compliance Patterns)
- **Luhn Algorithm** validation for card numbers
- CVV format validation (3 or 4 digits)
- Expiry date validation
- **Card number masking** (only last 4 digits shown)
- Payment tokenization (simulated - use Stripe/Square in production)

### 4. Fraud Detection
- Multiple failed payment attempts (3+ triggers alert)
- Unusual transaction frequency detection (5+ in 1 hour)
- Large transaction amount monitoring ($10,000+ flagged)
- Suspicious activity severity levels (low/medium/high)

### 5. Transaction Limits
- Single transaction maximum: $50,000
- Configurable limits per customer/policy
- Refund amount validation

## 📁 File Structure

```
phins/
├── billing_engine.py                  # Core billing logic
├── web_portal/
│   ├── server.py                      # Enhanced with billing API endpoints
│   └── static/
│       ├── billing.html               # Admin billing dashboard
│       └── billing.js                 # Billing UI logic
└── tests/
    └── test_billing_engine.py         # Comprehensive test suite (22 tests)
```

## 🔌 API Endpoints

### 1. Add Payment Method
**POST** `/api/billing/payment-method`

```json
{
  "customer_id": "CUST-12345",
  "card_number": "4532015112830366",
  "cvv": "123",
  "expiry_month": "12",
  "expiry_year": "2026",
  "card_type": "visa",
  "billing_address": {
    "street": "123 Main St",
    "city": "Boston",
    "state": "MA",
    "zip": "02101"
  }
}
```

**Response:**
```json
{
  "success": true,
  "token": "pm_365dbc6409bce01bda48a3c549b03ee8",
  "masked_card": "****-****-****-0366"
}
```

### 2. Process Payment/Charge
**POST** `/api/billing/charge`

```json
{
  "customer_id": "CUST-12345",
  "policy_id": "POL-20251212-1234",
  "amount": 250.00,
  "payment_token": "pm_365dbc6409bce01bda48a3c549b03ee8",
  "metadata": {
    "type": "monthly_premium",
    "month": "December"
  }
}
```

**Response:**
```json
{
  "success": true,
  "transaction_id": "TXN-20251212-fb29d87b604819f3",
  "amount": 250.0,
  "status": "success",
  "receipt_url": "/receipts/TXN-20251212-fb29d87b604819f3"
}
```

**Fraud Detection Response:**
```json
{
  "success": false,
  "transaction_id": "TXN-20251212-abc123",
  "error": "Transaction flagged for review",
  "requires_verification": true
}
```

### 3. Get Billing History
**POST** `/api/billing/history`

```json
{
  "customer_id": "CUST-12345"
}
```

**Response:**
```json
{
  "transactions": [
    {
      "transaction_id": "TXN-20251212-123",
      "amount": 250.00,
      "status": "success",
      "timestamp": "2025-12-12T15:30:00",
      "payment_method": "****-****-****-0366"
    }
  ]
}
```

### 4. Get Billing Statement
**POST** `/api/billing/statement`

```json
{
  "customer_id": "CUST-12345",
  "start_date": "2025-01-01T00:00:00",
  "end_date": "2025-12-31T23:59:59"
}
```

**Response:**
```json
{
  "customer_id": "CUST-12345",
  "period": {
    "start": "2025-01-01T00:00:00",
    "end": "2025-12-31T23:59:59"
  },
  "summary": {
    "total_transactions": 12,
    "successful_payments": 11,
    "failed_payments": 1,
    "total_amount_paid": 2750.00,
    "total_amount_failed": 250.00
  },
  "transactions": [...]
}
```

### 5. Process Refund
**POST** `/api/billing/refund`

```json
{
  "transaction_id": "TXN-20251212-123",
  "amount": 250.00,
  "reason": "Customer request"
}
```

**Response:**
```json
{
  "success": true,
  "refund_id": "RFD-20251212-abc123",
  "amount": 250.00,
  "status": "completed"
}
```

### 6. Get Fraud Alerts (Admin Only)
**POST** `/api/billing/fraud-alerts`

```json
{
  "severity": "high",
  "status": "flagged"
}
```

**Response:**
```json
{
  "alerts": [
    {
      "customer_id": "CUST-67890",
      "transaction_id": "TXN-20251212-xyz",
      "reason": "Multiple failed payment attempts",
      "severity": "high",
      "timestamp": "2025-12-12T15:45:00",
      "status": "flagged"
    }
  ]
}
```

### 7. Get Payment Methods
**POST** `/api/billing/payment-methods`

```json
{
  "customer_id": "CUST-12345"
}
```

**Response:**
```json
{
  "payment_methods": [
    {
      "token": "pm_abc123",
      "masked_card": "****-****-****-0366",
      "card_type": "visa",
      "expiry": "12/2026",
      "is_default": true,
      "created_date": "2025-12-12T10:00:00"
    }
  ]
}
```

## 🎨 Admin Billing Dashboard

Access: http://localhost:8000/billing.html

### Features:
1. **Real-time Statistics**
   - Total transactions
   - Success/failure rates
   - Total revenue
   - Active fraud alerts

2. **Fraud Alert Monitoring**
   - Color-coded severity levels
   - Alert details and timestamps
   - Resolution tracking

3. **Transaction Management**
   - View recent transactions
   - Process refunds
   - Transaction details

4. **Payment Processing**
   - Process new payments
   - Card validation
   - Customer lookup

5. **Customer Billing Lookup**
   - Full billing statement
   - Transaction history
   - Payment summary

## 🧪 Test Coverage

**22 comprehensive tests** covering:

### Security Tests (8 tests)
- Password hashing and verification
- Card number validation (Luhn algorithm)
- CVV validation
- Expiry date validation
- Card masking
- Fraud detection

### Payment Processing Tests (9 tests)
- Valid payment methods
- Invalid card detection
- Expired card detection
- Successful payments
- Negative amount rejection
- Transaction limit enforcement
- Refund processing
- Partial refunds
- Refund validation

### Data Management Tests (5 tests)
- Transaction history
- Billing statements
- Payment method storage
- Payment method removal
- Customer transaction queries

Run tests:
```bash
pytest tests/test_billing_engine.py -v
```

## 🔒 Production Deployment Considerations

### 1. Replace In-Memory Storage
```python
# Use proper database (PostgreSQL, MySQL)
from sqlalchemy import create_engine
engine = create_engine('postgresql://user:pass@localhost/phins')
```

### 2. Use Real Payment Gateway
```python
# Example: Stripe integration
import stripe
stripe.api_key = os.environ['STRIPE_SECRET_KEY']

payment_intent = stripe.PaymentIntent.create(
    amount=25000,  # $250.00
    currency='usd',
    customer=customer_id
)
```

### 3. Add Environment Variables
```bash
export PHINS_SECRET_KEY="your-secret-key"
export STRIPE_API_KEY="sk_live_..."
export DATABASE_URL="postgresql://..."
```

### 4. Enable HTTPS
```python
# Use proper WSGI server with SSL
gunicorn -w 4 -b 0.0.0.0:443 \
  --certfile=/path/to/cert.pem \
  --keyfile=/path/to/key.pem \
  web_portal.server:app
```

### 5. Add Rate Limiting
```python
from flask_limiter import Limiter

limiter = Limiter(
    app,
    key_func=lambda: request.headers.get('Authorization'),
    default_limits=["100 per hour"]
)

@app.route('/api/billing/charge', methods=['POST'])
@limiter.limit("10 per minute")
def process_charge():
    ...
```

### 6. Implement Logging
```python
import logging

logging.basicConfig(
    filename='billing.log',
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger.info(f"Payment processed: {transaction_id} - ${amount}")
logger.warning(f"Fraud alert: {customer_id} - {reason}")
```

### 7. Add Webhooks
```python
# Notify external systems of payment events
@app.route('/webhooks/payment-success', methods=['POST'])
def payment_success_webhook():
    # Send to accounting system, CRM, etc.
    pass
```

## 📊 Monitoring Metrics

Track these KPIs:
- Payment success rate
- Average transaction time
- Fraud detection accuracy
- Refund rate
- Failed payment reasons
- Revenue per customer

## 🚨 Fraud Alert Workflow

1. **Detection** → System flags suspicious transaction
2. **Alert** → Appears in admin dashboard
3. **Review** → Admin investigates customer history
4. **Decision** → Approve/reject/request verification
5. **Resolution** → Update alert status
6. **Notification** → Customer notified of decision

## 🔐 PCI DSS Compliance Notes

This implementation demonstrates PCI compliance patterns but is NOT PCI compliant for production:

**To achieve PCI compliance:**
1. Never store full card numbers
2. Use PCI-certified payment gateway (Stripe, Braintree, Adyen)
3. Tokenize all payment data
4. Implement network segmentation
5. Regular security audits
6. Encrypted data transmission (TLS 1.2+)
7. Access control and monitoring
8. Secure development lifecycle

## 📞 Support

For integration questions or security concerns:
- Review test cases in `/tests/test_billing_engine.py`
- Check error logs in billing system
- Contact system administrator

---

**Status:** ✅ Production-ready with proper gateway integration
**Last Updated:** December 12, 2025
**Version:** 1.0.0
