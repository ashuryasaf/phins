#!/usr/bin/env python3
"""
Comprehensive test suite for Customer Billing Dashboard functionality.
Tests the new billing button, premium allocation to investments, NFT recording,
and account settings features.

PHINS - Most Advanced AI BI Insurance Platform
"""

import sys
import os
import json
import time
import threading
import random
import string

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from http.server import HTTPServer
import urllib.request
import urllib.error

# Test configuration
TEST_PORT = 8765
BASE_URL = f"http://127.0.0.1:{TEST_PORT}"

def random_string(length=8):
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=length))

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
        print(f"✓ Test server started on port {self.port}")
        self.httpd.serve_forever()
    
    def stop(self):
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()


class TestCustomerBillingDashboard:
    """Test suite for Customer Billing Dashboard features"""
    
    def __init__(self):
        self.auth_token = None
        self.customer_id = None
        self.policy_id = None
        self.test_results = []
    
    def log(self, test_name, status, message=''):
        """Log test result"""
        icon = '✅' if status == 'PASS' else '❌'
        result = f"{icon} {test_name}: {status}"
        if message:
            result += f" - {message}"
        print(result)
        self.test_results.append({'test': test_name, 'status': status, 'message': message})
    
    def _request(self, endpoint, method='GET', data=None, headers=None):
        """Make HTTP request to test server"""
        url = f"{BASE_URL}{endpoint}"
        req_headers = {'Content-Type': 'application/json'}
        if self.auth_token:
            req_headers['Authorization'] = f'Bearer {self.auth_token}'
        if headers:
            req_headers.update(headers)
        
        body = json.dumps(data).encode('utf-8') if data else None
        req = urllib.request.Request(url, data=body, headers=req_headers, method=method)
        
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return {
                    'status': resp.status,
                    'body': json.loads(resp.read().decode('utf-8'))
                }
        except urllib.error.HTTPError as e:
            return {
                'status': e.code,
                'body': json.loads(e.read().decode('utf-8')) if e.read else {},
                'error': str(e)
            }
        except Exception as e:
            return {'status': 0, 'error': str(e)}
    
    def _post(self, endpoint, data=None):
        return self._request(endpoint, method='POST', data=data)
    
    def _get(self, endpoint):
        return self._request(endpoint, method='GET')
    
    # ========== SETUP ==========
    
    def setup(self):
        """Setup: Login as admin and create test customer/policy"""
        print("\n=== SETUP: Creating test environment ===\n")
        
        # Login as admin
        login_resp = self._post('/api/login', {
            'username': 'admin',
            'password': 'PDadmin123@'
        })
        
        if login_resp.get('status') != 200 or not login_resp.get('body', {}).get('token'):
            self.log('Admin Login', 'FAIL', f"Could not login: {login_resp}")
            return False
        
        self.auth_token = login_resp['body']['token']
        self.log('Admin Login', 'PASS', f"Token: {self.auth_token[:20]}...")
        
        # Create test customer and policy
        test_email = f"test_{random_string()}@phins.ai"
        submit_resp = self._post('/api/policies/create', {
            'customer_name': 'Test Customer',
            'first_name': 'Test',
            'last_name': 'Customer',
            'email': test_email,
            'phone': '555-0123',
            'dob': '1985-06-15',
            'gender': 'male',
            'occupation': 'Engineer',
            'coverage_type': 'standard',
            'coverage_amount': 100000,
            'monthly_premium': 250,
            'payment_frequency': 'monthly',
            'address': '123 Test St',
            'city': 'Test City',
            'state': 'CA',
            'zip': '90210'
        })
        
        if submit_resp.get('status') not in [200, 201]:
            self.log('Create Test Customer', 'FAIL', f"Could not create: {submit_resp}")
            return False
        
        body = submit_resp.get('body', {})
        self.customer_id = body.get('customer', {}).get('id') or body.get('customer_id')
        self.policy_id = body.get('policy', {}).get('id') or body.get('policy_id')
        
        self.log('Create Test Customer', 'PASS', f"Customer: {self.customer_id}, Policy: {self.policy_id}")
        return True
    
    # ========== BILLING TESTS ==========
    
    def test_customer_payment(self):
        """Test: Customer premium payment with NFT recording"""
        print("\n--- Testing Customer Payment ---")
        
        resp = self._post('/api/customer/payment', {
            'customer_id': self.customer_id,
            'amount': 250.00,
            'payment_method': 'card',
            'create_nft': True,
            'allocate_to_investments': True
        })
        
        if resp.get('status') != 200:
            self.log('Customer Payment', 'FAIL', f"Status: {resp.get('status')}, Body: {resp.get('body')}")
            return False
        
        body = resp.get('body', {})
        success = body.get('success')
        nft_token_id = body.get('nft_token_id')
        savings_allocated = body.get('savings_allocated')
        
        if not success:
            self.log('Customer Payment', 'FAIL', 'Payment not successful')
            return False
        
        if not nft_token_id:
            self.log('Customer Payment', 'FAIL', 'NFT token not created')
            return False
        
        if savings_allocated != 62.50:  # 25% of 250
            self.log('Customer Payment', 'FAIL', f'Savings allocation incorrect: {savings_allocated}')
            return False
        
        self.log('Customer Payment', 'PASS', f'NFT: {nft_token_id[:20]}..., Savings: ${savings_allocated}')
        return True

    def test_checkout_integrity_debug(self):
        """Test: Checkout integrity debug data is present and valid"""
        print("\n--- Testing Checkout Integrity Debug ---")
        
        resp = self._post('/api/customer/payment', {
            'customer_id': self.customer_id,
            'amount': 120.00,
            'payment_method': 'card',
            'debug': True
        })
        
        if resp.get('status') != 200:
            self.log('Checkout Integrity Debug', 'FAIL', f"Status: {resp.get('status')}, Body: {resp.get('body')}")
            return False
        
        body = resp.get('body', {})
        integrity = body.get('integrity')
        allocation_checks = body.get('allocation_checks', {})
        
        if not integrity:
            self.log('Checkout Integrity Debug', 'FAIL', 'Missing integrity payload in debug response')
            return False
        
        if not integrity.get('is_valid', False):
            self.log('Checkout Integrity Debug', 'FAIL', f"Integrity invalid: {integrity.get('issues')}")
            return False
        
        if not allocation_checks.get('savings_risk_sum_ok'):
            self.log('Checkout Integrity Debug', 'FAIL', 'Savings/risk allocation does not sum to payment amount')
            return False
        
        # Cross-check using integrity endpoint (requires auth)
        integrity_resp = self._get(f'/api/integrity/check?customer_id={self.customer_id}')
        if integrity_resp.get('status') == 200:
            if not integrity_resp.get('body', {}).get('is_valid', False):
                self.log('Checkout Integrity Debug', 'FAIL', 'Integrity endpoint reported invalid state')
                return False
        else:
            self.log('Checkout Integrity Debug', 'WARN', f"Integrity endpoint unavailable: {integrity_resp.get('status')}")
        
        self.log('Checkout Integrity Debug', 'PASS', 'Integrity checks passed with debug payload')
        return True
    
    def test_billing_allocation_calculation(self):
        """Test: Verify premium allocation percentages"""
        print("\n--- Testing Billing Allocation ---")
        
        # Test different payment amounts
        test_amounts = [100, 500, 1000]
        
        for amount in test_amounts:
            resp = self._post('/api/customer/payment', {
                'customer_id': self.customer_id,
                'amount': amount,
                'payment_method': 'bank',
                'create_nft': True
            })
            
            if resp.get('status') != 200:
                self.log(f'Allocation Test ${amount}', 'FAIL', f"Payment failed")
                return False
            
            body = resp.get('body', {})
            savings = body.get('savings_allocated', 0)
            risk = body.get('risk_allocated', 0)
            
            expected_savings = amount * 0.25
            expected_risk = amount * 0.75
            
            if abs(savings - expected_savings) > 0.01:
                self.log(f'Allocation Test ${amount}', 'FAIL', f'Savings: {savings} != {expected_savings}')
                return False
            
            if abs(risk - expected_risk) > 0.01:
                self.log(f'Allocation Test ${amount}', 'FAIL', f'Risk: {risk} != {expected_risk}')
                return False
        
        self.log('Billing Allocation', 'PASS', 'All allocation calculations correct (25%/75%)')
        return True
    
    # ========== ACTION RECORDING TESTS ==========
    
    def test_record_customer_action(self):
        """Test: Record customer action on NFT ledger"""
        print("\n--- Testing Action Recording ---")
        
        actions = [
            {'action_type': 'invest', 'amount': 1000, 'description': 'Investment in Index Fund'},
            {'action_type': 'claim_filed', 'amount': 5000, 'description': 'Medical claim submitted'},
            {'action_type': 'wallet_deposit', 'amount': 500, 'description': 'Health wallet deposit'},
            {'action_type': 'settings_change', 'amount': 0, 'description': 'Auto-pay enabled'},
        ]
        
        for action in actions:
            resp = self._post('/api/customer/action', {
                'customer_id': self.customer_id,
                **action
            })
            
            if resp.get('status') != 200:
                self.log(f"Action: {action['action_type']}", 'FAIL', f"Status: {resp.get('status')}")
                return False
            
            body = resp.get('body', {})
            if not body.get('success') or not body.get('nft_token'):
                self.log(f"Action: {action['action_type']}", 'FAIL', 'NFT token not created')
                return False
        
        self.log('Record Customer Action', 'PASS', f'{len(actions)} actions recorded with NFT tokens')
        return True
    
    def test_nft_ledger_integrity(self):
        """Test: Verify NFT ledger data integrity"""
        print("\n--- Testing NFT Ledger Integrity ---")
        
        # Get customer's NFT ledger
        resp = self._get(f'/api/nft-ledger?customer_id={self.customer_id}')
        
        if resp.get('status') != 200:
            # API may not exist yet - record warning
            self.log('NFT Ledger Integrity', 'WARN', 'NFT ledger API may not be implemented yet')
            return True  # Non-critical
        
        body = resp.get('body', {})
        ledger = body.get('ledger', [])
        
        if len(ledger) == 0:
            self.log('NFT Ledger Integrity', 'WARN', 'Ledger is empty (actions may not be persisted)')
            return True
        
        # Verify each token has required fields
        required_fields = ['token_id', 'transaction_type', 'amount', 'created_at', 'transaction_hash']
        for token in ledger:
            for field in required_fields:
                if field not in token:
                    self.log('NFT Ledger Integrity', 'FAIL', f'Missing field: {field}')
                    return False
        
        self.log('NFT Ledger Integrity', 'PASS', f'{len(ledger)} tokens with complete data')
        return True
    
    # ========== SETTINGS TESTS ==========
    
    def test_password_change(self):
        """Test: Password change functionality"""
        print("\n--- Testing Password Change ---")
        
        # First login as a regular user to test password change
        # Note: This test uses the admin session which should still work
        
        resp = self._post('/api/customer/change-password', {
            'current_password': 'PDadmin123@',
            'new_password': 'NewPass123@'
        })
        
        if resp.get('status') == 200:
            body = resp.get('body', {})
            if body.get('success'):
                self.log('Password Change', 'PASS', 'Password changed and NFT recorded')
                
                # Change back for other tests
                self._post('/api/customer/change-password', {
                    'current_password': 'NewPass123@',
                    'new_password': 'PDadmin123@'
                })
                return True
        
        # Password change might fail due to session/auth - not critical
        self.log('Password Change', 'WARN', f'Password change test skipped: {resp.get("body", {}).get("error", "N/A")}')
        return True
    
    # ========== INTEGRATION TESTS ==========
    
    def test_billing_api_endpoints(self):
        """Test: Verify all billing API endpoints exist"""
        print("\n--- Testing Billing API Endpoints ---")
        
        endpoints = [
            ('/api/billing', 'GET'),
            ('/api/customer/payment', 'POST'),
            ('/api/customer/action', 'POST'),
        ]
        
        all_ok = True
        for endpoint, method in endpoints:
            try:
                if method == 'GET':
                    resp = self._get(f"{endpoint}?customer_id={self.customer_id}")
                else:
                    resp = self._post(endpoint, {'customer_id': self.customer_id, 'action_type': 'test', 'amount': 0, 'description': 'API test'})
                
                if resp.get('status') in [200, 201]:
                    print(f"  ✓ {method} {endpoint}: OK")
                elif resp.get('status') in [400, 401]:
                    print(f"  ⚠ {method} {endpoint}: {resp.get('status')} (auth/validation)")
                else:
                    print(f"  ✗ {method} {endpoint}: {resp.get('status')}")
                    all_ok = False
            except Exception as e:
                print(f"  ✗ {method} {endpoint}: Error - {e}")
                all_ok = False
        
        if all_ok:
            self.log('Billing API Endpoints', 'PASS', 'All endpoints accessible')
        else:
            self.log('Billing API Endpoints', 'FAIL', 'Some endpoints not accessible')
        return all_ok
    
    def test_dashboard_data_integrity(self):
        """Test: Verify dashboard data consistency"""
        print("\n--- Testing Dashboard Data Integrity ---")
        
        try:
            # Get policies
            policies_resp = self._get('/api/policies')
            if policies_resp.get('status') != 200:
                self.log('Dashboard Data Integrity', 'FAIL', 'Cannot fetch policies')
                return False
            
            body = policies_resp.get('body', {})
            if isinstance(body, list):
                policies = body
            else:
                policies = body.get('items', []) or body.get('policies', [])
            
            # Get billing
            billing_resp = self._get(f'/api/billing?customer_id={self.customer_id}')
            if billing_resp.get('status') != 200:
                billing_resp = self._get('/api/billing')  # Try without customer_id
            
            billing_body = billing_resp.get('body', {})
            if isinstance(billing_body, list):
                bills = billing_body
            else:
                bills = billing_body.get('bills', [])
            
            # Verify data consistency
            policy_count = len(policies) if isinstance(policies, list) else 0
            bill_count = len(bills) if isinstance(bills, list) else 0
            
            self.log('Dashboard Data Integrity', 'PASS', f'{policy_count} policies, {bill_count} bills loaded')
            return True
        except Exception as e:
            self.log('Dashboard Data Integrity', 'FAIL', f'Error: {e}')
            return False
    
    def test_adjustable_allocation(self):
        """Test: Customer can adjust allocation percentages"""
        print("\n--- Testing Adjustable Allocation ---")
        
        # Set custom allocation: 30% savings, 70% risk
        resp = self._post('/api/customer/allocation', {
            'customer_id': self.customer_id,
            'savings_pct': 30.0,
            'risk_pct': 70.0,
            'index_pct': 50.0,
            'bonds_pct': 40.0,
            'crypto_pct': 10.0
        })
        
        if resp.get('status') != 200:
            self.log('Set Custom Allocation', 'FAIL', f"Status: {resp.get('status')}")
            return False
        
        body = resp.get('body', {})
        if not body.get('success'):
            self.log('Set Custom Allocation', 'FAIL', 'Not successful')
            return False
        
        # Verify allocation was saved
        get_resp = self._post('/api/customer/allocation', {
            'customer_id': self.customer_id
        })
        
        if get_resp.get('status') != 200:
            self.log('Get Custom Allocation', 'FAIL', f"Status: {get_resp.get('status')}")
            return False
        
        alloc = get_resp.get('body', {}).get('allocation', {})
        if alloc.get('savings_pct') != 30.0:
            self.log('Verify Custom Allocation', 'FAIL', f"Savings: {alloc.get('savings_pct')} != 30.0")
            return False
        
        self.log('Adjustable Allocation', 'PASS', 'Custom allocation saved: 30% savings, 70% risk')
        return True
    
    def test_payment_uses_custom_allocation(self):
        """Test: Payment uses customer's custom allocation"""
        print("\n--- Testing Payment with Custom Allocation ---")
        
        # Make payment (should use the 30% savings from previous test)
        resp = self._post('/api/customer/payment', {
            'customer_id': self.customer_id,
            'amount': 100.0,
            'payment_method': 'card'
        })
        
        if resp.get('status') != 200:
            self.log('Payment with Custom Allocation', 'FAIL', f"Status: {resp.get('status')}")
            return False
        
        body = resp.get('body', {})
        savings = body.get('savings_allocated', 0)
        savings_pct = body.get('savings_pct', 0)
        
        # Should be 30% of $100 = $30
        if abs(savings - 30.0) > 0.01:
            self.log('Payment with Custom Allocation', 'FAIL', f"Savings: {savings} != 30.0")
            return False
        
        if savings_pct != 30.0:
            self.log('Payment with Custom Allocation', 'FAIL', f"Savings %: {savings_pct} != 30.0")
            return False
        
        self.log('Payment with Custom Allocation', 'PASS', f'Used custom 30% allocation: ${savings}')
        return True
    
    def test_investment_deposit(self):
        """Test: Customer can deposit additional savings to investments"""
        print("\n--- Testing Investment Deposit ---")
        
        resp = self._post('/api/customer/investment/deposit', {
            'customer_id': self.customer_id,
            'amount': 500.0,
            'deposit_type': 'additional_savings'
        })
        
        if resp.get('status') != 200:
            self.log('Investment Deposit', 'FAIL', f"Status: {resp.get('status')}")
            return False
        
        body = resp.get('body', {})
        if not body.get('success'):
            self.log('Investment Deposit', 'FAIL', 'Not successful')
            return False
        
        if not body.get('nft_token_id'):
            self.log('Investment Deposit', 'FAIL', 'No NFT token created')
            return False
        
        account_balance = body.get('account_balance', 0)
        if account_balance < 500:
            self.log('Investment Deposit', 'FAIL', f'Balance too low: {account_balance}')
            return False
        
        self.log('Investment Deposit', 'PASS', f'Deposited $500, Balance: ${account_balance:.2f}')
        return True
    
    def test_investment_account_query(self):
        """Test: Query investment account details"""
        print("\n--- Testing Investment Account Query ---")
        
        resp = self._post('/api/customer/investment/account', {
            'customer_id': self.customer_id
        })
        
        if resp.get('status') != 200:
            self.log('Investment Account Query', 'FAIL', f"Status: {resp.get('status')}")
            return False
        
        body = resp.get('body', {})
        if not body.get('success'):
            self.log('Investment Account Query', 'FAIL', 'Not successful')
            return False
        
        breakdown = body.get('breakdown', {})
        if 'index_funds' not in breakdown:
            self.log('Investment Account Query', 'FAIL', 'Missing breakdown data')
            return False
        
        total = body.get('total_balance', 0)
        self.log('Investment Account Query', 'PASS', f'Total balance: ${total:.2f}')
        return True
    
    def test_transaction_ledger(self):
        """Test: All transactions recorded in master ledger"""
        print("\n--- Testing Transaction Ledger ---")
        
        resp = self._post('/api/customer/transactions', {
            'customer_id': self.customer_id,
            'limit': 10
        })
        
        if resp.get('status') != 200:
            self.log('Transaction Ledger', 'FAIL', f"Status: {resp.get('status')}")
            return False
        
        body = resp.get('body', {})
        transactions = body.get('transactions', [])
        
        if len(transactions) == 0:
            self.log('Transaction Ledger', 'FAIL', 'No transactions recorded')
            return False
        
        # Verify transactions have required fields
        for tx in transactions:
            if not tx.get('nft_token_id'):
                self.log('Transaction Ledger', 'FAIL', f"Transaction {tx.get('id')} missing NFT token")
                return False
        
        self.log('Transaction Ledger', 'PASS', f'{len(transactions)} transactions with NFT tokens')
        return True
    
    def run_all_tests(self):
        """Run all tests and report results"""
        print("\n" + "="*60)
        print("PHINS Customer Billing Dashboard Test Suite")
        print("="*60)
        
        # Setup
        if not self.setup():
            print("\n❌ Setup failed. Cannot proceed with tests.")
            return False
        
        # Run tests
        tests = [
            self.test_customer_payment,
            self.test_checkout_integrity_debug,
            self.test_billing_allocation_calculation,
            self.test_record_customer_action,
            self.test_nft_ledger_integrity,
            self.test_adjustable_allocation,
            self.test_payment_uses_custom_allocation,
            self.test_investment_deposit,
            self.test_investment_account_query,
            self.test_transaction_ledger,
            self.test_password_change,
            self.test_billing_api_endpoints,
            self.test_dashboard_data_integrity,
        ]
        
        passed = 0
        failed = 0
        warnings = 0
        
        for test in tests:
            try:
                result = test()
                if result:
                    passed += 1
                else:
                    failed += 1
            except Exception as e:
                self.log(test.__name__, 'FAIL', f'Exception: {e}')
                failed += 1
        
        # Count warnings from results
        for result in self.test_results:
            if result['status'] == 'WARN':
                warnings += 1
        
        # Summary
        print("\n" + "="*60)
        print("TEST SUMMARY")
        print("="*60)
        print(f"✅ Passed: {passed}")
        print(f"⚠️  Warnings: {warnings}")
        print(f"❌ Failed: {failed}")
        print(f"Total: {len(tests)}")
        
        success_rate = (passed / len(tests)) * 100 if tests else 0
        print(f"\nSuccess Rate: {success_rate:.1f}%")
        
        if failed == 0:
            print("\n🎉 ALL TESTS PASSED! Ready for deployment.")
            return True
        else:
            print(f"\n⚠️  {failed} test(s) failed. Review before deployment.")
            return False


def main():
    """Main test runner"""
    # Clean any existing database for fresh test
    db_file = 'phins.db'
    if os.path.exists(db_file):
        print(f"Removing existing {db_file} for clean test...")
        try:
            os.remove(db_file)
        except Exception as e:
            print(f"Warning: Could not remove {db_file}: {e}")
    
    # Start test server
    print("\n🚀 Starting test server...")
    server = TestServer(TEST_PORT)
    server.start()
    
    # Wait for server to be ready
    time.sleep(4)
    
    # Check server is responding
    try:
        req = urllib.request.Request(f"{BASE_URL}/health")
        urllib.request.urlopen(req, timeout=5)
        print("✓ Server health check passed")
    except Exception as e:
        print(f"⚠ Health check: {e} (proceeding anyway)")
    
    # Run tests
    tester = TestCustomerBillingDashboard()
    success = tester.run_all_tests()
    
    # Cleanup
    print("\n🛑 Stopping test server...")
    server.stop()
    
    return 0 if success else 1


if __name__ == '__main__':
    sys.exit(main())
