"""Marketplace commission is charged on the bid, and the premium table is read-only."""

from services.nft_ledger import mint_token
from decimal import Decimal

from services.premium_flow_reconciliation import (
    claim_postings_due,
    customer_cash_flow_streams,
    duplicate_claim_row_ids,
    monitoring_report,
    reconcile_customer,
    reconcile_customers,
    transferred_claim_amounts,
    worked_specimen,
)
from services.supply_chain_ecosystem_service import (
    SupplierStatus,
    SupplyChainEcosystemService,
)


def _customer_x_books():
    """$200 monthly risk, 100% savings add-on, uncut 15% loading, 10% profit."""
    policy = {
        "id": "POL-X",
        "customer_id": "CUST-X",
        "start_date": "2026-01-01",
        "risk_premium_annual": 2400.00,
        "savings_premium_annual": 2400.00,
        "expense_loading_annual": 360.00,
        "profit_margin_annual": 516.00,
        "annual_premium": 5676.00,
    }
    bills = [
        {
            "id": "BILL-X-01",
            "customer_id": "CUST-X",
            "payment_period": "2026-01",
            "amount_paid": 200.00,
            "premium_allocation": {"risk_amount": 100.00, "savings_amount": 100.00},
        },
        {
            "id": "BILL-X-02",
            "customer_id": "CUST-X",
            "payment_period": "2026-02",
            "amount_paid": 350.00,
            "premium_allocation": {"risk_amount": 262.50, "savings_amount": 87.50},
        },
        {
            "id": "BILL-X-03",
            "customer_id": "CUST-X",
            "payment_period": "2026-03",
            "amount_paid": 500.00,
            "premium_allocation": {"risk_amount": 250.00, "savings_amount": 250.00},
        },
    ]
    claims = [
        {"id": "CLM-X-1", "customer_id": "CUST-X", "status": "paid", "paid_amount": 800.00},
        {"id": "CLM-X-2", "customer_id": "CUST-X", "status": "paid", "paid_amount": 120.00},
        {"id": "CLM-X-3", "customer_id": "CUST-X", "status": "pending", "amount": 50.00},
    ]
    ledger = {}
    for month, amount, risk, savings, bill_id in (
        ("2026-01", 200.00, 100.00, 100.00, "BILL-X-01"),
        ("2026-02", 350.00, 262.50, 87.50, "BILL-X-02"),
        ("2026-03", 500.00, 250.00, 250.00, "BILL-X-03"),
    ):
        mint_token(
            ledger,
            owner_id="CUST-X",
            transaction_type="bill_payment",
            transaction_id=bill_id,
            amount=amount,
            description=f"Premium {month}",
            created_at=f"{month}-02T00:00:00+00:00",
            metadata={
                "payment_period": month,
                "premium_allocation": {"risk_amount": risk, "savings_amount": savings},
            },
        )
    mint_token(
        ledger,
        owner_id="CUST-X",
        transaction_type="claim_payment_received",
        transaction_id="CLM-X-2",
        amount=120.00,
        description="Claim CLM-X-2",
        created_at="2026-02-15T00:00:00+00:00",
        metadata={"claim_id": "CLM-X-2"},
    )
    seals = {token_id: token["verification_hash"] for token_id, token in ledger.items()}
    return policy, bills, claims, ledger, seals


