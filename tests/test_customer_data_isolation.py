#!/usr/bin/env python3
"""
Test suite for Customer Data Isolation
======================================
Tests that customer CUST-TEST-100 (Sara Cohen) can ONLY access their own data
and is denied access to all other customer data.

Security Requirement:
- Standard customers (role='customer') can ONLY access their own data
- Admin/staff roles can access any customer's data
- All unauthorized access attempts should be logged and denied
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import unittest
from datetime import datetime


class TestCustomerDataIsolation(unittest.TestCase):
    """Test customer data isolation enforcement"""
    
    # Test customer: Sara Cohen
    SARA_CUSTOMER_ID = 'CUST-TEST-100'
    
    # Other customers that Sara should NOT be able to access
    OTHER_CUSTOMER_IDS = ['CUST001', 'CUST002', 'CUST003', 'CUST-OTHER-123']
    
    def setUp(self):
        """Set up test fixtures"""
        # Import the authorization function
        try:
            # Try to import from web_portal if available
            sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'web_portal'))
            from server import authorize_customer_data
            self.authorize_customer_data = authorize_customer_data
        except ImportError:
            # Create a local version for testing
            from services.customer_data_access import CustomerDataAccessService
            self.access_service = CustomerDataAccessService()
            self.authorize_customer_data = self._authorize_wrapper
    
    def _authorize_wrapper(self, session, requested_customer_id, resource_type='data'):
        """Wrapper for CustomerDataAccessService"""
        return self.access_service.authorize_customer_access(session, requested_customer_id, resource_type)
    
    def test_sara_can_access_own_data(self):
        """Test that Sara Cohen (CUST-TEST-100) can access her own data"""
        session = {
            'username': 'sara_cohen',
            'role': 'customer',
            'customer_id': self.SARA_CUSTOMER_ID
        }
        
        # Test accessing own data with explicit customer_id
        authorized, customer_id, error = self.authorize_customer_data(
            session, self.SARA_CUSTOMER_ID, 'savings'
        )
        
        self.assertTrue(authorized, f"Sara should be able to access her own data. Error: {error}")
        self.assertEqual(customer_id, self.SARA_CUSTOMER_ID)
        self.assertIsNone(error)
        
        print(f"✓ Sara Cohen can access her own savings data ({self.SARA_CUSTOMER_ID})")
    
    def test_sara_gets_own_id_when_no_id_requested(self):
        """Test that Sara gets her own customer_id when no specific ID is requested"""
        session = {
            'username': 'sara_cohen',
            'role': 'customer',
            'customer_id': self.SARA_CUSTOMER_ID
        }
        
        # Test accessing without specifying customer_id
        authorized, customer_id, error = self.authorize_customer_data(
            session, None, 'policies'
        )
        
        self.assertTrue(authorized, "Sara should be authorized when no customer_id specified")
        self.assertEqual(customer_id, self.SARA_CUSTOMER_ID, "Should default to Sara's own customer_id")
        self.assertIsNone(error)
        
        print(f"✓ Sara Cohen gets her own ID when no customer_id specified")
    
    def test_sara_denied_access_to_other_customers(self):
        """Test that Sara Cohen is DENIED access to other customers' data"""
        session = {
            'username': 'sara_cohen',
            'role': 'customer',
            'customer_id': self.SARA_CUSTOMER_ID
        }
        
        for other_id in self.OTHER_CUSTOMER_IDS:
            authorized, customer_id, error = self.authorize_customer_data(
                session, other_id, 'savings'
            )
            
            self.assertFalse(authorized, 
                f"Sara should NOT be able to access {other_id}'s data")
            self.assertIsNone(customer_id, 
                f"customer_id should be None when access is denied for {other_id}")
            self.assertIsNotNone(error, 
                f"Error message should be provided when denying access to {other_id}")
            self.assertIn('denied', error.lower(), 
                f"Error should indicate access denied for {other_id}")
            
            print(f"✓ Sara Cohen DENIED access to {other_id}'s data")
    
    def test_sara_denied_access_to_other_customer_savings(self):
        """Test Sara is denied access to other customers' savings"""
        session = {
            'username': 'sara_cohen',
            'role': 'customer',
            'customer_id': self.SARA_CUSTOMER_ID
        }
        
        resource_types = ['savings', 'policies', 'claims', 'billing', 'wallet', 'transactions']
        
        for resource_type in resource_types:
            for other_id in self.OTHER_CUSTOMER_IDS[:2]:  # Test with first 2 other customers
                authorized, _, error = self.authorize_customer_data(
                    session, other_id, resource_type
                )
                
                self.assertFalse(authorized, 
                    f"Sara should NOT access {other_id}'s {resource_type}")
                
        print(f"✓ Sara Cohen DENIED access to all resource types for other customers")
    
    def test_admin_can_access_any_customer(self):
        """Test that admin can access any customer's data including Sara's"""
        admin_session = {
            'username': 'admin_user',
            'role': 'admin',
            'customer_id': None
        }
        
        # Admin can access Sara's data
        authorized, customer_id, error = self.authorize_customer_data(
            admin_session, self.SARA_CUSTOMER_ID, 'savings'
        )
        
        self.assertTrue(authorized, "Admin should access Sara's data")
        self.assertEqual(customer_id, self.SARA_CUSTOMER_ID)
        self.assertIsNone(error)
        
        # Admin can access other customers' data too
        for other_id in self.OTHER_CUSTOMER_IDS:
            authorized, customer_id, error = self.authorize_customer_data(
                admin_session, other_id, 'savings'
            )
            self.assertTrue(authorized, f"Admin should access {other_id}'s data")
            self.assertEqual(customer_id, other_id)
        
        print(f"✓ Admin can access any customer's data (including CUST-TEST-100)")
    
    def test_underwriter_can_access_any_customer(self):
        """Test that underwriter can access customer data for underwriting"""
        underwriter_session = {
            'username': 'underwriter_user',
            'role': 'underwriter',
            'customer_id': None
        }
        
        authorized, customer_id, error = self.authorize_customer_data(
            underwriter_session, self.SARA_CUSTOMER_ID, 'policies'
        )
        
        self.assertTrue(authorized, "Underwriter should access Sara's data")
        self.assertEqual(customer_id, self.SARA_CUSTOMER_ID)
        
        print(f"✓ Underwriter can access customer data for processing")
    
    def test_no_session_denied(self):
        """Test that requests without session are denied"""
        authorized, customer_id, error = self.authorize_customer_data(
            None, self.SARA_CUSTOMER_ID, 'savings'
        )
        
        self.assertFalse(authorized, "No session should be denied")
        self.assertIsNone(customer_id)
        self.assertIn('authentication', error.lower())
        
        print(f"✓ Requests without session are denied")
    
    def test_customer_without_customer_id_denied(self):
        """Test that customer role without customer_id is denied"""
        bad_session = {
            'username': 'bad_customer',
            'role': 'customer',
            'customer_id': None  # No customer_id
        }
        
        authorized, customer_id, error = self.authorize_customer_data(
            bad_session, self.SARA_CUSTOMER_ID, 'savings'
        )
        
        self.assertFalse(authorized, "Customer without customer_id should be denied")
        self.assertIsNone(customer_id)
        self.assertIsNotNone(error)
        
        print(f"✓ Customer session without customer_id is denied")
    
    def test_unknown_role_denied(self):
        """Test that unknown roles are denied"""
        bad_session = {
            'username': 'unknown_user',
            'role': 'hacker',  # Invalid role
            'customer_id': 'CUST-FAKE-001'
        }
        
        authorized, customer_id, error = self.authorize_customer_data(
            bad_session, self.SARA_CUSTOMER_ID, 'savings'
        )
        
        self.assertFalse(authorized, "Unknown role should be denied")
        self.assertIsNone(customer_id)
        
        print(f"✓ Unknown roles are denied access")


