"""Customer-ledger cash is the identity for premiums collected and claims paid.

The actuarial kernel pin (when present) decides the risk/savings split posted
to the accounting book. Historical billed amounts are never rewritten.
"""

import copy
from decimal import Decimal

from accounting_engine import (
    AccountType,
    AllocationStatus,
    EntryType,
    get_accounting_engine,
    reset_accounting_engine,
)
from services.financial_unification_service import (
    CLAIM_CASH_TYPES,
    PREMIUM_AUDIT_TYPES,
    PREMIUM_CASH_TYPES,
    accounting_book_totals,
    apply_ledger_derived_balance_sheet,
    economic_claims_reserve,
    ensure_seed_claims_reserve,
    kernel_components_from_policy,
    kernel_pin_restore_candidate,
    kernel_savings_cash_from_ledger,
    ledger_cash_total,
    ledger_derived_balance_sheet_view,
    pin_kernel_fields_on_policy,
    post_collected_premiums_to_accounting,
    post_premium_to_accounting_book,
    premium_cash_position,
    premium_revenue_rows_on_sheet,
    reconcile_financial_books,
    reconstruct_accounting_book_from_ledger,
    repair_financial_books,
    repin_kernel_fields_on_policy,
    resolve_premium_split,
    resplit_accounting_book_premiums,
    savings_and_investments_books,
    sum_paid_claim_records,
)


def setup_function():
    reset_accounting_engine()


def test_kernel_split_prefers_policy_pin_over_allocation_prefs():
    policy = {
        "id": "POL-K1",
        "annual_premium": 1000.0,
        "risk_premium_annual": 800.0,
        "savings_premium_annual": 200.0,
        "pricing_source": "pricing_kernel",
        "integrity_hash": "abc123",
        "product_id": "phins_pure_risk_adjustable",
    }
    split = resolve_premium_split(100.0, policy, fallback_risk_pct=50)
    assert split["risk_percentage"] == 80.0
    assert split["savings_percentage"] == 20.0
    assert split["risk_amount"] == 80.0
    assert split["savings_amount"] == 20.0
    assert split["split_source"].startswith("kernel")
    assert split["integrity_hash"] == "abc123"


def test_underwriting_fee_is_not_savings():
    """A 35% decision sits between risk and the add-on. It is company money."""
    policy = {
        "annual_premium": 1620.0,
        "actuarial_annual_premium": 1200.0,
        "risk_premium_annual": 1200.0,
        "underwriting_loading": 0.35,
    }
    split = resolve_premium_split(135.0, policy)
    assert split["risk_amount"] == 100.0
    assert split["underwriting_fee_amount"] == 35.0
    assert split["savings_amount"] == 0.0
    assert split["company_remainder"] == 0.0


def test_chat_loading_already_inside_risk_is_not_charged_again():
    policy = {
        "annual_premium": 1620.0,
        "risk_premium_annual": 1620.0,
        "savings_premium_annual": 0.0,
        "underwriting_loading": 0.35,
        "pricing_source": "pricing_kernel",
        "allocation_version": "chat",
        "application_channel": "chat",
    }
    split = resolve_premium_split(135.0, policy)
    assert split["underwriting_fee_amount"] == 0.0
    assert split["risk_amount"] == 135.0
    assert split["savings_amount"] == 0.0


def test_earlier_allocation_is_kept_and_the_fee_stays_out_of_savings():
    policy = {
        "annual_premium": 1620.0,
        "actuarial_annual_premium": 1200.0,
        "risk_allocation": 60.0,
        "savings_allocation": 40.0,
        "underwriting_loading": 0.35,
    }
    split = resolve_premium_split(135.0, policy)
    assert split["split_source"] == "historical"
    assert split["risk_amount"] == 60.0
    assert split["savings_amount"] == 40.0
    assert split["underwriting_fee_amount"] == 35.0


def test_split_without_a_savings_election_is_pure_risk():
    split = resolve_premium_split(200.0, {"annual_premium": 2400.0}, fallback_risk_pct=75)
    assert split["risk_percentage"] == 100.0
    assert split["risk_amount"] == 200.0
    assert split["savings_amount"] == 0.0
    assert split["split_source"] == "no_savings_election"
    assert split["split_label"] == "no_savings_election"


def test_premium_and_claim_cash_post_to_same_accounting_book():
    engine = get_accounting_engine()
    posted = post_premium_to_accounting_book(
        bill_id="BILL-1",
        policy_id="POL-1",
        customer_id="CUST-1",
        amount=120.50,
        risk_percentage=80,
        source_tx_id="TX-PREM-1",
        engine=engine,
    )
    assert posted["posted"] is True

    # Idempotent: same bill must not double-post.
    again = post_premium_to_accounting_book(
        bill_id="BILL-1",
        policy_id="POL-1",
        customer_id="CUST-1",
        amount=120.50,
        risk_percentage=80,
        source_tx_id="TX-PREM-1",
        engine=engine,
    )
    assert again["posted"] is False
    assert again["reason"] == "already_posted"

    ok, _ = engine.post_claim_payment(
        claim_id="CLM-1",
        policy_id="POL-1",
        customer_id="CUST-1",
        amount=Decimal("40.00"),
        paid_by="test",
    )
    assert ok is True

    totals = accounting_book_totals(engine)
    assert totals["premium_posted"] == 120.50
    assert totals["claims_posted"] == 40.00
    assert any(e.entry_type == EntryType.CLAIM_PAYMENT for e in engine.ledger_entries)


def test_accounting_book_totals_honor_customer_exclusion():
    """Book totals exclude sandbox customers the same way the ledger does."""
    engine = get_accounting_engine()
    post_premium_to_accounting_book(
        bill_id="BILL-REAL",
        policy_id="POL-REAL",
        customer_id="CUST-REAL",
        amount=90.0,
        risk_percentage=80,
        source_tx_id="TX-REAL",
        engine=engine,
    )
    post_premium_to_accounting_book(
        bill_id="BILL-SANDBOX",
        policy_id="POL-SANDBOX",
        customer_id="TESTSIM-1",
        amount=500.0,
        risk_percentage=80,
        source_tx_id="TX-SANDBOX",
        engine=engine,
    )
    assert accounting_book_totals(engine)["premium_posted"] == 590.0
    excluded = accounting_book_totals(
        engine, exclude_customer=lambda cid: str(cid).startswith("TESTSIM")
    )
    assert excluded["premium_posted"] == 90.0
    assert excluded["risk_posted"] == 72.0

    txs = [
        {"type": "premium_payment", "amount": 90.0, "customer_id": "CUST-REAL"},
        {"type": "premium_payment", "amount": 500.0, "customer_id": "TESTSIM-1"},
        {"type": "claim_payment_received", "amount": 10.0, "customer_id": "CUST-REAL"},
        {"type": "claim_payment_received", "amount": 40.0, "customer_id": "TESTSIM-1"},
    ]
    econ = economic_claims_reserve(
        transactions=txs,
        engine=engine,
        exclude_customer=lambda cid: str(cid).startswith("TESTSIM"),
    )
    assert econ["risk_cash_collected"] == 72.0
    assert econ["claim_cash_paid"] == 10.0
    assert econ["economic_claims_reserve"] == 62.0


def test_partial_installments_each_post_their_increment():
    """A bill paid in two installments must post both increments, not just one."""
    engine = get_accounting_engine()
    policy = {
        "id": "POL-INST",
        "annual_premium": 1200.0,
        "risk_premium_annual": 1200.0,
        "savings_premium_annual": 0.0,
        "pricing_source": "pricing_kernel",
    }
    billing = {"BILL-INST": {"id": "BILL-INST", "policy_id": "POL-INST"}}

    billing["BILL-INST"]["amount_paid"] = 40.0
    first = post_collected_premiums_to_accounting(
        customer_id="CUST-INST",
        policy_id="POL-INST",
        policy=policy,
        amount=40.0,
        bills_paid=["BILL-INST"],
        billing=billing,
        source_tx_id="TX-INST-1",
        fallback_risk_pct=100,
        engine=engine,
        bill_payments={"BILL-INST": 40.0},
    )
    assert all(r["posted"] for r in first)

    billing["BILL-INST"]["amount_paid"] = 100.0
    second = post_collected_premiums_to_accounting(
        customer_id="CUST-INST",
        policy_id="POL-INST",
        policy=policy,
        amount=60.0,
        bills_paid=["BILL-INST"],
        billing=billing,
        source_tx_id="TX-INST-2",
        fallback_risk_pct=100,
        engine=engine,
        bill_payments={"BILL-INST": 60.0},
    )
    assert all(r["posted"] for r in second)
    assert accounting_book_totals(engine)["premium_posted"] == 100.0


def test_same_ledger_payment_is_still_idempotent():
    """Re-posting the same ledger payment for a bill must not double-book."""
    engine = get_accounting_engine()
    first = post_premium_to_accounting_book(
        bill_id="BILL-IDEM",
        policy_id="POL-IDEM",
        customer_id="CUST-IDEM",
        amount=50.0,
        risk_percentage=100,
        source_tx_id="TX-IDEM",
        engine=engine,
    )
    assert first["posted"] is True
    again = post_premium_to_accounting_book(
        bill_id="BILL-IDEM",
        policy_id="POL-IDEM",
        customer_id="CUST-IDEM",
        amount=50.0,
        risk_percentage=100,
        source_tx_id="TX-IDEM",
        engine=engine,
    )
    assert again["posted"] is False
    assert again["reason"] == "already_posted"
    assert accounting_book_totals(engine)["premium_posted"] == 50.0


def test_unbilled_leftover_does_not_double_count_later_bill():
    """Cash posted as UNBILLED-{tx} must not post again when the bill appears."""
    engine = get_accounting_engine()
    policy = {
        "id": "POL-UNB",
        "annual_premium": 1200.0,
        "risk_premium_annual": 1200.0,
        "savings_premium_annual": 0.0,
        "pricing_source": "pricing_kernel",
    }
    leftover = post_collected_premiums_to_accounting(
        customer_id="CUST-UNB",
        policy_id="POL-UNB",
        policy=policy,
        amount=80.0,
        bills_paid=[],
        billing={},
        source_tx_id="TX-UNB",
        fallback_risk_pct=100,
        engine=engine,
        unbilled_amount=80.0,
    )
    assert leftover and leftover[0]["posted"] is True
    assert leftover[0]["bill_id"] == "UNBILLED-TX-UNB"

    later = post_collected_premiums_to_accounting(
        customer_id="CUST-UNB",
        policy_id="POL-UNB",
        policy=policy,
        amount=80.0,
        bills_paid=["BILL-UNB"],
        billing={"BILL-UNB": {"id": "BILL-UNB", "policy_id": "POL-UNB", "amount_paid": 80.0}},
        source_tx_id="TX-UNB",
        fallback_risk_pct=100,
        engine=engine,
        bill_payments={"BILL-UNB": 80.0},
    )
    assert later and later[0]["posted"] is False
    assert later[0]["reason"] == "already_posted"
    assert accounting_book_totals(engine)["premium_posted"] == 80.0