def test_customer_x_monthly_table_does_not_cut_risk_or_write_seals():
    policy, bills, claims, ledger, seals = _customer_x_books()
    report = reconcile_customer(
        "CUST-X",
        policies=[policy],
        bills=bills,
        claims=claims,
        nft_ledger=ledger,
    )

    assert report["writes"] is False
    assert {token_id: token["verification_hash"] for token_id, token in ledger.items()} == seals
    assert report["withheld_seals"] == []
    assert [row["month"] for row in report["months"]] == ["2026-01", "2026-02", "2026-03"]

    january, february, march = report["months"]
    for row in report["months"]:
        assert row["kernel_risk"] == 200.00
        assert row["expense_loading"] == 30.00
        assert row["savings_addon"] == 200.00
        assert row["profit"] == 43.00
        assert row["correct_total"] == 473.00
        assert round(
            row["phins_operations"] + row["carrier_share"] + row["reinsurance_ceding_reserve"],
            2,
        ) == 30.00
        assert row["cash_source"] == "nft"

    assert january["collected"] == 200.00
    assert january["landed_risk"] == 200.00
    assert january["landed_savings"] == 0.00
    assert "underbooked" in january["flags"]
    assert "risk_cut" in january["flags"]
    assert "savings_carved_from_premium" in january["flags"]

    assert february["collected"] == 350.00
    assert february["landed_risk"] == 200.00
    assert february["landed_expense"] == 30.00
    assert february["landed_profit"] == 43.00
    assert february["landed_savings"] == 77.00
    assert "risk_overstated" in february["flags"]
    assert "savings_short" in february["flags"]
    assert "underbooked" in february["flags"]

    assert march["collected"] == 500.00
    assert march["overbooked_excess"] == 27.00
    assert march["landed_savings"] == 200.00
    assert round(march["savings_wallet"] + march["savings_investments"] + march["savings_algo"], 2) == 200.00
    assert "overbooked" in march["flags"]

    by_claim = {row["claim_id"]: row for row in report["claims"]}
    assert "CLM-X-3" not in by_claim
    assert by_claim["CLM-X-1"]["unposted_reserve_transfer"] == 800.00
    assert by_claim["CLM-X-1"]["posted"] is False
    assert by_claim["CLM-X-2"]["sealed_wallet_credit"] == 120.00
    assert by_claim["CLM-X-2"]["unposted_reserve_transfer"] == 0.00
    assert by_claim["CLM-X-2"]["posted"] is True

    balances = report["admin_balances_from_landed_savings"]
    assert balances["savings_landed"] == 277.00
    assert balances["sealed_claim_credits"] == 120.00
    assert balances["unposted_claim_transfers"] == 800.00
    assert round(
        balances["health_wallet_savings"] + balances["investments"] + balances["algo"],
        2,
    ) == 277.00

    many = reconcile_customers(["CUST-X"], policies=[policy], bills=bills, claims=claims, nft_ledger=ledger)
    assert many["customer_count"] == 1
    assert many["writes"] is False


def test_broken_premium_seal_is_withheld_and_not_repaired():
    policy, bills, claims, ledger, seals = _customer_x_books()
    token_id = next(iter(ledger))
    ledger[token_id]["amount"] = 9999.0
    report = reconcile_customer(
        "CUST-X",
        policies=[policy],
        bills=bills,
        claims=claims,
        nft_ledger=ledger,
    )
    assert report["withheld_seals"][0]["token_id"] == token_id
    assert report["withheld_seals"][0]["reason"] == "hash_mismatch"
    assert ledger[token_id]["amount"] == 9999.0
    assert ledger[token_id]["verification_hash"] == seals[token_id]
    january = report["months"][0]
    assert january["nft_premium_cash"] == 0.0
    assert january["cash_source"] == "bill"


def test_named_addon_is_priced_when_the_savings_pin_is_absent():
    policy = {
        "id": "POL-ADD",
        "customer_id": "CUST-ADD",
        "start_date": "2026-01-01",
        "annual_premium": 2400.00,
        "risk_premium_annual": 2400.00,
        "savings_addon": "growth",
    }
    bills = [{
        "id": "BILL-ADD",
        "customer_id": "CUST-ADD",
        "payment_period": "2026-01",
        "amount_paid": 400.00,
    }]
    row = reconcile_customer("CUST-ADD", policies=[policy], bills=bills)["months"][0]
    assert row["kernel_risk"] == 200.00
    assert row["savings_addon"] == 200.00
    assert row["savings_source"] == "growth"
    assert row["landed_risk"] == 200.00
    assert row["landed_savings"] == 200.00
    light = dict(policy, savings_addon="light")
    light_row = reconcile_customer("CUST-ADD", policies=[light], bills=bills)["months"][0]
    assert light_row["savings_addon"] == 50.00
    assert light_row["savings_source"] == "addon"


