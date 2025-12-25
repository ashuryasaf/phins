"""
Comprehensive End-to-End Test Suite for PHINS Insurance Platform

Tests the complete customer journey from application to claim payment:
1. Customer applies for insurance → account provisioned
2. Underwriting reviews application → risk assessment
3. Policy approved/rejected → billing activated
4. Customer portal access → claims filing
5. Admin portal → complete workflow management
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
    """HTTP GET request with optional authentication"""
    headers = {}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    req = Request(url, headers=headers)
    with urlopen(req) as resp:
        return resp.read().decode('utf-8')


def _post(url, payload, token=None):
    """HTTP POST request with optional authentication"""
    data = json.dumps(payload).encode('utf-8')
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    req = Request(url, data=data, headers=headers)
    with urlopen(req) as resp:
        return resp.read().decode('utf-8')


def test_customer_application_flow():
    """Test customer can apply for insurance and get account provisioned"""
    port = 8021
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.3)
    
    base = f"http://127.0.0.1:{port}"
    
    # Customer applies for life insurance
    create_resp = json.loads(_post(
        base + "/api/policies/create",
        {
            "customer_name": "John Doe",
            "customer_email": "john.doe@example.com",
            "customer_phone": "555-1234",
            "type": "life",
            "coverage_amount": 500000,
            "risk_score": "medium",
            "age": 35
        }
    ))
    
    # Verify response structure
    assert 'customer' in create_resp
    assert 'policy' in create_resp
    assert 'underwriting' in create_resp
    assert 'provisioned_login' in create_resp
    
    # Verify customer record created
    customer = create_resp['customer']
    assert customer['name'] == "John Doe"
    assert customer['email'] == "john.doe@example.com"
    assert 'id' in customer
    
    # Verify policy created with correct status
    policy = create_resp['policy']
    assert policy['status'] == 'pending_underwriting'
    assert policy['type'] == 'life'
    assert policy['coverage_amount'] == 500000
    assert 'annual_premium' in policy
    assert policy['annual_premium'] > 0
    
    # Verify underwriting application created
    underwriting = create_resp['underwriting']
    assert underwriting['status'] == 'pending'
    assert underwriting['policy_id'] == policy['id']
    assert underwriting['customer_id'] == customer['id']
    
    # Verify login credentials provisioned
    login = create_resp['provisioned_login']
    assert login['username'] == customer['email']
    assert len(login['password']) >= 8
    
    srv.stop()


def test_authentication_and_portal_access():
    """Test authentication workflow and session management"""
    port = 8022
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.3)
    
    base = f"http://127.0.0.1:{port}"
    
    # Create customer with provisioned credentials
    create_resp = json.loads(_post(
        base + "/api/policies/create",
        {
            "customer_name": "Jane Smith",
            "customer_email": "jane.smith@example.com",
            "type": "health",
            "coverage_amount": 200000,
            "risk_score": "low"
        }
    ))
    
    customer = create_resp['customer']
    login_creds = create_resp['provisioned_login']
    
    # Test login with provisioned credentials
    login_resp = json.loads(_post(base + "/api/login", {
        "username": login_creds['username'],
        "password": login_creds['password']
    }))
    
    assert 'token' in login_resp
    assert login_resp['token'].startswith('phins_')
    assert login_resp['role'] == 'customer'
    assert login_resp['customer_id'] == customer['id']
    
    token = login_resp['token']
    
    # Test authenticated request - get profile
    profile_resp = json.loads(_get(base + "/api/profile", token))
    assert profile_resp['username'] == login_creds['username']
    assert profile_resp['role'] == 'customer'
    assert profile_resp['customer_id'] == customer['id']
    
    # Test session validation - get customer status
    status_resp = json.loads(_get(
        base + f"/api/customer/status?customer_id={customer['id']}"
    ))
    assert status_resp['customer']['id'] == customer['id']
    assert 'overall_status' in status_resp
    assert len(status_resp['policies']) > 0
    
    srv.stop()


def test_underwriting_workflow():
    """Test complete underwriting workflow from pending to approval"""
    port = 8023
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.3)
    
    base = f"http://127.0.0.1:{port}"
    
    # Create policy application
    create_resp = json.loads(_post(
        base + "/api/policies/create",
        {
            "customer_name": "Bob Wilson",
            "customer_email": "bob.wilson@example.com",
            "type": "life",
            "coverage_amount": 1000000,
            "risk_score": "high"
        }
    ))
    
    uw_id = create_resp['underwriting']['id']
    policy_id = create_resp['policy']['id']
    customer_id = create_resp['customer']['id']
    
    # Login as underwriter
    uw_login = json.loads(_post(base + "/api/login", {
        "username": "underwriter",
        "password": "under123"
    }))
    assert uw_login['role'] == 'underwriter'
    uw_token = uw_login['token']
    
    # View pending applications
    apps = json.loads(_get(base + "/api/underwriting", uw_token))
    assert len(apps) > 0
    pending_app = next((a for a in apps if a['id'] == uw_id), None)
    assert pending_app is not None
    assert pending_app['status'] == 'pending'
    
    # Approve application
    approve_resp = json.loads(_post(
        base + "/api/underwriting/approve",
        {
            "id": uw_id,
            "approved_by": "underwriter"
        },
        uw_token
    ))
    
    assert approve_resp['success'] is True
    assert approve_resp['application']['status'] == 'approved'
    
    # Verify policy status changed to active
    policy_resp = json.loads(_get(base + f"/api/policies?id={policy_id}"))
    assert policy_resp['status'] == 'active'
    
    # Verify customer can see active policy
    status_resp = json.loads(_get(
        base + f"/api/customer/status?customer_id={customer_id}"
    ))
    assert status_resp['overall_status'] in ['active_policy', 'approved']
    
    srv.stop()


def test_claims_processing_workflow():
    """Test complete claims workflow from filing to payment"""
    port = 8024
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.3)
    
    base = f"http://127.0.0.1:{port}"
    
    # Create and approve policy first
    create_resp = json.loads(_post(
        base + "/api/policies/create",
        {
            "customer_name": "Alice Brown",
            "customer_email": "alice.brown@example.com",
            "type": "health",
            "coverage_amount": 300000,
            "risk_score": "medium"
        }
    ))
    
    policy_id = create_resp['policy']['id']
    customer_id = create_resp['customer']['id']
    uw_id = create_resp['underwriting']['id']
    
    # Approve underwriting
    _post(base + "/api/underwriting/approve", {
        "id": uw_id,
        "approved_by": "underwriter"
    })
    
    # Customer files a claim
    claim_resp = json.loads(_post(
        base + "/api/claims/create",
        {
            "policy_id": policy_id,
            "customer_id": customer_id,
            "type": "medical",
            "description": "Emergency surgery",
            "claimed_amount": 50000
        }
    ))
    
    assert 'id' in claim_resp
    assert claim_resp['status'] == 'pending'
    assert claim_resp['claimed_amount'] == 50000
    claim_id = claim_resp['id']
    
    # Login as claims adjuster
    claims_login = json.loads(_post(base + "/api/login", {
        "username": "claims_adjuster",
        "password": "claims123"
    }))
    assert claims_login['role'] == 'claims'
    claims_token = claims_login['token']
    
    # View pending claims
    claims_list = json.loads(_get(
        base + "/api/claims?status=pending",
        claims_token
    ))
    assert len(claims_list['items']) > 0
    pending_claim = next((c for c in claims_list['items'] if c['id'] == claim_id), None)
    assert pending_claim is not None
    
    # Approve claim with adjusted amount
    approve_resp = json.loads(_post(
        base + "/api/claims/approve",
        {
            "id": claim_id,
            "approved_amount": 45000,
            "approved_by": "claims_adjuster",
            "notes": "Approved with deductible applied"
        },
        claims_token
    ))
    
    assert approve_resp['success'] is True
    assert approve_resp['claim']['status'] == 'approved'
    assert approve_resp['claim']['approved_amount'] == 45000
    
    # Process payment
    pay_resp = json.loads(_post(
        base + "/api/claims/pay",
        {
            "id": claim_id,
            "payment_method": "bank_transfer",
            "processed_by": "accountant"
        }
    ))
    
    assert pay_resp['success'] is True
    assert pay_resp['claim']['status'] == 'paid'
    assert 'payment_reference' in pay_resp['claim']
    assert pay_resp['claim']['paid_amount'] == 45000
    
    srv.stop()


def test_business_intelligence_endpoints():
    """Test BI endpoints for actuarial, underwriting, and accounting data"""
    port = 8025
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.3)
    
    base = f"http://127.0.0.1:{port}"
    
    # Create some test data first
    for i in range(3):
        _post(base + "/api/policies/create", {
            "customer_name": f"Test Customer {i}",
            "customer_email": f"test{i}@example.com",
            "type": "life",
            "coverage_amount": 100000 * (i + 1),
            "risk_score": ["low", "medium", "high"][i]
        })
    
    # Login as admin
    admin_login = json.loads(_post(base + "/api/login", {
        "username": "admin",
        "password": "As11as11@"
    }))
    assert admin_login['role'] == 'admin'
    admin_token = admin_login['token']
    
    # Test actuarial BI data
    actuary_resp = json.loads(_get(base + "/api/bi/actuary", admin_token))
    assert 'total_policies' in actuary_resp
    assert 'total_exposure' in actuary_resp
    assert 'average_premium' in actuary_resp
    assert 'risk_distribution' in actuary_resp
    assert actuary_resp['total_policies'] >= 3
    
    # Test underwriting BI data
    underwriting_resp = json.loads(_get(base + "/api/bi/underwriting", admin_token))
    assert 'pending_applications' in underwriting_resp
    assert 'rejection_rate' in underwriting_resp
    assert 'risk_assessment_distribution' in underwriting_resp
    
    # Test accounting BI data
    accounting_resp = json.loads(_get(base + "/api/bi/accounting", admin_token))
    assert 'total_revenue' in accounting_resp
    assert 'total_claims_paid' in accounting_resp
    assert 'net_income' in accounting_resp
    assert 'profit_margin' in accounting_resp
    assert 'monthly_breakdown' in accounting_resp
    
    # Test metrics endpoint (no auth required for basic metrics)
    metrics_resp = json.loads(_get(base + "/api/metrics"))
    assert 'metrics' in metrics_resp
    assert 'ts' in metrics_resp
    
    srv.stop()


def test_role_based_access_control():
    """Test that role-based access control works properly"""
    port = 8026
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.3)
    
    base = f"http://127.0.0.1:{port}"
    
    # Create customer
    create_resp = json.loads(_post(
        base + "/api/policies/create",
        {
            "customer_name": "Test Customer",
            "customer_email": "testcust@example.com",
            "type": "life",
            "coverage_amount": 100000
        }
    ))
    
    customer_creds = create_resp['provisioned_login']
    
    # Login as customer
    customer_login = json.loads(_post(base + "/api/login", {
        "username": customer_creds['username'],
        "password": customer_creds['password']
    }))
    customer_token = customer_login['token']
    
    # Test customer CANNOT access admin endpoints
    try:
        _get(base + "/api/audit", customer_token)
        assert False, "Customer should not access admin endpoints"
    except HTTPError as e:
        assert e.code == 403
    
    try:
        _get(base + "/api/security/threats", customer_token)
        assert False, "Customer should not access security endpoints"
    except HTTPError as e:
        assert e.code == 403
    
    # Login as admin
    admin_login = json.loads(_post(base + "/api/login", {
        "username": "admin",
        "password": "As11as11@"
    }))
    admin_token = admin_login['token']
    
    # Admin CAN access admin endpoints
    audit_resp = json.loads(_get(base + "/api/audit", admin_token))
    assert 'items' in audit_resp
    
    security_resp = json.loads(_get(base + "/api/security/threats", admin_token))
    assert 'malicious_attempts' in security_resp
    assert 'blocked_ips' in security_resp
    
    # Test underwriter can access underwriting BI but not accounting
    uw_login = json.loads(_post(base + "/api/login", {
        "username": "underwriter",
        "password": "under123"
    }))
    uw_token = uw_login['token']
    
    uw_bi_resp = json.loads(_get(base + "/api/bi/underwriting", uw_token))
    assert 'pending_applications' in uw_bi_resp
    
    try:
        _get(base + "/api/bi/accounting", uw_token)
        assert False, "Underwriter should not access accounting BI"
    except HTTPError as e:
        assert e.code == 403
    
    srv.stop()


def test_complete_customer_journey():
    """
    Complete end-to-end customer journey test:
    1. Customer applies for insurance
    2. System provisions account
    3. Customer logs in
    4. Checks application status (pending)
    5. Underwriter reviews and approves
    6. Customer checks status (active policy)
    7. First premium payment processed
    8. Customer files a claim
    9. Claims adjuster reviews and approves
    10. Claim is paid
    11. Customer views billing history
    12. Admin views audit logs
    """
    port = 8027
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.3)
    
    base = f"http://127.0.0.1:{port}"
    
    # Step 1: Customer applies for life insurance
    print("\n=== Step 1: Customer applies for insurance ===")
    create_resp = json.loads(_post(
        base + "/api/policies/create",
        {
            "customer_name": "Complete Journey Customer",
            "customer_email": "journey@example.com",
            "type": "life",
            "coverage_amount": 750000,
            "risk_score": "medium",
            "age": 40
        }
    ))
    
    customer = create_resp['customer']
    policy = create_resp['policy']
    underwriting = create_resp['underwriting']
    login_creds = create_resp['provisioned_login']
    
    print(f"Customer ID: {customer['id']}")
    print(f"Policy ID: {policy['id']}")
    print(f"Annual Premium: ${policy['annual_premium']}")
    
    # Step 2: System provisioned account (already done in create_resp)
    print("\n=== Step 2: Account provisioned ===")
    print(f"Username: {login_creds['username']}")
    print(f"Password: {login_creds['password'][:4]}****")
    
    # Step 3: Customer logs in
    print("\n=== Step 3: Customer logs in ===")
    customer_login = json.loads(_post(base + "/api/login", {
        "username": login_creds['username'],
        "password": login_creds['password']
    }))
    customer_token = customer_login['token']
    print(f"Token received: {customer_token[:20]}...")
    
    # Step 4: Check application status (pending)
    print("\n=== Step 4: Check application status ===")
    status_resp = json.loads(_get(
        base + f"/api/customer/status?customer_id={customer['id']}"
    ))
    print(f"Overall status: {status_resp['overall_status']}")
    assert status_resp['overall_status'] in ['pending', 'no_application']
    
    # Step 5: Underwriter reviews and approves
    print("\n=== Step 5: Underwriter approves application ===")
    uw_login = json.loads(_post(base + "/api/login", {
        "username": "underwriter",
        "password": "under123"
    }))
    
    approve_resp = json.loads(_post(
        base + "/api/underwriting/approve",
        {
            "id": underwriting['id'],
            "approved_by": "underwriter"
        }
    ))
    print(f"Application approved: {approve_resp['success']}")
    assert approve_resp['success'] is True
    
    # Step 6: Customer checks status (active policy)
    print("\n=== Step 6: Check updated status ===")
    status_resp = json.loads(_get(
        base + f"/api/customer/status?customer_id={customer['id']}"
    ))
    print(f"Updated status: {status_resp['overall_status']}")
    assert status_resp['overall_status'] in ['active_policy', 'approved']
    
    # Step 7: First premium payment processed
    print("\n=== Step 7: Process first premium payment ===")
    bill_resp = json.loads(_post(
        base + "/api/billing/create",
        {
            "policy_id": policy['id'],
            "amount_due": policy['annual_premium'],
            "due_days": 30
        }
    ))
    bill_id = bill_resp['bill']['bill_id']
    print(f"Bill created: {bill_id}, Amount: ${bill_resp['bill']['amount_due']}")
    
    pay_resp = json.loads(_post(
        base + "/api/billing/pay",
        {
            "bill_id": bill_id,
            "amount": policy['annual_premium']
        }
    ))
    print(f"Payment processed: {pay_resp['bill']['status']}")
    assert pay_resp['bill']['status'] == 'paid'
    
    # Step 8: Customer files a claim
    print("\n=== Step 8: Customer files a claim ===")
    claim_resp = json.loads(_post(
        base + "/api/claims/create",
        {
            "policy_id": policy['id'],
            "customer_id": customer['id'],
            "type": "critical_illness",
            "description": "Cancer treatment",
            "claimed_amount": 100000
        }
    ))
    claim_id = claim_resp['id']
    print(f"Claim filed: {claim_id}, Amount: ${claim_resp['claimed_amount']}")
    
    # Step 9: Claims adjuster reviews and approves
    print("\n=== Step 9: Claims adjuster reviews ===")
    claims_login = json.loads(_post(base + "/api/login", {
        "username": "claims_adjuster",
        "password": "claims123"
    }))
    
    claim_approve = json.loads(_post(
        base + "/api/claims/approve",
        {
            "id": claim_id,
            "approved_amount": 95000,
            "approved_by": "claims_adjuster",
            "notes": "Approved after review"
        }
    ))
    print(f"Claim approved: ${claim_approve['claim']['approved_amount']}")
    
    # Step 10: Claim is paid
    print("\n=== Step 10: Process claim payment ===")
    claim_pay = json.loads(_post(
        base + "/api/claims/pay",
        {
            "id": claim_id,
            "payment_method": "bank_transfer"
        }
    ))
    print(f"Claim paid: {claim_pay['claim']['status']}")
    print(f"Payment reference: {claim_pay['claim']['payment_reference']}")
    assert claim_pay['claim']['status'] == 'paid'
    
    # Step 11: Customer views their info
    print("\n=== Step 11: Customer views their data ===")
    final_status = json.loads(_get(
        base + f"/api/customer/status?customer_id={customer['id']}"
    ))
    print(f"Total policies: {len(final_status['policies'])}")
    print(f"Total underwriting apps: {len(final_status['underwriting_applications'])}")
    
    # Step 12: Admin views audit logs
    print("\n=== Step 12: Admin reviews audit logs ===")
    admin_login = json.loads(_post(base + "/api/login", {
        "username": "admin",
        "password": "As11as11@"
    }))
    
    audit_resp = json.loads(_get(base + "/api/audit?page=1&page_size=10", admin_login['token']))
    print(f"Total audit entries: {audit_resp['total']}")
    
    print("\n=== Journey Complete! ===")
    
    srv.stop()


def test_pagination_functionality():
    """Test pagination works correctly for policies and claims"""
    port = 8028
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.3)
    
    base = f"http://127.0.0.1:{port}"
    
    # Create 15 policies
    for i in range(15):
        _post(base + "/api/policies/create", {
            "customer_name": f"Pagination Test {i}",
            "customer_email": f"page{i}@example.com",
            "type": "life",
            "coverage_amount": 100000
        })
    
    # Test pagination - page 1 with page_size 5
    page1 = json.loads(_get(base + "/api/policies?page=1&page_size=5"))
    assert len(page1['items']) == 5
    assert page1['page'] == 1
    assert page1['page_size'] == 5
    assert page1['total'] >= 15
    
    # Test pagination - page 2
    page2 = json.loads(_get(base + "/api/policies?page=2&page_size=5"))
    assert len(page2['items']) == 5
    assert page2['page'] == 2
    
    # Test pagination - page 3
    page3 = json.loads(_get(base + "/api/policies?page=3&page_size=5"))
    assert len(page3['items']) == 5
    assert page3['page'] == 3
    
    # Verify items are different between pages
    page1_ids = {p['id'] for p in page1['items']}
    page2_ids = {p['id'] for p in page2['items']}
    assert len(page1_ids.intersection(page2_ids)) == 0
    
    srv.stop()
