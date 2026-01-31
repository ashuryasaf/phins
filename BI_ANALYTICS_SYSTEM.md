# PHINS BI and Analytics System

## Overview

Comprehensive Business Intelligence and Statistical Analytics service for platform optimization, insights generation, and data-driven decision making.

## Components

### 1. BI Analytics Service (`services/bi_analytics_service.py`)

Core analytics engine providing real-time metrics, trend analysis, and predictive forecasting.

### 2. Platform Integrity Service (`services/platform_integrity_service.py`)

Data integrity validation across all platform pipelines ensuring flawless data consistency.

### 3. API Endpoints (`web_portal/api_bi_analytics.py`)

RESTful API for accessing analytics and integrity reports.

## Dashboards

### Executive Dashboard

High-level KPIs for business leadership.

**Metrics:**
- Total customers (active, inactive)
- Total policies (by status)
- Monthly/annual revenue
- Claims metrics (approval rate, loss ratio)
- Financial health (assets, liabilities, net worth)
- Platform health scores

**API:**
```bash
GET /api/bi/executive-dashboard
```

**Response:**
```json
{
  "generated_at": "2024-01-15T12:00:00Z",
  "summary": {
    "total_customers": 150,
    "active_customers": 120,
    "total_policies": 200,
    "active_policies": 180,
    "monthly_revenue": 50000.0,
    "annual_revenue_projection": 600000.0
  },
  "financial": {
    "total_assets": 1000000.0,
    "total_liabilities": 200000.0,
    "net_worth": 800000.0,
    "claims_reserve": 500000.0,
    "loss_ratio": 45.0
  },
  "claims": {
    "total": 50,
    "total_claimed": 250000.0,
    "total_approved": 200000.0,
    "total_paid": 180000.0,
    "approval_rate": 80.0
  },
  "health_scores": {
    "financial_health": 85.0,
    "operational_health": 78.0,
    "overall_health": 81.5
  }
}
```

### Delivery Analytics Dashboard

Comprehensive delivery system performance metrics.

**Metrics:**
- Delivery requests (open, accepted, completed)
- Bid analytics (average per request, pricing)
- Delivery performance (on-time rate, completion time)
- Supplier performance (top performers, ratings)

**API:**
```bash
GET /api/bi/delivery-analytics
```

### Customer Analytics Dashboard

Customer behavior and engagement insights.

**Metrics:**
- Wallet adoption rate
- Investment participation
- Transaction volume
- Policy ownership
- Top customers by activity

**API:**
```bash
GET /api/bi/customer-analytics
```

### Supplier Analytics Dashboard

Supplier ecosystem performance and trends.

**Metrics:**
- Active suppliers by category
- Order volume and value
- Supplier ratings
- Top performers
- Revenue distribution

**API:**
```bash
GET /api/bi/supplier-analytics
```

## AI-Powered Insights

### Automated Insight Generation

The system automatically generates actionable insights based on data analysis:

**Categories:**
- Financial (loss ratio, receivables, net worth)
- Operations (claims approval, efficiency)
- Success (achievements, milestones)
- Warnings (emerging issues)

**Severity Levels:**
- **Critical**: Immediate action required
- **High**: Urgent attention needed
- **Medium**: Monitor closely
- **Positive**: Celebrate success

**API:**
```bash
GET /api/bi/insights
```

**Response:**
```json
{
  "dashboard_summary": {...},
  "health_scores": {...},
  "insights": [
    {
      "category": "financial",
      "severity": "high",
      "title": "High Loss Ratio Detected",
      "description": "Loss ratio is 85.0%, exceeding healthy threshold of 80%",
      "recommendation": "Consider: 1) Premium rate adjustments, 2) Stricter underwriting criteria, 3) Claims review process",
      "impact": "Sustainable profitability at risk"
    },
    {
      "category": "success",
      "severity": "positive",
      "title": "Strong Overall Health",
      "description": "Platform health score: 82.5/100",
      "recommendation": "Maintain current strategies and consider growth initiatives",
      "impact": "Strong foundation for expansion"
    }
  ],
  "insight_count": 2
}
```

## Revenue Forecasting

Predictive analytics for revenue planning using historical growth rates.

**Features:**
- Monthly Recurring Revenue (MRR) projections
- Annual Recurring Revenue (ARR) forecasts
- Compound growth modeling
- Scenario analysis

**API:**
```bash
GET /api/bi/revenue-forecast?growth_rate=0.05&months_ahead=12
```

**Parameters:**
- `growth_rate`: Monthly growth rate (default: 0.05 = 5%)
- `months_ahead`: Forecast horizon in months (default: 12)

**Response:**
```json
{
  "current_mrr": 50000.0,
  "current_arr": 600000.0,
  "growth_rate": 5.0,
  "forecast_months": 12,
  "forecast": [
    {
      "month": 1,
      "forecasted_mrr": 52500.0,
      "forecasted_arr": 630000.0
    },
    ...
  ]
}
```

## Platform Integrity Validation

Comprehensive data integrity checks across all pipelines.

### Validation Categories

1. **User Types** - Admin, underwriter, supplier, customer validation
2. **Customer Records** - Profile completeness, email uniqueness
3. **Policy Pipeline** - Customer → Policy → Underwriting → Billing
4. **Claims Pipeline** - Policy → Claim → Payment → Wallet
5. **Billing Pipeline** - Policy → Bill → Payment → Revenue
6. **Ledger Integrity** - Balance consistency, transaction matching
7. **Foundation Pipeline** - Foundation → Members → Contributions
8. **Supplier Pipeline** - Supplier → Offers → Orders → Delivery
9. **Delivery Pipeline** - Request → Bid → Delivery → Payment