def test_earlier_allocation_and_underwriting_fee_are_reported_as_booked():
    policy = {
        "id": "POL-OLD",
        "customer_id": "CUST-OLD",
        "start_date": "2026-01-01",
        "annual_premium": 1620.00,
        "actuarial_annual_premium": 1200.00,
        "risk_allocation": 60.0,
        "savings_allocation": 40.0,
        "underwriting_loading": 0.35,
    }
    bills = [{
        "id": "BILL-OLD",
        "customer_id": "CUST-OLD",
        "payment_period": "2026-01",
        "amount_paid": 135.00,
        "premium_allocation": {"risk_amount": 60.0, "savings_amount": 40.0},
    }]
    report = reconcile_customer("CUST-OLD", policies=[policy], bills=bills)
    assert report["picture"]["savings_kind"] == "historical"
    assert report["picture"]["landed_savings"] == 40.00
    row = report["months"][0]
    assert row["savings_source"] == "historical"
    assert row["kernel_risk"] == 60.00
    assert row["underwriting_fee"] == 35.00
    assert row["savings_addon"] == 40.00
    assert row["landed_risk"] == 60.00
    assert row["landed_underwriting_fee"] == 35.00
    assert row["landed_savings"] == 40.00
    assert row["booked_risk"] == 60.00
    assert row["booked_savings"] == 40.00
    assert "savings_carved_from_premium" not in row["flags"]


def test_issued_quote_field_names_pin_risk_expense_and_profit():
    """Quotes store the kernel's annual amounts without an ``_annual`` suffix."""
    policy = {
        "id": "POL-Q",
        "customer_id": "CUST-Q",
        "start_date": "2026-01-01",
        "risk_premium": 2400.00,
        "savings_premium": 2400.00,
        "expense_loading": 360.00,
        "profit_margin": 516.00,
    }
    bills = [{
        "id": "BILL-Q",
        "customer_id": "CUST-Q",
        "payment_period": "2026-01",
        "amount_paid": 200.00,
        "premium_allocation": {"risk_amount": 100.00, "savings_amount": 100.00},
    }]
    report = reconcile_customer("CUST-Q", policies=[policy], bills=bills)
    row = report["months"][0]
    assert row["kernel_risk"] == 200.00
    assert row["expense_loading"] == 30.00
    assert row["profit"] == 43.00
    assert row["savings_addon"] == 200.00
    assert row["expense_pinned"] is True
    assert row["profit_pinned"] is True
    assert row["landed_risk"] == 200.00
    assert row["landed_savings"] == 0.00
    assert "risk_cut" in row["flags"]
    assert "underbooked" in row["flags"]

    preferred = {
        "customer_id": "CUST-Q",
        "start_date": "2026-04-01",
        "risk_premium_annual": 1200.00,
        "risk_premium": 2400.00,
        "expense_loading_annual": 120.00,
        "expense_loading": 360.00,
        "profit_margin_annual": 60.00,
        "profit_margin": 516.00,
        "savings_premium_annual": 0,
        "savings_premium": 2400.00,
    }
    pinned = reconcile_customer("CUST-Q", policies=[preferred])["months"][0]
    assert pinned["kernel_risk"] == 100.00
    assert pinned["expense_loading"] == 10.00
    assert pinned["profit"] == 5.00
    assert pinned["savings_addon"] == 0.00


def test_non_premium_tokens_do_not_stretch_the_month_range():
    policy, bills, claims, ledger, _seals = _customer_x_books()
    mint_token(
        ledger,
        owner_id="CUST-X",
        transaction_type="claim_payment_received",
        transaction_id="CLM-OLD",
        amount=10.00,
        description="Older claim",
        created_at="2025-06-01T00:00:00+00:00",
        metadata={"claim_id": "CLM-OLD", "period": "2025-06"},
    )
    mint_token(
        ledger,
        owner_id="CUST-X",
        transaction_type="wallet_purchase",
        transaction_id="PUR-1",
        amount=15.00,
        description="Purchase",
        created_at="2025-11-02T00:00:00+00:00",
    )
    report = reconcile_customer(
        "CUST-X",
        policies=[policy],
        bills=bills,
        claims=claims,
        nft_ledger=ledger,
    )
    assert report["first_month"] == "2026-01"
    assert [row["month"] for row in report["months"]] == ["2026-01", "2026-02", "2026-03"]


def test_closed_claim_without_a_seal_is_an_unposted_transfer():
    report = reconcile_customer(
        "CUST-C",
        claims=[
            {"id": "CLM-C", "customer_id": "CUST-C", "status": "closed", "paid_amount": 250.00},
            {"id": "CLM-A", "customer_id": "CUST-C", "status": "approved", "approved_amount": 80.00},
            {"id": "CLM-R", "customer_id": "CUST-C", "status": "rejected", "amount": 40.00},
        ],
    )
    by_claim = {row["claim_id"]: row for row in report["claims"]}
    assert set(by_claim) == {"CLM-C"}
    assert by_claim["CLM-C"]["unposted_reserve_transfer"] == 250.00
    assert by_claim["CLM-C"]["posted"] is False
    assert report["admin_balances_from_landed_savings"]["unposted_claim_transfers"] == 250.00