def test_collected_premiums_use_kernel_split_per_bill():
    engine = get_accounting_engine()
    policy = {
        "id": "POL-K2",
        "annual_premium": 1200.0,
        "risk_premium_annual": 1200.0,
        "savings_premium_annual": 0.0,
        "pricing_source": "pricing_kernel",
    }
    billing = {
        "BILL-A": {
            "id": "BILL-A",
            "policy_id": "POL-K2",
            "amount_paid": 100.0,
        }
    }
    results = post_collected_premiums_to_accounting(
        customer_id="CUST-2",
        policy_id="POL-K2",
        policy=policy,
        amount=130.0,
        bills_paid=["BILL-A"],
        billing=billing,
        source_tx_id="TX-2",
        fallback_risk_pct=50,
        unbilled_amount=30.0,
        engine=engine,
    )
    assert len(results) == 2
    assert all(r["posted"] for r in results)
    allocs = list(engine.allocations.values())
    assert all(float(a.risk_percentage) == 100.0 for a in allocs)
    assert accounting_book_totals(engine)["premium_posted"] == 130.0


def test_reconcile_flags_paid_claim_missing_customer_ledger():
    claims = {
        "CLM-X": {
            "id": "CLM-X",
            "customer_id": "CUST-X",
            "status": "paid",
            "approved_amount": 500.0,
        }
    }
    report = reconcile_financial_books(
        policies={},
        claims=claims,
        billing={},
        transactions=[],
        balance_sheet={"revenue_breakdown": {}, "expense_breakdown": {}, "claims_reserve": 0},
    )
    assert report["is_consistent"] is False
    checks = {d["check"] for d in report["discrepancies"]}
    assert "claims_records_vs_customer_ledger" in checks
    assert "paid_claims_missing_customer_ledger" in checks
    assert report["claims"]["missing_ledger_claim_ids"] == ["CLM-X"]


def test_reconcile_is_consistent_when_ledger_matches_books():
    reset_accounting_engine()
    engine = get_accounting_engine()
    post_premium_to_accounting_book(
        bill_id="BILL-OK",
        policy_id="POL-OK",
        customer_id="CUST-OK",
        amount=90.0,
        risk_percentage=100,
        source_tx_id="TX-OK",
        engine=engine,
    )
    engine.post_claim_payment(
        claim_id="CLM-OK",
        policy_id="POL-OK",
        customer_id="CUST-OK",
        amount=Decimal("25.00"),
    )
    transactions = [
        {
            "id": "TX-OK",
            "customer_id": "CUST-OK",
            "type": "premium_payment",
            "amount": 90.0,
            "metadata": {"bill_id": "BILL-OK"},
        },
        {
            "id": "TX-CLM",
            "customer_id": "CUST-OK",
            "type": "claim_payment_received",
            "amount": 25.0,
            "metadata": {"claim_id": "CLM-OK"},
        },
    ]
    report = reconcile_financial_books(
        policies={
            "POL-OK": {
                "id": "POL-OK",
                "customer_id": "CUST-OK",
                "annual_premium": 1080.0,
                "pricing_source": "pricing_kernel",
                "risk_premium_annual": 1080.0,
                "savings_premium_annual": 0.0,
            }
        },
        claims={
            "CLM-OK": {
                "id": "CLM-OK",
                "customer_id": "CUST-OK",
                "status": "paid",
                "approved_amount": 25.0,
            }
        },
        billing={
            "BILL-OK": {
                "id": "BILL-OK",
                "customer_id": "CUST-OK",
                "amount_paid": 90.0,
            }
        },
        transactions=transactions,
        balance_sheet={
            "revenue_breakdown": {"premium_income": 90.0},
            "expense_breakdown": {"claims_paid": 25.0},
            "claims_reserve": 3475.0,
            "seed_claims_reserve": 3_500_000.0,
        },
        engine=engine,
    )
    assert report["is_consistent"] is True, report["discrepancies"]
    assert report["premiums"]["customer_ledger"]["total"] == 90.0
    assert report["claims"]["customer_ledger"]["total"] == 25.0
    assert report["authority"]["cash_identity"] == "customer_ledger"
    assert report["reserves"]["identity"] == "ledger_risk_cash_minus_claim_cash"
    assert report["reserves"]["economic_claims_reserve"] == 65.0
    assert report["reserves"]["seed_claims_reserve"] == 3_500_000.0
    assert report["reserves"]["balance_sheet_claims_reserve"] == 3475.0


def test_economic_claims_reserve_is_risk_cash_minus_claim_cash():
    reset_accounting_engine()
    engine = get_accounting_engine()
    post_premium_to_accounting_book(
        bill_id="BILL-ECON",
        policy_id="POL-ECON",
        customer_id="CUST-ECON",
        amount=200.0,
        risk_percentage=80,
        source_tx_id="TX-ECON",
        engine=engine,
    )
    txs = [
        {"type": "premium_payment", "amount": 200.0, "customer_id": "CUST-ECON"},
        {"type": "claim_payment_received", "amount": 40.0, "customer_id": "CUST-ECON"},
    ]
    result = economic_claims_reserve(transactions=txs, engine=engine)
    assert result["risk_cash_collected"] == 160.0
    assert result["claim_cash_paid"] == 40.0
    assert result["economic_claims_reserve"] == 120.0
    assert result["identity"] == "ledger_risk_cash_minus_claim_cash"


def test_reserves_reporting_uses_kernel_pin_not_seventy_five_percent():
    from services.reserves_reporting_service import ReservesReportingService

    reset_accounting_engine()
    policies = {
        "POL-R": {
            "id": "POL-R",
            "annual_premium": 1200.0,
            "risk_premium_annual": 900.0,
            "savings_premium_annual": 300.0,
            "pricing_source": "pricing_kernel",
        }
    }
    bills = {
        "BILL-R": {
            "id": "BILL-R",
            "policy_id": "POL-R",
            "status": "paid",
            "amount_paid": 100.0,
        }
    }
    svc = ReservesReportingService(
        premium_allocation_tracker=None,
        policies=policies,
        claims={},
        bills=bills,
    )
    summary = svc.calculate_reserve_summary()
    assert summary.gross_risk_reserve == Decimal("75.00")
    report = svc.generate_full_report()
    assert "75%" not in report["risk_reserves"]["source"]
    assert "kernel" in report["risk_reserves"]["source"]


def test_reserves_reporting_excludes_sandbox_book_risk():
    from services.reserves_reporting_service import ReservesReportingService

    reset_accounting_engine()
    engine = get_accounting_engine()
    post_premium_to_accounting_book(
        bill_id="BILL-RES-REAL",
        policy_id="POL-RES-REAL",
        customer_id="CUST-RES-REAL",
        amount=100.0,
        risk_percentage=100,
        source_tx_id="TX-RES-REAL",
        engine=engine,
    )
    post_premium_to_accounting_book(
        bill_id="BILL-RES-SANDBOX",
        policy_id="POL-RES-SANDBOX",
        customer_id="TESTSIM-RES",
        amount=400.0,
        risk_percentage=100,
        source_tx_id="TX-RES-SANDBOX",
        engine=engine,
    )
    svc = ReservesReportingService(
        premium_allocation_tracker=None,
        policies={},
        claims={},
        bills={},
    )
    summary = svc.calculate_reserve_summary()
    assert summary.gross_risk_reserve == Decimal("100.00")


def test_ledger_cash_aliases_and_paid_claim_records():
    txs = [
        {"type": "premium_payment", "amount": 10, "customer_id": "C1"},
        {"type": "auto_pay_execution", "amount": 15, "customer_id": "C1"},
        {"type": "claim_payment_received", "amount": 7, "customer_id": "C1"},
        {"tx_type": "claim_payment", "amount": 3, "customer_id": "C1"},
        {"type": "wallet_deposit", "amount": 99, "customer_id": "C1"},
        {"type": "bulk_premium_payment", "amount": -20, "customer_id": "C1"},
    ]
    prem = ledger_cash_total(txs, PREMIUM_CASH_TYPES)
    clm = ledger_cash_total(txs, CLAIM_CASH_TYPES)
    # auto_pay_execution is an audit twin and must not count as cash.
    assert prem["total"] == 30.0  # 10 + abs(-20)
    assert clm["total"] == 10.0
    assert sum_paid_claim_records([
        {"status": "paid", "approved_amount": 7},
        {"status": "approved", "approved_amount": 100},
        {"status": "closed", "paid_amount": 3},
    ]) == Decimal("10.00")


def test_pin_kernel_fields_is_additive():
    policy = {"id": "P", "annual_premium": 1}
    pin_kernel_fields_on_policy(policy, {
        "pricing_source": "pricing_kernel",
        "integrity_hash": "h",
        "risk_premium_annual": 80,
        "savings_premium_annual": 20,
    })
    assert policy["integrity_hash"] == "h"
    assert policy["risk_premium_annual"] == 80
    pin_kernel_fields_on_policy(policy, {"integrity_hash": "should-not-overwrite"})
    assert policy["integrity_hash"] == "h"


def test_premium_payment_posts_customer_ledger_and_accounting_book():
    """Live payment path: one amount on the ledger and the accounting book."""
    from web_portal.server import (
        BILLING,
        CUSTOMERS,
        POLICIES,
        TRANSACTION_LEDGER,
        process_customer_premium_payment,
    )

    reset_accounting_engine()
    customer_id = "CUST-UNIFY-LIVE"
    policy_id = "POL-UNIFY-LIVE"
    bill_id = "BILL-UNIFY-LIVE"
    CUSTOMERS[customer_id] = {"id": customer_id, "name": "Unify Live"}
    POLICIES[policy_id] = {
        "id": policy_id,
        "customer_id": customer_id,
        "annual_premium": 1200.0,
        "risk_premium_annual": 960.0,
        "savings_premium_annual": 240.0,
        "pricing_source": "pricing_kernel",
        "status": "active",
    }
    BILLING[bill_id] = {
        "id": bill_id,
        "customer_id": customer_id,
        "policy_id": policy_id,
        "amount": 100.0,
        "amount_due": 100.0,
        "amount_paid": 0.0,
        "status": "outstanding",
    }
    created_tx_ids = set(TRANSACTION_LEDGER.keys())
    try:
        result = process_customer_premium_payment(
            customer_id=customer_id,
            amount=100.0,
            policy_id=policy_id,
            specific_bill_ids=[bill_id],
            allocate_to_investments=False,
            use_pipeline=False,
            notify_customer=False,
        )
        assert result.get("success") is True
        assert BILLING[bill_id]["status"] == "paid"
        new_txs = [
            tx for tx_id, tx in TRANSACTION_LEDGER.items()
            if tx_id not in created_tx_ids and tx.get("customer_id") == customer_id
        ]
        premium_txs = [tx for tx in new_txs if str(tx.get("type") or "").lower() == "premium_payment"]
        assert premium_txs, "premium payment must land on the customer ledger"
        assert float(premium_txs[0]["amount"]) == 100.0
        book = accounting_book_totals()
        assert book["premium_posted"] == 100.0
        engine = get_accounting_engine()
        posted = list(engine.allocations.values())
        assert posted
        assert float(posted[0].risk_percentage) == 80.0
    finally:
        CUSTOMERS.pop(customer_id, None)
        POLICIES.pop(policy_id, None)
        BILLING.pop(bill_id, None)
        for tx_id in list(TRANSACTION_LEDGER.keys()):
            if tx_id not in created_tx_ids:
                TRANSACTION_LEDGER.pop(tx_id, None)
        reset_accounting_engine()


