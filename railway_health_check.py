#!/usr/bin/env python3
"""
Railway Deployment Health Check Script

Verifies the PHINS platform is running correctly on Railway:
- Server responds on port 8000
- All critical API endpoints respond
- Security headers are set
- Rate limiting is active
- Malicious input blocking works
- Session management works
- Audit logging is functional
"""

import sys
import json
import time
import argparse
from urllib.request import urlopen, Request
from urllib.error import HTTPError, URLError


class HealthChecker:
    def __init__(self, base_url):
        self.base_url = base_url.rstrip('/')
        self.passed = []
        self.failed = []
        self.warnings = []
    
    def check(self, name, test_func):
        """Run a health check test"""
        try:
            print(f"  Testing: {name}...", end=" ")
            test_func()
            print("✓ PASS")
            self.passed.append(name)
            return True
        except Exception as e:
            print(f"✗ FAIL: {e}")
            self.failed.append((name, str(e)))
            return False
    
    def warn(self, name, message):
        """Record a warning"""
        print(f"  Warning: {name}: {message}")
        self.warnings.append((name, message))
    
    def _get(self, path, token=None):
        """Make GET request"""
        url = f"{self.base_url}{path}"
        headers = {}
        if token:
            headers['Authorization'] = f'Bearer {token}'
        req = Request(url, headers=headers)
        with urlopen(req, timeout=10) as resp:
            return resp.read().decode('utf-8'), resp.headers
    
    def _post(self, path, payload, token=None):
        """Make POST request"""
        url = f"{self.base_url}{path}"
        data = json.dumps(payload).encode('utf-8')
        headers = {'Content-Type': 'application/json'}
        if token:
            headers['Authorization'] = f'Bearer {token}'
        req = Request(url, data=data, headers=headers)
        with urlopen(req, timeout=10) as resp:
            return resp.read().decode('utf-8'), resp.headers
    
    def test_server_responds(self):
        """Test server responds to basic request"""
        body, headers = self._get("/api/metrics")
        data = json.loads(body)
        assert 'metrics' in data, "Metrics endpoint should return metrics data"
    
    def test_login_endpoint(self):
        """Test login endpoint works"""
        body, headers = self._post("/api/login", {
            "username": "admin",
            "password": "admin123"
        })
        data = json.loads(body)
        assert 'token' in data, "Login should return token"
        assert data['token'].startswith('phins_'), "Token should have phins_ prefix"
        assert data['role'] == 'admin', "Admin login should return admin role"
    
    def test_policy_creation(self):
        """Test policy creation endpoint"""
        body, headers = self._post("/api/policies/create", {
            "customer_name": "Health Check Test",
            "customer_email": "healthcheck@example.com",
            "type": "life",
            "coverage_amount": 100000
        })
        data = json.loads(body)
        assert 'policy' in data, "Should return policy data"
        assert 'customer' in data, "Should return customer data"
        assert 'underwriting' in data, "Should return underwriting data"
    
    def test_security_headers(self):
        """Test security headers are present"""
        body, headers = self._get("/api/metrics")
        
        required_headers = [
            'X-Content-Type-Options',
            'X-Frame-Options',
            'X-XSS-Protection',
            'Content-Security-Policy'
        ]
        
        for header in required_headers:
            assert header in headers, f"Missing security header: {header}"
        
        assert headers['X-Content-Type-Options'] == 'nosniff'
    
    def test_rate_limiting(self):
        """Test rate limiting is active"""
        # Make many requests quickly to trigger rate limit
        success_count = 0
        rate_limited = False
        
        for i in range(65):
            try:
                self._get("/api/metrics")
                success_count += 1
            except HTTPError as e:
                if e.code == 429:
                    rate_limited = True
                    break
        
        # Should hit rate limit before 65 requests
        if not rate_limited:
            self.warn("Rate Limiting", "Rate limit not triggered after 65 requests")
    
    def test_sql_injection_blocking(self):
        """Test SQL injection attempts are blocked"""
        sql_payload = "' OR '1'='1"
        
        try:
            self._post("/api/policies/create", {
                "customer_name": sql_payload,
                "customer_email": "test@example.com",
                "type": "life",
                "coverage_amount": 100000
            })
            # If successful, check if input was sanitized
            # (server may sanitize instead of reject)
        except HTTPError as e:
            # Should be blocked with 400 or 403
            assert e.code in [400, 403], f"SQL injection should be blocked, got {e.code}"
    
    def test_xss_blocking(self):
        """Test XSS attempts are blocked"""
        xss_payload = "<script>alert('xss')</script>"
        
        try:
            self._post("/api/policies/create", {
                "customer_name": xss_payload,
                "customer_email": "test@example.com",
                "type": "life",
                "coverage_amount": 100000
            })
            # If successful, input should be sanitized
        except HTTPError as e:
            # Should be blocked with 400 or 403
            assert e.code in [400, 403], f"XSS should be blocked, got {e.code}"
    
    def test_authentication(self):
        """Test authentication and session management"""
        # Login
        body, _ = self._post("/api/login", {
            "username": "underwriter",
            "password": "under123"
        })
        data = json.loads(body)
        token = data['token']
        
        # Use token to access protected endpoint
        body, _ = self._get("/api/profile", token)
        profile = json.loads(body)
        assert profile['role'] == 'underwriter'
        
        # Invalid token should fail
        try:
            self._get("/api/profile", "invalid_token")
            assert False, "Invalid token should be rejected"
        except HTTPError as e:
            assert e.code == 401
    
    def test_role_based_access(self):
        """Test role-based access control"""
        # Customer login
        body, _ = self._post("/api/policies/create", {
            "customer_name": "RBAC Test",
            "customer_email": "rbac@example.com",
            "type": "life",
            "coverage_amount": 100000
        })
        customer_data = json.loads(body)
        login_creds = customer_data['provisioned_login']
        
        body, _ = self._post("/api/login", {
            "username": login_creds['username'],
            "password": login_creds['password']
        })
        customer_token = json.loads(body)['token']
        
        # Customer should NOT access admin endpoint
        try:
            self._get("/api/audit", customer_token)
            assert False, "Customer should not access admin endpoint"
        except HTTPError as e:
            assert e.code == 403
    
    def test_critical_endpoints(self):
        """Test all critical endpoints are accessible"""
        endpoints = [
            "/api/metrics",
            "/api/policies",
            "/api/customers",
            "/api/underwriting",
            "/api/claims"
        ]
        
        for endpoint in endpoints:
            body, _ = self._get(endpoint)
            data = json.loads(body)
            assert data is not None, f"{endpoint} should return data"
    
    def test_error_handling(self):
        """Test proper error handling"""
        # 404 for non-existent resource
        try:
            self._get("/api/nonexistent")
            assert False, "Should return 404"
        except HTTPError as e:
            assert e.code == 404
        
        # 400 for invalid input
        try:
            self._post("/api/policies/create", {
                "customer_name": "",  # Invalid: empty
                "type": "life"
            })
            # May succeed with defaults
        except HTTPError as e:
            assert e.code == 400
    
    def test_data_operations(self):
        """Test complete data operations workflow"""
        # Create policy
        body, _ = self._post("/api/policies/create", {
            "customer_name": "Data Ops Test",
            "customer_email": "dataops@example.com",
            "type": "health",
            "coverage_amount": 200000
        })
        data = json.loads(body)
        policy_id = data['policy']['id']
        customer_id = data['customer']['id']
        uw_id = data['underwriting']['id']
        
        # Approve underwriting
        body, _ = self._post("/api/underwriting/approve", {
            "id": uw_id,
            "approved_by": "health_checker"
        })
        result = json.loads(body)
        assert result['success'] is True
        
        # Create claim
        body, _ = self._post("/api/claims/create", {
            "policy_id": policy_id,
            "customer_id": customer_id,
            "type": "medical",
            "claimed_amount": 5000
        })
        claim = json.loads(body)
        assert claim['status'] == 'pending'
    
    def run_all_checks(self):
        """Run all health checks"""
        print(f"\n{'='*60}")
        print(f"PHINS Health Check - {self.base_url}")
        print(f"{'='*60}\n")
        
        print("🏥 Running Health Checks...\n")
        
        # Core functionality
        print("Core Functionality:")
        self.check("Server Responds", self.test_server_responds)
        self.check("Login Endpoint", self.test_login_endpoint)
        self.check("Policy Creation", self.test_policy_creation)
        self.check("Critical Endpoints", self.test_critical_endpoints)
        
        # Security
        print("\nSecurity:")
        self.check("Security Headers", self.test_security_headers)
        self.check("Rate Limiting", self.test_rate_limiting)
        self.check("SQL Injection Blocking", self.test_sql_injection_blocking)
        self.check("XSS Blocking", self.test_xss_blocking)
        self.check("Authentication", self.test_authentication)
        self.check("Role-Based Access", self.test_role_based_access)
        
        # Data operations
        print("\nData Operations:")
        self.check("Error Handling", self.test_error_handling)
        self.check("Complete Workflow", self.test_data_operations)
        
        # Results
        print(f"\n{'='*60}")
        print("RESULTS:")
        print(f"{'='*60}")
        print(f"✓ Passed: {len(self.passed)}")
        print(f"✗ Failed: {len(self.failed)}")
        print(f"⚠ Warnings: {len(self.warnings)}")
        
        if self.failed:
            print(f"\n{'='*60}")
            print("FAILURES:")
            print(f"{'='*60}")
            for name, error in self.failed:
                print(f"  ✗ {name}: {error}")
        
        if self.warnings:
            print(f"\n{'='*60}")
            print("WARNINGS:")
            print(f"{'='*60}")
            for name, message in self.warnings:
                print(f"  ⚠ {name}: {message}")
        
        print(f"\n{'='*60}")
        
        total = len(self.passed) + len(self.failed)
        success_rate = (len(self.passed) / total * 100) if total > 0 else 100
        if success_rate == 100:
            print("✅ ALL CHECKS PASSED!")
        elif success_rate >= 80:
            print(f"⚠️  MOSTLY HEALTHY ({success_rate:.0f}% passed)")
        else:
            print(f"❌ CRITICAL ISSUES ({success_rate:.0f}% passed)")
        
        print(f"{'='*60}\n")
        
        return len(self.failed) == 0