class TestCustomerDataAccessService(unittest.TestCase):
    """Test the CustomerDataAccessService class directly"""
    
    def setUp(self):
        """Set up test fixtures"""
        from services.customer_data_access import CustomerDataAccessService
        self.audit_log = []
        self.customers = {
            'CUST-TEST-100': {'id': 'CUST-TEST-100', 'name': 'Sara Cohen'},
            'CUST001': {'id': 'CUST001', 'name': 'John Doe'},
            'CUST002': {'id': 'CUST002', 'name': 'Jane Smith'}
        }
        self.policies = {
            'POL-SARA-001': {'id': 'POL-SARA-001', 'customer_id': 'CUST-TEST-100'},
            'POL-JOHN-001': {'id': 'POL-JOHN-001', 'customer_id': 'CUST001'},
        }
        self.service = CustomerDataAccessService(
            audit_log=self.audit_log,
            customers=self.customers,
            policies=self.policies,
        )
    
    def test_access_violations_logged(self):
        """Test that access violations are logged"""
        sara_session = {
            'username': 'sara_cohen',
            'role': 'customer',
            'customer_id': 'CUST-TEST-100'
        }
        
        # Try to access another customer's data
        self.service.authorize_customer_access(sara_session, 'CUST001', 'savings')
        
        # Check violations were logged
        self.assertTrue(len(self.service.access_violations) > 0, 
            "Access violations should be logged")
        
        violation = self.service.access_violations[-1]
        self.assertEqual(violation['violation_type'], 'unauthorized_access_attempt')
        self.assertEqual(violation['requested_customer_id'], 'CUST001')
        self.assertEqual(violation['session_customer_id'], 'CUST-TEST-100')
        
        print(f"✓ Access violations are properly logged")
    
    def test_filter_resources_for_customer(self):
        """Test filtering resources for a customer"""
        sara_session = {
            'username': 'sara_cohen',
            'role': 'customer',
            'customer_id': 'CUST-TEST-100'
        }
        
        all_resources = [
            {'id': '1', 'customer_id': 'CUST-TEST-100', 'name': 'Sara\'s Policy'},
            {'id': '2', 'customer_id': 'CUST001', 'name': 'John\'s Policy'},
            {'id': '3', 'customer_id': 'CUST-TEST-100', 'name': 'Sara\'s Other Policy'},
            {'id': '4', 'customer_id': 'CUST002', 'name': 'Jane\'s Policy'},
        ]
        
        filtered = self.service.filter_resources_for_customer(sara_session, all_resources)
        
        # Sara should only see her own resources
        self.assertEqual(len(filtered), 2, "Sara should only see 2 resources")
        for resource in filtered:
            self.assertEqual(resource['customer_id'], 'CUST-TEST-100')
        
        print(f"✓ Resource filtering works correctly for customers")
    
    def test_admin_sees_all_resources(self):
        """Test that admin can see all resources"""
        admin_session = {
            'username': 'admin_user',
            'role': 'admin',
            'customer_id': None
        }
        
        all_resources = [
            {'id': '1', 'customer_id': 'CUST-TEST-100', 'name': 'Sara\'s Policy'},
            {'id': '2', 'customer_id': 'CUST001', 'name': 'John\'s Policy'},
            {'id': '3', 'customer_id': 'CUST002', 'name': 'Jane\'s Policy'},
        ]
        
        filtered = self.service.filter_resources_for_customer(admin_session, all_resources)
        
        # Admin should see all resources
        self.assertEqual(len(filtered), 3, "Admin should see all 3 resources")
        
        print(f"✓ Admin can see all resources")

    def test_validate_resource_ownership_resolves_policy_owner(self):
        """Resources without customer_id should inherit ownership from policy_id."""
        sara_session = {
            'username': 'sara_cohen',
            'role': 'customer',
            'customer_id': 'CUST-TEST-100'
        }

        authorized, error = self.service.validate_resource_ownership(
            sara_session,
            {'id': 'CLM-001', 'policy_id': 'POL-SARA-001'},
            'claim'
        )

        self.assertTrue(authorized, "Sara should access a claim linked to her policy")
        self.assertIsNone(error)

    def test_validate_resource_ownership_denies_other_policy_owner(self):
        """Policy ownership lookup must still deny access to another customer."""
        sara_session = {
            'username': 'sara_cohen',
            'role': 'customer',
            'customer_id': 'CUST-TEST-100'
        }

        authorized, error = self.service.validate_resource_ownership(
            sara_session,
            {'id': 'BILL-001', 'policy_id': 'POL-JOHN-001'},
            'billing'
        )

        self.assertFalse(authorized, "Sara should not access resources linked to John's policy")
        self.assertIn('own billing', error)

    def test_validate_resource_ownership_denies_unknown_policy(self):
        """Unknown policies should not be treated as owned resources."""
        sara_session = {
            'username': 'sara_cohen',
            'role': 'customer',
            'customer_id': 'CUST-TEST-100'
        }

        authorized, error = self.service.validate_resource_ownership(
            sara_session,
            {'id': 'DOC-001', 'policy_id': 'POL-MISSING-001'},
            'document'
        )

        self.assertFalse(authorized, "Unknown policy ownership should be denied")
        self.assertIsNotNone(error)


