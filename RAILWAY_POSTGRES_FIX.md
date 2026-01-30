# Railway PostgreSQL Fix Guide

## Quick Fix for "Postgres-AyKP Failed" Error

**Error:** `Postgres-AyKP / 93384fb8 Failed`  
**Cause:** Railway cannot connect to Docker registry to pull PostgreSQL image  
**Impact:** Database service won't start, app falls back to in-memory mode  

---

## Immediate Fix Steps (5 minutes)

### Step 1: Delete the Failing PostgreSQL Service

1. Go to [Railway Dashboard](https://railway.app/dashboard)
2. Open your PHINS project
3. Find the **Postgres-AyKP** service (red/failed status)
4. Click on the service → **Settings** tab
5. Scroll to bottom → **Delete Service** → Confirm

### Step 2: Create a New PostgreSQL Service

1. In your project, click **+ New**
2. Select **Database** → **PostgreSQL**
3. Wait 1-2 minutes for provisioning
4. The new service will appear with green status

### Step 3: Link Database to Web Service

1. Click on your **web application service** (not the database)
2. Go to **Variables** tab
3. Check if `DATABASE_URL` exists:
   - If missing: Click **+ Add Variable** → **Add Reference** → Select your new PostgreSQL → `DATABASE_URL`
   - If exists but pointing to old service: Delete it and re-add as above

### Step 4: Set Required Environment Variables

Ensure these variables are set in your **web service**:

| Variable | Value | Purpose |
|----------|-------|---------|
| `USE_DATABASE` | `true` | Enable database mode |
| `ENABLE_LEDGER_PERSISTENCE` | `true` | Enable ledger persistence |

### Step 5: Redeploy

1. Go to **Deployments** tab
2. Click **Redeploy** on the latest deployment
3. Wait for deployment to complete (2-3 minutes)

### Step 6: Verify Connection

Test the database diagnostic endpoint:

```bash
curl https://[your-app].up.railway.app/api/diagnostics/db-test
```

Expected successful response:
```json
{
  "database_url_set": true,
  "database_enabled_flag": true,
  "connection_test": "SUCCESS",
  "storage_mode": "database"
}
```

---

## Preventing Future Issues

### 1. Monitor Railway Status

Before investigating code issues, check [Railway Status](https://status.railway.app) for outages.

### 2. Use Health Checks

The app includes automatic health checks at `/api/health`. Railway uses this to monitor service health.

### 3. Connection Resilience (Already Implemented)

The PHINS app includes:
- **Automatic retry** with exponential backoff (3 attempts)
- **Graceful fallback** to in-memory storage if database unavailable
- **Connection pooling** with pre-ping validation
- **Detailed diagnostic endpoints** for troubleshooting

### 4. Environment Variable Checklist

For any Railway deployment, ensure these are set:

```bash
# Required for database mode
DATABASE_URL=postgresql://...  # Auto-injected by Railway
USE_DATABASE=true

# Optional but recommended
ENABLE_LEDGER_PERSISTENCE=true
PORT=8000
```

---

## Diagnostic Endpoints

| Endpoint | Purpose |
|----------|---------|
| `/api/health` | Basic health check (used by Railway) |
| `/api/diagnostics/db-test` | Database connection test with recommendations |
| `/api/diagnostics/env-check` | Environment variable status |
| `/api/status` | Full system status |

---

## Common Error Scenarios

### Error: "Unable to connect to registry"

**Cause:** Docker Hub rate limiting or Railway infrastructure issue  
**Fix:** Delete and recreate PostgreSQL service (Steps 1-2 above)

### Error: "Connection refused" or "Timeout"

**Cause:** Database service not running or wrong credentials  
**Fix:**
1. Check PostgreSQL service is running (green status)
2. Verify `DATABASE_URL` references correct service
3. Redeploy web service

### Error: "Authentication failed"

**Cause:** Stale credentials after PostgreSQL recreation  
**Fix:**
1. Go to web service → Variables
2. Delete `DATABASE_URL`
3. Re-add as reference to PostgreSQL service
4. Redeploy

### Error: "Database does not exist"

**Cause:** Fresh PostgreSQL with no tables  
**Fix:** Tables are auto-created on first connection. Just redeploy.

---

## Railway CLI Quick Commands

```bash
# Install CLI
npm i -g @railway/cli

# Login and link project
railway login
railway link

# Check service status
railway status

# View logs
railway logs

# List environment variables
railway variables

# Force redeploy
railway up --force

# Delete failing service
railway service delete Postgres-AyKP

# Add new PostgreSQL
railway add --database postgres
```

---

## Architecture: How Database Fallback Works

```
┌─────────────────────────────────────────────────────────┐
│                  Server Startup                          │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  1. Check DATABASE_URL environment variable              │
│     ├── Not set → Use in-memory storage                  │
│     └── Set → Continue to step 2                         │
│                                                          │
│  2. Test database connection (3 retries)                 │
│     ├── Success → Use PostgreSQL                         │
│     └── Failure → Fallback to in-memory                  │
│                                                          │
│  3. Initialize tables if needed                          │
│     ├── Success → Seed default users                     │
│     └── Failure → Log warning, continue                  │
│                                                          │
│  4. Start HTTP server                                    │
│     └── Health endpoint reports database status          │
│                                                          │
└─────────────────────────────────────────────────────────┘
```

---

## Data Recovery After Recreation

When you delete and recreate PostgreSQL, **data is lost**. For production:

1. **Before deletion:** Export critical data if possible
2. **After recreation:** Data will need to be re-entered or imported
3. **For testing environments:** Data loss is expected and acceptable

---

## Support Contacts

- **Railway Status:** https://status.railway.app
- **Railway Discord:** https://discord.gg/railway
- **Railway Docs:** https://docs.railway.app

---

*Document Version: 1.0*  
*Last Updated: January 2026*
