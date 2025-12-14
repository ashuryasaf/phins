"""
Complete Customer Journey Test - Standalone Edition

This test validates the entire insurance lifecycle from application to claim payment.
It's designed to be run as a single comprehensive test that exercises all system features.

Journey Steps:
1. Customer applies for life insurance
2. System provisions account with login credentials
3. Customer logs in with provisioned credentials
4. Customer checks application status (pending)
5. Underwriter logs in and reviews application
6. Underwriter approves application
7. Customer checks status (now active policy)
8. System creates first premium bill
9. Customer pays first premium
10. Customer files a claim
11. Claims adjuster reviews and approves claim
12. Accountant processes claim payment
13. Customer views billing history
14. Admin views audit logs
15. Admin checks business intelligence metrics
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


def _get(url, token=None):
    """HTTP GET request"""
    headers = {}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    req = Request(url, headers=headers)
    with urlopen(req) as resp:
        return resp.read().decode('utf-8')


def _post(url, payload, token=None):
    """HTTP POST request"""
    data = json.dumps(payload).encode('utf-8')
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    req = Request(url, data=data, headers=headers)
    with urlopen(req) as resp:
        return resp.read().decode('utf-8')


def test_complete_insurance_lifecycle():
    """
    Complete end-to-end insurance lifecycle test.
    
    This test simulates a real-world insurance customer journey from application
    through policy approval, premium payment, claim filing, and final settlement.
    """
    port = 8120
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.3)
    
    base = f"http://127.0.0.1:{port}"
    
    print("\n" + "="*70)
    print("COMPLETE INSURANCE LIFECYCLE TEST")
    print("="*70)
    
    # ========== STEP 1: Customer applies for life insurance ==========
    print("\n📝 STEP 1: Customer applies for life insurance")
    print("-" * 70)
    
    create_resp = json.loads(_post(
        base + "/api/policies/create",
        {
            "customer_name": "Sarah Johnson",
            "customer_email": "sarah.johnson@example.com",
            "customer_phone": "555-0123",
            "type": "life",
            "coverage_amount": 1000000,
            "risk_score": "medium",
            "age": 35
        }
    ))
    
    customer = create_resp['customer']
    policy = create_resp['policy']
    underwriting = create_resp['underwriting']
    login_creds = create_resp['provisioned_login']
    
    print(f"✓ Customer created: {customer['name']} (ID: {customer['id']})")
    print(f"✓ Policy created: {policy['id']}")
    print(f"✓ Coverage amount: ${policy['coverage_amount']:,}")
    print(f"✓ Annual premium: ${policy['annual_premium']:,.2f}")
    print(f"✓ Policy status: {policy['status']}")
    print(f"✓ Underwriting application: {underwriting['id']}")
    
    # ========== STEP 2: System provisions account ==========
    print("\n🔑 STEP 2: System auto-provisions account")
    print("-" * 70)
    
    print(f"✓ Username: {login_creds['username']}")
    print(f"✓ Password: {login_creds['password'][:4]}******")
    print(f"✓ Account ready for customer login")
    
    # ========== STEP 3: Customer logs in ==========
    print("\n👤 STEP 3: Customer logs in")
    print("-" * 70)
    
    customer_login = json.loads(_post(base + "/api/login", {
        "username": login_creds['username'],
        "password": login_creds['password']
    }))
    
    customer_token = customer_login['token']
    print(f"✓ Login successful")
    print(f"✓ Token: {customer_token[:30]}...")
    print(f"✓ Role: {customer_login['role']}")
    print(f"✓ Customer ID: {customer_login['customer_id']}")
    
    # ========== STEP 4: Check application status (pending) ==========
    print("\n📊 STEP 4: Customer checks application status")
    print("-" * 70)
    
    status_resp = json.loads(_get(
        base + f"/api/customer/status?customer_id={customer['id']}"
    ))
    
    print(f"✓ Overall status: {status_resp['overall_status']}")
    print(f"✓ Active policies: {len([p for p in status_resp['policies'] if p.get('status') == 'active'])}")
    print(f"✓ Pending applications: {len([u for u in status_resp['underwriting_applications'] if u.get('status') == 'pending'])}")
    
    assert status_resp['overall_status'] in ['pending', 'no_application']
    
    # ========== STEP 5: Underwriter logs in and reviews ==========
    print("\n🔍 STEP 5: Underwriter reviews application")
    print("-" * 70)
    
    uw_login = json.loads(_post(base + "/api/login", {
        "username": "underwriter",
        "password": "under123"
    }))
    
    uw_token = uw_login['token']
    print(f"✓ Underwriter logged in: {uw_login.get('username', 'underwriter')}")
    
    # View pending applications
    pending_apps = json.loads(_get(base + "/api/underwriting", uw_token))
    pending_count = sum(1 for app in pending_apps if app.get('status') == 'pending')
    print(f"✓ Pending applications: {pending_count}")
    
    # ========== STEP 6: Underwriter approves application ==========
    print("\n✅ STEP 6: Underwriter approves application")
    print("-" * 70)
    
    approve_resp = json.loads(_post(
        base + "/api/underwriting/approve",
        {
            "id": underwriting['id'],
            "approved_by": "underwriter"
        }
    ))
    
    print(f"✓ Application approved: {approve_resp['success']}")
    print(f"✓ Approval date: {approve_resp['application'].get('decision_date', 'N/A')}")
    print(f"✓ Approved by: {approve_resp['application'].get('approved_by', 'N/A')}")
    
    assert approve_resp['success'] is True
    
    # ========== STEP 7: Customer checks updated status ==========
    print("\n📊 STEP 7: Customer checks updated status")
    print("-" * 70)
    
    status_after = json.loads(_get(
        base + f"/api/customer/status?customer_id={customer['id']}"
    ))
    
    print(f"✓ Updated status: {status_after['overall_status']}")
    
    # Get policy status
    policy_status = json.loads(_get(base + f"/api/policies?id={policy['id']}"))
    print(f"✓ Policy status: {policy_status['status']}")
    
    assert policy_status['status'] == 'active'
    assert status_after['overall_status'] in ['active_policy', 'approved']
    
    # ========== STEP 8: Create first premium bill ==========
    print("\n💰 STEP 8: System creates first premium bill")
    print("-" * 70)
    
    bill_resp = json.loads(_post(
        base + "/api/billing/create",
        {
            "policy_id": policy['id'],
            "amount_due": policy['annual_premium'],
            "due_days": 30
        }
    ))
    
    bill = bill_resp['bill']
    bill_id = bill['bill_id']
    
    print(f"✓ Bill created: {bill_id}")
    print(f"✓ Amount due: ${bill['amount_due']:,.2f}")
    print(f"✓ Due date: {bill.get('due_date', 'N/A')}")
    print(f"✓ Status: {bill['status']}")
    
    # ========== STEP 9: Customer pays first premium ==========
    print("\n💳 STEP 9: Customer pays first premium")
    print("-" * 70)
    
    payment_resp = json.loads(_post(
        base + "/api/billing/pay",
        {
            "bill_id": bill_id,
            "amount": policy['annual_premium']
        }
    ))
    
    paid_bill = payment_resp['bill']
    print(f"✓ Payment processed")
    print(f"✓ Amount paid: ${paid_bill['amount_paid']:,.2f}")
    print(f"✓ Payment status: {paid_bill['status']}")
    
    assert paid_bill['status'] == 'paid'
    
    # ========== STEP 10: Customer files a claim ==========
    print("\n🏥 STEP 10: Customer files a claim")
    print("-" * 70)
    
    claim_resp = json.loads(_post(
        base + "/api/claims/create",
        {
            "policy_id": policy['id'],
            "customer_id": customer['id'],
            "type": "critical_illness",
            "description": "Diagnosed with critical illness - requiring treatment",
            "claimed_amount": 150000
        }
    ))
    
    claim_id = claim_resp['id']
    print(f"✓ Claim filed: {claim_id}")
    print(f"✓ Claim type: {claim_resp['type']}")
    print(f"✓ Claimed amount: ${claim_resp['claimed_amount']:,}")
    print(f"✓ Status: {claim_resp['status']}")
    
    # ========== STEP 11: Claims adjuster reviews and approves ==========
    print("\n🔍 STEP 11: Claims adjuster reviews and approves claim")
    print("-" * 70)
    
    claims_login = json.loads(_post(base + "/api/login", {
        "username": "claims_adjuster",
        "password": "claims123"
    }))
    
    claims_token = claims_login['token']
    print(f"✓ Claims adjuster logged in")
    
    # View pending claims
    pending_claims = json.loads(_get(base + "/api/claims?status=pending", claims_token))
    print(f"✓ Pending claims: {len(pending_claims['items'])}")
    
    # Approve claim with adjustment
    approved_amount = 145000  # Slightly reduced after review
    claim_approve = json.loads(_post(
        base + "/api/claims/approve",
        {
            "id": claim_id,
            "approved_amount": approved_amount,
            "approved_by": "claims_adjuster",
            "notes": "Approved after medical review. Deductible applied."
        },
        claims_token
    ))
    
    print(f"✓ Claim approved")
    print(f"✓ Approved amount: ${claim_approve['claim']['approved_amount']:,}")
    print(f"✓ Notes: {claim_approve['claim'].get('approval_notes', 'N/A')}")
    
    # ========== STEP 12: Accountant processes claim payment ==========
    print("\n💸 STEP 12: Accountant processes claim payment")
    print("-" * 70)
    
    acct_login = json.loads(_post(base + "/api/login", {
        "username": "accountant",
        "password": "acct123"
    }))
    
    acct_token = acct_login['token']
    print(f"✓ Accountant logged in")
    
    claim_pay = json.loads(_post(
        base + "/api/claims/pay",
        {
            "id": claim_id,
            "payment_method": "bank_transfer",
            "processed_by": "accountant"
        }
    ))
    
    print(f"✓ Claim payment processed")
    print(f"✓ Payment status: {claim_pay['claim']['status']}")
    print(f"✓ Payment reference: {claim_pay['claim'].get('payment_reference', 'N/A')}")
    print(f"✓ Paid amount: ${claim_pay['claim']['paid_amount']:,}")
    
    assert claim_pay['claim']['status'] == 'paid'
    
    # ========== STEP 13: Customer views billing history ==========
    print("\n📜 STEP 13: Customer views their account")
    print("-" * 70)
    
    final_status = json.loads(_get(
        base + f"/api/customer/status?customer_id={customer['id']}"
    ))
    
    print(f"✓ Total policies: {len(final_status['policies'])}")
    print(f"✓ Active policies: {len([p for p in final_status['policies'] if p.get('status') == 'active'])}")
    
    # Get claims list
    customer_claims = json.loads(_get(base + "/api/claims"))
    customer_claim_count = len([c for c in customer_claims['items'] if c.get('customer_id') == customer['id']])
    print(f"✓ Total claims: {customer_claim_count}")
    print(f"✓ Paid claims: {len([c for c in customer_claims['items'] if c.get('status') == 'paid' and c.get('customer_id') == customer['id']])}")
    
    # ========== STEP 14: Admin views audit logs ==========
    print("\n📋 STEP 14: Admin reviews audit logs")
    print("-" * 70)
    
    admin_login = json.loads(_post(base + "/api/login", {
        "username": "admin",
        "password": "admin123"
    }))
    
    admin_token = admin_login['token']
    print(f"✓ Admin logged in")
    
    audit_resp = json.loads(_get(base + "/api/audit?page=1&page_size=10", admin_token))
    print(f"✓ Total audit entries: {audit_resp['total']}")
    print(f"✓ Recent entries retrieved: {len(audit_resp['items'])}")
    
    # ========== STEP 15: Admin checks BI metrics ==========
    print("\n📈 STEP 15: Admin checks business intelligence metrics")
    print("-" * 70)
    
    # Actuarial metrics
    actuary_resp = json.loads(_get(base + "/api/bi/actuary", admin_token))
    print(f"✓ Total policies: {actuary_resp['total_policies']}")
    print(f"✓ Total exposure: ${actuary_resp['total_exposure']:,.2f}")
    print(f"✓ Average premium: ${actuary_resp['average_premium']:,.2f}")
    print(f"✓ Claims ratio: {actuary_resp['claims_ratio']:.2%}")
    
    # Underwriting metrics
    uw_metrics = json.loads(_get(base + "/api/bi/underwriting", admin_token))
    print(f"✓ Pending applications: {uw_metrics['pending_applications']}")
    print(f"✓ Approved this month: {uw_metrics['approved_this_month']}")
    
    # Accounting metrics
    acct_metrics = json.loads(_get(base + "/api/bi/accounting", admin_token))
    print(f"✓ Total revenue: ${acct_metrics['total_revenue']:,.2f}")
    print(f"✓ Total claims paid: ${acct_metrics['total_claims_paid']:,.2f}")
    print(f"✓ Net income: ${acct_metrics['net_income']:,.2f}")
    print(f"✓ Profit margin: {acct_metrics['profit_margin']:.2f}%")
    
    # Platform metrics
    platform_metrics = json.loads(_get(base + "/api/metrics"))
    print(f"✓ Platform metrics retrieved")
    
    # ========== JOURNEY COMPLETE ==========
    print("\n" + "="*70)
    print("✅ COMPLETE INSURANCE LIFECYCLE TEST PASSED!")
    print("="*70)
    print("\nSummary:")
    print(f"  • Customer: {customer['name']}")
    print(f"  • Policy: {policy['id']} (${policy['coverage_amount']:,} coverage)")
    print(f"  • Premium: ${policy['annual_premium']:,.2f}/year")
    print(f"  • Claim: {claim_id} (${claim_pay['claim']['paid_amount']:,} paid)")
    print(f"  • Status: Policy Active, Premium Paid, Claim Settled")
    print("\n" + "="*70 + "\n")
    
    srv.stop()


if __name__ == '__main__':
    """Allow running this test standalone"""
    import sys
    import pytest
    
    sys.exit(pytest.main([__file__, '-v', '-s']))
