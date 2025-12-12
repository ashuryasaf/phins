# 🚂 Railway Deployment Guide for PHINS

## Quick Deploy to Railway

### Option 1: Using Railway Dashboard (Easiest)

1. **Go to Railway:** <https://railway.app>

2. **Sign in with GitHub**

3. **New Project → Deploy from GitHub repo**
   - Select repository: `ashuryasaf/phins`
   - Railway auto-detects Python and uses `railway.json` config

4. **Wait for deployment** (2-3 minutes)
   - Railway will install dependencies
   - Start server with `python3 web_portal/server.py`

5. **Get your URL:**
   - Format: `https://[project-name].up.railway.app`
   - Click "View Deployment" or check Settings → Domains

6. **Test it:**

   ```
   https://[your-project].up.railway.app/admin-portal.html
   ```
   
   Login with: `admin` / `admin123`

### Option 2: Using Railway CLI

```bash
# Install Railway CLI
npm i -g @railway/cli
# or
brew install railway

# Login
railway login

# Deploy
railway init  # First time
railway up    # Deploy

# Get URL
railway domain
```

Or use the automated script:

```bash
./deploy_railway.sh
```

## Adding Custom Domain (`www.phins.ai`)

### Step 1: In Railway Dashboard

1. Go to your project
2. Click **Settings** → **Domains**
3. Click **Custom Domain**
4. Enter: ```www.phins.ai```
5. Railway will provide a CNAME target (like `[project].up.railway.app`)

### Step 2: Configure DNS

At your domain registrar (GoDaddy, Namecheap, Cloudflare, etc.):

**Add CNAME Record:**
- **Type:** CNAME
- **Name:** www
- **Value:** `[your-project].up.railway.app` (from Railway)
- **TTL:** Auto or 3600

**Example for Cloudflare:**

```
Type: CNAME
Name: www
Target: orange-space-enigma-jjv7wvg45pwvcp59p.up.railway.app
Proxy: Off (DNS only)
```

### Step 3: Wait for DNS Propagation

- Usually 5-30 minutes
- Maximum 48 hours
- Check status: <https://www.whatsmydns.net>

### Step 4: SSL Certificate

Railway automatically provisions SSL via Let's Encrypt:

- Takes 5-15 minutes after DNS propagates
- Your site will be accessible at `https://``www.phins.ai```

## Verify Deployment

### Check Health

```bash
# Test if server is running
curl https://[your-project].up.railway.app/

# Test admin portal
curl https://[your-project].up.railway.app/admin-portal.html

# Test API
curl -X POST https://[your-project].up.railway.app/api/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin123"}'
```

### Expected Response

```json
{
  "token": "demo-token-admin-...",
  "role": "admin",
  "name": "Admin User"
}
```

## Environment Variables (Optional)

If you need custom configuration:

1. Railway Dashboard → Variables
2. Add:

   ```
   PORT=8000
   DOMAIN=``www.phins.ai``
   ENVIRONMENT=production
   ```

## Monitoring & Logs

### View Logs

**Dashboard:**
- Go to your project
- Click "View Logs" tab

**CLI:**

```bash
railway logs
railway logs --follow  # Live logs
```

### Metrics

Railway provides:

- CPU usage
- Memory usage
- Network traffic
- Request count

Check in: Dashboard → Metrics tab

## Troubleshooting

### "Build Failed"

**Check logs:**

```bash
railway logs
```

**Common issues:**
- Missing `requirements.txt` → Already included ✅
- Wrong Python version → Railway auto-detects ✅
- Port issues → Server auto-detects PORT env var ✅

### "502 Bad Gateway"

Server didn't start properly.

**Fix:**
1. Check logs: `railway logs`
2. Verify `railway.json` start command:

   ```json
   "startCommand": "python3 web_portal/server.py"
   ```

### "Can't Access Admin Portal"

**Solutions:**

1. **Check URL:** Make sure you're accessing:

   ```
   https://[project].up.railway.app/admin-portal.html
   ```

   (Note the `/admin-portal.html` at the end)

2. **Clear cache:** Use incognito mode

3. **Check server logs:**

   ```bash
   railway logs
   ```

4. **Test locally first:**

   ```bash
   python3 web_portal/server.py
   ```

### "Custom Domain Not Working"

**Checklist:**

- [ ] DNS CNAME record added correctly
- [ ] CNAME points to Railway domain (not IP address)
- [ ] Waited at least 30 minutes for propagation
- [ ] Domain shows as "Active" in Railway dashboard

**Verify DNS:**

```bash
nslookup ``www.phins.ai``
dig ``www.phins.ai``
```

Should return Railway's domain.

## Railway Configuration Files

### railway.json (Already Configured ✅)

```json
{
  "$schema": "https://railway.app/railway.schema.json",
  "build": {
    "builder": "NIXPACKS"
  },
  "deploy": {
    "startCommand": "python3 web_portal/server.py",
    "restartPolicyType": "ON_FAILURE",
    "restartPolicyMaxRetries": 10
  }
}
```

### requirements.txt (Already Configured ✅)

Railway automatically installs these dependencies.

## Cost & Limits

### Free Tier

Railway provides:

- **$5 free credits/month**
- Enough for development/testing
- ~500 hours of runtime

### Usage Tips

- Deploy from `main` branch only
- Use sleep mode when not testing
- Monitor usage in dashboard

## Post-Deployment Checklist

- [ ] Deployment successful
- [ ] Admin portal accessible
- [ ] Login works (test all 4 demo accounts)
- [ ] Custom domain added (optional)
- [ ] DNS configured (if using custom domain)
- [ ] SSL certificate active
- [ ] Logs show no errors

## Quick Commands Reference

```bash
# Deploy/Update
railway up

# View status
railway status

# View logs
railway logs

# Get URL
railway domain

# Open in browser
railway open

# Environment variables
railway variables

# Link different project
railway link
```

## Next Steps After Deployment

1. **Test all features:**
   - Login with all demo accounts
   - Create a test policy
   - Submit a claim
   - Check BI dashboards

2. **Bookmark your URLs:**
   - Production: `https://[project].up.railway.app`
   - Admin Portal: `https://[project].up.railway.app/admin-portal.html`
   - Custom Domain: `https://``www.phins.ai``` (when DNS propagates)

3. **Monitor regularly:**
   - Check logs for errors
   - Monitor resource usage
   - Watch for crashes/restarts

4. **Share with team:**
   - Send credentials to authorized users
   - Document any custom configurations
   - Set up monitoring alerts (optional)

## Support Resources

- **Railway Docs:** <https://docs.railway.app>
- **Railway Discord:** <https://discord.gg/railway>
- **PHINS Docs:** See DEPLOYMENT.md and DOMAIN_SETUP.md
- **Test Authentication:** Run `python3 test_admin_auth.py` locally

## Ready to Deploy?

Run the automated script:

```bash
./deploy_railway.sh
```

Or follow the manual steps above! 🚀
