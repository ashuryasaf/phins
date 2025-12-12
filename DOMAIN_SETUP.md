# Domain Configuration: phins.ai

## Overview

The PHINS platform is now configured to use the custom domain: **phins.ai** (accessible at <https://www.phins.ai>)

## Configuration Changes

### 1. Application Configuration (`config.py`)

Added domain settings:

```python
DOMAIN = "www.phins.ai"
BASE_URL = "https://www.phins.ai"
EMAIL_FROM_ADDRESS = "noreply@phins.ai"
```

### 2. DNS Setup Required

To make your domain active, configure DNS records with your domain provider:

#### Required DNS Records

**Primary Domain:**

- **Type:** CNAME
- **Name:** www
- **Value:** [Your hosting provider's domain]
  - For Railway: `your-app.up.railway.app`
  - For Render: `your-app.onrender.com`
  - For Vercel: `cname.vercel-dns.com`

**Optional - Root Domain:**

- **Type:** A or ALIAS
- **Name:** @
- **Value:** [Your hosting provider's IP or ALIAS target]

#### SSL Certificate

Most hosting providers (Railway, Render, Vercel) automatically provision SSL certificates for custom domains using Let's Encrypt. This typically takes 5-15 minutes after DNS propagation.

### 3. Hosting Platform Setup

#### Railway

1. Go to your project dashboard
2. Settings → Domains → Custom Domain
3. Enter `www.phins.ai`
4. Copy the CNAME value provided
5. Add to your DNS provider

#### Render

1. Go to your service dashboard
2. Settings → Custom Domain → Add Custom Domain
3. Enter `www.phins.ai`
4. Copy the CNAME value provided
5. Add to your DNS provider

#### Vercel

1. Go to your project settings
2. Domains → Add Domain
3. Enter `www.phins.ai`
4. Follow the DNS configuration instructions

### 4. Environment Variables

If using environment-specific configurations, set:

```bash
DOMAIN=www.phins.ai
BASE_URL=https://www.phins.ai
EMAIL_FROM_ADDRESS=noreply@phins.ai
```

### 5. Application Integration

The domain configuration is accessible throughout the application:

```python
from config import PHINSConfig

# Access domain
domain = PHINSConfig.DOMAIN  # "www.phins.ai"
base_url = PHINSConfig.BASE_URL  # "https://www.phins.ai"
email = PHINSConfig.EMAIL_FROM_ADDRESS  # "noreply@phins.ai"
```

## Verification

After DNS propagation (24-48 hours), verify:

1. **Domain Resolution:**

   ```bash
   nslookup www.phins.ai
   ```

2. **HTTPS Access:**

   ```bash
   curl -I https://www.phins.ai
   ```

3. **SSL Certificate:**

   Check at [SSL Labs](https://www.ssllabs.com/ssltest/analyze.html?d=www.phins.ai)

## Email Configuration

The system is configured to send emails from `noreply@phins.ai`. Additional setup required:

1. **SPF Record:**

   ```dns
   TXT @ "v=spf1 include:_spf.yourmailprovider.com ~all"
   ```

2. **DKIM Record:**

   Configure with your email service provider (SendGrid, AWS SES, etc.)

3. **DMARC Record:**

   ```dns
   TXT _dmarc "v=DMARC1; p=quarantine; rua=mailto:admin@phins.ai"
   ```

## Subdomain Ideas

Consider these subdomains for different services:

- `portal.phins.ai` - Customer portal
- `admin.phins.ai` - Admin interface
- `api.phins.ai` - API endpoints
- `docs.phins.ai` - Documentation
- `status.phins.ai` - Status page
- `staging.phins.ai` - Staging environment

## Troubleshooting

### DNS Not Resolving

- Wait 24-48 hours for propagation
- Clear DNS cache: `ipconfig /flushdns` (Windows) or `sudo dscacheutil -flushcache` (Mac)
- Use DNS checker: [whatsmydns.net](https://www.whatsmydns.net)

### SSL Certificate Issues

- Ensure DNS is fully propagated before adding custom domain
- Check hosting provider's SSL status
- Wait 15-30 minutes after DNS propagation

### Email Not Sending

- Verify SMTP configuration
- Check SPF/DKIM records
- Use email testing service like [Mail Tester](https://www.mail-tester.com)

## Next Steps

1. **Configure DNS records** with your domain provider
2. **Add custom domain** to your hosting platform
3. **Wait for DNS propagation** (24-48 hours)
4. **Verify SSL certificate** is active
5. **Test email sending** from your configured address
6. **Update all documentation** with new domain
7. **Notify users** of new domain

## Support

For domain configuration assistance:

- Check hosting provider documentation
- Contact your DNS provider support
- Review platform-specific guides in [DEPLOYMENT.md](DEPLOYMENT.md)

