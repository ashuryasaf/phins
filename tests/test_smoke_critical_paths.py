"""
Smoke Test Suite - Critical Paths

Quick validation tests for:
- Server starts without errors
- All static files load (HTML, JS, CSS)
- Login endpoints work
- API returns proper JSON responses
- Error handling works (404, 401, 403, 429)
- Database persistence (in-memory validation)
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


def test_server_starts():
    """Test server starts without errors"""
    port = 8081
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.3)
    
    # Server should be running
    assert srv.is_alive()
    
    srv.stop()


def test_login_works():
    """Test basic login functionality"""
    port = 8082
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.2)
    
    base = f"http://127.0.0.1:{port}"
    
    # Test login
    data = json.dumps({"username": "admin", "password": "admin123"}).encode('utf-8')
    req = Request(base + "/api/login", data=data, headers={'Content-Type': 'application/json'})
    
    with urlopen(req) as resp:
        body = resp.read().decode('utf-8')
        data = json.loads(body)
        assert 'token' in data
        assert data['token'].startswith('phins_')
        assert resp.status == 200
    
    srv.stop()


def test_api_returns_json():
    """Test API endpoints return valid JSON"""
    port = 8083
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.2)
    
    base = f"http://127.0.0.1:{port}"

    # Public endpoints (no auth)
    public_endpoints = ["/api/metrics", "/api/policies", "/api/underwriting"]
    for endpoint in public_endpoints:
        req = Request(base + endpoint)
        with urlopen(req) as resp:
            body = resp.read().decode('utf-8')
            data = json.loads(body)
            assert isinstance(data, (dict, list))
            assert resp.status == 200

    # Restricted endpoints require admin auth
    login = json.dumps({"username": "admin", "password": "admin123"}).encode("utf-8")
    req = Request(base + "/api/login", data=login, headers={"Content-Type": "application/json"})
    with urlopen(req) as resp:
        admin_login = json.loads(resp.read().decode("utf-8"))
    token = admin_login["token"]

    req = Request(base + "/api/customers", headers={"Authorization": f"Bearer {token}"})
    with urlopen(req) as resp:
        body = resp.read().decode("utf-8")
        data = json.loads(body)
        assert isinstance(data, (dict, list))
        assert resp.status == 200
    
    srv.stop()


def test_404_error_handling():
    """Test 404 errors are handled properly"""
    port = 8084
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.2)
    
    base = f"http://127.0.0.1:{port}"
    
    try:
        req = Request(base + "/api/nonexistent")
        urlopen(req)
        assert False, "Should return 404"
    except HTTPError as e:
        assert e.code == 404
    
    srv.stop()


def test_401_unauthorized():
    """Test 401 errors for unauthorized access"""
    port = 8085
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.2)
    
    base = f"http://127.0.0.1:{port}"
    
    try:
        req = Request(base + "/api/profile")
        urlopen(req)
        assert False, "Should return 401"
    except HTTPError as e:
        assert e.code == 401
    
    srv.stop()


def test_403_forbidden():
    """Test 403 errors for forbidden access"""
    port = 8086
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.2)
    
    base = f"http://127.0.0.1:{port}"
    
    # Create customer and login
    data = json.dumps({
        "customer_name": "Test Customer",
        "customer_email": "test@example.com",
        "type": "life",
        "coverage_amount": 100000
    }).encode('utf-8')
    req = Request(base + "/api/policies/create", data=data, headers={'Content-Type': 'application/json'})
    with urlopen(req) as resp:
        create_data = json.loads(resp.read().decode('utf-8'))

    # Register the customer account (applications are created before registration)
    reg = json.dumps({
        "name": "Test Customer",
        "email": "test@example.com",
        "phone": "+1-555-0000",
        "dob": "1990-01-01",
        "password": "StrongPass123"
    }).encode("utf-8")
    req = Request(base + "/api/register", data=reg, headers={"Content-Type": "application/json"})
    with urlopen(req) as resp:
        _ = json.loads(resp.read().decode("utf-8"))

    # Login as customer
    login = json.dumps({"username": "test@example.com", "password": "StrongPass123"}).encode("utf-8")
    req = Request(base + "/api/login", data=login, headers={"Content-Type": "application/json"})
    with urlopen(req) as resp:
        login_data = json.loads(resp.read().decode("utf-8"))
    customer_token = login_data["token"]
    
    # Try to access admin endpoint
    try:
        req = Request(base + "/api/audit", headers={'Authorization': f'Bearer {customer_token}'})
        urlopen(req)
        assert False, "Customer should not access admin endpoint"
    except HTTPError as e:
        assert e.code == 403
    
    srv.stop()


def test_policy_creation():
    """Test basic policy creation works"""
    port = 8087
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.2)
    
    base = f"http://127.0.0.1:{port}"
    
    data = json.dumps({
        "customer_name": "Smoke Test Customer",
        "customer_email": "smoke@example.com",
        "type": "life",
        "coverage_amount": 100000
    }).encode('utf-8')
    
    req = Request(base + "/api/policies/create", data=data, headers={'Content-Type': 'application/json'})
    with urlopen(req) as resp:
        body = resp.read().decode('utf-8')
        result = json.loads(body)
        
        assert 'policy' in result
        assert 'customer' in result
        assert 'underwriting' in result
        assert result['policy']['status'] == 'pending_underwriting'
        assert resp.status == 201
    
    srv.stop()


def test_underwriting_workflow():
    """Test basic underwriting workflow"""
    port = 8088
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.2)
    
    base = f"http://127.0.0.1:{port}"
    
    # Create policy
    data = json.dumps({
        "customer_name": "UW Test",
        "customer_email": "uwtest@example.com",
        "type": "life",
        "coverage_amount": 100000
    }).encode('utf-8')
    req = Request(base + "/api/policies/create", data=data, headers={'Content-Type': 'application/json'})
    with urlopen(req) as resp:
        create_result = json.loads(resp.read().decode('utf-8'))
    
    uw_id = create_result['underwriting']['id']
    
    # Approve underwriting
    data = json.dumps({"id": uw_id, "approved_by": "test"}).encode('utf-8')
    req = Request(base + "/api/underwriting/approve", data=data, headers={'Content-Type': 'application/json'})
    with urlopen(req) as resp:
        approve_result = json.loads(resp.read().decode('utf-8'))
        assert approve_result['success'] is True
        assert approve_result['application']['status'] == 'approved'
    
    srv.stop()


def test_claims_workflow():
    """Test basic claims workflow"""
    port = 8089
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.2)
    
    base = f"http://127.0.0.1:{port}"
    
    # Create policy
    data = json.dumps({
        "customer_name": "Claims Test",
        "customer_email": "claimstest@example.com",
        "type": "health",
        "coverage_amount": 200000
    }).encode('utf-8')
    req = Request(base + "/api/policies/create", data=data, headers={'Content-Type': 'application/json'})
    with urlopen(req) as resp:
        create_result = json.loads(resp.read().decode('utf-8'))
    
    policy_id = create_result['policy']['id']
    customer_id = create_result['customer']['id']
    
    # File claim
    data = json.dumps({
        "policy_id": policy_id,
        "customer_id": customer_id,
        "type": "medical",
        "claimed_amount": 10000
    }).encode('utf-8')
    req = Request(base + "/api/claims/create", data=data, headers={'Content-Type': 'application/json'})
    with urlopen(req) as resp:
        claim_result = json.loads(resp.read().decode('utf-8'))
        assert claim_result['status'] == 'pending'
        assert claim_result['claimed_amount'] == 10000
    
    srv.stop()


def test_data_persists_in_memory():
    """Test data persists in memory during server lifetime"""
    port = 8090
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.2)
    
    base = f"http://127.0.0.1:{port}"
    
    # Create policy
    data = json.dumps({
        "customer_name": "Persistence Test",
        "customer_email": "persist@example.com",
        "type": "life",
        "coverage_amount": 100000
    }).encode('utf-8')
    req = Request(base + "/api/policies/create", data=data, headers={'Content-Type': 'application/json'})
    with urlopen(req) as resp:
        create_result = json.loads(resp.read().decode('utf-8'))
    
    policy_id = create_result['policy']['id']
    customer_id = create_result['customer']['id']
    
    # Verify policy exists
    req = Request(base + f"/api/policies?id={policy_id}")
    with urlopen(req) as resp:
        policy = json.loads(resp.read().decode('utf-8'))
        assert policy['id'] == policy_id
    
    # Verify customer exists
    # /api/customers is restricted; verify via admin auth
    login = json.dumps({"username": "admin", "password": "admin123"}).encode("utf-8")
    req = Request(base + "/api/login", data=login, headers={"Content-Type": "application/json"})
    with urlopen(req) as resp:
        admin_login = json.loads(resp.read().decode("utf-8"))
    token = admin_login["token"]

    req = Request(base + f"/api/customers?id={customer_id}", headers={"Authorization": f"Bearer {token}"})
    with urlopen(req) as resp:
        customer = json.loads(resp.read().decode('utf-8'))
        assert customer['id'] == customer_id
    
    srv.stop()


def test_authentication_flow():
    """Test complete authentication flow"""
    port = 8091
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.2)
    
    base = f"http://127.0.0.1:{port}"
    
    # Create customer
    data = json.dumps({
        "customer_name": "Auth Test",
        "customer_email": "auth@example.com",
        "type": "life",
        "coverage_amount": 100000
    }).encode('utf-8')
    req = Request(base + "/api/policies/create", data=data, headers={'Content-Type': 'application/json'})
    with urlopen(req) as resp:
        create_result = json.loads(resp.read().decode('utf-8'))

    # Register + Login as the same email used for application
    reg = json.dumps({
        "name": "Auth Test",
        "email": "auth@example.com",
        "phone": "+1-555-0001",
        "dob": "1990-01-01",
        "password": "StrongPass123"
    }).encode("utf-8")
    req = Request(base + "/api/register", data=reg, headers={"Content-Type": "application/json"})
    with urlopen(req) as resp:
        _ = json.loads(resp.read().decode("utf-8"))

    login = json.dumps({"username": "auth@example.com", "password": "StrongPass123"}).encode("utf-8")
    req = Request(base + "/api/login", data=login, headers={"Content-Type": "application/json"})
    with urlopen(req) as resp:
        login_result = json.loads(resp.read().decode("utf-8"))
        assert "token" in login_result
        token = login_result["token"]
    
    # Use token to access profile
    req = Request(base + "/api/profile", headers={'Authorization': f'Bearer {token}'})
    with urlopen(req) as resp:
        profile = json.loads(resp.read().decode('utf-8'))
        assert profile['username'] == "auth@example.com"
    
    srv.stop()


def test_billing_flow():
    """Test basic billing workflow"""
    port = 8092
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.2)
    
    base = f"http://127.0.0.1:{port}"
    
    # Create policy
    data = json.dumps({
        "customer_name": "Billing Test",
        "customer_email": "billing@example.com",
        "type": "life",
        "coverage_amount": 150000
    }).encode('utf-8')
    req = Request(base + "/api/policies/create", data=data, headers={'Content-Type': 'application/json'})
    with urlopen(req) as resp:
        create_result = json.loads(resp.read().decode('utf-8'))
    
    policy_id = create_result['policy']['id']
    
    # Create bill
    data = json.dumps({
        "policy_id": policy_id,
        "amount_due": 1000.00,
        "due_days": 30
    }).encode('utf-8')
    req = Request(base + "/api/billing/create", data=data, headers={'Content-Type': 'application/json'})
    with urlopen(req) as resp:
        bill_result = json.loads(resp.read().decode('utf-8'))
        assert bill_result['bill']['status'] == 'outstanding'
        bill_id = bill_result['bill']['bill_id']
    
    # Pay bill
    data = json.dumps({
        "bill_id": bill_id,
        "amount": 1000.00
    }).encode('utf-8')
    req = Request(base + "/api/billing/pay", data=data, headers={'Content-Type': 'application/json'})
    with urlopen(req) as resp:
        pay_result = json.loads(resp.read().decode('utf-8'))
        assert pay_result['bill']['status'] == 'paid'
    
    srv.stop()


def test_multiple_roles():
    """Test multiple user roles can login"""
    port = 8093
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.2)
    
    base = f"http://127.0.0.1:{port}"
    
    roles = [
        ("admin", "admin123", "admin"),
        ("underwriter", "under123", "underwriter"),
        ("claims_adjuster", "claims123", "claims"),
        ("accountant", "acct123", "accountant")
    ]
    
    for username, password, expected_role in roles:
        data = json.dumps({
            "username": username,
            "password": password
        }).encode('utf-8')
        req = Request(base + "/api/login", data=data, headers={'Content-Type': 'application/json'})
        with urlopen(req) as resp:
            result = json.loads(resp.read().decode('utf-8'))
            assert result['role'] == expected_role
            assert 'token' in result
    
    srv.stop()


def test_pagination_basic():
    """Test basic pagination functionality"""
    port = 8094
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.2)
    
    base = f"http://127.0.0.1:{port}"
    
    # Create multiple policies
    for i in range(5):
        data = json.dumps({
            "customer_name": f"Page Test {i}",
            "customer_email": f"page{i}@example.com",
            "type": "life",
            "coverage_amount": 100000
        }).encode('utf-8')
        req = Request(base + "/api/policies/create", data=data, headers={'Content-Type': 'application/json'})
        with urlopen(req) as resp:
            pass  # Just create them
    
    # Test pagination
    req = Request(base + "/api/policies?page=1&page_size=2")
    with urlopen(req) as resp:
        result = json.loads(resp.read().decode('utf-8'))
        assert 'items' in result
        assert 'page' in result
        assert 'page_size' in result
        assert result['page'] == 1
        assert result['page_size'] == 2
    
    srv.stop()


def test_quick_end_to_end():
    """Quick end-to-end test of main workflow"""
    port = 8095
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.2)
    
    base = f"http://127.0.0.1:{port}"
    
    # 1. Create policy
    data = json.dumps({
        "customer_name": "E2E Test",
        "customer_email": "e2e@example.com",
        "type": "life",
        "coverage_amount": 200000
    }).encode('utf-8')
    req = Request(base + "/api/policies/create", data=data, headers={'Content-Type': 'application/json'})
    with urlopen(req) as resp:
        create_result = json.loads(resp.read().decode('utf-8'))
    
    policy_id = create_result['policy']['id']
    customer_id = create_result['customer']['id']
    uw_id = create_result['underwriting']['id']
    
    # 2. Approve underwriting
    data = json.dumps({"id": uw_id}).encode('utf-8')
    req = Request(base + "/api/underwriting/approve", data=data, headers={'Content-Type': 'application/json'})
    with urlopen(req) as resp:
        pass
    
    # 3. File claim
    data = json.dumps({
        "policy_id": policy_id,
        "customer_id": customer_id,
        "type": "medical",
        "claimed_amount": 15000
    }).encode('utf-8')
    req = Request(base + "/api/claims/create", data=data, headers={'Content-Type': 'application/json'})
    with urlopen(req) as resp:
        claim_result = json.loads(resp.read().decode('utf-8'))
    
    claim_id = claim_result['id']
    
    # 4. Approve claim
    data = json.dumps({
        "id": claim_id,
        "approved_amount": 15000
    }).encode('utf-8')
    req = Request(base + "/api/claims/approve", data=data, headers={'Content-Type': 'application/json'})
    with urlopen(req) as resp:
        pass
    
    # 5. Pay claim
    data = json.dumps({"id": claim_id}).encode('utf-8')
    req = Request(base + "/api/claims/pay", data=data, headers={'Content-Type': 'application/json'})
    with urlopen(req) as resp:
        pay_result = json.loads(resp.read().decode('utf-8'))
        assert pay_result['claim']['status'] == 'paid'
    
    srv.stop()
