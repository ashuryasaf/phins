# PHINS Risk Reports Dashboard - Usage Guide

## 🚀 Overview

The Risk Reports Dashboard is a comprehensive risk assessment and reporting system integrated throughout the PHINS platform. It provides AI-powered risk analysis, detailed medical assessments, and actionable recommendations for underwriting decisions.

## 📍 Where to Access Risk Reports

Risk reports are accessible from multiple locations across the PHINS platform, depending on your role and workflow needs:

### 1. **Underwriter Dashboard** (`/underwriter-dashboard.html`)
**Primary Use Case**: Review risk assessments during the underwriting process

**How to Access**:
- Navigate to the Underwriter Dashboard
- Find any pending application in the applications list
- Click the **"Risk Report"** button on the application row
- The risk assessment report will open in a new view

**URL Pattern**: 
```
/risk-assessment-viewer.html?id=<application_id>
```

**Best For**:
- Reviewing individual application risk profiles
- Making approve/reject/refer decisions
- Assessing medical conditions and risk factors
- Viewing AI-powered recommendations

---

### 2. **Admin Dashboard** (`/admin.html`)
**Primary Use Case**: Executive oversight and underwriting supervision

**How to Access**:
- Navigate to the Admin Dashboard
- Go to the **"Underwriting Division — Risk Assessment"** section
- Click on **"🔒 Risk Assessment Reports"** link in the navigation
- Or click the **"Risk Report"** button next to any underwriting application

**URL Patterns**:
```
/risk-assessment-viewer.html
/risk-assessment-viewer.html?id=<underwriting_id>
```

**Best For**:
- High-level risk portfolio review
- Supervising underwriting decisions
- Auditing risk assessments
- Executive reporting

---

### 3. **Claims Adjuster Dashboard** (`/claims-adjuster-dashboard.html`)
**Primary Use Case**: Review customer risk profile when processing claims

**How to Access**:
- Navigate to the Claims Adjuster Dashboard
- When viewing a claim, click the **"Risk Report"** button
- The system will fetch the risk profile for the customer associated with the claim

**URL Pattern**:
```
/risk-assessment-viewer.html?customer_id=<customer_id>
```

**Best For**:
- Understanding customer risk profile during claims assessment
- Detecting potential fraud patterns
- Cross-referencing medical history with claim details
- Making informed claims decisions

---

### 4. **Actuary Dashboard** (`/actuary-dashboard.html`)
**Primary Use Case**: Actuarial analysis and pricing model validation

**How to Access**:
- Navigate to the Actuary Dashboard
- Click on **"Risk Reports"** link in the navigation menu
- Access aggregate risk assessment data for portfolio analysis

**URL Pattern**:
```
/risk-assessment-viewer.html
```

**Best For**:
- Portfolio risk analysis
- Pricing model validation
- Loss ratio calculations
- Reserve adequacy assessment

---

### 5. **Direct URL Access**
**Primary Use Case**: Deep linking and API integration

**URL Patterns**:
```
# By Application ID
/risk-assessment-viewer.html?id=<application_id>

# By Customer ID
/risk-assessment-viewer.html?customer_id=<customer_id>

# By Customer Email
/risk-assessment-viewer.html?email=<customer_email>
```

**Examples**:
```
/risk-assessment-viewer.html?id=UW-001
/risk-assessment-viewer.html?customer_id=CUST-ASAF-001
/risk-assessment-viewer.html?email=asaf@assurance.co.il
```

**Best For**:
- API integrations
- External system linking
- Email notifications with direct links
- Bookmarking specific reports

---

## 🔐 Role-Based Access Control

Risk reports are accessible to the following roles:

| Role | Access Level | Use Case |
|------|--------------|----------|
| **admin** | Full Access | Executive oversight, all reports |
| **underwriter** | Full Access | Primary underwriting workflow |
| **actuary** | Full Access | Pricing and portfolio analysis |
| **claims_adjuster** | Read Access | Claims assessment support |
| **claims** | Read Access | Claims processing support |

**Security Note**: All access is session-based. Users must be logged in to view risk reports.

---

## 📊 Report Features

### What's Included in a Risk Report:

1. **Executive Summary**
   - Overall risk score (0-100%)
   - Risk category (Very Low to Very High)
   - AI recommendation (Auto-Approve, Refer, Decline, etc.)
   - Premium loading recommendation

