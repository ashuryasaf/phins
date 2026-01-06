"""
Test Suite for Approval → Billing → Active Policy Flow

Tests the complete flow:
1. Admin approves underwriting application
2. Policy status changes to 'active'
3. Billing record is automatically created
4. Customer can see billing on their status page
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


def test_approval_creates_billing():
    """Test that approving an underwriting application creates billing"""
    port = 8050
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.3)
    
    base = f"http://127.0.0.1:{port}"
    
    # Step 1: Create a policy application
    print("\n=== Step 1: Create policy application ===")
    create_resp = json.loads(_post(
        base + "/api/policies/create",
        {
            "customer_name": "Billing Test Customer",
            "customer_email": "billing.test@example.com",
            "customer_phone": "555-9999",
            "type": "life",
            "coverage_amount": 500000,
            "risk_score": "medium",
            "age": 35
        }
    ))
    
    customer_id = create_resp['customer']['id']
    policy_id = create_resp['policy']['id']
    uw_id = create_resp['underwriting']['id']
    
    print(f"  Customer ID: {customer_id}")
    print(f"  Policy ID: {policy_id}")
    print(f"  Underwriting ID: {uw_id}")
    print(f"  Initial Policy Status: {create_resp['policy']['status']}")
    
    # Verify initial status is pending_underwriting
    assert create_resp['policy']['status'] == 'pending_underwriting'
    assert create_resp['underwriting']['status'] == 'pending'
    
    # Step 2: Login as admin and approve
    print("\n=== Step 2: Admin approves underwriting ===")
    admin_login = json.loads(_post(base + "/api/login", {
        "username": "admin",
        "password": "admin123"
    }))
    admin_token = admin_login['token']
    
    approve_resp = json.loads(_post(
        base + "/api/underwriting/approve",
        {
            "id": uw_id,
            "approved_by": "admin"
        },
        admin_token
    ))
    
    print(f"  Approval Success: {approve_resp['success']}")
    print(f"  Policy Status: {approve_resp.get('policy_status', 'N/A')}")
    print(f"  Bill ID: {approve_resp.get('bill_id', 'N/A')}")
    
    # Verify approval creates billing
    assert approve_resp['success'] is True
    assert approve_resp.get('policy_status') == 'active'
    assert approve_resp.get('bill_id') is not None, "Billing record should be created on approval"
    
    bill_id = approve_resp['bill_id']
    
    # Step 3: Verify policy is now active
    print("\n=== Step 3: Verify policy is active ===")
    policy_resp = json.loads(_get(base + f"/api/policies?id={policy_id}", admin_token))
    print(f"  Policy Status: {policy_resp['status']}")
    assert policy_resp['status'] == 'active'
    
    # Step 4: Verify customer can see billing
    print("\n=== Step 4: Verify customer status includes billing ===")
    status_resp = json.loads(_get(
        base + f"/api/customer/status?customer_id={customer_id}",
        admin_token
    ))
    
    print(f"  Overall Status: {status_resp['overall_status']}")
    print(f"  Billing Records: {len(status_resp.get('billing', []))}")
    print(f"  Outstanding Amount: ${status_resp.get('billing_summary', {}).get('total_outstanding', 0)}")
    
    # Verify customer status shows active and billing
    assert status_resp['overall_status'] in ['active_policy', 'approved']
    assert 'billing' in status_resp
    assert len(status_resp['billing']) > 0
    
    # Verify billing summary
    billing_summary = status_resp.get('billing_summary', {})
    assert billing_summary.get('outstanding_count', 0) > 0
    assert billing_summary.get('total_outstanding', 0) > 0
    
    # Step 5: Find and verify the specific bill
    print("\n=== Step 5: Verify specific bill details ===")
    bills = status_resp['billing']
    matching_bill = next((b for b in bills if (b.get('id') == bill_id or b.get('bill_id') == bill_id)), None)
    
    assert matching_bill is not None, f"Should find bill {bill_id} in customer status"
    print(f"  Bill ID: {matching_bill.get('id') or matching_bill.get('bill_id')}")
    print(f"  Policy ID: {matching_bill.get('policy_id')}")
    print(f"  Amount: ${matching_bill.get('amount', 0) or matching_bill.get('amount_due', 0)}")
    print(f"  Status: {matching_bill.get('status')}")
    
    assert matching_bill['policy_id'] == policy_id
    assert matching_bill['status'] == 'outstanding'
    
    srv.stop()
    print("\n✅ Test passed: Approval creates billing correctly!")


def test_approval_billing_with_multiple_policies():
    """Test billing works correctly with multiple policies"""
    port = 8051
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.3)
    
    base = f"http://127.0.0.1:{port}"
    
    admin_login = json.loads(_post(base + "/api/login", {
        "username": "admin",
        "password": "admin123"
    }))
    admin_token = admin_login['token']
    
    # Create first policy
    print("\n=== Creating first policy ===")
    create_resp1 = json.loads(_post(
        base + "/api/policies/create",
        {
            "customer_name": "First Policy Customer",
            "customer_email": "first.policy@example.com",
            "type": "life",
            "coverage_amount": 300000,
            "risk_score": "low",
            "age": 30
        }
    ))
    
    customer_id_1 = create_resp1['customer']['id']
    policy_id_1 = create_resp1['policy']['id']
    uw_id_1 = create_resp1['underwriting']['id']
    
    # Create second policy for different customer
    print("=== Creating second policy ===")
    create_resp2 = json.loads(_post(
        base + "/api/policies/create",
        {
            "customer_name": "Second Policy Customer",
            "customer_email": "second.policy@example.com",
            "type": "health",
            "coverage_amount": 200000,
            "risk_score": "medium",
            "age": 35
        }
    ))
    
    customer_id_2 = create_resp2['customer']['id']
    policy_id_2 = create_resp2['policy']['id']
    uw_id_2 = create_resp2['underwriting']['id']
    
    # Approve both policies
    print("=== Approving both policies ===")
    approve1 = json.loads(_post(
        base + "/api/underwriting/approve",
        {"id": uw_id_1, "approved_by": "admin"},
        admin_token
    ))
    bill_id_1 = approve1.get('bill_id')
    
    approve2 = json.loads(_post(
        base + "/api/underwriting/approve",
        {"id": uw_id_2, "approved_by": "admin"},
        admin_token
    ))
    bill_id_2 = approve2.get('bill_id')
    
    print(f"  Bill 1: {bill_id_1}")
    print(f"  Bill 2: {bill_id_2}")
    
    assert bill_id_1 is not None, "First approval should create billing"
    assert bill_id_2 is not None, "Second approval should create billing"
    assert bill_id_1 != bill_id_2, "Each policy should have unique bill ID"
    
    # Verify first customer sees their billing
    print("=== Verifying first customer billing ===")
    status1 = json.loads(_get(
        base + f"/api/customer/status?customer_id={customer_id_1}",
        admin_token
    ))
    billing1 = status1.get('billing', [])
    print(f"  Customer 1 Bills: {len(billing1)}")
    assert len(billing1) >= 1, "Customer 1 should have at least 1 bill"
    
    # Verify second customer sees their billing
    print("=== Verifying second customer billing ===")
    status2 = json.loads(_get(
        base + f"/api/customer/status?customer_id={customer_id_2}",
        admin_token
    ))
    billing2 = status2.get('billing', [])
    print(f"  Customer 2 Bills: {len(billing2)}")
    assert len(billing2) >= 1, "Customer 2 should have at least 1 bill"
    
    srv.stop()
    print("\n✅ Test passed: Multiple policy billing works correctly!")


def test_admin_approval_flow_desktop():
    """Test the complete admin approval flow as it appears on desktop"""
    port = 8052
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.3)
    
    base = f"http://127.0.0.1:{port}"
    
    print("\n=== Desktop Admin Approval Flow Test ===")
    
    # Step 1: Create application via apply page
    print("\n1. Customer submits application...")
    create_resp = json.loads(_post(
        base + "/api/policies/create",
        {
            "customer_name": "Desktop Test User",
            "customer_email": "desktop.test@example.com",
            "customer_phone": "555-DESK",
            "type": "life",
            "coverage_amount": 1000000,
            "risk_score": "high",
            "age": 45
        }
    ))
    
    policy_id = create_resp['policy']['id']
    uw_id = create_resp['underwriting']['id']
    customer_id = create_resp['customer']['id']
    creds = create_resp['provisioned_login']
    
    print(f"   ✓ Application created: {uw_id}")
    print(f"   ✓ Customer credentials provisioned")
    
    # Step 2: Admin logs in
    print("\n2. Admin logs into admin portal...")
    admin_login = json.loads(_post(base + "/api/login", {
        "username": "admin",
        "password": "admin123"
    }))
    admin_token = admin_login['token']
    print(f"   ✓ Admin authenticated")
    
    # Step 3: Admin views underwriting queue
    print("\n3. Admin views underwriting queue...")
    uw_list = json.loads(_get(base + "/api/underwriting", admin_token))
    pending = [u for u in uw_list if u['status'] == 'pending']
    print(f"   ✓ {len(pending)} pending applications")
    
    # Step 4: Admin approves application
    print("\n4. Admin approves application...")
    approve_resp = json.loads(_post(
        base + "/api/underwriting/approve",
        {
            "id": uw_id,
            "approved_by": "admin"
        },
        admin_token
    ))
    
    assert approve_resp['success'] is True
    assert approve_resp.get('policy_status') == 'active'
    assert approve_resp.get('bill_id') is not None
    
    bill_id = approve_resp['bill_id']
    print(f"   ✓ Application approved")
    print(f"   ✓ Policy activated: {policy_id}")
    print(f"   ✓ Billing created: {bill_id}")
    
    # Step 5: Customer logs in and checks status
    print("\n5. Customer checks their status...")
    customer_login = json.loads(_post(base + "/api/login", {
        "username": creds['username'],
        "password": creds['password']
    }))
    customer_token = customer_login['token']
    
    status_resp = json.loads(_get(
        base + "/api/customer/status",
        customer_token
    ))
    
    print(f"   ✓ Overall status: {status_resp['overall_status']}")
    print(f"   ✓ Active policies: {sum(1 for p in status_resp['policies'] if p['status'] == 'active')}")
    print(f"   ✓ Outstanding bills: {status_resp['billing_summary']['outstanding_count']}")
    print(f"   ✓ Amount due: ${status_resp['billing_summary']['total_outstanding']:.2f}")
    
    # Verify everything is correct
    assert status_resp['overall_status'] in ['active_policy', 'approved']
    assert any(p['status'] == 'active' for p in status_resp['policies'])
    assert status_resp['billing_summary']['outstanding_count'] > 0
    
    srv.stop()
    print("\n✅ Desktop admin approval flow test passed!")


def test_customer_validated_on_desktop():
    """Test customer can view active policy and billing on desktop"""
    port = 8053
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.3)
    
    base = f"http://127.0.0.1:{port}"
    
    print("\n=== Customer Validation on Desktop ===")
    
    # Create and approve policy
    create_resp = json.loads(_post(
        base + "/api/policies/create",
        {
            "customer_name": "Validated Customer",
            "customer_email": "validated@example.com",
            "type": "health",
            "coverage_amount": 250000,
            "risk_score": "low",
            "age": 28
        }
    ))
    
    customer_id = create_resp['customer']['id']
    policy_id = create_resp['policy']['id']
    uw_id = create_resp['underwriting']['id']
    creds = create_resp['provisioned_login']
    
    # Approve
    admin_login = json.loads(_post(base + "/api/login", {
        "username": "admin",
        "password": "admin123"
    }))
    
    approve_resp = json.loads(_post(
        base + "/api/underwriting/approve",
        {"id": uw_id, "approved_by": "admin"},
        admin_login['token']
    ))
    
    # Customer validation
    print("\n1. Customer logs in with provisioned credentials...")
    customer_login = json.loads(_post(base + "/api/login", {
        "username": creds['username'],
        "password": creds['password']
    }))
    customer_token = customer_login['token']
    assert customer_login['role'] == 'customer'
    print(f"   ✓ Logged in as: {customer_login['name']}")
    
    print("\n2. Customer views status page...")
    status = json.loads(_get(base + "/api/customer/status", customer_token))
    
    print(f"   ✓ Status: {status['overall_status']}")
    assert status['overall_status'] in ['active_policy', 'approved']
    
    print("\n3. Customer views policies...")
    policies = status['policies']
    active_policy = next((p for p in policies if p['id'] == policy_id), None)
    assert active_policy is not None
    assert active_policy['status'] == 'active'
    print(f"   ✓ Policy {policy_id}: {active_policy['status']}")
    print(f"   ✓ Coverage: ${active_policy['coverage_amount']}")
    
    print("\n4. Customer views billing...")
    billing = status['billing']
    billing_summary = status['billing_summary']
    
    assert len(billing) > 0
    print(f"   ✓ Bills: {len(billing)}")
    print(f"   ✓ Outstanding: ${billing_summary['total_outstanding']:.2f}")
    print(f"   ✓ Due date: {billing_summary.get('next_due', 'N/A')}")
    
    srv.stop()
    print("\n✅ Customer validation on desktop passed!")


if __name__ == '__main__':
    print("=" * 60)
    print("APPROVAL → BILLING → ACTIVE POLICY FLOW TEST SUITE")
    print("=" * 60)
    
    test_approval_creates_billing()
    test_approval_billing_with_multiple_policies()
    test_admin_approval_flow_desktop()
    test_customer_validated_on_desktop()
    
    print("\n" + "=" * 60)
    print("ALL TESTS PASSED ✅")
    print("=" * 60)
