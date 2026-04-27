"""
Tests for the Customer AI Report API endpoint (/api/customer/ai-report).

Validates:
- Authentication and authorization
- Period filtering (all, monthly, quarterly, annual, custom)
- Report data structure and integrity
- Real data aggregation without mock data
"""

import json
import threading
import time
from datetime import datetime
from http.server import HTTPServer
from urllib.request import urlopen, Request
from urllib.error import HTTPError

import web_portal.server as portal


class ServerThread(threading.Thread):
    def __init__(self, port):
        super().__init__(daemon=True)
        self.port = port
        self.httpd = HTTPServer(('127.0.0.1', port), portal.PortalHandler)

    def run(self):
        self.httpd.serve_forever()

    def stop(self):
        self.httpd.shutdown()


def _get(url, token=None):
    headers = {}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    req = Request(url, headers=headers)
    with urlopen(req) as resp:
        return json.loads(resp.read().decode('utf-8')), resp.status


def _post(url, payload, token=None):
    data = json.dumps(payload).encode('utf-8')
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    req = Request(url, data=data, headers=headers)
    with urlopen(req) as resp:
        return json.loads(resp.read().decode('utf-8')), resp.status


def _register_and_login(base, email="aireport@test.com"):
    """Register a customer via invitation code and log in."""
    reg_data, status = _post(base + "/api/register", {
        "name": "AI Report Tester",
        "email": email,
        "password": "Secure123456!",
        "phone": "555-1234",
        "dob": "1990-01-01",
        "invitation_code": "TESTCODE2026",
    })
    assert status == 201, f"Registration failed: {reg_data}"
    customer_id = reg_data.get('customer_id', '')

    login_data, status = _post(base + "/api/login", {
        "username": email,
        "password": "Secure123456!",
    })
    assert status == 200
    token = login_data.get('token', '')
    if not customer_id:
        customer_id = login_data.get('customer_id', '')
    return token, customer_id


def _seed_data(customer_id):
    """Seed policies, claims, billing, wallet, investments, and ledger for customer."""
    now = datetime.now().isoformat()

    portal.CUSTOMERS[customer_id] = {
        'id': customer_id,
        'name': 'AI Report Tester',
        'email': 'aireport@test.com',
        'credit_score': 720,
        'risk_score': 25,
        'created_at': now,
    }

    portal.POLICIES['POL-TEST-001'] = {
        'id': 'POL-TEST-001',
        'customer_id': customer_id,
        'policy_type': 'health',
        'status': 'Active',
        'coverage_amount': 50000,
        'monthly_premium': 250,
        'created_at': now,
    }
    portal.POLICIES['POL-TEST-002'] = {
        'id': 'POL-TEST-002',
        'customer_id': customer_id,
        'policy_type': 'auto',
        'status': 'Active',
        'coverage_amount': 30000,
        'monthly_premium': 150,
        'created_at': now,
    }

    portal.CLAIMS['CLM-TEST-001'] = {
        'id': 'CLM-TEST-001',
        'customer_id': customer_id,
        'status': 'Pending',
        'amount': 5000,
        'created_at': now,
    }
    portal.CLAIMS['CLM-TEST-002'] = {
        'id': 'CLM-TEST-002',
        'customer_id': customer_id,
        'status': 'Approved',
        'amount': 3000,
        'created_at': now,
    }

    portal.BILLING['BILL-TEST-001'] = {
        'id': 'BILL-TEST-001',
        'customer_id': customer_id,
        'status': 'Outstanding',
        'amount': 250,
        'amount_paid': 0,
        'due_date': '2026-05-15',
        'created_at': now,
    }
    portal.BILLING['BILL-TEST-002'] = {
        'id': 'BILL-TEST-002',
        'customer_id': customer_id,
        'status': 'Paid',
        'amount': 150,
        'amount_paid': 150,
        'created_at': now,
    }

    portal.HEALTH_WALLETS[customer_id] = {
        'balance': 1200,
        'monthly_deposit': 100,
        'transactions': [{
            'id': 'WAL-TX-001',
            'type': 'deposit',
            'amount': 1200,
            'timestamp': now,
        }],
    }

    portal.INVESTMENT_ACCOUNTS[customer_id] = {
        'balance': 5000,
        'index_balance': 2000,
        'bonds_balance': 2000,
        'crypto_balance': 1000,
        'deposits': [{
            'id': 'INV-DEP-001',
            'amount': 5000,
            'timestamp': now,
        }],
    }

    portal.TRANSACTION_LEDGER['TX-TEST-001'] = {
        'id': 'TX-TEST-001',
        'customer_id': customer_id,
        'type': 'premium_payment',
        'amount': -250,
        'timestamp': now,
    }
    portal.TRANSACTION_LEDGER['TX-TEST-002'] = {
        'id': 'TX-TEST-002',
        'customer_id': customer_id,
        'type': 'claim_payment',
        'amount': 3000,
        'timestamp': now,
    }


def test_ai_report_requires_auth():
    """Report endpoint rejects unauthenticated requests."""
    port = 8180
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.2)
    try:
        try:
            _get(f"http://127.0.0.1:{port}/api/customer/ai-report")
            assert False, "Should have returned 401/403"
        except HTTPError as e:
            assert e.code in (401, 403)
    finally:
        srv.stop()


