"""
API Integration Test Suite

Tests every API endpoint for correctness and proper behavior:
- Authentication endpoints (login, register, profile)
- Policy management (create, list, get)
- Underwriting (approve, reject, list)
- Claims (create, approve, reject, pay)
- Billing (create, pay)
- Customer management
- Business Intelligence
- Admin/Security endpoints
"""

import threading
import time
import json
from datetime import datetime, timedelta
from http.server import HTTPServer
from urllib.request import urlopen, Request
from urllib.error import HTTPError
from unittest.mock import patch
from types import SimpleNamespace

from security import auth_tokens
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


def _request_and_verify_registration_otp(base_url: str, email: str) -> str:
    """Request + verify OTP and return verification_id."""
    otp_body, otp_status = _post(base_url + "/api/security/otp/request", {
        "email": email,
        "purpose": "registration",
        "user_type": "customer"
    })
    assert otp_status == 200
    otp_data = json.loads(otp_body)

    verification_id = otp_data.get('verification_id') or otp_data.get('data', {}).get('verification_id')
    otp_code = otp_data.get('demo_otp_code') or otp_data.get('data', {}).get('otp_code')
    assert verification_id, f"Missing verification_id in OTP response: {otp_data}"
    assert otp_code, f"Missing OTP code in OTP response: {otp_data}"

    verify_body, verify_status = _post(base_url + "/api/security/otp/verify", {
        "verification_id": verification_id,
        "otp_code": otp_code
    })
    assert verify_status == 200
    verify_data = json.loads(verify_body)
    assert verify_data.get('success') is True

    return verification_id


def test_login_endpoint():
    """Test POST /api/login"""
    port = 8031
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.2)
    
    base = f"http://127.0.0.1:{port}"
    
    # Test admin login
    body, status = _post(base + "/api/login", {
        "username": "admin",
        "password": "admin123"
    })
    assert status == 200
    data = json.loads(body)
    assert 'token' in data
    assert data['token'].startswith('phins_')
    assert data['role'] == 'admin'
    assert data['username'] == 'admin'
    
    # Test underwriter login
    body, status = _post(base + "/api/login", {
        "username": "underwriter",
        "password": "under123"
    })
    assert status == 200
    data = json.loads(body)
    assert data['role'] == 'underwriter'
    
    # Test claims adjuster login
    body, status = _post(base + "/api/login", {
        "username": "claims_adjuster",
        "password": "claims123"
    })
    assert status == 200
    data = json.loads(body)
    assert data['role'] == 'claims'
    
    # Test accountant login
    body, status = _post(base + "/api/login", {
        "username": "accountant",
        "password": "acct123"
    })
    assert status == 200
    data = json.loads(body)
    assert data['role'] == 'accountant'
    
    # Test invalid credentials
    try:
        _post(base + "/api/login", {
            "username": "admin",
            "password": "wrongpassword"
        })
        assert False, "Should fail with wrong password"
    except HTTPError as e:
        assert e.code == 401
    
    srv.stop()


def test_login_stores_v2_jti_in_session(monkeypatch):
    with portal.STATE_LOCK:
        portal.SESSIONS.clear()

    monkeypatch.setenv("SESSION_SECRET_KEY", "s" * 48)
    auth_tokens.set_secret_provider_for_tests(None)

    port = 8039
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.2)

    base = f"http://127.0.0.1:{port}"

    try:
        body, status = _post(base + "/api/login", {
            "username": "admin",
            "password": "admin123"
        })
        assert status == 200

        data = json.loads(body)
        token = data["token"]
        claims = auth_tokens.verify_v2_token(token)

        assert claims is not None
        with portal.STATE_LOCK:
            session = portal.SESSIONS[token]
        assert session["jti"] == claims.jti
    finally:
        srv.stop()


def test_login_rejects_captcha_token_when_validation_errors(monkeypatch):
    port = 8060
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.2)

    base = f"http://127.0.0.1:{port}"

    class _ExplodingLock:
        def __enter__(self):
            raise RuntimeError("captcha unavailable")

        def __exit__(self, exc_type, exc, tb):
            return False

    exploding_service = SimpleNamespace(
        _lock=_ExplodingLock(),
        _challenges={},
    )

    monkeypatch.setattr(portal, "PHINS_TEST_MODE", False)
    with portal.STATE_LOCK:
        portal.FAILED_LOGINS.clear()

    with patch("services.otp_security_service.get_otp_security_service", return_value=exploding_service):
        try:
            _post(base + "/api/login", {
                "username": "admin",
                "password": "admin123",
                "captcha_token": "CAPTCHA_test"
            })
            assert False, "Expected CAPTCHA validation failure"
        except HTTPError as e:
            assert e.code == 503
            data = json.loads(e.read().decode("utf-8"))
            assert data["error"] == "CAPTCHA validation unavailable. Please try again."

    with portal.STATE_LOCK:
        assert portal.FAILED_LOGINS == {}

    srv.stop()


def test_login_requires_captcha_token_outside_test_mode(monkeypatch):
    port = 8061
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.2)

    base = f"http://127.0.0.1:{port}"

    monkeypatch.setattr(portal, "PHINS_TEST_MODE", False)
    with portal.STATE_LOCK:
        portal.FAILED_LOGINS.clear()

    try:
        _post(base + "/api/login", {
            "username": "admin",
            "password": "admin123"
        })
        assert False, "Expected missing CAPTCHA token to be rejected"
    except HTTPError as e:
        assert e.code == 400
        data = json.loads(e.read().decode("utf-8"))
        assert data["error"] == "CAPTCHA verification required. Please reload and try again."
    finally:
        srv.stop()


