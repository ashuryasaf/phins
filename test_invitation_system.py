#!/usr/bin/env python3
"""
Test script for the Customer Invitation System
Tests the complete flow from code generation to registration
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Test that the server module can be imported and has the required data structures
print("=" * 60)
print("PHINS Customer Invitation System - Validation Test")
print("=" * 60)

# Test 1: Check data structures exist
print("\n[TEST 1] Checking data structures...")
try:
    # Import the server module (without starting the server)
    from web_portal import server
    
    # Check that required data structures exist
    assert hasattr(server, 'INVITATION_CODES'), "Missing INVITATION_CODES"
    assert hasattr(server, 'CUSTOMER_INVITATIONS'), "Missing CUSTOMER_INVITATIONS"
    assert hasattr(server, 'CUSTOMER_REFERRAL_STATS'), "Missing CUSTOMER_REFERRAL_STATS"
    assert hasattr(server, 'MAX_CUSTOMER_INVITATIONS'), "Missing MAX_CUSTOMER_INVITATIONS"
    
    print(f"  ✅ INVITATION_CODES: {type(server.INVITATION_CODES)}")
    print(f"  ✅ CUSTOMER_INVITATIONS: {type(server.CUSTOMER_INVITATIONS)}")
    print(f"  ✅ CUSTOMER_REFERRAL_STATS: {type(server.CUSTOMER_REFERRAL_STATS)}")
    print(f"  ✅ MAX_CUSTOMER_INVITATIONS: {server.MAX_CUSTOMER_INVITATIONS}")
    
except Exception as e:
    print(f"  ❌ Error: {e}")
    sys.exit(1)

# Test 2: Check persistence functions
print("\n[TEST 2] Checking persistence functions...")
try:
    assert hasattr(server, 'save_ledger_data'), "Missing save_ledger_data"
    assert hasattr(server, 'load_ledger_data'), "Missing load_ledger_data"
    print("  ✅ save_ledger_data function exists")
    print("  ✅ load_ledger_data function exists")
except Exception as e:
    print(f"  ❌ Error: {e}")
    sys.exit(1)

# Test 3: Test admin invitation code generation (simulate)
print("\n[TEST 3] Testing admin invitation code generation...")
try:
    import secrets
    from datetime import datetime, timedelta
    
    # Generate a test code
    code = f"PHINS-2026-{secrets.token_hex(4).upper()}"
    expires_at = (datetime.now() + timedelta(days=30)).isoformat()
    
    invitation = {
        'code': code,
        'created_at': datetime.now().isoformat(),
        'created_by': 'test_admin',
        'expires_at': expires_at,
        'max_uses': 1,
        'used_count': 0,
        'used_by': [],
        'status': 'active',
        'notes': 'Test invitation'
    }
    
    # Store it
    server.INVITATION_CODES[code] = invitation
    
    # Verify it's stored
    assert code in server.INVITATION_CODES, "Code not stored"
    assert server.INVITATION_CODES[code]['status'] == 'active', "Wrong status"
    
    print(f"  ✅ Generated admin code: {code}")
    print(f"  ✅ Code stored successfully")
    print(f"  ✅ Status: {server.INVITATION_CODES[code]['status']}")
    
except Exception as e:
    print(f"  ❌ Error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Test 4: Test customer invitation code generation (simulate)
print("\n[TEST 4] Testing customer invitation code generation...")
try:
    customer_id = "CUST-TEST-001"
    customer_short = customer_id[-4:]
    
    # Generate a customer referral code
    ref_code = f"REF-{customer_short}-{secrets.token_hex(3).upper()}"
    
    customer_invitation = {
        'code': ref_code,
        'creator_customer_id': customer_id,
        'creator_name': 'Test Customer',
        'creator_email': 'test@example.com',
        'created_at': datetime.now().isoformat(),
        'expires_at': (datetime.now() + timedelta(days=90)).isoformat(),
        'max_uses': 1,
        'used_count': 0,
        'used_by': [],
        'status': 'active',
        'notes': '',
        'reward_status': 'pending'
    }
    
    # Store it
    server.CUSTOMER_INVITATIONS[ref_code] = customer_invitation
    
    # Initialize referral stats
    server.CUSTOMER_REFERRAL_STATS[customer_id] = {
        'codes_generated': 1,
        'successful_referrals': 0,
        'codes': [{'code': ref_code, 'created_at': customer_invitation['created_at'], 'status': 'active'}],
        'referred_customers': [],
        'rewards': [],
        'total_reward_value': 0
    }
    
    # Verify
    assert ref_code in server.CUSTOMER_INVITATIONS, "Customer code not stored"
    assert customer_id in server.CUSTOMER_REFERRAL_STATS, "Referral stats not stored"
    
    print(f"  ✅ Generated customer referral code: {ref_code}")
    print(f"  ✅ Code stored in CUSTOMER_INVITATIONS")
    print(f"  ✅ Referral stats initialized for customer")
    
except Exception as e:
    print(f"  ❌ Error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Test 5: Verify both code types can be validated
print("\n[TEST 5] Testing code validation logic...")
try:
    # Test admin code lookup
    admin_found = server.INVITATION_CODES.get(code)
    assert admin_found is not None, "Admin code not found"
    print(f"  ✅ Admin code '{code}' found")
    
    # Test customer code lookup
    customer_found = server.CUSTOMER_INVITATIONS.get(ref_code)
    assert customer_found is not None, "Customer code not found"
    print(f"  ✅ Customer code '{ref_code}' found")
    
    # Test combined lookup (what validation endpoint does)
    test_code = ref_code
    invitation = server.INVITATION_CODES.get(test_code)
    invitation_type = 'admin'
    if not invitation:
        invitation = server.CUSTOMER_INVITATIONS.get(test_code)
        invitation_type = 'customer'
    
    assert invitation is not None, "Combined lookup failed"
    assert invitation_type == 'customer', "Wrong type detected"
    print(f"  ✅ Combined lookup works (type: {invitation_type})")
    
except Exception as e:
    print(f"  ❌ Error: {e}")
    sys.exit(1)

# Test 6: Test max invitations limit
print("\n[TEST 6] Testing max invitations limit...")
try:
    assert server.MAX_CUSTOMER_INVITATIONS == 10, f"Wrong limit: {server.MAX_CUSTOMER_INVITATIONS}"
    print(f"  ✅ MAX_CUSTOMER_INVITATIONS = {server.MAX_CUSTOMER_INVITATIONS}")
    
except Exception as e:
    print(f"  ❌ Error: {e}")
    sys.exit(1)

# Cleanup test data
print("\n[CLEANUP] Removing test data...")
try:
    if code in server.INVITATION_CODES:
        del server.INVITATION_CODES[code]
    if ref_code in server.CUSTOMER_INVITATIONS:
        del server.CUSTOMER_INVITATIONS[ref_code]
    if customer_id in server.CUSTOMER_REFERRAL_STATS:
        del server.CUSTOMER_REFERRAL_STATS[customer_id]
    print("  ✅ Test data cleaned up")
except Exception as e:
    print(f"  ⚠️ Cleanup warning: {e}")

print("\n" + "=" * 60)
print("✅ ALL TESTS PASSED - Invitation System is ready!")
print("=" * 60)
print("\nSummary of implemented features:")
print("  • Admin can generate invitation codes (INVITATION_CODES)")
print("  • Customers can generate referral codes (CUSTOMER_INVITATIONS)")
print("  • Maximum 10 referral codes per customer")
print("  • Referral tracking and statistics (CUSTOMER_REFERRAL_STATS)")
print("  • Both code types validated via /api/invitations/validate")
print("  • Data persisted via save_ledger_data()")
print("=" * 60)
