# Risk Reports Dashboard - Quick Reference Card

## 🎯 Where Can I Use Risk Reports?

### Underwriter Dashboard
**URL**: `/underwriter-dashboard.html`
**Button**: "Risk Report" (on application row)
**Use**: Review risk during underwriting workflow
```
/risk-assessment-viewer.html?id=<application_id>
```

### Admin Dashboard
**URL**: `/admin.html`
**Link**: "🔒 Risk Assessment Reports" (navigation)
**Button**: "Risk Report" (on application row)
**Use**: Executive oversight and supervision
```
/risk-assessment-viewer.html?id=<underwriting_id>
```

### Claims Adjuster Dashboard
**URL**: `/claims-adjuster-dashboard.html`
**Button**: "Risk Report" (on claim)
**Use**: Customer risk profile during claims assessment
```
/risk-assessment-viewer.html?customer_id=<customer_id>
```

### Actuary Dashboard
**URL**: `/actuary-dashboard.html`
**Link**: "Risk Reports" (navigation)
**Use**: Portfolio analysis and pricing validation
```
/risk-assessment-viewer.html
```

---

## 🔗 Direct URL Patterns

```bash
# By Application ID
/risk-assessment-viewer.html?id=<application_id>

# By Customer ID
/risk-assessment-viewer.html?customer_id=<customer_id>

# By Email
/risk-assessment-viewer.html?email=<customer_email>
```

**Examples**:
```
/risk-assessment-viewer.html?id=UW-001
/risk-assessment-viewer.html?customer_id=CUST-ASAF-001
/risk-assessment-viewer.html?email=asaf@assurance.co.il
```

---

## 🔐 Who Can Access?

✅ **admin** - Full access  
✅ **underwriter** - Full access  
✅ **actuary** - Full access  
✅ **claims_adjuster** - Read access  
✅ **claims** - Read access  

---

## 📊 What's in a Report?

1. **Executive Summary** - Risk score, category, AI recommendation
2. **Medical Analysis** - Conditions, severity, risk impact
3. **Risk Factors** - Age, lifestyle, occupation, BMI
4. **Document Verification** - ID, medical records, authenticity
5. **AI Recommendations** - Approve/reject/refer with reasoning
6. **Action Buttons** - Download PDF, print, approve, reject

---

## 🔌 API Endpoints

### Get Report
```
GET /api/risk-assessment/report?id=<application_id>
GET /api/risk-assessment/report?customer_id=<customer_id>
GET /api/risk-assessment/report?email=<email>
```

### List Reports
```
GET /api/risk-assessment/list?page=1&page_size=50
```

**Query Parameters**:
- `risk_level` - Filter by risk (very_low, low, moderate, elevated, high, very_high)
- `status` - Filter by status (pending, approved, rejected, referred)

---

## 💻 JavaScript Integration

```javascript
// Link to risk report from your dashboard
function viewRiskReport(applicationId) {
    window.location.href = `/risk-assessment-viewer.html?id=${encodeURIComponent(applicationId)}`;
}

function viewCustomerRiskReport(customerId) {
    window.location.href = `/risk-assessment-viewer.html?customer_id=${encodeURIComponent(customerId)}`;
}
```

---

## 📈 Risk Categories

| Score | Category | Action |
|-------|----------|--------|
| 0-15% | Very Low | Auto-approve |
| 16-25% | Low | Approve standard |
| 26-40% | Moderate | Approve with possible loading |
| 41-55% | Elevated | Approve with loading/exclusions |
| 56-70% | High | Refer to senior underwriter |
| 71-100% | Very High | Likely decline |

---

## 🛠️ Troubleshooting

**"Access Denied"**  
→ Check you're logged in with correct role

**"No data available"**  
→ Verify application/customer ID exists

**Report loads slowly**  
→ Large reports take 5-10 seconds (normal)

---

## ✅ Quick Test

```bash
python3 test_risk_report_integration.py
```

Verifies:
- Data structure integrity
- API endpoints available
- Dashboard integration
- Role-based access
- Data protection

---

## 📚 Full Documentation

See [RISK_REPORTS_DASHBOARD_GUIDE.md](RISK_REPORTS_DASHBOARD_GUIDE.md) for complete guide.

---

**Need Help?** Contact: support@phins.ai  
**Version**: 1.0.0 | **Updated**: February 2026
