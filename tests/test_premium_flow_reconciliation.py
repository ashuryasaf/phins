"""Marketplace commission is charged on the bid, and the premium table is read-only."""

from services.nft_ledger import mint_token
from services.premium_flow_reconciliation import reconcile_customer, reconcile_customers
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


def test_issued_quote_field_names_and_closed_claims_stay_in_bounds():
    policy = {
        "id": "POL-SHORT",
        "customer_id": "CUST-SHORT",
        "start_date": "2026-13-01",
        "risk_premium": 2400.00,
        "savings_premium": 2400.00,
        "expense_loading": 360.00,
        "profit_margin": 516.00,
    }
    ledger = {}
    mint_token(
        ledger,
        owner_id="CUST-SHORT",
        transaction_type="wallet_deposit",
        transaction_id="DEP-1",
        amount=50.00,
        description="Earlier wallet deposit",
        created_at="2025-06-01T00:00:00+00:00",
    )
    mint_token(
        ledger,
        owner_id="CUST-SHORT",
        transaction_type="bill_payment",
        transaction_id="BILL-SHORT",
        amount=473.00,
        description="Premium",
        created_at="2026-02-02T00:00:00+00:00",
        metadata={"payment_period": "2026-02"},
    )
    report = reconcile_customer(
        "CUST-SHORT",
        policies=[policy],
        bills=[{
            "id": "BILL-OK",
            "customer_id": "CUST-SHORT",
            "payment_period": "2026-13",
            "amount_paid": 999.00,
        }, {
            "id": "BILL-FEB",
            "customer_id": "CUST-SHORT",
            "payment_period": "2026-02",
            "amount_paid": 473.00,
        }],
        claims=[
            {"id": "CLM-CLOSED", "customer_id": "CUST-SHORT", "status": "closed", "paid_amount": 40.00},
            {"id": "CLM-APPROVED", "customer_id": "CUST-SHORT", "status": "approved", "approved_amount": 70.00},
        ],
        nft_ledger=ledger,
    )
    assert report["months"] and report["months"][0]["month"] == "2026-02"
    assert all(row["month"] >= "2026-01" for row in report["months"])
    assert report["months"][0]["kernel_risk"] == 200.00
    assert report["months"][0]["expense_loading"] == 30.00
    assert report["months"][0]["profit"] == 43.00
    assert report["months"][0]["savings_addon"] == 200.00
    by_claim = {row["claim_id"]: row for row in report["claims"]}
    assert by_claim["CLM-CLOSED"]["unposted_reserve_transfer"] == 40.00
    assert "CLM-APPROVED" not in by_claim


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