2. **Medical Condition Analysis**
   - Pre-existing conditions with ICD codes
   - Severity assessments
   - Treatment history
   - Risk impact calculations
   - Exclusion recommendations

3. **Risk Factor Breakdown**
   - Age-related risk
   - Lifestyle factors (smoking, alcohol)
   - Occupation hazards
   - BMI and health metrics
   - Family medical history

4. **Document Verification**
   - Identity verification status
   - Medical records authenticity
   - Document expiry tracking
   - Fraud detection flags

5. **AI-Powered Recommendations**
   - Approval/Rejection recommendation
   - Premium loading suggestions
   - Required medical examinations
   - Exclusion clauses
   - Referral reasons

6. **Action Buttons**
   - Download PDF report
   - Print report
   - Approve application
   - Reject application
   - Back to dashboard

---

## 🔌 API Endpoints

The risk reports system exposes the following API endpoints:

### Generate Risk Assessment Report
```
GET /api/risk-assessment/report?id=<application_id>
GET /api/risk-assessment/report?customer_id=<customer_id>
GET /api/risk-assessment/report?email=<email>
```

**Response Format**: JSON with complete risk assessment data

**Authentication**: Requires valid session with appropriate role

**Rate Limiting**: Standard API rate limits apply

---

### List All Risk Assessments
```
GET /api/risk-assessment/list
```

**Query Parameters**:
- `page` - Page number (default: 1)
- `page_size` - Results per page (default: 50)
- `risk_level` - Filter by risk level (very_low, low, moderate, elevated, high, very_high)
- `status` - Filter by status (pending, approved, rejected, referred)

**Response Format**: Paginated JSON list

**Authentication**: Requires valid session with appropriate role

---

## 🎯 Usage Scenarios

### Scenario 1: New Application Review (Underwriter)
1. Log in as underwriter
2. Navigate to Underwriter Dashboard
3. View pending applications
4. Click **"Risk Report"** on application
5. Review AI recommendation and risk factors
6. Make decision (Approve/Reject/Refer)
7. Document decision reasons

### Scenario 2: Claims Assessment (Claims Adjuster)
1. Log in as claims adjuster
2. Navigate to Claims Dashboard
3. Open a claim for review
4. Click **"Risk Report"** to view customer profile
5. Cross-reference medical history with claim details
6. Detect any inconsistencies or fraud patterns
7. Make informed claims decision

### Scenario 3: Portfolio Analysis (Actuary)
1. Log in as actuary
2. Navigate to Actuary Dashboard
3. Click **"Risk Reports"** link
4. Use API endpoint to fetch aggregate data
5. Analyze risk distribution across portfolio
6. Validate pricing models
7. Recommend reserve adjustments

### Scenario 4: Executive Oversight (Admin)
1. Log in as admin
2. Navigate to Admin Dashboard
3. Access **"Risk Assessment Reports"** section
4. Review high-risk applications
5. Monitor underwriter decisions
6. Generate executive reports

---

## 🛠️ Technical Integration

### Frontend Integration
The risk assessment viewer is located at:
```
/home/runner/work/phins/phins/web_portal/static/risk-assessment-viewer.html
```

### Backend Service
Risk report generation is handled by:
```
/home/runner/work/phins/phins/services/risk_report_generator.py
```

### JavaScript Integration
To link to a risk report from your dashboard:
```javascript
// By application ID
function viewRiskReport(applicationId) {
    window.location.href = `/risk-assessment-viewer.html?id=${encodeURIComponent(applicationId)}`;
}

// By customer ID
function viewCustomerRiskReport(customerId) {
    window.location.href = `/risk-assessment-viewer.html?customer_id=${encodeURIComponent(customerId)}`;
}

// By email
function viewRiskReportByEmail(email) {
    window.location.href = `/risk-assessment-viewer.html?email=${encodeURIComponent(email)}`;
}
```

---

## 📋 Data Integrity & Security

### Read-Only Access
- Risk reports **only read** data from the system
- No modifications are made to customer, policy, or claims data
- All customer data remains secure and isolated

### Data Sources
Risk reports aggregate data from:
- Customer profiles
- Underwriting applications
- Medical history
- Claims history
- Policy information
- External medical records (when available)

