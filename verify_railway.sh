#!/bin/bash
# Railway Deployment Verification Script

echo "🔍 PHINS Railway Deployment Checker"
echo "====================================="
echo ""

# Check if URL provided
if [ -z "$1" ]; then
    echo "Usage: ./verify_railway.sh <your-railway-url>"
    echo ""
    echo "Example:"
    echo "  ./verify_railway.sh https://phins-production-xxxx.up.railway.app"
    echo ""
    exit 1
fi

URL="$1"
URL="${URL%/}"  # Remove trailing slash

echo "Testing deployment at: $URL"
echo ""

# Test 1: Homepage
echo "1️⃣  Testing homepage..."
STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$URL/")
if [ "$STATUS" -eq 200 ]; then
    echo "   ✅ Homepage accessible (HTTP $STATUS)"
else
    echo "   ❌ Homepage failed (HTTP $STATUS)"
fi

# Test 2: Admin Portal
echo ""
echo "2️⃣  Testing admin portal..."
STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$URL/admin-portal.html")
if [ "$STATUS" -eq 200 ]; then
    echo "   ✅ Admin portal accessible (HTTP $STATUS)"
else
    echo "   ❌ Admin portal failed (HTTP $STATUS)"
fi

# Test 3: Login API
echo ""
echo "3️⃣  Testing login API..."
RESPONSE=$(curl -s -X POST "$URL/api/login" \
    -H "Content-Type: application/json" \
    -d '{"username":"admin","password":"admin123"}')

if echo "$RESPONSE" | grep -q "token"; then
    echo "   ✅ Login API working"
    echo "   Token: $(echo $RESPONSE | grep -o '"token":"[^"]*"' | cut -d'"' -f4 | head -c 30)..."
else
    echo "   ❌ Login API failed"
    echo "   Response: $RESPONSE"
fi

# Test 4: Policies API
echo ""
echo "4️⃣  Testing policies API..."
STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$URL/api/policies")
if [ "$STATUS" -eq 200 ]; then
    echo "   ✅ Policies API accessible (HTTP $STATUS)"
else
    echo "   ❌ Policies API failed (HTTP $STATUS)"
fi

# Test 5: Check response time
echo ""
echo "5️⃣  Testing response time..."
TIME=$(curl -s -o /dev/null -w "%{time_total}" "$URL/")
echo "   ⏱️  Response time: ${TIME}s"
if (( $(echo "$TIME < 2" | bc -l) )); then
    echo "   ✅ Fast response"
else
    echo "   ⚠️  Slow response (consider optimizing)"
fi

echo ""
echo "====================================="
echo "🎯 Deployment Status Summary"
echo "====================================="

# Count successes
SUCCESS_COUNT=0
if [ "$STATUS" -eq 200 ]; then ((SUCCESS_COUNT++)); fi

if [ $SUCCESS_COUNT -ge 3 ]; then
    echo "✅ Deployment is HEALTHY"
    echo ""
    echo "🔐 Access your admin portal:"
    echo "   $URL/admin-portal.html"
    echo ""
    echo "🔑 Demo Credentials:"
    echo "   admin / admin123"
    echo "   underwriter / under123"
    echo "   claims_adjuster / claims123"
    echo "   accountant / acct123"
else
    echo "❌ Deployment has ISSUES"
    echo ""
    echo "Troubleshooting:"
    echo "1. Check Railway logs: railway logs"
    echo "2. Verify server is running in Railway dashboard"
    echo "3. Check build logs for errors"
    echo "4. Ensure railway.json is configured correctly"
fi

echo ""