def test_kernel_components_read_snapshot_when_policy_scalars_missing(monkeypatch):
    from services import pricing_shadow_service as shadow

    monkeypatch.setattr(
        shadow,
        "get_snapshots_for_policy",
        lambda _pid: [{
            "kernel_annual": 999.0,
            "integrity_hash": "snap-hash",
            "product_id": "phins_pure_risk_adjustable",
            "components": {
                "risk_premium_annual": 900.0,
                "savings_premium_annual": 99.0,
            },
        }],
    )
    comps = kernel_components_from_policy({"id": "POL-SNAP", "annual_premium": 10})
    assert comps["source"] == "premium_snapshot"
    assert comps["risk_premium_annual"] == 900.0
    assert comps["integrity_hash"] == "snap-hash"


def test_create_binds_accepted_chat_quote_provenance():
    from web_portal.server import _apply_accepted_quote_provenance

    recalculated = {
        "annual": 999.0,
        "monthly": 83.25,
        "quarterly": 242.22,
        "pricing_source": "pricing_kernel",
        "integrity_hash": "new-hash",
        "risk_premium_annual": 800.0,
    }
    bound = _apply_accepted_quote_provenance(recalculated, {
        "quote_provenance": {
            "pricing_source": "pricing_kernel",
            "quoted_annual": 120.0,
            "quoted_monthly": 10.0,
            "integrity_hash": "accepted-hash",
            "tables_version": "T1",
        }
    })
    assert bound["annual"] == 120.0
    assert bound["monthly"] == 10.0
    assert bound["integrity_hash"] == "accepted-hash"
    assert bound["quote_bound"] is True
    assert bound["tables_version"] == "T1"


def test_auto_pay_execution_is_audit_not_cash():
    assert "auto_pay_execution" in PREMIUM_AUDIT_TYPES
    assert "auto_pay_execution" not in PREMIUM_CASH_TYPES
    assert "bulk_premium_payment" in PREMIUM_CASH_TYPES
    txs = [
        {"type": "premium_payment", "amount": 50, "customer_id": "C1"},
        {"type": "auto_pay_execution", "amount": 50, "customer_id": "C1"},
    ]
    assert ledger_cash_total(txs, PREMIUM_CASH_TYPES)["total"] == 50.0


def test_accountant_frs_uses_ledger_claim_cash_not_approved_records():
    from services.financial_reporting_service import FinancialReportingService

    svc = FinancialReportingService(
        policies={},
        claims={
            "CLM-1": {"status": "approved", "approved_amount": 400},
            "CLM-2": {"status": "paid", "paid_amount": 25},
        },
        billing={},
        customers={},
        underwriting={},
        transaction_ledger={
            "TX-1": {"type": "claim_payment_received", "amount": 25, "customer_id": "C1"},
        },
    )
    summary = svc.get_dashboard_summary("accountant")
    assert summary["claims_paid"] == 25.0

    empty_ledger_svc = FinancialReportingService(
        policies={},
        claims={"CLM-1": {"status": "approved", "approved_amount": 400}},
        billing={},
        customers={},
        underwriting={},
        transaction_ledger={},
    )
    empty_summary = empty_ledger_svc.get_dashboard_summary("accountant")
    assert empty_summary["claims_paid"] == 0.0


def test_two_halves_of_a_growth_bill_still_credit_the_add_on():
    """Each installment is the change in the running waterfall, not a new stack."""
    from services.billing_service import BillingService
    from services.premium_allocation_tracker import PremiumAllocationTracker

    policies = {
        "POL-HALF": {
            "id": "POL-HALF",
            "customer_id": "CUST-HALF",
            "annual_premium": 2400.0,
            "risk_premium_annual": 2400.0,
            "savings_addon": "growth",
            "pricing_source": "pricing_kernel",
        }
    }
    bills = {}
    tracker = PremiumAllocationTracker(bills=bills, policies=policies)
    billing = BillingService(bills=bills, policies=policies, premium_allocation_tracker=tracker)
    bill = billing.create_bill("POL-HALF", 400.0, customer_id="CUST-HALF")
    assert bill["premium_allocation"]["risk_amount_due"] == 200.0
    assert bill["premium_allocation"]["savings_amount_due"] == 200.0

    first = billing.record_payment(bill["bill_id"], 200.0)
    assert first["premium_allocation"]["risk_amount_paid"] == 200.0
    assert first["premium_allocation"]["savings_amount_paid"] == 0.0

    second = billing.record_payment(bill["bill_id"], 200.0)
    assert second["status"] == "paid"
    assert second["premium_allocation"]["risk_amount_paid"] == 200.0
    assert second["premium_allocation"]["savings_amount_paid"] == 200.0
    recorded = next(iter(tracker.allocations.values()))
    assert float(recorded.risk_amount) == 200.0
    assert float(recorded.savings_amount) == 200.0


def test_payment_over_a_finished_month_keeps_the_extra_dollar_on_risk():
    """Rounded bill percentages must not move the next month's first dollar."""
    from services.billing_service import BillingService

    policies = {
        "POL-OVER": {
            "id": "POL-OVER",
            "customer_id": "CUST-OVER",
            "annual_premium": 2400.0,
            "risk_premium_annual": 2400.0,
            "savings_addon": "growth",
            "pricing_source": "pricing_kernel",
        }
    }
    billing = BillingService(bills={}, policies=policies)
    one_shot = billing.create_bill("POL-OVER", 401.0, customer_id="CUST-OVER")
    assert one_shot["premium_allocation"]["risk_amount_due"] == 201.0
    assert one_shot["premium_allocation"]["savings_amount_due"] == 200.0
    paid_once = billing.record_payment(one_shot["bill_id"], 401.0, auto_allocate=False)
    assert paid_once["premium_allocation"]["risk_amount_paid"] == 201.0
    assert paid_once["premium_allocation"]["savings_amount_paid"] == 200.0

    stepped = billing.create_bill("POL-OVER", 401.0, customer_id="CUST-OVER")
    billing.record_payment(stepped["bill_id"], 400.0, auto_allocate=False)
    paid_step = billing.record_payment(stepped["bill_id"], 1.0, auto_allocate=False)
    assert paid_step["premium_allocation"]["savings_amount_paid"] == 200.0
    assert paid_step["premium_allocation"]["risk_amount_paid"] == 201.0


def test_unstamped_bill_payment_does_not_send_half_the_premium_to_savings():
    from services.billing_service import BillingService

    policies = {
        "POL-NOSPLIT": {
            "id": "POL-NOSPLIT",
            "customer_id": "CUST-NOSPLIT",
            "annual_premium": 1200.0,
            "monthly_premium": 100.0,
            "risk_premium_annual": 1200.0,
            "savings_premium_annual": 0.0,
            "pricing_source": "pricing_kernel",
        }
    }
    bills = {
        "BILL-NOSPLIT": {
            "bill_id": "BILL-NOSPLIT",
            "policy_id": "POL-NOSPLIT",
            "customer_id": "CUST-NOSPLIT",
            "amount_due": 100.0,
            "amount_paid": 0.0,
            "status": "outstanding",
        }
    }
    updated = BillingService(bills=bills, policies=policies).record_payment(
        "BILL-NOSPLIT", 100.0, auto_allocate=False
    )
    paid = updated["premium_allocation"]
    assert paid["savings_amount_paid"] == 0.0
    assert paid["risk_amount_paid"] == 100.0


def test_billing_service_payment_writes_ledger_and_accounting_book():
    from services.billing_service import BillingService
    from web_portal.server import POLICIES, TRANSACTION_LEDGER

    reset_accounting_engine()
    bills = {}
    customer_id = "CUST-BILL-SVC"
    policy_id = "POL-BILL-SVC"
    POLICIES[policy_id] = {
        "id": policy_id,
        "customer_id": customer_id,
        "annual_premium": 1000.0,
        "risk_premium_annual": 800.0,
        "savings_premium_annual": 200.0,
        "pricing_source": "pricing_kernel",
        "status": "active",
    }
    billing = BillingService(bills=bills, policies=POLICIES)
    bill = billing.create_bill(policy_id, 100.0, customer_id=customer_id)
    created_tx_ids = set(TRANSACTION_LEDGER.keys())
    try:
        billing.record_payment(bill["bill_id"], 40.0)
        new_txs = [
            tx for tx_id, tx in TRANSACTION_LEDGER.items()
            if tx_id not in created_tx_ids and tx.get("customer_id") == customer_id
        ]
        premium_txs = [tx for tx in new_txs if str(tx.get("type") or "").lower() == "premium_payment"]
        assert premium_txs
        assert float(premium_txs[0]["amount"]) == 40.0
        assert accounting_book_totals()["premium_posted"] == 40.0
        assert bills[bill["bill_id"]]["status"] == "partial"
        billing.record_payment(bill["bill_id"], 60.0)
        assert accounting_book_totals()["premium_posted"] == 100.0
        assert bills[bill["bill_id"]]["status"] == "paid"
    finally:
        POLICIES.pop(policy_id, None)
        for tx_id in list(TRANSACTION_LEDGER.keys()):
            if tx_id not in created_tx_ids:
                TRANSACTION_LEDGER.pop(tx_id, None)
        reset_accounting_engine()