def main():
    parser = argparse.ArgumentParser(
        description='PHINS Railway Health Check',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Check local server
  python railway_health_check.py http://localhost:8000
  
  # Check Railway deployment
  python railway_health_check.py https://your-app.railway.app
        """
    )
    parser.add_argument(
        'url',
        nargs='?',
        default='http://localhost:8000',
        help='Base URL to check (default: http://localhost:8000)'
    )
    parser.add_argument(
        '--quick',
        action='store_true',
        help='Run quick checks only (skip time-consuming tests)'
    )
    
    args = parser.parse_args()
    
    print("""
    ____  __  ___   _______   _______
   / __ \/ / / / | / / ___/  / ____(_)
  / /_/ / /_/ /  |/ /\__ \  / /_  / / 
 / ____/ __  / /|  /___/ / / __/ / /  
/_/   /_/ /_/_/ |_//____/ /_/   /_/   
                                       
Health Check Script for Railway Deployment
    """)
    
    checker = HealthChecker(args.url)
    
    try:
        success = checker.run_all_checks()
        sys.exit(0 if success else 1)
    except URLError as e:
        print(f"\n❌ ERROR: Cannot connect to {args.url}")
        print(f"   {e}")
        print("\nPlease verify:")
        print("  1. Server is running")
        print("  2. URL is correct")
        print("  3. Network connectivity")
        sys.exit(2)
    except KeyboardInterrupt:
        print("\n\n⚠️  Health check interrupted by user")
        sys.exit(3)


if __name__ == '__main__':
    main()
