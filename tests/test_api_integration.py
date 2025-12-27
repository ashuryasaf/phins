"""
API Integration Test Suite

Tests every API endpoint for correctness and proper behavior:
- Authentication endpoints (login, register, profile)
- Policy management (create, list, get)
- Underwriting (approve, reject, list)
- Claims (create, approve, reject, pay)
- Billing (create, pay)
- Customer management
- Business Intelligence
- Admin/Security endpoints
"""

import threading
import time
import json
from http.server import HTTPServer
from urllib.request import urlopen, Request
from urllib.error import HTTPError

import web_portal.server as portal


class ServerThread(threading.Thread):
    """Thread to run the HTTP server in background"""
    def __init__(self, port):
        super().__init__(daemon=True)
        self.port = port
        self.httpd = HTTPServer(('127.0.0.1', port), portal.PortalHandler)

    def run(self):
        self.httpd.serve_forever()

    def stop(self):
        self.httpd.shutdown()


def _get(url, token=None):
    """HTTP GET request"""
    headers = {}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    req = Request(url, headers=headers)
    try:
        with urlopen(req) as resp:
            return resp.read().decode('utf-8'), resp.status
    except HTTPError as e:
        return e.read().decode('utf-8'), e.code


def _post(url, payload, token=None):
    """HTTP POST request"""
    data = json.dumps(payload).encode('utf-8')
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    req = Request(url, data=data, headers=headers)
    try:
        with urlopen(req) as resp:
            return resp.read().decode('utf-8'), resp.status
    except HTTPError as e:
        return e.read().decode('utf-8'), e.code


def test_login_endpoint():
    """Test POST /api/login"""
    port = 8031
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.2)
    
    base = f"http://127.0.0.1:{port}"
    
    # Test admin login
    body, status = _post(base + "/api/login", {
        "username": "admin",
        "password": "admin123"
    })
    assert status == 200
    data = json.loads(body)
    assert 'token' in data
    assert data['token'].startswith('phins_')
    assert data['role'] == 'admin'
    assert data['username'] == 'admin'
    
    # Test underwriter login
    body, status = _post(base + "/api/login", {
        "username": "underwriter",
        "password": "under123"
    })
    assert status == 200
    data = json.loads(body)
    assert data['role'] == 'underwriter'
    
    # Test claims adjuster login
    body, status = _post(base + "/api/login", {
        "username": "claims_adjuster",
        "password": "claims123"
    })
    assert status == 200
    data = json.loads(body)
    assert data['role'] == 'claims'
    
    # Test accountant login
    body, status = _post(base + "/api/login", {
        "username": "accountant",
        "password": "acct123"
    })
    assert status == 200
    data = json.loads(body)
    assert data['role'] == 'accountant'
    
    # Test invalid credentials
    _, status = _post(base + "/api/login", {
        "username": "admin",
        "password": "wrongpassword"
    })
    assert status == 401
    
    srv.stop()


def test_register_endpoint():
    """Test POST /api/register"""
    port = 8032
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.2)
    
    base = f"http://127.0.0.1:{port}"
    
    # Test successful registration
    body, status = _post(base + "/api/register", {
        "name": "New Customer",
        "email": "newcustomer@example.com",
        "password": "secure123456",
        "phone": "555-9999",
        "dob": "1990-01-01"
    })
    assert status == 201
    data = json.loads(body)
    assert data['success'] is True
    assert 'customer_id' in data
    assert data['email'] == "newcustomer@example.com"
    
    # Test duplicate registration
    _, status = _post(base + "/api/register", {
        "name": "New Customer 2",
        "email": "newcustomer@example.com",
        "password": "secure123456",
        "phone": "555-8888"
    })
    assert status == 409
    
    # Test missing required fields
    _, status = _post(base + "/api/register", {
        "name": "Incomplete User"
    })
    assert status == 400
    
    srv.stop()


