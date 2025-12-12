#!/usr/bin/env python3
"""
Quick Security Validation
Runs basic checks to ensure security features are working
"""

import requests
import json
from datetime import datetime

BASE_URL = 'http://localhost:8000'

print("=" * 70)
print("PHINS SECURITY QUICK CHECK")
print("=" * 70)
print(f"Target: {BASE_URL}")
print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

tests_passed = 0
tests_failed = 0

# Test 1: SQL Injection Block
print("1. Testing SQL Injection Protection...")
try:
    response = requests.post(f'{BASE_URL}/api/login',
        json={'username': "admin' OR '1'='1", 'password': 'test'},
        timeout=5
    )
    if response.status_code in [400, 403]:
        print("   ✓ SQL injection blocked\n")
        tests_passed += 1
    else:
        print(f"   ✗ Not blocked (status: {response.status_code})\n")
        tests_failed += 1
except Exception as e:
    print(f"   ✗ Error: {str(e)}\n")
    tests_failed += 1

# Test 2: XSS Block
print("2. Testing XSS Protection...")
try:
    response = requests.post(f'{BASE_URL}/api/login',
        json={'username': "<script>alert('xss')</script>", 'password': 'test'},
        timeout=5
    )
    if response.status_code in [400, 403]:
        print("   ✓ XSS attack blocked\n")
        tests_passed += 1
    else:
        print(f"   ✗ Not blocked (status: {response.status_code})\n")
        tests_failed += 1
except Exception as e:
    print(f"   ✗ Error: {str(e)}\n")
    tests_failed += 1

# Test 3: Path Traversal
print("3. Testing Path Traversal Protection...")
try:
    response = requests.get(f'{BASE_URL}/../../etc/passwd', timeout=5)
    if response.status_code in [400, 403, 404]:
        print("   ✓ Path traversal blocked\n")
        tests_passed += 1
    else:
        print(f"   ✗ Not blocked (status: {response.status_code})\n")
        tests_failed += 1
except Exception as e:
    print(f"   ✗ Error: {str(e)}\n")
    tests_failed += 1

# Test 4: Rate Limiting Check
print("4. Testing Rate Limiting...")
try:
    blocked = False
    for i in range(65):  # Exceed 60/min limit
        response = requests.get(f'{BASE_URL}/api/policies', timeout=5)
        if response.status_code == 429:
            blocked = True
            break
    
    if blocked:
        print("   ✓ Rate limiting active\n")
        tests_passed += 1
    else:
        print("   ✗ Rate limiting not triggered\n")
        tests_failed += 1
except Exception as e:
    print(f"   ✗ Error: {str(e)}\n")
    tests_failed += 1

# Test 5: Security Endpoint
print("5. Testing Security Monitoring Endpoint...")
try:
    response = requests.get(f'{BASE_URL}/api/security/threats', timeout=5)
    if response.status_code in [401, 403]:
        print("   ✓ Requires authentication\n")
        tests_passed += 1
    else:
        print(f"   ✗ Accessible without auth (status: {response.status_code})\n")
        tests_failed += 1
except Exception as e:
    print(f"   ✗ Error: {str(e)}\n")
    tests_failed += 1

# Summary
print("=" * 70)
print("RESULTS")
print("=" * 70)
print(f"Tests Passed: {tests_passed}")
print(f"Tests Failed: {tests_failed}")
print(f"Success Rate: {tests_passed * 100 // (tests_passed + tests_failed)}%")

if tests_failed == 0:
    print("\n✓ ALL SECURITY CHECKS PASSED")
    print("  System is ready for deployment")
else:
    print(f"\n✗ {tests_failed} SECURITY ISSUES DETECTED")
    print("  Review and fix before deployment")

print("=" * 70)
