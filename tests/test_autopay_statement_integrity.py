"""Statement installments, due-day collection, and one-cash settlement.

The quoted installment is what auto-pay and outstanding-bill repair collect.
A run on the 1st opens that cycle when no live bill exists. A later run pays
bills already due and does not open the next period. Each settled bill posts
one premium_payment and one auto_pay_execution audit twin.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import web_portal.server as portal  # noqa: E402


def _seed_policy(
    *,
    policy_id: str = "POL-STMT-1",
    customer_id: str = "CUST-STMT-1",
    frequency: str = "monthly",
    monthly: float = 100.0,
    annual: float = 1200.0,
    quarterly: float = 0.0,
    next_due: str = "2026-04-01T00:00:00",
) -> None:
    portal.CUSTOMERS[customer_id] = {
        "id": customer_id,
        "name": "Statement Customer",
        "email": "statement@example.com",
        "phone": "+15555550111",
    }
    portal.POLICIES[policy_id] = {
        "id": policy_id,
        "customer_id": customer_id,
        "status": "active",
        "monthly_premium": monthly,
        "annual_premium": annual,
        "quarterly_premium": quarterly,
        "payment_setup": {
            "auto_pay": True,
            "billing_frequency": frequency,
            "billing_day": 1,
            "card_last4": "4444",
            "card_type": "mastercard",
            "next_billing_date": next_due,
        },
        "billing": {
            "auto_pay": True,
            "frequency": frequency,
            "billing_day": 1,
            "next_billing_date": next_due,
            "auto_pay_config": {},
        },
    }


def _open_bill(
    bill_id: str,
    *,
    amount: float,
    due: str,
    cycle: str = "",
    created: str = "2026-03-01T00:00:00",
    policy_id: str = "POL-STMT-1",
    customer_id: str = "CUST-STMT-1",
) -> None:
    portal.BILLING[bill_id] = {
        "id": bill_id,
        "policy_id": policy_id,
        "customer_id": customer_id,
        "amount": amount,
        "amount_due": amount,
        "amount_paid": 0.0,
        "status": "outstanding",
        "due_date": due,
        "billing_cycle_key": cycle,
        "created_date": created,
    }


def _txs(tx_type: str):
    return [tx for tx in portal.TRANSACTION_LEDGER.values() if tx.get("type") == tx_type]


def test_frequency_alias_and_quoted_installments():
    assert portal._normalize_billing_frequency("annually") == "annual"
    policy = {
        "monthly_premium": 100.0,
        "annual_premium": 1200.0,
        "quarterly_premium": 250.0,
    }
    assert portal.premium_installment_amount(policy, "monthly") == 100.0
    assert portal.premium_installment_amount(policy, "quarterly") == 250.0
    assert portal.premium_installment_amount(
        {"monthly_premium": 100.0}, "quarterly"
    ) == 291.0
    assert portal.premium_installment_amount(policy, "annual") == 1200.0
    assert portal.premium_installment_amount(
        {"monthly_premium": 100.0}, "annual"
    ) == 1200.0


def test_next_cycle_due_advances_a_full_year_from_the_settled_due_date():
    assert portal._next_cycle_due(datetime(2026, 1, 1), "annual") == datetime(2027, 1, 1)
    assert portal._next_cycle_due(datetime(2026, 6, 1), "annual") == datetime(2027, 6, 1)
    assert portal._next_cycle_due(datetime(2026, 12, 1), "annual") == datetime(2027, 12, 1)


def test_upcoming_statement_due_is_the_next_first():
    march = datetime(2026, 3, 15, 12, 0, 0)
    april_first = datetime(2026, 4, 1, 8, 0, 0)
    april_second = datetime(2026, 4, 2, 8, 0, 0)
    new_year = datetime(2026, 1, 1, 0, 0, 0)

    assert portal.upcoming_statement_due(march, "monthly") == datetime(2026, 4, 1)
    assert portal.upcoming_statement_due(april_first, "monthly") == datetime(2026, 4, 1)
    assert portal.upcoming_statement_due(march, "quarterly") == datetime(2026, 4, 1)
    assert portal.upcoming_statement_due(april_first, "quarterly") == datetime(2026, 4, 1)
    assert portal.upcoming_statement_due(april_second, "quarterly") == datetime(2026, 7, 1)
    assert portal.upcoming_statement_due(march, "annual") == datetime(2027, 1, 1)
    assert portal.upcoming_statement_due(new_year, "annual") == datetime(2026, 1, 1)


def test_statement_bill_uses_quoted_annual_not_a_second_discount():
    policy = {
        "id": "POL-ANN",
        "monthly_premium": 100.0,
        "annual_premium": 1200.0,
    }
    bill = portal.build_premium_statement_bill(
        policy,
        customer_id="CUST-ANN",
        frequency="annual",
        auto_pay=True,
        reference=datetime(2026, 3, 15, 9, 0, 0),
    )
    assert bill["amount"] == 1200.0
    assert bill["due_date"].startswith("2027-01-01")
    assert bill["billing_cycle_key"] == "2027"
    assert bill["status"] == "outstanding"


def test_existing_statement_is_collected_once():
    _seed_policy()
    _open_bill("BILL-APR", amount=100.0, due="2026-04-01T00:00:00", cycle="2026-04")
    before = set(portal.BILLING)

    report = portal.run_monthly_auto_pay(
        reference_datetime=datetime(2026, 4, 1, 8, 0, 0),
        specific_policy="POL-STMT-1",
        dry_run=False,
        notify_users=False,
    )

    assert report["processed"] == 1
    assert report["total_amount"] == 100.0
    assert set(portal.BILLING) == before
    assert portal.BILLING["BILL-APR"]["status"] == "paid"
    assert portal.BILLING["BILL-APR"]["amount_paid"] == 100.0
    cash = _txs("premium_payment")
    audit = _txs("auto_pay_execution")
    assert len(cash) == 1 and cash[0]["amount"] == 100.0
    assert len(audit) == 1 and audit[0]["amount"] == 100.0
    assert portal.POLICIES["POL-STMT-1"]["payment_setup"]["next_billing_date"].startswith(
        "2026-05-01"
    )


def test_quarterly_and_annual_collect_the_quoted_installment_once():
    _seed_policy(
        policy_id="POL-Q",
        customer_id="CUST-Q",
        frequency="quarterly",
        quarterly=0.0,
        next_due="2026-04-01T00:00:00",
    )
    report = portal.run_monthly_auto_pay(
        reference_datetime=datetime(2026, 4, 1, 8, 0, 0),
        specific_policy="POL-Q",
        dry_run=False,
        notify_users=False,
    )
    assert report["processed"] == 1
    assert report["total_amount"] == 291.0
    assert len(_txs("premium_payment")) == 1
    assert portal.POLICIES["POL-Q"]["payment_setup"]["next_billing_date"].startswith(
        "2026-07-01"
    )

    _seed_policy(
        policy_id="POL-Y",
        customer_id="CUST-Y",
        frequency="annual",
        annual=1200.0,
        next_due="2026-01-01T00:00:00",
    )
    report = portal.run_monthly_auto_pay(
        reference_datetime=datetime(2026, 1, 1, 8, 0, 0),
        specific_policy="POL-Y",
        dry_run=False,
        notify_users=False,
    )
    assert report["processed"] == 1
    assert report["total_amount"] == 1200.0
    paid = [b for b in portal.BILLING.values() if b.get("policy_id") == "POL-Y"]
    assert len(paid) == 1 and paid[0]["amount"] == 1200.0


def test_a_mid_year_annual_policy_is_rescheduled_a_year_out():
    _seed_policy(
        policy_id="POL-ANN-MID",
        customer_id="CUST-ANN-MID",
        frequency="annual",
        annual=1200.0,
        next_due="2026-06-01T00:00:00",
    )

    report = portal.run_monthly_auto_pay(
        reference_datetime=datetime(2026, 6, 1, 8, 0, 0),
        specific_policy="POL-ANN-MID",
        dry_run=False,
        notify_users=False,
    )

    assert report["processed"] == 1
    assert report["total_amount"] == 1200.0
    assert portal.POLICIES["POL-ANN-MID"]["payment_setup"]["next_billing_date"].startswith(
        "2027-06-01"
    )

    january = portal.run_monthly_auto_pay(
        reference_datetime=datetime(2027, 1, 1, 8, 0, 0),
        specific_policy="POL-ANN-MID",
        dry_run=False,
        notify_users=False,
    )
    assert january["processed"] == 0
    assert len(_txs("premium_payment")) == 1


def test_an_opted_out_policy_is_neither_re_enabled_nor_charged():
    _seed_policy(
        policy_id="POL-MANUAL",
        customer_id="CUST-MANUAL",
        next_due="2026-04-01T00:00:00",
    )
    portal.POLICIES["POL-MANUAL"]["payment_setup"]["auto_pay"] = False
    portal.POLICIES["POL-MANUAL"]["billing"]["auto_pay"] = False
    _open_bill(
        "BILL-MANUAL",
        amount=100.0,
        due="2026-04-01T00:00:00",
        cycle="2026-04",
        policy_id="POL-MANUAL",
        customer_id="CUST-MANUAL",
    )

    report = portal.run_monthly_auto_pay(
        reference_datetime=datetime(2026, 4, 1, 8, 0, 0),
        specific_policy="POL-MANUAL",
        dry_run=False,
        notify_users=False,
    )

    assert report["processed"] == 0
    assert portal.BILLING["BILL-MANUAL"]["status"] == "outstanding"
    assert _txs("premium_payment") == []
    policy = portal.POLICIES["POL-MANUAL"]
    assert policy["payment_setup"]["auto_pay"] is False
    assert policy["billing"]["auto_pay"] is False


def test_off_first_collects_overdue_and_leaves_future_bills():
    _seed_policy(next_due="2026-04-01T00:00:00")
    _open_bill("BILL-MAR", amount=100.0, due="2026-03-01T00:00:00", cycle="2026-03")
    _open_bill(
        "BILL-APR",
        amount=100.0,
        due="2026-04-01T00:00:00",
        cycle="2026-04",
        created="2026-03-02T00:00:00",
    )

    report = portal.run_monthly_auto_pay(
        reference_datetime=datetime(2026, 3, 15, 8, 0, 0),
        specific_policy="POL-STMT-1",
        dry_run=False,
        notify_users=False,
        enforce_first_day=True,
    )

    assert report["success"] is True
    assert report["catch_up"] is True
    assert report["processed"] == 1
    assert portal.BILLING["BILL-MAR"]["status"] == "paid"
    assert portal.BILLING["BILL-APR"]["status"] == "outstanding"
    assert len(_txs("premium_payment")) == 1


def test_first_does_not_collect_a_future_due_statement_or_open_a_second_bill():
    _seed_policy(next_due="2026-04-01T00:00:00")
    _open_bill("BILL-MID", amount=100.0, due="2026-04-15T00:00:00")

    report = portal.run_monthly_auto_pay(
        reference_datetime=datetime(2026, 4, 1, 8, 0, 0),
        specific_policy="POL-STMT-1",
        dry_run=False,
        notify_users=False,
    )

    assert report["processed"] == 0
    assert list(portal.BILLING) == ["BILL-MID"]
    assert portal.BILLING["BILL-MID"]["status"] == "outstanding"
    assert _txs("premium_payment") == []


def test_repair_then_autopay_does_not_charge_again():
    _seed_policy(next_due="2026-05-01T00:00:00")
    _open_bill("BILL-MAY", amount=80.0, due="2026-05-01T00:00:00", cycle="2026-05")

    repair = portal.repair_billing_pending_pipeline(
        customer_id="CUST-STMT-1",
        dry_run=False,
        notify_users=False,
        reference_datetime=datetime(2026, 4, 10, 9, 0, 0),
    )
    assert repair["bills_settled"] == 1
    assert portal.BILLING["BILL-MAY"]["status"] == "paid"
    assert len(_txs("premium_payment")) == 1
    assert len(_txs("auto_pay_execution")) == 1

    later = portal.run_monthly_auto_pay(
        reference_datetime=datetime(2026, 5, 1, 8, 0, 0),
        specific_policy="POL-STMT-1",
        dry_run=False,
        notify_users=False,
    )
    assert later["processed"] == 0
    assert len(_txs("premium_payment")) == 1
    assert portal.BILLING["BILL-MAY"]["amount_paid"] == 80.0


def test_duplicate_open_twin_is_cancelled_without_a_second_charge():
    _seed_policy(next_due="2026-04-01T00:00:00")
    _open_bill(
        "BILL-KEEP",
        amount=100.0,
        due="2026-04-01T00:00:00",
        cycle="2026-04",
        created="2026-03-01T00:00:00",
    )
    _open_bill(
        "BILL-TWIN",
        amount=100.0,
        due="2026-04-01T00:00:00",
        cycle="2026-04",
        created="2026-03-02T00:00:00",
    )

    report = portal.run_monthly_auto_pay(
        reference_datetime=datetime(2026, 4, 1, 8, 0, 0),
        specific_policy="POL-STMT-1",
        dry_run=False,
        notify_users=False,
    )

    assert report["processed"] == 1
    assert "BILL-TWIN" in report["duplicates_cancelled"]
    assert portal.BILLING["BILL-KEEP"]["status"] == "paid"
    assert portal.BILLING["BILL-TWIN"]["status"] == "cancelled"
    assert portal.BILLING["BILL-TWIN"]["cancelled_reason"] == "duplicate_statement_cycle"
    assert len(_txs("premium_payment")) == 1


def test_dry_run_does_not_mutate_and_settings_mail_is_not_sent(monkeypatch):
    _seed_policy()
    generic = []
    receipts = []
    monkeypatch.setattr(
        portal,
        "_send_generic_auto_pay_notification",
        lambda **kwargs: generic.append(kwargs) or {"success": True},
    )
    monkeypatch.setattr(
        portal,
        "_send_auto_pay_billing_notification",
        lambda **kwargs: receipts.append(kwargs) or {"success": True, **kwargs},
    )
    snapshot = portal.POLICIES["POL-STMT-1"]["payment_setup"]["next_billing_date"]

    preview = portal.run_monthly_auto_pay(
        reference_datetime=datetime(2026, 4, 1, 8, 0, 0),
        specific_policy="POL-STMT-1",
        dry_run=True,
        notify_users=True,
    )
    assert preview["processed"] == 1
    assert preview["payments"][0]["bill_state"] == "would_create"
    assert portal.BILLING == {}
    assert portal.POLICIES["POL-STMT-1"]["payment_setup"]["next_billing_date"] == snapshot
    assert generic == []
    assert receipts == []
    assert _txs("premium_payment") == []

    live = portal.run_monthly_auto_pay(
        reference_datetime=datetime(2026, 4, 1, 8, 0, 0),
        specific_policy="POL-STMT-1",
        dry_run=False,
        notify_users=True,
    )
    assert live["processed"] == 1
    assert generic == []
    assert len(receipts) == 1
    assert receipts[0]["event_name"] == "received"
    assert len(_txs("premium_payment")) == 1
