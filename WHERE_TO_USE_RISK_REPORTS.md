# Where Can I Use risk-reports-dashboard.html?

## Quick Answer

The risk reports dashboard (implemented as `risk-assessment-viewer.html`) can be accessed from **4 main locations** in the PHINS platform:

### 1. ✅ Underwriter Dashboard
- **Location**: `/underwriter-dashboard.html`
- **How**: Click the **"Risk Report"** button on any application
- **Access Pattern**: `?id=<application_id>`

### 2. ✅ Admin Dashboard  
- **Location**: `/admin.html`
- **How**: 
  - Click **"Risk Assessment Reports"** link in the Underwriting section
  - Or click **"Risk Report"** button on any application
- **Access Pattern**: `?id=<underwriting_id>`

### 3. ✅ Claims Adjuster Dashboard
- **Location**: `/claims-adjuster-dashboard.html`
- **How**: Click the **"Risk Report"** button when viewing a claim
- **Access Pattern**: `?customer_id=<customer_id>`

### 4. ✅ Actuary Dashboard
- **Location**: `/actuary-dashboard.html`
- **How**: Access via direct URL or API for portfolio analysis
- **Access Pattern**: Direct URL access or API calls

---

## Direct URL Access

You can also access risk reports directly via URL:

```
# By Application ID
/risk-assessment-viewer.html?id=UW-001

# By Customer ID  
/risk-assessment-viewer.html?customer_id=CUST-ASAF-001

# By Email
/risk-assessment-viewer.html?email=asaf@assurance.co.il
```

---

## Who Can Access?

✅ **admin** - Full access  
✅ **underwriter** - Full access  
✅ **actuary** - Full access  
✅ **claims_adjuster** - Read access  
✅ **claims** - Read access

---

## File Note

The feature is implemented as `risk-assessment-viewer.html` (not `risk-reports-dashboard.html`). The viewer page:
- Located at: `/home/runner/work/phins/phins/web_portal/static/risk-assessment-viewer.html`
- Provides comprehensive risk assessment reports
- Includes AI-powered recommendations
- Supports PDF download and print functionality
- Integrates with multiple dashboards

---

## Complete Documentation

📚 **Full Guide**: [RISK_REPORTS_DASHBOARD_GUIDE.md](RISK_REPORTS_DASHBOARD_GUIDE.md)  
📋 **Quick Reference**: [RISK_REPORTS_QUICK_REFERENCE.md](RISK_REPORTS_QUICK_REFERENCE.md)  
🏗️ **Architecture**: [RISK_REPORTS_ARCHITECTURE.md](RISK_REPORTS_ARCHITECTURE.md)  
🧪 **Test**: Run `python3 test_risk_report_integration.py`

---

## Visual Map

```
Underwriter Dashboard ──► [Risk Report Button] ──► Risk Assessment Viewer
Admin Dashboard ───────► [Risk Report Button] ──► Risk Assessment Viewer
Claims Dashboard ──────► [Risk Report Button] ──► Risk Assessment Viewer
Actuary Dashboard ─────► [Direct URL Access] ──► Risk Assessment Viewer
```

---

**Need more details?** See the full documentation guides linked above.

**Platform**: PHINS Insurance Management System  
**Version**: 1.0.0 | **Updated**: February 2026
