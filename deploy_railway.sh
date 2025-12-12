#!/bin/bash
# Railway Deployment Script for PHINS Platform

set -e

echo "=========================================="
echo "🚂 PHINS Railway Deployment"
echo "Domain: www.phins.ai"
echo "=========================================="
echo ""

# Check for Railway CLI
if ! command -v railway &> /dev/null; then
    echo "📦 Railway CLI not found. Installing..."
    echo ""
    echo "Run one of these commands:"
    echo ""
    echo "NPM:  npm i -g @railway/cli"
    echo "Brew: brew install railway"
    echo "Manual: https://docs.railway.app/develop/cli"
    echo ""
    read -p "Install Railway CLI now with npm? (y/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        npm i -g @railway/cli
    else
        echo "Please install Railway CLI and run this script again"
        exit 1
    fi
fi

echo "✅ Railway CLI found: $(railway --version)"
echo ""

# Check if logged in
if ! railway whoami &> /dev/null; then
    echo "🔐 Not logged in to Railway"
    echo "Opening browser for authentication..."
    railway login
    echo ""
fi

echo "✅ Logged in to Railway as: $(railway whoami)"
echo ""

# Check git status
if ! git rev-parse --git-dir > /dev/null 2>&1; then
    echo "❌ Not a git repository"
    exit 1
fi

echo "📊 Git Status:"
git status --short
echo ""

# Check for uncommitted changes
if ! git diff-index --quiet HEAD --; then
    echo "⚠️  You have uncommitted changes"
    read -p "Commit changes now? (y/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        git add .
        git commit -m "Deploy: PHINS platform with www.phins.ai domain configuration"
        git push origin main
        echo "✅ Changes committed and pushed"
    else
        echo "⚠️  Deploying with uncommitted changes (Railway will use last commit)"
    fi
fi

echo ""
echo "🚀 Railway Deployment Options:"
echo ""
echo "1️⃣  Link existing project"
echo "2️⃣  Create new project"
echo "3️⃣  Deploy current project"
echo ""
read -p "Choose option (1-3): " -n 1 -r option
echo
echo ""

case $option in
    1)
        echo "🔗 Linking to existing Railway project..."
        railway link
        ;;
    2)
        echo "➕ Creating new Railway project..."
        railway init
        ;;
    3)
        echo "🚀 Deploying to Railway..."
        ;;
    *)
        echo "Invalid option"
        exit 1
        ;;
esac

echo ""
echo "📤 Deploying to Railway..."
railway up

echo ""
echo "✅ Deployment initiated!"
echo ""
echo "📊 Check deployment status:"
echo "  railway status"
echo ""
echo "📝 View logs:"
echo "  railway logs"
echo ""
echo "🌐 Open in browser:"
echo "  railway open"
echo ""

# Get the URL
echo "🔍 Getting deployment URL..."
RAILWAY_URL=$(railway domain 2>/dev/null || echo "")

if [ -n "$RAILWAY_URL" ]; then
    echo "✅ Your app is deployed at: $RAILWAY_URL"
    echo ""
    echo "📋 Next Steps:"
    echo "1. Add custom domain www.phins.ai:"
    echo "   - Go to Railway dashboard"
    echo "   - Settings → Domains → Custom Domain"
    echo "   - Enter: www.phins.ai"
    echo "   - Add CNAME record to your DNS:"
    echo "     Name: www"
    echo "     Value: (provided by Railway)"
    echo ""
    echo "2. Test your deployment:"
    echo "   $RAILWAY_URL/admin-portal.html"
    echo ""
    echo "3. Login with demo credentials:"
    echo "   admin / admin123"
else
    echo "⚠️  Could not retrieve deployment URL automatically"
    echo "Run: railway domain"
    echo "Or visit: railway open"
fi

echo ""
echo "📚 Documentation:"
echo "  - DEPLOYMENT.md - Full deployment guide"
echo "  - DOMAIN_SETUP.md - Custom domain setup"
echo "  - ADMIN_ACCESS.md - Admin portal access"
echo ""
echo "✅ Deployment complete!"
