"""
Data Persistence Validation Test Suite

Ensures data survives and persists correctly:
- Policy creation persists in POLICIES dict
- Customer data persists in CUSTOMERS dict
- Claims persist in CLAIMS dict
- Underwriting apps persist in UNDERWRITING_APPLICATIONS dict
- Sessions persist in SESSIONS dict
- Billing records persist in BILLING dict
"""

import threading
import time
import json
from http.server import HTTPServer
from urllib.request import urlopen, Request

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


def _post(url, payload):
    """HTTP POST request"""
    data = json.dumps(payload).encode('utf-8')
    req = Request(url, data=data, headers={'Content-Type': 'application/json'})
    with urlopen(req) as resp:
        return resp.read().decode('utf-8')


def _get(url, token=None):
    """HTTP GET request"""
    headers = {}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    req = Request(url, headers=headers)
    with urlopen(req) as resp:
        return resp.read().decode('utf-8')


def test_policy_persistence():
    """Test policies persist in POLICIES dict"""
    port = 8101
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.2)
    
    base = f"http://127.0.0.1:{port}"
    
    # Create multiple policies
    policy_ids = []
    for i in range(5):
        body = _post(base + "/api/policies/create", {
            "customer_name": f"Persistence Test {i}",
            "customer_email": f"persist{i}@example.com",
            "type": "life",
            "coverage_amount": 100000 + (i * 10000)
        })
        result = json.loads(body)
        policy_ids.append(result['policy']['id'])
    
    # Verify all policies exist in memory
    assert len(portal.POLICIES) >= 5
    
    # Verify each policy can be retrieved
    for policy_id in policy_ids:
        body = _get(base + f"/api/policies?id={policy_id}")
        policy = json.loads(body)
        assert policy['id'] == policy_id
        assert policy['id'] in portal.POLICIES
    
    # Verify policies list contains all created policies
    body = _get(base + "/api/policies")
    all_policies = json.loads(body)
    all_policy_ids = {p['id'] for p in all_policies['items']}
    for policy_id in policy_ids:
        assert policy_id in all_policy_ids
    
    srv.stop()


def test_customer_persistence():
    """Test customers persist in CUSTOMERS dict"""
    port = 8102
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.2)
    
    base = f"http://127.0.0.1:{port}"
    
    # Create customers via policy creation
    customer_ids = []
    customer_emails = []
    for i in range(5):
        email = f"custpersist{i}@example.com"
        body = _post(base + "/api/policies/create", {
            "customer_name": f"Customer Persist {i}",
            "customer_email": email,
            "type": "health",
            "coverage_amount": 150000
        })
        result = json.loads(body)
        customer_ids.append(result['customer']['id'])
        customer_emails.append(result['customer']['email'])
    
    # Verify all customers exist in memory
    assert len(portal.CUSTOMERS) >= 5
    
    # Verify each customer can be retrieved
    for customer_id in customer_ids:
        body = _get(base + f"/api/customers?id={customer_id}")
        customer = json.loads(body)
        assert customer['id'] == customer_id
        assert customer_id in portal.CUSTOMERS
    
    # Verify customers list contains all created customers
    body = _get(base + "/api/customers")
    all_customers = json.loads(body)
    all_customer_ids = {c['id'] for c in all_customers}
    for customer_id in customer_ids:
        assert customer_id in all_customer_ids
    
    # Verify customer status endpoint works
    for customer_id in customer_ids:
        body = _get(base + f"/api/customer/status?customer_id={customer_id}")
        status = json.loads(body)
        assert status['customer']['id'] == customer_id
    
    srv.stop()