### Validation API

```bash
GET /api/integrity/validate
```

**Response:**
```json
{
  "timestamp": "2024-01-15T12:00:00Z",
  "status": "PASS",
  "summary": {
    "total_checks": 9,
    "passed_checks": 8,
    "failed_checks": 1,
    "errors_found": 3,
    "warnings_found": 5,
    "overall_status": "FAIL"
  },
  "validation_results": {
    "users": {
      "total_users": 50,
      "invalid_roles": 0,
      "status": "PASS"
    },
    "customers": {
      "total_customers": 150,
      "missing_email": 0,
      "duplicate_emails": 0,
      "status": "PASS"
    },
    "policies": {
      "total_policies": 200,
      "orphaned_policies": 2,
      "policies_without_billing": 5,
      "status": "FAIL"
    },
    ...
  },
  "errors": [
    {
      "category": "policies",
      "severity": "error",
      "policy_id": "POL-999",
      "message": "Policy POL-999 references non-existent customer CUST-999"
    }
  ],
  "warnings": [
    {
      "category": "customers",
      "severity": "warning",
      "customer_id": "CUST-001",
      "message": "Customer CUST-001 has no user account for portal access"
    }
  ]
}
```

## Health Score Calculations

### Financial Health Score (0-100)

**Components:**
- **Net Worth** (30 points): Positive equity position
- **Claims Reserve** (30 points): Adequate reserves (3 months revenue)
- **Revenue Positivity** (20 points): Positive cash flow

**Formula:**
```python
score = 50  # Base
score += min(30, (net_worth / 100000) * 10)  # Net worth bonus
score += min(30, (claims_reserve / (monthly_revenue * 3)) * 30)  # Reserve adequacy
score += 20 if monthly_revenue > 0 else 0  # Revenue positivity
return min(100, max(0, score))
```

### Operational Health Score (0-100)

**Components:**
- **Claims Efficiency** (30 points): High approval rate (>70%)
- **Receivables Management** (20 points): Low outstanding (<5% revenue)

**Formula:**
```python
score = 50  # Base
if claims_approval_rate >= 70: score += 30
elif claims_approval_rate >= 50: score += 20
if receivables_ratio < 0.05: score += 20
elif receivables_ratio < 0.10: score += 15
return min(100, max(0, score))
```

### Overall Health Score

```python
overall_health = (financial_health + operational_health) / 2
```

## Statistical Analytics

### Trend Analysis

- Moving averages
- Growth rate calculations
- Seasonality detection
- Anomaly detection

### Performance Benchmarking

- Industry comparisons
- Historical performance
- Peer analysis
- Best practices identification

### Predictive Modeling

- Revenue forecasting
- Churn prediction
- Claims frequency modeling
- Risk assessment

## Usage Examples

### Python SDK

```python
from services.bi_analytics_service import get_bi_analytics_service
from services.platform_integrity_service import get_platform_integrity_service

# Initialize services
bi_service = get_bi_analytics_service()
integrity_service = get_platform_integrity_service()

# Get executive dashboard
dashboard = bi_service.get_executive_dashboard(
    customers=CUSTOMERS,
    policies=POLICIES,
    claims=CLAIMS,
    billing=BILLING,
    balance_sheet=PHINS_BALANCE_SHEET
)

# Generate AI insights
insights = bi_service.generate_ai_insights(dashboard)

# Validate platform integrity
validation = integrity_service.validate_all(
    users=USERS,
    customers=CUSTOMERS,
    policies=POLICIES,
    # ... all data sources ...
)

# Revenue forecast
forecast = bi_service.predict_revenue_forecast(
    policies=POLICIES,
    historical_growth_rate=0.05,
    months_ahead=12
)
```

### API Integration

```javascript
// Executive Dashboard
fetch('/api/bi/executive-dashboard')
  .then(res => res.json())
  .then(dashboard => {
    console.log('Platform Health:', dashboard.health_scores.overall_health);
    console.log('Monthly Revenue:', dashboard.summary.monthly_revenue);
  });

// AI Insights
fetch('/api/bi/insights')
  .then(res => res.json())
  .then(data => {
    data.insights.forEach(insight => {
      console.log(`[${insight.severity}] ${insight.title}`);
      console.log(` → ${insight.recommendation}`);
    });
  });

// Platform Integrity
fetch('/api/integrity/validate')
  .then(res => res.json())
  .then(validation => {
    console.log('Status:', validation.status);
    console.log('Errors:', validation.summary.errors_found);
    console.log('Warnings:', validation.summary.warnings_found);
  });
```

## Testing

Comprehensive test suites:

- `tests/test_bi_analytics.py` - BI analytics functionality
- `tests/test_platform_integrity.py` - Data integrity validation

Run tests:
```bash
pytest tests/test_bi_analytics.py -v
pytest tests/test_platform_integrity.py -v
```

## Best Practices

1. **Regular Monitoring**: Check executive dashboard daily
2. **Act on Insights**: Address AI-generated insights promptly
3. **Data Integrity**: Run validation weekly
4. **Trend Analysis**: Review metrics monthly for trends
5. **Forecasting**: Update forecasts quarterly
6. **Documentation**: Document all major metric changes

## Future Enhancements

1. **Machine Learning Models**: Advanced predictive analytics
2. **Real-time Dashboards**: Live streaming metrics
3. **Custom Reports**: User-defined report builder
4. **Data Warehouse**: Historical data analysis
5. **Export Capabilities**: PDF/Excel report generation
6. **Alert System**: Automated threshold-based alerts
7. **Comparative Analytics**: Multi-period comparisons
