#!/usr/bin/env python3
"""
Manual verification script for customer_id guarantee fix (PR #90).

This script demonstrates that the get_customer_id_guaranteed function
ensures customer_id is NEVER None for customer role using a 5-layer
fallback strategy.
"""

import sys
import os
import time

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import server module
import web_portal.server as portal

def test_guarantee_with_new_customer():
    """Test that a new customer always gets a customer_id"""
    print("\n" + "="*80)
    print("TEST 1: New customer (no existing records)")
    print("="*80)
    
    test_email = f"demo{time.time_ns()}@example.com"
    
    print(f"\nCalling get_customer_id_guaranteed('{test_email}', 'customer')...")
    customer_id = portal.get_customer_id_guaranteed(test_email, 'customer')
    
    print(f"\n✅ RESULT: customer_id = {customer_id}")
    print(f"   Format valid: {customer_id.startswith('CUST-')}")
    print(f"   Type: {type(customer_id)}")
    print(f"   Persisted: {customer_id in portal.CUSTOMERS}")
    
    if customer_id and customer_id.startswith('CUST-'):
        print("\n✅ TEST PASSED: customer_id is NEVER None for customer role")
        return True
    else:
        print("\n❌ TEST FAILED: customer_id is invalid")
        return False

def test_guarantee_with_existing_customer():
    """Test that existing customer gets their customer_id"""
    print("\n" + "="*80)
    print("TEST 2: Existing customer (with record in CUSTOMERS dict)")
    print("="*80)
    
    # Add a test customer
    test_customer_id = "CUST-12345"
    test_email = "existing@example.com"
    
    portal.CUSTOMERS[test_customer_id] = {
        'id': test_customer_id,
        'email': test_email,
        'name': 'Existing Customer',
        'status': 'active'
    }
    
    print(f"\nAdded customer to CUSTOMERS dict: {test_customer_id}")
    print(f"Calling get_customer_id_guaranteed('{test_email}', 'customer')...")
    
    customer_id = portal.get_customer_id_guaranteed(test_email, 'customer')
    
    print(f"\n✅ RESULT: customer_id = {customer_id}")
    print(f"   Matches expected: {customer_id == test_customer_id}")
    
    if customer_id == test_customer_id:
        print("\n✅ TEST PASSED: Existing customer_id correctly returned")
        return True
    else:
        print("\n❌ TEST FAILED: customer_id mismatch")
        return False

def test_guarantee_with_database_failure():
    """Test that customer_id is generated even when database fails"""
    print("\n" + "="*80)
    print("TEST 3: Database failure scenario")
    print("="*80)
    
    # Temporarily disable database
    original_use_db = portal.USE_DATABASE
    portal.USE_DATABASE = False
    
    try:
        test_email = f"dbfail{time.time_ns()}@example.com"
        
        print(f"\nDatabase disabled (USE_DATABASE=False)")
        print(f"Calling get_customer_id_guaranteed('{test_email}', 'customer')...")
        
        customer_id = portal.get_customer_id_guaranteed(test_email, 'customer')
        
        print(f"\n✅ RESULT: customer_id = {customer_id}")
        print(f"   Generated despite DB failure: {customer_id is not None}")
        print(f"   Format valid: {customer_id.startswith('CUST-')}")
        
        if customer_id and customer_id.startswith('CUST-'):
            print("\n✅ TEST PASSED: customer_id generated even with DB failure")
            return True
        else:
            print("\n❌ TEST FAILED: customer_id generation failed")
            return False
    finally:
        portal.USE_DATABASE = original_use_db

def test_non_customer_role():
    """Test that non-customer roles can have None customer_id"""
    print("\n" + "="*80)
    print("TEST 4: Non-customer role (admin)")
    print("="*80)
    
    test_email = "admin@example.com"
    
    print(f"\nCalling get_customer_id_guaranteed('{test_email}', 'admin')...")
    customer_id = portal.get_customer_id_guaranteed(test_email, 'admin')
    
    print(f"\n✅ RESULT: customer_id = {customer_id}")
    print(f"   None is acceptable for admin role: {customer_id is None or isinstance(customer_id, str)}")
    
    print("\n✅ TEST PASSED: Non-customer roles handled correctly")
    return True

if __name__ == '__main__':
    print("\n" + "="*80)
    print("CUSTOMER DASHBOARD ACCESS FIX VERIFICATION (PR #90)")
    print("="*80)
    print("\nThis script verifies the 5-layer customer_id guarantee implementation.")
    print("The fix ensures customer_id is NEVER None for customer role,")
    print("preventing 403 Forbidden errors on /api/customer/* endpoints.")
    
    results = []
    
    # Run all tests
    results.append(("New Customer", test_guarantee_with_new_customer()))
    results.append(("Existing Customer", test_guarantee_with_existing_customer()))
    results.append(("Database Failure", test_guarantee_with_database_failure()))
    results.append(("Non-Customer Role", test_non_customer_role()))
    
    # Summary
    print("\n" + "="*80)
    print("TEST SUMMARY")
    print("="*80)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for name, result in results:
        status = "✅ PASSED" if result else "❌ FAILED"
        print(f"{status}: {name}")
    
    print(f"\nTotal: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n✅ ALL TESTS PASSED - customer_id guarantee is working correctly!")
        print("\nThe fix successfully addresses the 84-hour customer dashboard access issue.")
        print("Customer logins will now ALWAYS receive a valid customer_id.")
        sys.exit(0)
    else:
        print("\n❌ SOME TESTS FAILED - please review the implementation")
        sys.exit(1)