def test_claims_persistence():
    """Test claims persist in CLAIMS dict"""
    port = 8103
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.2)
    
    base = f"http://127.0.0.1:{port}"
    
    initial_claims_count = len(portal.CLAIMS)
    
    # Create policy first
    body = _post(base + "/api/policies/create", {
        "customer_name": "Claims Persist Test",
        "customer_email": "claimspersist@example.com",
        "type": "health",
        "coverage_amount": 300000
    })
    result = json.loads(body)
    policy_id = result['policy']['id']
    customer_id = result['customer']['id']
    
    # Create multiple claims
    claim_ids = []
    for i in range(5):
        body = _post(base + "/api/claims/create", {
            "policy_id": policy_id,
            "customer_id": customer_id,
            "type": "medical",
            "description": f"Claim {i}",
            "claimed_amount": 5000 + (i * 1000)
        })
        claim = json.loads(body)
        claim_ids.append(claim['id'])
    
    # Verify all claims exist in memory
    assert len(portal.CLAIMS) >= initial_claims_count + 5
    
    # Verify each claim can be retrieved
    for claim_id in claim_ids:
        body = _get(base + f"/api/claims?id={claim_id}")
        claim = json.loads(body)
        assert claim['id'] == claim_id
        assert claim_id in portal.CLAIMS
    
    # Verify claims list contains all created claims
    body = _get(base + "/api/claims")
    all_claims = json.loads(body)
    all_claim_ids = {c['id'] for c in all_claims['items']}
    for claim_id in claim_ids:
        assert claim_id in all_claim_ids
    
    srv.stop()


def test_underwriting_persistence():
    """Test underwriting applications persist in UNDERWRITING_APPLICATIONS dict"""
    port = 8104
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.2)
    
    base = f"http://127.0.0.1:{port}"
    
    # Create multiple policies (each creates an underwriting app)
    uw_ids = []
    for i in range(5):
        body = _post(base + "/api/policies/create", {
            "customer_name": f"UW Persist {i}",
            "customer_email": f"uwpersist{i}@example.com",
            "type": "life",
            "coverage_amount": 200000,
            "risk_score": ["low", "medium", "high", "medium", "low"][i]
        })
        result = json.loads(body)
        uw_ids.append(result['underwriting']['id'])
    
    # Verify all underwriting apps exist in memory
    assert len(portal.UNDERWRITING_APPLICATIONS) >= 5
    
    # Verify each underwriting app can be retrieved
    for uw_id in uw_ids:
        body = _get(base + f"/api/underwriting?id={uw_id}")
        uw_app = json.loads(body)
        assert uw_app['id'] == uw_id
        assert uw_id in portal.UNDERWRITING_APPLICATIONS
    
    # Verify underwriting list contains all created apps
    body = _get(base + "/api/underwriting")
    all_uw_apps = json.loads(body)
    all_uw_ids = {u['id'] for u in all_uw_apps}
    for uw_id in uw_ids:
        assert uw_id in all_uw_ids
    
    # Test status changes persist
    for uw_id in uw_ids[:2]:
        _post(base + "/api/underwriting/approve", {"id": uw_id})
        body = _get(base + f"/api/underwriting?id={uw_id}")
        uw_app = json.loads(body)
        assert uw_app['status'] == 'approved'
    
    srv.stop()


def test_sessions_persistence():
    """Test sessions persist in SESSIONS dict"""
    port = 8105
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.2)
    
    base = f"http://127.0.0.1:{port}"
    
    initial_session_count = len(portal.SESSIONS)
    
    # Create multiple login sessions
    tokens = []
    
    # Admin session
    body = _post(base + "/api/login", {
        "username": "admin",
        "password": "admin123"
    })
    result = json.loads(body)
    tokens.append(result['token'])
    
    # Underwriter session
    body = _post(base + "/api/login", {
        "username": "underwriter",
        "password": "under123"
    })
    result = json.loads(body)
    tokens.append(result['token'])
    
    # Claims adjuster session
    body = _post(base + "/api/login", {
        "username": "claims_adjuster",
        "password": "claims123"
    })
    result = json.loads(body)
    tokens.append(result['token'])
    
    # Verify sessions exist in memory
    assert len(portal.SESSIONS) >= initial_session_count + 3
    
    # Verify each token is valid and can be used
    for token in tokens:
        assert token in portal.SESSIONS
        body = _get(base + "/api/profile", token)
        profile = json.loads(body)
        assert 'username' in profile
    
    # Verify session data structure
    for token in tokens:
        session = portal.SESSIONS[token]
        assert 'username' in session
        assert 'expires' in session
        assert 'role' in session or session['username'] in portal.USERS
    
    srv.stop()


