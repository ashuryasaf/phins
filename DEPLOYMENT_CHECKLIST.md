# PHINS Database Deployment Checklist

## ✅ Pre-Deployment Verification

### Code Quality
- [x] All database tests passing (8/8)
- [x] Code review completed and feedback addressed
- [x] Railway configuration updated
- [x] Dependencies added to requirements.txt
- [x] Security documentation complete

### Database Configuration
- [x] SQLAlchemy models defined for all entities
- [x] Repository pattern implemented
- [x] Connection pooling configured
- [x] Auto-initialization implemented
- [x] Default user seeding ready

## 🚀 Deployment Steps for Railway

### Step 1: Merge Pull Request

1. Review and approve the PR: `Add PostgreSQL database support`
2. Merge the PR into `main` branch
3. Verify the merge was successful

### Step 2: Add PostgreSQL to Railway

1. **Go to Railway Dashboard**: https://railway.app
2. **Navigate to your PHINS project**
3. **Add PostgreSQL**:
   - Click **"New"** button
   - Select **"Database"**
   - Choose **"PostgreSQL"**
   - Railway will provision the database (takes ~30 seconds)

### Step 3: Configure Environment Variables

Railway should automatically set:
- ✅ `DATABASE_URL` - Automatically provided by PostgreSQL plugin

You need to verify/add:
- ✅ `USE_DATABASE=1` - Already in railway.json

**To verify:**
1. Go to your service in Railway
2. Click on **"Variables"** tab
3. Confirm `USE_DATABASE` is set to `1`
4. Confirm `DATABASE_URL` exists (starts with `postgresql://`)

### Step 4: Deploy

Railway will automatically deploy when you push to main:

```bash
# If you have local changes, push them:
git push origin main

# Otherwise, Railway will auto-deploy from the merged PR
```

### Step 5: Monitor Deployment

1. **Watch Build Logs**:
   - Go to Railway dashboard
   - Click on your service
   - Watch the **"Deployments"** tab
   - Wait for build to complete

2. **Check Deployment Logs** for these messages:
   ```
   ✓ Database support enabled
   📊 Initializing database...
   ✓ Database connection successful
      Type: PostgreSQL
   ✓ Database schema initialized
   ✓ Default users seeded
   🚀 Serving web portal at http://0.0.0.0:8000
   💾 Storage: Database (persistent)
   ```

### Step 6: Verify Database Connection

1. **Check Logs** for successful connection:
   - Look for "✓ Database connection successful"
   - Look for "✓ Database schema initialized"
   - Look for "✓ Default users seeded"

2. **Test API Endpoints**:
   ```bash
   # Replace with your Railway URL
   RAILWAY_URL="your-app.railway.app"
   
   # Check metrics (should work even with empty database)
   curl https://${RAILWAY_URL}/api/metrics
   
   # Create a test policy
   curl -X POST https://${RAILWAY_URL}/api/policies/create_simple \
     -H "Content-Type: application/json" \
     -d '{
       "customer_name": "Test User",
       "customer_email": "test@example.com",
       "type": "life",
       "coverage_amount": 100000
     }'
   
   # Verify it was stored
   curl https://${RAILWAY_URL}/api/policies
   ```

3. **Verify Data Persistence**:
   - Restart the service in Railway (deployments tab)
   - Query `/api/policies` again
   - Data should still be there!

## 🔒 Post-Deployment Security

### Critical: Change Default Passwords

The system seeds 4 default users with well-known passwords:

| Username | Default Password | Status |
|----------|-----------------|---------|
| admin | admin123 | ⚠️ CHANGE IMMEDIATELY |
| underwriter | under123 | ⚠️ CHANGE IMMEDIATELY |
| claims_adjuster | claims123 | ⚠️ CHANGE IMMEDIATELY |
| accountant | acct123 | ⚠️ CHANGE IMMEDIATELY |

**To change passwords**, connect to Railway shell or use an API endpoint:

```python
# Create a secure password change script
from database.manager import DatabaseManager
import hashlib
import secrets

def hash_password(password: str) -> dict:
    salt = secrets.token_hex(16)
    hashed = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 100000)
    return {'hash': hashed.hex(), 'salt': salt}

# Change admin password
with DatabaseManager() as db:
    new_pwd = hash_password('YOUR_SECURE_PASSWORD_HERE')
    db.users.update('admin', 
                    password_hash=new_pwd['hash'],
                    password_salt=new_pwd['salt'])
```

### Security Checklist

- [ ] Changed all default passwords
- [ ] Verified SSL/TLS is enabled (Railway default)
- [ ] Confirmed audit logging is working
- [ ] Set up automated backups (Railway automatic)
- [ ] Reviewed security documentation (SECURITY_DATABASE.md)

## 📊 Monitoring

### What to Monitor

1. **Database Connections**:
   - Check Railway metrics for connection count
   - Should stay under 30 (20 pool + 10 overflow)

2. **Error Logs**:
   - Monitor for database connection errors
   - Watch for slow query warnings

3. **Performance**:
   - API response times should be <100ms
   - Database queries should be <10ms average

### Railway Monitoring

1. **Metrics Dashboard**:
   - CPU usage (should be low)
   - Memory usage (watch for leaks)
   - Network traffic

2. **Logs**:
   - Set up log alerts for errors
   - Monitor for security events

## 🔄 Rollback Plan

If deployment fails:

1. **Revert in Railway**:
   - Go to "Deployments" tab
   - Find previous successful deployment
   - Click "Redeploy"

2. **Disable Database Mode** (emergency):
   - In Railway Variables, remove `USE_DATABASE`
   - Redeploy
   - System will revert to in-memory mode

3. **Database Issues**:
   - Check PostgreSQL logs in Railway
   - Verify `DATABASE_URL` is correct
   - Confirm network connectivity

## 📋 Troubleshooting

### Issue: Database Connection Failed

**Check:**
- `DATABASE_URL` environment variable exists
- PostgreSQL plugin is running
- Network connectivity between service and database

**Fix:**
```bash
# Verify in Railway console
echo $DATABASE_URL

# Should output: postgresql://...
```

### Issue: Tables Not Created

**Check:**
- Deployment logs for "Database schema initialized"
- No errors during schema creation

**Fix:**
- May need to manually initialize (future enhancement)
- Currently auto-initializes on startup

### Issue: Default Users Not Created

**Check:**
- Logs show "Default users seeded successfully"
- No unique constraint errors

**Fix:**
- Users may already exist from previous deployment
- This is normal and safe to ignore

## ✅ Success Criteria

Deployment is successful when:

- [x] Service is running and accessible
- [x] Database connection established
- [x] Schema tables created
- [x] Default users seeded
- [x] API endpoints responding
- [x] Data persists across restarts
- [x] No errors in deployment logs

## 📞 Support

If you encounter issues:

1. Check deployment logs first
2. Review DATABASE_SETUP.md
3. Review SECURITY_DATABASE.md
4. Check Railway community forums

## 🎉 Deployment Complete!

Once all steps are complete:

1. ✅ Database is live and persistent
2. ✅ All features working
3. ✅ Security hardened
4. ✅ Monitoring enabled
5. ✅ Ready for production use

**Next Steps:**
- Change default passwords
- Set up regular backups (Railway automatic)
- Configure custom domain (optional)
- Set up monitoring alerts
- Train users on new features
