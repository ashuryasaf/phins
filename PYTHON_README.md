# PHINS Insurance Management System - Python Implementation

This directory contains a complete Python implementation of the PHINS Insurance Management System, mirroring the AL (Business Central) architecture.

## Overview

The Python implementation provides:
- **Core Data Models**: Complete data classes for all insurance entities
- **Business Logic**: Management codeunits for policy, claims, billing, and underwriting
- **System Orchestration**: Main PHINS system manager for all operations
- **Enumerations**: Type-safe enums for all statuses and categories

## Files

### `phins_system.py`
Main system implementation containing:
- **Enums**: PolicyStatus, ClaimStatus, BillStatus, UnderwritingStatus, etc.
- **Data Models**: Company, Customer, InsurancePolicy, Claim, Bill, Underwriting, Reinsurance
- **Business Logic**: 
  - `PolicyManagement` - Policy lifecycle management
  - `ClaimsManagement` - Claims processing
  - `BillingManagement` - Billing operations
  - `UnderwritingEngine` - Risk assessment
- **Main System**: `PHINSInsuranceSystem` - Central orchestration

### `demo.py`
Comprehensive demonstration script showing:
- Company management
- Customer registration
- Policy creation and management
- Complete underwriting workflow
- Billing with payment recording
- Claims processing from filing to payment
- Reinsurance arrangements
- Customer portal features
- System reporting

## Installation & Usage

### Prerequisites
```bash
Python 3.8+
```

### Running the Demo

```bash
python demo.py
```

This will execute a complete walkthrough of all PHINS system features.

## Architecture

### Data Model Relationships

```
Company
├── Customers
│   ├── Policies
│   │   ├── Bills
│   │   ├── Claims
│   │   ├── Underwriting
│   │   └── Reinsurance
│   ├── Billing Statements
│   └── Claims History
```

### Main Workflows

#### 1. Policy Sales → Underwriting → Billing
```python
# Create customer
customer = system.register_customer(customer)

# Create policy
policy = system.create_policy(
    customer_id="CUST001",
    policy_type=PolicyType.AUTO,
    premium=1200.00,
    coverage=500000.00,
    deductible=500.00
)

# Initiate underwriting
underwriting = system.initiate_underwriting(policy.policy_id, customer.customer_id)

# Assess and approve
UnderwritingEngine.assess_risk(underwriting, RiskLevel.MEDIUM)
UnderwritingEngine.approve_underwriting(underwriting)

# Create bill
bill = system.create_bill(policy.policy_id, customer.customer_id, policy.premium_amount)
```

#### 2. Claims Processing
```python
# File claim
claim = system.file_claim(
    policy_id=policy.policy_id,
    customer_id=customer.customer_id,
    amount=25000.00,
    description="Vehicle collision damage"
)

# Approve claim
ClaimsManagement.approve_claim(claim, 24500.00)

# Process payment
ClaimsManagement.process_claim_payment(claim)
```

#### 3. Billing & Payment
```python
# Create bill
bill = system.create_bill(policy_id, customer_id, amount)

# Record payment
BillingManagement.record_payment(bill, 600.00, PaymentMethod.BANK_TRANSFER)

# Apply late fee if overdue
BillingManagement.apply_late_fee(bill, late_fee_percentage=5.0)

# Get billing summary
statement = system.get_customer_billing(customer_id)
```

## Key Classes

### PHINSInsuranceSystem
Main orchestrator for all operations:

```python
system = PHINSInsuranceSystem()

# Company operations
system.register_company(company)
company = system.get_company(company_id)

# Customer operations
system.register_customer(customer)
policies = system.get_customer_policies(customer_id)
claims = system.get_customer_claims(customer_id)
billing = system.get_customer_billing(customer_id)

# Policy management
policy = system.create_policy(customer_id, policy_type, premium, coverage, deductible)
system.get_policy(policy_id)

# Claims management
claim = system.file_claim(policy_id, customer_id, amount, description)
system.get_claim(claim_id)

# Billing management
bill = system.create_bill(policy_id, customer_id, amount)
system.get_bill(bill_id)

# Underwriting management
underwriting = system.initiate_underwriting(policy_id, customer_id)
system.get_underwriting(uw_id)

# Reinsurance management
system.create_reinsurance(reinsurance_record)
system.get_reinsurance(reinsurance_id)

# Reporting
summary = system.get_system_summary()
```

### Data Models

#### Customer
```python
customer = Customer(
    customer_id="CUST001",
    first_name="John",
    last_name="Smith",
    email="john@email.com",
    phone="+1-555-0100",
    address="456 Main St",
    city="New York",
    state="NY",
    postal_code="10001",
    country_code="US",
    customer_type=CustomerType.INDIVIDUAL,
    identification_number="123-45-6789",
    portal_access=True
)
```

#### InsurancePolicy
```python
policy = InsurancePolicy(
    policy_id="POL001",
    customer_id="CUST001",
    policy_type=PolicyType.AUTO,
    start_date=datetime.now(),
    end_date=datetime.now() + timedelta(days=365),
    premium_amount=1200.00,
    coverage_amount=500000.00,
    deductible=500.00,
    status=PolicyStatus.ACTIVE,
    underwriting_status=UnderwritingStatus.PENDING,
    payment_frequency=PaymentFrequency.ANNUAL
)
```

