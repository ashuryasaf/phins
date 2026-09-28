"""Dashboard books stay on the unified pipeline identities.

Billing stats (GET and POST) share one payload. The risk report shows the
issued premium, not a loading percentage. Supplier order totals cover the
filtered book. Foundation stats compare the recorded balance with fund rows.
"""

from __future__ import annotations

import os

import requests

import web_portal.server as portal
from services.supplier_management_service import SupplierManagementService
from web_portal.api_extensions import handle_admin_foundations_stats

BASE_URL = os.environ.get("TEST_BASE_URL", "http://127.0.0.1:8000")


def test_issued_premium_view_prefers_kernel_pin_and_does_not_invent():
    pinned = portal.issued_premium_view(
        {"annual_premium": "1200", "risk_premium_annual": 800, "savings_premium_annual": 400},
        {"premium_adjustment": 0.2},
        {"annual_premium": 999},
    )
    assert pinned["identity"] == "kernel_pin"
    assert pinned["annual_premium"] == 1200.0
    assert pinned["risk_premium_annual"] == 800.0
    assert pinned["savings_premium_annual"] == 400.0
    assert "premium_adjustment" not in pinned

    quoted = portal.issued_premium_view(
        {"annual_premium": 500},
        {},
        {"risk_premium_annual": 500, "savings_premium_annual": 0},
    )
    assert quoted["identity"] == "quote"
    assert quoted["risk_premium_annual"] == 500.0

    empty = portal.issued_premium_view({}, {"premium_adjustment": 0.15}, {})
    assert empty == {"identity": "unavailable"}


def test_supplier_order_totals_cover_the_full_book_not_the_page():
    orders = {
        "ORD-1": {"id": "ORD-1", "total_amount": 100, "platform_fee": 10, "supplier_payout": 90, "created_date": "2026-01-02"},
        "ORD-2": {"id": "ORD-2", "total_amount": 40, "platform_fee": 4, "supplier_payout": 36, "created_date": "2026-01-01"},
    }
    service = SupplierManagementService(orders_store=orders)
    page = service.get_orders(page=1, page_size=1)
    assert page["total"] == 2
    assert len(page["items"]) == 1
    assert page["totals"]["order_count"] == 2
    assert page["totals"]["order_value"] == 140.0
    assert page["totals"]["platform_fees"] == 14.0
    assert page["totals"]["supplier_payouts"] == 126.0
    assert portal.supplier_order_money_totals(orders.values())["order_value"] == 140.0


def test_billing_stats_payload_ties_ledger_and_accounting_fields():
    payload = portal.billing_stats_payload()
    for key in (
        "total_revenue",
        "ledger_premium_collected",
        "ledger_claims_paid",
        "accounting_premium_posted",
        "accounting_claims_posted",
        "successful_payments",
        "failed_payments",
        "collection_rate",
        "books_cash_tied",
    ):
        assert key in payload
    assert payload["books_cash_tied"] is (
        abs(payload["ledger_premium_collected"] - payload["accounting_premium_posted"]) < 0.01
        and abs(payload["ledger_claims_paid"] - payload["accounting_claims_posted"]) < 0.01
    )


def test_foundation_stats_report_a_fund_ledger_gap(monkeypatch):
    class _Service:
        def list_foundations(self, limit=1000):
            return [{
                "id": "FND-GAP",
                "current_members": 1,
                "total_fund_balance": 100,
            }]

        def get_foundation_funds(self, foundation_id):
            assert foundation_id == "FND-GAP"
            return [{"balance": 40, "status": "active"}]

        def get_foundation_members(self, foundation_id, include_inactive=False):
            members = [{"total_contributed": 60, "status": "active"}]
            if include_inactive:
                members.append({"total_contributed": 40, "status": "removed"})
            return members

    monkeypatch.setattr("web_portal.api_extensions.FOUNDATION_SERVICE_AVAILABLE", True)
    monkeypatch.setattr("web_portal.api_extensions.get_foundation_service", lambda: _Service())
    status, body = handle_admin_foundations_stats({"role": "admin"})
    assert status == 200
    assert body["total_funds"] == 100.0
    assert body["fund_ledger_balance"] == 40.0
    assert body["member_contributions"] == 100.0
    assert body["fund_balance_mismatches"] == 1
    assert body["fund_books_tied"] is False


def _admin_token() -> str:
    resp = requests.post(
        f"{BASE_URL}/api/login",
        json={"username": "admin", "password": "admin123"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["token"]


def test_risk_report_includes_kernel_premium_identity():
    token = _admin_token()
    portal.CUSTOMERS["CUST-PRICE-1"] = {
        "id": "CUST-PRICE-1",
        "name": "Priced Pat",
        "email": "priced@example.com",
        "age": 40,
    }
    portal.POLICIES["POL-PRICE-1"] = {
        "id": "POL-PRICE-1",
        "customer_id": "CUST-PRICE-1",
        "type": "phins_unified",
        "annual_premium": 1200,
        "monthly_premium": 100,
        "risk_premium_annual": 700,
        "savings_premium_annual": 500,
        "coverage_amount": 250000,
        "status": "active",
    }
    portal.UNDERWRITING_APPLICATIONS["UW-PRICE-1"] = {
        "id": "UW-PRICE-1",
        "customer_id": "CUST-PRICE-1",
        "policy_id": "POL-PRICE-1",
        "policy_type": "phins_unified",
        "coverage_amount": 250000,
        "age": 40,
        "created_date": "2026-02-01T00:00:00",
        "status": "pending",
        "premium_adjustment": 0.1,
    }
    resp = requests.get(
        f"{BASE_URL}/api/risk-assessment/report?application_id=UW-PRICE-1",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    report = resp.json()
    assert report["pricing"]["identity"] == "kernel_pin"
    assert report["pricing"]["risk_premium_annual"] == 700.0
    assert report["pricing"]["savings_premium_annual"] == 500.0
    assert report["recommendation"]["premium_adjustment"] != 700
