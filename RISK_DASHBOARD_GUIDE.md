# Risk Report System Dashboard - Access Guide

## 🔗 Dashboard URL

**Production URL:** `https://www.phins.ai/risk-assessment-viewer.html`

**Local Development URL:** `http://localhost:8000/risk-assessment-viewer.html`

---

## 📊 Overview

The Risk Assessment Report Dashboard is a comprehensive visualization tool for viewing detailed underwriting risk assessments. It provides a complete view of:

- Risk scores and classifications
- Medical conditions and their impact
- Risk factors analysis
- Underwriting recommendations
- Premium adjustments
- Applicant health profiles

---

## 🎯 Key Features

### 1. **Risk Score Visualization**
- Visual gauge showing overall risk score (0-100)
- Color-coded risk categories:
  - 🟢 **Low Risk** (0-30): Green
  - 🟡 **Medium Risk** (31-60): Yellow
  - 🟠 **High Risk** (61-80): Orange
  - 🔴 **Very High Risk** (81-100): Red

### 2. **Applicant Profile**
- Complete demographic information
- Policy type and coverage amount
- Smoking status and occupation
- Age and gender details

### 3. **Medical Conditions Assessment**
- Detailed list of medical conditions
- ICD-10 codes for each condition
- Risk impact percentage per condition
- Treatment status and notes
- Loading percentages and exclusion recommendations

### 4. **Risk Factors Analysis**
- Comprehensive list of risk factors
- Impact quantification (percentage)
- Direction indicators (increases/decreases risk)
- Explanations for each factor

### 5. **Underwriting Decision**
- Clear recommendation (Approve/Reject/Refer)
- Confidence level percentage
- Detailed rationale
- Premium adjustment recommendations

### 6. **Policy Exclusions & Requirements**
- List of recommended exclusions
- Special terms and conditions
- Monitoring requirements
- Medical review schedules

### 7. **Action Buttons**
- ✅ **Approve**: Accept the underwriting recommendation
- ❌ **Reject**: Decline the application
- 📥 **Download PDF**: Export the report
- 🖨️ **Print**: Print the assessment
- ⬅️ **Back**: Return to dashboard

---

## 🔗 API Integration

The dashboard integrates with the following REST API endpoints:

### Get Risk Assessment Report
```
GET /api/risk-assessment/report?application_id={id}
```

**Query Parameters:**
- `application_id` (required): The underwriting application ID

**Response Structure:**
```json
{
  "application_id": "UW001",
  "report_id": "RISK-RPT-001",
  "generated_date": "2026-02-03T17:00:00Z",
  "risk_score": 45.5,
  "risk_category": "medium",
  "recommendation": "approve",
  "confidence": 0.85,
  "applicant": {
    "name": "John Doe",
    "age": 35,
    "gender": "male",
    "smoking_status": "never"
  },
  "medical_conditions": [
    {
      "condition": "Hypertension",
      "icd_code": "I10",
      "severity": "moderate",
      "risk_impact": 0.15,
      "loading_percentage": 10
    }
  ],
  "risk_factors": [
    {
      "name": "Age Factor",
      "impact": 0.08,
      "direction": "increase",
      "explanation": "Age 35-40 increases baseline risk"
    }
  ],
  "premium_adjustment": 1.15,
  "recommended_exclusions": [],
  "monitoring_requirements": []
}
```

### List All Risk Assessment Reports
```
GET /api/risk-assessment/list
```

**Response:** Returns array of all generated risk assessment reports.

---

## 💻 Access Methods

### Method 1: Direct URL Access
Simply navigate to the URL in your browser:
```
https://www.phins.ai/risk-assessment-viewer.html?application_id=UW001
```

### Method 2: From Underwriter Dashboard
1. Login at `https://www.phins.ai/login.html`
2. Use credentials: `underwriter` / (set password)
3. Navigate to Underwriter Dashboard
4. Click on any application's "View Risk Report" button

### Method 3: From Admin Portal
1. Login as admin at `https://www.phins.ai/login.html`
2. Navigate to Admin Portal
3. Select "Underwriting" section
4. Click "View Risk Assessment" for any application

---

## 🛠️ Running Locally

### 1. Start the PHINS Server
```bash
cd /home/runner/work/phins/phins
python3 web_portal/server.py
```

The server will start on port **8000** by default.

### 2. Access the Dashboard
Open your browser and navigate to:
```
http://localhost:8000/risk-assessment-viewer.html?application_id=UW001
```

### 3. Test with Sample Data
The system automatically seeds sample underwriting applications on startup. You can view these reports immediately.

---

## 📋 URL Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `application_id` | string | Yes | The underwriting application ID to display |

### Example URLs:
```
# View specific application
/risk-assessment-viewer.html?application_id=UW001

# List view (shows all reports)
/risk-assessment-viewer.html
```

