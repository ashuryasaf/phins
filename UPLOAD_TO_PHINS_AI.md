# 📤 How to Upload to www.phins.ai

Complete step-by-step instructions for deploying the PHINS platform to production at www.phins.ai.

---

## 📑 Table of Contents

1. [Quick Summary](#-quick-summary)
2. [Prerequisites](#-prerequisites)
3. [Method 1: Railway Dashboard (Easiest)](#-method-1-railway-dashboard-easiest---recommended)
4. [Method 2: Railway CLI](#-method-2-railway-cli-for-developers)
5. [Adding Custom Domain (www.phins.ai)](#-adding-custom-domain-wwwphinsai)
6. [Verification & Testing](#-verification--testing)
7. [Production Security Checklist](#-production-security-checklist)
8. [Troubleshooting](#️-troubleshooting)
9. [Monitoring Your Deployment](#-monitoring-your-deployment)
10. [Cost Information](#-cost-information)
11. [Updating Your Deployment](#-updating-your-deployment)
12. [Additional Resources](#-additional-resources)

---

## 🎯 Quick Summary

**Goal:** Deploy PHINS to www.phins.ai using Railway hosting  
**Time Required:** 15-30 minutes (plus DNS propagation)  
**Prerequisites:** GitHub account, Railway account, domain access  

### Deployment Flow

```
┌─────────────────────────────────────────────────────────────┐
│                    DEPLOYMENT FLOW                          │
└─────────────────────────────────────────────────────────────┘

Step 1: Sign in to Railway (GitHub auth)
   ↓
Step 2: Deploy from GitHub repo (ashuryasaf/phins)
   ↓
Step 3: Railway auto-builds & deploys (2-5 min)
   ↓
Step 4: Get Railway URL (https://xxx.up.railway.app)
   ↓
Step 5: Test deployment ✅
   ↓
Step 6: Add custom domain (www.phins.ai)
   ↓
Step 7: Configure DNS (CNAME record)
   ↓
Step 8: Wait for DNS propagation (5-30 min)
   ↓
Step 9: SSL certificate auto-provisioned
   ↓
Step 10: Live at https://www.phins.ai ✅
```

---

## 📋 Prerequisites

Before you begin, ensure you have:

1. ✅ **GitHub Account** with access to the repository
2. ✅ **Railway Account** - Sign up at [railway.app](https://railway.app)
3. ✅ **Domain Access** - Admin access to phins.ai DNS settings
4. ✅ **Git** installed on your computer (optional, for command-line deployment)

---

## 🚀 Method 1: Railway Dashboard (Easiest - Recommended)

This is the **simplest way** to deploy - no command line needed!

### Step 1: Sign in to Railway

1. Go to **[railway.app](https://railway.app)**
2. Click **"Login"**
3. Choose **"Login with GitHub"**
4. Authorize Railway to access your GitHub account

### Step 2: Create New Project

1. Click **"New Project"** button (top right)
2. Select **"Deploy from GitHub repo"**
3. Choose the repository: **`ashuryasaf/phins`**
4. Railway will automatically:
   - Detect it's a Python project
   - Read the `railway.json` configuration
   - Install dependencies from `requirements.txt`
   - Start the server with `python3 web_portal/server.py`

### Step 3: Wait for Deployment

- Railway will build and deploy automatically (2-5 minutes)
- Watch the logs in real-time to see progress
- Look for: `✅ Deployment successful`

### Step 4: Get Your Railway URL

1. Once deployed, Railway assigns you a URL like:
   ```
   https://phins-production-xxxx.up.railway.app
   ```
2. Click **"View"** or go to **Settings → Domains** to see your URL
3. Test it by visiting: `https://[your-railway-url]/admin-portal.html`
4. Login with: `admin` / `admin123`

✅ **Success!** Your app is now live on Railway.

---

## 🌐 Method 2: Railway CLI (For Developers)

If you prefer the command line:

### Step 1: Install Railway CLI

**Mac/Linux:**
```bash
brew install railway
```

**Windows/Alternative:**
```bash
npm install -g @railway/cli
```

### Step 2: Login to Railway

```bash
railway login
```
This opens your browser for authentication.

### Step 3: Initialize Project (First Time Only)

```bash
cd /path/to/phins
railway init
```
Select your GitHub repository when prompted.

### Step 4: Deploy

```bash
railway up
```

### Step 5: Get Your URL

```bash
railway domain
```

### Use the Automated Script

We've included a deployment script:

```bash
./deploy_railway.sh
```

This script will:
- Check if Railway CLI is installed
- Verify you're logged in
- Check git status
- Deploy to Railway
- Display your deployment URL

---

## 🔧 Adding Custom Domain (www.phins.ai)

Once your app is deployed to Railway, follow these steps to connect it to www.phins.ai:

### Step 1: Add Custom Domain in Railway

1. Go to your Railway project
2. Click **"Settings"** tab
3. Scroll to **"Domains"** section
4. Click **"Custom Domain"**
5. Enter: `www.phins.ai`
6. Click **"Add"**

Railway will show you a CNAME target like:
```
phins-production-xxxx.up.railway.app
```
**Copy this target** - you'll need it for Step 2.

### Step 2: Configure DNS Settings

Log in to your domain registrar (where you bought phins.ai):

**Common registrars:**
- GoDaddy
- Namecheap
- Google Domains
- Cloudflare
- etc.

**Add a CNAME record:**

| Field | Value |
|-------|-------|
| **Type** | CNAME |
| **Name** | www |
| **Target/Value** | `phins-production-xxxx.up.railway.app` *(from Railway)* |
| **TTL** | 3600 (or Auto) |

**Example for Cloudflare:**
```
Type:   CNAME
Name:   www
Target: phins-production-xxxx.up.railway.app
Proxy:  OFF (DNS only - important!)
```

**Example for GoDaddy:**
```
Type:   CNAME
Host:   www
Points to: phins-production-xxxx.up.railway.app
TTL:    1 Hour
```

### Step 3: Wait for DNS Propagation

- **Typical wait time:** 5-30 minutes
- **Maximum:** 48 hours (rare)
- **Check status:** [whatsmydns.net](https://www.whatsmydns.net)

Enter `www.phins.ai` to see if DNS has propagated globally.

### Step 4: SSL Certificate (Automatic)

Railway automatically provisions an SSL certificate via Let's Encrypt:

- Starts after DNS propagates
- Takes 5-15 minutes
- When ready, your site will be accessible at: `https://www.phins.ai`
- Railway dashboard will show "Active" status

✅ **Done!** Your site is now live at https://www.phins.ai

---

## ✅ Verification & Testing

### 1. Check if Site is Live

Visit these URLs and verify they load:

```
https://www.phins.ai
https://www.phins.ai/admin-portal.html
https://www.phins.ai/login.html
```

### 2. Test Admin Login

1. Go to: `https://www.phins.ai/login.html`
2. Login with:
   - **Username:** `admin`
   - **Password:** `admin123`
3. Verify you see the admin dashboard

### 3. Test Other User Roles

Try logging in with these demo accounts:

| Username | Password | Role |
|----------|----------|------|
| admin | admin123 | Administrator |
| underwriter | admin123 | Underwriter |
| claims_adjuster | admin123 | Claims Adjuster |
| accountant | admin123 | Accountant |

### 4. Check API Health

Test the health endpoint:
```bash
curl https://www.phins.ai/api/health
```

Expected response:
```json
{
  "status": "ok",
  "timestamp": "2026-02-16T22:00:00.000Z"
}
```

### 5. Monitor Logs

In Railway dashboard:
- Go to your project
- Click **"Logs"** tab
- Look for any errors

Or via CLI:
```bash
railway logs --follow
```

---

## 🔒 Production Security Checklist

**⚠️ IMPORTANT:** Before going live with real users, complete these security steps:

### Critical Tasks

- [ ] **Change default passwords** (currently all use `admin123`)
- [ ] **Generate new SECRET_KEY** for production
- [ ] **Set up PostgreSQL database** (currently using in-memory storage)
- [ ] **Configure automated backups**
- [ ] **Review user permissions** and role-based access
- [ ] **Enable HTTPS only** (disable HTTP)
- [ ] **Set up monitoring and alerts**

### Environment Variables to Set

In Railway Dashboard → Variables, add:

```bash
# Database (Production)
USE_DATABASE=true
DATABASE_URL=postgresql://user:pass@host:5432/phins_prod

# Security
PHINS_SECRET_KEY=<generate-secure-256-bit-key>
ALLOW_LEGACY_DEMO_PASSWORDS=false

# Optional: Data Persistence
ENABLE_LEDGER_PERSISTENCE=true
```

See `PRODUCTION_DEPLOYMENT_REPORT.md` for detailed security recommendations.

---

## 🛠️ Troubleshooting

### Issue: "Build Failed"

**Solution:**
1. Check Railway logs: Dashboard → Logs
2. Common causes:
   - Missing `requirements.txt` (already included ✅)
   - Python version mismatch (Railway auto-detects ✅)
   - Syntax errors in code

**Fix:**
- Review the error in logs
- Fix the issue in your code
- Push changes to GitHub
- Railway will auto-rebuild

### Issue: "502 Bad Gateway"

**Cause:** Server didn't start properly

**Solution:**
1. Check logs: `railway logs`
2. Look for startup errors
3. Verify `railway.json` is correct (already configured ✅)
4. Check if port is set correctly (auto-detected ✅)

### Issue: "Can't Login to Admin Portal"

**Solutions:**

1. **Verify URL:** Use the full path:
   ```
   https://www.phins.ai/admin-portal.html
   ```
   (Don't forget `/admin-portal.html`)

2. **Clear browser cache** or try incognito mode

3. **Check credentials:**
   - Username: `admin` (lowercase)
   - Password: `admin123`

4. **Test API directly:**
   ```bash
   curl -X POST https://www.phins.ai/api/login \
     -H "Content-Type: application/json" \
     -d '{"username":"admin","password":"admin123"}'
   ```

### Issue: "Custom Domain Not Working"

**Checklist:**

- [ ] DNS CNAME record added correctly
- [ ] CNAME points to Railway domain (not an IP address)
- [ ] Waited at least 30 minutes for DNS propagation
- [ ] Domain shows "Active" in Railway dashboard
- [ ] If using Cloudflare, proxy is OFF (DNS only)

**Verify DNS:**
```bash
nslookup www.phins.ai
# Should return your Railway domain

dig www.phins.ai
# Should show CNAME record
```

### Issue: "Site Works But Shows Railway URL in Browser"

**Cause:** DNS not fully propagated or browser cached old DNS

**Solution:**
- Clear browser DNS cache
- Try incognito mode
- Wait a bit longer for DNS propagation
- Check [whatsmydns.net](https://www.whatsmydns.net)

### Issue: "SSL Certificate Not Working"

**Causes:**
- DNS hasn't propagated yet
- Railway hasn't provisioned certificate yet

**Solution:**
1. Verify DNS is propagated (Step 3 above)
2. Wait 15-30 minutes after DNS propagation
3. Check Railway dashboard → Domains
4. Look for "SSL: Active" status

---

## 📊 Monitoring Your Deployment

### Railway Dashboard Metrics

Available in Dashboard → Metrics:
- CPU usage
- Memory usage
- Network traffic
- Request count
- Response times

### View Logs

**Dashboard:**
- Project → "Logs" tab

**CLI:**
```bash
railway logs              # Recent logs
railway logs --follow     # Live stream
```

### Set Up Alerts

Consider integrating with:
- **Sentry** - Error tracking
- **Datadog** - Performance monitoring  
- **PagerDuty** - Incident alerts

---

## 💰 Cost Information

### Railway Pricing

**Hobby Plan (Free):**
- $5 free credits per month
- ~500 hours of runtime
- Perfect for testing/development

**Developer Plan ($5/month):**
- Includes custom domains
- SSL certificates
- Enough for small production use

**Team Plan ($20/month):**
- Multiple projects
- Team collaboration
- Higher resource limits

**Tip:** Start with the free tier and upgrade as needed.

---

## 🔄 Updating Your Deployment

### Automatic Updates (Recommended)

Railway automatically deploys when you push to GitHub:

1. Make changes to your code
2. Commit and push to GitHub:
   ```bash
   git add .
   git commit -m "Update feature X"
   git push origin main
   ```
3. Railway detects the change and redeploys automatically
4. Monitor logs during deployment

### Manual Re-deploy

**Via Dashboard:**
- Project → Deployments → "Redeploy"

**Via CLI:**
```bash
railway up
```

---

## 📚 Additional Resources

### Documentation

- **Full Deployment Guide:** `DEPLOYMENT.md`
- **Railway-Specific Guide:** `RAILWAY_DEPLOYMENT.md`
- **Production Checklist:** `PRODUCTION_DEPLOYMENT_REPORT.md`
- **Domain Setup:** See DNS configuration in this document
- **Security Guide:** `SECURITY.md`
- **Admin Access:** `ADMIN_ACCESS.md`

### Scripts

- `deploy_railway.sh` - Automated Railway deployment
- `deploy_railway_verified.sh` - Verified deployment with checks
- `quick_deploy.sh` - Quick deployment script

### Railway Resources

- **Railway Docs:** [docs.railway.app](https://docs.railway.app)
- **Railway Discord:** [discord.gg/railway](https://discord.gg/railway)
- **Railway Status:** [status.railway.app](https://status.railway.app)

### Support

- Check existing documentation in the repo
- Review Railway logs for errors
- Test locally first: `python3 web_portal/server.py`

---

## 🎉 Success Checklist

After following this guide, you should have:

- ✅ PHINS deployed to Railway
- ✅ Site accessible at Railway URL
- ✅ Custom domain (www.phins.ai) configured
- ✅ DNS propagated and working
- ✅ SSL certificate active (HTTPS)
- ✅ Admin login working
- ✅ All pages loading correctly
- ✅ Logs showing no errors

---

## 🚦 Next Steps

1. **Test all features thoroughly**
   - Try all user roles
   - Create test policies
   - Submit test claims
   - Test billing functions

2. **Set up production database**
   - Add PostgreSQL service in Railway
   - Configure DATABASE_URL
   - Migrate any test data

3. **Secure your deployment**
   - Change all default passwords
   - Review security settings
   - Set up monitoring

4. **Share with your team**
   - Provide access credentials
   - Document any custom configurations
   - Set up user accounts

---

## ❓ Still Need Help?

If you encounter issues not covered here:

1. **Check the logs:** `railway logs`
2. **Review documentation:** See other .md files in the repo
3. **Test locally first:** `python3 web_portal/server.py`
4. **Railway support:** [docs.railway.app/help](https://docs.railway.app/help)

---

**Last Updated:** February 2026  
**Platform:** Railway  
**Domain:** www.phins.ai  
**Status:** Production Ready ✅