def test_profile_endpoint():
    """Test GET /api/profile"""
    port = 8033
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.2)
    
    base = f"http://127.0.0.1:{port}"
    
    # Login first
    login_body, _ = _post(base + "/api/login", {
        "username": "admin",
        "password": "admin123"
    })
    token = json.loads(login_body)['token']
    
    # Get profile
    body, status = _get(base + "/api/profile", token)
    assert status == 200
    data = json.loads(body)
    assert data['username'] == 'admin'
    assert data['role'] == 'admin'
    assert data['name'] == 'Admin User'
    
    # Test unauthorized access
    _, status = _get(base + "/api/profile")
    assert status == 401
    
    srv.stop()


def test_policies_create_endpoint():
    """Test POST /api/policies/create"""
    port = 8034
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.2)
    
    base = f"http://127.0.0.1:{port}"
    
    # Test successful policy creation
    body, status = _post(base + "/api/policies/create", {
        "customer_name": "Test Policy Customer",
        "customer_email": "policy@example.com",
        "customer_phone": "555-1111",
        "type": "life",
        "coverage_amount": 250000,
        "risk_score": "low",
        "age": 30
    })
    assert status == 201
    data = json.loads(body)
    assert 'policy' in data
    assert 'customer' in data
    assert 'underwriting' in data
    assert 'provisioned_login' in data
    assert data['policy']['status'] == 'pending_underwriting'
    assert data['policy']['coverage_amount'] == 250000
    
    # Test missing customer name
    _, status = _post(base + "/api/policies/create", {
        "customer_email": "test2@example.com",
        "type": "health",
        "coverage_amount": 100000
    })
    assert status == 400
    
    # Test invalid coverage amount
    _, status = _post(base + "/api/policies/create", {
        "customer_name": "Test",
        "customer_email": "test3@example.com",
        "coverage_amount": 999999999999  # Too large
    })
    assert status == 400
    
    srv.stop()


def test_policies_list_endpoint():
    """Test GET /api/policies with pagination"""
    port = 8035
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.2)
    
    base = f"http://127.0.0.1:{port}"
    
    # Create some policies first
    for i in range(5):
        _post(base + "/api/policies/create", {
            "customer_name": f"List Test {i}",
            "customer_email": f"list{i}@example.com",
            "type": "life",
            "coverage_amount": 100000
        })
    
    # Test listing all policies
    body, status = _get(base + "/api/policies")
    assert status == 200
    data = json.loads(body)
    assert 'items' in data
    assert 'page' in data
    assert 'page_size' in data
    assert 'total' in data
    assert len(data['items']) >= 5
    
    # Test pagination
    body, status = _get(base + "/api/policies?page=1&page_size=2")
    assert status == 200
    data = json.loads(body)
    assert len(data['items']) == 2
    assert data['page'] == 1
    assert data['page_size'] == 2
    
    srv.stop()


def test_policies_get_by_id_endpoint():
    """Test GET /api/policies?id={id}"""
    port = 8036
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.2)
    
    base = f"http://127.0.0.1:{port}"
    
    # Create a policy
    body, _ = _post(base + "/api/policies/create", {
        "customer_name": "Get Test",
        "customer_email": "get@example.com",
        "type": "auto",
        "coverage_amount": 50000
    })
    policy_id = json.loads(body)['policy']['id']
    
    # Get specific policy
    body, status = _get(base + f"/api/policies?id={policy_id}")
    assert status == 200
    data = json.loads(body)
    assert data['id'] == policy_id
    assert data['type'] == 'auto'
    assert data['coverage_amount'] == 50000
    
    # Test non-existent policy
    body, status = _get(base + "/api/policies?id=NONEXISTENT")
    assert status == 404
    
    srv.stop()