def test_monthly_distribution_uses_kernel_pin_not_quote_override():
    """Issued risk/savings come from the policy pin, never a re-price."""
    import web_portal.server as portal

    customer_id = "CUST-PIN-DIST"
    policy_id = "POL-PIN-DIST"
    portal.CUSTOMERS[customer_id] = {"id": customer_id, "name": "Pin Dist", "age": 40}
    portal.POLICIES[policy_id] = {
        "id": policy_id,
        "customer_id": customer_id,
        "type": "life",
        "coverage_amount": 250000.0,
        "annual_premium": 1000.0,
        "monthly_premium": 83.33,
        "status": "active",
        "risk_score": "medium",
        "risk_premium_annual": 800.0,
        "savings_premium_annual": 200.0,
        "pricing_source": "pricing_kernel",
        "integrity_hash": "pin-hash",
    }
    try:
        dist = portal.calculate_monthly_distribution(customer_id)
        assert dist["actuarial_data"]["total_risk_premium"] == 800.0
        assert dist["actuarial_data"]["total_savings_premium"] == 200.0
        assert dist["actuarial_data"]["data_source"] == "pricing_kernel_pin"
        assert dist["active_policies"][0]["integrity_hash"] == "pin-hash"
        portal.POLICIES[policy_id]["adl_level"] = 5
        portal.POLICIES[policy_id]["adl_level_source"] = "unspecified_baseline"
        labeled = portal.calculate_monthly_distribution(customer_id)
        assert labeled["active_policies"][0]["adl_level"] is None
        assert labeled["actuarial_data"]["total_risk_premium"] == 800.0
        assert portal.POLICIES[policy_id]["monthly_premium"] == 83.33
        assert portal.POLICIES[policy_id]["adl_level"] == 5
        # Cash split still follows customer allocation on the issued monthly.
        assert abs(dist["distribution"]["risk_coverage"] + dist["distribution"]["total_savings"]
                   - dist["total_monthly_premium"]) < 0.01
    finally:
        portal.POLICIES.pop(policy_id, None)
        portal.CUSTOMERS.pop(customer_id, None)


def test_simulate_coverage_quotes_through_calculate_premium():
    from pathlib import Path

    source = Path(__file__).resolve().parents[1] / "web_portal" / "server.py"
    text = source.read_text(encoding="utf-8")
    assert "premium_data = calculate_premium(quote_payload)" in text
    assert "base_rates = {'life': 0.012" not in text
    assert "calculate_age_adjusted_premium(base_annual_premium" not in text


def _repair_fixture(risk_pct=100.0):
    """Paid bill + paid claim with no customer-ledger rows (early durability gap)."""
    annual = 1200.0
    risk = round(annual * risk_pct / 100.0, 2)
    savings = round(annual - risk, 2)
    policies = {
        "POL-R": {
            "id": "POL-R",
            "customer_id": "CUST-R",
            "annual_premium": annual,
            "risk_premium_annual": risk,
            "savings_premium_annual": savings,
            "pricing_source": "pricing_kernel",
        }
    }
    billing = {
        "BILL-R": {
            "id": "BILL-R",
            "bill_id": "BILL-R",
            "policy_id": "POL-R",
            "customer_id": "CUST-R",
            "amount": 100.0,
            "amount_paid": 100.0,
            "status": "paid",
        }
    }
    claims = {
        "CLM-R": {
            "id": "CLM-R",
            "customer_id": "CUST-R",
            "policy_id": "POL-R",
            "status": "paid",
            "paid_amount": 40.0,
        }
    }
    sheet = {
        "revenue_breakdown": {"premium_income": 0.0, "management_fees": 5.0},
        "expense_breakdown": {"claims_paid": 0.0},
        "claims_reserve": 3_400_000.0,
        "seed_claims_reserve": 3_500_000.0,
    }
    return policies, billing, claims, sheet


def test_repair_dry_run_does_not_mutate_books():
    reset_accounting_engine()
    engine = get_accounting_engine()
    policies, billing, claims, sheet = _repair_fixture()
    transactions = {}
    report = repair_financial_books(
        policies=policies,
        claims=claims,
        billing=billing,
        transactions=transactions,
        balance_sheet=sheet,
        engine=engine,
        dry_run=True,
    )
    assert report["dry_run"] is True
    assert transactions == {}
    assert accounting_book_totals(engine)["premium_posted"] == 0.0
    assert accounting_book_totals(engine)["claims_posted"] == 0.0
    assert sheet["revenue_breakdown"]["premium_income"] == 0.0
    assert sheet["seed_claims_reserve"] == 3_500_000.0
    actions = {a["action"] for a in report["actions"]}
    assert "append_premium_ledger" in actions
    assert "append_claim_ledger" in actions
    assert "post_premium_accounting" in actions
    assert "post_claim_accounting" in actions
    assert "derive_balance_sheet_from_ledger" in actions


def test_repair_reconstructs_missing_cash_and_aligns_books():
    reset_accounting_engine()
    engine = get_accounting_engine()
    policies, billing, claims, sheet = _repair_fixture(risk_pct=100.0)
    transactions = {}
    report = repair_financial_books(
        policies=policies,
        claims=claims,
        billing=billing,
        transactions=transactions,
        balance_sheet=sheet,
        engine=engine,
        dry_run=False,
        actor="unit_repair",
    )
    premium_txs = [
        tx for tx in transactions.values()
        if str(tx.get("type")) == "premium_payment"
    ]
    claim_txs = [
        tx for tx in transactions.values()
        if str(tx.get("type")) == "claim_payment_received"
    ]
    assert len(premium_txs) == 1
    assert premium_txs[0]["amount"] == 100.0
    assert premium_txs[0]["metadata"]["bill_id"] == "BILL-R"
    assert len(claim_txs) == 1
    assert claim_txs[0]["amount"] == 40.0
    assert claim_txs[0]["metadata"]["claim_id"] == "CLM-R"

    totals = accounting_book_totals(engine)
    assert totals["premium_posted"] == 100.0
    assert totals["claims_posted"] == 40.0
    assert sheet["revenue_breakdown"]["premium_income"] == 100.0
    assert sheet["expense_breakdown"]["claims_paid"] == 40.0
    assert sheet["revenue_breakdown"]["management_fees"] == 5.0
    assert sheet["seed_claims_reserve"] == 3_500_000.0
    assert sheet["claims_reserve"] == 3_400_000.0
    assert policies["POL-R"]["annual_premium"] == 1200.0
    assert billing["BILL-R"]["amount"] == 100.0
    assert report["after"]["is_consistent"] is True, report["after"]["discrepancies"]
    assert report["after"]["discrepancy_count"] == 0


def test_repair_is_idempotent_and_never_rewrites_seed_or_billed_premium():
    reset_accounting_engine()
    engine = get_accounting_engine()
    policies, billing, claims, sheet = _repair_fixture()
    transactions = {}
    first = repair_financial_books(
        policies=policies,
        claims=claims,
        billing=billing,
        transactions=transactions,
        balance_sheet=sheet,
        engine=engine,
    )
    ledger_ids = set(transactions)
    seed = sheet["seed_claims_reserve"]
    second = repair_financial_books(
        policies=policies,
        claims=claims,
        billing=billing,
        transactions=transactions,
        balance_sheet=sheet,
        engine=engine,
    )
    assert second["action_count"] == 0
    assert set(transactions) == ledger_ids
    assert sheet["seed_claims_reserve"] == seed == 3_500_000.0
    assert policies["POL-R"]["annual_premium"] == 1200.0
    assert billing["BILL-R"]["amount"] == 100.0
    assert first["after"]["premiums"]["customer_ledger"]["total"] == 100.0


def test_repair_does_not_invent_savings_portfolio_deposits():
    reset_accounting_engine()
    engine = get_accounting_engine()
    policies, billing, claims, sheet = _repair_fixture(risk_pct=80.0)
    transactions = {}
    investments = {}
    report = repair_financial_books(
        policies=policies,
        claims=claims,
        billing=billing,
        transactions=transactions,
        balance_sheet=sheet,
        investment_accounts=investments,
        savings_pipeline_accounts={},
        engine=engine,
    )
    assert investments == {}
    savings = report["after"]["savings"]
    assert savings["kernel_savings_cash"] == 20.0
    assert savings["savings_landed"] == 0.0
    checks = {d["check"] for d in report["after"]["discrepancies"]}
    assert "savings_cash_not_landed_in_portfolios" in checks
    assert "paid_bills_missing_customer_ledger" not in checks
    assert "paid_claims_missing_customer_ledger" not in checks


def test_repair_books_every_claim_slice_not_just_the_first():
    reset_accounting_engine()
    engine = get_accounting_engine()
    policies, billing, claims, sheet = _repair_fixture()
    # Early durability left part of the claim cash on the ledger and nothing
    # on the book; repair appends the remainder as a second row.
    transactions = {
        "TX-CLM-PARTIAL": {
            "id": "TX-CLM-PARTIAL",
            "customer_id": "CUST-R",
            "type": "claim_payment_received",
            "amount": 15.0,
            "metadata": {"claim_id": "CLM-R", "policy_id": "POL-R"},
        }
    }
    report = repair_financial_books(
        policies=policies,
        claims=claims,
        billing=billing,
        transactions=transactions,
        balance_sheet=sheet,
        engine=engine,
    )
    claim_txs = [
        tx for tx in transactions.values()
        if str(tx.get("type")) == "claim_payment_received"
    ]
    assert len(claim_txs) == 2
    assert sum(float(tx["amount"]) for tx in claim_txs) == 40.0
    assert accounting_book_totals(engine)["claims_posted"] == 40.0
    assert report["after"]["is_consistent"] is True, report["after"]["discrepancies"]


def test_kernel_split_never_borrows_another_policy_of_the_same_customer():
    policies = {
        "POL-RISK": {
            "id": "POL-RISK",
            "customer_id": "CUST-M",
            "annual_premium": 1000.0,
            "risk_premium_annual": 1000.0,
            "savings_premium_annual": 0.0,
            "pricing_source": "pricing_kernel",
        },
        "POL-SAVE": {
            "id": "POL-SAVE",
            "customer_id": "CUST-M",
            "annual_premium": 1000.0,
            "risk_premium_annual": 200.0,
            "savings_premium_annual": 800.0,
            "pricing_source": "pricing_kernel",
        },
    }
    untagged = {"type": "premium_payment", "amount": 100.0, "customer_id": "CUST-M"}
    ambiguous = kernel_savings_cash_from_ledger([untagged], policies)
    # No single pin can be chosen, so the cash stays risk and is not POL-SAVE's 80%.
    assert ambiguous["savings_amount"] == 0.0
    assert ambiguous["risk_amount"] == 100.0

    tagged = dict(untagged, metadata={"policy_id": "POL-SAVE"})
    own_split = kernel_savings_cash_from_ledger([tagged], policies)
    assert own_split["savings_amount"] == 80.0
    assert own_split["risk_amount"] == 20.0

    only_savings_policy = {"POL-SAVE": policies["POL-SAVE"]}
    sole = kernel_savings_cash_from_ledger([untagged], only_savings_policy)
    assert sole["savings_amount"] == 80.0