def test_ai_report_returns_valid_structure():
    """Report returns all expected sections with correct data."""
    port = 8181
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.2)
    base = f"http://127.0.0.1:{port}"
    try:
        token, customer_id = _register_and_login(base, "aitest1@test.com")
        _seed_data(customer_id)

        data, status = _get(base + "/api/customer/ai-report?period=all", token)
        assert status == 200

        assert data['customer_id'] == customer_id
        assert 'generated_at' in data
        assert data['period']['type'] == 'all'

        assert data['profile']['name'] == 'AI Report Tester'

        assert data['policies']['total'] == 2
        assert data['policies']['active'] == 2
        assert data['policies']['total_coverage'] == 80000
        assert data['policies']['total_premium'] == 400

        assert data['claims']['total'] == 2
        assert data['claims']['pending'] == 1
        assert data['claims']['approved'] == 1
        assert data['claims']['total_amount'] == 8000

        assert data['billing']['total'] == 2
        assert data['billing']['outstanding'] == 1
        assert data['billing']['paid'] == 1
        assert data['billing']['outstanding_amount'] == 250
        assert data['billing']['total_paid'] == 150

        assert data['health_wallet']['balance'] == 1200

        assert data['investments']['balance'] == 5000
        assert data['investments']['index_balance'] == 2000

        assert data['ledger']['total_transactions'] == 2

        assert data['credit']['credit_score'] == 720
        assert data['credit']['risk_level'] == 'Low'

        assert data['total_assets'] == 6200
        assert data['total_liabilities'] == 250
        assert data['net_position'] == 5950

        assert isinstance(data['ai_insights'], list)
        assert isinstance(data['timeline'], list)
        assert len(data['timeline']) > 0
    finally:
        srv.stop()


def test_ai_report_period_filtering():
    """Report respects period parameter."""
    port = 8182
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.2)
    base = f"http://127.0.0.1:{port}"
    try:
        token, customer_id = _register_and_login(base, "aitest2@test.com")
        _seed_data(customer_id)

        for period in ['monthly', 'quarterly', 'annual', 'all']:
            data, status = _get(base + f"/api/customer/ai-report?period={period}", token)
            assert status == 200
            assert data['period']['type'] == period
    finally:
        srv.stop()


def test_ai_report_custom_date_range():
    """Report accepts custom date range."""
    port = 8183
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.2)
    base = f"http://127.0.0.1:{port}"
    try:
        token, customer_id = _register_and_login(base, "aitest3@test.com")
        _seed_data(customer_id)

        data, status = _get(
            base + "/api/customer/ai-report?period=custom&from=01/01/2026&to=31/12/2026",
            token,
        )
        assert status == 200
        assert data['period']['type'] == 'custom'
        assert data['policies']['total'] == 2
    finally:
        srv.stop()


def test_ai_report_no_mock_data():
    """With empty stores, report returns zeros, not fabricated data."""
    port = 8184
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.2)
    base = f"http://127.0.0.1:{port}"
    try:
        token, customer_id = _register_and_login(base, "aitest4@test.com")

        data, status = _get(base + "/api/customer/ai-report?period=all", token)
        assert status == 200

        assert data['policies']['total'] == 0
        assert data['policies']['items'] == []
        assert data['claims']['total'] == 0
        assert data['claims']['items'] == []
        assert data['billing']['total'] == 0
        assert data['billing']['items'] == []
        assert data['ledger']['total_transactions'] == 0
        assert data['total_assets'] == 0
        assert data['total_liabilities'] == 0
        assert data['net_position'] == 0
    finally:
        srv.stop()


def test_ai_report_customer_isolation():
    """Customer cannot see another customer's data."""
    port = 8185
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.2)
    base = f"http://127.0.0.1:{port}"
    try:
        token, customer_id = _register_and_login(base, "aitest5@test.com")

        portal.POLICIES['POL-OTHER-001'] = {
            'id': 'POL-OTHER-001',
            'customer_id': 'CUST-OTHER-999',
            'policy_type': 'health',
            'status': 'Active',
            'coverage_amount': 100000,
            'monthly_premium': 500,
            'created_at': '2026-01-01T00:00:00',
        }

        data, status = _get(base + "/api/customer/ai-report?period=all", token)
        assert status == 200
        assert data['policies']['total'] == 0
        for p in data['policies']['items']:
            assert p.get('customer_id') == customer_id
    finally:
        srv.stop()


def test_ai_report_insights_generation():
    """AI insights reflect actual data conditions."""
    port = 8186
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.2)
    base = f"http://127.0.0.1:{port}"
    try:
        token, customer_id = _register_and_login(base, "aitest6@test.com")
        _seed_data(customer_id)

        data, status = _get(base + "/api/customer/ai-report?period=all", token)
        assert status == 200

        categories = [i['category'] for i in data['ai_insights']]
        assert 'billing' in categories
        severities = [i['severity'] for i in data['ai_insights']]
        assert all(s in ('critical', 'warning', 'info', 'positive') for s in severities)
    finally:
        srv.stop()
