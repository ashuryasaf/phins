"""Customer-ledger cash is the identity for premiums collected and claims paid.

The actuarial kernel pin (when present) decides the risk/savings split posted
to the accounting book. Historical billed amounts are never rewritten.
"""

from decimal import Decimal

from accounting_engine import reset_accounting_engine, get_accounting_engine, EntryType
from services.financial_unification_service import (
    CLAIM_CASH_TYPES,
    PREMIUM_AUDIT_TYPES,
    PREMIUM_CASH_TYPES,
    accounting_book_totals,
    economic_claims_reserve,
    kernel_components_from_policy,
    ledger_cash_total,
    pin_kernel_fields_on_policy,
    post_collected_premiums_to_accounting,
    post_premium_to_accounting_book,
    reconcile_financial_books,
    resolve_premium_split,
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


def test_split_falls_back_to_allocation_when_no_kernel_pin():
    split = resolve_premium_split(200.0, {"annual_premium": 2400.0}, fallback_risk_pct=75)
    assert split["risk_percentage"] == 75.0
    assert split["risk_amount"] == 150.0
    assert split["savings_amount"] == 50.0
    assert split["split_source"] == "allocation_prefs"


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
        },
        engine=engine,
    )
    assert report["is_consistent"] is True, report["discrepancies"]
    assert report["premiums"]["customer_ledger"]["total"] == 90.0
    assert report["claims"]["customer_ledger"]["total"] == 25.0
    assert report["authority"]["cash_identity"] == "customer_ledger"
    assert report["reserves"]["identity"] == "ledger_risk_cash_minus_claim_cash"
    assert report["reserves"]["economic_claims_reserve"] == 65.0
    assert report["reserves"]["seed_claims_reserve"] == 3475.0


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
