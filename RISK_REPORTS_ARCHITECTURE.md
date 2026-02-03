# Risk Reports Dashboard - Integration Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                     PHINS RISK REPORTS DASHBOARD                              │
│                       Integration Architecture                                │
└─────────────────────────────────────────────────────────────────────────────┘

┌───────────────────────────────────────────────────────────────────────────────┐
│                          FRONTEND DASHBOARDS                                   │
└───────────────────────────────────────────────────────────────────────────────┘

    ┌─────────────────────┐
    │ Underwriter         │
    │ Dashboard           │──┐
    │ /underwriter-       │  │
    │  dashboard.html     │  │   Click "Risk Report" Button
    └─────────────────────┘  │   ──────────────────────────►
                             │
    ┌─────────────────────┐  │
    │ Admin Dashboard     │  │
    │ /admin.html         │──┤
    │                     │  │   View Risk Assessment Reports
    └─────────────────────┘  │   ──────────────────────────►
                             │
    ┌─────────────────────┐  │
    │ Claims Adjuster     │  │
    │ Dashboard           │──┤
    │ /claims-adjuster-   │  │   Click "Risk Report" Button
    │  dashboard.html     │  │   ──────────────────────────►
    └─────────────────────┘  │
                             │
    ┌─────────────────────┐  │
    │ Actuary Dashboard   │  │
    │ /actuary-           │──┘
    │  dashboard.html     │       Direct URL Access
    └─────────────────────┘       ──────────────────────────►

                             │
                             │
                             ▼
            ┌────────────────────────────────────────┐
            │   Risk Assessment Viewer Page          │
            │   /risk-assessment-viewer.html         │
            │                                        │
            │   Query Parameters:                    │
            │   • ?id=<application_id>              │
            │   • ?customer_id=<customer_id>        │
            │   • ?email=<customer_email>           │
            └────────────────────────────────────────┘
                             │
                             │ Fetches Data via API
                             ▼
┌───────────────────────────────────────────────────────────────────────────────┐
│                          BACKEND API LAYER                                     │
└───────────────────────────────────────────────────────────────────────────────┘

    ┌─────────────────────────────────────────────────────────────┐
    │  GET /api/risk-assessment/report                             │
    │      Parameters: id OR customer_id OR email                  │
    │      Returns: Complete risk assessment JSON                  │
    │      Auth: Requires session with role check                  │
    └─────────────────────────────────────────────────────────────┘
                             │
    ┌─────────────────────────────────────────────────────────────┐
    │  GET /api/risk-assessment/list                               │
    │      Parameters: page, page_size, risk_level, status         │
    │      Returns: Paginated list of assessments                  │
    │      Auth: Requires session with role check                  │
    └─────────────────────────────────────────────────────────────┘
                             │
                             │ Calls Service Layer
                             ▼
┌───────────────────────────────────────────────────────────────────────────────┐
│                       BUSINESS LOGIC LAYER                                     │
└───────────────────────────────────────────────────────────────────────────────┘

    ┌─────────────────────────────────────────────────────────────┐
    │  services/risk_report_generator.py                           │
    │                                                              │
    │  • RiskReportGenerator                                       │
    │  • calculate_risk_score()                                    │
    │  • assess_medical_conditions()                               │
    │  • verify_documents()                                        │
    │  • generate_recommendations()                                │
    │  • format_report() → HTML/JSON/PDF                           │
    └─────────────────────────────────────────────────────────────┘
                             │
                             │ Reads from Data Stores
                             ▼