#### Claim
```python
claim = Claim(
    claim_id="CLM001",
    policy_id="POL001",
    customer_id="CUST001",
    claim_date=datetime.now(),
    incident_date=datetime.now(),
    description="Vehicle collision damage",
    claim_amount=25000.00,
    status=ClaimStatus.PENDING
)

# Approve and pay
claim.approve(24500.00)
claim.process_payment()
```

#### Bill
```python
bill = Bill(
    bill_id="BILL001",
    policy_id="POL001",
    customer_id="CUST001",
    bill_date=datetime.now(),
    due_date=datetime.now() + timedelta(days=30),
    amount_due=1200.00,
    status=BillStatus.OUTSTANDING
)

# Record payment
bill.record_payment(600.00, PaymentMethod.BANK_TRANSFER)

# Apply late fee
bill.apply_late_fee(5.0)  # 5% late fee
```

## Enumerations

### Status Types
- `PolicyStatus`: ACTIVE, INACTIVE, CANCELLED, LAPSED, SUSPENDED
- `UnderwritingStatus`: PENDING, APPROVED, REJECTED, REFERRED, APPROVED_CONDITIONAL
- `ClaimStatus`: PENDING, UNDER_REVIEW, APPROVED, REJECTED, PAID, CLOSED
- `BillStatus`: OUTSTANDING, PARTIAL, PAID, OVERDUE, CANCELLED

### Classification Types
- `PolicyType`: AUTO, HOME, HEALTH, LIFE, COMMERCIAL, LIABILITY, OTHER
- `CustomerType`: INDIVIDUAL, BUSINESS, CORPORATE
- `PaymentFrequency`: MONTHLY, QUARTERLY, SEMI_ANNUAL, ANNUAL
- `RiskLevel`: LOW, MEDIUM, HIGH, VERY_HIGH
- `ReinsuranceType`: PROPORTIONAL, NON_PROPORTIONAL, EXCESS_OF_LOSS, STOP_LOSS, FACULTATIVE
- `PaymentMethod`: CREDIT_CARD, BANK_TRANSFER, CHEQUE, CASH, ONLINE_PORTAL

## Example: Complete Policy Lifecycle

```python
from phins_system import *

# Initialize system
system = PHINSInsuranceSystem()

# 1. Register customer
customer = Customer(
    customer_id="CUST001",
    first_name="John",
    last_name="Smith",
    # ... other fields
)
system.register_customer(customer)

# 2. Create policy
policy = system.create_policy(
    customer_id="CUST001",
    policy_type=PolicyType.AUTO,
    premium=1200.00,
    coverage=500000.00,
    deductible=500.00
)

# 3. Underwriting
underwriting = system.initiate_underwriting(policy.policy_id, customer.customer_id)
UnderwritingEngine.assess_risk(underwriting, RiskLevel.MEDIUM)
UnderwritingEngine.approve_underwriting(underwriting, premium_adjustment=0.0)

# 4. Create bill
bill = system.create_bill(policy.policy_id, customer.customer_id, policy.premium_amount)

# 5. Customer makes payment
BillingManagement.record_payment(bill, policy.premium_amount, PaymentMethod.ONLINE_PORTAL)

# 6. Customer files claim
claim = system.file_claim(
    policy_id=policy.policy_id,
    customer_id=customer.customer_id,
    amount=25000.00,
    description="Vehicle collision"
)

# 7. Claims adjuster approves
ClaimsManagement.approve_claim(claim, 24500.00)

# 8. Process payment
ClaimsManagement.process_claim_payment(claim)

# 9. Customer portal access
policies = system.get_customer_policies(customer.customer_id)
claims = system.get_customer_claims(customer.customer_id)
billing = system.get_customer_billing(customer.customer_id)
```

## Deployment Options

This Python implementation can be deployed as:

1. **REST API Backend** - Using Flask or FastAPI
2. **Database Models** - With SQLAlchemy ORM
3. **Microservices** - Individual service modules
4. **CLI Application** - Command-line interface
5. **Integration Layer** - Between AL/Business Central and external systems

## Testing

The `demo.py` file serves as comprehensive testing documentation. You can:
- Modify and extend the demo for additional test cases
- Use it as a template for unit tests
- Integrate with pytest for automated testing

## Architecture Comparison: AL vs Python

| Aspect | AL (Business Central) | Python |
|--------|----------------------|--------|
| **Language** | AL (Dynamics 365) | Python 3.8+ |
| **Database** | SQL Server | In-memory (extensible) |
| **UI Framework** | Business Central Pages | Web Framework (Flask/FastAPI) |
| **Type System** | Strongly Typed | Type Hints |
| **OOP** | Supported | Native |
| **Async** | Limited | Full Support |
| **Deployment** | Business Central Instance | Web Server/Container |

## Future Enhancements

- Database integration (SQLAlchemy)
- REST API (FastAPI/Flask)
- WebSocket support for real-time updates
- Advanced analytics and reporting
- Machine learning for risk assessment
- Payment gateway integration

## License

MIT License - See LICENSE file for details

---

**Version:** 1.0.0  
**Last Updated:** December 2025