def test_underwriting_list_endpoint():
    """Test GET /api/underwriting"""
    port = 8037
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.2)
    
    base = f"http://127.0.0.1:{port}"
    
    # Create policies with underwriting apps
    for i in range(3):
        _post(base + "/api/policies/create", {
            "customer_name": f"UW Test {i}",
            "customer_email": f"uw{i}@example.com",
            "type": "life",
            "coverage_amount": 100000,
            "risk_score": ["low", "medium", "high"][i]
        })
    
    # List all underwriting applications
    body, status = _get(base + "/api/underwriting")
    assert status == 200
    data = json.loads(body)
    assert isinstance(data, list)
    assert len(data) >= 3
    
    srv.stop()


def test_underwriting_approve_endpoint():
    """Test POST /api/underwriting/approve"""
    port = 8038
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.2)
    
    base = f"http://127.0.0.1:{port}"
    
    # Create policy
    body, _ = _post(base + "/api/policies/create", {
        "customer_name": "Approve Test",
        "customer_email": "approve@example.com",
        "type": "life",
        "coverage_amount": 200000
    })
    uw_id = json.loads(body)['underwriting']['id']
    policy_id = json.loads(body)['policy']['id']
    
    # Approve underwriting
    body, status = _post(base + "/api/underwriting/approve", {
        "id": uw_id,
        "approved_by": "test_underwriter"
    })
    assert status == 200
    data = json.loads(body)
    assert data['success'] is True
    assert data['application']['status'] == 'approved'
    
    # Verify policy status changed
    body, _ = _get(base + f"/api/policies?id={policy_id}")
    policy = json.loads(body)
    assert policy['status'] == 'active'
    
    srv.stop()


def test_underwriting_reject_endpoint():
    """Test POST /api/underwriting/reject"""
    port = 8039
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.2)
    
    base = f"http://127.0.0.1:{port}"
    
    # Create policy
    body, _ = _post(base + "/api/policies/create", {
        "customer_name": "Reject Test",
        "customer_email": "reject@example.com",
        "type": "life",
        "coverage_amount": 150000,
        "risk_score": "very_high"
    })
    uw_id = json.loads(body)['underwriting']['id']
    policy_id = json.loads(body)['policy']['id']
    
    # Reject underwriting
    body, status = _post(base + "/api/underwriting/reject", {
        "id": uw_id,
        "reason": "High risk factors",
        "rejected_by": "test_underwriter"
    })
    assert status == 200
    data = json.loads(body)
    assert data['success'] is True
    assert data['application']['status'] == 'rejected'
    assert 'rejection_reason' in data['application']
    
    # Verify policy status changed
    body, _ = _get(base + f"/api/policies?id={policy_id}")
    policy = json.loads(body)
    assert policy['status'] == 'rejected'
    
    srv.stop()


def test_claims_create_endpoint():
    """Test POST /api/claims/create"""
    port = 8040
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.2)
    
    base = f"http://127.0.0.1:{port}"
    
    # Create and approve policy first
    body, _ = _post(base + "/api/policies/create", {
        "customer_name": "Claims Test",
        "customer_email": "claims@example.com",
        "type": "health",
        "coverage_amount": 300000
    })
    policy_id = json.loads(body)['policy']['id']
    customer_id = json.loads(body)['customer']['id']
    uw_id = json.loads(body)['underwriting']['id']
    
    _post(base + "/api/underwriting/approve", {"id": uw_id})
    
    # Create claim
    body, status = _post(base + "/api/claims/create", {
        "policy_id": policy_id,
        "customer_id": customer_id,
        "type": "medical",
        "description": "Hospital visit",
        "claimed_amount": 25000
    })
    assert status == 201
    data = json.loads(body)
    assert data['status'] == 'pending'
    assert data['claimed_amount'] == 25000
    assert data['policy_id'] == policy_id
    
    srv.stop()