def test_billing_persistence():
    """Test billing records persist in BILLING dict"""
    port = 8106
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.2)
    
    base = f"http://127.0.0.1:{port}"
    
    initial_billing_count = len(portal.BILLING)
    
    # Create policy
    body = _post(base + "/api/policies/create", {
        "customer_name": "Billing Persist Test",
        "customer_email": "billingpersist@example.com",
        "type": "life",
        "coverage_amount": 250000
    })
    result = json.loads(body)
    policy_id = result['policy']['id']
    
    # Create multiple bills
    bill_ids = []
    for i in range(5):
        body = _post(base + "/api/billing/create", {
            "policy_id": policy_id,
            "amount_due": 1000.00 + (i * 100),
            "due_days": 30
        })
        bill = json.loads(body)
        bill_ids.append(bill['bill']['bill_id'])
    
    # Verify all bills exist in memory
    assert len(portal.BILLING) >= initial_billing_count + 5
    
    # Verify each bill exists in BILLING dict
    for bill_id in bill_ids:
        assert bill_id in portal.BILLING
        bill = portal.BILLING[bill_id]
        assert bill['status'] == 'outstanding'
        assert bill['amount_paid'] == 0.0
    
    # Test bill status changes persist
    for i, bill_id in enumerate(bill_ids[:3]):
        bill_amount = portal.BILLING[bill_id]['amount_due']
        payment_amount = bill_amount if i < 2 else bill_amount / 2
        
        _post(base + "/api/billing/pay", {
            "bill_id": bill_id,
            "amount": payment_amount
        })
        
        # Verify payment persisted
        bill = portal.BILLING[bill_id]
        assert bill['amount_paid'] == payment_amount
        if i < 2:
            assert bill['status'] == 'paid'
        else:
            assert bill['status'] == 'partial'
    
    srv.stop()


def test_data_relationships():
    """Test relationships between different data types persist correctly"""
    port = 8107
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.2)
    
    base = f"http://127.0.0.1:{port}"
    
    # Create complete flow: customer -> policy -> underwriting -> claim -> billing
    body = _post(base + "/api/policies/create", {
        "customer_name": "Relationship Test",
        "customer_email": "relationship@example.com",
        "type": "health",
        "coverage_amount": 400000
    })
    result = json.loads(body)
    
    customer_id = result['customer']['id']
    policy_id = result['policy']['id']
    uw_id = result['underwriting']['id']
    
    # Verify relationships
    policy = portal.POLICIES[policy_id]
    assert policy['customer_id'] == customer_id
    assert policy['underwriting_id'] == uw_id
    
    uw_app = portal.UNDERWRITING_APPLICATIONS[uw_id]
    assert uw_app['customer_id'] == customer_id
    assert uw_app['policy_id'] == policy_id
    
    # Create claim
    body = _post(base + "/api/claims/create", {
        "policy_id": policy_id,
        "customer_id": customer_id,
        "type": "medical",
        "claimed_amount": 25000
    })
    claim_result = json.loads(body)
    claim_id = claim_result['id']
    
    # Verify claim relationships
    claim = portal.CLAIMS[claim_id]
    assert claim['customer_id'] == customer_id
    assert claim['policy_id'] == policy_id
    
    # Create billing
    body = _post(base + "/api/billing/create", {
        "policy_id": policy_id,
        "amount_due": 2000.00
    })
    bill_result = json.loads(body)
    bill_id = bill_result['bill']['bill_id']
    
    # Verify billing relationships
    bill = portal.BILLING[bill_id]
    assert bill['policy_id'] == policy_id
    
    # Verify all related data can be retrieved via customer
    body = _get(base + f"/api/customer/status?customer_id={customer_id}")
    status = json.loads(body)
    
    assert status['customer']['id'] == customer_id
    assert any(p['id'] == policy_id for p in status['policies'])
    assert any(u['id'] == uw_id for u in status['underwriting_applications'])
    
    srv.stop()