---

## 🔒 Security & Access Control

### Authentication
- The dashboard requires an active session
- Users must be logged in via `/login.html`
- Session timeout: 30 minutes of inactivity

### Role-Based Access
The following roles can access risk reports:
- **Underwriters**: Full access to all reports
- **Actuaries**: Read-only access
- **Admins**: Full access including bulk operations
- **Claims Adjusters**: Limited access (policy-related reports only)

---

## 📸 Dashboard Sections Breakdown

### Header Section
- Report ID and generated date
- Quick action buttons (Approve, Reject, Download, Print)
- Back navigation

### Risk Score Section
- Large circular gauge visualization
- Numeric score display (0-100)
- Color-coded risk category badge
- Score breakdown bars

### Applicant Information
- Personal details grid
- Policy information
- Coverage amounts
- Risk factors summary

### Medical Assessment
- Detailed conditions list
- Severity indicators (Severe, Moderate, Mild)
- Risk impact percentages
- Treatment status
- ICD-10 codes

### Risk Factors
- Itemized factor list
- Impact quantification
- Direction indicators (increases/decreases)
- Detailed explanations

### Underwriting Decision
- Large recommendation box
- Confidence percentage
- Detailed rationale
- Supporting factors vs. mitigations

### Premium Calculation
- Base premium
- Adjustment factor
- Final adjusted premium
- Loading breakdown

### Special Conditions
- Exclusions list (if any)
- Monitoring requirements
- Special terms and conditions

---

## 🎨 Visual Design

The dashboard uses a professional color scheme:
- **Primary Blue**: `#1a237e` (headers, accents)
- **Gradient Background**: Blue gradient for headers
- **Risk Colors**: 
  - Low: `#4caf50` (green)
  - Medium: `#ffc107` (yellow)
  - High: `#ff9800` (orange)
  - Very High: `#f44336` (red)

**Responsive Design:** The dashboard is fully responsive and works on:
- Desktop (1920px+)
- Laptop (1366px+)
- Tablet (768px+)
- Mobile (360px+)

---

## 🔧 Troubleshooting

### Issue: "Report Not Found"
**Solution:** Check that the `application_id` parameter is correct and the report exists in the system.

### Issue: "Unauthorized Access"
**Solution:** Ensure you're logged in with appropriate credentials. Navigate to `/login.html` first.

### Issue: "Server Not Responding"
**Solution:** Verify the PHINS server is running on port 8000. Check with:
```bash
curl http://localhost:8000/api/health
```

### Issue: "Data Not Loading"
**Solution:** 
1. Check browser console for errors (F12)
2. Verify API endpoint is accessible: `/api/risk-assessment/report?application_id=UW001`
3. Ensure database is initialized (if using persistent storage)

---

## 📊 Sample Data

The system includes sample risk assessment reports on startup:

| Application ID | Applicant Name | Risk Score | Recommendation |
|----------------|----------------|------------|----------------|
| UW001 | John Doe | 45.5 | Approve |
| UW002 | Jane Smith | 72.3 | Refer |
| UW003 | Bob Johnson | 25.8 | Approve |

---

## 🚀 Advanced Usage

### Batch Report Generation
Generate multiple reports programmatically:
```python
import requests

application_ids = ['UW001', 'UW002', 'UW003']
for app_id in application_ids:
    response = requests.get(f'http://localhost:8000/api/risk-assessment/report?application_id={app_id}')
    report = response.json()
    print(f"Report {app_id}: Risk Score = {report['risk_score']}")
```

### Export Reports to PDF
Use the built-in download button or call the API directly:
```javascript
// JavaScript example
async function downloadReport(applicationId) {
    const response = await fetch(`/api/risk-assessment/report?application_id=${applicationId}`);
    const report = await response.json();
    // Report data ready for PDF generation
}
```

---

## 📚 Related Documentation

- **[README.md](./README.md)** - Main PHINS documentation
- **[AI_ARCHITECTURE.md](./AI_ARCHITECTURE.md)** - AI-powered underwriting details
- **[UNDERWRITING_BOT_IMPLEMENTATION.md](./UNDERWRITING_BOT_IMPLEMENTATION.md)** - Automated underwriting
- **[AGENTS.md](./AGENTS.md)** - System architecture for agents
- **[API Documentation](./web_portal/server.py)** - Complete API reference

---

## 📞 Support

For issues or questions about the Risk Report Dashboard:
1. Check this guide first
2. Review the server logs: `web_portal/server.py` output
3. Contact the PHINS development team
4. File an issue on the repository

---

**Last Updated:** February 3, 2026
**Dashboard Version:** 1.0
**Compatible with:** PHINS v1.0.0+
