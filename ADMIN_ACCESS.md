# Accessing PHINS Admin Portal

## ✅ Authentication Status: WORKING

All demo accounts are functioning correctly!

## 🌐 How to Access

### Option 1: GitHub Codespaces (Current Environment)

The server is running at: `http://localhost:8000`

**Steps:**

1. Make sure the server is running:

   ```bash
   python3 web_portal/server.py
   ```

2. VS Code will show a notification about port 8000 being forwarded
   - Click "Open in Browser" or "Make Public"

3. The URL will be something like:

   ```text
   https://[workspace-name]-8000.app.github.dev/admin-portal.html
   ```

4. At the login screen, use any of these accounts:

   | Username | Password | Role | Access Level |
   |----------|----------|------|--------------|
   | `admin` | `$PHINS_ADMIN_PASSWORD` | Admin | Full Access - All Divisions |
   | `underwriter` | `$PHINS_UNDERWRITER_PASSWORD` | Underwriter | Underwriting Division |
   | `claims_adjuster` | `$PHINS_CLAIMS_PASSWORD` | Claims | Claims Division |
   | `accountant` | `$PHINS_ACCOUNTANT_PASSWORD` | Accountant | Accounting Division |

### Option 2: Local Machine

1. Clone the repository
2. Start the server:

   ```bash
   python3 web_portal/server.py
   ```

3. Open browser: http://localhost:8000/admin-portal.html
4. Login with demo credentials above

## 🔧 Troubleshooting

### "Cannot access admin-portal.html"

**Solution:**
1. Check if server is running:

   ```bash
   ps aux | grep server.py
   ```

2. If not running, start it:

   ```bash
   python3 web_portal/server.py
   ```

### "Login not working"

**Diagnosis:**

**Diagnosis:**
- Run the authentication test:

  ```bash
  python3 test_admin_auth.py
  ```

If tests pass but browser login fails:

- Clear browser cache and cookies
- Try incognito/private browsing mode
- Check browser console (F12) for JavaScript errors

### "Port 8000 already in use"

**Solution:**

```bash
# Kill existing server
pkill -f "python3 web_portal/server.py"

# Wait a moment
sleep 2

# Start fresh
python3 web_portal/server.py
```

### GitHub Codespaces Port Not Forwarded

**Solution:**

Steps to forward port:

1. Go to VS Code PORTS tab (bottom panel)
2. Find port 8000
3. Right-click → Port Visibility → Public
4. Click the globe icon to open in browser

## 📱 Available Portal Pages

| Page | URL | Purpose |
|------|-----|---------|
| **Admin Portal** | `/admin-portal.html` | Complete management system |
| **Alternative Admin** | `/admin.html` | Simplified admin view |
| **Customer Portal** | `/` or `/index.html` | Customer self-service |
| **Login Page** | `/login.html` | Standalone login |
| **Dashboard** | `/dashboard.html` | Customer dashboard |
| **Apply** | `/apply.html` | New policy application |
| **Quote** | `/quote.html` | Get insurance quote |

## 🧪 Testing Authentication

Run the included test script to verify all accounts work:

```bash
python3 test_admin_auth.py
```

Expected output:

```bash
✅ SUCCESS for all accounts
✅ admin-portal.html is accessible
✅ Page content looks correct
```

## 🚀 Quick Start Commands

**Start server:**

```bash
python3 web_portal/server.py
```

**Start server in background:**

```bash
python3 web_portal/server.py > /tmp/phins.log 2>&1 &
```

**View server logs:**

```bash
tail -f /tmp/phins.log
```

**Stop server:**

```bash
pkill -f "python3 web_portal/server.py"
```

## 💡 Tips

1. **First Time Access:** The admin portal requires login - this is intentional security
2. **Session Persistence:** Credentials are stored in browser localStorage
3. **Multiple Roles:** You can login with different accounts in different browser tabs/profiles
4. **Demo Data:** All data is in-memory and resets when server restarts

## 🔐 Security Notes

- These are **DEMO CREDENTIALS** only
- Do NOT use these passwords in production
- Real deployments need proper authentication (OAuth, JWT, etc.)
- Current implementation is for development/testing only

## 📚 Next Steps

After logging in, you can:

- View dashboard statistics
- Manage policies (create, view, update)
- Process underwriting applications
- Handle claims
- View BI dashboards (Actuary, Underwriting, Accounting)

For deployment to ```www.phins.ai```, see:

- [DEPLOYMENT.md](DEPLOYMENT.md)
- [DOMAIN_SETUP.md](DOMAIN_SETUP.md)
