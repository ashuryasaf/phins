"""Integration coverage for Customer Management recent-activity actions.

These tests focus on action-button backend contracts used by admin/customer
management views: pipeline validation, ledger sync payloads, auto-pay actions,
and registration/notification metadata integrity.
"""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timedelta
from http.server import HTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import web_portal.server as portal


class ServerThread(threading.Thread):
    """Run portal server in background for integration tests."""

    def __init__(self, port: int):
        super().__init__(daemon=True)
        self.port = port
        self.httpd = HTTPServer(("127.0.0.1", port), portal.PortalHandler)

    def run(self) -> None:
        self.httpd.serve_forever()

    def stop(self) -> None:
        self.httpd.shutdown()


def _post(url: str, payload: dict, token: str | None = None) -> tuple[dict, int]:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8")), response.status
    except HTTPError as error:
        return json.loads(error.read().decode("utf-8")), error.code


def _get(url: str, token: str | None = None) -> tuple[dict, int]:
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    request = Request(url, headers=headers, method="GET")
    try:
        with urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8")), response.status
    except HTTPError as error:
        return json.loads(error.read().decode("utf-8")), error.code


def _login_admin(base: str) -> str:
    """Support both legacy and hardened admin password defaults."""
    attempts = [
        {"username": "admin", "password": "admin123"},
        {"username": "admin", "password": "PDadmin123@"},
    ]
    for creds in attempts:
        body, status = _post(base + "/api/login", creds)
        if status == 200 and body.get("token"):
            return body["token"]
    raise AssertionError("Unable to login as admin with known test credentials")


def _request_and_verify_registration_otp(base: str, email: str) -> str:
    """Request + verify OTP and return verification_id for registration."""
    otp_data, otp_status = _post(
        base + "/api/security/otp/request",
        {"email": email, "purpose": "registration", "user_type": "customer"},
    )
    assert otp_status == 200, otp_data

    verification_id = otp_data.get("verification_id") or otp_data.get("data", {}).get(
        "verification_id"
    )
    otp_code = otp_data.get("demo_otp_code") or otp_data.get("data", {}).get("otp_code")
    assert verification_id
    assert otp_code

    verify_data, verify_status = _post(
        base + "/api/security/otp/verify",
        {"verification_id": verification_id, "otp_code": otp_code},
    )
    assert verify_status == 200, verify_data
    assert verify_data.get("success") is True
    return verification_id


def test_recent_activity_pipeline_validation_and_ledger_contract_integrity():
    port = 8161
    server = ServerThread(port)
    server.start()
    time.sleep(0.25)
    base = f"http://127.0.0.1:{port}"

    try:
        token = _login_admin(base)
        email = f"recent-activity-{int(time.time())}@example.com"

        create_data, create_status = _post(
            base + "/api/policies/create",
            {
                "customer_name": "Recent Activity Customer",
                "customer_email": email,
                "coverage_amount": 180000,
                "type": "life",
                "payment_setup": {"billing_frequency": "monthly", "auto_pay": True},
            },
            token,
        )
        assert create_status == 201, create_data

        customer_id = create_data["customer"]["id"]
        underwriting_id = create_data["underwriting"]["id"]

        approve_data, approve_status = _post(
            base + "/api/underwriting/approve",
            {"id": underwriting_id, "approved_by": "admin_recent_activity_test"},
            token,
        )
        assert approve_status == 200, approve_data
        assert approve_data.get("success") is True

        validation, validation_status = _get(
            base + f"/api/admin/pipeline-validate/{customer_id}", token
        )
        assert validation_status == 200, validation
        assert isinstance(validation.get("valid"), bool)
        assert isinstance(validation.get("checks"), list)
        assert isinstance(validation.get("errors"), list)
        assert isinstance(validation.get("warnings"), list)

        ledger, ledger_status = _get(base + "/api/ledger", token)
        assert ledger_status == 200, ledger
        assert "ledger_entries" in ledger
        assert "entries" in ledger
        assert len(ledger["ledger_entries"]) == len(ledger["entries"])

        ledger_validation, lv_status = _get(base + "/api/ledger/validate", token)
        assert lv_status == 200, ledger_validation
        assert ledger_validation.get("integrity_status") in {"HEALTHY", "WARNING", "CRITICAL"}
    finally:
        server.stop()