def test_seed_claims_reserve_is_pinned_once():
    sheet = {"claims_reserve": 1.0}
    first = ensure_seed_claims_reserve(sheet)
    assert first == 3_500_000.0
    sheet["claims_reserve"] = 99.0
    again = ensure_seed_claims_reserve(sheet, founding_capital=1.0)
    assert again == 3_500_000.0
    assert sheet["seed_claims_reserve"] == 3_500_000.0


def test_apply_ledger_derived_balance_sheet_does_not_touch_seed():
    sheet = {
        "revenue_breakdown": {"premium_income": 1.0, "fees": 2.0},
        "expense_breakdown": {"claims_paid": 9.0},
        "seed_claims_reserve": 3_500_000.0,
        "claims_reserve": 3_400_000.0,
    }
    derived = apply_ledger_derived_balance_sheet(sheet, 50.0, 12.0)
    assert derived["premium_income"] == 50.0
    assert derived["claims_paid"] == 12.0
    assert sheet["seed_claims_reserve"] == 3_500_000.0
    assert sheet["claims_reserve"] == 3_400_000.0
    assert sheet["revenue_breakdown"]["fees"] == 2.0


def test_savings_books_flag_invented_investment_deposits():
    txs = [
        {
            "type": "premium_payment",
            "amount": 100.0,
            "customer_id": "CUST-S",
            "metadata": {"policy_id": "POL-S"},
        }
    ]
    policies = {
        "POL-S": {
            "id": "POL-S",
            "customer_id": "CUST-S",
            "annual_premium": 1000.0,
            "risk_premium_annual": 800.0,
            "savings_premium_annual": 200.0,
            "pricing_source": "pricing_kernel",
        }
    }
    investments = {
        "CUST-S": {
            "balance": 500.0,
            "deposits": [
                {"type": "premium_allocation", "amount": 80.0},
            ],
        }
    }
    books = savings_and_investments_books(
        transactions=txs,
        policies=policies,
        investment_accounts=investments,
        savings_pipeline_accounts=None,
    )
    assert books["kernel_savings_cash"] == 20.0
    assert books["investment_premium_allocations"] == 80.0
    report = reconcile_financial_books(
        policies=policies,
        claims={},
        billing={
            "BILL-S": {
                "id": "BILL-S",
                "customer_id": "CUST-S",
                "amount_paid": 100.0,
            }
        },
        transactions=txs,
        investment_accounts=investments,
    )
    checks = {d["check"] for d in report["discrepancies"]}
    assert "investment_allocations_exceed_savings_premium" in checks


def test_post_claim_payment_is_idempotent_on_claim_id():
    reset_accounting_engine()
    engine = get_accounting_engine()
    ok1, _ = engine.post_claim_payment(
        claim_id="CLM-IDEM",
        policy_id="POL-IDEM",
        customer_id="CUST-IDEM",
        amount=Decimal("15.00"),
    )
    ok2, msg = engine.post_claim_payment(
        claim_id="CLM-IDEM",
        policy_id="POL-IDEM",
        customer_id="CUST-IDEM",
        amount=Decimal("15.00"),
    )
    assert ok1 is True
    assert ok2 is True
    assert "already recorded" in msg
    assert accounting_book_totals(engine)["claims_posted"] == 15.0


def test_ledger_derived_balance_sheet_view_does_not_mutate_store():
    stored = {
        "revenue_breakdown": {"premium_income": 1.0, "fees": 2.0},
        "expense_breakdown": {"claims_paid": 9.0},
        "seed_claims_reserve": 3_500_000.0,
        "claims_reserve": 3_400_000.0,
        "total_revenue": 3.0,
        "total_expenses": 9.0,
    }
    view = ledger_derived_balance_sheet_view(stored, 80.0, 20.0)
    assert view["revenue_breakdown"]["premium_income"] == 80.0
    assert view["expense_breakdown"]["claims_paid"] == 20.0
    assert stored["revenue_breakdown"]["premium_income"] == 1.0
    assert stored["expense_breakdown"]["claims_paid"] == 9.0
    assert stored["total_revenue"] == 3.0
    assert stored["seed_claims_reserve"] == 3_500_000.0


def test_reconstruct_accounting_book_from_ledger_is_idempotent():
    reset_accounting_engine()
    txs = {
        "TX-P1": {
            "id": "TX-P1",
            "type": "premium_payment",
            "amount": 40.0,
            "customer_id": "C1",
            "metadata": {"bill_id": "BILL-1", "policy_id": "POL-1"},
        },
        "TX-C1": {
            "id": "TX-C1",
            "type": "claim_payment_received",
            "amount": 12.0,
            "customer_id": "C1",
            "metadata": {"claim_id": "CLM-1", "policy_id": "POL-1"},
        },
    }
    policies = {
        "POL-1": {
            "id": "POL-1",
            "customer_id": "C1",
            "annual_premium": 480.0,
            "risk_premium_annual": 480.0,
            "savings_premium_annual": 0.0,
            "pricing_source": "pricing_kernel",
        }
    }
    claims = {
        "CLM-1": {
            "id": "CLM-1",
            "customer_id": "C1",
            "policy_id": "POL-1",
            "status": "paid",
            "approved_amount": 12.0,
        }
    }
    first = reconstruct_accounting_book_from_ledger(
        policies=policies,
        claims=claims,
        billing={},
        transactions=txs,
        actor="test",
    )
    assert first["posted_count"] == 2
    totals = accounting_book_totals()
    assert totals["premium_posted"] == 40.0
    assert totals["claims_posted"] == 12.0
    second = reconstruct_accounting_book_from_ledger(
        policies=policies,
        claims=claims,
        billing={},
        transactions=txs,
        actor="test",
    )
    assert second["posted_count"] == 0
    assert accounting_book_totals()["premium_posted"] == 40.0


def test_kernel_quote_for_seed_rejects_auto():
    from services.pricing_shadow_service import kernel_quote_for_seed
    try:
        kernel_quote_for_seed({"type": "auto", "coverage_amount": 100000, "age": 40})
        raise AssertionError("auto should not kernel-price")
    except ValueError as exc:
        assert "non-kernel" in str(exc)


# ---------------------------------------------------------------------------
# Full kernel stack: every premium dollar lands on one stream
# ---------------------------------------------------------------------------

def _full_stack_policy(**extra):
    """Annual $3,557.68 = risk 1,960.15 + savings 980.08 + expense 294.02 + profit 323.43."""
    policy = {
        "id": "POL-FS",
        "customer_id": "CUST-FS",
        "annual_premium": 3557.68,
        "monthly_premium": 296.47,
        "pricing_source": "pricing_kernel",
        "risk_premium_annual": 1960.15,
        "savings_premium_annual": 980.08,
        "expense_loading_annual": 294.02,
        "profit_margin_annual": 323.43,
        "savings_addon": "balanced",
    }
    policy.update(extra)
    return policy


def test_a_closed_kernel_stack_shares_the_installment_to_the_cent():
    split = resolve_premium_split(296.47, _full_stack_policy())
    assert split["risk_amount"] == 163.35
    assert split["expense_amount"] == 24.50
    assert split["profit_amount"] == 26.95
    assert split["savings_amount"] == 81.67
    assert split["company_remainder"] == 0.0
    landed = Decimal("0")
    for key in ("risk_amount", "underwriting_fee_amount", "expense_amount", "profit_amount", "savings_amount"):
        landed += Decimal(str(split[key]))
    assert landed == Decimal("296.47")


def test_twelve_installments_of_a_closed_stack_leave_no_cent_above_it():
    policy = _full_stack_policy()
    for amount in (296.47, 100.00, 0.01, 3557.68, 17.33):
        split = resolve_premium_split(amount, policy)
        parts = sum(
            Decimal(str(split[key]))
            for key in ("risk_amount", "underwriting_fee_amount", "expense_amount", "profit_amount", "savings_amount")
        )
        assert parts == Decimal(str(amount)), (amount, split)
        assert split["company_remainder"] == 0.0


def test_pin_kernel_fields_carries_the_loadings():
    policy = {"id": "P", "annual_premium": 3557.68}
    pin_kernel_fields_on_policy(policy, {
        "pricing_source": "pricing_kernel",
        "risk_premium_annual": 1960.15,
        "savings_premium_annual": 980.08,
        "expense_loading_annual": 294.02,
        "profit_margin_annual": 323.43,
    })
    assert policy["expense_loading_annual"] == 294.02
    assert policy["profit_margin_annual"] == 323.43


def test_repin_replaces_the_money_pins_and_a_flat_reprice_clears_them():
    policy = _full_stack_policy()
    repin_kernel_fields_on_policy(policy, {
        "pricing_source": "pricing_kernel",
        "integrity_hash": "new",
        "risk_premium_annual": 1000.0,
        "savings_premium_annual": 0.0,
        "expense_loading_annual": 150.0,
        "profit_margin_annual": 165.0,
    })
    assert policy["risk_premium_annual"] == 1000.0
    assert policy["savings_premium_annual"] == 0.0
    assert policy["integrity_hash"] == "new"
    repin_kernel_fields_on_policy(policy, {"annual": 900.0, "monthly": 75.0})
    for key in ("risk_premium_annual", "savings_premium_annual", "expense_loading_annual", "profit_margin_annual"):
        assert policy[key] is None


def test_accounting_book_carries_the_cents_the_split_landed():
    engine = get_accounting_engine()
    policy = _full_stack_policy()
    post_collected_premiums_to_accounting(
        customer_id="CUST-FS",
        policy_id="POL-FS",
        policy=policy,
        amount=296.47,
        bills_paid=["BILL-FS"],
        billing={"BILL-FS": {"id": "BILL-FS", "policy_id": "POL-FS", "amount_paid": 296.47}},
        source_tx_id="TX-FS",
        fallback_risk_pct=100,
        engine=engine,
    )
    totals = accounting_book_totals(engine)
    assert totals["premium_posted"] == 296.47
    # A two-decimal percentage of 296.47 would have booked 81.68.
    assert totals["savings_posted"] == 81.67


