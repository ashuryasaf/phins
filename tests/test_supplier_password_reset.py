"""
Tests for supplier forgot-password / password-reset flow.

Validates:
- OTP is issued specifically for suppliers via /api/supplier/request-password-reset
- Password reset only changes the supplier record, never a customer/user record
- Invalid/expired OTPs are rejected
- Supplier sessions are revoked after reset
- Anti-enumeration: decoy responses for unknown emails
- Data integrity: customer passwords remain unchanged when email overlaps
"""

import json
import urllib.request
import urllib.error

import web_portal.server as portal
from services.otp_security_service import (
    get_otp_security_service,
    reset_otp_security_service,
    OTPPurpose,
)

BASE = "http://localhost:8000"


def _post(path, payload):
    """POST JSON and return (status, parsed_body)."""
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def _setup_supplier(email="supplier@test.com", password="SupplierPass123"):
    """Register a supplier directly via the service."""
    svc = portal.supplier_service
    supplier_id = svc.generate_supplier_id()
    password_hash, salt = svc.hash_password(password)

    supplier = {
        'id': supplier_id,
        'company_name': 'Test Supplier Co',
        'contact_name': 'Test Contact',
        'contact_email': email.lower(),
        'supplier_type': 'wellness',
        'category': 'health',
        'status': 'approved',
        'portal_active': True,
        'password_hash': password_hash,
        'password_salt': salt,
        'created_date': '2025-01-01T00:00:00+00:00',
        'updated_date': '2025-01-01T00:00:00+00:00',
    }
    portal.SUPPLIERS[supplier_id] = supplier
    return supplier_id, email


def _setup_customer_with_same_email(email="supplier@test.com", password="CustomerPass456"):
    """Create a customer/user with the same email to test isolation."""
    pwd_hash = portal.hash_password(password)
    username = email.lower()
    portal.USERS[username] = {
        "hash": pwd_hash["hash"],
        "salt": pwd_hash["salt"],
        "role": "customer",
        "customer_id": "CUST_OVERLAP_001",
    }
    portal.CUSTOMERS["CUST_OVERLAP_001"] = {
        "id": "CUST_OVERLAP_001",
        "name": "Overlapping Customer",
        "email": email.lower(),
    }
    return username


def _teardown():
    portal.SUPPLIERS.clear()
    portal.SUPPLIER_ORDERS.clear()
    portal.USERS.clear()
    portal.CUSTOMERS.clear()
    portal.SESSIONS.clear()
    reset_otp_security_service()


# ---------- Step 1: /api/supplier/request-password-reset ----------

class TestSupplierRequestPasswordReset:

    def setup_method(self):
        _teardown()

    def test_request_returns_verification_id(self):
        _setup_supplier()
        status, body = _post("/api/supplier/request-password-reset", {
            "email": "supplier@test.com",
        })
        assert status == 200
        assert body.get("success") is True
        assert body.get("verification_id")
        assert body.get("requires_otp") is True

    def test_request_nonexistent_email_returns_decoy(self):
        status, body = _post("/api/supplier/request-password-reset", {
            "email": "unknown@nobody.com",
        })
        assert status == 200
        assert body.get("success") is True
        assert "verification_id" in body
        assert body.get("requires_otp") is True
        assert body.get("notification_sent") is True
        assert "masked_email" in body

    def test_request_missing_email_returns_400(self):
        status, body = _post("/api/supplier/request-password-reset", {
            "email": "",
        })
        assert status == 400

    def test_demo_otp_exposed_in_test_mode(self):
        _setup_supplier()
        status, body = _post("/api/supplier/request-password-reset", {
            "email": "supplier@test.com",
        })
        assert status == 200
        assert body.get("demo_otp_code"), "demo_otp_code should be exposed in test mode"

    def test_customer_email_not_found_by_supplier_reset(self):
        """A customer-only email should NOT trigger a real supplier OTP."""
        _setup_customer_with_same_email(email="customer_only@test.com")
        status, body = _post("/api/supplier/request-password-reset", {
            "email": "customer_only@test.com",
        })
        assert status == 200
        assert body.get("success") is True
        assert body.get("notification_sent") is True


# ---------- Step 2: /api/supplier/reset-password ----------

