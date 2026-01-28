# Customer Data Reset Documentation

## Overview

This document describes the customer data reset functionality for the PHINS platform, specifically for customer `asaf@assurance.co.il` (CUST-ASAF-001).

## API Endpoint

```
POST /api/admin/reset-customer-account
```

### Request Body

```json
{
    "customer_id": "CUST-ASAF-001",
    "keep_ledger": true
}
```

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `customer_id` | string | `CUST-ASAF-001` | Target customer ID |
| `keep_ledger` | boolean | `true` | Preserve transaction ledger for audit trail |

## What Gets Reset

### 1. Claims (All Statuses)
- Paid claims
- Approved claims
- Pending claims
- Rejected claims
- Under review claims

Each claim removal is recorded on the transaction ledger before deletion.

### 2. Health Wallet
- Balance reset to $0
- Monthly deposit reset to $0
- Transaction history cleared
- Wallet ID preserved

### 3. Investment Account
- Total balance reset to $0
- Index balance reset to $0
- Bonds balance reset to $0
- Crypto balance reset to $0
- Deposit history cleared

### 4. Algo Trading
- Available balance reset to $0
- Positions reset to $0
- Total PnL reset to $0
- Active bots count reset to 0

### 5. Savings Pipeline
- Cash balance reset to $0
- Total allocated reset to $0
- Allocation history cleared

### 6. Medical Purchases (Wallet Purchase History)
- All medical purchases removed
- Total purchase amount tracked in result

### 7. Associated Items
- Policies for this customer
- Underwriting applications
- Bills and invoices

## What Gets Preserved

### Transaction Ledger
The transaction ledger is preserved by default (`keep_ledger: true`) to maintain:
- Complete audit trail
- Regulatory compliance
- Historical record of all transactions

Each reset action records a ledger entry with:
- Transaction type (e.g., `claim_cancelled`, `wallet_reset`)
- Amount
- Reason: `customer_account_reset`
- Metadata about the removed item

### NFT Tokens
- NFT ledger entries preserved
- New NFT token created for the reset transaction

### Customer Profile
- Basic customer information preserved
- Pipeline stage reset to `registered`

## Response Structure

```json
{
    "success": true,
    "customer_id": "CUST-ASAF-001",
    "removed": {
        "policies": 3,
        "applications": 1,
        "claims": 5,
        "bills": 2,
        "medical_purchases": 4,
        "medical_purchase_total": 7450.00
    },
    "investment_reset": true,
    "wallet_reset": true,
    "algo_reset": true,
    "pipeline_reset": true,
    "ledger_preserved": true,
    "ready_for": ["new_applications", "increase_coverage", "new_deposits"],
    "ledger_entries": {
        "transactions": 150,
        "nft_tokens": 25
    },
    "nft_token_id": "NFT-RESET-20260128-123456",
    "block_number": 12345,
    "message": "Account reset complete. Customer is now ready for new applications and deposits."
}
```

## Data Integrity Features

### Safe Delete Operations
All delete operations use safe patterns to prevent errors:

```python
# Instead of:
del CLAIMS[cid]  # Can raise KeyError

# We use:
CLAIMS.pop(cid, None)  # Safe delete, returns None if not found
```

### Pre-Delete Checks
Each item is verified to exist before deletion:

```python
claim = CLAIMS.get(cid)
if claim is None:
    continue  # Skip if already removed
```

### Transaction Recording
Every removal is recorded before the item is deleted:

```python
record_transaction(
    customer_id=customer_id,
    tx_type='claim_cancelled',
    amount=0,
    description=f'Claim {cid} cancelled - account reset',
    metadata={
        'claim_id': cid,
        'status': claim.get('status'),
        'claimed_amount': claim.get('claimed_amount'),
        'reason': 'customer_account_reset'
    }
)
```

## Customer Isolation

The reset is **strictly restricted** to the specified customer:

- Only items where `customer_id == TARGET_CUSTOMER_ID` are affected
- Other customers' data remains untouched
- Filter is applied at the query level

## Testing

### Run Tests
```bash
pytest tests/test_customer_reset.py -v
```

### Test Coverage
- Customer isolation verification
- All data types reset correctly
- Safe delete prevents KeyError
- Result structure validation
- Ledger preservation

## Usage Script

A helper script is available at `scripts/reset_customer_asaf.py`:

```bash
# Dry run (show what would be reset)
python scripts/reset_customer_asaf.py --dry-run --production

# Execute reset
python scripts/reset_customer_asaf.py --production
```

## Security

### Access Control
- Endpoint requires admin role
- Audit trail maintained
- NFT token generated for compliance

### Confirmation Required
- Interactive script requires typing 'RESET' to confirm
- API endpoint should be called with caution

## Post-Reset State

After reset, the customer account is in a clean state:

| Component | Value |
|-----------|-------|
| Health Wallet Balance | $0 |
| Investment Balance | $0 |
| Algo Trading Balance | $0 |
| Claims Count | 0 |
| Medical Purchases | 0 |
| Pipeline Stage | `registered` |
| Ledger History | Preserved |

The customer is ready for:
- New policy applications
- Coverage increases
- New premium deposits
- Fresh start with clean data

---

*Last Updated: January 28, 2026*
*Target Customer: asaf@assurance.co.il (CUST-ASAF-001)*