def test_invalid_month_does_not_hang_or_enter_the_range():
    report = reconcile_customer(
        "CUST-M",
        policies=[{
            "customer_id": "CUST-M",
            "start_date": "2026-11-01",
            "risk_premium_annual": 1200.00,
        }],
        bills=[
            {"customer_id": "CUST-M", "payment_period": "2026-14", "amount_paid": 10.00},
            {"customer_id": "CUST-M", "payment_period": "2026-99", "due_date": "2026-00-01", "amount_paid": 10.00},
            {"customer_id": "CUST-M", "payment_period": "2027-01", "amount_paid": 40.00},
        ],
    )
    assert [row["month"] for row in report["months"]] == ["2026-11", "2026-12", "2027-01"]
    assert report["months"][-1]["collected"] == 40.00


def test_supplier_bid_is_charged_commission_without_markup():
    service = SupplyChainEcosystemService(
        suppliers_store={
            "SUP-1": {
                "id": "SUP-1",
                "status": SupplierStatus.APPROVED.value,
                "supplier_type": "pharmacy",
                "created_date": "2026-01-01T00:00:00+00:00",
            }
        },
        offers_store={
            "OFF-1": {
                "id": "OFF-1",
                "supplier_id": "SUP-1",
                "name": "Medication",
                "price": 80.0,
                "active": True,
                "item_type": "product",
            }
        },
        health_wallets={"CUST-1": {"balance": 500.0, "transactions": []}},
    )
    result = service.create_order(
        "CUST-1",
        "SUP-1",
        "OFF-1",
        {
            "quantity": 2,
            "payment_method": "health_wallet",
            "expense_loading_pct": 0.50,
            "profit_margin_pct": 0.40,
            "discounted_rate_pct": 0.0,
        },
    )
    plan = result["pricing_plan"]
    order = result["order"]
    assert plan["markup_applied"] is False
    assert plan["final_customer_amount"] == 160.00
    assert plan["expense_loading_amount"] == 0.0
    assert plan["profit_margin_amount"] == 0.0
    assert plan["commission"] == 14.40
    assert plan["supplier_payout"] == 145.60
    assert order["total_amount"] == 160.00
    assert order["wallet_deduction"] == 160.00
    assert service.health_wallets["CUST-1"]["balance"] == 340.00


def test_monitoring_list_names_the_platform_customers_and_flags_a_carve():
    policy, bills, claims, ledger, _seals = _customer_x_books()
    policy = dict(policy, savings_addon="growth")
    report = monitoring_report(
        customers={
            "CUST-ASAF-001": {"name": "Asaf Assurance"},
            "CUST-X": {"name": "Specimen"},
        },
        policies=[policy],
        bills=bills,
        claims=claims,
        nft_ledger=ledger,
        wallets={
            "CUST-X": {"balance": 10.0},
            "CUST-EFRAT-001": {"balance": 0},
            "PHINS-CORPORATE": {"balance": 99},
            "SYSTEM": {"balance": 1},
        },
        investments={"CUST-X": {"position": 0}},
        algo={"CUST-X": {"available": 0}},
    )
    assert report["writes"] is False
    by_id = {row["customer_id"]: row for row in report["customers"]}
    for customer_id in ("CUST-ASAF-001", "CUST-EFRAT-001", "CUST-ASI-001", "CUST-SHOSH-001"):
        assert by_id[customer_id]["on_watch_list"] is True
    assert by_id["CUST-ASAF-001"]["name"] == "Asaf Assurance"
    assert "PHINS-CORPORATE" not in by_id
    assert "SYSTEM" not in by_id
    assert by_id["CUST-EFRAT-001"]["name"] == "Efrat PHINS"
    specimen = by_id["CUST-X"]
    assert specimen["priority"] == "attention"
    assert "savings_carved_from_premium" in specimen["flags"]
    assert "unposted_claim" in specimen["flags"]
    assert specimen["picture"]["risk_sent_to_savings"] == 0.0
    assert specimen["picture"]["savings_kind"] == "growth"
    assert specimen["claim_postings_due"] == [{
        "customer_id": "CUST-X",
        "claim_id": "CLM-X-1",
        "amount": 800.0,
        "stays_on_books": True,
        "destination": "health_wallet",
        "source": "claims_reserve",
    }]
    assert report["accumulated_funds"]["health_wallet"] == 10.0
    assert report["accumulated_funds"]["unposted_claim_transfers"] == 800.0
    due = claim_postings_due(worked_specimen())
    assert [row["claim_id"] for row in due] == ["CLM-X-1"]
    assert worked_specimen()["writes"] is False