def test_login_consumes_verified_captcha_token(monkeypatch):
    port = 8062
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.2)

    base = f"http://127.0.0.1:{port}"
    captcha_token = "CAPTCHA_test"
    verified_service = SimpleNamespace(
        _lock=threading.Lock(),
        _challenges={
            captcha_token: SimpleNamespace(
                verified=True,
                expires_at=datetime.now() + timedelta(minutes=5),
            )
        },
    )

    monkeypatch.setattr(portal, "PHINS_TEST_MODE", False)
    with portal.STATE_LOCK:
        portal.FAILED_LOGINS.clear()

    with patch("services.otp_security_service.get_otp_security_service", return_value=verified_service):
        try:
            body, status = _post(base + "/api/login", {
                "username": "admin",
                "password": "admin123",
                "captcha_token": captcha_token
            })
            assert status == 200
            assert json.loads(body)["username"] == "admin"
            assert captcha_token not in verified_service._challenges

            try:
                _post(base + "/api/login", {
                    "username": "admin",
                    "password": "admin123",
                    "captcha_token": captcha_token
                })
                assert False, "Expected replayed CAPTCHA token to be rejected"
            except HTTPError as e:
                assert e.code == 400
                data = json.loads(e.read().decode("utf-8"))
                assert data["error"] == "CAPTCHA verification required. Please reload and try again."
        finally:
            srv.stop()


def test_register_endpoint():
    """Test POST /api/register (with invitation code)"""
    port = 8032
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.2)
    
    base = f"http://127.0.0.1:{port}"
    
    # Test invitation code - use the test mode code (TESTCODE2026)
    # This is automatically created when PHINS_TEST_MODE=1
    test_invitation_code = "TESTCODE2026"
    
    # Test successful registration with invitation code
    body, status = _post(base + "/api/register", {
        "name": "New Customer",
        "email": "newcustomer@example.com",
        "password": "secure123456",
        "phone": "555-9999",
        "dob": "1990-01-01",
        "invitation_code": test_invitation_code
    })
    assert status == 201
    data = json.loads(body)
    assert data['success'] is True
    assert 'customer_id' in data
    assert data['email'] == "newcustomer@example.com"
    
    # Test duplicate registration
    try:
        _post(base + "/api/register", {
            "name": "New Customer 2",
            "email": "newcustomer@example.com",
            "password": "secure123456",
            "phone": "555-8888",
            "invitation_code": test_invitation_code
        })
        assert False, "Should fail with duplicate email"
    except HTTPError as e:
        assert e.code == 409
    
    # Test missing invitation code (should fail with 400)
    try:
        _post(base + "/api/register", {
            "name": "No Invitation User",
            "email": "noinvite@example.com",
            "password": "secure123456",
            "phone": "555-1111"
        })
        assert False, "Should fail without invitation code"
    except HTTPError as e:
        assert e.code == 400
    
    srv.stop()


def test_register_allows_legacy_invalid_verification_payload_when_invitation_is_valid():
    """Invitation-only registration should ignore legacy OTP payload fields."""
    port = 8123
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.2)

    base = f"http://127.0.0.1:{port}"

    try:
        body, status = _post(base + "/api/register", {
            "name": "Legacy OTP Payload User",
            "email": "legacyotp@example.com",
            "password": "secure123456",
            "phone": "555-3333",
            "invitation_code": "TESTCODE2026",
            "email_verified": False,
            "verification_id": "OTP_INVALID_TEST_ID"
        })
        assert status == 201
        payload = json.loads(body)
        assert payload.get('success') is True
        assert payload.get('customer_id')
    finally:
        srv.stop()


def test_registration_invitation_only_flow_preserves_data_integrity():
    """Invitation usage limits are enforced without any OTP dependency."""
    port = 8125
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.2)

    base = f"http://127.0.0.1:{port}"
    primary_invite = "FLOWOTP2026A"
    replay_invite = "FLOWOTP2026B"
    portal.INVITATION_CODES[primary_invite] = {
        "code": primary_invite,
        "status": "active",
        "used_count": 0,
        "max_uses": 1,
        "created_by": "admin",
        "created_at": "2026-01-01T00:00:00",
        "expires_at": "2099-12-31T23:59:59",
    }
    portal.INVITATION_CODES[replay_invite] = {
        "code": replay_invite,
        "status": "active",
        "used_count": 0,
        "max_uses": 1,
        "created_by": "admin",
        "created_at": "2026-01-01T00:00:00",
        "expires_at": "2099-12-31T23:59:59",
    }

    try:
        register_body, register_status = _post(base + "/api/register", {
            "name": "First Invite User",
            "email": "invitation-flow-primary@example.com",
            "password": "SecureFlow123",
            "phone": "555-2222",
            "dob": "1991-02-03",
            "invitation_code": primary_invite,
            "email_verified": False,
            "verification_id": "OTP_UNUSED_PLACEHOLDER"
        })
        assert register_status == 201
        register_data = json.loads(register_body)
        assert register_data.get("success") is True
        primary_customer_id = register_data.get("customer_id")
        assert primary_customer_id
        assert "invitation-flow-primary@example.com" in portal.USERS
        assert primary_customer_id in portal.CUSTOMERS
        assert portal.INVITATION_CODES[primary_invite]["used_count"] == 1
        assert portal.INVITATION_CODES[primary_invite]["status"] == "used"

        try:
            _post(base + "/api/register", {
                "name": "Primary Invite Replay User",
                "email": "invitation-flow-replay@example.com",
                "password": "SecureReplay123",
                "phone": "555-9999",
                "dob": "1992-03-04",
                "invitation_code": primary_invite,
                "email_verified": True,
                "verification_id": "OTP_UNUSED_PLACEHOLDER"
            })
            assert False, "Registration should fail when invitation code is already used"
        except HTTPError as e:
            assert e.code == 400
            replay_payload = json.loads(e.read().decode("utf-8"))
            assert replay_payload.get("code") == "CODE_USED"
            assert "invitation-flow-replay@example.com" not in portal.USERS

        replay_register_body, replay_register_status = _post(base + "/api/register", {
            "name": "Replay Invite Success User",
            "email": "invitation-flow-secondary@example.com",
            "password": "SecureReplaySuccess123",
            "phone": "555-4444",
            "dob": "1990-08-15",
            "invitation_code": replay_invite,
        })
        assert replay_register_status == 201
        replay_register_data = json.loads(replay_register_body)
        assert replay_register_data.get("success") is True
        assert replay_register_data.get("customer_id")
        assert portal.INVITATION_CODES[replay_invite]["used_count"] == 1
        assert portal.INVITATION_CODES[replay_invite]["status"] == "used"
    finally:
        srv.stop()


