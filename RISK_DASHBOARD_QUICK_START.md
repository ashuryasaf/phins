# Risk Report Dashboard - Quick Start Guide

## 🔗 Direct Access Links

### Production (Live)
```
https://www.phins.ai/risk-assessment-viewer.html
```

### Local Development
```
http://localhost:8000/risk-assessment-viewer.html
```

---

## ⚡ Quick Start (3 Steps)

### Step 1: Start the Server
```bash
cd /home/runner/work/phins/phins
python3 web_portal/server.py
```

### Step 2: Login
Navigate to: `http://localhost:8000/login.html`

**Default Credentials:**
- Username: `underwriter`
- Password: `under123` (or as configured)

### Step 3: Access Dashboard
Navigate to: `http://localhost:8000/risk-assessment-viewer.html?application_id=UW001`

**Sample Application IDs:** UW001, UW002, UW003

---

## 📸 What You'll See

The dashboard displays:

1. **Header** - Report ID, actions (Approve/Reject/Download/Print)
2. **Risk Score** - Large circular gauge with color-coded categories
3. **Applicant Info** - Demographics, policy details, coverage amounts
4. **Medical Conditions** - Detailed health assessment with ICD-10 codes
5. **Risk Factors** - Itemized risk analysis with impact percentages
6. **Recommendation** - Clear underwriting decision with rationale
7. **Premium Calculation** - Base + adjustments = final premium

---

## 🎯 Use Cases

### For Underwriters
- Review risk assessments before approval
- Evaluate medical conditions impact
- Validate premium adjustments
- Export reports for compliance

### For Actuaries
- Analyze risk scoring methodology
- Review premium calculation logic
- Validate actuarial assumptions
- Track portfolio risk distribution

### For Admins
- Audit underwriting decisions
- Review historical risk reports
- Monitor underwriter performance
- Generate compliance reports

---

## 🔌 API Endpoints

### Get Single Report
```bash
curl http://localhost:8000/api/risk-assessment/report?application_id=UW001
```

### List All Reports
```bash
curl http://localhost:8000/api/risk-assessment/list
```

**Note:** API requires authentication. Login first via `/api/login`

---

## 🛠️ Troubleshooting

### Issue: Page loads but no data shows
**Fix:** Add `?application_id=UW001` to the URL

### Issue: "Access Denied" error
**Fix:** Login first at `/login.html` with valid credentials

### Issue: Server not starting
**Fix:** Check if port 8000 is available:
```bash
lsof -i :8000  # Check what's using port 8000
```

### Issue: 404 Not Found
**Fix:** Ensure you're in the correct directory:
```bash
cd /home/runner/work/phins/phins
ls web_portal/static/risk-assessment-viewer.html  # Should exist
```

---

## 📚 Full Documentation

For complete details, see:
- **[RISK_DASHBOARD_GUIDE.md](./RISK_DASHBOARD_GUIDE.md)** - Complete access guide
- **[README.md](./README.md)** - System overview
- **[AGENTS.md](./AGENTS.md)** - Architecture details

---

**Quick Link Summary:**

| Environment | URL |
|-------------|-----|
| **Production** | https://www.phins.ai/risk-assessment-viewer.html |
| **Local** | http://localhost:8000/risk-assessment-viewer.html |
| **Login** | http://localhost:8000/login.html |
| **Health Check** | http://localhost:8000/api/health |

---

**Last Updated:** February 3, 2026