def test_cashflow_errors_do_not_return_exception_text(monkeypatch, caplog):
    """A customer can open the premium picture. The failure stays in the log."""
    import json
    import os
    from urllib.error import HTTPError
    from urllib.request import Request, urlopen

    import web_portal.server as portal

    secret = "SECRET_MODULE /opt/phins/internal.py boom"
    caplog.set_level("ERROR")

    def boom(*_args, **_kwargs):
        raise RuntimeError(secret)

    monkeypatch.setattr(portal, "build_cashflow_monitoring", boom)
    monkeypatch.setattr(portal, "post_unposted_claim_transfers", boom)
    monkeypatch.setattr("services.premium_flow_reconciliation.reconcile_customer", boom)

    portal.SESSIONS["phins_cash-err-cust"] = {
        "username": "cust-err@test",
        "role": "customer",
        "customer_id": "CUST-ERR",
        "expires": "2099-01-01T00:00:00",
    }
    portal.SESSIONS["phins_cash-err-admin"] = {
        "username": "admin",
        "role": "admin",
        "expires": "2099-01-01T00:00:00",
    }
    init_set = getattr(portal, "_TEST_PORTS_INITIALIZED", None)
    if isinstance(init_set, set):
        init_set.add(int(os.environ.get("TEST_PORT", "8000")))
    base = os.environ.get("TEST_BASE_URL", "http://127.0.0.1:8000")

    def call(method, path, token):
        req = Request(
            base + path,
            data=b"{}" if method == "POST" else None,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            method=method,
        )
        try:
            with urlopen(req, timeout=15) as resp:
                return resp.status, resp.read().decode("utf-8")
        except HTTPError as exc:
            return exc.code, exc.read().decode("utf-8")

    try:
        routes = (
            ("GET", "/api/customer/premium-picture", "phins_cash-err-cust"),
            ("GET", "/api/admin/cashflow/monitoring", "phins_cash-err-admin"),
            ("GET", "/api/admin/cashflow/customers/CUST-ERR", "phins_cash-err-admin"),
            ("POST", "/api/admin/cashflow/post-claim-transfers", "phins_cash-err-admin"),
        )
        for method, path, token in routes:
            status, body = call(method, path, token)
            assert status == 500, path
            assert json.loads(body) == {"error": "internal_error"}, path
            assert secret not in body
        assert secret in caplog.text
    finally:
        portal.SESSIONS.pop("phins_cash-err-cust", None)
        portal.SESSIONS.pop("phins_cash-err-admin", None)


def test_paid_claim_covered_by_the_ledger_is_not_unposted_without_a_seal():
    policy, bills, claims, ledger, seals = _customer_x_books()
    report = reconcile_customer(
        "CUST-X",
        policies=[policy],
        bills=bills,
        claims=claims,
        nft_ledger=ledger,
        claim_transfers={"CLM-X-1": Decimal("800.00")},
    )
    assert {token_id: token["verification_hash"] for token_id, token in ledger.items()} == seals
    by_claim = {row["claim_id"]: row for row in report["claims"]}
    assert by_claim["CLM-X-1"]["unposted_reserve_transfer"] == 0.0
    assert by_claim["CLM-X-1"]["posted"] is True
    assert by_claim["CLM-X-1"]["sealed_wallet_credit"] == 0.0
    assert claim_postings_due(report) == []
    assert "savings_carved_from_premium" in report["picture"]["flags"]
    assert report["picture"]["savings_premiums_paid"] == report["picture"]["landed_savings"]