def test_otp_resend_endpoint_active():
    """OTP resend endpoint should actively issue a fresh code."""
    port = 8124
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.2)

    base = f"http://127.0.0.1:{port}"

    # Reduce cooldown for deterministic testing.
    import services.otp_security_service as otp_security
    original_cooldown = otp_security.OTPSecurityConfig.OTP_RESEND_COOLDOWN_SECONDS
    otp_security.OTPSecurityConfig.OTP_RESEND_COOLDOWN_SECONDS = 0
    otp_security.reset_otp_security_service()

    try:
        otp_body, otp_status = _post(base + "/api/security/otp/request", {
            "email": "resend_test@example.com",
            "purpose": "registration",
            "user_type": "customer"
        })
        assert otp_status == 200
        otp_data = json.loads(otp_body)
        verification_id = otp_data.get('verification_id') or otp_data.get('data', {}).get('verification_id')
        assert verification_id

        resend_body, resend_status = _post(base + "/api/security/otp/resend", {
            "verification_id": verification_id
        })
        assert resend_status == 200
        resend_data = json.loads(resend_body)
        assert resend_data.get('success') is True
        assert resend_data.get('verification_id') == verification_id
    finally:
        otp_security.OTPSecurityConfig.OTP_RESEND_COOLDOWN_SECONDS = original_cooldown
        otp_security.reset_otp_security_service()
        srv.stop()


def test_profile_endpoint():
    """Test GET /api/profile"""
    port = 8033
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.2)
    
    base = f"http://127.0.0.1:{port}"
    
    # Login first
    login_body, _ = _post(base + "/api/login", {
        "username": "admin",
        "password": "admin123"
    })
    token = json.loads(login_body)['token']
    
    # Get profile
    body, status = _get(base + "/api/profile", token)
    assert status == 200
    data = json.loads(body)
    assert data['username'] == 'admin'
    assert data['role'] == 'admin'
    assert data['name'] == 'Admin User'
    
    # Test unauthorized access
    try:
        _get(base + "/api/profile")
        assert False, "Should fail without token"
    except HTTPError as e:
        assert e.code == 401
    
    srv.stop()


def test_policies_create_endpoint():
    """Test POST /api/policies/create"""
    port = 8034
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.2)
    
    base = f"http://127.0.0.1:{port}"
    
    # Test successful policy creation
    body, status = _post(base + "/api/policies/create", {
        "customer_name": "Test Policy Customer",
        "customer_email": "policy@example.com",
        "customer_phone": "555-1111",
        "type": "life",
        "coverage_amount": 250000,
        "risk_score": "low",
        "age": 30
    })
    assert status == 201
    data = json.loads(body)
    assert 'policy' in data
    assert 'customer' in data
    assert 'underwriting' in data
    assert 'provisioned_login' in data
    assert data['policy']['status'] == 'pending_underwriting'
    assert data['policy']['coverage_amount'] == 250000
    
    # Test missing customer name
    try:
        _post(base + "/api/policies/create", {
            "customer_email": "test2@example.com",
            "type": "health",
            "coverage_amount": 100000
        })
        assert False, "Should fail without customer name"
    except HTTPError as e:
        assert e.code == 400
    
    # Test invalid coverage amount
    try:
        _post(base + "/api/policies/create", {
            "customer_name": "Test",
            "customer_email": "test3@example.com",
            "coverage_amount": 999999999999  # Too large
        })
        assert False, "Should fail with invalid amount"
    except HTTPError as e:
        assert e.code == 400
    
    srv.stop()


def test_policies_list_endpoint():
    """Test GET /api/policies with pagination"""
    port = 8035
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.2)
    
    base = f"http://127.0.0.1:{port}"
    
    # Create some policies first
    for i in range(5):
        _post(base + "/api/policies/create", {
            "customer_name": f"List Test {i}",
            "customer_email": f"list{i}@example.com",
            "type": "life",
            "coverage_amount": 100000
        })
    
    # Test listing all policies
    body, status = _get(base + "/api/policies")
    assert status == 200
    data = json.loads(body)
    assert 'items' in data
    assert 'page' in data
    assert 'page_size' in data
    assert 'total' in data
    assert len(data['items']) >= 5
    
    # Test pagination
    body, status = _get(base + "/api/policies?page=1&page_size=2")
    assert status == 200
    data = json.loads(body)
    assert len(data['items']) == 2
    assert data['page'] == 1
    assert data['page_size'] == 2
    
    srv.stop()


def test_policies_get_by_id_endpoint():
    """Test GET /api/policies?id={id}"""
    port = 8036
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.2)
    
    base = f"http://127.0.0.1:{port}"
    
    # Create a policy
    body, _ = _post(base + "/api/policies/create", {
        "customer_name": "Get Test",
        "customer_email": "get@example.com",
        "type": "auto",
        "coverage_amount": 50000
    })
    policy_id = json.loads(body)['policy']['id']
    
    # Get specific policy
    body, status = _get(base + f"/api/policies?id={policy_id}")
    assert status == 200
    data = json.loads(body)
    assert data['id'] == policy_id
    assert data['type'] == 'auto'
    assert data['coverage_amount'] == 50000
    
    # Test non-existent policy
    try:
        body, status = _get(base + "/api/policies?id=NONEXISTENT")
    except HTTPError as e:
        body = e.read().decode('utf-8')
        status = e.code
    assert status == 404
    
    srv.stop()


