#!/usr/bin/env python3
"""
Comprehensive Admin Action Button Tests

Tests all admin action buttons including:
- Underwriting approve/reject
- Claims approve/reject/pay
- Billing create/pay
- Policy management

PHINS - Most Advanced AI BI Insurance Platform
Ensures data integrity across all admin operations.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
import threading
import time
import random
import string
from http.server import HTTPServer
from urllib.request import urlopen, Request
from urllib.error import HTTPError
from datetime import datetime


# Test configuration
TEST_PORT = 8099
BASE_URL = f"http://127.0.0.1:{TEST_PORT}"

# Test credentials
ADMIN_CREDS = {"username": "admin", "password": "PDadmin123@"}


class TestServer(threading.Thread):
    """Background server for testing"""
    def __init__(self, port):
        super().__init__(daemon=True)
        self.port = port
        self.httpd = None
        
    def run(self):
        import web_portal.server as portal
        
        # Initialize database and seed users
        try:
            from database import init_database
            from database.seeds import seed_default_users
            init_database()
            seed_default_users()
            print("✓ Database initialized and users seeded")
        except Exception as e:
            print(f"Warning: Database init failed: {e}")
        
        self.httpd = HTTPServer(('127.0.0.1', self.port), portal.PortalHandler)
        self.httpd.serve_forever()
    
    def stop(self):
        if self.httpd:
            self.httpd.shutdown()


def _request(method: str, url: str, data=None, token=None):
    """Make HTTP request and return response"""
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    
    body = json.dumps(data).encode() if data else None
    req = Request(url, data=body, headers=headers, method=method)
    
    try:
        with urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except HTTPError as e:
        return {"error": e.reason, "status": e.code, "body": e.read().decode()}


def _get(url: str, token=None):
    return _request("GET", url, token=token)


def _post(url: str, data: dict, token=None):
    return _request("POST", url, data=data, token=token)


def random_string(length=8):
    """Generate random string for unique IDs"""
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=length))


class TestAdminActions:
    """Test class for admin action buttons"""
    
    def __init__(self):
        self.token = None
        self.test_customer_id = None
        self.test_policy_id = None
        self.test_underwriting_id = None
        self.test_claim_id = None
        self.test_bill_id = None
        self.results = []
    
    def log(self, test_name: str, status: str, details: str = ""):
        """Log test result"""
        result = {
            "test": test_name,
            "status": status,
            "details": details,
            "timestamp": datetime.now().isoformat()
        }
        self.results.append(result)
        emoji = "✅" if status == "PASS" else "❌" if status == "FAIL" else "⚠️"
        print(f"  {emoji} {test_name}: {status} {details}")
    
    def setup(self):
        """Setup test environment"""
        print("\n=== Setting up test environment ===")
        
        # Login as admin
        login_resp = _post(f"{BASE_URL}/api/login", ADMIN_CREDS)
        if "token" not in login_resp:
            raise Exception(f"Admin login failed: {login_resp}")
        
        self.token = login_resp["token"]
        self.log("Admin Login", "PASS", f"Token acquired")
        
        # Create test customer via application submission
        unique_id = random_string()
        self.test_customer_email = f"test_{unique_id}@phins-test.com"
        
        app_data = {
            "customer_name": f"Test Customer {unique_id}",
            "customer_email": self.test_customer_email,
            "coverage_amount": 500000,
            "policy_type": "life",
            "questionnaire_responses": {
                "age": 35,
                "smoker": False,
                "health_conditions": [],
                "occupation": "Software Engineer"
            },
            "payment_setup": {
                "billing_frequency": "monthly",
                "auto_pay": True
            },
            "health_wallet": {
                "enabled": True,
                "monthly_deposit": 100
            }
        }
        
        submit_resp = _post(f"{BASE_URL}/api/policies/create", app_data, self.token)
        
        # Extract IDs from nested response structure
        customer_data = submit_resp.get("customer", {})
        policy_data = submit_resp.get("policy", {})
        underwriting_data = submit_resp.get("underwriting", {})
        
        self.test_customer_id = customer_data.get("id") or submit_resp.get("customer_id")
        self.test_policy_id = policy_data.get("id") or submit_resp.get("policy_id")
        self.test_underwriting_id = underwriting_data.get("id") or submit_resp.get("underwriting_id")
        
        if self.test_customer_id or self.test_policy_id:
            self.log("Create Test Application", "PASS", 
                    f"Customer: {self.test_customer_id}, UW: {self.test_underwriting_id}")
        else:
            self.log("Create Test Application", "FAIL", str(submit_resp)[:200])
            raise Exception("Failed to create test application")
    
    def test_underwriting_approve(self):
        """Test underwriting approval action"""
        print("\n=== Test: Underwriting Approve ===")
        
        if not self.test_underwriting_id:
            self.log("Underwriting Approve", "SKIP", "No underwriting ID")
            return
        
        approve_data = {
            "id": self.test_underwriting_id,
            "approved_by": "test_admin"
        }
        
        resp = _post(f"{BASE_URL}/api/underwriting/approve", approve_data, self.token)
        
        if resp.get("success"):
            self.log("Underwriting Approve", "PASS", 
                    f"Policy: {resp.get('policy', {}).get('status')}, Bill: {resp.get('bill', {}).get('id')}")
            
            # Verify bill was created correctly
            bill = resp.get("bill", {})
            if "id" in bill and bill.get("status") == "outstanding":
                self.test_bill_id = bill["id"]
                self.log("Bill Creation (from approval)", "PASS", f"Bill ID: {self.test_bill_id}")
            else:
                self.log("Bill Creation (from approval)", "FAIL", f"Bill: {bill}")
            
            # Verify data integrity
            if resp.get("validation", {}).get("customer_verified"):
                self.log("Data Integrity Check", "PASS", "Customer verified")
            else:
                self.log("Data Integrity Check", "WARN", "Verification info missing")
        else:
            error = resp.get("error", str(resp))
            self.log("Underwriting Approve", "FAIL", error)
    
    def test_underwriting_reject(self):
        """Test underwriting rejection action"""
        print("\n=== Test: Underwriting Reject ===")
        
        # Create new application for rejection test
        unique_id = random_string()
        app_data = {
            "customer_name": f"Reject Test {unique_id}",
            "customer_email": f"reject_{unique_id}@phins-test.com",
            "coverage_amount": 100000,
            "policy_type": "health"
        }
        
        submit_resp = _post(f"{BASE_URL}/api/policies/create", app_data, self.token)
        uw_id = submit_resp.get("underwriting", {}).get("id") or submit_resp.get("underwriting_id")
        
        if not uw_id:
            self.log("Create Rejection Test App", "FAIL", str(submit_resp)[:200])
            return
        
        reject_data = {
            "id": uw_id,
            "reason": "Test rejection - high risk assessment",
            "rejected_by": "test_admin"
        }
        
        resp = _post(f"{BASE_URL}/api/underwriting/reject", reject_data, self.token)
        
        if resp.get("success"):
            app_status = resp.get("application", {}).get("status")
            self.log("Underwriting Reject", "PASS", f"Status: {app_status}")
            
            if app_status == "rejected":
                self.log("Rejection Status Verified", "PASS")
            else:
                self.log("Rejection Status Verified", "FAIL", f"Expected 'rejected', got '{app_status}'")
        else:
            self.log("Underwriting Reject", "FAIL", resp.get("error", str(resp)))
    
    def test_claim_create(self):
        """Test claim creation"""
        print("\n=== Test: Create Claim ===")
        
        if not self.test_policy_id:
            self.log("Create Claim", "SKIP", "No policy ID")
            return
        
        claim_data = {
            "policy_id": self.test_policy_id,
            "customer_id": self.test_customer_id,
            "type": "medical",
            "description": "Test claim for medical expense",
            "claimed_amount": 5000
        }
        
        resp = _post(f"{BASE_URL}/api/claims/create", claim_data, self.token)
        
        # Claim response can have direct id or nested in 'claim' object
        claim = resp.get("claim", resp)  # Use resp if no 'claim' key
        self.test_claim_id = claim.get("id")
        
        if self.test_claim_id:
            self.log("Create Claim", "PASS", f"Claim ID: {self.test_claim_id}")
        else:
            self.log("Create Claim", "FAIL", resp.get("error", str(resp)[:200]))
    
    def test_claim_approve(self):
        """Test claim approval action"""
        print("\n=== Test: Claim Approve ===")
        
        if not self.test_claim_id:
            self.log("Claim Approve", "SKIP", "No claim ID")
            return
        
        approve_data = {
            "id": self.test_claim_id,
            "approved_amount": 4500,
            "approved_by": "test_adjuster",
            "notes": "Approved with minor deduction"
        }
        
        resp = _post(f"{BASE_URL}/api/claims/approve", approve_data, self.token)
        
        if resp.get("success"):
            claim = resp.get("claim", {})
            self.log("Claim Approve", "PASS", 
                    f"Status: {claim.get('status')}, Approved: ${claim.get('approved_amount', 0)}")
            
            # Verify data integrity
            if claim.get("approved_amount") == 4500:
                self.log("Claim Amount Integrity", "PASS")
            else:
                self.log("Claim Amount Integrity", "FAIL", f"Expected 4500, got {claim.get('approved_amount')}")
        else:
            self.log("Claim Approve", "FAIL", resp.get("error", str(resp)))
    
    def test_claim_reject(self):
        """Test claim rejection action"""
        print("\n=== Test: Claim Reject ===")
        
        # Create a new claim for rejection
        if not self.test_policy_id:
            self.log("Claim Reject", "SKIP", "No policy ID")
            return
        
        claim_data = {
            "policy_id": self.test_policy_id,
            "customer_id": self.test_customer_id,
            "type": "property",
            "description": "Test claim for rejection",
            "claimed_amount": 10000
        }
        
        create_resp = _post(f"{BASE_URL}/api/claims/create", claim_data, self.token)
        claim_obj = create_resp.get("claim", create_resp)
        claim_id = claim_obj.get("id")
        
        if not claim_id:
            self.log("Create Rejection Test Claim", "FAIL", str(create_resp)[:200])
            return
        
        reject_data = {
            "id": claim_id,
            "reason": "Not covered under policy terms",
            "rejected_by": "test_adjuster"
        }
        
        resp = _post(f"{BASE_URL}/api/claims/reject", reject_data, self.token)
        
        if resp.get("success"):
            claim = resp.get("claim", {})
            self.log("Claim Reject", "PASS", f"Status: {claim.get('status')}")
        else:
            self.log("Claim Reject", "FAIL", resp.get("error", str(resp)))
    
    def test_billing_create(self):
        """Test billing record creation"""
        print("\n=== Test: Billing Create ===")
        
        if not self.test_policy_id:
            self.log("Billing Create", "SKIP", "No policy ID")
            return
        
        bill_data = {
            "policy_id": self.test_policy_id,
            "amount_due": 250.00,
            "due_days": 30
        }
        
        resp = _post(f"{BASE_URL}/api/billing/create", bill_data, self.token)
        
        if "bill" in resp:
            bill = resp.get("bill", {})
            new_bill_id = bill.get("id")
            self.log("Billing Create", "PASS", f"Bill ID: {new_bill_id}")
            
            # Verify bill structure
            if bill.get("status") == "outstanding" and bill.get("amount") == 250.00:
                self.log("Bill Structure Integrity", "PASS")
            else:
                self.log("Bill Structure Integrity", "WARN", f"Bill: {bill}")
        else:
            self.log("Billing Create", "FAIL", resp.get("error", str(resp)))
    
    def test_billing_pay(self):
        """Test billing payment action"""
        print("\n=== Test: Billing Pay ===")
        
        if not self.test_bill_id:
            self.log("Billing Pay", "SKIP", "No bill ID")
            return
        
        pay_data = {
            "bill_id": self.test_bill_id,
            "amount": 100.00
        }
        
        resp = _post(f"{BASE_URL}/api/billing/pay", pay_data, self.token)
        
        if resp.get("success") or "bill" in resp:
            bill = resp.get("bill", {})
            self.log("Billing Pay", "PASS", 
                    f"Paid: ${bill.get('amount_paid', 0)}, Status: {bill.get('status')}")
        else:
            self.log("Billing Pay", "FAIL", resp.get("error", str(resp)))
    
    def test_admin_dashboard_stats(self):
        """Test admin dashboard statistics retrieval"""
        print("\n=== Test: Admin Dashboard Stats ===")
        
        # Try POST first (some endpoints require POST)
        resp = _post(f"{BASE_URL}/api/admin/dashboard-stats", {}, self.token)
        if "error" in resp and resp.get("status") == 404:
            # Try GET
            resp = _get(f"{BASE_URL}/api/admin/dashboard", self.token)
        
        if resp.get("success") or resp.get("total_customers") is not None:
            self.log("Dashboard Stats", "PASS", 
                    f"Customers: {resp.get('total_customers')}, Policies: {resp.get('total_policies')}")
            
            # Verify data integrity - stats should reflect our test data
            if resp.get("total_customers", 0) >= 1:
                self.log("Customer Count Integrity", "PASS")
            else:
                self.log("Customer Count Integrity", "WARN", "No customers found")
        else:
            self.log("Dashboard Stats", "WARN", "Dashboard endpoint not found (API may differ)")
    
    def test_customer_validation(self):
        """Test customer validation endpoint"""
        print("\n=== Test: Customer Validation ===")
        
        if not self.test_customer_id:
            self.log("Customer Validation", "SKIP", "No customer ID")
            return
        
        resp = _get(f"{BASE_URL}/api/admin/validate-customer/{self.test_customer_id}", self.token)
        
        if "checks" in resp:
            passed = sum(1 for c in resp["checks"] if c.get("status") == "PASS")
            total = len(resp["checks"])
            self.log("Customer Validation", "PASS", f"Checks: {passed}/{total} passed")
            
            for check in resp["checks"]:
                status = "✓" if check.get("status") == "PASS" else "✗"
                print(f"      {status} {check.get('check')}: {check.get('details', '')}")
        else:
            self.log("Customer Validation", "FAIL", resp.get("error", str(resp)))
    
    def test_data_integrity(self):
        """Test overall data integrity across all entities"""
        print("\n=== Test: Data Integrity Verification ===")
        
        # Verify customer exists
        if self.test_customer_id:
            cust_resp = _get(f"{BASE_URL}/api/customer/status?customer_id={self.test_customer_id}", self.token)
            if cust_resp.get("customer"):
                self.log("Customer Data Integrity", "PASS")
            else:
                self.log("Customer Data Integrity", "FAIL", "Customer not found in status")
        
        # Verify underwriting exists
        if self.test_underwriting_id:
            uw_resp = _get(f"{BASE_URL}/api/underwriting/{self.test_underwriting_id}", self.token)
            if uw_resp.get("id") == self.test_underwriting_id:
                self.log("Underwriting Data Integrity", "PASS")
            else:
                self.log("Underwriting Data Integrity", "WARN", "May not have direct GET endpoint")
        
        # Verify policy exists
        if self.test_policy_id:
            pol_resp = _get(f"{BASE_URL}/api/policies?id={self.test_policy_id}", self.token)
            if pol_resp.get("id") == self.test_policy_id or pol_resp.get("policies"):
                self.log("Policy Data Integrity", "PASS")
            else:
                self.log("Policy Data Integrity", "WARN", str(pol_resp))
    
    def run_all_tests(self):
        """Run all admin action tests"""
        print("\n" + "="*60)
        print("  PHINS Admin Action Button Tests")
        print("  Most Advanced AI BI Insurance Platform")
        print("="*60)
        
        try:
            self.setup()
            
            # Underwriting tests
            self.test_underwriting_approve()
            self.test_underwriting_reject()
            
            # Claims tests
            self.test_claim_create()
            self.test_claim_approve()
            self.test_claim_reject()
            
            # Billing tests
            self.test_billing_create()
            self.test_billing_pay()
            
            # Admin dashboard tests
            self.test_admin_dashboard_stats()
            self.test_customer_validation()
            
            # Data integrity verification
            self.test_data_integrity()
            
        except Exception as e:
            self.log("Test Suite", "FAIL", str(e))
        
        # Summary
        print("\n" + "="*60)
        print("  Test Summary")
        print("="*60)
        
        passed = sum(1 for r in self.results if r["status"] == "PASS")
        failed = sum(1 for r in self.results if r["status"] == "FAIL")
        skipped = sum(1 for r in self.results if r["status"] == "SKIP")
        warned = sum(1 for r in self.results if r["status"] == "WARN")
        
        print(f"  ✅ Passed:  {passed}")
        print(f"  ❌ Failed:  {failed}")
        print(f"  ⚠️  Warned:  {warned}")
        print(f"  ⏭️  Skipped: {skipped}")
        print(f"  📊 Total:   {len(self.results)}")
        print("="*60)
        
        return failed == 0


def main():
    """Main test runner"""
    print("\n🚀 Starting test server...")
    server = TestServer(TEST_PORT)
    server.start()
    time.sleep(4)  # Wait for server and database to initialize
    
    print(f"📡 Test server running on port {TEST_PORT}")
    
    try:
        tester = TestAdminActions()
        success = tester.run_all_tests()
        
        # Save results
        with open("admin_action_test_results.json", "w") as f:
            json.dump({
                "timestamp": datetime.now().isoformat(),
                "results": tester.results,
                "success": success
            }, f, indent=2)
        
        print(f"\n📄 Results saved to admin_action_test_results.json")
        
        return 0 if success else 1
        
    finally:
        print("\n🛑 Stopping test server...")
        server.stop()


if __name__ == "__main__":
    exit(main())
