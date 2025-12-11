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
5. Run with systemd for auto-restart:

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

6. Set up nginx reverse proxy for port 80/443

## Environment Configuration

The web portal runs on port 8000 by default. To change:

Edit `web_portal/server.py`:
```python
PORT = int(os.environ.get('PORT', 8000))
```

Then set `PORT` environment variable in your hosting platform.

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