def test_underwriting_list_endpoint():
    """Test GET /api/underwriting"""
    port = 8037
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.2)
    
    base = f"http://127.0.0.1:{port}"
    
    # Create policies with underwriting apps
    for i in range(3):
        _post(base + "/api/policies/create", {
            "customer_name": f"UW Test {i}",
            "customer_email": f"uw{i}@example.com",
            "type": "life",
            "coverage_amount": 100000,
            "risk_score": ["low", "medium", "high"][i]
        })
    
    # List all underwriting applications
    body, status = _get(base + "/api/underwriting")
    assert status == 200
    data = json.loads(body)
    assert isinstance(data, list)
    assert len(data) >= 3
    
    srv.stop()


def test_underwriting_approve_endpoint():
    """Test POST /api/underwriting/approve"""
    port = 8038
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.2)
    
    base = f"http://127.0.0.1:{port}"
    
    # Create policy
    body, _ = _post(base + "/api/policies/create", {
        "customer_name": "Approve Test",
        "customer_email": "approve@example.com",
        "type": "life",
        "coverage_amount": 200000
    })
    uw_id = json.loads(body)['underwriting']['id']
    policy_id = json.loads(body)['policy']['id']
    
    # Approve underwriting
    body, status = _post(base + "/api/underwriting/approve", {
        "id": uw_id,
        "approved_by": "test_underwriter"
    })
    assert status == 200
    data = json.loads(body)
    assert data['success'] is True
    assert data['application']['status'] == 'approved'
    
    # Verify policy status changed
    body, _ = _get(base + f"/api/policies?id={policy_id}")
    policy = json.loads(body)
    assert policy['status'] == 'active'
    
    srv.stop()


def test_underwriting_reject_endpoint():
    """Test POST /api/underwriting/reject"""
    port = 8039
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.2)
    
    base = f"http://127.0.0.1:{port}"
    
    # Create policy
    body, _ = _post(base + "/api/policies/create", {
        "customer_name": "Reject Test",
        "customer_email": "reject@example.com",
        "type": "life",
        "coverage_amount": 150000,
        "risk_score": "very_high"
    })
    uw_id = json.loads(body)['underwriting']['id']
    policy_id = json.loads(body)['policy']['id']
    
    # Reject underwriting
    body, status = _post(base + "/api/underwriting/reject", {
        "id": uw_id,
        "reason": "High risk factors",
        "rejected_by": "test_underwriter"
    })
    assert status == 200
    data = json.loads(body)
    assert data['success'] is True
    assert data['application']['status'] == 'rejected'
    assert 'rejection_reason' in data['application']
    
    # Verify policy status changed
    body, _ = _get(base + f"/api/policies?id={policy_id}")
    policy = json.loads(body)
    assert policy['status'] == 'rejected'
    
    srv.stop()


def test_claims_create_endpoint():
    """Test POST /api/claims/create"""
    port = 8040
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.2)
    
    base = f"http://127.0.0.1:{port}"
    
    # Create and approve policy first
    body, _ = _post(base + "/api/policies/create", {
        "customer_name": "Claims Test",
        "customer_email": "claims@example.com",
        "type": "health",
        "coverage_amount": 300000
    })
    policy_id = json.loads(body)['policy']['id']
    customer_id = json.loads(body)['customer']['id']
    uw_id = json.loads(body)['underwriting']['id']
    
    _post(base + "/api/underwriting/approve", {"id": uw_id})
    
    # Create claim
    body, status = _post(base + "/api/claims/create", {
        "policy_id": policy_id,
        "customer_id": customer_id,
        "type": "medical",
        "description": "Hospital visit",
        "claimed_amount": 25000
    })
    assert status == 201
    data = json.loads(body)
    assert data['status'] == 'pending'
    assert data['claimed_amount'] == 25000
    assert data['policy_id'] == policy_id
    
    srv.stop()


def test_claims_list_endpoint():
    """Test GET /api/claims with status filter"""
    port = 8041
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.2)
    
    base = f"http://127.0.0.1:{port}"
    
    # Create policy and claims
    body, _ = _post(base + "/api/policies/create", {
        "customer_name": "Claims List Test",
        "customer_email": "claimslist@example.com",
        "type": "health",
        "coverage_amount": 200000
    })
    policy_id = json.loads(body)['policy']['id']
    customer_id = json.loads(body)['customer']['id']
    
    for i in range(3):
        _post(base + "/api/claims/create", {
            "policy_id": policy_id,
            "customer_id": customer_id,
            "type": "medical",
            "description": f"Claim {i}",
            "claimed_amount": 10000 * (i + 1)
        })
    
    # List all claims
    body, status = _get(base + "/api/claims")
    assert status == 200
    data = json.loads(body)
    assert 'items' in data
    assert len(data['items']) >= 3
    
    # List pending claims only
    body, status = _get(base + "/api/claims?status=pending")
    assert status == 200
    data = json.loads(body)
    all_pending = all(c['status'] == 'pending' for c in data['items'])
    assert all_pending
    
    srv.stop()


def test_claims_approve_endpoint():
    """Test POST /api/claims/approve"""
    port = 8042
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.2)
    
    base = f"http://127.0.0.1:{port}"
    
    # Create policy and claim
    body, _ = _post(base + "/api/policies/create", {
        "customer_name": "Claim Approve Test",
        "customer_email": "claimapprove@example.com",
        "type": "health",
        "coverage_amount": 200000
    })
    policy_id = json.loads(body)['policy']['id']
    customer_id = json.loads(body)['customer']['id']
    
    body, _ = _post(base + "/api/claims/create", {
        "policy_id": policy_id,
        "customer_id": customer_id,
        "type": "medical",
        "claimed_amount": 30000
    })
    claim_id = json.loads(body)['id']
    
    # Approve claim
    body, status = _post(base + "/api/claims/approve", {
        "id": claim_id,
        "approved_amount": 28000,
        "approved_by": "test_adjuster",
        "notes": "Approved with deductible"
    })
    assert status == 200
    data = json.loads(body)
    assert data['success'] is True
    assert data['claim']['status'] == 'approved'
    assert data['claim']['approved_amount'] == 28000
    
    srv.stop()


