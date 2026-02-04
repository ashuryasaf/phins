# QUICK START: Risk Dashboard Upload

## 🚀 Access the Risk Dashboard

### URL
```
https://phins-portal-production.up.railway.app/risk-dashboard.html
```

### Who Can Access?
- ✅ **Admin** (full access)
- ✅ **Underwriter** (full access)
- ✅ **Actuary** (full access)
- ❌ Others (redirected to main dashboard)

## 📝 Step-by-Step Usage

### 1. Login
```
URL: https://phins-portal-production.up.railway.app/login.html
Credentials:
  - Username: underwriter
  - Password: under123
```

### 2. Navigate to Risk Dashboard
```
https://phins-portal-production.up.railway.app/risk-dashboard.html
```

### 3. Upload File

**Option A: Drag & Drop**
- Drag your JSON or CSV file to the upload area
- File is validated automatically

**Option B: Browse**
- Click "Choose File"
- Select JSON or CSV file (max 10MB)

### 4. Review File Info
- Check filename, size, and type
- Verify data is correct

### 5. Process Upload
- Click "✓ Process Upload" button
- Watch progress bar
- Wait for results

### 6. View Results
- See counts: processed, created, updated
- Review any errors
- Get upload ID for tracking

## 📊 Data Format

### JSON Format
```json
{
  "data": [
    {
      "customer_id": "CUST-001",
      "risk_score": 45.5,
      "assessment_date": "2024-02-04",
      "medical_conditions": "None",
      "occupation_risk": "Low",
      "lifestyle_factors": "Non-smoker",
      "premium_loading": 0
    }
  ]
}
```

### CSV Format
```csv
customer_id,risk_score,assessment_date,medical_conditions,occupation_risk,lifestyle_factors,premium_loading
CUST-001,45.5,2024-02-04,None,Low,Non-smoker,0
CUST-002,65.0,2024-02-04,Diabetes Type 2,Medium,Smoker,15
```

## ✅ Required Fields
- **customer_id** OR **email** (one required)
- **risk_score** (number, 0-100)
- **assessment_date** (YYYY-MM-DD format)

## 📋 Optional Fields
- medical_conditions (string)
- occupation_risk (Low/Medium/High)
- lifestyle_factors (string)
- premium_loading (number, percentage)
- status (defaults to 'pending')

## ⚠️ Common Issues

### "Access Denied"
- **Cause**: Not logged in with correct role
- **Fix**: Login as admin, underwriter, or actuary

### "Invalid file type"
- **Cause**: File is not JSON or CSV
- **Fix**: Convert to JSON or CSV format

### "File too large"
- **Cause**: File exceeds 10MB
- **Fix**: Split into smaller files

### "risk_score must be between 0 and 100"
- **Cause**: Invalid risk score value
- **Fix**: Use values from 0 to 100

### "Customer not found"
- **Cause**: customer_id doesn't exist
- **Fix**: Use existing customer ID or create customer first

## 🔍 Testing Locally

### Start Server
```bash
cd /home/runner/work/phins/phins
python3 web_portal/server.py
```

### Run Tests
```bash
# Logic tests
python3 test_risk_dashboard_upload.py

# Integration tests (requires server running)
python3 test_risk_dashboard_integration.py
```

### Access Locally
```
http://localhost:8000/risk-dashboard.html
```

## 📚 Documentation

- **Fix Summary**: `RISK_DASHBOARD_FIX_SUMMARY.md`
- **Architecture**: `RISK_DASHBOARD_ARCHITECTURE.md`
- **Tests**: `test_risk_dashboard_*.py`

## 🆘 Support

If you encounter issues:
1. Check browser console for errors
2. Verify you're logged in with correct role
3. Validate your data format
4. Review error messages in the results
5. Check server logs for details

## ✨ Success Indicators

- ✅ Page loads without errors
- ✅ User info displayed (username, role)
- ✅ Upload area is interactive
- ✅ File validation works
- ✅ Upload completes successfully
- ✅ Results show processed counts
- ✅ Data is saved to database

---

**Status**: ✅ Production Ready  
**Last Updated**: February 4, 2024  
**Version**: 1.0.0
