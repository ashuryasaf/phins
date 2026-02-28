from datetime import datetime

import web_portal.server as server


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