def test_claims_reject_endpoint():
    """Test POST /api/claims/reject"""
    port = 8043
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.2)
    
    base = f"http://127.0.0.1:{port}"
    
    # Create policy and claim
    body, _ = _post(base + "/api/policies/create", {
        "customer_name": "Claim Reject Test",
        "customer_email": "claimreject@example.com",
        "type": "auto",
        "coverage_amount": 50000
    })
    policy_id = json.loads(body)['policy']['id']
    customer_id = json.loads(body)['customer']['id']
    
    body, _ = _post(base + "/api/claims/create", {
        "policy_id": policy_id,
        "customer_id": customer_id,
        "type": "accident",
        "claimed_amount": 15000
    })
    claim_id = json.loads(body)['id']
    
    # Reject claim
    body, status = _post(base + "/api/claims/reject", {
        "id": claim_id,
        "reason": "Not covered under policy",
        "rejected_by": "test_adjuster"
    })
    assert status == 200
    data = json.loads(body)
    assert data['success'] is True
    assert data['claim']['status'] == 'rejected'
    assert 'rejection_reason' in data['claim']
    
    srv.stop()


def test_claims_pay_endpoint():
    """Test POST /api/claims/pay"""
    port = 8044
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.2)
    
    base = f"http://127.0.0.1:{port}"
    
    # Create, approve and pay claim
    body, _ = _post(base + "/api/policies/create", {
        "customer_name": "Claim Pay Test",
        "customer_email": "claimpay@example.com",
        "type": "health",
        "coverage_amount": 200000
    })
    policy_id = json.loads(body)['policy']['id']
    customer_id = json.loads(body)['customer']['id']
    
    body, _ = _post(base + "/api/claims/create", {
        "policy_id": policy_id,
        "customer_id": customer_id,
        "type": "medical",
        "claimed_amount": 20000
    })
    claim_id = json.loads(body)['id']
    
    # Must approve first
    _post(base + "/api/claims/approve", {
        "id": claim_id,
        "approved_amount": 20000
    })
    
    # Pay claim
    body, status = _post(base + "/api/claims/pay", {
        "id": claim_id,
        "payment_method": "bank_transfer",
        "processed_by": "test_accountant"
    })
    assert status == 200
    data = json.loads(body)
    assert data['success'] is True
    assert data['claim']['status'] == 'paid'
    assert 'payment_reference' in data['claim']
    assert data['claim']['paid_amount'] == 20000
    
    srv.stop()


def test_billing_create_endpoint():
    """Test POST /api/billing/create"""
    port = 8045
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.2)
    
    base = f"http://127.0.0.1:{port}"
    
    # Create policy first
    body, _ = _post(base + "/api/policies/create", {
        "customer_name": "Billing Test",
        "customer_email": "billing@example.com",
        "type": "life",
        "coverage_amount": 200000
    })
    policy_id = json.loads(body)['policy']['id']
    
    # Create bill
    body, status = _post(base + "/api/billing/create", {
        "policy_id": policy_id,
        "amount_due": 1500.00,
        "due_days": 30
    })
    assert status == 201
    data = json.loads(body)
    assert 'bill' in data
    assert data['bill']['status'] == 'outstanding'
    assert data['bill']['amount_due'] == 1500.00
    assert data['bill']['amount_paid'] == 0.0
    
    srv.stop()


def test_billing_pay_endpoint():
    """Test POST /api/billing/pay"""
    port = 8046
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.2)
    
    base = f"http://127.0.0.1:{port}"
    
    # Create policy and bill
    body, _ = _post(base + "/api/policies/create", {
        "customer_name": "Bill Pay Test",
        "customer_email": "billpay@example.com",
        "type": "life",
        "coverage_amount": 150000
    })
    policy_id = json.loads(body)['policy']['id']
    
    body, _ = _post(base + "/api/billing/create", {
        "policy_id": policy_id,
        "amount_due": 1200.00,
        "due_days": 30
    })
    bill_id = json.loads(body)['bill']['bill_id']
    
    # Pay partial amount
    body, status = _post(base + "/api/billing/pay", {
        "bill_id": bill_id,
        "amount": 600.00
    })
    assert status == 200
    data = json.loads(body)
    assert data['bill']['status'] == 'partial'
    assert data['bill']['amount_paid'] == 600.00
    
    # Pay remaining amount
    body, status = _post(base + "/api/billing/pay", {
        "bill_id": bill_id,
        "amount": 600.00
    })
    assert status == 200
    data = json.loads(body)
    assert data['bill']['status'] == 'paid'
    assert data['bill']['amount_paid'] == 1200.00
    
    srv.stop()


def test_customers_endpoint():
    """Test GET /api/customers"""
    port = 8047
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.2)
    
    base = f"http://127.0.0.1:{port}"
    
    # Create customers
    for i in range(3):
        _post(base + "/api/policies/create", {
            "customer_name": f"Customer {i}",
            "customer_email": f"customer{i}@example.com",
            "type": "life",
            "coverage_amount": 100000
        })
    
    # List all customers
    body, status = _get(base + "/api/customers")
    assert status == 200
    data = json.loads(body)
    assert isinstance(data, list)
    assert len(data) >= 3
    
    srv.stop()


