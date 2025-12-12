#!/bin/bash
# Quick commands for working with pending applications

echo "🛡️  PHINS Pending Applications - Quick Commands"
echo "================================================"
echo ""

# Check if server is running
echo "1️⃣  Generate Pending Applications Report:"
echo "   python test_complete_flow.py"
echo ""

echo "2️⃣  View Live Server Applications:"
echo "   python list_pending_applications.py"
echo ""

echo "3️⃣  Start Web Server:"
echo "   python web_portal/server.py"
echo ""

echo "4️⃣  Access Admin Portal:"
echo "   Open: http://localhost:8000/admin-portal.html"
echo "   Login: admin / admin123"
echo ""

echo "5️⃣  Check API Endpoints:"
echo "   curl http://localhost:8000/api/dashboard"
echo "   curl http://localhost:8000/api/underwriting"
echo ""

echo "6️⃣  View JSON Report:"
echo "   cat pending_applications_report.json | python -m json.tool"
echo ""

echo "================================================"
echo "📚 Documentation:"
echo "   - PENDING_APPLICATIONS_SUMMARY.md"
echo "   - CLIENT_DATA_STORAGE_ANALYSIS.md"
echo "================================================"
