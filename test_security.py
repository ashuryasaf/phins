#!/usr/bin/env python3
"""
Security Testing Suite for PHINS Portal
Tests injection attacks, rate limiting, IP blocking, and malicious activity detection
"""

import json
import time
import requests
from datetime import datetime

BASE_URL = 'http://localhost:8000'

def test_sql_injection():
    """Test SQL injection detection"""
    print("\n=== Testing SQL Injection Detection ===")
    
    malicious_inputs = [
        "' OR '1'='1",
        "admin'--",
        "1' UNION SELECT * FROM users--",
        "'; DROP TABLE customers;--",
        "admin' AND 1=1--"
    ]
    
    blocked_count = 0
    for payload in malicious_inputs:
        try:
            response = requests.post(f'{BASE_URL}/api/login', 
                json={'username': payload, 'password': 'test123'},
                timeout=5
            )
            if response.status_code in [400, 403]:
                print(f"✓ Blocked SQL injection: {payload[:30]}...")
                blocked_count += 1
            else:
                print(f"✗ FAILED to block: {payload[:30]}...")
        except Exception as e:
            print(f"✗ Error testing: {str(e)}")
    
    print(f"\nBlocked {blocked_count}/{len(malicious_inputs)} SQL injection attempts")
    return blocked_count == len(malicious_inputs)

def test_xss_attacks():
    """Test XSS attack detection"""
    print("\n=== Testing XSS Attack Detection ===")
    
    xss_payloads = [
        "<script>alert('XSS')</script>",
        "<img src=x onerror=alert('XSS')>",
        "javascript:alert('XSS')",
        "<iframe src='javascript:alert(1)'></iframe>",
        "<svg onload=alert('XSS')>"
    ]
    
    blocked_count = 0
    for payload in xss_payloads:
        try:
            response = requests.post(f'{BASE_URL}/api/login',
                json={'username': payload, 'password': 'test'},
                timeout=5
            )
            if response.status_code in [400, 403]:
                print(f"✓ Blocked XSS: {payload[:40]}...")
                blocked_count += 1
            else:
                print(f"✗ FAILED to block: {payload[:40]}...")
        except Exception as e:
            print(f"✗ Error: {str(e)}")
    
    print(f"\nBlocked {blocked_count}/{len(xss_payloads)} XSS attempts")
    return blocked_count == len(xss_payloads)

def test_path_traversal():
    """Test path traversal detection"""
    print("\n=== Testing Path Traversal Detection ===")
    
    traversal_attempts = [
        "../../etc/passwd",
        "../../../windows/system32",
        "....//....//....//etc/shadow",
        "..\\..\\..\\boot.ini",
        "%2e%2e%2f%2e%2e%2fetc%2fpasswd"
    ]
    
    blocked_count = 0
    for path in traversal_attempts:
        try:
            response = requests.get(f'{BASE_URL}/{path}', timeout=5)
            if response.status_code in [400, 403, 404]:
                print(f"✓ Blocked traversal: {path[:40]}...")
                blocked_count += 1
            else:
                print(f"✗ FAILED to block: {path}")
        except Exception as e:
            print(f"✗ Error: {str(e)}")
    
    print(f"\nBlocked {blocked_count}/{len(traversal_attempts)} path traversal attempts")
    return blocked_count == len(traversal_attempts)

def test_rate_limiting():
    """Test rate limiting functionality"""
    print("\n=== Testing Rate Limiting ===")
    
    # Make rapid requests
    requests_made = 0
    blocked = 0
    
    print("Making 70 rapid requests (limit is 60/min)...")
    for i in range(70):
        try:
            response = requests.get(f'{BASE_URL}/api/policies', timeout=5)
            requests_made += 1
            if response.status_code == 429:  # Too Many Requests
                blocked += 1
                if blocked == 1:
                    print(f"✓ Rate limiting activated after {requests_made} requests")
        except Exception as e:
            print(f"✗ Error on request {i+1}: {str(e)}")
            break
    
    success = blocked > 0
    print(f"\n{'✓' if success else '✗'} Rate limiting: {requests_made} requests made, {blocked} blocked")
    return success

def test_command_injection():
    """Test command injection detection"""
    print("\n=== Testing Command Injection Detection ===")
    
    command_payloads = [
        "; ls -la",
        "| cat /etc/passwd",
        "&& rm -rf /",
        "`whoami`",
        "$(cat /etc/shadow)"
    ]
    
    blocked_count = 0
    for payload in command_payloads:
        try:
            response = requests.post(f'{BASE_URL}/api/login',
                json={'username': f"admin{payload}", 'password': 'test'},
                timeout=5
            )
            if response.status_code in [400, 403]:
                print(f"✓ Blocked command injection: {payload[:30]}...")
                blocked_count += 1
            else:
                print(f"✗ FAILED to block: {payload}")
        except Exception as e:
            print(f"✗ Error: {str(e)}")
    
    print(f"\nBlocked {blocked_count}/{len(command_payloads)} command injection attempts")
    return blocked_count == len(command_payloads)

