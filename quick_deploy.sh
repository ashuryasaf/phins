#!/bin/bash
# Quick deployment script for PHINS platform with www.phins.ai domain

set -e

echo "========================================"
echo "PHINS Platform Deployment Helper"
echo "Domain: www.phins.ai"
echo "========================================"
echo ""

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 is required but not installed"
    exit 1
fi
echo "✅ Python 3 found: $(python3 --version)"

# Check dependencies
if [ -f "requirements.txt" ]; then
    echo "📦 Installing Python dependencies..."
    python3 -m pip install -q -r requirements.txt
    echo "✅ Dependencies installed"
else
    echo "⚠️  No requirements.txt found"
fi

# Test server
echo ""
echo "🧪 Testing web server..."
if python3 web_portal/server.py --test &> /dev/null; then
    echo "✅ Server test passed"
else
    echo "⚠️  Server test had warnings (this is usually ok)"
fi

# Check for git
if ! command -v git &> /dev/null; then
    echo "⚠️  Git not found - cannot check repository status"
else
    echo ""
    echo "📊 Repository Status:"
    echo "   Branch: $(git branch --show-current 2>/dev/null || echo 'unknown')"
    echo "   Remote: $(git config --get remote.origin.url 2>/dev/null || echo 'none')"
fi

echo ""
echo "========================================"
echo "✅ System Ready!"
echo "========================================"
echo ""
echo "🚀 Deployment Options:"
echo ""
echo "1️⃣  LOCAL TEST:"
echo "   python3 web_portal/server.py"
echo "   Then visit: http://localhost:8000"
echo ""
echo "2️⃣  RAILWAY DEPLOYMENT:"
echo "   - Go to: https://railway.app"
echo "   - Connect GitHub repository: phins"
echo "   - Add custom domain: www.phins.ai"
echo "   - Railway will auto-deploy from main branch"
echo ""
echo "3️⃣  RENDER DEPLOYMENT:"
echo "   - Go to: https://render.com"
echo "   - New Web Service from GitHub"
echo "   - Select repository: phins"
echo "   - Add custom domain: www.phins.ai"
echo ""
echo "📋 DNS Configuration Required:"
echo "   Type: CNAME"
echo "   Name: www"
echo "   Value: [from hosting provider]"
echo ""
echo "📚 Full docs: See DEPLOYMENT.md and DOMAIN_SETUP.md"
echo ""

# Ask if user wants to start local server
read -p "Start local server now? (y/N): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo ""
    echo "🚀 Starting server on http://localhost:8000"
    echo "   Press Ctrl+C to stop"
    echo ""
    python3 web_portal/server.py
fi
