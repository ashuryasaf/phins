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


def _seed_test_session(role='underwriter', username='underwriter', customer_id=None):
    """Inject a test session token directly into in-memory session store."""
    expires = datetime.now() + timedelta(hours=2)
    if hasattr(portal, '_create_signed_token'):
        token = portal._create_signed_token(username=username, role=role, customer_id=customer_id, expires=expires)
    else:
        token = f"phins_test_{username}_{int(time.time() * 1000000)}"
    portal.SESSIONS[token] = {
        'username': username,
        'role': role,
        'customer_id': customer_id,
        'expires': expires.isoformat()
    }
    return token


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


def test_underwriting_approval_enforces_default_autopay_schedule():
    """Policy approval should enforce auto-pay defaults on 1st billing day."""
    port = 8058
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.2)

    base = f"http://127.0.0.1:{port}"

    body, _ = _post(base + "/api/policies/create", {
        "customer_name": "AutoPay Default Test",
        "customer_email": "autopay-default@example.com",
        "type": "life",
        "coverage_amount": 125000,
        "payment": {
            "card_number": "4242424242424242",
            "cvv": "123",
            "expiry_month": "12",
            "expiry_year": "2032",
            "cardholder_name": "AUTOPAY TEST",
            "billing_frequency": "monthly",
            "auto_pay": False
        }
    })
    created = json.loads(body)
    uw_id = created["underwriting"]["id"]

    body, status = _post(base + "/api/underwriting/approve", {"id": uw_id})
    assert status == 200
    approved = json.loads(body)

    policy = approved["policy"]
    payment_setup = policy.get("payment_setup", {})
    assert payment_setup.get("auto_pay") is True
    assert payment_setup.get("billing_day") == 1
    assert payment_setup.get("payment_method") == "credit_card"

    next_billing = payment_setup.get("next_billing_date", "")
    assert len(next_billing) >= 10
    assert next_billing[8:10] == "01"

    bill = approved.get("bill", {})
    due_date = str(bill.get("due_date", ""))
    assert len(due_date) >= 10
    assert due_date[8:10] == "01"
    assert bill.get("auto_pay") is True

    srv.stop()


def test_billing_overpayment_creates_future_cover_credit():
    """Overpayments should become credits and appear as future cover."""
    port = 8059
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.2)

    base = f"http://127.0.0.1:{port}"

    body, _ = _post(base + "/api/policies/create", {
        "customer_name": "Future Cover Test",
        "customer_email": "future-cover@example.com",
        "type": "life",
        "coverage_amount": 90000
    })
    created = json.loads(body)
    policy_id = created["policy"]["id"]
    customer_id = created["customer"]["id"]

    # Activate policy so customer status computes future cover against active premium.
    uw_id = created["underwriting"]["id"]
    _post(base + "/api/underwriting/approve", {"id": uw_id})

    body, _ = _post(base + "/api/billing/create", {
        "policy_id": policy_id,
        "amount_due": 100.0,
        "due_days": 30
    })
    bill_id = json.loads(body)["bill"]["bill_id"]

    body, status = _post(base + "/api/billing/pay", {
        "bill_id": bill_id,
        "amount": 250.0
    })
    assert status == 200
    payment_result = json.loads(body)
    assert payment_result["amount_applied_to_bill"] == 100.0
    assert payment_result["overpayment_amount"] == 150.0
    assert payment_result["bill"]["amount_paid"] == 100.0
    assert payment_result["overpayment_credit"]["created"] is True

    body, status = _get(base + f"/api/customer/status?customer_id={customer_id}")
    assert status == 200
    customer_status = json.loads(body)
    billing_summary = customer_status.get("billing_summary", {})
    assert billing_summary.get("future_cover_credit_balance", 0) >= 150.0
    assert "future_cover_months" in billing_summary

    srv.stop()


def test_risk_report_resolves_shosh_reference_id():
    """Risk report endpoint should resolve UW-SHOSH-001 reliably."""
    port = 8060
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.2)

    base = f"http://127.0.0.1:{port}"
    token = _seed_test_session(role='underwriter', username='underwriter')

    app_id = 'UW-SHOSH-001'
    policy_id = 'POL-SHOSH-UNIFIED-001'
    customer_id = 'CUST-SHOSH-001'

    original_app = portal.UNDERWRITING_APPLICATIONS.pop(app_id, None)
    original_policy = portal.POLICIES.pop(policy_id, None)
    original_customer = portal.CUSTOMERS.pop(customer_id, None)

    try:
        body, status = _get(base + f"/api/risk-assessment/report?id={app_id}", token)
        assert status == 200
        data = json.loads(body)
        assert data['application_id'] == app_id
        assert data['applicant']['customer_id'] == customer_id
        assert data['applicant']['email'] == 'shosh@phins.ai'
        assert data.get('metadata', {}).get('data_integrity_verified') is True
    finally:
        if original_app is None:
            portal.UNDERWRITING_APPLICATIONS.pop(app_id, None)
        else:
            portal.UNDERWRITING_APPLICATIONS[app_id] = original_app

        if original_policy is None:
            portal.POLICIES.pop(policy_id, None)
        else:
            portal.POLICIES[policy_id] = original_policy

        if original_customer is None:
            portal.CUSTOMERS.pop(customer_id, None)
        else:
            portal.CUSTOMERS[customer_id] = original_customer

        srv.stop()


