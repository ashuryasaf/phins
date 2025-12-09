# PHINS Premium Forecast Calculator - Sales Division Guide

## Overview
The Premium Forecast Calculator is a powerful sales tool for demonstrating premium allocation options to customers. It shows how monthly premiums are split between **risk/coverage** and **savings/investment**, with projections for growth, returns, and capital revenue impacts.

## Key Features

### 1. Risk Hedging Strategies
Five pre-built hedging strategies to match customer preferences:

| Strategy | Risk % | Savings % | Best For | ROI Range |
|----------|--------|-----------|----------|-----------|
| **NO_HEDGE** | 100% | 0% | Protection-first customers | 0% |
| **LOW_HEDGE** | 70% | 30% | Growth-focused, good coverage | 43.66% |
| **BALANCED_HEDGE** | 50% | 50% | Most customers, balanced | 18.55% |
| **HIGH_HEDGE** | 30% | 70% | Savings-focused, conservative | 14.07% |
| **PURE_SAVINGS** | 0% | 100% | Savings/investment only | Higher ROI |

### 2. Payment Periods
Flexible payment options to fit customer cash flow:
- **Monthly**: $800/month (most common)
- **Quarterly**: $2,400/quarter (3% less total cost due to consolidation)
- **Semi-Annual**: $4,800 twice/year
- **Annual**: $9,600/year (best rate)

### 3. Investment Routes
Four investment options for savings allocation:

| Route | Annual Rate | Risk Level | Best For |
|-------|------------|------------|----------|
| **Basic Savings** | 0.5% | Very Low | Conservative, immediate access |
| **Bonds** | 3.5% | Low | Moderate growth, stable |
| **Mixed Portfolio** | 4.5% | Medium | Balanced approach |
| **Equities** | 7.0% | High | Long-term growth, risk-tolerant |

### 4. Market Indices
Adjust projections for different market conditions:
- **Conservative**: 3% market growth multiplier
- **Moderate**: 5% market growth multiplier (default)
- **Aggressive**: 8% market growth multiplier
- **Volatile**: 2-10% range, conservative estimate

### 5. Capital Revenue (Tax) Impact
Automatic calculation of tax liabilities on investment returns:
- Default rate: 15% on investment earnings
- Adjustable by jurisdiction
- Shows net customer value after tax liability

## How to Use

### Basic Usage
```python
from premium_forecast_calculator import PremiumForecastCalculator, PaymentPeriod, MarketIndex, RiskHedgeStrategy
from accounting_engine import InvestmentRoute
from decimal import Decimal

calculator = PremiumForecastCalculator()

# Create a forecast scenario
forecast = calculator.create_forecast(
    scenario_name="Balanced Approach",
    monthly_premium=Decimal('800'),
    payment_period=PaymentPeriod.MONTHLY,
    duration_years=5,
    risk_hedge=RiskHedgeStrategy.BALANCED_HEDGE,
    investment_route=InvestmentRoute.MIXED_PORTFOLIO,
    market_index=MarketIndex.MODERATE,
    capital_revenue_rate=Decimal('15.0')
)

# Display results
calculator.print_forecast_summary(forecast)
```

### Key Metrics Explained

**Risk Allocation**: Amount going toward claims coverage and operational costs
- 60% goes to actual claims reserve
- 40% goes to operational/admin costs

**Savings Allocation**: Amount invested in chosen route
- Grows with compound interest monthly
- Subject to capital revenue (tax) on earnings only

**Investment Returns**: Net earnings from investment growth
- Calculated with monthly compounding
- Adjusted for market index conditions
- Shows ROI percentage

**Capital Revenue Liability**: Tax on investment earnings
- 15% default rate on investment returns
- Does NOT tax the principal contribution

**Net Customer Savings**: Final value after all taxes
- Savings contributed + Investment returns - Capital revenue tax

**Customer Lifetime Value**: Total value including risk reserves
- Savings balance + Implied claims reserve

**Premium Efficiency**: Claims reserve as % of total premium
- Higher = more protection per dollar
- NO_HEDGE = 60% efficiency
- PURE_SAVINGS = 0% efficiency

## Sales Pitch Examples

### For Conservative Customers
"With our **HIGH_HEDGE** option (30% risk, 70% savings), you get strong family protection while most of your premium grows in our BONDS portfolio at 3.5% annually. Over 5 years, that's **$37,618 in net savings** plus **$8,640 in claims reserve**. Best of both worlds!"