def test_claims_list_endpoint():
    """Test GET /api/claims with status filter"""
    port = 8041
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.2)
    
    base = f"http://127.0.0.1:{port}"
    
    # Create policy and claims
    body, _ = _post(base + "/api/policies/create", {
        "customer_name": "Claims List Test",
        "customer_email": "claimslist@example.com",
        "type": "health",
        "coverage_amount": 200000
    })
    policy_id = json.loads(body)['policy']['id']
    customer_id = json.loads(body)['customer']['id']
    
    for i in range(3):
        _post(base + "/api/claims/create", {
            "policy_id": policy_id,
            "customer_id": customer_id,
            "type": "medical",
            "description": f"Claim {i}",
            "claimed_amount": 10000 * (i + 1)
        })
    
    # List all claims
    body, status = _get(base + "/api/claims")
    assert status == 200
    data = json.loads(body)
    assert 'items' in data
    assert len(data['items']) >= 3
    
    # List pending claims only
    body, status = _get(base + "/api/claims?status=pending")
    assert status == 200
    data = json.loads(body)
    all_pending = all(c['status'] == 'pending' for c in data['items'])
    assert all_pending
    
    srv.stop()


def test_claims_approve_endpoint():
    """Test POST /api/claims/approve"""
    port = 8042
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.2)
    
    base = f"http://127.0.0.1:{port}"
    
    # Create policy and claim
    body, _ = _post(base + "/api/policies/create", {
        "customer_name": "Claim Approve Test",
        "customer_email": "claimapprove@example.com",
        "type": "health",
        "coverage_amount": 200000
    })
    policy_id = json.loads(body)['policy']['id']
    customer_id = json.loads(body)['customer']['id']
    
    body, _ = _post(base + "/api/claims/create", {
        "policy_id": policy_id,
        "customer_id": customer_id,
        "type": "medical",
        "claimed_amount": 30000
    })
    claim_id = json.loads(body)['id']
    
    # Approve claim
    body, status = _post(base + "/api/claims/approve", {
        "id": claim_id,
        "approved_amount": 28000,
        "approved_by": "test_adjuster",
        "notes": "Approved with deductible"
    })
    assert status == 200
    data = json.loads(body)
    assert data['success'] is True
    assert data['claim']['status'] == 'approved'
    assert data['claim']['approved_amount'] == 28000
    
    srv.stop()


def test_claims_reject_endpoint():
    """Test POST /api/claims/reject"""
    port = 8043
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.2)
    
    base = f"http://127.0.0.1:{port}"
    
    # Create policy and claim
    body, _ = _post(base + "/api/policies/create", {
        "customer_name": "Claim Reject Test",
        "customer_email": "claimreject@example.com",
        "type": "auto",
        "coverage_amount": 50000
    })
    policy_id = json.loads(body)['policy']['id']
    customer_id = json.loads(body)['customer']['id']
    
    body, _ = _post(base + "/api/claims/create", {
        "policy_id": policy_id,
        "customer_id": customer_id,
        "type": "accident",
        "claimed_amount": 15000
    })
    claim_id = json.loads(body)['id']
    
    # Reject claim
    body, status = _post(base + "/api/claims/reject", {
        "id": claim_id,
        "reason": "Not covered under policy",
        "rejected_by": "test_adjuster"
    })
    assert status == 200
    data = json.loads(body)
    assert data['success'] is True
    assert data['claim']['status'] == 'rejected'
    assert 'rejection_reason' in data['claim']
    
    srv.stop()


def test_claims_pay_endpoint():
    """Test POST /api/claims/pay"""
    port = 8044
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.2)
    
    base = f"http://127.0.0.1:{port}"
    
    # Create, approve and pay claim
    body, _ = _post(base + "/api/policies/create", {
        "customer_name": "Claim Pay Test",
        "customer_email": "claimpay@example.com",
        "type": "health",
        "coverage_amount": 200000
    })
    policy_id = json.loads(body)['policy']['id']
    customer_id = json.loads(body)['customer']['id']
    
    body, _ = _post(base + "/api/claims/create", {
        "policy_id": policy_id,
        "customer_id": customer_id,
        "type": "medical",
        "claimed_amount": 20000
    })
    claim_id = json.loads(body)['id']
    
    # Must approve first
    _post(base + "/api/claims/approve", {
        "id": claim_id,
        "approved_amount": 20000
    })
    
    # Pay claim
    body, status = _post(base + "/api/claims/pay", {
        "id": claim_id,
        "payment_method": "bank_transfer",
        "processed_by": "test_accountant"
    })
    assert status == 200
    data = json.loads(body)
    assert data['success'] is True
    assert data['claim']['status'] == 'paid'
    assert 'payment_reference' in data['claim']
    assert data['claim']['paid_amount'] == 20000
    
    srv.stop()


