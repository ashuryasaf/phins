# URGENT: Railway Manual Redeploy Required

## Current Status (February 2, 2026 ~21:45 UTC)

| Component | Status |
|-----------|--------|
| GitHub main branch | ✅ Has ALL fixes (commit b03f807) |
| Production server | ❌ Running OLD code (duplicate authToken issue) |
| Database (Postgres-AyKP) | ✅ Connected |
| GitHub Actions | ⚠️ Tests queued/failed (non-blocking) |
| Railway Auto-Deploy | ❌ NOT WORKING - requires manual trigger |

## Problem

The dashboard at `https://phins-portal-production.up.railway.app/dashboard.html` is rendering endlessly because:

1. **Production is running stale code** - The JavaScript fix from PR #88 has NOT been deployed
2. **GitHub Actions failed** - Security scan and Visual PDF test failed, but these are non-blocking tests
3. **Railway auto-deploy may be disabled** or waiting for manual trigger

## Evidence

```bash
# Main branch has the fix:
$ git show origin/main:web_portal/static/dashboard.html | grep -A3 "return trimmed;"
      return trimmed;
    }                          # <-- Closing brace EXISTS in main
    
    function getStorage(type) {

# Production is MISSING the fix:
$ curl -s "https://phins-portal-production.up.railway.app/dashboard.html" | grep -A3 "return trimmed;"
      return trimmed;
    function getStorage(type) {  # <-- NO closing brace! BROKEN!
```

## Auto-Deploy Issue

Railway is NOT auto-deploying from GitHub pushes. Multiple pushes to main have been made but production still runs old code.

**Evidence:**
```bash
# GitHub main branch (has fix):
$ grep -c "let authToken" web_portal/static/dashboard.html
1

# Production (still broken):
$ curl -s "https://phins-portal-production.up.railway.app/dashboard.html" | grep -c "let authToken"
2
```

**Possible causes:**
1. Railway GitHub integration is misconfigured
2. Railway is set to manual deploy only
3. Railway deployment webhook is failing silently
4. Previous failed GitHub Actions blocked deployment

---

## Solution: Manual Redeploy Required

### Option 1: Railway Dashboard (Recommended - MUST DO)

1. Go to [Railway Dashboard](https://railway.app/dashboard)
2. Open the **phins-portal** project
3. Click on the **phins-portal** service (web app, not database)
4. Go to **Deployments** tab
5. Click **Redeploy** on the latest deployment
6. Wait 2-3 minutes for deployment to complete
7. Verify: `curl https://phins-portal-production.up.railway.app/api/health`

### Option 2: Railway CLI

```bash
# Install Railway CLI if not installed
npm i -g @railway/cli

# Login
railway login

# Link to project (if not linked)
railway link

# Force redeploy
railway up --force

# Or trigger from specific branch
railway up --branch main
```

### Option 3: Push a Trigger Commit

I've created this documentation file. Pushing it to main will trigger a new deployment:

```bash
git add RAILWAY_REDEPLOY_REQUIRED.md
git commit -m "docs: Add Railway redeploy instructions - trigger deployment"
git push origin main
```

## Verification Steps

After redeploy, verify the fix is live:

```bash
# 1. Check health
curl -s "https://phins-portal-production.up.railway.app/api/health"

# 2. Check if normalizeCustomerId function has closing brace
curl -s "https://phins-portal-production.up.railway.app/dashboard.html" | grep -A3 "return trimmed;" | head -5

# Expected output (FIXED):
#   return trimmed;
#   }
#   
#   function getStorage(type) {

# 3. Test login flow
curl -X POST "https://phins-portal-production.up.railway.app/api/login" \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"YOUR_ADMIN_PASSWORD"}'

# 4. Test dashboard loads (browser)
# Open: https://phins-portal-production.up.railway.app/login.html
# Login with valid credentials
# Dashboard should load WITHOUT endless spinner
```

## Root Cause Summary

The dashboard endless rendering is caused by **JavaScript syntax errors** in `dashboard.html`:

1. Missing closing brace `}` for `normalizeCustomerId` function
2. Duplicate `let authToken` declaration
3. Corrupted initialization code in DOMContentLoaded handler

These were fixed in PR #88 (merged Feb 2, 2026 19:27 UTC), but the fix hasn't reached production because Railway didn't auto-deploy.

## Timeline

| Time | Event |
|------|-------|
| Jan 30 14:00 | Dashboard access broken |
| Jan 30 - Feb 2 | 8 PRs attempted fixes (symptoms only) |
| Feb 2 19:27 | PR #88 merged with actual fix |
| Feb 2 20:29 | GitHub Actions failed (non-critical tests) |
| Feb 2 21:30 | Production still running old code |

## Contact

For Railway dashboard access issues, contact the project owner or use Railway CLI with appropriate credentials.

---

*Generated: February 2, 2026 21:35 UTC*