def _savings_reconcile(landed):
    reset_accounting_engine()
    engine = get_accounting_engine()
    policy = _full_stack_policy()
    post_collected_premiums_to_accounting(
        customer_id="CUST-FS",
        policy_id="POL-FS",
        policy=policy,
        amount=296.47,
        bills_paid=["BILL-FS"],
        billing={"BILL-FS": {"id": "BILL-FS", "policy_id": "POL-FS", "amount_paid": 296.47}},
        source_tx_id="TX-FS",
        fallback_risk_pct=100,
        engine=engine,
    )
    return reconcile_financial_books(
        policies={"POL-FS": policy},
        claims={},
        billing={"BILL-FS": {"id": "BILL-FS", "customer_id": "CUST-FS", "policy_id": "POL-FS", "amount_paid": 296.47}},
        transactions=[{
            "id": "TX-FS", "customer_id": "CUST-FS", "type": "bill_payment", "amount": 296.47,
            "metadata": {"bill_id": "BILL-FS", "policy_id": "POL-FS"},
        }],
        balance_sheet={
            "revenue_breakdown": {"premium_income": 296.47},
            "expense_breakdown": {"claims_paid": 0.0},
            "claims_reserve": 3_500_000.0,
            "seed_claims_reserve": 3_500_000.0,
        },
        engine=engine,
        investment_accounts={},
        savings_landed_by_customer=landed,
    )


def test_reconcile_counts_savings_on_the_customers_own_books():
    report = _savings_reconcile({"CUST-FS": 81.67})
    assert report["is_consistent"] is True, report["discrepancies"]
    assert report["savings"]["savings_landed_basis"] == "customer_books"
    assert report["savings"]["savings_landed"] == 81.67
    assert report["savings"]["unlanded_savings_cash"] == 0.0
    assert report["premium_streams"] == {
        "risk": 163.35,
        "underwriting_fee": 0.0,
        "expense_loading": 24.5,
        "profit": 26.95,
        "savings": 81.67,
        "above_kernel_stack": 0.0,
        "without_kernel_pin": 0.0,
    }
    assert report["warnings"] == []


def test_reconcile_names_the_customer_whose_savings_never_landed():
    report = _savings_reconcile({"CUST-FS": 20.00})
    assert report["is_consistent"] is False
    item = next(d for d in report["discrepancies"] if d["check"] == "savings_cash_not_landed_in_portfolios")
    assert item["difference"] == 61.67
    assert item["customers"] == [{
        "customer_id": "CUST-FS",
        "savings_charged": 81.67,
        "savings_landed": 20.0,
        "not_landed": 61.67,
    }]


def test_a_customers_own_deposits_do_not_cover_another_customers_savings():
    """Extra money on one book is not counted against a different customer's gap."""
    report = _savings_reconcile({"CUST-FS": 0.0, "CUST-OTHER": 5000.0})
    assert report["savings"]["savings_landed"] == 0.0
    assert report["savings"]["unlanded_savings_cash"] == 81.67


def test_reconcile_warns_about_premium_cash_on_a_policy_with_no_pin():
    reset_accounting_engine()
    engine = get_accounting_engine()
    policy = {"id": "POL-NP", "customer_id": "CUST-NP", "annual_premium": 1200.0}
    post_premium_to_accounting_book(
        bill_id="BILL-NP", policy_id="POL-NP", customer_id="CUST-NP",
        amount=100.0, risk_percentage=100, source_tx_id="TX-NP", engine=engine,
    )
    report = reconcile_financial_books(
        policies={"POL-NP": policy},
        claims={},
        billing={"BILL-NP": {"id": "BILL-NP", "customer_id": "CUST-NP", "policy_id": "POL-NP", "amount_paid": 100.0}},
        transactions=[{
            "id": "TX-NP", "customer_id": "CUST-NP", "type": "bill_payment", "amount": 100.0,
            "metadata": {"bill_id": "BILL-NP", "policy_id": "POL-NP"},
        }],
        balance_sheet={
            "revenue_breakdown": {"premium_income": 100.0},
            "expense_breakdown": {"claims_paid": 0.0},
            "claims_reserve": 3_500_000.0,
            "seed_claims_reserve": 3_500_000.0,
        },
        engine=engine,
        savings_landed_by_customer={},
    )
    # The totals tie, so the books are in balance. The warning says what is not known.
    assert report["is_consistent"] is True, report["discrepancies"]
    warning = next(w for w in report["warnings"] if w["check"] == "premium_cash_without_kernel_pin")
    assert warning["amount"] == 100.0
    assert warning["policy_ids"] == ["POL-NP"]
    # It sits on the risk book, and it is shown apart from priced risk.
    assert report["savings"]["kernel_risk_cash"] == 100.0
    assert report["premium_streams"]["risk"] == 0.0
    assert report["premium_streams"]["without_kernel_pin"] == 100.0
    assert round(sum(report["premium_streams"].values()), 2) == 100.0


# ---------------------------------------------------------------------------
# A pin that arrives after the cash was booked: the book is re-split
# ---------------------------------------------------------------------------

def _booked_before_the_pin():
    """$296.47 booked all-risk on a policy with no pin, then the pin is restored."""
    reset_accounting_engine()
    engine = get_accounting_engine()
    billing = {"BILL-FS": {"id": "BILL-FS", "customer_id": "CUST-FS", "policy_id": "POL-FS", "amount_paid": 296.47}}
    transactions = [{
        "id": "TX-FS", "customer_id": "CUST-FS", "type": "bill_payment", "amount": 296.47,
        "metadata": {"bill_id": "BILL-FS", "policy_id": "POL-FS"},
    }]
    unpinned = {"id": "POL-FS", "customer_id": "CUST-FS", "annual_premium": 3557.68, "monthly_premium": 296.47}
    post_collected_premiums_to_accounting(
        customer_id="CUST-FS", policy_id="POL-FS", policy=unpinned, amount=296.47,
        bills_paid=["BILL-FS"], billing=billing, source_tx_id="TX-FS",
        fallback_risk_pct=100, engine=engine,
    )
    assert accounting_book_totals(engine)["risk_posted"] == 296.47
    return engine, {"POL-FS": _full_stack_policy()}, billing, transactions


def _books(engine, policies, billing, transactions):
    return reconcile_financial_books(
        policies=policies, claims={}, billing=billing, transactions=transactions,
        balance_sheet={
            "revenue_breakdown": {"premium_income": 296.47},
            "expense_breakdown": {"claims_paid": 0.0},
            "claims_reserve": 3_500_000.0,
            "seed_claims_reserve": 3_500_000.0,
        },
        engine=engine, investment_accounts={},
        savings_landed_by_customer={"CUST-FS": 81.67},
    )


def test_reconcile_reports_a_book_split_that_no_longer_matches_the_pin():
    engine, policies, billing, transactions = _booked_before_the_pin()
    report = _books(engine, policies, billing, transactions)
    assert report["is_consistent"] is False
    item = next(d for d in report["discrepancies"] if d["check"] == "accounting_book_split_vs_kernel_pins")
    assert item["book"] == {"risk": 296.47, "savings": 0.0}
    assert item["kernel"] == {"risk": 163.35, "savings": 81.67}
    assert item["difference"] == -81.67
    # The reserve bridge still reads the stale book until it is re-split.
    assert report["reserves"]["risk_cash_collected"] == 296.47


def test_resplit_reverses_the_old_posting_and_books_the_pinned_split():
    engine, policies, billing, transactions = _booked_before_the_pin()
    preview = resplit_accounting_book_premiums(
        policies=policies, billing=billing, transactions=transactions, engine=engine, dry_run=True,
    )
    assert preview["resplit_count"] == 1 and preview["dry_run"] is True
    assert accounting_book_totals(engine)["risk_posted"] == 296.47

    result = resplit_accounting_book_premiums(
        policies=policies, billing=billing, transactions=transactions, engine=engine, actor="accountant",
    )
    assert result["failed"] == []
    row = result["resplit"][0]
    assert row["before"] == {"risk": 296.47, "savings": 0.0}
    assert row["after"] == {"risk": 163.35, "savings": 81.67}
    totals = accounting_book_totals(engine)
    assert totals["premium_posted"] == 296.47
    assert totals["risk_posted"] == 163.35
    assert totals["savings_posted"] == 81.67
    assert totals["allocation_count"] == 1
    # The first posting stays on record, reversed, with contra entries.
    reversed_alloc = engine.allocations[row["reversed_allocation_id"]]
    assert reversed_alloc.status == AllocationStatus.REVERSED
    assert "reversed_by=accountant" in reversed_alloc.notes
    contra = [e for e in engine.ledger_entries if e.allocation_id == row["reversed_allocation_id"] and e.credit_amount > 0]
    assert [float(e.credit_amount) for e in contra] == [296.47]
    risk_fund = [e for e in engine.ledger_entries if e.account_type == AccountType.RISK_FUND][-1]
    assert float(risk_fund.balance) == 163.35

    report = _books(engine, policies, billing, transactions)
    assert report["is_consistent"] is True, report["discrepancies"]
    assert report["reserves"]["risk_cash_collected"] == 163.35

    again = resplit_accounting_book_premiums(
        policies=policies, billing=billing, transactions=transactions, engine=engine,
    )
    assert again["resplit_count"] == 0
    assert accounting_book_totals(engine)["allocation_count"] == 1


def test_resplit_is_limited_to_the_named_policies_and_ignores_a_cent():
    engine, policies, billing, transactions = _booked_before_the_pin()
    other = resplit_accounting_book_premiums(
        policies=policies, billing=billing, transactions=transactions, engine=engine,
        policy_ids=["POL-OTHER"],
    )
    assert other["resplit_count"] == 0
    assert accounting_book_totals(engine)["risk_posted"] == 296.47

    reset_accounting_engine()
    engine = get_accounting_engine()
    post_premium_to_accounting_book(
        bill_id="BILL-FS", policy_id="POL-FS", customer_id="CUST-FS", amount=296.47,
        risk_percentage=55.1, savings_percentage=27.55, source_tx_id="TX-FS", engine=engine,
        risk_amount=163.36, savings_amount=81.66,
    )
    cent = resplit_accounting_book_premiums(
        policies=policies, billing=billing, transactions=transactions, engine=engine,
    )
    assert cent["resplit_count"] == 0
    assert accounting_book_totals(engine)["risk_posted"] == 163.36


def test_books_repair_resplits_a_stale_posting():
    engine, policies, billing, transactions = _booked_before_the_pin()
    sheet = {
        "revenue_breakdown": {"premium_income": 296.47},
        "expense_breakdown": {"claims_paid": 0.0},
        "claims_reserve": 3_500_000.0,
        "seed_claims_reserve": 3_500_000.0,
    }
    ledger = {tx["id"]: tx for tx in transactions}
    dry = repair_financial_books(
        policies=policies, claims={}, billing=billing, transactions=ledger,
        balance_sheet=sheet, engine=engine, dry_run=True,
        savings_landed_by_customer={"CUST-FS": 81.67},
    )
    assert [a["action"] for a in dry["actions"]] == ["resplit_premium_accounting"]
    assert accounting_book_totals(engine)["risk_posted"] == 296.47

    done = repair_financial_books(
        policies=policies, claims={}, billing=billing, transactions=ledger,
        balance_sheet=sheet, engine=engine,
        savings_landed_by_customer={"CUST-FS": 81.67},
    )
    assert done["is_consistent"] is True, done["after"]["discrepancies"]
    assert accounting_book_totals(engine)["savings_posted"] == 81.67
    assert len(ledger) == 1 and sheet["revenue_breakdown"]["premium_income"] == 296.47