def run_sara_cohen_isolation_test():
    """Run a quick test to verify Sara Cohen (CUST-TEST-100) data isolation"""
    print("\n" + "=" * 70)
    print("CUSTOMER DATA ISOLATION TEST - CUST-TEST-100 (Sara Cohen)")
    print("=" * 70)
    
    from services.customer_data_access import CustomerDataAccessService
    
    service = CustomerDataAccessService()
    
    # Sara Cohen's session
    sara_session = {
        'username': 'sara_cohen',
        'role': 'customer',
        'customer_id': 'CUST-TEST-100'
    }
    
    # Test 1: Sara can access her own data
    authorized, customer_id, error = service.authorize_customer_access(
        sara_session, 'CUST-TEST-100', 'savings'
    )
    print(f"\n✓ Sara can access CUST-TEST-100 data: {authorized}")
    
    # Test 2: Sara CANNOT access other customers
    other_customers = ['CUST001', 'CUST002', 'CUST003', 'CUST-OTHER-456']
    
    for other_id in other_customers:
        authorized, _, error = service.authorize_customer_access(
            sara_session, other_id, 'savings'
        )
        status = "✓ DENIED" if not authorized else "✗ ALLOWED (BUG!)"
        print(f"{status}: Sara trying to access {other_id}: authorized={authorized}")
        
        if authorized:
            print(f"  ⚠️ SECURITY BUG: Sara should NOT access {other_id}")
            return False
    
    print("\n" + "=" * 70)
    print("✓ ALL DATA ISOLATION TESTS PASSED - CUST-TEST-100 is properly isolated")
    print("=" * 70)
    
    return True


if __name__ == '__main__':
    # Run quick isolation test first
    if not run_sara_cohen_isolation_test():
        print("\n⚠️ SECURITY ISSUE DETECTED")
        sys.exit(1)
    
    print("\n\nRunning full test suite...\n")
    
    # Run full unittest suite
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    suite.addTests(loader.loadTestsFromTestCase(TestCustomerDataIsolation))
    suite.addTests(loader.loadTestsFromTestCase(TestCustomerDataAccessService))
    
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    # Exit with error code if tests failed
    sys.exit(0 if result.wasSuccessful() else 1)
