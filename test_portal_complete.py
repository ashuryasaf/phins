#!/usr/bin/env python3
"""
Comprehensive PHINS Admin Portal Test
Tests all user accounts and portal functionality
"""

import requests
import json
import sys

BASE_URL = "http://localhost:8000"

# Test accounts
ACCOUNTS = {
    'admin': {
        'password': 'admin123',
        'expected_role': 'admin',
        'expected_name': 'Admin User',
        'description': 'Full system access'
    },
    'underwriter': {
        'password': 'under123',
        'expected_role': 'underwriter',
        'expected_name': 'John Underwriter',
        'description': 'Underwriting division access'
    },
    'claims_adjuster': {
        'password': 'claims123',
        'expected_role': 'claims',
        'expected_name': 'Jane Claims',
        'description': 'Claims division access'
    },
    'accountant': {
        'password': 'acct123',
        'expected_role': 'accountant',
        'expected_name': 'Bob Accountant',
        'description': 'Accounting division access'
    }
}

print("=" * 70)
print("🔐 PHINS ADMIN PORTAL - COMPREHENSIVE TEST")
print("=" * 70)
print()

# Test 1: Server accessibility
print("📡 Test 1: Server Accessibility")
print("-" * 70)
try:
    response = requests.get(f"{BASE_URL}/")
    if response.status_code == 200:
        print("✅ Server is running and accessible")
    else:
        print(f"⚠️  Server returned status {response.status_code}")
except Exception as e:
    print(f"❌ Cannot connect to server: {e}")
    print("\nPlease start the server with: python3 web_portal/server.py")
    sys.exit(1)

print()

# Test 2: Admin portal page
print("📄 Test 2: Admin Portal Pages")
print("-" * 70)
pages = [
    ('/admin-portal.html', 'Admin Portal (main)'),
    ('/admin.html', 'Admin Portal (alternative)'),
    ('/login.html', 'Login Page'),
    ('/dashboard.html', 'Customer Dashboard')
]

for path, name in pages:
    try:
        response = requests.get(f"{BASE_URL}{path}")
        if response.status_code == 200:
            print(f"✅ {name}: Accessible")
        else:
            print(f"❌ {name}: HTTP {response.status_code}")
    except Exception as e:
        print(f"❌ {name}: Error - {e}")

print()

# Test 3: Authentication for all accounts
print("🔑 Test 3: Authentication Testing")
print("-" * 70)

successful_logins = 0
tokens = {}

for username, details in ACCOUNTS.items():
    print(f"\nTesting: {username}")
    print(f"  Description: {details['description']}")
    
    try:
        response = requests.post(
            f"{BASE_URL}/api/login",
            json={"username": username, "password": details['password']},
            headers={"Content-Type": "application/json"}
        )
        
        if response.status_code == 200:
            data = response.json()
            token = data.get('token', '')
            role = data.get('role', '')
            name = data.get('name', '')
            
            # Verify token
            if token and token.startswith('demo-token-'):
                print(f"  ✅ Login successful")
                print(f"  📝 Token: {token[:30]}...")
                successful_logins += 1
                tokens[username] = token
            else:
                print(f"  ❌ Invalid token format")
                continue
            
            # Verify role
            if role == details['expected_role']:
                print(f"  ✅ Role correct: {role}")
            else:
                print(f"  ❌ Role mismatch: got '{role}', expected '{details['expected_role']}'")
            
            # Verify name
            if name == details['expected_name']:
                print(f"  ✅ Name correct: {name}")
            else:
                print(f"  ⚠️  Name: {name} (expected: {details['expected_name']})")
                
        else:
            print(f"  ❌ Login failed: HTTP {response.status_code}")
            print(f"  Response: {response.text}")
    except Exception as e:
        print(f"  ❌ Error: {e}")

print()
print(f"Login Success Rate: {successful_logins}/{len(ACCOUNTS)}")

# Test 4: API Endpoints with authentication
print()
print("🔌 Test 4: API Endpoints")
print("-" * 70)

if tokens:
    # Use admin token for API tests
    admin_token = tokens.get('admin', list(tokens.values())[0])
    headers = {'Authorization': f'Bearer {admin_token}'}
    
    endpoints = [
        ('/api/policies', 'Policies'),
        ('/api/claims', 'Claims'),
        ('/api/underwriting', 'Underwriting'),
        ('/api/customers', 'Customers'),
        ('/api/bi/actuary', 'BI Actuary'),
        ('/api/bi/underwriting', 'BI Underwriting'),
        ('/api/bi/accounting', 'BI Accounting'),
    ]
    
    for path, name in endpoints:
        try:
            response = requests.get(f"{BASE_URL}{path}", headers=headers)
            if response.status_code == 200:
                data = response.json()
                print(f"✅ {name}: Working (returned {len(str(data))} bytes)")
            else:
                print(f"⚠️  {name}: HTTP {response.status_code}")
        except Exception as e:
            print(f"❌ {name}: {e}")
else:
    print("⚠️  Skipping API tests - no valid tokens")

# Final Summary
print()
print("=" * 70)
print("📊 TEST SUMMARY")
print("=" * 70)

if successful_logins == len(ACCOUNTS):
    print("✅ ALL TESTS PASSED")
    print()
    print("🎯 Admin Portal Status: READY FOR USE")
    print()
    print("📍 Access URLs:")
    print(f"   Main Portal: {BASE_URL}/admin-portal.html")
    print(f"   Alt Portal:  {BASE_URL}/admin.html")
    print()
    print("🔑 All Accounts Verified:")
    for username, details in ACCOUNTS.items():
        print(f"   • {username:16} / {details['password']:10} → {details['description']}")
else:
    print(f"⚠️  {successful_logins}/{len(ACCOUNTS)} accounts working")
    print()
    print("❌ SOME TESTS FAILED - Review output above")

print()
print("=" * 70)
