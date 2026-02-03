# Dashboard Loading Issues - Troubleshooting Guide

## Problem: Endless Loading Spinner on Dashboard

Users cannot access the customer dashboard after logging in. The page shows an endless loading spinner with the PHINS splash screen.

## Root Causes & Solutions

### 1. Database Connection Issues

**Symptoms:**
- Dashboard never loads
- Splash screen shows indefinitely
- No error messages displayed

**Diagnosis:**
```bash
# Check database health
curl https://phins-portal-production.up.railway.app/api/health

# Check database connection
curl https://phins-portal-production.up.railway.app/api/diagnostics/db-test
```

**Expected Healthy Response:**
```json
{
  "status": "healthy",
  "database": "connected",
  "database_enabled": true,
  "database_connected": true,
  "storage_mode": "database"
}
```

**Fix for PostgreSQL Connection Failures:**

If you see `"database": "disconnected"` or `"database": "disabled"`:

1. **Delete the failing PostgreSQL service in Railway**
   - Go to Railway Dashboard
   - Find the PostgreSQL service (e.g., "Postgres-AyKP")
   - Delete it

2. **Create a new PostgreSQL service**
   - Click "+ New"
   - Select "Database" → "PostgreSQL"
   - Wait for deployment to complete

3. **Link DATABASE_URL to web service**
   - Go to your web service (phins-portal)
   - Click "Variables"
   - Delete old DATABASE_URL if present
   - Click "Add Reference"
   - Select the new PostgreSQL service
   - Select `DATABASE_URL` variable

4. **Verify environment variables are set**
   ```
   USE_DATABASE=true
   ENABLE_LEDGER_PERSISTENCE=true
   ```

5. **Redeploy the web service**
   - The service should auto-deploy
   - Watch logs for "✓ Database connection verified"

**Detailed Guide:** See `RAILWAY_POSTGRES_FIX.md`

### 2. Missing customer_id in Session

**Symptoms:**
- Login succeeds but dashboard shows "Access denied" or 403 errors
- Console shows: "Customer session invalid - no customer_id"

**Diagnosis:**
Check browser console (F12) for error messages like:
```
[loadCustomerInfo] Access denied to customer summary - customer_id may be invalid
```

**Fix:**
The server has automatic recovery logic:

1. **Session Validation Recovery** (automatic)
   - The `/api/session/validate` endpoint attempts to recover `customer_id` from:
     - In-memory CUSTOMERS dict
     - REGISTERED_CUSTOMERS dict  
     - Database (if connected)
     - Auto-generation (last resort)

2. **Customer ID Guarantee** (automatic)
   - The `get_customer_id_guaranteed()` function ensures customer role ALWAYS gets a valid `customer_id`
   - Uses 5-layer fallback strategy
   - Auto-generates ID if all else fails

**Manual Recovery:**
If automatic recovery fails, have user log out and log in again:
```javascript
// Clear storage
localStorage.clear();
sessionStorage.clear();
// Redirect to login
window.location.href = '/login.html';
```

### 3. API Endpoint Failures

**Symptoms:**
- Splash screen shows for 8 seconds then disappears
- Dashboard loads but some sections are empty
- Console shows multiple fetch errors

**Diagnosis:**
Check browser console for failed API requests:
- `/api/customer/summary` - 403 or 400 errors
- `/api/customers` - No data returned
- `/api/policies` - Empty array

**Fix:**
The dashboard now has improved error handling:

1. **Graceful Degradation** (implemented)
   - Uses `Promise.allSettled` instead of `Promise.all`
   - Partial failures don't block entire dashboard
   - Shows error notification but still displays available data

2. **Health Check** (implemented)
   - Dashboard checks `/api/health` before loading data
   - Detects database connectivity issues early
   - Shows warning if database is disconnected

3. **Fallback Values** (implemented)
   - Sets zeros for stats when API fails
   - Displays basic customer info even without database

### 4. Authentication Token Issues

**Symptoms:**
- Dashboard redirects back to login immediately
- Console shows: "Invalid or expired token"

**Diagnosis:**
```javascript
// Check if token exists
console.log('Token:', localStorage.getItem('phins_token'));

// Check token expiration
fetch('/api/session/validate', {
  headers: { 'Authorization': 'Bearer ' + localStorage.getItem('phins_token') }
}).then(r => r.json()).then(console.log);
```

