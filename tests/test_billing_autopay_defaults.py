from datetime import datetime
import json
import threading
import time
from http.server import HTTPServer
from urllib.request import urlopen, Request

import web_portal.server as server


class _ServerThread(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.httpd = HTTPServer(("127.0.0.1", 0), server.PortalHandler)
        self.port = self.httpd.server_address[1]

    def run(self):
        self.httpd.serve_forever()

    def stop(self):
        self.httpd.shutdown()


def test_get_bill_amount_paid_falls_back_for_legacy_paid_bill():
    bill = {
        "status": "Paid",
        "amount_due": 220.50,
        "amount_paid": 0,
    }

    assert server.get_bill_amount_paid(bill) == 220.50
    assert server.get_bill_outstanding_amount(bill) == 0.0


def test_get_bill_outstanding_amount_handles_partial_bill():
    bill = {
        "status": "partial",
        "amount": 200.0,
        "amount_paid": 50.0,
    }

    assert server.get_bill_amount_due(bill) == 200.0
    assert server.get_bill_amount_paid(bill) == 50.0
    assert server.get_bill_outstanding_amount(bill) == 150.0


def test_ensure_policy_autopay_defaults_bootstraps_to_first_of_month():
    policy = {
        "id": "POL-TEST-001",
        "customer_id": "CUST-TEST-001",
        "status": "active",
        "monthly_premium": 100.0,
    }

    changed, state = server.ensure_policy_autopay_defaults(
        policy,
        now=datetime(2026, 2, 27, 12, 0, 0),
        force_enable=True,
    )

    assert changed is True
    assert state["next_billing_date"].startswith("2026-03-01")
    assert policy["payment_setup"]["auto_pay"] is True
    assert policy["payment_setup"]["billing_frequency"] == "monthly"
    assert policy["payment_setup"]["billing_day"] == 1
    assert policy["payment_setup"]["card_type"] == "mastercard"
    assert policy["payment_setup"]["card_last4"] == "4444"
    assert policy["billing"]["next_billing_date"].startswith("2026-03-01")
    assert policy["billing"]["auto_pay"] is True


def test_enforce_autopay_defaults_updates_only_active_policies(monkeypatch):
    test_policies = {
        "POL-ACTIVE-001": {
            "id": "POL-ACTIVE-001",
            "customer_id": "CUST-ACTIVE-001",
            "status": "active",
            "monthly_premium": 150.0,
        },
        "POL-PENDING-001": {
            "id": "POL-PENDING-001",
            "customer_id": "CUST-PENDING-001",
            "status": "pending_underwriting",
            "monthly_premium": 90.0,
        },
    }
    monkeypatch.setattr(server, "POLICIES", test_policies)

    summary = server.enforce_autopay_defaults_for_active_policies(
        now=datetime(2026, 2, 27, 12, 0, 0),
        force_enable=True,
    )

    assert summary["checked"] == 1
    assert summary["updated"] == 1
    assert test_policies["POL-ACTIVE-001"]["payment_setup"]["auto_pay"] is True
    assert "payment_setup" not in test_policies["POL-PENDING-001"]


def test_compute_policy_projected_premium_12m_respects_frequency_discounts():
    monthly = {"monthly_premium": 100.0, "billing": {"frequency": "monthly"}}
    quarterly = {"monthly_premium": 100.0, "billing": {"frequency": "quarterly"}}
    annual = {"monthly_premium": 100.0, "billing": {"frequency": "annual"}}

    assert server._compute_policy_projected_premium_12m(monthly) == 1200.0
    assert server._compute_policy_projected_premium_12m(quarterly) == 1164.0
    assert server._compute_policy_projected_premium_12m(annual) == 1080.0


def test_admin_customers_exposes_billing_outline_fields(monkeypatch):
    customer_id = "CUST-BILL-SEARCH-001"
    policy_id = "POL-BILL-SEARCH-001"

    monkeypatch.setattr(
        server,
        "CUSTOMERS",
        {
            customer_id: {
                "id": customer_id,
                "name": "Billing Search Customer",
                "email": "billing.search@example.com",
                "created_date": "2026-01-15T10:00:00",
            }
        },
    )
    monkeypatch.setattr(
        server,
        "POLICIES",
        {
            policy_id: {
                "id": policy_id,
                "customer_id": customer_id,
                "status": "active",
                "monthly_premium": 100.0,
                "annual_premium": 1200.0,
            }
        },
    )
    monkeypatch.setattr(
        server,
        "BILLING",
        {
            "BILL-PAID-FUTURE": {
                "id": "BILL-PAID-FUTURE",
                "policy_id": policy_id,
                "customer_id": customer_id,
                "amount": 100.0,
                "amount_paid": 100.0,
                "status": "paid",
                "due_date": "2026-04-01T00:00:00",
            },
            "BILL-OUTSTANDING": {
                "id": "BILL-OUTSTANDING",
                "policy_id": policy_id,
                "customer_id": customer_id,
                "amount": 100.0,
                "amount_paid": 0.0,
                "status": "outstanding",
                "due_date": "2026-03-01T00:00:00",
            },
        },
    )
    monkeypatch.setattr(server, "UNDERWRITING_APPLICATIONS", {})
    monkeypatch.setattr(server, "HEALTH_WALLETS", {})
    monkeypatch.setattr(server, "INVESTMENT_ACCOUNTS", {})
    monkeypatch.setattr(server, "CUSTOMER_ALLOCATIONS", {})
    monkeypatch.setattr(server, "save_ledger_data", lambda: None)

    srv = _ServerThread()
    srv.start()
    time.sleep(0.2)

    try:
        req = Request(f"http://127.0.0.1:{srv.port}/api/admin/customers")
        with urlopen(req, timeout=5) as resp:
            payload = json.loads(resp.read().decode("utf-8"))

        assert payload.get("success") is True
        customer = payload["customers"][0]
        assert customer["id"] == customer_id
        assert customer["total_collected"] == 100.0
        assert customer["prepaid_future_premiums"] == 100.0
        assert customer["future_premium_projection_12m"] == 1200.0
        assert customer["autopay_enabled_policies"] == 1
        assert customer["billing_summary"]["total_collected"] == 100.0
        assert customer["billing_summary"]["future_premium_projection_12m"] == 1200.0
    finally:
        srv.stop()