### For Balanced Customers
"Our **50/50 split** is perfect if you want protection AND growth. Half your premium goes to comprehensive family coverage, the other half grows in our MIXED_PORTFOLIO at 4.5%. In 5 years: **$27,785 net savings** + **$14,400 claims reserve**. True balance."

### For Growth-Focused Customers
"Ready to maximize growth? Our **AGGRESSIVE option** puts 70% into EQUITIES (7% annual return) while keeping solid 30% protection. With aggressive market momentum, you could see **$19,744 net growth** over 5 years plus **$20,160 in claims reserve**."

### For Protection-First Customers
"Your family's security comes first. With our **100% RISK coverage**, every dollar builds your claims reserve. Over 5 years: **$28,800 dedicated to protecting your family**. Pure peace of mind."

### For Convenience Preference
"Prefer quarterly payments? No problem! **$2,400 four times a year** instead of monthly. Same balanced 50/50 split, same 4.5% growth, with **$25,128 accumulated** in just 5 years."

## Running the Demo
```bash
cd /workspaces/phins
python premium_forecast_calculator.py
```

This will:
1. Create 5 complete forecast scenarios
2. Print detailed breakdowns for each
3. Show comparison table across all scenarios
4. Provide recommendations by customer type
5. Display customizable sales pitch templates

## Advanced Features

### Comparing Scenarios
```python
# Get recommendations
best_customer_value = calculator.get_best_for_customer()
best_risk_mitigation = calculator.get_best_for_risk_mitigation()
best_balanced = calculator.get_best_balanced()

# Print comparison
calculator.print_comparison_table()
calculator.print_detailed_comparison()
```

### Custom Scenarios
Create unlimited scenarios with different parameters:
- Different customer ages/income levels
- Different term lengths (1-30 years)
- Different premium amounts
- Different jurisdictions (affects capital revenue rate)

### Real-time Adjustments
Scenario parameters are calculated in real-time:
- Change payment period → automatic recalculation of period payment
- Change investment route → automatic rate adjustment
- Change market index → automatic growth adjustment
- Change duration → automatic period calculation

## Integration Points

### Web Portal Integration
Add to web portal for customer self-service:
```python
# In web_portal/server.py
@app.get('/api/forecast')
def get_forecast(monthly_premium: float, strategy: str, duration_years: int):
    calculator = PremiumForecastCalculator()
    # Create forecast, return as JSON
```

### Business Central Integration
Link to AL pages for formal quote generation:
- Premium allocation posting in AL
- Risk reserve calculations
- Capital revenue tracking per customer
- Annual tax reporting

### Sales CRM Integration
Export scenarios for customer proposals:
- PDF quote generation
- Side-by-side scenario comparison
- Customizable branding
- Electronic signature capture

## Technical Details

### Calculation Methods

**Compound Interest (Monthly)**:
```
For each month:
  balance = balance * (1 + monthly_rate) + monthly_contribution
```

**ROI Percentage**:
```
ROI = (Investment Returns / Total Savings Contributed) * 100
```

**Capital Revenue**:
```
Liability = Investment Returns * (Capital Revenue Rate / 100)
```

**Claims Reserve**:
```
Reserve = Total Risk Premium * 0.60
```

### Performance
- Handles up to 360 periods (30-year scenarios) instantly
- Monthly compounding for accuracy
- Decimal precision to 0.01

### Data Structure
Each forecast contains:
- Scenario parameters (premium, period, duration, strategy, route, index)
- Calculated periods and payment amounts
- Risk/savings allocation breakdown
- Investment growth projections
- Capital revenue calculations
- Reserve projections
- Customer net value summary

## Future Enhancements

1. **Dynamic Factor Adjustments**
   - Customer age/health risk multipliers
   - Occupation-based rate adjustments
   - Regional market variations

2. **Advanced Market Modeling**
   - Historical volatility patterns
   - Scenario planning tools
   - Monte Carlo simulations

3. **Regulatory Compliance**
   - Automatic jurisdiction rate selection
   - Regulatory disclosures
   - Compliance documentation

4. **Integration APIs**
   - REST endpoints for integrations
   - Real-time IRS capital revenue rate lookup
   - Market data feeds

## Support & Questions

For sales team support, the calculator provides:
- Clear ROI comparisons
- Pitch templates for every customer type
- Detailed breakdowns for customer questions
- Competitive scenario modeling
- Profitability analysis by strategy
