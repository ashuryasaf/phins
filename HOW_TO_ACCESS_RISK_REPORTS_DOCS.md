# How to Access Risk Reports Documentation

## Problem Solved ✅

You mentioned the documentation links "got you nowhere". This has been fixed!

## Solution: Web-Based Documentation Page

A new interactive documentation page has been created that you can access directly from your browser.

## 🌐 How to Access

### Option 1: Direct URL (Easiest)
Navigate to this URL in your PHINS system:
```
/risk-reports-documentation.html
```

Example: `http://localhost:8000/risk-reports-documentation.html`
Or: `https://www.phins.ai/risk-reports-documentation.html`

### Option 2: From Any Dashboard
1. Log into PHINS
2. Look for **"📚 Risk Reports Docs"** in the navigation menu
3. Click it to access the documentation

Available in:
- ✅ Home page (header and footer)
- ✅ Admin Dashboard
- ✅ Underwriter Dashboard
- ✅ Claims Adjuster Dashboard
- ✅ Actuary Dashboard

### Option 3: From GitHub
View the Markdown files directly on GitHub:
- [WHERE_TO_USE_RISK_REPORTS.md](https://github.com/ashuryasaf/phins/blob/copilot/add-risk-reports-dashboard/WHERE_TO_USE_RISK_REPORTS.md)
- [RISK_REPORTS_QUICK_REFERENCE.md](https://github.com/ashuryasaf/phins/blob/copilot/add-risk-reports-dashboard/RISK_REPORTS_QUICK_REFERENCE.md)
- [RISK_REPORTS_DASHBOARD_GUIDE.md](https://github.com/ashuryasaf/phins/blob/copilot/add-risk-reports-dashboard/RISK_REPORTS_DASHBOARD_GUIDE.md)
- [RISK_REPORTS_ARCHITECTURE.md](https://github.com/ashuryasaf/phins/blob/copilot/add-risk-reports-dashboard/RISK_REPORTS_ARCHITECTURE.md)

## 📊 What You'll Find

The new documentation page includes:

1. **Quick Start Guide** - Choose your learning path based on your needs
2. **Quick Answer Section** - Immediate answer to where you can use risk reports (4 locations)
3. **Cheat Sheet** - Quick reference with URLs and code examples
4. **Complete Guide Links** - Links to comprehensive documentation
5. **Architecture Details** - System design and technical specs

## 🎯 Quick Answer (Right Here!)

The risk reports dashboard can be accessed from **4 main locations**:

1. **Underwriter Dashboard** (`/underwriter-dashboard.html`)
   - Click "Risk Report" button on applications
   - URL: `/risk-assessment-viewer.html?id=<application_id>`

2. **Admin Dashboard** (`/admin.html`)
   - "Risk Assessment Reports" section
   - URL: `/risk-assessment-viewer.html?id=<underwriting_id>`

3. **Claims Adjuster Dashboard** (`/claims-adjuster-dashboard.html`)
   - Click "Risk Report" button on claims
   - URL: `/risk-assessment-viewer.html?customer_id=<customer_id>`

4. **Actuary Dashboard** (`/actuary-dashboard.html`)
   - Direct URL or API access
   - URL: `/risk-assessment-viewer.html`

## 💡 Note

The feature is implemented as **`risk-assessment-viewer.html`** (not `risk-reports-dashboard.html`).

## 🚀 Next Steps

1. Visit `/risk-reports-documentation.html` in your browser
2. Or log into any dashboard and click "📚 Risk Reports Docs"
3. Follow the Quick Start guide based on your role

---

**File Location**: This README is at `/home/runner/work/phins/phins/HOW_TO_ACCESS_RISK_REPORTS_DOCS.md`
**Documentation Page**: `/home/runner/work/phins/phins/web_portal/static/risk-reports-documentation.html`
**Last Updated**: February 2026