def test_three_balance_sheet_lines_count_as_one_claim():
    policy, bills, claims, ledger, _seals = _customer_x_books()
    sheet = {
        "transactions": [
            {"tx_id": "BS-1", "category": "claims_paid", "claim_id": "CLM-X-1", "amount": 800},
            {"tx_id": "BS-2", "category": "claims_paid", "claim_id": "CLM-X-1", "amount": 800},
            {"tx_id": "BS-3", "category": "claims_paid", "claim_id": "CLM-X-1", "amount": 800},
        ]
    }
    covered = transferred_claim_amounts(balance_sheet=sheet)
    assert covered["CLM-X-1"] == Decimal("2400.00")
    report = reconcile_customer(
        "CUST-X",
        policies=[policy],
        bills=bills,
        claims=claims,
        nft_ledger=ledger,
        claim_transfers=covered,
    )
    by_claim = {row["claim_id"]: row for row in report["claims"]}
    assert by_claim["CLM-X-1"]["unposted_reserve_transfer"] == 0.0
    assert duplicate_claim_row_ids(
        [
            {"id": "BS-1", "amount": 800, "timestamp": "2026-01-01"},
            {"id": "BS-2", "amount": 800, "timestamp": "2026-01-02"},
            {"id": "BS-3", "amount": 800, "timestamp": "2026-01-03"},
        ],
        800,
    ) == ["BS-2", "BS-3"]
    assert duplicate_claim_row_ids(
        [
            {"id": "P1", "amount": 200, "timestamp": "2026-01-01"},
            {"id": "P2", "amount": 300, "timestamp": "2026-01-02"},
            {"id": "P3", "amount": 300, "timestamp": "2026-01-03"},
        ],
        800,
    ) == []
    # One line already equals the paid amount, so the other lines are copies.
    assert duplicate_claim_row_ids(
        [
            {"id": "PART", "amount": 200, "timestamp": "2026-01-01"},
            {"id": "FULL", "amount": 800, "timestamp": "2026-01-02"},
            {"id": "COPY", "amount": 800, "timestamp": "2026-01-03"},
        ],
        800,
    ) == ["PART", "COPY"]


def test_billed_savings_is_kept_when_the_policy_pin_is_gone():
    policy = {
        "id": "POL-S",
        "customer_id": "CUST-S",
        "start_date": "2026-01-01",
        "annual_premium": 1200.00,
        "risk_premium_annual": 1200.00,
    }
    bills = [{
        "id": "BILL-S",
        "customer_id": "CUST-S",
        "payment_period": "2026-01",
        "amount_paid": 200.00,
        "premium_allocation": {"risk_amount_paid": 120.00, "savings_amount_paid": 80.00},
    }]
    report = reconcile_customer("CUST-S", policies=[policy], bills=bills)
    assert report["picture"]["landed_savings"] == 0.0
    assert report["picture"]["savings_premiums_paid"] == 80.0
    assert report["writes"] is False


def test_a_premium_with_no_savings_election_does_not_invent_savings():
    policy = {
        "id": "POL-R",
        "customer_id": "CUST-R",
        "start_date": "2026-01-01",
        "annual_premium": 1200.00,
        "risk_premium_annual": 1200.00,
    }
    bills = [{
        "id": "BILL-R",
        "customer_id": "CUST-R",
        "payment_period": "2026-01",
        "amount_paid": 100.00,
    }]
    report = reconcile_customer("CUST-R", policies=[policy], bills=bills)
    assert report["picture"]["landed_savings"] == 0.0
    assert report["picture"]["savings_premiums_paid"] == 0.0
    assert report["writes"] is False


def _full_stack_report(cash=296.47):
    policy = {
        "id": "POL-CF", "customer_id": "CUST-CF", "start_date": "2026-01-01",
        "annual_premium": 3557.68,
        "risk_premium_annual": 1960.15, "savings_premium_annual": 980.08,
        "expense_loading_annual": 294.02, "profit_margin_annual": 323.43,
    }
    bills = [{
        "id": "BILL-CF-01", "customer_id": "CUST-CF", "policy_id": "POL-CF",
        "payment_period": "2026-01", "status": "paid", "amount_paid": cash,
    }]
    return reconcile_customer("CUST-CF", policies=[policy], bills=bills, claims=[], nft_ledger={})


