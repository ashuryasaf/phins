"""
Tests for the /api/admin/billing-pending/repair endpoint and the
``repair_billing_pending_pipeline`` helper.

These guard the customer-management.html "Pipeline Stage = Billing Pending"
flow that activates auto-pay defaults and settles outstanding bills while
preserving ledger integrity.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import web_portal.server as portal  # noqa: E402  (sys.path manipulation above)


CUSTOMER_ID = "CUST-BILLPEND-001"
POLICY_ID = "POL-BILLPEND-001"
BILL_ID = "BILL-BILLPEND-001"


def _seed_pending_customer(monthly_premium: float = 250.0) -> None:
    """Seed an in-memory customer with an active policy and an outstanding bill."""
    now = datetime.now()
    portal.CUSTOMERS[CUSTOMER_ID] = {
        "id": CUSTOMER_ID,
        "name": "Billing Pending Test",
        "email": "billpend@example.com",
        "phone": "+15555550100",
        "created_date": (now - timedelta(days=120)).isoformat(),
    }
    portal.POLICIES[POLICY_ID] = {
        "id": POLICY_ID,
        "customer_id": CUSTOMER_ID,
        "status": "active",
        "monthly_premium": monthly_premium,
        "annual_premium": monthly_premium * 12,
        "approval_date": (now - timedelta(days=90)).isoformat(),
        "effective_date": (now - timedelta(days=90)).isoformat(),
        "payment_setup": {},
        "billing": {},
    }
    portal.BILLING[BILL_ID] = {
        "id": BILL_ID,
        "customer_id": CUSTOMER_ID,
        "policy_id": POLICY_ID,
        "status": "outstanding",
        "amount": monthly_premium,
        "amount_due": monthly_premium,
        "amount_paid": 0.0,
        "due_date": now.strftime("%Y-%m-%d"),
        "billing_period_start": now.strftime("%Y-%m-01"),
        "created_date": now.isoformat(),
    }


class TestRepairBillingPendingHelper:
    def test_dry_run_does_not_mutate_state(self):
        _seed_pending_customer()
        bill_before = dict(portal.BILLING[BILL_ID])
        policy_before_autopay = bool(
            (portal.POLICIES[POLICY_ID].get("payment_setup") or {}).get("auto_pay")
        )

        report = portal.repair_billing_pending_pipeline(
            customer_id=CUSTOMER_ID,
            dry_run=True,
            notify_users=False,
        )

        assert report["success"] is True
        assert report["dry_run"] is True
        assert report["targeted"] == 1
        assert portal.BILLING[BILL_ID]["status"] == bill_before["status"]
        assert portal.BILLING[BILL_ID]["amount_paid"] == bill_before["amount_paid"]
        assert (
            bool((portal.POLICIES[POLICY_ID].get("payment_setup") or {}).get("auto_pay"))
            == policy_before_autopay
        )

    def test_repair_settles_outstanding_and_activates_autopay(self):
        _seed_pending_customer()

        report = portal.repair_billing_pending_pipeline(
            customer_id=CUSTOMER_ID,
            dry_run=False,
            notify_users=False,
        )

        assert report["success"] is True
        assert report["targeted"] == 1
        assert report["bills_settled"] >= 1
        assert report["bills_remaining"] == 0
        assert report["amount_remaining"] == 0.0
        assert report["data_integrity_ok"] is True

        customer_record = report["customers"][0]
        assert customer_record["fully_settled"] is True
        assert customer_record["after"]["pipeline_stage"] == "fully_active"
        assert customer_record["after"]["outstanding_bills"] == 0
        assert customer_record["after"]["autopay_active_policies"] == 1

        bill_after = portal.BILLING[BILL_ID]
        assert bill_after["status"] == "paid"
        assert bill_after["amount_paid"] >= bill_after["amount_due"] - 0.01

        policy_after = portal.POLICIES[POLICY_ID]
        assert (policy_after.get("payment_setup") or {}).get("auto_pay") is True
        assert (policy_after.get("billing") or {}).get("auto_pay") is True
        assert (policy_after.get("billing") or {}).get("auto_pay_config", {}).get(
            "schedule"
        ) == "1st_of_month"

    def test_repair_idempotent_on_already_paid_customer(self):
        _seed_pending_customer()
        portal.repair_billing_pending_pipeline(
            customer_id=CUSTOMER_ID, dry_run=False, notify_users=False,
        )

        second = portal.repair_billing_pending_pipeline(
            customer_id=CUSTOMER_ID, dry_run=False, notify_users=False,
        )
        assert second["success"] is True
        assert second["bills_settled"] == 0
        assert second["bills_remaining"] == 0
        assert second["amount_remaining"] == 0.0
        assert second["data_integrity_ok"] is True

    def test_repair_unknown_customer_returns_error(self):
        report = portal.repair_billing_pending_pipeline(
            customer_id="CUST-DOES-NOT-EXIST",
            dry_run=True,
            notify_users=False,
        )
        assert report["success"] is False
        assert report["targeted"] == 0
        assert report["errors"], "expected an error entry for unknown customer"

    def test_bulk_repair_targets_only_billing_pending(self):
        _seed_pending_customer()
        # Add a fully-paid customer that should NOT be targeted.
        other_id = "CUST-PAID-002"
        portal.CUSTOMERS[other_id] = {
            "id": other_id,
            "name": "Already Paid",
            "email": "paid@example.com",
        }
        portal.POLICIES["POL-PAID-002"] = {
            "id": "POL-PAID-002",
            "customer_id": other_id,
            "status": "active",
            "monthly_premium": 100.0,
            "payment_setup": {"auto_pay": True},
            "billing": {"auto_pay": True},
        }
        portal.BILLING["BILL-PAID-002"] = {
            "id": "BILL-PAID-002",
            "customer_id": other_id,
            "policy_id": "POL-PAID-002",
            "status": "paid",
            "amount": 100.0,
            "amount_paid": 100.0,
        }

        report = portal.repair_billing_pending_pipeline(
            customer_id=None,
            dry_run=True,
            notify_users=False,
        )

        targeted_ids = {c["customer_id"] for c in report["customers"]}
        assert CUSTOMER_ID in targeted_ids
        assert other_id not in targeted_ids


class TestRepairEndpointHTTP:
    def test_endpoint_requires_admin_auth(self):
        import json
        import urllib.error
        import urllib.request

        base_url = os.environ.get("TEST_BASE_URL", "http://localhost:8000")
        req = urllib.request.Request(
            f"{base_url}/api/admin/billing-pending/repair",
            data=json.dumps({"dry_run": True}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                status = resp.status
        except urllib.error.HTTPError as exc:
            status = exc.code
        assert status in (401, 403)