def test_billing_create_endpoint():
    """Test POST /api/billing/create"""
    port = 8045
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.2)
    
    base = f"http://127.0.0.1:{port}"
    
    # Create policy first
    body, _ = _post(base + "/api/policies/create", {
        "customer_name": "Billing Test",
        "customer_email": "billing@example.com",
        "type": "life",
        "coverage_amount": 200000
    })
    policy_id = json.loads(body)['policy']['id']
    
    # Create bill
    body, status = _post(base + "/api/billing/create", {
        "policy_id": policy_id,
        "amount_due": 1500.00,
        "due_days": 30
    })
    assert status == 201
    data = json.loads(body)
    assert 'bill' in data
    assert data['bill']['status'] == 'outstanding'
    assert data['bill']['amount_due'] == 1500.00
    assert data['bill']['amount_paid'] == 0.0
    
    srv.stop()


def test_billing_pay_endpoint():
    """Test POST /api/billing/pay"""
    port = 8046
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.2)
    
    base = f"http://127.0.0.1:{port}"
    
    # Create policy and bill
    body, _ = _post(base + "/api/policies/create", {
        "customer_name": "Bill Pay Test",
        "customer_email": "billpay@example.com",
        "type": "life",
        "coverage_amount": 150000
    })
    policy_id = json.loads(body)['policy']['id']
    
    body, _ = _post(base + "/api/billing/create", {
        "policy_id": policy_id,
        "amount_due": 1200.00,
        "due_days": 30
    })
    bill_id = json.loads(body)['bill']['bill_id']
    
    # Pay partial amount
    body, status = _post(base + "/api/billing/pay", {
        "bill_id": bill_id,
        "amount": 600.00
    })
    assert status == 200
    data = json.loads(body)
    assert data['bill']['status'] == 'partial'
    assert data['bill']['amount_paid'] == 600.00
    
    # Pay remaining amount
    body, status = _post(base + "/api/billing/pay", {
        "bill_id": bill_id,
        "amount": 600.00
    })
    assert status == 200
    data = json.loads(body)
    assert data['bill']['status'] == 'paid'
    assert data['bill']['amount_paid'] == 1200.00
    
    srv.stop()


def test_customers_endpoint():
    """Test GET /api/customers"""
    port = 8047
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.2)
    
    base = f"http://127.0.0.1:{port}"
    
    # Create customers
    for i in range(3):
        _post(base + "/api/policies/create", {
            "customer_name": f"Customer {i}",
            "customer_email": f"customer{i}@example.com",
            "type": "life",
            "coverage_amount": 100000
        })
    
    # List all customers
    body, status = _get(base + "/api/customers")
    assert status == 200
    data = json.loads(body)
    assert isinstance(data, list)
    assert len(data) >= 3
    
    srv.stop()


def test_customer_status_endpoint():
    """Test GET /api/customer/status"""
    port = 8048
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.2)
    
    base = f"http://127.0.0.1:{port}"
    
    # Create customer and policy
    body, _ = _post(base + "/api/policies/create", {
        "customer_name": "Status Test",
        "customer_email": "status@example.com",
        "type": "life",
        "coverage_amount": 100000
    })
    customer_id = json.loads(body)['customer']['id']
    
    # Get customer status
    body, status = _get(base + f"/api/customer/status?customer_id={customer_id}")
    assert status == 200
    data = json.loads(body)
    assert 'customer' in data
    assert 'overall_status' in data
    assert 'policies' in data
    assert 'underwriting_applications' in data
    assert data['customer']['id'] == customer_id
    
    srv.stop()


