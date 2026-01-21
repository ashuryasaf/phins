# SSL Certificate & TLS Security Analysis for www.phins.ai

**Date:** January 21, 2026  
**Status:** CRITICAL - Action Required  
**Request ID:** YURF7-M_RVm83-3bss7a6g

---

## Executive Summary

The website www.phins.ai is experiencing two critical issues:

1. **SSL Certificate Mismatch** - Causing browser security warnings
2. **Application Not Found (404)** - Railway service not properly configured

---

## Issue #1: SSL Certificate Mismatch

### Symptoms
- Google Chrome shows "unsafe web page" warning
- Browser displays SSL/TLS security error
- Users cannot access the website securely

### Technical Analysis

```
SSL Certificate Details:
- Subject:    CN=*.up.railway.app (WRONG - should be www.phins.ai)
- Issuer:     C=US, O=Let's Encrypt, CN=R12
- Valid From: Dec 6, 2025 GMT
- Expires:    Mar 6, 2026 GMT
- Protocol:   TLSv1.3 (secure)
- Cipher:     TLS_AES_128_GCM_SHA256 (secure)
```

### Error Message from OpenSSL
```
SSL: no alternative certificate subject name matches target host name 'www.phins.ai'
subjectAltName does not match www.phins.ai
```

### Root Cause
Railway is serving its **wildcard certificate** (`*.up.railway.app`) instead of provisioning a proper certificate for the custom domain `www.phins.ai`. This happens when:
- The custom domain is NOT registered in Railway's domain settings
- OR the domain verification is incomplete

---

## Issue #2: Application Not Found (404)

### Symptoms
- Error message: "Not Found - The train has not arrived at the station"
- Request ID: YURF7-M_RVm83-3bss7a6g

### Technical Analysis

```
DNS Configuration:
- CNAME: www.phins.ai → phins-portal-testing.up.railway.app
- IP Resolution: 66.33.22.165 (Railway infrastructure)

HTTP Response (bypassing SSL):
{"status":"error","code":404,"message":"Application not found"}
```

### Root Cause
Railway is receiving the request but cannot route it to an application because:
1. The custom domain `www.phins.ai` is not registered in the Railway project's domain settings
2. Or the underlying service (`phins-portal-testing`) is not running

---

## TLS Security Assessment

| Aspect | Status | Details |
|--------|--------|---------|
| TLS Version | SECURE | TLSv1.3 (latest) |
| Cipher Suite | SECURE | TLS_AES_128_GCM_SHA256 |
| Key Exchange | SECURE | X25519 |
| Signature | SECURE | RSASSA-PSS |
| Certificate Issuer | VALID | Let's Encrypt |
| Certificate Domain | INVALID | Wrong domain (*.up.railway.app) |

**Note:** The TLS infrastructure itself is secure. The only issue is the certificate is for the wrong domain.

---

## Fix Instructions

### Step 1: Access Railway Dashboard

1. Go to https://railway.app
2. Sign in with your account
3. Navigate to the **phins-portal-testing** project

### Step 2: Add Custom Domain

1. Click **Settings** in your project
2. Go to **Domains** section
3. Click **+ Custom Domain**
4. Enter: `www.phins.ai`
5. Railway will show the verification status

### Step 3: Verify DNS Configuration

Railway will check if your DNS is properly configured:

```
Current DNS (already correct):
Type: CNAME
Name: www
Value: phins-portal-testing.up.railway.app
```

The DNS is already pointing to Railway - this is correct.

### Step 4: Wait for SSL Certificate Provisioning

Once the custom domain is added:
1. Railway will automatically request a Let's Encrypt certificate
2. This typically takes **5-15 minutes**
3. Status will show "Certificate Issued" when complete

### Step 5: Verify Service is Running

In Railway dashboard:
1. Check the **Deployments** tab
2. Ensure the latest deployment shows **Active** status
3. Check **Logs** for any startup errors
4. Verify the health endpoint: `/api/health`

---

## Verification Commands

After fixing, verify with these commands:

```bash
# Check SSL certificate (should show www.phins.ai)
echo | openssl s_client -connect www.phins.ai:443 -servername www.phins.ai 2>/dev/null | openssl x509 -noout -subject

# Expected output: subject=CN = www.phins.ai

# Test HTTPS access
curl -I https://www.phins.ai

# Expected: HTTP/2 200 (or redirect)

# Test API health endpoint
curl https://www.phins.ai/api/health

# Expected: {"status": "healthy", ...}
```

---

## DNS Records Reference

Current configuration (already set correctly):

| Type | Name | Value | TTL |
|------|------|-------|-----|
| CNAME | www | phins-portal-testing.up.railway.app | Auto |

If you also want the root domain (phins.ai without www):

| Type | Name | Value | TTL |
|------|------|-------|-----|
| A | @ | (Railway IP from dashboard) | Auto |

---

## Common Issues & Solutions

### "Certificate Not Issued"
- **Cause:** Railway cannot verify domain ownership
- **Fix:** Ensure DNS CNAME points to your Railway app domain
- **Wait:** Up to 24-48 hours for DNS propagation

### "Domain Verification Failed"
- **Cause:** DNS not pointing to Railway
- **Fix:** Check CNAME record is correct
- **Test:** `dig www.phins.ai CNAME +short`

### "Application Not Found" Persists
- **Cause:** Service not deployed or crashed
- **Fix:** 
  1. Check Railway logs
  2. Trigger a new deployment
  3. Verify `railway.json` configuration

---

## Railway Dashboard Quick Link

Visit your Railway project:
```
https://railway.app/dashboard
```

Look for project: **phins-portal-testing**

---

## Support Resources

- Railway Documentation: https://docs.railway.app/deploy/custom-domains
- Railway Status: https://status.railway.app
- Let's Encrypt: https://letsencrypt.org/docs/

---

## Summary of Required Actions

| Priority | Action | Who |
|----------|--------|-----|
| 1 | Add `www.phins.ai` as custom domain in Railway | Admin |
| 2 | Verify service is running | Admin |
| 3 | Wait for SSL certificate provisioning | Automatic |
| 4 | Test website access | Admin |

---

*Generated by PHINS SSL Security Analysis*