def test_customer_streams_add_up_to_the_premium_paid():
    before = _full_stack_report()
    flow = customer_cash_flow_streams(
        before, savings_on_accounts=81.67,
        balances={"health_wallet": 24.50, "investments": 53.09, "algo": 4.08},
    )
    assert flow["writes"] is False
    assert flow["collected"] == 296.47
    assert flow["ties"] is True and flow["streams_total"] == 296.47
    amounts = {row["key"]: row["amount"] for row in flow["streams"]}
    assert amounts == {"risk": 163.35, "expense_loading": 24.50, "profit": 26.95, "savings": 81.67}
    # Rounded one by one these would print 55.1 + 8.3 + 9.1 + 27.6 = 100.1.
    shares = {row["key"]: row["share_pct"] for row in flow["streams"]}
    assert shares == {"risk": 55.1, "expense_loading": 8.3, "profit": 9.1, "savings": 27.5}
    assert round(sum(shares.values()), 1) == 100.0
    assert flow["savings"]["charged"] == 81.67
    assert (
        flow["savings"]["health_wallet"] + flow["savings"]["investments"] + flow["savings"]["algo"]
    ) == 81.67
    assert flow["savings"]["on_accounts"] == 81.67
    assert flow["savings"]["not_yet_on_accounts"] == 0.0
    assert flow["balances"] == {"health_wallet": 24.50, "investments": 53.09, "algo": 4.08}


def test_customer_streams_show_savings_that_have_not_reached_the_accounts():
    flow = customer_cash_flow_streams(_full_stack_report(), savings_on_accounts=20.00)
    assert flow["savings"]["on_accounts"] == 20.00
    assert flow["savings"]["not_yet_on_accounts"] == 61.67
    assert flow["balances"] is None
    # Money already on the accounts above the charged savings is not counted twice.
    over = customer_cash_flow_streams(_full_stack_report(), savings_on_accounts=5000.00)
    assert over["savings"]["on_accounts"] == 81.67
    assert over["savings"]["not_yet_on_accounts"] == 0.0


def test_customer_streams_name_premium_on_a_policy_with_no_pin():
    policy = {"id": "POL-NP", "customer_id": "CUST-NP", "start_date": "2026-01-01", "annual_premium": 1200.00}
    bills = [{
        "id": "BILL-NP-01", "customer_id": "CUST-NP", "policy_id": "POL-NP",
        "payment_period": "2026-01", "status": "paid", "amount_paid": 100.00,
    }]
    report = reconcile_customer("CUST-NP", policies=[policy], bills=bills, claims=[], nft_ledger={})
    flow = customer_cash_flow_streams(report)
    amounts = {row["key"]: row["amount"] for row in flow["streams"]}
    assert amounts == {"risk": 0.0, "not_split": 100.00}
    assert flow["ties"] is True
    assert flow["savings"]["on_accounts"] is None


def test_unpinned_premium_stays_off_a_pinned_policy_in_the_same_month():
    """One pinned stack must not classify the other policy's cash as above the stack."""
    pinned = {
        "id": "POL-MIX-P", "customer_id": "CUST-MIX", "start_date": "2026-01-01",
        "risk_premium_annual": 2400.00, "savings_premium_annual": 2400.00,
        "expense_loading_annual": 360.00, "profit_margin_annual": 516.00,
        "annual_premium": 5676.00,
    }
    unpinned = {
        "id": "POL-MIX-U", "customer_id": "CUST-MIX", "start_date": "2026-01-01",
        "annual_premium": 1200.00,
    }
    bills = [
        {"id": "BILL-MIX-P", "customer_id": "CUST-MIX", "policy_id": "POL-MIX-P",
         "payment_period": "2026-01", "status": "paid", "amount_paid": 400.00},
        {"id": "BILL-MIX-U", "customer_id": "CUST-MIX", "policy_id": "POL-MIX-U",
         "payment_period": "2026-01", "status": "paid", "amount_paid": 100.00},
    ]
    row = reconcile_customer("CUST-MIX", policies=[pinned, unpinned], bills=bills)["months"][0]
    assert row["correct_total"] == 473.00
    assert row["collected"] == 500.00
    # The short pinned payment fills its own stack. The unpinned 100 is not
    # used to finish that stack, and it is not cash paid above it.
    assert row["landed_risk"] == 200.00
    assert row["landed_savings"] == 127.00
    assert row["no_kernel_pin_cash"] == 100.00
    assert row["overbooked_excess"] == 100.00
    flow = customer_cash_flow_streams(
        reconcile_customer("CUST-MIX", policies=[pinned, unpinned], bills=bills)
    )
    assert flow["ties"] is True and flow["collected"] == 500.00