def test_metrics_endpoint():
    """Test GET /api/metrics"""
    port = 8049
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.2)
    
    base = f"http://127.0.0.1:{port}"
    
    # Get metrics
    body, status = _get(base + "/api/metrics")
    assert status == 200
    data = json.loads(body)
    assert 'metrics' in data
    assert 'ts' in data
    
    srv.stop()


def test_audit_endpoint():
    """Test GET /api/audit (admin only)"""
    port = 8050
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.2)
    
    base = f"http://127.0.0.1:{port}"
    
    # Login as admin
    body, _ = _post(base + "/api/login", {
        "username": "admin",
        "password": "admin123"
    })
    admin_token = json.loads(body)['token']
    
    # Get audit logs
    body, status = _get(base + "/api/audit?page=1&page_size=10", admin_token)
    assert status == 200
    data = json.loads(body)
    assert 'items' in data
    assert 'page' in data
    assert 'page_size' in data
    assert 'total' in data
    
    # Test unauthorized access
    _, status = _get(base + "/api/audit")
    assert status == 401
    
    srv.stop()


def test_security_threats_endpoint():
    """Test GET /api/security/threats (admin only)"""
    port = 8051
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.2)
    
    base = f"http://127.0.0.1:{port}"
    
    # Login as admin
    body, _ = _post(base + "/api/login", {
        "username": "admin",
        "password": "admin123"
    })
    admin_token = json.loads(body)['token']
    
    # Get security threats
    body, status = _get(base + "/api/security/threats", admin_token)
    assert status == 200
    data = json.loads(body)
    assert 'malicious_attempts' in data
    assert 'blocked_ips' in data
    assert 'failed_logins' in data
    assert 'statistics' in data
    
    srv.stop()


def test_bi_actuary_endpoint():
    """Test GET /api/bi/actuary"""
    port = 8052
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.2)
    
    base = f"http://127.0.0.1:{port}"
    
    # Login as admin
    body, _ = _post(base + "/api/login", {
        "username": "admin",
        "password": "admin123"
    })
    admin_token = json.loads(body)['token']
    
    # Get actuarial BI data
    body, status = _get(base + "/api/bi/actuary", admin_token)
    assert status == 200
    data = json.loads(body)
    assert 'total_policies' in data
    assert 'total_exposure' in data
    assert 'average_premium' in data
    assert 'risk_distribution' in data
    assert 'claims_ratio' in data
    
    srv.stop()


def test_bi_underwriting_endpoint():
    """Test GET /api/bi/underwriting"""
    port = 8053
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.2)
    
    base = f"http://127.0.0.1:{port}"
    
    # Login as underwriter
    body, _ = _post(base + "/api/login", {
        "username": "underwriter",
        "password": "under123"
    })
    uw_token = json.loads(body)['token']
    
    # Get underwriting BI data
    body, status = _get(base + "/api/bi/underwriting", uw_token)
    assert status == 200
    data = json.loads(body)
    assert 'pending_applications' in data
    assert 'approved_this_month' in data
    assert 'rejection_rate' in data
    assert 'risk_assessment_distribution' in data
    
    srv.stop()


def test_bi_accounting_endpoint():
    """Test GET /api/bi/accounting"""
    port = 8054
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.2)
    
    base = f"http://127.0.0.1:{port}"
    
    # Login as accountant
    body, _ = _post(base + "/api/login", {
        "username": "accountant",
        "password": "acct123"
    })
    acct_token = json.loads(body)['token']
    
    # Get accounting BI data
    body, status = _get(base + "/api/bi/accounting", acct_token)
    assert status == 200
    data = json.loads(body)
    assert 'total_revenue' in data
    assert 'total_claims_paid' in data
    assert 'net_income' in data
    assert 'profit_margin' in data
    assert 'monthly_breakdown' in data
    
    srv.stop()
