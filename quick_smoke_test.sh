#!/usr/bin/env bash
set -euo pipefail

# PHINS: Quick smoke test for core flows

echo "🧪 PHINS Smoke Test"

python3 -m py_compile web_portal/server.py || { echo "❌ Syntax error"; exit 1; }

# Check if server already running
if curl -s http://localhost:8000/api/metrics >/dev/null 2>&1; then
	echo "✓ Using running server"
	PID=""
else
	echo "⚙️ Starting server..."
	python3 web_portal/server.py &
	PID=$!
	trap 'kill $PID 2>/dev/null || true' EXIT
	sleep 3
fi

policy_json='{"customer_id":"CUST-DEMO-1","coverage_amount":150000,"type":"life"}'

echo "➡️ Create policy"
POLICY_RESP=$(curl -s -X POST http://localhost:8000/api/policies/create_simple -H 'Content-Type: application/json' -d "$policy_json") || true
# Extract policy_id from response using Python
if [ -z "$POLICY_RESP" ]; then
	echo "⚠️ Empty policy response"
	POLICY_ID=""
else
POLICY_ID=$(echo "$POLICY_RESP" | python3 -c "import sys, json; data=json.load(sys.stdin); print(data.get('policy',{}).get('id',''))")
fi
echo "Derived POLICY_ID=$POLICY_ID"

echo "➡️ Create bill"
BILL_RESP=$(curl -s -X POST http://localhost:8000/api/billing/create \
	-H 'Content-Type: application/json' \
	-d "{\"policy_id\":\"$POLICY_ID\",\"amount_due\":100.0,\"due_days\":30}") || true
if [ -z "$BILL_RESP" ]; then
	echo "⚠️ Empty bill response"
	BILL_ID=""
else
BILL_ID=$(echo "$BILL_RESP" | python3 -c "import sys, json; data=json.load(sys.stdin); print(data.get('bill',{}).get('bill_id',''))")
fi
echo "Derived BILL_ID=$BILL_ID"

echo "➡️ Pay bill"
curl -s -X POST http://localhost:8000/api/billing/pay \
	-H 'Content-Type: application/json' \
	-d "{\"bill_id\":\"$BILL_ID\",\"amount\":100.0}" || true

echo "📊 Metrics"
curl -s http://localhost:8000/api/metrics || true

echo "✅ Smoke test completed"