def test_data_survives_multiple_operations():
    """Test data persists through multiple operations"""
    port = 8108
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.2)
    
    base = f"http://127.0.0.1:{port}"
    
    # Create initial data
    body = _post(base + "/api/policies/create", {
        "customer_name": "Multi Op Test",
        "customer_email": "multiop@example.com",
        "type": "life",
        "coverage_amount": 500000
    })
    result = json.loads(body)
    policy_id = result['policy']['id']
    customer_id = result['customer']['id']
    uw_id = result['underwriting']['id']
    
    # Perform multiple operations
    # 1. Approve underwriting
    _post(base + "/api/underwriting/approve", {"id": uw_id})
    
    # 2. Create claim
    body = _post(base + "/api/claims/create", {
        "policy_id": policy_id,
        "customer_id": customer_id,
        "type": "death_benefit",
        "claimed_amount": 500000
    })
    claim_id = json.loads(body)['id']
    
    # 3. Approve claim
    _post(base + "/api/claims/approve", {
        "id": claim_id,
        "approved_amount": 500000
    })
    
    # 4. Create billing
    body = _post(base + "/api/billing/create", {
        "policy_id": policy_id,
        "amount_due": 3000.00
    })
    bill_id = json.loads(body)['bill']['bill_id']
    
    # 5. Pay bill
    _post(base + "/api/billing/pay", {
        "bill_id": bill_id,
        "amount": 3000.00
    })
    
    # Verify all data still exists and is correct
    assert policy_id in portal.POLICIES
    assert customer_id in portal.CUSTOMERS
    assert uw_id in portal.UNDERWRITING_APPLICATIONS
    assert claim_id in portal.CLAIMS
    assert bill_id in portal.BILLING
    
    # Verify status changes persisted
    policy = portal.POLICIES[policy_id]
    assert policy['status'] == 'active'
    
    uw_app = portal.UNDERWRITING_APPLICATIONS[uw_id]
    assert uw_app['status'] == 'approved'
    
    claim = portal.CLAIMS[claim_id]
    assert claim['status'] == 'approved'
    
    bill = portal.BILLING[bill_id]
    assert bill['status'] == 'paid'
    
    srv.stop()


def test_concurrent_data_access():
    """Test data remains consistent with concurrent access"""
    port = 8109
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.2)
    
    base = f"http://127.0.0.1:{port}"
    
    # Create initial data
    body = _post(base + "/api/policies/create", {
        "customer_name": "Concurrent Test",
        "customer_email": "concurrent@example.com",
        "type": "auto",
        "coverage_amount": 75000
    })
    result = json.loads(body)
    policy_id = result['policy']['id']
    customer_id = result['customer']['id']
    
    # Perform multiple reads concurrently (simulated by sequential reads)
    for _ in range(10):
        body = _get(base + f"/api/policies?id={policy_id}")
        policy = json.loads(body)
        assert policy['id'] == policy_id
        
        body = _get(base + f"/api/customers?id={customer_id}")
        customer = json.loads(body)
        assert customer['id'] == customer_id
    
    # Verify data integrity maintained
    assert policy_id in portal.POLICIES
    assert customer_id in portal.CUSTOMERS
    
    srv.stop()


def test_data_integrity_after_errors():
    """Test data integrity is maintained even after errors"""
    port = 8110
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.2)
    
    base = f"http://127.0.0.1:{port}"
    
    # Create valid data
    body = _post(base + "/api/policies/create", {
        "customer_name": "Error Test",
        "customer_email": "error@example.com",
        "type": "property",
        "coverage_amount": 350000
    })
    result = json.loads(body)
    policy_id = result['policy']['id']
    customer_id = result['customer']['id']
    
    initial_policy_count = len(portal.POLICIES)
    initial_customer_count = len(portal.CUSTOMERS)
    
    # Try to create invalid data (should fail without corrupting existing data)
    try:
        _post(base + "/api/policies/create", {
            "customer_name": "",  # Invalid: empty name
            "customer_email": "invalid",  # Invalid: bad email
            "coverage_amount": -1000  # Invalid: negative amount
        })
    except:
        pass  # Expected to fail
    
    # Verify original data still intact
    assert len(portal.POLICIES) == initial_policy_count  # No new invalid policy
    assert len(portal.CUSTOMERS) == initial_customer_count  # No new invalid customer
    assert policy_id in portal.POLICIES
    assert customer_id in portal.CUSTOMERS
    
    # Verify we can still access original data
    body = _get(base + f"/api/policies?id={policy_id}")
    policy = json.loads(body)
    assert policy['id'] == policy_id
    assert policy['coverage_amount'] == 350000
    
    srv.stop()