def test_auto_pay_action_flow_records_paid_bill_and_ledger_entry_when_due():
    port = 8162
    server = ServerThread(port)
    server.start()
    time.sleep(0.25)
    base = f"http://127.0.0.1:{port}"

    try:
        token = _login_admin(base)
        email = f"autopay-flow-{int(time.time())}@example.com"

        create_data, create_status = _post(
            base + "/api/policies/create",
            {
                "customer_name": "AutoPay Flow Customer",
                "customer_email": email,
                "coverage_amount": 200000,
                "type": "life",
                "payment_setup": {"billing_frequency": "monthly", "auto_pay": True},
            },
            token,
        )
        assert create_status == 201, create_data

        customer_id = create_data["customer"]["id"]
        policy_id = create_data["policy"]["id"]
        underwriting_id = create_data["underwriting"]["id"]

        approve_data, approve_status = _post(
            base + "/api/underwriting/approve",
            {"id": underwriting_id, "approved_by": "admin_autopay_test"},
            token,
        )
        assert approve_status == 200, approve_data
        assert approve_data.get("success") is True

        config_data, config_status = _post(
            base + "/api/billing/auto-pay/configure",
            {
                "customer_id": customer_id,
                "policy_id": policy_id,
                "enabled": True,
                "payment_method": "credit_card",
                "card_last4": "4242",
                "card_type": "visa",
                "billing_frequency": "monthly",
                "billing_day": 1,
                "ai_optimization": True,
            },
            token,
        )
        assert config_status == 200, config_data
        assert config_data.get("success") is True

        # Force policy due date into the past to simulate an immediately due auto-pay run.
        due_date = (datetime.now() - timedelta(days=1)).isoformat()
        portal.POLICIES[policy_id]["payment_setup"]["next_billing_date"] = due_date
        if "billing" in portal.POLICIES[policy_id]:
            portal.POLICIES[policy_id]["billing"]["next_billing_date"] = due_date

        execute_data, execute_status = _post(
            base + "/api/billing/auto-pay/execute",
            {"policy_id": policy_id, "customer_id": customer_id, "dry_run": False},
            token,
        )
        assert execute_status == 200, execute_data
        assert execute_data.get("success") is True
        assert execute_data.get("processed", 0) >= 1

        payment = execute_data["payments"][0]
        bill_id = payment.get("bill_id")
        assert bill_id

        assert bill_id in portal.BILLING
        bill = portal.BILLING[bill_id]
        assert bill.get("policy_id") == policy_id
        assert bill.get("customer_id") == customer_id
        assert bill.get("status") == "paid"
        assert bill.get("auto_pay") is True

        auto_pay_entries = [
            tx
            for tx in portal.TRANSACTION_LEDGER.values()
            if tx.get("type") == "auto_pay_execution"
            and tx.get("metadata", {}).get("bill_id") == bill_id
        ]
        assert auto_pay_entries, "Expected auto_pay_execution ledger entry"
    finally:
        server.stop()