def test_customer_status_endpoint():
    """Test GET /api/customer/status"""
    port = 8048
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.2)
    
    base = f"http://127.0.0.1:{port}"
    
    # Create customer and policy
    body, _ = _post(base + "/api/policies/create", {
        "customer_name": "Status Test",
        "customer_email": "status@example.com",
        "type": "life",
        "coverage_amount": 100000
    })
    customer_id = json.loads(body)['customer']['id']
    
    # Get customer status
    body, status = _get(base + f"/api/customer/status?customer_id={customer_id}")
    assert status == 200
    data = json.loads(body)
    assert 'customer' in data
    assert 'overall_status' in data
    assert 'policies' in data
    assert 'underwriting_applications' in data
    assert data['customer']['id'] == customer_id
    
    srv.stop()


def test_metrics_endpoint():
    """Test GET /api/metrics"""
    port = 8049
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.2)
    
    base = f"http://127.0.0.1:{port}"
    
    # Get metrics
    body, status = _get(base + "/api/metrics")
    assert status == 200
    data = json.loads(body)
    assert 'metrics' in data
    assert 'ts' in data
    
    srv.stop()


def test_metrics_endpoint_fallback_counts_partial_bills_as_outstanding():
    """Fallback metrics should count partial bills as outstanding, not pending bills."""
    port = 8089
    srv = ServerThread(port)
    partial_id = 'TEST-METRICS-PARTIAL-001'
    pending_id = 'TEST-METRICS-PENDING-001'
    previous_bills = {
        partial_id: portal.BILLING.get(partial_id),
        pending_id: portal.BILLING.get(pending_id),
    }

    try:
        srv.start()
        time.sleep(0.2)
        portal._TEST_PORTS_INITIALIZED.add(port)

        baseline_outstanding = sum(
            1 for bill in portal.BILLING.values()
            if (
                not portal.is_suspended_account(bill.get('customer_id', ''))
                and portal.status_in(bill, ['outstanding', 'partial'])
            )
        )
        portal.BILLING[partial_id] = {
            'id': partial_id,
            'customer_id': 'CUST-TEST-METRICS-001',
            'policy_id': 'POL-TEST-METRICS-001',
            'amount': 200.0,
            'amount_due': 200.0,
            'amount_paid': 75.0,
            'status': 'partial',
        }
        portal.BILLING[pending_id] = {
            'id': pending_id,
            'customer_id': 'CUST-TEST-METRICS-002',
            'policy_id': 'POL-TEST-METRICS-002',
            'amount': 300.0,
            'amount_due': 300.0,
            'amount_paid': 0.0,
            'status': 'pending',
        }

        expected_outstanding = baseline_outstanding + 1

        base = f"http://127.0.0.1:{port}"
        with patch('services.metrics_service.MetricsService.summary', side_effect=RuntimeError('Force /api/metrics fallback path')):
            body, status = _get(base + "/api/metrics")

        assert status == 200
        data = json.loads(body)
        assert data['metrics']['billing']['outstanding'] == expected_outstanding
    finally:
        srv.stop()
        for bill_id, previous_bill in previous_bills.items():
            if previous_bill is None:
                portal.BILLING.pop(bill_id, None)
            else:
                portal.BILLING[bill_id] = previous_bill


def test_metrics_endpoint_fallback_excludes_medical_assessment_from_pending_claims():
    """Fallback metrics should match the legacy pending-claims definition."""
    port = 8091
    srv = ServerThread(port)
    pending_id = 'CLM-TEST-METRICS-PENDING-001'
    medical_id = 'CLM-TEST-METRICS-MEDICAL-001'
    previous_claims = {
        pending_id: portal.CLAIMS.get(pending_id),
        medical_id: portal.CLAIMS.get(medical_id),
    }

    try:
        srv.start()
        time.sleep(0.2)
        portal._TEST_PORTS_INITIALIZED.add(port)

        baseline_pending = sum(
            1 for claim_id, claim in portal.CLAIMS.items()
            if (
                claim_id not in {pending_id, medical_id}
                and not portal.is_suspended_account(claim.get('customer_id', ''))
                and portal.status_in(claim, ['pending', 'under_review'])
            )
        )
        portal.CLAIMS[pending_id] = {
            'id': pending_id,
            'customer_id': 'CUST-TEST-METRICS-CLAIMS-001',
            'policy_id': 'POL-TEST-METRICS-CLAIMS-001',
            'claimed_amount': 150.0,
            'status': 'pending',
        }
        portal.CLAIMS[medical_id] = {
            'id': medical_id,
            'customer_id': 'CUST-TEST-METRICS-CLAIMS-002',
            'policy_id': 'POL-TEST-METRICS-CLAIMS-002',
            'claimed_amount': 275.0,
            'status': 'medical_assessment',
        }

        base = f"http://127.0.0.1:{port}"
        with patch('services.metrics_service.MetricsService.summary', side_effect=RuntimeError('Force /api/metrics fallback path')):
            body, status = _get(base + "/api/metrics")

        assert status == 200
        data = json.loads(body)
        assert data['metrics']['claims']['pending'] == baseline_pending + 1
    finally:
        srv.stop()
        for claim_id, previous_claim in previous_claims.items():
            if previous_claim is None:
                portal.CLAIMS.pop(claim_id, None)
            else:
                portal.CLAIMS[claim_id] = previous_claim