class TestSupplierResetPassword:

    def setup_method(self):
        _teardown()

    def test_reset_without_otp_rejected(self):
        _setup_supplier()
        status, body = _post("/api/supplier/reset-password", {
            "email": "supplier@test.com",
            "new_password": "NewPass456",
        })
        assert status == 400
        assert body.get("requires_otp") is True

    def test_reset_with_invalid_otp(self):
        _setup_supplier()
        _, req_body = _post("/api/supplier/request-password-reset", {
            "email": "supplier@test.com",
        })
        vid = req_body["verification_id"]

        status, body = _post("/api/supplier/reset-password", {
            "email": "supplier@test.com",
            "new_password": "NewPass456",
            "verification_id": vid,
            "otp_code": "000000",
        })
        assert status == 401

    def test_full_reset_flow(self):
        """Happy path: request OTP -> verify -> supplier password changed."""
        supplier_id, email = _setup_supplier(password="OldPassword1")

        old_hash = portal.SUPPLIERS[supplier_id]['password_hash']

        # Step 1: Request OTP
        _, req_body = _post("/api/supplier/request-password-reset", {
            "email": email,
        })
        vid = req_body["verification_id"]
        otp_code = req_body.get("demo_otp_code")
        assert otp_code

        # Step 2: Reset with valid OTP
        status, body = _post("/api/supplier/reset-password", {
            "email": email,
            "new_password": "BrandNewSecure9",
            "verification_id": vid,
            "otp_code": otp_code,
        })
        assert status == 200
        assert body.get("success") is True

        # Verify supplier password was actually changed
        new_hash = portal.SUPPLIERS[supplier_id]['password_hash']
        assert new_hash != old_hash

        # Verify new password works via the service
        assert portal.supplier_service.verify_password(
            "BrandNewSecure9",
            portal.SUPPLIERS[supplier_id]['password_hash'],
            portal.SUPPLIERS[supplier_id]['password_salt']
        )

    def test_short_password_rejected(self):
        _setup_supplier()
        _, req_body = _post("/api/supplier/request-password-reset", {
            "email": "supplier@test.com",
        })
        vid = req_body["verification_id"]
        otp = req_body["demo_otp_code"]

        status, body = _post("/api/supplier/reset-password", {
            "email": "supplier@test.com",
            "new_password": "short",
            "verification_id": vid,
            "otp_code": otp,
        })
        assert status == 400
        assert "8 characters" in body.get("error", "")

    def test_otp_cannot_be_reused(self):
        _setup_supplier()
        _, req_body = _post("/api/supplier/request-password-reset", {
            "email": "supplier@test.com",
        })
        vid = req_body["verification_id"]
        otp = req_body["demo_otp_code"]

        # First reset succeeds
        status, _ = _post("/api/supplier/reset-password", {
            "email": "supplier@test.com",
            "new_password": "FirstPass99!",
            "verification_id": vid,
            "otp_code": otp,
        })
        assert status == 200

        # Second attempt fails
        status2, _ = _post("/api/supplier/reset-password", {
            "email": "supplier@test.com",
            "new_password": "SecondPass99!",
            "verification_id": vid,
            "otp_code": otp,
        })
        assert status2 == 401

    def test_supplier_sessions_revoked_after_reset(self):
        """All existing supplier sessions must be invalidated."""
        supplier_id, email = _setup_supplier()
        portal.SESSIONS["supplier_token_abc"] = {
            "username": supplier_id,
            "role": "supplier",
            "supplier_id": supplier_id,
        }

        _, req_body = _post("/api/supplier/request-password-reset", {
            "email": email,
        })
        vid = req_body["verification_id"]
        otp = req_body["demo_otp_code"]

        _post("/api/supplier/reset-password", {
            "email": email,
            "new_password": "AfterReset1!",
            "verification_id": vid,
            "otp_code": otp,
        })

        assert "supplier_token_abc" not in portal.SESSIONS


# ---------- Data Integrity: Supplier reset does NOT touch customer passwords ----------

class TestSupplierResetDataIntegrity:

    def setup_method(self):
        _teardown()

    def test_supplier_reset_does_not_change_customer_password(self):
        """
        If the same email is registered as both a supplier and a customer,
        resetting the supplier password must NOT modify the customer/user record.
        """
        shared_email = "shared@company.com"
        supplier_id, _ = _setup_supplier(email=shared_email, password="SupplierOld1")
        customer_username = _setup_customer_with_same_email(
            email=shared_email, password="CustomerPass1"
        )

        customer_hash_before = portal.USERS[customer_username]["hash"]
        customer_salt_before = portal.USERS[customer_username]["salt"]

        # Request and complete supplier password reset
        _, req_body = _post("/api/supplier/request-password-reset", {
            "email": shared_email,
        })
        vid = req_body["verification_id"]
        otp = req_body["demo_otp_code"]

        status, body = _post("/api/supplier/reset-password", {
            "email": shared_email,
            "new_password": "SupplierNew99!",
            "verification_id": vid,
            "otp_code": otp,
        })
        assert status == 200
        assert body.get("success") is True

        # Customer password is completely untouched
        assert portal.USERS[customer_username]["hash"] == customer_hash_before
        assert portal.USERS[customer_username]["salt"] == customer_salt_before

        # Customer can still log in with old password
        assert portal.verify_password(
            "CustomerPass1",
            portal.USERS[customer_username]["hash"],
            portal.USERS[customer_username]["salt"]
        )

        # Supplier password is changed
        assert portal.supplier_service.verify_password(
            "SupplierNew99!",
            portal.SUPPLIERS[supplier_id]['password_hash'],
            portal.SUPPLIERS[supplier_id]['password_salt']
        )

    def test_customer_reset_does_not_change_supplier_password(self):
        """
        The general /api/request-password-reset endpoint for customers
        must NOT modify any supplier record.
        """
        shared_email = "both@shared.com"
        supplier_id, _ = _setup_supplier(email=shared_email, password="SupPass1!")
        customer_username = _setup_customer_with_same_email(
            email=shared_email, password="CustPass1!"
        )

        supplier_hash_before = portal.SUPPLIERS[supplier_id]['password_hash']
        supplier_salt_before = portal.SUPPLIERS[supplier_id]['password_salt']

        # Use the customer password reset flow
        _, req_body = _post("/api/request-password-reset", {
            "username": customer_username,
            "email": shared_email,
        })
        vid = req_body["verification_id"]
        otp = req_body.get("demo_otp_code")

        if otp:
            status, body = _post("/api/reset-password", {
                "username": customer_username,
                "email": shared_email,
                "new_password": "CustNewPass1!",
                "verification_id": vid,
                "otp_code": otp,
            })
            assert status == 200

        # Supplier password is completely untouched
        assert portal.SUPPLIERS[supplier_id]['password_hash'] == supplier_hash_before
        assert portal.SUPPLIERS[supplier_id]['password_salt'] == supplier_salt_before
