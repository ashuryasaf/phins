# PHINS Accounting Engine - Complete Documentation

## Overview

The **PHINS Accounting Engine** is a comprehensive accounting and financial management system for insurance premiums with **dynamic risk/savings allocation** and **accumulative premium tracking**. It enables insurance companies to:

- Split customer premiums between **risk coverage** and **customer savings accounts**
- Track accumulative premiums for accounting books
- Calculate risk/investment ratios
- Generate customer-facing premium statements
- Maintain general ledger entries with full audit trail

## Key Features

### 1. Premium Allocation with Risk/Savings Split

Each premium payment is divided between:
- **Risk Coverage**: Amount allocated to cover insurance risk
- **Customer Savings**: Amount credited to customer savings account (refundable/returnable)

**Example:**
```
Customer pays: $1,000/month
├─ Risk Coverage (80%): $800 → Goes to risk fund
└─ Customer Savings (20%): $200 → Goes to customer savings account
```

### 2. Accumulative Premium Tracking

Tracks cumulative premiums over time for:
- Accounting books (general ledger)
- Policy-level accumulation
- Customer-level accumulation
- Fund-level tracking (Risk Fund, Savings Fund)

### 3. Risk/Investment Ratio Analysis

Calculates the ratio between risk coverage and savings:
```
Investment Ratio = Risk Coverage / Customer Savings
```

For the example above:
- Investment Ratio = $800 / $200 = 4:1
- Meaning: For every $1 in savings, customer covers $4 in risk

### 4. Customer Premium Statements

Generates detailed statements showing:
- Individual monthly allocations
- Risk vs. savings breakdown per payment
- Total accumulated amounts
- Period summaries

### 5. Accounting Book/General Ledger

Maintains complete ledger entries with:
- Debit/credit tracking
- Running balances per account
- Fund summaries (Risk, Savings, Reinsurance, Operating)
- Full audit trail with timestamps

## System Architecture

```
AccountingEngine (Main Service)
├── PremiumAllocation (Data: Premium split tracking)
├── AccountingEntry (Data: Ledger entries)
├── CustomerPremiumStatement (Data: Customer reports)
├── AccountingBook (Data: General ledger)
└── Helper Methods (Calculations and reporting)
```

## Data Models

### PremiumAllocation
Represents a single premium allocation decision:
- **allocation_id**: Unique identifier
- **bill_id**: Link to billing system
- **policy_id**: Link to policy
- **customer_id**: Link to customer
- **allocation_date**: Date of allocation
- **total_premium**: Total amount paid
- **risk_percentage**: % allocated to risk (0-100)
- **savings_percentage**: % allocated to savings (100 - risk)
- **risk_premium**: Calculated risk amount
- **savings_premium**: Calculated savings amount
- **investment_ratio**: Risk/Savings ratio
- **status**: Draft, Posted, Reversed, Cancelled
- **posted_date**: When posted to ledger
- **posted_by**: User who posted

### AccountingEntry
General ledger entry:
- **entry_no**: Auto-incrementing entry number
- **allocation_id**: Link to allocation
- **entry_type**: Premium Posted, Risk Payment, Savings Deposit, etc.
- **account_type**: Risk Fund, Savings Fund, Reinsurance, Operating
- **debit_amount**: Debit side amount
- **credit_amount**: Credit side amount
- **balance**: Running balance
- **description**: Entry description
- **posted_by**: User who posted
- **entry_date**: When posted

### CustomerPremiumStatement
Customer-facing statement:
- **customer_id**: Customer identifier
- **period_start**: Statement period start
- **period_end**: Statement period end
- **allocations**: List of allocations in period
- **total_premiums**: Sum of all premiums
- **total_risk_coverage**: Sum of risk amounts
- **total_customer_savings**: Sum of savings amounts
- **average_risk_percentage**: Average risk % for period
- **average_savings_percentage**: Average savings % for period

## Usage Examples

### Create and Post Premium Allocation

```python
from accounting_engine import AccountingEngine
from decimal import Decimal
from datetime import date

# Initialize engine
engine = AccountingEngine("ACC_001", "PHINS Insurance")

# Create allocation: $1,000 premium, 80% risk, 20% savings
allocation = engine.create_allocation(
    bill_id="BILL_001",
    policy_id="POL_001",
    customer_id="CUST_001",
    total_premium=Decimal("1000.00"),
    risk_percentage=Decimal("80")
)

# Post allocation (creates ledger entries)
success, message = engine.post_allocation(
    allocation.allocation_id, 
    posted_by="Accounting Officer"
)

# Result:
# - Risk Premium: $800.00 → Risk Fund
# - Savings Premium: $200.00 → Savings Fund
# - Investment Ratio: 4.0000 (Risk:Savings)
```

### Generate Customer Statement

```python
from datetime import date, timedelta

start_date = date(2025, 10, 1)
end_date = date(2025, 12, 31)

statement = engine.get_customer_statement(
    customer_id="CUST_001",
    start_date=start_date,
    end_date=end_date
)

# Display statement
print(statement.to_string())

# Or get as dictionary
statement_dict = statement.to_dict()
```