# ---------------------------------------------------------------------------
# Restoring a pin that was never stored: reproduce the premium or refuse
# ---------------------------------------------------------------------------

def _quote(annual, risk, savings, expense, profit, rate):
    return {
        "annual": annual,
        "monthly": round(annual / 12.0, 2),
        "pricing_source": "pricing_kernel",
        "integrity_hash": f"h-{annual}",
        "product_id": "phins_hybrid_savings" if rate else "phins_pure_risk_adjustable",
        "tables_version": "V2.0",
        "config_version": "cfg_v1",
        "risk_premium_annual": risk,
        "savings_premium_annual": savings,
        "expense_loading_annual": expense,
        "profit_margin_annual": profit,
        "savings_rate_used": rate,
        "savings_formula": "risk_premium_markup",
        "eligible": True,
    }


def _pricer(table):
    def price(payload):
        return table.get((float(payload["savings_rate"]), int(payload["term_years"])))
    return price


_STORED = {
    "id": "POL-R1", "customer_id": "CUST-R1", "type": "life", "coverage_amount": 500000,
    "annual_premium": 3557.68, "monthly_premium": 296.47, "status": "active",
}


def test_restore_offers_the_one_decomposition_that_reproduces_the_premium():
    table = {
        (0.0, 20): _quote(2479.59, 1960.15, 0.0, 294.02, 225.42, 0.0),
        (0.5, 20): _quote(3557.68, 1960.15, 980.08, 294.02, 323.43, 0.5),
        (1.0, 20): _quote(4635.76, 1960.15, 1960.15, 294.02, 421.44, 1.0),
    }
    result = kernel_pin_restore_candidate(dict(_STORED), application={"age": 40}, pricer=_pricer(table))
    assert result["status"] == "restorable"
    assert result["matches"] == [{"savings_addon": "balanced", "savings_rate": 0.5, "term_years": 20}]
    pins = result["pins"]
    assert pins["risk_premium_annual"] == 1960.15
    assert pins["savings_premium_annual"] == 980.08
    assert pins["expense_loading_annual"] == 294.02
    assert pins["profit_margin_annual"] == 323.43
    assert pins["savings_addon"] == "balanced"
    assert pins["kernel_pin_source"] == "restored_by_reprice"
    # The restored pins close the premium, so no cash is left above the stack.
    split = resolve_premium_split(296.47, {**_STORED, **pins})
    assert split["company_remainder"] == 0.0 and split["savings_amount"] == 81.67


def test_restore_refuses_when_no_kernel_price_gives_the_premium():
    table = {(0.0, 20): _quote(2479.59, 1960.15, 0.0, 294.02, 225.42, 0.0)}
    result = kernel_pin_restore_candidate(dict(_STORED), pricer=_pricer(table))
    assert result["status"] == "refused"
    assert result["reason"] == "no_kernel_price_reproduces_the_premium"
    assert result["pins"] == {}


def test_restore_refuses_when_two_decompositions_give_the_same_premium():
    table = {
        (0.5, 20): _quote(3557.68, 1960.15, 980.08, 294.02, 323.43, 0.5),
        (0.25, 30): _quote(3557.68, 2300.00, 575.00, 345.00, 337.68, 0.25),
    }
    calls = []

    def counting_pricer(payload):
        calls.append((float(payload["savings_rate"]), int(payload["term_years"])))
        return _pricer(table)(payload)

    result = kernel_pin_restore_candidate(dict(_STORED), pricer=counting_pricer)
    assert result["status"] == "refused"
    assert result["reason"] == "more_than_one_decomposition"
    assert result["pins"] == {}
    # Stop as soon as a second distinct stack appears; do not finish the full grid.
    assert len(calls) < 20


def test_restore_accepts_two_terms_that_price_identically():
    quote = _quote(3557.68, 1960.15, 980.08, 294.02, 323.43, 0.5)
    result = kernel_pin_restore_candidate(dict(_STORED), pricer=_pricer({(0.5, 20): quote, (0.5, 25): quote}))
    assert result["status"] == "restorable"
    assert len(result["matches"]) == 2


def test_restore_prefers_application_term_and_reuses_quote_cache():
    table = {
        (0.5, 25): _quote(3557.68, 1960.15, 980.08, 294.02, 323.43, 0.5),
        (0.5, 20): _quote(3400.00, 1900.00, 950.00, 285.00, 265.00, 0.5),
    }
    calls = []

    def counting_pricer(payload):
        calls.append((float(payload["savings_rate"]), int(payload["term_years"])))
        return _pricer(table)(payload)

    cache = {}
    first = kernel_pin_restore_candidate(
        dict(_STORED),
        application={"age": 40, "term_years": 25},
        pricer=counting_pricer,
        quote_cache=cache,
    )
    assert first["status"] == "restorable"
    assert first["matches"][0]["term_years"] == 25
    assert calls[0] == (0.0, 25)
    before = len(calls)
    second = kernel_pin_restore_candidate(
        dict(_STORED),
        application={"age": 40, "term_years": 25},
        pricer=counting_pricer,
        quote_cache=cache,
    )
    assert second["status"] == "restorable"
    assert len(calls) == before  # identical quotes served from the shared cache


def test_restore_keeps_an_underwriting_loading_as_the_company_fee():
    stored = {**_STORED, "annual_premium": 4802.87, "monthly_premium": 400.23}
    table = {(0.5, 20): {**_quote(3557.68, 1960.15, 980.08, 294.02, 323.43, 0.5), "monthly": 296.47}}
    result = kernel_pin_restore_candidate(
        stored, application={"premium_adjustment": 35}, pricer=_pricer(table),
    )
    assert result["status"] == "restorable", result
    pins = result["pins"]
    assert pins["actuarial_annual_premium"] == 3557.68
    assert pins["underwriting_fee_annual"] == 1245.19
    assert pins["underwriting_loading"] == 0.35
    split = resolve_premium_split(4802.87, {**stored, **pins})
    assert split["underwriting_fee_amount"] == 1245.19
    assert split["savings_amount"] == 980.08
    assert split["company_remainder"] == 0.0


def test_restore_refuses_a_discount_a_broken_seal_and_a_mismatched_monthly():
    table = {(0.5, 20): _quote(3557.68, 1960.15, 980.08, 294.02, 323.43, 0.5)}
    discounted = kernel_pin_restore_candidate(
        dict(_STORED), application={"premium_adjustment": -10}, pricer=_pricer(table),
    )
    assert (discounted["status"], discounted["reason"]) == ("refused", "discounted_premium")
    broken = kernel_pin_restore_candidate({**_STORED, "kernel_pin_intact": False}, pricer=_pricer(table))
    assert (broken["status"], broken["reason"]) == ("refused", "pin_seal_broken")
    monthly = kernel_pin_restore_candidate({**_STORED, "monthly_premium": 300.00}, pricer=_pricer(table))
    assert monthly["status"] == "refused"


def test_restore_leaves_a_pinned_policy_and_an_earlier_allocation_alone():
    pinned = kernel_pin_restore_candidate(_full_stack_policy(), pricer=_pricer({}))
    assert (pinned["status"], pinned["reason"]) == ("pinned", "already_pinned")
    earlier = kernel_pin_restore_candidate(
        {**_STORED, "risk_allocation": 75, "savings_allocation": 25}, pricer=_pricer({}),
    )
    assert (earlier["status"], earlier["reason"]) == ("pinned", "earlier_sealed_allocation")


def test_restore_reproduces_a_premium_the_live_kernel_priced():
    from services.pricing_shadow_service import price_application_with_kernel

    application = {"policy_type": "life", "coverage_amount": 500000, "age": 40, "risk_score": "medium"}
    quote = price_application_with_kernel({
        "type": "life", "coverage_amount": 500000, "age": 40, "risk_score": "medium",
        "savings_rate": 0.5, "term_years": 20,
    })
    stored = {
        "id": "POL-LIVE", "customer_id": "CUST-LIVE", "type": "life", "coverage_amount": 500000,
        "annual_premium": quote["annual"], "monthly_premium": quote["monthly"], "risk_score": "medium",
    }
    result = kernel_pin_restore_candidate(stored, application=application)
    assert result["status"] == "restorable", result
    for key in ("risk_premium_annual", "savings_premium_annual", "expense_loading_annual", "profit_margin_annual"):
        assert result["pins"][key] == quote[key]
    assert result["pins"]["savings_addon"] == "balanced"


def _position_books():
    """A pinned policy and one with no pin, each paid once, and one claim paid."""
    engine = get_accounting_engine()
    policies = {
        "POL-FS": _full_stack_policy(),
        "POL-NP": {"id": "POL-NP", "customer_id": "CUST-NP", "annual_premium": 2100.60, "monthly_premium": 175.05},
    }
    billing = {
        "BILL-FS": {"id": "BILL-FS", "customer_id": "CUST-FS", "policy_id": "POL-FS", "amount_paid": 296.47},
        "BILL-NP": {"id": "BILL-NP", "customer_id": "CUST-NP", "policy_id": "POL-NP", "amount_paid": 175.05},
    }
    transactions = [
        {"id": "TX-FS", "customer_id": "CUST-FS", "type": "bill_payment", "amount": 296.47,
         "metadata": {"bill_id": "BILL-FS", "policy_id": "POL-FS"}},
        {"id": "TX-NP", "customer_id": "CUST-NP", "type": "bill_payment", "amount": 175.05,
         "metadata": {"bill_id": "BILL-NP", "policy_id": "POL-NP"}},
        {"id": "TX-CLM", "customer_id": "CUST-FS", "type": "claim_payment_received", "amount": 120.00,
         "metadata": {"claim_id": "CLM-FS"}},
    ]
    for policy_id, customer_id, bill_id, tx_id, amount in (
        ("POL-FS", "CUST-FS", "BILL-FS", "TX-FS", 296.47),
        ("POL-NP", "CUST-NP", "BILL-NP", "TX-NP", 175.05),
    ):
        post_collected_premiums_to_accounting(
            customer_id=customer_id, policy_id=policy_id, policy=policies[policy_id], amount=amount,
            bills_paid=[bill_id], billing=billing, source_tx_id=tx_id, fallback_risk_pct=100, engine=engine,
        )
    return engine, policies, billing, transactions