### Privacy Compliance
- All medical data is handled per HIPAA/GDPR guidelines
- Access logs are maintained for audit trails
- PII is masked in non-essential views
- Data retention policies are enforced

---

## 🚀 Getting Started

### For Underwriters
1. Complete training on risk assessment interpretation
2. Familiarize yourself with AI recommendation types
3. Practice with sample applications
4. Use the **"Risk Report"** button during application review
5. Document your decisions with reference to risk factors

### For Administrators
1. Set up role-based access for your team
2. Configure risk thresholds per organizational policy
3. Monitor report usage and audit trails
4. Generate executive summaries periodically

### For Claims Adjusters
1. Use risk reports as supplementary information
2. Cross-reference with claim details
3. Flag inconsistencies for investigation
4. Do not use risk scores as sole decision criteria

### For Actuaries
1. Use API endpoints for bulk data retrieval
2. Integrate with actuarial modeling tools
3. Track risk distribution trends over time
4. Validate pricing models against actual risk profiles

---

## 📞 Support & Troubleshooting

### Common Issues

**Issue**: "Access Denied" when viewing report
- **Solution**: Ensure you're logged in with the correct role (admin, underwriter, actuary, claims_adjuster, or claims)

**Issue**: Report shows "No data available"
- **Solution**: Verify the application/customer ID exists and has underwriting data

**Issue**: Report loads slowly
- **Solution**: Large reports with extensive medical history may take 5-10 seconds to generate

### Testing
Run the integration test to verify system status:
```bash
python3 test_risk_report_integration.py
```

This will verify:
- Data structure integrity
- API endpoint availability
- Dashboard integration
- Role-based access control
- Data protection measures

---

## 📚 Related Documentation

- [Admin Portal Guide](ADMIN_PORTAL_GUIDE.md) - Complete admin features
- [Customer Application Guide](CUSTOMER_APPLICATION_GUIDE.md) - Customer-facing workflows
- [Underwriting Bot Implementation](UNDERWRITING_BOT_IMPLEMENTATION.md) - AI automation details
- [Agents Guide](AGENTS.md) - AI agent instructions
- [Security Documentation](SECURITY.md) - Security architecture

---

## 🎓 Best Practices

1. **Always review the full report** - Don't rely solely on AI recommendations
2. **Document your decisions** - Include risk factors in your decision notes
3. **Update risk assessments** - When new information becomes available
4. **Maintain consistency** - Follow organizational guidelines for risk thresholds
5. **Protect privacy** - Only access reports when necessary for your role
6. **Audit regularly** - Review report access logs periodically
7. **Train staff** - Ensure all users understand how to interpret risk scores

---

## 📊 Risk Assessment Calculation

### Risk Score Components

The overall risk score is calculated using:

```
Base Risk: 15%
+ Age Risk: (age - 18) / 1000
+ Medical Conditions: Sum of condition risk impacts
+ BMI Risk: (BMI - 25) / 100 (if BMI > 25)
+ Lifestyle Risk: Smoking (30%), Alcohol (10-20%), Hazardous activities (5-25%)
+ Occupation Risk: 0-20% based on occupation hazard level
+ Family History: 5-15% based on hereditary conditions
= Overall Risk Score (capped at 100%)
```

### Risk Categories

| Score Range | Category | Action |
|-------------|----------|--------|
| 0-15% | Very Low | Auto-approve (standard rates) |
| 16-25% | Low | Approve (standard rates) |
| 26-40% | Moderate | Approve with possible loading |
| 41-55% | Elevated | Approve with loading or exclusions |
| 56-70% | High | Refer to senior underwriter |
| 71-100% | Very High | Likely decline or significant loading |

---

## ✅ Quick Reference

| Need | Location | Button/Link |
|------|----------|-------------|
| Review application risk | Underwriter Dashboard | "Risk Report" button |
| Executive oversight | Admin Dashboard | "Risk Assessment Reports" link |
| Claims assessment | Claims Dashboard | "Risk Report" button |
| Portfolio analysis | Actuary Dashboard | "Risk Reports" link |
| Direct access | Browser | `/risk-assessment-viewer.html?id=<id>` |

---

**Last Updated**: February 2026  
**Version**: 1.0.0  
**Platform**: PHINS Insurance Management System