### Get Accumulative Premium Report

```python
report = engine.get_accumulative_premium_report(policy_id="POL_001")

print(f"Cumulative Premium: ${report['cumulative_premium']:.2f}")
print(f"Cumulative Risk: ${report['cumulative_risk']:.2f}")
print(f"Cumulative Savings: ${report['cumulative_savings']:.2f}")
print(f"Overall Risk %: {report['overall_risk_percentage']:.2f}%")
```

### Get Risk/Investment Ratio

```python
ratio_info = engine.get_risk_investment_ratio(customer_id="CUST_001")

print(f"Total Risk: ${ratio_info['total_risk']:.2f}")
print(f"Total Savings: ${ratio_info['total_savings']:.2f}")
print(f"Risk:Savings Ratio: {ratio_info['risk_investment_ratio']:.4f}:1")
```

### Generate Accounting Book

```python
from datetime import date, timedelta

start_date = date.today() - timedelta(days=30)
end_date = date.today()

book = engine.generate_accounting_book(start_date, end_date)

# Display full ledger
print(book.to_string())

# Get balances
print(f"Risk Fund: ${book.risk_fund_balance:.2f}")
print(f"Savings Fund: ${book.savings_fund_balance:.2f}")
print(f"Total Debits: ${book.total_debits:.2f}")
print(f"Total Credits: ${book.total_credits:.2f}")
```

### Get Customer Summary

```python
summary = engine.get_customer_summary(customer_id="CUST_001")

print(f"Total Allocations: {summary['allocation_count']}")
print(f"Total Premium: ${summary['total_premium']:.2f}")
print(f"Total Risk: ${summary['total_risk']:.2f}")
print(f"Total Savings: ${summary['total_savings']:.2f}")
print(f"Investment Ratio: {summary['overall_investment_ratio']:.4f}")
```

## Allocation Strategies

### Strategy 1: Pure Risk (100% Risk / 0% Savings)
- Full premium goes to risk coverage
- No customer savings account accumulation
- Suitable for pure insurance products
- Investment Ratio: ∞

### Strategy 2: Conservative (60% Risk / 40% Savings)
- Majority to risk, significant savings component
- Good for customers wanting savings
- Investment Ratio: 1.5:1

### Strategy 3: Balanced (50% Risk / 50% Savings)
- Equal split between risk and savings
- Most common for hybrid products
- Investment Ratio: 1.0:1

### Strategy 4: Savings Focus (30% Risk / 70% Savings)
- Majority to customer savings
- Minimal risk coverage
- Good for investment-oriented customers
- Investment Ratio: 0.43:1

## Integration with PHINS Modules

### Integration with Billing Module
```python
# After payment recorded in BillingManagement
bill_id = CreateBill(policy_id, customer_id, 1000, "Monthly Premium")
RecordPayment(bill_id, 1000, "Online Portal")

# Create accounting allocation
allocation = engine.create_allocation(
    bill_id=bill_id,
    policy_id=policy_id,
    customer_id=customer_id,
    total_premium=1000,
    risk_percentage=80
)
engine.post_allocation(allocation.allocation_id, "System")
```

### Integration with Underwriting Module
```python
# Risk assessment can influence allocation percentage
# Example: Higher risk → higher risk_percentage

risk_score = calculate_risk_score(customer_info)

if risk_score > 0.7:
    risk_percentage = 90  # High-risk customer
elif risk_score > 0.5:
    risk_percentage = 75  # Medium risk
else:
    risk_percentage = 60  # Low risk

allocation = engine.create_allocation(
    bill_id=bill_id,
    policy_id=policy_id,
    customer_id=customer_id,
    total_premium=1000,
    risk_percentage=risk_percentage
)
```

### Integration with Claims Module
```python
# When claim is paid, it affects risk fund
claim_amount = 5000

# Create accounting entry
engine._create_ledger_entry(
    allocation_id="CLAIM_001",
    policy_id=policy_id,
    customer_id=customer_id,
    entry_date=date.today(),
    entry_type=EntryType.CLAIM_PAYMENT,
    account_type=AccountType.RISK_FUND,
    credit_amount=claim_amount,
    description=f"Claim Payment: CLM_{claim_number}"
)
```

## Business Central (AL) Integration

### Create Premium Allocation in AL

```al
procedure CreateAndPostAllocation()
var
    AccountingMgmt: Codeunit "PHINS Accounting Management";
    AllocationID: Code[20];
begin
    // Create allocation
    AllocationID := AccountingMgmt.AllocatePremium(
        'BILL_001',     // Bill ID
        'POL_001',      // Policy ID
        'CUST_001',     // Customer ID
        1000.00,        // Total Premium
        80              // Risk Percentage
    );
    
    // Post to ledger
    AccountingMgmt.PostAllocation(AllocationID);
end;
```

### Generate Customer Statement in AL

```al
procedure ShowCustomerStatement()
var
    AccountingMgmt: Codeunit "PHINS Accounting Management";
    Statement: Text;
begin
    Statement := AccountingMgmt.GenerateCustomerStatement(
        'CUST_001',
        Today() - 90,
        Today()
    );
    
    Message(Statement);
end;
```