def test_request_size_limit():
    """Test oversized request blocking"""
    print("\n=== Testing Request Size Limits ===")
    
    # Create a 15MB payload (over the 10MB limit)
    large_data = {'data': 'A' * (15 * 1024 * 1024)}
    
    try:
        response = requests.post(f'{BASE_URL}/api/submit-quote',
            json=large_data,
            timeout=10
        )
        if response.status_code in [413, 400]:
            print("✓ Successfully blocked oversized request (15MB)")
            return True
        else:
            print(f"✗ Failed to block large request: {response.status_code}")
            return False
    except Exception as e:
        print(f"✗ Error testing size limit: {str(e)}")
        return False

def test_authentication_bypass():
    """Test authentication bypass attempts"""
    print("\n=== Testing Authentication Bypass ===")
    
    bypass_attempts = [
        {'username': 'admin', 'password': "' OR '1'='1"},
        {'username': "admin'--", 'password': 'anything'},
        {'username': 'admin', 'password': 'admin\' OR \'1\'=\'1'},
    ]
    
    blocked_count = 0
    for attempt in bypass_attempts:
        try:
            response = requests.post(f'{BASE_URL}/api/login',
                json=attempt,
                timeout=5
            )
            # Should not receive a valid session token
            data = response.json() if response.status_code == 200 else {}
            if 'token' not in data or response.status_code in [400, 403]:
                print(f"✓ Blocked bypass attempt: {attempt['username']}")
                blocked_count += 1
            else:
                print(f"✗ FAILED to block: {attempt}")
        except Exception as e:
            print(f"✗ Error: {str(e)}")
    
    print(f"\nBlocked {blocked_count}/{len(bypass_attempts)} bypass attempts")
    return blocked_count == len(bypass_attempts)

def check_security_endpoint():
    """Test security monitoring endpoint"""
    print("\n=== Testing Security Monitoring Endpoint ===")
    
    try:
        # Try without auth (should fail)
        response = requests.get(f'{BASE_URL}/api/security/threats', timeout=5)
        if response.status_code in [401, 403]:
            print("✓ Security endpoint requires authentication")
        else:
            print("✗ Security endpoint accessible without auth")
        
        # Note: Full test requires admin credentials
        print("ℹ Full endpoint test requires admin login")
        return True
    except Exception as e:
        print(f"✗ Error: {str(e)}")
        return False

def run_all_tests():
    """Run complete security test suite"""
    print("=" * 70)
    print("PHINS SECURITY TEST SUITE")
    print("=" * 70)
    print(f"Testing against: {BASE_URL}")
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    tests = [
        ("SQL Injection Protection", test_sql_injection),
        ("XSS Attack Protection", test_xss_attacks),
        ("Path Traversal Protection", test_path_traversal),
        ("Command Injection Protection", test_command_injection),
        ("Authentication Bypass Prevention", test_authentication_bypass),
        ("Request Size Limiting", test_request_size_limit),
        ("Rate Limiting", test_rate_limiting),
        ("Security Monitoring", check_security_endpoint),
    ]
    
    results = []
    for test_name, test_func in tests:
        try:
            result = test_func()
            results.append((test_name, result))
            time.sleep(1)  # Brief pause between tests
        except Exception as e:
            print(f"\n✗ Test crashed: {test_name} - {str(e)}")
            results.append((test_name, False))
    
    # Summary
    print("\n" + "=" * 70)
    print("SECURITY TEST RESULTS")
    print("=" * 70)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"{status:8} | {test_name}")
    
    print("=" * 70)
    print(f"Overall: {passed}/{total} tests passed ({passed*100//total}%)")
    
    if passed == total:
        print("✓ ALL SECURITY TESTS PASSED")
    else:
        print(f"✗ {total - passed} SECURITY ISSUES DETECTED")
    
    print(f"Completed: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    return passed == total

if __name__ == '__main__':
    print("\n⚠️  WARNING: This script tests security features by attempting attacks")
    print("   Only run against development/test environments!")
    print("\n   Press Ctrl+C to cancel, or wait 3 seconds to continue...")
    
    try:
        time.sleep(3)
        success = run_all_tests()
        exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\nTest cancelled by user")
        exit(1)