def test_risk_report_does_not_fabricate_documents():
    """Risk report should not synthesize default documents when none are stored."""
    port = 8061
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.2)

    base = f"http://127.0.0.1:{port}"
    token = _seed_test_session(role='underwriter', username='underwriter')

    customer_id = 'CUST-RISK-DOC-001'
    policy_id = 'POL-RISK-DOC-001'
    app_id = 'UW-RISK-DOC-001'

    portal.CUSTOMERS[customer_id] = {
        'id': customer_id,
        'name': 'Risk Doc User',
        'email': 'risk-doc@example.com',
        'created_date': '2026-01-01T00:00:00',
        'status': 'active'
    }
    portal.POLICIES[policy_id] = {
        'id': policy_id,
        'customer_id': customer_id,
        'type': 'life',
        'coverage_amount': 120000,
        'annual_premium': 1200,
        'monthly_premium': 100,
        'status': 'pending_underwriting',
        'risk_score': 'low'
    }
    portal.UNDERWRITING_APPLICATIONS[app_id] = {
        'id': app_id,
        'policy_id': policy_id,
        'customer_id': customer_id,
        'customer_name': 'Risk Doc User',
        'customer_email': 'risk-doc@example.com',
        'policy_type': 'life',
        'coverage_amount': 120000,
        'status': 'pending',
        'risk_score': 'low',
        'risk_assessment': 'low',
        'medical_conditions': [],
        'documents': []
    }

    try:
        body, status = _get(base + f"/api/risk-assessment/report?application_id={app_id}", token)
        assert status == 200
        report = json.loads(body)
        assert report.get('documents') == []
        integrity_notes = report.get('metadata', {}).get('integrity_notes', [])
        assert 'documents_unavailable' in integrity_notes
    finally:
        portal.UNDERWRITING_APPLICATIONS.pop(app_id, None)
        portal.POLICIES.pop(policy_id, None)
        portal.CUSTOMERS.pop(customer_id, None)
        srv.stop()


def test_risk_report_handles_string_encoded_medical_payloads():
    """Risk report should parse string-encoded questionnaire and conditions safely."""
    port = 8062
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.2)

    base = f"http://127.0.0.1:{port}"
    token = _seed_test_session(role='underwriter', username='underwriter')

    customer_id = 'CUST-RISK-STRING-001'
    policy_id = 'POL-RISK-STRING-001'
    app_id = 'UW-RISK-STRING-001'

    portal.CUSTOMERS[customer_id] = {
        'id': customer_id,
        'name': 'String Payload User',
        'email': 'risk-string@example.com',
        'created_date': '2026-01-01T00:00:00',
        'status': 'active'
    }
    portal.POLICIES[policy_id] = {
        'id': policy_id,
        'customer_id': customer_id,
        'type': 'health',
        'coverage_amount': 250000,
        'annual_premium': 2400,
        'monthly_premium': 200,
        'status': 'pending_underwriting',
        'risk_score': 'moderate'
    }
    portal.UNDERWRITING_APPLICATIONS[app_id] = {
        'id': app_id,
        'policy_id': policy_id,
        'customer_id': customer_id,
        'customer_name': 'String Payload User',
        'customer_email': 'risk-string@example.com',
        'policy_type': 'health',
        'coverage_amount': 250000,
        'status': 'pending',
        'risk_score': 'moderate',
        'risk_assessment': 'moderate',
        'questionnaire_responses': '{"age":"41","disability_percentage":"15","smoke":"no","height":"170","weight":"78"}',
        'medical_conditions': '[{"condition":"Hypertension","severity":"moderate","risk_impact":"0.18","loading_percentage":"12"}]',
        'documents': '[]'
    }

    try:
        body, status = _get(base + f"/api/risk-assessment/report?application_id={app_id}", token)
        assert status == 200
        report = json.loads(body)
        assert report.get('application_id') == app_id
        assert report.get('applicant', {}).get('age') == 41
        assert report.get('medical_assessment', {}).get('disability_percentage') == 15
        assert report.get('medical_assessment', {}).get('smoking_status') == 'never'
        conditions = report.get('medical_assessment', {}).get('conditions', [])
        assert any(c.get('condition') == 'Hypertension' for c in conditions)
    finally:
        portal.UNDERWRITING_APPLICATIONS.pop(app_id, None)
        portal.POLICIES.pop(policy_id, None)
        portal.CUSTOMERS.pop(customer_id, None)
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