def test_post_billing_stats_reports_unified_revenue():
    """POST /api/billing/stats should return policy revenue, not collected payments."""
    port = 8090
    srv = ServerThread(port)
    policy_id = 'POL-TEST-BILLING-STATS-001'
    paid_bill_id = 'BILL-TEST-BILLING-STATS-PAID-001'
    partial_bill_id = 'BILL-TEST-BILLING-STATS-PARTIAL-001'
    failed_bill_id = 'BILL-TEST-BILLING-STATS-FAILED-001'
    previous_policy = portal.POLICIES.get(policy_id)
    previous_bills = {
        paid_bill_id: portal.BILLING.get(paid_bill_id),
        partial_bill_id: portal.BILLING.get(partial_bill_id),
        failed_bill_id: portal.BILLING.get(failed_bill_id),
    }

    try:
        srv.start()
        time.sleep(0.2)
        portal._TEST_PORTS_INITIALIZED.add(port)

        baseline_transactions = sum(
            1 for bill_id, bill in portal.BILLING.items()
            if (
                bill_id not in {paid_bill_id, partial_bill_id, failed_bill_id}
                and not portal.is_suspended_account(bill.get('customer_id', ''))
            )
        )
        baseline_successful = sum(
            1 for bill_id, bill in portal.BILLING.items()
            if (
                bill_id not in {paid_bill_id, partial_bill_id, failed_bill_id}
                and not portal.is_suspended_account(bill.get('customer_id', ''))
                and portal.status_in(bill, ['paid', 'partial'])
            )
        )
        baseline_failed = sum(
            1 for bill_id, bill in portal.BILLING.items()
            if (
                bill_id not in {paid_bill_id, partial_bill_id, failed_bill_id}
                and not portal.is_suspended_account(bill.get('customer_id', ''))
                and portal.status_eq(bill, 'failed')
            )
        )
        baseline_revenue = round(sum(
            portal.safe_float(policy.get('annual_premium', 0), 0.0)
            for existing_policy_id, policy in portal.POLICIES.items()
            if (
                existing_policy_id != policy_id
                and not portal.is_suspended_account(policy.get('customer_id', ''))
                and portal.status_eq(policy, 'active')
            )
        ), 2)

        portal.POLICIES[policy_id] = {
            'id': policy_id,
            'customer_id': 'CUST-TEST-BILLING-STATS-001',
            'annual_premium': 1200.0,
            'monthly_premium': 100.0,
            'status': 'active',
        }
        portal.BILLING[paid_bill_id] = {
            'id': paid_bill_id,
            'customer_id': 'CUST-TEST-BILLING-STATS-001',
            'policy_id': policy_id,
            'amount': 100.0,
            'amount_due': 100.0,
            'amount_paid': 100.0,
            'status': 'paid',
        }
        portal.BILLING[partial_bill_id] = {
            'id': partial_bill_id,
            'customer_id': 'CUST-TEST-BILLING-STATS-001',
            'policy_id': policy_id,
            'amount': 100.0,
            'amount_due': 100.0,
            'amount_paid': 25.0,
            'status': 'partial',
        }
        portal.BILLING[failed_bill_id] = {
            'id': failed_bill_id,
            'customer_id': 'CUST-TEST-BILLING-STATS-001',
            'policy_id': policy_id,
            'amount': 100.0,
            'amount_due': 100.0,
            'amount_paid': 0.0,
            'status': 'failed',
        }

        base = f"http://127.0.0.1:{port}"
        body, status = _post(base + "/api/billing/stats", {})

        assert status == 200
        data = json.loads(body)
        assert data['total_transactions'] == baseline_transactions + 3
        assert data['successful_payments'] == baseline_successful + 2
        assert data['failed_payments'] == baseline_failed + 1
        assert data['total_revenue'] == baseline_revenue + 1200.0
    finally:
        srv.stop()
        if previous_policy is None:
            portal.POLICIES.pop(policy_id, None)
        else:
            portal.POLICIES[policy_id] = previous_policy
        for bill_id, previous_bill in previous_bills.items():
            if previous_bill is None:
                portal.BILLING.pop(bill_id, None)
            else:
                portal.BILLING[bill_id] = previous_bill


def test_audit_endpoint():
    """Test GET /api/audit (admin only)"""
    port = 8050
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.2)
    
    base = f"http://127.0.0.1:{port}"
    
    # Login as admin
    body, _ = _post(base + "/api/login", {
        "username": "admin",
        "password": "admin123"
    })
    admin_token = json.loads(body)['token']
    
    # Get audit logs
    body, status = _get(base + "/api/audit?page=1&page_size=10", admin_token)
    assert status == 200
    data = json.loads(body)
    assert 'items' in data
    assert 'page' in data
    assert 'page_size' in data
    assert 'total' in data
    
    # Test unauthorized access
    try:
        _get(base + "/api/audit")
        assert False, "Should require authentication"
    except HTTPError as e:
        assert e.code == 401
    
    srv.stop()


def test_security_threats_endpoint():
    """Test GET /api/security/threats (admin only)"""
    port = 8051
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.2)
    
    base = f"http://127.0.0.1:{port}"
    
    # Login as admin
    body, _ = _post(base + "/api/login", {
        "username": "admin",
        "password": "admin123"
    })
    admin_token = json.loads(body)['token']
    
    # Get security threats
    body, status = _get(base + "/api/security/threats", admin_token)
    assert status == 200
    data = json.loads(body)
    assert 'malicious_attempts' in data
    assert 'blocked_ips' in data
    assert 'failed_logins' in data
    assert 'statistics' in data
    
    srv.stop()


def test_bi_actuary_endpoint():
    """Test GET /api/bi/actuary"""
    port = 8052
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.2)
    
    base = f"http://127.0.0.1:{port}"
    
    # Login as admin
    body, _ = _post(base + "/api/login", {
        "username": "admin",
        "password": "admin123"
    })
    admin_token = json.loads(body)['token']
    
    # Get actuarial BI data
    body, status = _get(base + "/api/bi/actuary", admin_token)
    assert status == 200
    data = json.loads(body)
    assert 'total_policies' in data
    assert 'total_exposure' in data
    assert 'average_premium' in data
    assert 'risk_distribution' in data
    assert 'claims_ratio' in data
    assert 'reinsurance' in data
    
    srv.stop()


