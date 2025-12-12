#!/bin/bash
# Quick access helper for PHINS Admin Portal

echo "========================================"
echo "🔐 PHINS Admin Portal - Quick Access"
echo "========================================"
echo ""

# Check if server is running
if ps aux | grep -q "[p]ython3 web_portal/server.py"; then
    echo "✅ Server is running on port 8000"
    echo ""
    
    # Get the Codespaces URL if available
    if [ -n "$CODESPACE_NAME" ]; then
        echo "📍 GitHub Codespaces Environment Detected"
        echo ""
        echo "Access your admin portal at:"
        echo "https://${CODESPACE_NAME}-8000.app.github.dev/admin-portal.html"
        echo ""
        echo "⚠️  If the link doesn't work:"
        echo "1. Go to VS Code 'PORTS' tab (bottom panel)"
        echo "2. Find port 8000"
        echo "3. Right-click → 'Port Visibility' → 'Public'"
        echo "4. Click the globe icon 🌐 to open in browser"
    else
        echo "📍 Local Environment Detected"
        echo ""
        echo "Access your admin portal at:"
        echo "http://localhost:8000/admin-portal.html"
    fi
    
    echo ""
    echo "🔑 Demo Login Credentials:"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "Username: admin         | Password: admin123"
    echo "Username: underwriter   | Password: under123"
    echo "Username: claims_adjuster | Password: claims123"
    echo "Username: accountant    | Password: acct123"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
else
    echo "❌ Server is NOT running"
    echo ""
    echo "Start the server with:"
    echo "  python3 web_portal/server.py"
    echo ""
    echo "Or run this script with 'start' argument:"
    echo "  ./admin_access.sh start"
fi

echo ""

# Handle start command
if [ "$1" == "start" ]; then
    if ps aux | grep -q "[p]ython3 web_portal/server.py"; then
        echo "ℹ️  Server already running"
    else
        echo "🚀 Starting server..."
        cd "$(dirname "$0")"
        python3 web_portal/server.py > /tmp/phins_server.log 2>&1 &
        sleep 2
        
        if ps aux | grep -q "[p]ython3 web_portal/server.py"; then
            echo "✅ Server started successfully!"
            echo ""
            echo "Re-run this script to get the access URL:"
            echo "  ./admin_access.sh"
        else
            echo "❌ Failed to start server. Check logs:"
            echo "  tail -f /tmp/phins_server.log"
        fi
    fi
elif [ "$1" == "stop" ]; then
    echo "🛑 Stopping server..."
    pkill -f "python3 web_portal/server.py"
    sleep 1
    echo "✅ Server stopped"
elif [ "$1" == "test" ]; then
    echo "🧪 Running authentication test..."
    python3 test_admin_auth.py
fi

echo ""
echo "📚 Documentation:"
echo "  - Admin Access Guide: ADMIN_ACCESS.md"
echo "  - Admin Portal Guide: ADMIN_PORTAL_GUIDE.md"
echo "  - Deployment Guide: DEPLOYMENT.md"
echo "  - Domain Setup: DOMAIN_SETUP.md"
