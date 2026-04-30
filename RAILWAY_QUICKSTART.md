# 🚀 Quick Railway Deployment Instructions

## Your Repository is Ready for Railway!

All changes have been committed. Now deploy to Railway:

### Method 1: Railway Dashboard (Recommended)

1. **Visit:** <https://railway.app>

2. **Sign in** with your GitHub account

3. **Click:** "New Project" → "Deploy from GitHub repo"

4. **Select:** `ashuryasaf/phins`

5. **Wait 2-3 minutes** for automatic deployment

6. **Access your app:**
   - Railway will give you a URL like: `https://phins.up.railway.app`
   - Add `/admin-portal.html` to access admin portal
   - Login: `admin` / `admin123`

### Method 2: Railway CLI

```bash
# Install Railway CLI
npm i -g @railway/cli

# Login to Railway
railway login

# Deploy from repository
railway up

# Get your deployment URL
railway domain
```

### Method 3: Automated Script

```bash
./deploy_railway.sh
```

## After Deployment

### 1. Get Your URL

Railway assigns a URL automatically:
```
https://phins-production-xxxx.up.railway.app
```

### 2. Test It

Access the admin portal:
```
https://[your-url]/admin-portal.html
```

Login with:
- Username: `admin`
- Password: `admin123`

### 3. Add Custom Domain (Optional)

In Railway Dashboard:
1. Settings → Domains → Custom Domain
2. Enter: `www.phins.ai`
3. Add CNAME record to your DNS:
   - Name: `www`
   - Value: (provided by Railway)

## Verify Everything Works

```bash
# Test the API endpoint
curl https://[your-railway-url]/api/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin123"}'

# Should return:
# {"token": "demo-token-admin-...", "role": "admin", "name": "Admin User"}
```

## Configuration Already Set

✅ `railway.json` - Deployment configuration
✅ `requirements.txt` - Python dependencies  
✅ Server auto-detects PORT from Railway
✅ All demo accounts configured
✅ Domain configuration (`www.phins.ai`)
✅ Graceful shutdown (SIGTERM flushes data before exit)
✅ Startup integrity validation (hash-chain, balance checks)

## Required: Attach Persistent Volume

**Without a volume, wallet/transaction data is lost on every redeploy.**

1. Railway Dashboard → Your Service → **Settings** → **Volumes**
2. Click **+ Add Volume**
3. Set Mount Path: `/data`
4. Size: 1 GB (minimum)

The server automatically detects `/data` and persists ledger data there.
See [RAILWAY_POSTGRES_SETUP.md](RAILWAY_POSTGRES_SETUP.md) for full setup.

## Troubleshooting

**Deployment fails?**
- Check Railway logs in dashboard
- Run `railway logs` in CLI

**Can't access admin portal?**
- Make sure URL ends with `/admin-portal.html`
- Try: `https://[your-url]/admin.html` (alternative)

**Login not working?**
- Test locally first: `python3 test_admin_auth.py`
- Check browser console (F12)
- Try incognito mode

## Documentation

- Full guide: [RAILWAY_DEPLOYMENT.md](RAILWAY_DEPLOYMENT.md)
- Domain setup: [DOMAIN_SETUP.md](DOMAIN_SETUP.md)
- Admin access: [ADMIN_ACCESS.md](ADMIN_ACCESS.md)
- General deployment: [DEPLOYMENT.md](DEPLOYMENT.md)

## Support

- Railway Docs: <https://docs.railway.app>
- Railway Discord: <https://discord.gg/railway>
- Railway Status: <https://status.railway.app>

---

**Ready to deploy? Go to <https://railway.app> and click "Deploy from GitHub repo"!** 🚂

