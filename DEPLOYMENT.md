# PHINS Web Portal Deployment Guide

This guide covers multiple deployment options for the PHINS web portal.

## Prerequisites

- Git repository with your code
- Account on your chosen hosting platform

## Deployment Options

### 1. Railway (Recommended - Easiest)

Railway provides free hosting with automatic deployments from GitHub.

**Steps:**

1. Go to [railway.app](https://railway.app)
2. Sign in with GitHub
3. Click "New Project" → "Deploy from GitHub repo"
4. Select the `phins` repository
5. Railway will auto-detect Python and deploy
6. Your site will be live at `https://[project-name].railway.app`

**Configuration:**

- Uses `railway.json` for deployment settings
- Automatically runs `python3 web_portal/server.py`
- Port is automatically detected

**Custom Domain Setup:**

To use your custom domain `www.phins.ai`:

1. In Railway dashboard, go to Settings → Domains
2. Click "Custom Domain"
3. Enter `www.phins.ai`
4. Add the provided CNAME record to your DNS:
   - **Name:** `www`
   - **Value:** (provided by Railway)
5. Wait for DNS propagation (up to 48 hours)

### 2. Render

Render offers free web services with easy GitHub integration.

**Steps:**

1. Go to [render.com](https://render.com)
2. Sign in with GitHub
3. Click "New +" → "Web Service"
4. Connect your `phins` repository
5. Use these settings:
   - **Name:** phins-portal
   - **Environment:** Python 3
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `python3 web_portal/server.py`
6. Click "Create Web Service"

**Configuration:**

- Uses `render.yaml` for infrastructure-as-code
- Add a `cron` service in `render.yaml` for monthly auto-pay execution

**Monthly auto-pay cron (recommended):**

- The repo now includes `scripts/run_monthly_auto_pay.py`
- Schedule it for **00:00 UTC on the 1st of every month**
- Set `MONTHLY_AUTO_PAY_COMMAND_TOKEN` in both the web service and the cron job
- The command exits after processing and writes a persisted batch report into the
  main ledger persistence file

**Custom Domain Setup:**

To use `www.phins.ai` with Render:

1. In Render dashboard, go to Settings → Custom Domain
2. Click "Add Custom Domain"
3. Enter `www.phins.ai`
4. Add the provided CNAME record to your DNS provider:
   - **Name:** `www`
   - **Value:** (provided by Render)
5. Render will automatically provision SSL certificate

Additional features:

- Free tier includes SSL and custom domains


### 3. Docker (Self-Hosted)

Deploy using Docker on any platform (AWS, Azure, DigitalOcean, etc.)

**Build and Run Locally:**

```bash
# Build the image
docker build -t phins-portal .

# Run the container
docker run -p 8000:8000 phins-portal

# Access at http://localhost:8000
```

**Deploy to Cloud:**

```bash
# Tag for your registry
docker tag phins-portal your-registry/phins-portal:latest

# Push to registry
docker push your-registry/phins-portal:latest

# Deploy on your platform (example: AWS ECS, Azure Container Instances, etc.)
```


### 4. Vercel (Serverless)

Vercel offers serverless Python deployments with global CDN.

**Steps:**

1. Install Vercel CLI: `npm i -g vercel`
2. Run: `vercel` in the project root
3. Follow prompts to link your project
4. Deploy: `vercel --prod`


**Configuration:**

- Uses `vercel.json` for routing and build settings
- Deploys as serverless functions
- Automatically gets SSL and custom domain support

### 5. Manual VPS Deployment

For full control, deploy to any VPS (DigitalOcean, Linode, AWS EC2, etc.)

**Steps:**

1. SSH into your server
2. Install Python 3.11+: `sudo apt update && sudo apt install python3 python3-pip`
3. Clone repository: `git clone https://github.com/ashuryasaf/phins.git`
4. Install dependencies: `cd phins && pip3 install -r requirements.txt`
5. Run with systemd for auto-restart

**Create systemd service** (`/etc/systemd/system/phins.service`):

```ini
[Unit]
Description=PHINS Web Portal
After=network.target

[Service]
Type=simple
User=www-data
WorkingDirectory=/var/www/phins
ExecStart=/usr/bin/python3 web_portal/server.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl enable phins
sudo systemctl start phins
```

**Monthly auto-pay with cron:**

Add a first-of-month cron entry for the same app environment:

```bash
0 0 1 * * cd /var/www/phins && MONTHLY_AUTO_PAY_COMMAND_TOKEN=your-token /usr/bin/python3 scripts/run_monthly_auto_pay.py >> /var/log/phins-monthly-autopay.log 2>&1
```

Set up nginx reverse proxy for port 80/443


## Environment Configuration

The web portal runs on port 8000 by default. To change:

Edit `web_portal/server.py`:

```python
PORT = int(os.environ.get('PORT', 8000))
```

Then set `PORT` environment variable in your hosting platform.

### Document intelligence pipeline environment variables

The document/assessment pipeline is fully functional with **no configuration**
(synchronous processing, self-hosted OCR, deterministic offline assessments).
The variables below opt in to async processing, external transcription, and
advisory LLM features:

| Variable | Default | Purpose |
|---|---|---|
| `PHINS_DOC_ASYNC` | `false` | Uploads enqueue enrichment jobs instead of parsing inline; worker threads run inside the web process |
| `PHINS_DOC_WORKER_CONCURRENCY` | `2` | Worker threads draining `document_processing_jobs` |
| `PHINS_DOC_WORKER_POLL_INTERVAL` | `2.0` | Seconds between queue polls |
| `PHINS_DOC_RETRY_SCHEDULE` | `30,120,600` | Retry backoff seconds; exhausted jobs go to `dead_letter` |
| `PHINS_DOC_CLAIM_TIMEOUT` | `600` | Claim expiry (crashed-worker recovery) |
| `PHINS_TRANSCRIPTION_PROVIDER` | `disabled` | `openai_compatible` enables Whisper-style audio transcription |
| `PHINS_TRANSCRIPTION_ENDPOINT` / `_API_KEY` / `_MODEL` | — | Transcription endpoint configuration |
| `PHINS_ASSESSMENT_AI_ENABLED` / `_ENDPOINT` / `_API_KEY` / `_MODEL` | off | Advisory LLM (never decides; deterministic offline otherwise) |
| `PHINS_LLM_ESCALATION_MODEL` | — | Stronger model used when facts contain contradictions |
| `PHINS_AI_ACCEPT_THRESHOLD` / `PHINS_AI_REVIEW_THRESHOLD` | `0.90` / `0.70` | Confidence → accepted / flagged / needs_review |
| `PHINS_AI_PRICE_INPUT_PER_MTOK`, `PHINS_AI_PRICE_OUTPUT_PER_MTOK`, `PHINS_AI_PRICE_PARSE_PER_PAGE`, `PHINS_AI_PRICE_TRANSCRIPTION_PER_MIN` | `0` | Cost-accounting unit prices (snapshotted per usage row; never hard-coded) |

Operational surfaces: `GET /api/health` includes `document_processing.queue`
depth; staff can inspect jobs via `GET /api/doc-service/jobs`, requeue
dead-letter jobs via `POST /api/doc-service/jobs/requeue`, and review costs
via `GET /api/ai-usage/summary`. For scale-out, run a dedicated worker
service with `./scripts/entrypoint.sh worker` (requires `USE_DATABASE=true`).

Video audio-track / keyframe enrichment needs `ffmpeg` on `PATH`. The default
image does **not** install it (the Debian package blew Railway PR-preview
build time past ~10 minutes). The pipeline degrades to a stub when ffmpeg is
missing. To bake ffmpeg into a custom image, rebuild with
`--build-arg INSTALL_FFMPEG=1` (or set that build argument in Railway).

### Alpaca Trading Terminal environment variables

To enable the live trading terminal with Alpaca Markets, set these environment
variables in Railway (or Render / your hosting platform):

| Variable | Required | Description |
|---|---|---|
| `ALPACA_API_KEY` | Yes | Alpaca API key ID (from [app.alpaca.markets](https://app.alpaca.markets)) |
| `ALPACA_SECRET_KEY` | Yes | Alpaca secret key (also accepted as `ALPACA_API_SECRET`) |
| `ALPACA_PAPER` | No | `true` (default) for paper trading, `false` for live |
| `ALPACA_BROKER_MODE` | No | `true` to enable Broker API endpoints (account creation, funding) |
| `TERMINAL_ACCESS_KEY` | Yes | Access key for the trading terminal UI authentication (legacy `INVESTMENT_AI_ACCESS_KEY` still honored) |

**Paper trading** is enabled by default. To switch to live trading, set
`ALPACA_PAPER=false`. The terminal will show "Paper" or "Live" in the header.

The trading terminal is accessible at `/trading-terminal.html` and requires the
Investment AI access key to authenticate API calls.

### Confidential document access (investor / corporate documents)

Investor business plans under `/internal/` and corporate instruments under
`/legal/` (cap table, term sheet, shareholders/employment agreements, financial
model) plus `/pitch-dashboard.html` are **not** customer-facing. They are served
through an access gate (`security/confidential_access.py`), which also protects
`/api/legal-docs/{registry,sign,verify}` — those endpoints expose anchored
signer names and the signed content snapshot for a document instance.

| Variable | Required | Description |
|---|---|---|
| `PHINS_CONFIDENTIAL_ACCESS_TOKEN` | Recommended in production | Optional global open password / access token. Generate with `openssl rand -hex 32`. Alias: `PHINS_INVESTOR_ACCESS_TOKEN` |
| `SESSION_SECRET_KEY` | Yes, in production | Server-only secret used to sign staff-unlock and share-link cookies (the shared confidential token is never used for signing) |
| `PHINS_CONFIDENTIAL_DOCS_PUBLIC` | No | `true` publishes the documents to anyone (explicit, logged opt-out) |
| `PHINS_CONFIDENTIAL_PATHS` | No | Extra paths to gate. Entries ending in `/` are prefixes, otherwise exact files |
| `PHINS_CONFIDENTIAL_COOKIE_MAX_AGE` | No | Access cookie lifetime in seconds (default `43200`, 12h) |

Access is granted when any of the following holds:

1. **Staff session** (admin/accountant/underwriter/actuary/compliance/founder)
2. **Admin password unlock** on the access-restricted page
   (`POST /api/confidential/admin-unlock`) — enters staff username/password,
   sets an HttpOnly staff-unlock cookie, and returns a normal auth token
3. **Share link** (HTML pages only) with a simple open password — single-use or
   multi-use (`?share=<id>` + `POST /api/confidential/share-unlock`)
4. **Global access token** via `?access_token=` / access cookie

#### Admin unlock (no shared token required)

When production has no `PHINS_CONFIDENTIAL_ACCESS_TOKEN`, anonymous callers
still see **Access restricted**, but staff can unlock from that page with their
admin-level password (`username` defaults to `admin`, password =
`PHINS_ADMIN_PASSWORD`). This is the supported path for
`https://www.phins.ai/pitch-dashboard.html`.

If `PHINS_CONFIDENTIAL_ACCESS_TOKEN` **is** set, the same form also accepts that
value as an open password (sets the access cookie). Staff unlock still works
in parallel via `PHINS_ADMIN_PASSWORD`.

Required for password unlock to stick across workers:

- `SESSION_SECRET_KEY` (signs the staff-unlock cookie)
- `PHINS_ADMIN_PASSWORD` (or another staff role password in `STAFF_ROLES`)

#### Share links (single / multi use)

Staff create share links after unlocking:

```bash
curl -X POST https://<host>/api/confidential/shares \
  -H "Authorization: Bearer <staff-token>" \
  -H "Content-Type: application/json" \
  -d '{
    "path": "/pitch-dashboard.html",
    "password": "simple-open-password",
    "mode": "single",
    "label": "Investor ACME"
  }'
```

- `mode`: `single` (one successful open), `multi` / `unlimited`, or set
  `max_uses` to an integer
- Recipient URL: `https://<host>/pitch-dashboard.html?share=<id>`
- Opening prompts for the simple password; success sets a path-scoped HttpOnly
  share cookie and consumes one use
- **Downloaded documents are excluded** (`.pdf`, `.md`, `.docx`, …): share
  links cannot target or unlock exports. Downloads still require staff unlock
  or the global access token / open password
- List: `GET /api/confidential/shares` — revoke: `DELETE /api/confidential/shares/<id>`
- Share metadata (hashed passwords + use counts) persists in
  `database/confidential_shares.json`

Global token deep link (optional):

```text
https://<host>/internal/phins-investor-business-plan.html?access_token=<token>
```

The token is accepted once from the query string, exchanged for an
`HttpOnly; SameSite=Strict` cookie, and the caller is redirected to the bare URL
so the secret does not persist in browser history, `Referer` headers, or access
logs. The cookie stores an HMAC of the token, never the token itself.

**In production, if no token is configured anonymous access returns 503**, but
admin password unlock and share links remain available. Non-production
deployments (and `PHINS_TEST_MODE`) stay open so local development and CI are
unaffected. The boot log reports the gate's state.

### Monthly auto-pay environment variables

Set these for production auto-pay automation:

- `MONTHLY_AUTO_PAY_COMMAND_TOKEN`: shared secret used by deployment cron and the
  secured auto-pay execution path
- `PHINS_DEFAULT_AUTO_PAY_CARD_NUMBER`
- `PHINS_DEFAULT_AUTO_PAY_CARD_EXPIRY_MONTH`
- `PHINS_DEFAULT_AUTO_PAY_CARD_EXPIRY_YEAR`
- `PHINS_DEFAULT_AUTO_PAY_CARD_CVV`
- `PHINS_DEFAULT_AUTO_PAY_CARDHOLDER_NAME`

By default the app will normalize auto-pay to the **1st of each month** and will
assign the configured fallback Mastercard details to policies that do not already
have a credit card on file. Raw card values are not persisted in policy records;
only masked metadata and a derived token are stored.

### Post-deployment monthly trigger

The supported production command is:

```bash
python3 scripts/run_monthly_auto_pay.py
```

This command:

- normalizes eligible auto-pay schedules to the 1st of the month
- assigns the configured fallback Mastercard to customers missing a card
- processes due premium payments
- updates billing, ledgers, balance sheet, investment/client wallet flows, and
  persisted reporting
- sends customer notifications when configuration or payment state changes

Use platform scheduling rather than an in-process background thread so the job
does not run multiple times on horizontally scaled web instances.

## Custom Domain

Most platforms (Railway, Render, Vercel) support custom domains:

1. Go to project settings
2. Add your domain
3. Update DNS records as instructed
4. SSL certificates are auto-provisioned

## Monitoring

After deployment:

- Check logs in platform dashboard
- Monitor uptime and performance
- Set up alerts for downtime


## Static Files

The portal serves static files from `web_portal/static/`:

- `index.html` - Main page
- `styles.css` - Styling
- `script.js` - JavaScript functionality
- Images and other assets

## Security Notes

For production deployments:

1. Change default credentials in `server.py`
2. Add proper authentication (JWT, OAuth)
3. Use environment variables for secrets
4. Enable HTTPS (automatic on most platforms)
5. Implement rate limiting
6. Add CORS headers as needed
7. Set `PHINS_CONFIDENTIAL_ACCESS_TOKEN` so investor/corporate documents are
   not anonymously reachable (see *Confidential document access* above)
8. Leave `PHINS_EXPOSE_DEMO_OTP` unset — it returns live verification codes in
   API responses and is ignored in production, but should not be set at all
9. Never commit backups: `backups/` is gitignored and
   `scripts/backup_platform.sh` refuses to write into a tracked path. A snapshot
   can contain a full database dump (see `BACKUP.md`)

## Cost Estimates

- **Railway:** Free tier includes 500 hours/month ($5/month after)
- **Render:** Free tier with auto-sleep after inactivity
- **Vercel:** Free for hobby projects, generous limits
- **VPS:** $5-10/month (DigitalOcean, Linode)

## Support

For deployment issues:

- Check platform documentation
- Review application logs
- Ensure all dependencies in `requirements.txt`
- Verify Python version compatibility (3.11+)

## Quick Deploy Commands

**Railway:**

```bash
# Install Railway CLI
npm i -g @railway/cli

# Login and deploy
railway login
railway init
railway up
```

**Render:**

```bash
# Render auto-deploys from GitHub
# Just connect repo in dashboard
```

**Docker:**

```bash
docker build -t phins-portal .
docker run -p 8000:8000 phins-portal
```

---

Choose the platform that best fits your needs. Railway and Render are recommended for quick, hassle-free deployment with free tiers.