┌───────────────────────────────────────────────────────────────────────────────┐
│                          DATA LAYER (READ-ONLY)                                │
└───────────────────────────────────────────────────────────────────────────────┘

    ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐
    │ CUSTOMERS        │  │ POLICIES         │  │ CLAIMS           │
    │ Dictionary/DB    │  │ Dictionary/DB    │  │ Dictionary/DB    │
    └──────────────────┘  └──────────────────┘  └──────────────────┘
               │                     │                     │
               └─────────────────────┴─────────────────────┘
                             │
    ┌──────────────────────────────────────────────────────────────┐
    │ UNDERWRITING_APPLICATIONS                                     │
    │ Dictionary/DB                                                 │
    │                                                               │
    │ Contains:                                                     │
    │ • Risk scores                                                 │
    │ • Medical conditions                                          │
    │ • Underwriting decisions                                      │
    │ • Document verification                                       │
    └──────────────────────────────────────────────────────────────┘


┌───────────────────────────────────────────────────────────────────────────────┐
│                       ROLE-BASED ACCESS CONTROL                                │
└───────────────────────────────────────────────────────────────────────────────┘

    ┌─────────────┬─────────────────┬─────────────────────────────────────────┐
    │ Role        │ Access Level    │ Typical Use Case                         │
    ├─────────────┼─────────────────┼─────────────────────────────────────────┤
    │ admin       │ Full Access     │ Executive oversight, all reports         │
    │ underwriter │ Full Access     │ Primary underwriting workflow            │
    │ actuary     │ Full Access     │ Pricing and portfolio analysis           │
    │ claims_adj. │ Read Access     │ Claims assessment support                │
    │ claims      │ Read Access     │ Claims processing support                │
    └─────────────┴─────────────────┴─────────────────────────────────────────┘


┌───────────────────────────────────────────────────────────────────────────────┐
│                          REPORT COMPONENTS                                     │
└───────────────────────────────────────────────────────────────────────────────┘

    ┌─────────────────────────────────────────────────────────────┐
    │ 1. EXECUTIVE SUMMARY                                         │
    │    • Overall risk score (0-100%)                             │
    │    • Risk category (Very Low → Very High)                    │
    │    • AI recommendation (Approve/Reject/Refer)                │
    │    • Premium loading recommendation                          │
    └─────────────────────────────────────────────────────────────┘

    ┌─────────────────────────────────────────────────────────────┐
    │ 2. MEDICAL CONDITION ANALYSIS                                │
    │    • Pre-existing conditions with ICD codes                  │
    │    • Severity assessments                                    │
    │    • Treatment history                                       │
    │    • Risk impact calculations                                │
    │    • Exclusion recommendations                               │
    └─────────────────────────────────────────────────────────────┘

    ┌─────────────────────────────────────────────────────────────┐
    │ 3. RISK FACTOR BREAKDOWN                                     │
    │    • Age-related risk                                        │
    │    • Lifestyle factors (smoking, alcohol)                    │
    │    • Occupation hazards                                      │
    │    • BMI and health metrics                                  │
    │    • Family medical history                                  │
    └─────────────────────────────────────────────────────────────┘

    ┌─────────────────────────────────────────────────────────────┐
    │ 4. DOCUMENT VERIFICATION                                     │
    │    • Identity verification status                            │
    │    • Medical records authenticity                            │
    │    • Document expiry tracking                                │
    │    • Fraud detection flags                                   │
    └─────────────────────────────────────────────────────────────┘

    ┌─────────────────────────────────────────────────────────────┐
    │ 5. AI-POWERED RECOMMENDATIONS                                │
    │    • Approval/Rejection recommendation                       │
    │    • Premium loading suggestions                             │
    │    • Required medical examinations                           │
    │    • Exclusion clauses                                       │
    │    • Referral reasons                                        │
    └─────────────────────────────────────────────────────────────┘