### Get Accounting Book in AL

```al
procedure GenerateAccounting()
var
    AccountingMgmt: Codeunit "PHINS Accounting Management";
    BookReport: Text;
begin
    BookReport := AccountingMgmt.GenerateAccountingBook(
        Today() - 30,
        Today()
    );
    
    Message(BookReport);
end;
```

## Database Schema

### Tables (Business Central)

#### PHINS Premium Allocation (50107)
- Allocation ID (PK)
- Bill ID (FK)
- Policy ID (FK)
- Customer ID (FK)
- Allocation Date
- Total Premium, Risk Premium, Savings Premium
- Risk %, Savings %, Investment Ratio
- Status, Posted Date, Posted By
- Notes, Created Date, Last Modified

#### PHINS Accounting Ledger (50108)
- Entry No. (PK, Auto-increment)
- Allocation ID (FK)
- Policy ID (FK)
- Customer ID (FK)
- Entry Date
- Entry Type, Account Type
- Debit Amount, Credit Amount, Balance
- Description, Reference No.
- Posted, Posted By, Created Date

## Reports and Dashboards

### 1. Customer Premium Statement
- **Audience**: Individual customers
- **Frequency**: Monthly
- **Content**: Detailed allocation breakdown, running totals
- **Format**: PDF or portal view

### 2. Accounting Book / General Ledger
- **Audience**: Finance, Accounting
- **Frequency**: Monthly, Quarterly, Annual
- **Content**: All ledger entries, fund balances, trial balance
- **Format**: Report, Excel export

### 3. Accumulative Premium Report
- **Audience**: Underwriting, Risk Management
- **Frequency**: Monthly
- **Content**: Cumulative premiums by policy, trends
- **Format**: Report, Dashboard

### 4. Risk/Investment Analysis Report
- **Audience**: Executive, Finance
- **Frequency**: Monthly
- **Content**: Ratio analysis, fund allocation trends
- **Format**: Report, Charts

### 5. Fund Summary Report
- **Audience**: Finance, Treasury
- **Frequency**: Daily, Monthly
- **Content**: Risk Fund balance, Savings Fund balance, movements
- **Format**: Real-time dashboard

## Security and Audit

### Access Control
- Post allocations: Accounting Officer role
- View statements: Customer (own), Finance (all)
- Generate reports: Management, Accounting

### Audit Trail
- All allocations tracked with created/modified dates
- All ledger entries immutable once posted
- User attribution (posted_by)
- Full transaction history

### Validation
- Premium percentages validate to 100%
- Amounts must be non-negative
- Allocations cannot be modified after posting
- Ledger entries create balanced entries

## Performance Considerations

### Indexing (Business Central Tables)
- Primary index: Allocation ID, Entry No.
- Secondary indices: Bill ID, Policy ID, Customer ID, Date, Status
- Search optimization for customer statements

### Query Optimization
- Filter allocations by date range early
- Use indexed columns in lookups
- Batch ledger entry creation

### Data Volume
- Expected 10,000-100,000 allocations/month (by premium volume)
- Ledger entries grow linearly with allocations
- Archive old ledger entries for performance

## Testing

### Unit Tests
```python
def test_premium_allocation():
    engine = AccountingEngine("TEST", "Test Org")
    alloc = engine.create_allocation(
        "BILL_001", "POL_001", "CUST_001",
        Decimal("1000"), Decimal("80")
    )
    assert alloc.risk_premium == Decimal("800")
    assert alloc.savings_premium == Decimal("200")

def test_customer_statement():
    # Create multiple allocations
    # Generate statement
    # Verify totals and calculations

def test_accounting_book():
    # Create allocations with different customers
    # Generate book
    # Verify ledger balances, debits = credits
```

### Integration Tests
- Test with actual billing data
- Test with customer database
- Test report generation
- Test concurrent allocations

## Deployment Checklist

- [ ] Database tables created
- [ ] Codeunits deployed
- [ ] Python modules installed
- [ ] Integration with Billing tested
- [ ] Customer portal integration ready
- [ ] Accounting reports configured
- [ ] User roles and permissions set
- [ ] Audit logging enabled
- [ ] Backup strategy in place
- [ ] Performance testing completed

## Support and Maintenance

### Common Issues

**Issue**: Allocation percentages don't equal 100%
- **Solution**: Validate input, system auto-calculates savings%

**Issue**: Ledger entries don't balance
- **Solution**: Always post both Risk and Savings entries together

**Issue**: Customer statement missing allocations
- **Solution**: Check allocation status is "Posted", verify dates

### Regular Maintenance

- Monthly: Run accounting book, verify balances
- Quarterly: Archive old ledger entries
- Annual: Full audit trail review

## Future Enhancements

1. **Investment Returns**: Track investment income on savings accounts
2. **Withdrawal Processing**: Handle customer withdrawals from savings
3. **Policy Renewal**: Recalculate allocation percentages at renewal
4. **Integration**: Connect to investment fund manager systems
5. **Analytics**: Advanced reporting and predictive analysis
6. **Automation**: Auto-post allocations based on payment status