def test_premium_cash_position_puts_every_dollar_on_one_balance_sheet_line():
    engine, policies, billing, transactions = _position_books()
    position = premium_cash_position(
        transactions=transactions, policies=policies, billing=billing, engine=engine,
    )
    assert position["premium_cash"] == 471.52 and position["claim_cash"] == 120.00
    assert position["net_cash"] == 351.52
    # Kernel risk 163.35, and the unpinned 175.05 the writer holds as risk, less the claim.
    assert position["risk_premium"] == 163.35
    assert position["premium_without_kernel_pin"] == 175.05
    assert position["claims_reserve"] == 218.40
    # Expense loading 24.50 is shared 12.76 / 2.55 / 9.19. Only the first is the company's.
    assert position["company_lines"] == {
        "underwriting_fee": 0.0, "phins_operations": 12.76, "profit": 26.95, "above_kernel_stack": 0.0,
    }
    assert position["company_income"] == 39.71
    assert position["customer_savings"] == 81.67
    assert position["carrier_share"] == 2.55
    assert position["reinsurance_ceding_reserve"] == 9.19
    assert position["own_funds"] == 258.11
    assert position["held_for_others"] == 93.41
    assert position["total"] == 351.52 and position["difference"] == 0.0
    assert position["ties_to_cash"] is True
    assert round(sum(line["amount"] for line in position["lines"]), 2) == position["net_cash"]
    # The reserve the accounting book carries is the same figure.
    assert position["accounting_book_claims_reserve"] == 218.40
    assert position["reserve_ties_to_book"] is True
    assert "operating_reserve" not in position


def test_premium_cash_position_restates_the_operating_counter_that_took_premiums_whole():
    engine, policies, billing, transactions = _position_books()
    sheet = {
        # A $500 deposit, then both premiums added whole by the revenue writer.
        "operating_reserve": 971.52,
        "transactions": [
            {"tx_id": "BS-1", "type": "revenue", "category": "premium_income", "amount": 296.47},
            {"tx_id": "BS-2", "type": "revenue", "category": "premium_income", "amount": 175.05},
            {"tx_id": "BS-3", "type": "revenue", "category": "late_fees", "amount": 15.00},
            {"tx_id": "BS-4", "type": "expense", "category": "claims_paid", "amount": 120.00},
        ],
    }
    before = copy.deepcopy(sheet)
    assert premium_revenue_rows_on_sheet(sheet) == Decimal("471.52")
    position = premium_cash_position(
        transactions=transactions, policies=policies, billing=billing, engine=engine, balance_sheet=sheet,
    )
    assert position["operating_reserve"] == {
        "stored": 971.52,
        "premium_taken_in_whole": 471.52,
        "company_part_of_premium": 39.71,
        "restated": 539.71,
    }
    # Reading the position leaves the stored sheet as it was.
    assert sheet == before


def test_premium_cash_position_names_a_reserve_the_book_has_not_re_split():
    engine, policies, billing, transactions = _booked_before_the_pin()
    position = premium_cash_position(
        transactions=transactions, policies=policies, billing=billing, engine=engine,
    )
    assert position["ties_to_cash"] is True
    assert position["claims_reserve"] == 163.35
    assert position["accounting_book_claims_reserve"] == 296.47
    assert position["reserve_difference"] == 133.12
    assert position["reserve_ties_to_book"] is False
    without_book = premium_cash_position(
        transactions=transactions, policies=policies, billing=billing, with_accounting_book=False,
    )
    assert "reserve_ties_to_book" not in without_book


def _wallet_credit(balance, transactions=None):
    return {
        "customer_id": "CUST-OLD",
        "balance": balance,
        "transactions": list(transactions or []),
    }


def _mix(wallet, investment, algo):
    return {
        "id": "UW-OLD",
        "customer_id": "CUST-OLD",
        "submitted_date": "2024-01-01T00:00:00",
        "health_wallet": {
            "written_distribution": {
                "wallet_pct": wallet,
                "investment_pct": investment,
                "algo_trading_pct": algo,
            }
        },
    }


def test_wallet_credit_uses_the_written_mix_on_the_original_application():
    from services.financial_unification_service import classify_legacy_wallet_credits

    wallet = _wallet_credit(200)
    before = copy.deepcopy(wallet)
    report = classify_legacy_wallet_credits(
        {"CUST-OLD": wallet},
        [_mix(40, 50, 10)],
        retired_allocations=[{"retired_75_25_savings": 9000, "retired_50_50_savings": 8000}],
        recommendations={"wallet_pct": 15, "investment_pct": 60, "algo_trading_pct": 25},
    )
    assert wallet == before
    assert report["writes"] is False
    assert report["retired_allocations_included"] is False
    assert report["wallets"] == 80.00
    assert report["investments"] == 100.00
    assert report["algo"] == 20.00
    assert report["allocated"] == 200.00
    assert report["unallocated"] == 0.00
    assert report["rows"][0]["basis"] == "application_distribution"
    assert report["rows"][0]["reason"] is None


def test_wallet_credit_without_a_written_mix_stays_unallocated():
    from services.financial_unification_service import classify_legacy_wallet_credits

    bare = {"id": "UW-BARE", "customer_id": "CUST-OLD", "submitted_date": "2024-01-01"}
    report = classify_legacy_wallet_credits(
        {"CUST-OLD": _wallet_credit(100)},
        [bare],
        recommendations={"wallet_pct": 30, "investment_pct": 65, "algo_pct": 5},
    )
    row = report["rows"][0]
    assert row["wallets"] == 0.00
    assert row["investments"] == 0.00
    assert row["algo"] == 0.00
    assert row["unallocated"] == 100.00
    assert "No written mix" in row["reason"]
    assert report["allocated"] == 0.00


def test_invalid_written_mix_is_not_replaced_with_30_65_5():
    from services.financial_unification_service import classify_legacy_wallet_credits

    report = classify_legacy_wallet_credits(
        {"CUST-OLD": _wallet_credit(100)},
        [_mix(40, 40, 40)],
    )
    row = report["rows"][0]
    assert row["unallocated"] == 100.00
    assert row["wallets"] == 0.00
    assert row["investments"] == 0.00
    assert "0–100" in row["reason"]

    out_of_range = classify_legacy_wallet_credits(
        {"CUST-OLD": _wallet_credit(100)},
        [_mix(120, -10, -10)],
    )
    assert out_of_range["rows"][0]["unallocated"] == 100.00
    assert out_of_range["rows"][0]["wallets"] == 0.00


def test_known_allocation_templates_stay_unallocated():
    from services.financial_unification_service import classify_legacy_wallet_credits

    for mix in ((30, 65, 5), (15, 60, 25), (75, 25, 0)):
        report = classify_legacy_wallet_credits(
            {"CUST-OLD": _wallet_credit(100)},
            [_mix(*mix)],
        )
        row = report["rows"][0]
        assert row["unallocated"] == 100.00, mix
        assert row["wallets"] == 0.00, mix
        assert row["investments"] == 0.00, mix
        assert "Left unallocated" in row["reason"]


def test_claim_posting_in_the_wallet_is_not_classified_as_aum():
    from services.financial_unification_service import classify_legacy_wallet_credits

    wallet = _wallet_credit(500, [
        {"type": "claim_payment", "amount": 300, "claim_id": "CLM-1"},
        {"type": "premium_savings", "amount": 200},
    ])
    before = copy.deepcopy(wallet)
    report = classify_legacy_wallet_credits({"CUST-OLD": wallet}, [_mix(40, 50, 10)])
    assert wallet == before
    assert report["credits"] == 200.00
    assert report["wallets"] == 80.00
    assert report["investments"] == 100.00
    assert report["algo"] == 20.00


def test_later_flat_preference_is_not_the_original_mix():
    from services.financial_unification_service import classify_legacy_wallet_credits

    report = classify_legacy_wallet_credits(
        {"CUST-OLD": _wallet_credit(100)},
        [{"id": "UW-BARE", "customer_id": "CUST-OLD", "submitted_date": "2024-01-01"}],
        {"CUST-OLD": {"wallet_pct": 40, "investment_pct": 50, "algo_pct": 10, "updated_at": "2026-01-01"}},
    )
    assert report["rows"][0]["unallocated"] == 100.00
    assert report["wallets"] == 0.00


def test_later_allocation_row_is_not_the_original_mix():
    from services.financial_unification_service import classify_legacy_wallet_credits

    report = classify_legacy_wallet_credits(
        {"CUST-OLD": _wallet_credit(100)},
        [{"id": "UW-BARE", "customer_id": "CUST-OLD", "submitted_date": "2024-01-01"}],
        {"CUST-OLD": {"distribution": {"wallet_pct": 20, "investment_pct": 70, "algo_trading_pct": 10}}},
    )
    row = report["rows"][0]
    assert row["unallocated"] == 100.00
    assert row["wallets"] == 0.00
    assert row["investments"] == 0.00
    assert row["basis"] == "unallocated"
    assert "No written mix" in row["reason"]


def test_earliest_application_is_the_one_that_writes_the_mix():
    from services.financial_unification_service import classify_legacy_wallet_credits

    later = _mix(10, 80, 10)
    later["id"] = "UW-LATER"
    later["submitted_date"] = "2025-06-01"
    original = _mix(40, 50, 10)
    report = classify_legacy_wallet_credits(
        {"CUST-OLD": _wallet_credit(100)},
        [later, original],
    )
    assert report["rows"][0]["application_id"] == "UW-OLD"
    assert report["wallets"] == 40.00
    assert report["investments"] == 50.00


def test_submitted_distribution_does_not_invent_a_missing_percent():
    from services.financial_unification_service import submitted_savings_distribution

    assert submitted_savings_distribution({}) is None
    assert submitted_savings_distribution({"distribution": {"wallet_pct": 40}}) is None
    stored = submitted_savings_distribution({
        "distribution": {"wallet_pct": 40, "investment_pct": 50, "algo_trading_pct": 10},
    })
    assert stored == {"wallet_pct": 40, "investment_pct": 50, "algo_trading_pct": 10}


def test_unified_report_aum_does_not_add_retired_allocation_rows():
    from services.cashflow_unified_report import unified_cashflow_report

    report = unified_cashflow_report(
        wallets={"CUST-OLD": _wallet_credit(100)},
        investments={"CUST-OLD": {"position": 50}},
        algo={"CUST-OLD": {"available": 10}},
        applications=[_mix(40, 50, 10)],
    )
    assert report["customer_funds"]["assets_under_management"] == 60.00
    assert report["customer_funds"]["health_wallet"] == 100.00
    assert report["accumulated_aum"]["allocated"] == 100.00
    assert report["accumulated_aum"]["wallets"] == 40.00
    assert report["accumulated_aum"]["investments"] == 50.00
    assert report["accumulated_aum"]["retired_allocations_included"] is False
    assert report["accumulated_aum"]["allocated"] != 100.00 + 9000
