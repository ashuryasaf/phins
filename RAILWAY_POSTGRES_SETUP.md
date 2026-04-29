# Railway PostgreSQL Setup Guide for PHINS

## Step-by-Step Instructions

### 1️⃣ Get Database URL from PostgreSQL Service

1. Open Railway Dashboard: https://railway.app/dashboard
2. Select your project
3. Click on the **PostgreSQL** service (database icon)
4. Click **Variables** tab
5. Find `DATABASE_URL` and click **Copy** button

Example format:
```
postgresql://postgres:ABCdef123xyz@roundhouse.proxy.rlwy.net:12345/railway
```

---

### 2️⃣ Add Variables to PHINS Web Service

1. Click on your **PHINS web service** (the Python app)
2. Click **Variables** tab
3. Click **+ New Variable** for each:

```
DATABASE_URL = <paste the URL from step 1>
USE_DATABASE = true
ENABLE_LEDGER_PERSISTENCE = true
ALLOW_LEGACY_DEMO_PASSWORDS = false
```

**Screenshot location in Railway:**
```
Your Project
├── PostgreSQL (database) ← Copy DATABASE_URL from here
└── phins-portal (web)    ← Paste variables here
```

---

### 3️⃣ Add Persistent Volume (Important!)

1. Click on **PHINS web service**
2. Click **Settings** tab
3. Scroll to **Volumes**
4. Click **+ Add Volume**
5. Set:
   - Mount Path: `/data`
   - Size: 1GB (or more)

The server automatically detects a volume mounted at `/data` and stores
ledger data there.  You can also set the path explicitly:
```
LEDGER_PERSISTENCE_FILE = /data/phins_ledger.json
```

---

### 4️⃣ Redeploy

After adding all variables:
1. Railway will auto-redeploy
2. Or click **Deployments** → **Redeploy**

---

### 5️⃣ Verify Connection

Check the deployment logs for:
```
✓ Database connection successful
✓ Database schema initialized
✓ Default admin users seeded
```

---

## Environment Variables Summary

| Variable | Value | Required |
|----------|-------|----------|
| `DATABASE_URL` | `postgresql://...` | ✅ Yes |
| `USE_DATABASE` | `true` | ✅ Yes |
| `ENABLE_LEDGER_PERSISTENCE` | `true` | ✅ Yes |
| `LEDGER_PERSISTENCE_FILE` | `/data/phins_ledger.json` | Optional (auto-detected if `/data` volume mounted) |
| `ALLOW_LEGACY_DEMO_PASSWORDS` | `false` | ✅ Yes (security) |

---

## Troubleshooting

### Error: "Database connection failed"
- Check DATABASE_URL is correctly copied
- Ensure PostgreSQL service is running
- Check if the URL starts with `postgresql://` (not `postgres://`)

### Error: "No module named 'sqlalchemy'"
- This should not happen with the current Dockerfile
- Check requirements.txt includes: `sqlalchemy`, `psycopg2-binary`

### Data not persisting
- Ensure volume is mounted at `/data`
- Check `LEDGER_PERSISTENCE_FILE` points to `/data/...`