┌───────────────────────────────────────────────────────────────────────────────┐
│                     WORKFLOW INTEGRATION EXAMPLES                              │
└───────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│ SCENARIO 1: Underwriter Reviews Application                                  │
├─────────────────────────────────────────────────────────────────────────────┤
│ 1. Underwriter logs in → Underwriter Dashboard                               │
│ 2. Views pending applications list                                           │
│ 3. Clicks "Risk Report" button on application row                            │
│ 4. System navigates to: /risk-assessment-viewer.html?id=UW-001               │
│ 5. API fetches risk assessment data                                          │
│ 6. Report displays with AI recommendation                                    │
│ 7. Underwriter reviews and makes decision                                    │
│ 8. Clicks "Approve" or "Reject" button on report                             │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│ SCENARIO 2: Claims Adjuster Assesses Claim                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│ 1. Claims adjuster logs in → Claims Dashboard                                │
│ 2. Opens claim for review                                                    │
│ 3. Clicks "Risk Report" to view customer profile                             │
│ 4. System navigates to: /risk-assessment-viewer.html?customer_id=CUST-001    │
│ 5. Reviews medical history and risk factors                                  │
│ 6. Cross-references with claim details                                       │
│ 7. Makes informed claims decision                                            │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│ SCENARIO 3: Actuary Performs Portfolio Analysis                              │
├─────────────────────────────────────────────────────────────────────────────┤
│ 1. Actuary logs in → Actuary Dashboard                                       │
│ 2. Uses API: GET /api/risk-assessment/list?page=1&page_size=1000             │
│ 3. Aggregates risk scores across portfolio                                   │
│ 4. Analyzes risk distribution                                                │
│ 5. Validates pricing models against actual risk                              │
│ 6. Recommends reserve adjustments                                            │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│ SCENARIO 4: Admin Executive Oversight                                        │
├─────────────────────────────────────────────────────────────────────────────┤
│ 1. Admin logs in → Admin Dashboard                                           │
│ 2. Clicks "Risk Assessment Reports" section                                  │
│ 3. Reviews high-risk applications                                            │
│ 4. Monitors underwriter decisions                                            │
│ 5. Clicks specific application for detailed report                           │
│ 6. Generates executive summary reports                                       │
└─────────────────────────────────────────────────────────────────────────────┘


┌───────────────────────────────────────────────────────────────────────────────┐
│                          SECURITY & DATA INTEGRITY                             │
└───────────────────────────────────────────────────────────────────────────────┘

    ✓ Session-based authentication required
    ✓ Role-based access control enforced
    ✓ All customer data is READ-ONLY
    ✓ No modifications to customer/policy/claims data
    ✓ Audit logs maintained for all access
    ✓ PII masked in non-essential views
    ✓ HIPAA/GDPR compliance ready
    ✓ XSS protection via HTML escaping
    ✓ API rate limiting applied
    ✓ Data isolation per customer


┌───────────────────────────────────────────────────────────────────────────────┐
│                        KEY FILES & LOCATIONS                                   │
└───────────────────────────────────────────────────────────────────────────────┘

    Frontend:
    ─────────
    /web_portal/static/risk-assessment-viewer.html    Main report viewer page
    /web_portal/static/underwriter-dashboard.html     Underwriter integration
    /web_portal/static/admin.html                     Admin integration
    /web_portal/static/claims-adjuster-dashboard.html Claims integration
    /web_portal/static/actuary-dashboard.html         Actuary dashboard

    Backend:
    ────────
    /web_portal/server.py                             API endpoints & routing
    /services/risk_report_generator.py                Report generation logic

    Documentation:
    ──────────────
    /RISK_REPORTS_DASHBOARD_GUIDE.md                  Complete usage guide
    /RISK_REPORTS_QUICK_REFERENCE.md                  Quick reference card
    /test_risk_report_integration.py                  Integration test suite


┌───────────────────────────────────────────────────────────────────────────────┐
│                            QUICK LINKS                                         │
└───────────────────────────────────────────────────────────────────────────────┘

    📚 Full Documentation:    RISK_REPORTS_DASHBOARD_GUIDE.md
    📋 Quick Reference:       RISK_REPORTS_QUICK_REFERENCE.md
    🧪 Integration Tests:     python3 test_risk_report_integration.py
    🌐 Live Access:           www.phins.ai/risk-assessment-viewer.html

```

---

**Version**: 1.0.0  
**Last Updated**: February 2026  
**Platform**: PHINS Insurance Management System
