# Railway Postgres Registry Connection Fix

## Problem

Deployment error: **"We were unable to connect to the registry for this image"** for service `Postgres-AyKP`

This error occurs when Railway cannot pull the PostgreSQL Docker image from the container registry to provision your database service.

## Root Cause

This is typically a Railway infrastructure issue, not a code problem. The error can be caused by:

1. **Temporary registry unavailability** - Docker Hub or Railway's registry having connectivity issues
2. **Corrupted database service state** - The Railway Postgres service configuration is corrupted
3. **Rate limiting** - Docker Hub rate limits being hit
4. **Service configuration issues** - Invalid or outdated service configuration

## Quick Fix (Recommended)

### Step 1: Delete the Failing Postgres Service

1. Go to [Railway Dashboard](https://railway.app/dashboard)
2. Open your PHINS project
3. Click on the failing **Postgres-AyKP** service
4. Go to **Settings** → scroll to bottom → **Delete Service**
5. Confirm deletion

### Step 2: Create a New PostgreSQL Service

1. In your project, click **+ New Service**
2. Select **Add PostgreSQL** (or Database → PostgreSQL)
3. Wait for the service to provision (usually 1-2 minutes)
4. Railway will automatically create a new service with a fresh configuration

### Step 3: Link DATABASE_URL to Your Application

Railway should automatically inject the `DATABASE_URL` environment variable. Verify this:

1. Click on your **main application service** (web-portal)
2. Go to **Variables** tab
3. Check if `DATABASE_URL` is listed under "Service Variables"
4. If not, click **+ Variable Reference** and select the Postgres service's `DATABASE_URL`

### Step 4: Redeploy Your Application

1. Click on your application service
2. Go to **Deployments** tab
3. Click **Redeploy** on the latest deployment

## Alternative Fix: Use Railway CLI

```bash
# Install Railway CLI if not already installed
npm install -g @railway/cli

# Login to Railway
railway login

# Link to your project
railway link

# List services to find the failing one
railway service

# Delete the failing Postgres service
railway service delete Postgres-AyKP

# Add a new Postgres database
railway add -p postgres

# Redeploy
railway up
```

## Verify the Fix

After redeployment, verify the database connection:

1. **Check Health Endpoint:**
   ```bash
   curl https://[your-app].up.railway.app/api/health
   ```
   Expected response:
   ```json
   {
     "status": "healthy",
     "database": "connected"
   }
   ```

2. **Check Database Diagnostic:**
   ```bash
   curl https://[your-app].up.railway.app/api/diagnostics/db-test
   ```
   Expected response:
   ```json
   {
     "database_url_set": true,
     "connection_test": "SUCCESS"
   }
   ```

## Application Fallback Behavior

The PHINS application is designed to handle database connection failures gracefully:

1. **If Postgres is unavailable**: The app falls back to in-memory storage mode
2. **Data persistence**: In-memory mode means data is lost on restart
3. **Health checks**: The `/api/health` endpoint reports the current database status

To verify which mode is active, check the deployment logs or the health endpoint.

## Environment Variables

Ensure these variables are set in your Railway service:

| Variable | Description | Required |
|----------|-------------|----------|
| `DATABASE_URL` | PostgreSQL connection string (auto-injected) | Yes |
| `USE_DATABASE` | Enable database mode (default: `true`) | No |
| `PORT` | Server port (auto-set by Railway) | No |

## Preventing Future Issues

1. **Use Railway's managed Postgres** - Don't use custom Postgres images
2. **Enable health checks** - Already configured in `railway.json`
3. **Monitor deployments** - Check Railway dashboard regularly
4. **Use connection pooling** - Already configured in `database/config.py`

## If Problems Persist

1. **Check Railway Status**: [status.railway.app](https://status.railway.app)
2. **Clear Railway Cache**: In project settings, try "Rebuild without cache"
3. **Contact Railway Support**: [help.railway.app](https://help.railway.app)
4. **Check Docker Hub Status**: [status.docker.com](https://status.docker.com)

## Technical Details

### Database Configuration (`database/config.py`)

The application handles the `DATABASE_URL` from Railway:
- Automatically converts `postgres://` to `postgresql://` (SQLAlchemy requirement)
- Configures connection pooling for production use
- Falls back to SQLite for local development

### Health Check Configuration (`railway.json`)

```json
{
  "deploy": {
    "healthcheckPath": "/api/health",
    "healthcheckTimeout": 60
  }
}
```

### Connection Verification (`web_portal/server.py`)

The server performs a connection check at startup:
1. Tests actual database connectivity
2. Falls back to in-memory if connection fails
3. Reports database status in health endpoint

---

*Last Updated: January 2026*
*For PHINS Insurance Platform v2.0*