def test_reinsurance_simulation_binding_updates_balance_sheet():
    """Simulation-backed reinsurance binding should book balance-sheet expense."""
    port = 8152
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.2)

    base = f"http://127.0.0.1:{port}"

    body, _ = _post(base + "/api/login", {
        "username": "admin",
        "password": "admin123"
    })
    admin_token = json.loads(body)['token']

    try:
        sim_body, sim_status = _post(base + "/api/actuarial/simulate", {
            "customer_count": 5000,
            "age_min": 25,
            "age_max": 55,
            "age_mean": 39,
            "age_std": 8,
            "coverage_min": 100000,
            "coverage_max": 500000,
            "coverage_median": 220000,
            "policy_term_min": 10,
            "policy_term_max": 20,
            "policy_term_mode": "random",
            "male_pct": 49,
            "female_pct": 51,
            "ethnicity": {
                "caucasian": 60,
                "african": 13,
                "hispanic": 18,
                "asian": 6,
                "other": 3
            }
        }, admin_token)
        assert sim_status == 200
        sim_payload = json.loads(sim_body)
        simulation = sim_payload["simulation"]
        simulation_id = simulation["simulation_id"]
        assert simulation["reinsurance_program"]["selected_contracts"] > 0

        rec_body, rec_status = _get(
            base + f"/api/reinsurance/recommendation?simulation_id={simulation_id}&contract_count=1000&hedge_share_pct=30&objective=min_cost",
            admin_token
        )
        assert rec_status == 200
        rec_payload = json.loads(rec_body)
        assert rec_payload["success"] is True
        recommended = rec_payload["recommended"]
        assert recommended["phins_simulation_id"] == simulation_id
        assert recommended["phins_total_contract_cost"] > 0

        bind_body, bind_status = _post(base + "/api/reinsurance/contracts/bind", {
            "contract_name": "Simulation Treaty",
            "portfolio_id": simulation_id,
            "quote": recommended
        }, admin_token)
        assert bind_status == 201
        bind_payload = json.loads(bind_body)
        assert bind_payload["success"] is True
        assert bind_payload["simulation_id"] == simulation_id
        assert bind_payload["balance_sheet_transaction"]["category"] == "reinsurance"
        assert bind_payload["balance_sheet_transaction"]["amount"] > 0

        bs_body, bs_status = _get(base + "/api/admin/balance-sheet", admin_token)
        assert bs_status == 200
        balance_sheet = json.loads(bs_body)["balance_sheet"]
        assert balance_sheet["expense_breakdown"]["reinsurance"] >= bind_payload["balance_sheet_transaction"]["amount"]

        bi_body, bi_status = _get(base + "/api/bi/actuary", admin_token)
        assert bi_status == 200
        bi_payload = json.loads(bi_body)
        assert bi_payload["reinsurance"]["annual_expense_booked"] >= bind_payload["balance_sheet_transaction"]["amount"]
        assert bi_payload["reinsurance"]["latest_program"]["selected_contracts"] > 0
    finally:
        srv.stop()


def test_bi_underwriting_endpoint():
    """Test GET /api/bi/underwriting"""
    port = 8053
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.2)
    
    base = f"http://127.0.0.1:{port}"
    
    # Login as underwriter
    body, _ = _post(base + "/api/login", {
        "username": "underwriter",
        "password": "under123"
    })
    uw_token = json.loads(body)['token']
    
    # Get underwriting BI data
    body, status = _get(base + "/api/bi/underwriting", uw_token)
    assert status == 200
    data = json.loads(body)
    assert 'pending_applications' in data
    assert 'approved_this_month' in data
    assert 'rejection_rate' in data
    assert 'risk_assessment_distribution' in data


def test_admin_balance_sheet_reflects_collected_premium_breakdown():
    """Admin balance sheet should expose collected premium totals and breakdown."""
    port = 8054
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.2)

    base = f"http://127.0.0.1:{port}"

    body, _ = _post(base + "/api/login", {
        "username": "admin",
        "password": "admin123"
    })
    admin_token = json.loads(body)['token']

    # Create a simple policy/customer and pay its bill so premium income is collected.
    create_body, create_status = _post(base + "/api/policies/create", {
        "customer_name": "Balance Sheet Premium Test",
        "customer_email": "bs-premium@example.com",
        "type": "life",
        "coverage_amount": 100000
    }, admin_token)
    assert create_status in [200, 201]
    created = json.loads(create_body)
    policy_id = created["policy"]["id"]

    bill_body, bill_status = _post(base + "/api/billing/create", {
        "policy_id": policy_id,
        "amount_due": 250.0,
        "due_days": 30
    }, admin_token)
    assert bill_status in [200, 201]
    bill = json.loads(bill_body)["bill"]

    pay_body, pay_status = _post(base + "/api/billing/pay", {
        "bill_id": bill["id"],
        "amount": 250.0,
        "payment_method": "card"
    }, admin_token)
    assert pay_status == 200, pay_body

    bs_body, bs_status = _get(base + "/api/admin/balance-sheet", admin_token)
    assert bs_status == 200
    balance_sheet = json.loads(bs_body)["balance_sheet"]
    assert balance_sheet["cumulative_premium"] >= 250.0
    assert balance_sheet["revenue_breakdown"]["premium_income"] == balance_sheet["cumulative_premium"]
    assert "cumulative_premium_breakdown" in balance_sheet
    assert balance_sheet["cumulative_premium_breakdown"]["from_bills"] >= 250.0
    assert "from_ledger" in balance_sheet["cumulative_premium_breakdown"]

    srv.stop()
    
    srv.stop()


def test_bi_accounting_endpoint():
    """Test GET /api/bi/accounting"""
    port = 8054
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.2)
    
    base = f"http://127.0.0.1:{port}"
    
    # Login as accountant
    body, _ = _post(base + "/api/login", {
        "username": "accountant",
        "password": "acct123"
    })
    acct_token = json.loads(body)['token']
    
    # Get accounting BI data
    body, status = _get(base + "/api/bi/accounting", acct_token)
    assert status == 200
    data = json.loads(body)
    assert 'total_revenue' in data
    assert 'total_claims_paid' in data
    assert 'net_income' in data
    assert 'profit_margin' in data
    assert 'monthly_breakdown' in data
    
    srv.stop()
