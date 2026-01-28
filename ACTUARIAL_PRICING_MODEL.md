# PHINS Actuarial Pricing Model

## Overview

This document describes the unified actuarial pricing model used across the PHINS platform to ensure consistent premium calculations from application through billing.

## Issue Identified (January 2026)

**Problem**: Premiums shown on applications were ~3.3x lower than what appeared on billing.

**Root Cause**: Two different calculation methods:
- Frontend (apply.js): Used `$0.25 per $1000 coverage per month`
- Backend (server.py): Used fixed base premiums ($800-$3000/year) with multipliers

**Resolution**: Unified all calculations to use the frontend formula.

## Premium Calculation Formula

```
monthly_premium = (coverage / 1000) * base_rate * age_factor * risk_factor
annual_premium = monthly_premium * 12
```

### Components

#### 1. Base Rate (per $1000 coverage per month)

| Policy Type    | Base Rate |
|---------------|-----------|
| Life          | $0.25     |
| Health        | $0.25     |
| PHINS Unified | $0.25     |
| Auto          | $0.15     |
| Property      | $0.20     |
| Business      | $0.40     |

#### 2. Age Factor

```
age_factor = 1.0 + (max(0, age - 25) * 0.015)
```

| Age | Factor |
|-----|--------|
| 25  | 1.00   |
| 30  | 1.075  |
| 35  | 1.15   |
| 40  | 1.225  |
| 45  | 1.30   |
| 47  | 1.33   |
| 50  | 1.375  |
| 55  | 1.45   |
| 60  | 1.525  |

#### 3. Risk Factor

| Risk Score | Factor |
|------------|--------|
| very_low   | 0.85   |
| low        | 0.90   |
| medium     | 1.00   |
| moderate   | 1.15   |
| elevated   | 1.25   |
| high       | 1.35   |
| very_high  | 1.50   |

### Billing Discounts

| Frequency  | Discount | Calculation |
|------------|----------|-------------|
| Monthly    | 0%       | `monthly_premium` |
| Quarterly  | 3%       | `monthly_premium * 3 * 0.97` |
| Annual     | 10%      | `monthly_premium * 12 * 0.90` |

## Example Calculations

### Example 1: ASAF ($500K health, age 47, moderate risk)

```
coverage = 500,000
base_rate = 0.25
age_factor = 1.0 + (47 - 25) * 0.015 = 1.33
risk_factor = 1.15 (moderate)

monthly = (500,000 / 1,000) * 0.25 * 1.33 * 1.15 = $191.19/month
annual = $191.19 * 12 = $2,294.25/year
```

### Example 2: EFRAT ($500K unified, age 35, low risk)

```
coverage = 500,000
base_rate = 0.25
age_factor = 1.0 + (35 - 25) * 0.015 = 1.15
risk_factor = 0.90 (low)

monthly = (500,000 / 1,000) * 0.25 * 1.15 * 0.90 = $129.38/month
annual = $129.38 * 12 = $1,552.50/year
```

### Example 3: $100K auto, age 30, medium risk

```
coverage = 100,000
base_rate = 0.15 (auto)
age_factor = 1.0 + (30 - 25) * 0.015 = 1.075
risk_factor = 1.00 (medium)

monthly = (100,000 / 1,000) * 0.15 * 1.075 * 1.00 = $16.13/month
annual = $16.13 * 12 = $193.50/year
```

## Implementation Locations

### Frontend (apply.js)

```javascript
function calculateBasePremium(coverage) {
    const dob = document.getElementById('dob')?.value;
    let ageFactor = 1.0;
    
    if (dob) {
        const age = calculateAge(dob);
        ageFactor = 1.0 + (Math.max(0, age - 25) * 0.015);
    }
    
    // Base: $0.25 per $1000 coverage per month
    const basePremium = (coverage / 1000) * 0.25 * ageFactor;
    return Math.round(basePremium);
}
```

### Backend (server.py)

```python
def calculate_premium(policy_data: Dict[str, Any]) -> Dict[str, float]:
    coverage = policy_data.get('coverage_amount', 100000)
    
    policy_type_rates = {
        'life': 0.25, 'health': 0.25, 'phins_unified': 0.25,
        'auto': 0.15, 'property': 0.20, 'business': 0.40
    }
    base_rate = policy_type_rates.get(policy_data.get('type', 'life'), 0.25)
    
    age = policy_data.get('age', 30)
    age_factor = 1.0 + (max(0, age - 25) * 0.015)
    
    risk_score = policy_data.get('risk_score', 'medium')
    risk_factors = {
        'very_low': 0.85, 'low': 0.90, 'medium': 1.0, 'moderate': 1.15,
        'elevated': 1.25, 'high': 1.35, 'very_high': 1.50
    }
    risk_factor = risk_factors.get(risk_score, 1.0)
    
    monthly_premium = (coverage / 1000) * base_rate * age_factor * risk_factor
    annual_premium = monthly_premium * 12
    
    return {
        'annual': round(annual_premium, 2),
        'monthly': round(monthly_premium, 2),
        'quarterly': round(monthly_premium * 3 * 0.97, 2)
    }
```

## Admin Tools

### Validation Script

```bash
# Validate premiums on production (dry-run)
python scripts/validate_premium_pricing.py --production

# Validate with fix option
python scripts/validate_premium_pricing.py --production --fix
```

### Recalculate API

```bash
# Dry-run (check only)
curl -X POST https://phins-portal-production.up.railway.app/api/admin/recalculate-premiums \
  -H "Content-Type: application/json" \
  -d '{"dry_run": true}'

# Apply corrections
curl -X POST https://phins-portal-production.up.railway.app/api/admin/recalculate-premiums \
  -H "Content-Type: application/json" \
  -d '{"dry_run": false}'

# Target specific customer
curl -X POST https://phins-portal-production.up.railway.app/api/admin/recalculate-premiums \
  -H "Content-Type: application/json" \
  -d '{"customer_id": "CUST-ASAF-001", "dry_run": false}'
```

## Data Integrity Checklist

- [ ] Frontend and backend use the same formula
- [ ] All seed data uses correct premiums
- [ ] Existing applications validated
- [ ] Existing policies validated
- [ ] Billing amounts aligned with policy premiums
- [ ] No hardcoded premium values that bypass calculation

## Files Modified

1. `web_portal/server.py` - `calculate_premium()` function
2. `web_portal/static/apply.js` - `calculateBasePremium()` function
3. `database/seeds.py` - All hardcoded premium values
4. `scripts/validate_premium_pricing.py` - Validation utility

---

*Last Updated: January 2026*