**Fix:**
1. Log out and log in again to get fresh token
2. Check if session timeout is too short (default: 24 hours)
3. Verify token is being stored correctly in localStorage

## Improvements Made

### Dashboard HTML Changes
✅ Added health check API call at initialization  
✅ Changed `Promise.all` to `Promise.allSettled` for partial failures  
✅ Ensured splash screen ALWAYS hides after timeout  
✅ Added error notification for critical failures  
✅ Improved `loadCustomerInfo` with specific error handling  
✅ Added fallback values when API calls fail  
✅ Enhanced console logging for debugging  

### Server Improvements
✅ Added diagnostic logging to `/api/customer/summary`  
✅ Database connection retry with exponential backoff  
✅ Customer ID guarantee with 5-layer fallback  
✅ Session validation with automatic recovery  
✅ Health check endpoint with database status  

## Testing Checklist

Use this checklist to verify fixes:

- [ ] Login with test account succeeds
- [ ] Dashboard loads within 3 seconds
- [ ] Splash screen disappears automatically
- [ ] Customer info displays correctly
- [ ] Policy count shows accurate number
- [ ] Claims count shows accurate number
- [ ] Total coverage displays correctly
- [ ] No 403/400 errors in browser console
- [ ] Health check returns "connected" status
- [ ] Database connection is stable

## Diagnostic Commands

### Check Application Health
```bash
curl https://phins-portal-production.up.railway.app/api/health | jq
```

### Test Database Connection
```bash
curl https://phins-portal-production.up.railway.app/api/diagnostics/db-test | jq
```

### Validate Session Token
```bash
TOKEN="your-token-here"
curl -H "Authorization: Bearer $TOKEN" \
  https://phins-portal-production.up.railway.app/api/session/validate | jq
```

### Get Customer Summary
```bash
TOKEN="your-token-here"
CUSTOMER_ID="CUST-12345"
curl -H "Authorization: Bearer $TOKEN" \
  "https://phins-portal-production.up.railway.app/api/customer/summary?customer_id=$CUSTOMER_ID" | jq
```

## Production Monitoring

### Server Logs to Watch For

**Success:**
```
[CUSTOMER SUMMARY] Authorized for customer_id: CUST-12345
[CUSTOMER SUMMARY] Returning summary: 2 active policies, 1 claims
```

**Warning:**
```
[CUSTOMER SUMMARY] Authorization failed: Customer session invalid
[SESSION VALIDATE] Customer session without customer_id for user@example.com
[AUTH WARNING] Auto-generated customer_id for user@example.com: CUST-45678
```

**Error:**
```
[CUSTOMER SUMMARY] No customer_id resolved
Database connection error: connection refused
```

### Browser Console Logs to Watch For

**Success:**
```
[Dashboard Init] Customer ID retrieved from session: CUST-12345
[loadCustomerInfo] Customer info loaded: {...}
[Dashboard Init] All data loaded successfully
```

**Warning:**
```
[Dashboard Init] Database connectivity issue: disconnected
[loadCustomerInfo] Summary fetch failed: 403
Splash screen failsafe triggered - forcing hide
```

**Error:**
```
[Dashboard Init] No auth token - redirecting to login
[Dashboard Init] Error loading dashboard data: Network error
```

## Support Resources

- **PostgreSQL Fix Guide:** `RAILWAY_POSTGRES_FIX.md`
- **Deployment Guide:** `RAILWAY_DEPLOYMENT.md`
- **Database Analysis:** `POSTGRES_DEPLOYMENT_ANALYSIS.md`
- **Test Dashboard Flow:** `python3 test_dashboard_flow.py`

## Quick Fix Summary

If users report endless loading:

1. **Check database status:** `/api/health`
2. **Recreate PostgreSQL if needed:** Delete + Create in Railway
3. **Verify variables:** `USE_DATABASE=true`, `DATABASE_URL` set
4. **Clear browser storage:** Have user clear localStorage/sessionStorage
5. **Re-login:** Have user log out and log in again

All fixes are designed to be **non-breaking** and maintain **data integrity**.