def test_auto_pay_save_settings_applies_billing_defaults_and_preserves_integrity():
    """Saving auto-pay settings must normalize invalid values to safe billing defaults."""
    port = 8164
    server = ServerThread(port)
    server.start()
    time.sleep(0.25)
    base = f"http://127.0.0.1:{port}"

    try:
        token = _login_admin(base)
        email = f"autopay-defaults-{int(time.time())}@example.com"

        create_data, create_status = _post(
            base + "/api/policies/create",
            {
                "customer_name": "AutoPay Defaults Customer",
                "customer_email": email,
                "coverage_amount": 160000,
                "type": "life",
                "payment_setup": {"billing_frequency": "monthly", "auto_pay": True},
            },
            token,
        )
        assert create_status == 201, create_data
        customer_id = create_data["customer"]["id"]
        policy_id = create_data["policy"]["id"]
        underwriting_id = create_data["underwriting"]["id"]

        approve_data, approve_status = _post(
            base + "/api/underwriting/approve",
            {"id": underwriting_id, "approved_by": "admin_autopay_defaults_test"},
            token,
        )
        assert approve_status == 200, approve_data
        assert approve_data.get("success") is True

        config_data, config_status = _post(
            base + "/api/billing/auto-pay/configure",
            {
                "customer_id": customer_id,
                "policy_id": policy_id,
                "enabled": "true",
                "payment_method": "not_a_real_method",
                "card_type": "invalid_card_type",
                "card_last4": "12AB",
                "billing_frequency": "weekly",
                "billing_day": 99,
                "notify_before": -5,
                "ai_optimization": "true",
            },
            token,
        )
        assert config_status == 200, config_data
        assert config_data.get("success") is True

        configured = config_data.get("auto_pay_config", {})
        assert configured.get("enabled") is True
        assert configured.get("billing_frequency") == "monthly"
        assert configured.get("billing_day") == 1
        assert configured.get("card_last4") == "4444"
        assert configured.get("card_type") == "visa"

        settings_data, settings_status = _post(
            base + "/api/billing/auto-pay/settings",
            {"policy_id": policy_id, "customer_id": customer_id},
            token,
        )
        assert settings_status == 200, settings_data
        auto_pay_settings = settings_data.get("auto_pay", {})
        assert auto_pay_settings.get("enabled") is True
        assert auto_pay_settings.get("billing_frequency") == "monthly"
        assert auto_pay_settings.get("billing_day") == 1
        assert auto_pay_settings.get("card_last4") == "4444"
        assert auto_pay_settings.get("payment_method_raw") == "credit_card"

        policy = portal.POLICIES[policy_id]
        payment_setup = policy.get("payment_setup", {})
        billing = policy.get("billing", {})
        assert payment_setup.get("auto_pay") is True
        assert payment_setup.get("billing_frequency") == "monthly"
        assert payment_setup.get("billing_day") == 1
        assert payment_setup.get("card_last4") == "4444"
        assert payment_setup.get("payment_method") == "credit_card"
        assert billing.get("frequency") == "monthly"
    finally:
        server.stop()


def test_registration_and_notification_metadata_remain_available():
    """Registration path should keep welcome notification metadata and history API accessible."""
    port = 8163
    server = ServerThread(port)
    server.start()
    time.sleep(0.25)
    base = f"http://127.0.0.1:{port}"

    invite_code = f"RECENTTAB{int(time.time())}"
    portal.INVITATION_CODES[invite_code] = {
        "code": invite_code,
        "status": "active",
        "used_count": 0,
        "max_uses": 3,
        "created_by": "admin",
        "created_at": datetime.now().isoformat(),
        "expires_at": "2099-12-31T23:59:59",
    }

    email = f"registration-actions-{int(time.time())}@example.com"
    password = "SecureActions123!"

    try:
        verification_id = _request_and_verify_registration_otp(base, email)

        register_data, register_status = _post(
            base + "/api/register",
            {
                "name": "Recent Activity Registration",
                "email": email,
                "password": password,
                "phone": "555-0101",
                "dob": "1990-01-01",
                "invitation_code": invite_code,
                "email_verified": True,
                "verification_id": verification_id,
            },
        )
        assert register_status == 201, register_data
        assert register_data.get("success") is True
        assert isinstance(register_data.get("welcome_notification_sent"), bool)
        assert isinstance(register_data.get("welcome_whatsapp_sent"), bool)

        login_data, login_status = _post(
            base + "/api/login", {"username": email, "password": password}
        )
        assert login_status == 200, login_data
        customer_token = login_data.get("token")
        assert customer_token

        history_data, history_status = _get(base + "/api/notifications/history", customer_token)
        assert history_status == 200, history_data
        assert isinstance(history_data.get("history"), list)
        assert isinstance(history_data.get("count"), int)
    finally:
        server.stop()
