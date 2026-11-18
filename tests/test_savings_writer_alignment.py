"""Writer alignment for the testing-phase savings path.

Premium cash is split by the kernel pin. Only the savings component is
addressed to savings. A missing pin is the 50/50 default. That savings
figure is 30% health wallet, 65% investments, 5% algo, and the investment
piece is 60/30/10. ``balance`` stays unallocated cash.
"""

from services.data_integrity_service import DataIntegrityService
from services.financial_unification_service import resolve_premium_split
from services.nft_ledger import mint_token
from services.portfolio_tracker_service import PortfolioTrackerService
from services.process_pipeline_orchestrator import ProcessPipelineOrchestrator
import threading

from services.savings_pipeline_service import (
    AllocationStrategy,
    SavingsPipelineService,
    apply_investment_withdrawal,
    bounded_distribution,
    credit_settled_investment,
    investment_books,
    mark_unallocated_cash,
    settle_investment_to_algo,
)
from services.unified_balance_service import UnifiedBalanceService


def test_kernel_savings_excludes_expense_and_profit():
    policy = {
        "id": "POL-SPLIT",
        "annual_premium": 181.50,
        "risk_premium_annual": 100.0,
        "savings_premium_annual": 50.0,
        "expense_loading_annual": 15.0,
        "profit_margin_annual": 16.50,
        "pricing_source": "pricing_kernel",
        "integrity_hash": "pin-unchanged",
    }
    split = resolve_premium_split(181.50, policy, fallback_risk_pct=0)
    assert split["risk_amount"] == 100.0
    assert split["savings_amount"] == 50.0
    assert split["expense_amount"] == 15.0
    assert split["profit_amount"] == 16.50
    assert split["company_remainder"] == 0.0
    assert split["split_label"] == "kernel"
    assert split["integrity_hash"] == "pin-unchanged"
    assert policy["integrity_hash"] == "pin-unchanged"


def test_shrunk_annual_cannot_credit_more_than_the_cash_collected():
    """A rewritten annual premium must not mint savings above the payment."""
    policy = {
        "id": "POL-SHRUNK",
        "annual_premium": 12.0,
        "risk_premium_annual": 100.0,
        "savings_premium_annual": 50.0,
        "expense_loading_annual": 15.0,
        "profit_margin_annual": 16.50,
        "pricing_source": "pricing_kernel",
        "integrity_hash": "pin-unchanged",
    }
    split = resolve_premium_split(10.0, policy)
    credited = (
        split["risk_amount"]
        + split["savings_amount"]
        + split["expense_amount"]
        + split["profit_amount"]
    )
    assert abs(credited - 10.0) < 0.001
    assert split["savings_amount"] <= 10.0
    assert split["risk_percentage"] <= 100.0
    assert split["savings_percentage"] <= 100.0
    assert split["company_remainder"] == 0.0
    assert split["split_label"] == "kernel"
    assert split["integrity_hash"] == "pin-unchanged"
    assert policy["integrity_hash"] == "pin-unchanged"
    assert policy["savings_premium_annual"] == 50.0
    assert abs((split["savings_amount"] / split["risk_amount"]) - 0.5) < 0.02


def test_missing_pin_is_labeled_default_not_history():
    split = resolve_premium_split(
        200.0,
        {"id": "POL-OPEN", "annual_premium": 2400.0},
        fallback_risk_pct=100,
    )
    assert split["risk_amount"] == 100.0
    assert split["savings_amount"] == 100.0
    assert split["split_source"] == "default"
    assert split["split_label"] == "default"
    assert split["expense_amount"] == 0.0
    assert split["profit_amount"] == 0.0


def test_explicit_zero_savings_pin_is_not_the_default():
    split = resolve_premium_split(
        80.0,
        {
            "annual_premium": 1200.0,
            "risk_premium_annual": 1200.0,
            "savings_premium_annual": 0.0,
            "pricing_source": "pricing_kernel",
        },
    )
    assert split["savings_amount"] == 0.0
    assert split["risk_amount"] == 80.0
    assert split["split_label"] == "kernel"


def _pipeline(customer_id="CUST-PIPE"):
    wallets = {}
    investments = {}
    algo = {}

    class _Balance:
        def __init__(self):
            self.health_wallets = wallets
            self.investment_accounts = investments
            self.algo_trading_balances = algo

    service = SavingsPipelineService(
        unified_balance_service=_Balance(),
        health_wallets=wallets,
        investment_accounts=investments,
    )
    return service, wallets, investments, algo


def test_fresh_pipeline_deposit_uses_canonical_split_and_unallocated_cash():
    service, wallets, investments, algo = _pipeline("CUST-FRESH")
    result = service.deposit_to_pipeline(
        "CUST-FRESH", 100.0, source="premium_payment", auto_allocate=True
    )
    assert result["success"] is True
    account = service.accounts["CUST-FRESH"]
    assert account.allocation_strategy != AllocationStrategy.CUSTOM
    assert account.wallet_balance == 30.0
    assert account.investment_balance == 65.0
    assert account.algo_trading_balance == 5.0
    assert wallets["CUST-FRESH"]["balance"] == 30.0
    row = investments["CUST-FRESH"]
    assert row["balance_is_unallocated_cash"] is True
    assert row["balance"] == 0.0
    assert round(row["index_balance"], 2) == 39.0
    assert round(row["bonds_balance"], 2) == 19.5
    assert round(row["crypto_balance"], 2) == 6.5
    assert algo["CUST-FRESH"]["available"] == 5.0


def test_existing_custom_allocation_is_kept():
    service, wallets, investments, algo = _pipeline("CUST-CUSTOM")
    account = service.get_or_create_account("CUST-CUSTOM")
    account.allocation_strategy = AllocationStrategy.CUSTOM
    account.allocation_config.wallet_pct = 10.0
    account.allocation_config.investment_pct = 80.0
    account.allocation_config.algo_trading_pct = 10.0
    result = service.deposit_to_pipeline("CUST-CUSTOM", 100.0, auto_allocate=True)
    assert result["success"] is True
    assert account.wallet_balance == 10.0
    assert account.investment_balance == 80.0
    assert account.algo_trading_balance == 10.0
    assert wallets["CUST-CUSTOM"]["balance"] == 10.0
    assert investments["CUST-CUSTOM"]["balance"] == 0.0
    assert algo["CUST-CUSTOM"]["available"] == 10.0


def test_orchestrator_credits_thirty_percent_of_savings_and_appends_seals():
    wallets = {"CUST-ORCH": {"balance": 100.0, "transactions": []}}
    investments = {}
    ledger = {}
    nft = {}
    existing = mint_token(
        nft,
        owner_id="CUST-ORCH",
        transaction_type="record",
        transaction_id="TX-EXISTING",
        amount=1.0,
        description="already sealed",
        metadata={"note": "do not edit"},
    )
    sealed_hash = existing["verification_hash"]
    orchestrator = ProcessPipelineOrchestrator(
        policies={
            "POL-ORCH": {
                "id": "POL-ORCH",
                "customer_id": "CUST-ORCH",
                "status": "active",
                "monthly_premium": 200.0,
                "annual_premium": 2400.0,
                "health_wallet": {"allocation_percentage": 25},
            }
        },
        health_wallets=wallets,
        investment_accounts=investments,
        transaction_ledger=ledger,
        nft_ledger=nft,
    )
    generated = orchestrator.automate_billing_cycle("POL-ORCH")
    breakdown = generated["premium_breakdown"]
    assert breakdown["savings_amount"] == 100.0
    assert breakdown["split_label"] == "default"
    assert breakdown["health_wallet_amount"] == 30.0
    assert breakdown["investment_amount"] == 65.0
    assert breakdown["algo_amount"] == 5.0
    paid = orchestrator.process_billing_payment(generated["bill_id"], 200.0)
    assert paid["wallet_credit"]["amount"] == 30.0
    assert wallets["CUST-ORCH"]["balance"] == 130.0
    row = investments["CUST-ORCH"]
    assert row["balance"] == 0.0
    assert row["balance_is_unallocated_cash"] is True
    assert round(row["index_balance"] + row["bonds_balance"] + row["crypto_balance"], 2) == 65.0
    assert orchestrator.algo_balances["CUST-ORCH"]["available"] == 5.0
    assert nft[existing["token_id"]]["verification_hash"] == sealed_hash
    assert len(nft) > 1
    assert any(tx.get("type") == "premium_payment" for tx in ledger.values())


def test_auto_correct_does_not_add_a_gap_to_balance():
    customer_id = "CUST-GAP"
    investments = {
        customer_id: {
            "balance": 0.0,
            "index_balance": 40.0,
            "bonds_balance": 20.0,
            "crypto_balance": 10.0,
            "balance_is_unallocated_cash": True,
        }
    }
    wallets = {customer_id: {"balance": 30.0}}
    ledger = {
        "TX-DEP": {
            "id": "TX-DEP",
            "customer_id": customer_id,
            "type": "pipeline_deposit",
            "amount": 120.0,
        }
    }
    service = DataIntegrityService(
        health_wallets=wallets,
        investment_accounts=investments,
        transaction_ledger=ledger,
    )
    report = service.validate_customer_integrity(customer_id, auto_correct=True)
    assert report.discrepancy < -10
    assert investments[customer_id]["balance"] == 0.0
    assert report.corrections_applied
    assert report.corrections_applied[0]["action"] == "gap_left_in_place"
    historical = {
        "balance": 5000.0,
        "index_balance": 3000.0,
        "bonds_balance": 1500.0,
        "crypto_balance": 500.0,
    }
    assert service._investment_position(historical) == 5000.0


def test_checkout_payment_uses_kernel_savings_not_the_complement_of_risk():
    import web_portal.server as portal

    customer_id = "CUST-WRITER-ALIGN"
    policy_id = "POL-WRITER-ALIGN"
    portal.CUSTOMERS[customer_id] = {"id": customer_id, "name": "Writer Align"}
    portal.POLICIES[policy_id] = {
        "id": policy_id,
        "customer_id": customer_id,
        "status": "active",
        "annual_premium": 181.50,
        "monthly_premium": 181.50,
        "risk_premium_annual": 100.0,
        "savings_premium_annual": 50.0,
        "expense_loading_annual": 15.0,
        "profit_margin_annual": 16.50,
        "pricing_source": "pricing_kernel",
        "integrity_hash": "issued-pin",
    }
    portal.CUSTOMER_ALLOCATIONS.pop(customer_id, None)
    portal.HEALTH_WALLETS.pop(customer_id, None)
    portal.INVESTMENT_ACCOUNTS.pop(customer_id, None)
    existing = mint_token(
        portal.NFT_LEDGER,
        owner_id=customer_id,
        transaction_type="record",
        transaction_id="TX-WRITER-EXISTING",
        amount=1.0,
        description="existing seal",
    )
    sealed_hash = existing["verification_hash"]
    before_txs = set(portal.TRANSACTION_LEDGER.keys())
    before_nft = set(portal.NFT_LEDGER.keys())
    try:
        result = portal.process_customer_premium_payment(
            customer_id=customer_id,
            amount=181.50,
            policy_id=policy_id,
            allocate_to_investments=True,
            notify_customer=False,
        )
        assert result["success"] is True
        assert result["savings_allocated"] == 50.0
        assert result["risk_allocated"] == 100.0
        assert result["expense_amount"] == 15.0
        assert result["profit_amount"] == 16.50
        assert result["split_label"] == "kernel"
        assert result["allocation_source"] == "pipeline"
        assert portal.POLICIES[policy_id]["integrity_hash"] == "issued-pin"
        row = portal.INVESTMENT_ACCOUNTS[customer_id]
        assert row.get("balance_is_unallocated_cash") is True
        assert abs(float(row.get("balance") or 0)) < 0.02
        invested = (
            float(row.get("index_balance") or 0)
            + float(row.get("bonds_balance") or 0)
            + float(row.get("crypto_balance") or 0)
        )
        assert abs(invested - 32.50) < 0.05
        assert abs(float(portal.HEALTH_WALLETS[customer_id]["balance"]) - 15.0) < 0.05
        assert portal.NFT_LEDGER[existing["token_id"]]["verification_hash"] == sealed_hash
        new_txs = [
            tx for tx_id, tx in portal.TRANSACTION_LEDGER.items()
            if tx_id not in before_txs and tx.get("customer_id") == customer_id
        ]
        assert any(tx.get("type") == "premium_payment" for tx in new_txs)
    finally:
        portal.CUSTOMERS.pop(customer_id, None)
        portal.POLICIES.pop(policy_id, None)
        portal.HEALTH_WALLETS.pop(customer_id, None)
        portal.INVESTMENT_ACCOUNTS.pop(customer_id, None)
        portal.CUSTOMER_ALLOCATIONS.pop(customer_id, None)
        for token_id in list(portal.NFT_LEDGER.keys()):
            if token_id not in before_nft:
                portal.NFT_LEDGER.pop(token_id, None)
        for tx_id in list(portal.TRANSACTION_LEDGER.keys()):
            if tx_id not in before_txs:
                portal.TRANSACTION_LEDGER.pop(tx_id, None)
        pipeline = getattr(portal, "savings_pipeline_service", None)
        if pipeline is not None and hasattr(pipeline, "accounts"):
            pipeline.accounts.pop(customer_id, None)
            pipeline.transactions = [
                row for row in pipeline.transactions
                if getattr(row, "customer_id", None) != customer_id
            ]
        unified = getattr(portal, "unified_balance_service", None)
        if unified is not None and hasattr(unified, "algo_trading_balances"):
            unified.algo_trading_balances.pop(customer_id, None)


def test_existing_breakdown_stays_visible_after_the_next_credit():
    """An older row stores the total in balance. The next slice must show up."""
    service, wallets, investments, algo = _pipeline("CUST-OLD")
    investments["CUST-OLD"] = {
        "balance": 1000.0,
        "index_balance": 600.0,
        "bonds_balance": 300.0,
        "crypto_balance": 100.0,
    }
    result = service.deposit_to_pipeline("CUST-OLD", 100.0, auto_allocate=True)
    assert result["success"] is True
    row = investments["CUST-OLD"]
    assert row["balance_is_unallocated_cash"] is True
    invested = row["index_balance"] + row["bonds_balance"] + row["crypto_balance"]
    assert abs((row["balance"] + invested) - 1065.0) < 0.05
    assert abs(wallets["CUST-OLD"]["balance"] - 30.0) < 0.05
    assert abs(algo["CUST-OLD"]["available"] - 5.0) < 0.05
    reader = UnifiedBalanceService(
        health_wallets=wallets,
        investment_accounts=investments,
        transaction_ledger={},
        nft_ledger={},
        record_transaction_func=lambda **kwargs: {},
        generate_nft_token_func=lambda **kwargs: {},
    )
    reader.algo_trading_balances = algo
    view = reader.get_unified_balance("CUST-OLD")
    assert abs(view["balances"]["investment_account"]["total_balance"] - (row["balance"] + invested)) < 0.05


def test_unbounded_custom_split_cannot_mint_more_than_collected_cash():
    assert bounded_distribution(10000, 0, 0) is None
    assert bounded_distribution(40, 50, 10) == (40.0, 50.0, 10.0)
    service, wallets, investments, algo = _pipeline("CUST-WILD")
    account = service.get_or_create_account("CUST-WILD")
    account.allocation_strategy = AllocationStrategy.CUSTOM
    account.allocation_config.wallet_pct = 10000.0
    account.allocation_config.investment_pct = 10000.0
    account.allocation_config.algo_trading_pct = 10000.0
    result = service.deposit_to_pipeline("CUST-WILD", 100.0, auto_allocate=True)
    assert result["success"] is True
    assert account.wallet_balance == 30.0
    assert account.investment_balance == 65.0
    assert account.algo_trading_balance == 5.0
    assert wallets["CUST-WILD"]["balance"] == 30.0
    assert investments["CUST-WILD"]["balance"] == 0.0
    assert algo["CUST-WILD"]["available"] == 5.0


def test_side_by_side_subs_are_not_peeled_out_of_cash():
    account = {
        "balance": 0.0,
        "index_balance": 39.0,
        "bonds_balance": 19.5,
        "crypto_balance": 6.5,
    }
    mark_unallocated_cash(account)
    assert account["balance"] == 0.0
    assert account["balance_is_unallocated_cash"] is True
    assert account["index_balance"] == 39.0


def test_leftover_pipeline_cash_is_not_reduced_by_invested_subs():
    """Cash that already sits beside invested sub-balances stays put."""
    account = {
        "balance": 600.0,
        "index_balance": 156.0,
        "bonds_balance": 78.0,
        "crypto_balance": 26.0,
        "allocations": [{
            "type": "pipeline_allocation",
            "total_amount": 260.0,
        }],
    }
    mark_unallocated_cash(account)
    assert account["balance"] == 600.0
    assert account["balance_is_unallocated_cash"] is True
    assert account["index_balance"] == 156.0


def test_bare_leftover_cash_beside_holdings_is_not_peeled():
    account = {
        "balance": 600.0,
        "index_balance": 240.0,
        "bonds_balance": 120.0,
        "crypto_balance": 40.0,
    }
    mark_unallocated_cash(account)
    assert account["balance"] == 600.0
    assert account["balance_is_unallocated_cash"] is True
    assert account["index_balance"] == 240.0


def test_matching_cash_funded_by_an_allocation_stays_beside_holdings():
    account = {
        "balance": 65.0,
        "index_balance": 39.0,
        "bonds_balance": 19.5,
        "crypto_balance": 6.5,
        "allocations": [{
            "total_amount": 65.0,
            "index": 39.0,
            "bonds": 19.5,
            "crypto": 6.5,
        }],
    }
    mark_unallocated_cash(account)
    assert account["balance"] == 65.0
    assert account["balance_is_unallocated_cash"] is True
    assert account["index_balance"] == 39.0


def test_deposit_breakdown_inside_the_total_is_still_peeled():
    account = {
        "balance": 1200.0,
        "index_balance": 600.0,
        "bonds_balance": 300.0,
        "crypto_balance": 100.0,
        "deposits": [{
            "amount": 1000.0,
            "index_amount": 600.0,
            "bonds_amount": 300.0,
            "crypto_amount": 100.0,
        }],
    }
    mark_unallocated_cash(account)
    assert account["balance"] == 200.0
    assert account["balance_is_unallocated_cash"] is True
    assert account["index_balance"] == 600.0


def test_later_deposit_keeps_pipeline_cash_beside_invested_subs():
    service, wallets, investments, algo = _pipeline("CUST-BESIDE")
    investments["CUST-BESIDE"] = {
        "balance": 600.0,
        "index_balance": 156.0,
        "bonds_balance": 78.0,
        "crypto_balance": 26.0,
        "deposits": [],
        "allocations": [{
            "type": "pipeline_allocation",
            "total_amount": 260.0,
        }],
    }
    result = service.deposit_to_pipeline("CUST-BESIDE", 100.0, auto_allocate=True)
    assert result["success"] is True
    row = investments["CUST-BESIDE"]
    invested = row["index_balance"] + row["bonds_balance"] + row["crypto_balance"]
    assert row["balance_is_unallocated_cash"] is True
    assert abs(row["balance"] - 600.0) < 0.05
    assert abs(invested - 325.0) < 0.05
    assert abs(wallets["CUST-BESIDE"]["balance"] - 30.0) < 0.05
    assert abs(algo["CUST-BESIDE"]["available"] - 5.0) < 0.05


def test_allocate_marks_cash_so_the_new_slice_is_visible():
    service, wallets, investments, algo = _pipeline("CUST-ALLOC")
    account = service.get_or_create_account("CUST-ALLOC")
    account.cash_balance = 100.0
    investments["CUST-ALLOC"] = {
        "balance": 600.0,
        "index_balance": 156.0,
        "bonds_balance": 78.0,
        "crypto_balance": 26.0,
        "allocations": [{
            "type": "pipeline_allocation",
            "total_amount": 260.0,
        }],
    }
    result = service.allocate_cash_balance("CUST-ALLOC")
    assert result["success"] is True
    row = investments["CUST-ALLOC"]
    invested = row["index_balance"] + row["bonds_balance"] + row["crypto_balance"]
    assert row["balance_is_unallocated_cash"] is True
    assert abs(row["balance"] - 500.0) < 0.05
    assert abs(invested - 325.0) < 0.05
    reader = UnifiedBalanceService(
        health_wallets=wallets,
        investment_accounts=investments,
        transaction_ledger={},
        nft_ledger={},
        record_transaction_func=lambda **kwargs: {},
        generate_nft_token_func=lambda **kwargs: {},
    )
    reader.algo_trading_balances = algo
    view = reader.get_unified_balance("CUST-ALLOC")
    assert abs(view["balances"]["investment_account"]["total_balance"] - 825.0) < 0.05


def test_checkout_without_pipeline_service_still_credits_savings():
    import web_portal.server as portal

    customer_id = "CUST-NO-PIPE"
    policy_id = "POL-NO-PIPE"
    portal.CUSTOMERS[customer_id] = {"id": customer_id, "name": "No Pipe"}
    portal.POLICIES[policy_id] = {
        "id": policy_id,
        "customer_id": customer_id,
        "status": "active",
        "annual_premium": 200.0,
        "monthly_premium": 200.0,
    }
    portal.CUSTOMER_ALLOCATIONS.pop(customer_id, None)
    portal.HEALTH_WALLETS.pop(customer_id, None)
    portal.INVESTMENT_ACCOUNTS.pop(customer_id, None)
    saved_enabled = portal.savings_pipeline_enabled
    saved_service = portal.savings_pipeline_service
    portal.savings_pipeline_enabled = False
    portal.savings_pipeline_service = None
    try:
        result = portal.process_customer_premium_payment(
            customer_id=customer_id,
            amount=200.0,
            policy_id=policy_id,
            use_pipeline=True,
            notify_customer=False,
        )
        assert result["success"] is True
        assert result["allocation_source"] == "direct_investment"
        assert result["savings_allocated"] == 100.0
        assert abs(float(portal.HEALTH_WALLETS[customer_id]["balance"]) - 30.0) < 0.05
        row = portal.INVESTMENT_ACCOUNTS[customer_id]
        invested = (
            float(row["index_balance"]) + float(row["bonds_balance"]) + float(row["crypto_balance"])
        )
        assert abs(invested - 65.0) < 0.05
        assert abs(float(row["balance"])) < 0.02
    finally:
        portal.savings_pipeline_enabled = saved_enabled
        portal.savings_pipeline_service = saved_service
        portal.CUSTOMERS.pop(customer_id, None)
        portal.POLICIES.pop(policy_id, None)
        portal.HEALTH_WALLETS.pop(customer_id, None)
        portal.INVESTMENT_ACCOUNTS.pop(customer_id, None)


def test_orchestrator_algo_credit_lands_in_the_injected_store():
    shared = {}
    investments = {
        "CUST-OLD": {
            "balance": 1000.0,
            "index_balance": 600.0,
            "bonds_balance": 300.0,
            "crypto_balance": 100.0,
        }
    }
    wallets = {"CUST-OLD": {"balance": 0.0, "transactions": []}}
    orchestrator = ProcessPipelineOrchestrator(
        policies={
            "POL-OLD": {
                "id": "POL-OLD",
                "customer_id": "CUST-OLD",
                "status": "active",
                "monthly_premium": 200.0,
                "annual_premium": 2400.0,
            }
        },
        health_wallets=wallets,
        investment_accounts=investments,
        algo_balances=shared,
    )
    generated = orchestrator.automate_billing_cycle("POL-OLD")
    paid = orchestrator.process_billing_payment(generated["bill_id"], 200.0)
    assert paid["success"] is True
    assert shared["CUST-OLD"]["available"] == 5.0
    assert orchestrator.algo_balances is shared
    row = investments["CUST-OLD"]
    invested = row["index_balance"] + row["bonds_balance"] + row["crypto_balance"]
    assert row["balance_is_unallocated_cash"] is True
    assert abs((row["balance"] + invested) - 1065.0) < 0.05


def test_flagged_position_keeps_holdings_when_cash_is_zero():
    books = investment_books({
        "balance": 0.0,
        "index_balance": 390.0,
        "bonds_balance": 195.0,
        "crypto_balance": 65.0,
        "balance_is_unallocated_cash": True,
    })
    assert books["cash"] == 0.0
    assert books["invested"] == 650.0
    assert books["position"] == 650.0


def test_legacy_total_is_not_added_to_its_own_breakdown():
    books = investment_books({
        "balance": 1000.0,
        "index_balance": 600.0,
        "bonds_balance": 300.0,
        "crypto_balance": 100.0,
    })
    assert books["position"] == 1000.0
    assert books["cash"] == 0.0
    assert books["unallocated_cash"] is False


def test_withdrawal_takes_flagged_cash_before_holdings():
    account = {
        "balance": 100.0,
        "index_balance": 390.0,
        "bonds_balance": 195.0,
        "crypto_balance": 65.0,
        "balance_is_unallocated_cash": True,
    }
    moved = apply_investment_withdrawal(account, 150.0)
    assert moved["applied"] == 150.0
    assert moved["cash_taken"] == 100.0
    assert account["balance"] == 0.0
    remaining = account["index_balance"] + account["bonds_balance"] + account["crypto_balance"]
    assert abs(remaining - 600.0) < 0.05
    assert investment_books(account)["position"] == 600.0


def test_withdrawal_cannot_mint_past_the_position():
    account = {
        "balance": 0.0,
        "index_balance": 60.0,
        "bonds_balance": 30.0,
        "crypto_balance": 10.0,
        "balance_is_unallocated_cash": True,
    }
    moved = apply_investment_withdrawal(account, 500.0)
    assert moved["applied"] == 100.0
    assert account["balance"] == 0.0
    assert account["index_balance"] == 0.0
    assert account["bonds_balance"] == 0.0
    assert account["crypto_balance"] == 0.0


def test_algo_credit_cannot_exceed_the_position():
    """A credit already posted for more than the position is clawed back."""
    account = {
        "balance": 0.0,
        "index_balance": 60.0,
        "bonds_balance": 30.0,
        "crypto_balance": 10.0,
        "balance_is_unallocated_cash": True,
        "algo_trading_profits": 5.0,
    }
    algo = {"available": 500.0}
    settled = settle_investment_to_algo(account, 500.0, algo)
    assert settled["applied"] == 100.0
    assert settled["shortfall"] == 400.0
    assert algo["available"] == 100.0
    assert account["algo_trading_profits"] == 105.0
    assert investment_books(account)["position"] == 0.0


def _balance_service(accounts):
    recorded = []

    def _record(**kwargs):
        recorded.append(kwargs)
        return {"id": "TX-1", "nft_token_id": "NFT-1"}

    service = UnifiedBalanceService(
        health_wallets={},
        investment_accounts=accounts,
        transaction_ledger={},
        nft_ledger={},
        record_transaction_func=_record,
        generate_nft_token_func=lambda *args, **kwargs: {},
    )
    return service, recorded


def test_transfer_to_algo_refuses_more_than_the_position():
    accounts = {
        "CUST-1": {
            "balance": 0.0,
            "index_balance": 60.0,
            "bonds_balance": 30.0,
            "crypto_balance": 10.0,
            "balance_is_unallocated_cash": True,
        }
    }
    service, recorded = _balance_service(accounts)
    result = service.transfer_to_algo_trading("CUST-1", 500.0, "investment_account")
    assert result["success"] is False
    assert result["available_balance"] == 100.0
    assert accounts["CUST-1"]["index_balance"] == 60.0
    assert "CUST-1" not in service.algo_trading_balances
    assert recorded == []


def test_transfer_to_algo_keeps_holdings_when_cash_covers_it():
    accounts = {
        "CUST-1": {
            "balance": 200.0,
            "index_balance": 390.0,
            "bonds_balance": 195.0,
            "crypto_balance": 65.0,
            "balance_is_unallocated_cash": True,
        }
    }
    service, recorded = _balance_service(accounts)
    result = service.transfer_to_algo_trading("CUST-1", 100.0, "investment_account")
    assert result["success"] is True
    assert result["amount"] == 100.0
    assert result["new_algo_balance"] == 100.0
    assert result["new_source_balance"] == 750.0
    assert accounts["CUST-1"]["balance"] == 100.0
    assert accounts["CUST-1"]["index_balance"] == 390.0
    assert accounts["CUST-1"]["bonds_balance"] == 195.0
    assert accounts["CUST-1"]["crypto_balance"] == 65.0
    assert service.algo_trading_balances["CUST-1"]["available"] == 100.0
    assert recorded[0]["amount"] == 100.0
    assert investment_books(accounts["CUST-1"])["position"] == 750.0


def test_shared_tracker_deposit_keeps_the_canonical_row():
    """The tracker book is the customer row. Crediting algo must not replace it."""
    accounts = {
        "CUST-1": {
            "balance": 40.0,
            "index_balance": 60.0,
            "bonds_balance": 30.0,
            "crypto_balance": 10.0,
            "balance_is_unallocated_cash": True,
            "deposits": [{"id": "DEP-1", "amount": 100.0}],
            "algo_trading_profits": 0.0,
        }
    }
    recorded = []

    def _record(**kwargs):
        recorded.append(kwargs)
        return {"id": "TX-1", "nft_token_id": "NFT-1"}

    tracker = PortfolioTrackerService(
        investment_accounts=accounts,
        record_transaction_func=_record,
    )
    assert tracker.investment_accounts is accounts
    row = accounts["CUST-1"]
    settled = settle_investment_to_algo(row, 50.0)
    remaining = investment_books(row)["position"]
    result = tracker.deposit_to_algo(
        "CUST-1",
        settled["applied"],
        "investment",
        debit_source=False,
        source_balance_after=remaining,
    )
    assert result["success"] is True
    assert settled["applied"] == 50.0
    assert remaining == 90.0
    assert result["source_balance"] == 90.0
    assert recorded[0]["metadata"]["source_balance_after"] == 90.0
    assert row["deposits"][0]["id"] == "DEP-1"
    assert row["balance_is_unallocated_cash"] is True
    assert row["balance"] == 0.0
    assert investment_books(row)["position"] == 90.0
    assert tracker.algo_balances["CUST-1"]["available"] == 50.0
    assert row["algo_trading_profits"] == 50.0


def _flagged_row():
    return {
        "balance": 40.0,
        "index_balance": 60.0,
        "bonds_balance": 30.0,
        "crypto_balance": 10.0,
        "balance_is_unallocated_cash": True,
        "deposits": [{"id": "DEP-1", "amount": 100.0}],
        "algo_trading_profits": 7.0,
    }


def test_overlapping_transfers_credit_the_position_once():
    account = _flagged_row()
    credited = []
    ready = threading.Barrier(4)

    def credit(applied, remaining):
        credited.append((applied, remaining))
        return {"success": True}

    def worker():
        ready.wait(timeout=5)
        credit_settled_investment(account, 140.0, credit)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)
        assert not thread.is_alive()

    assert sum(item[0] for item in credited) == 140.0
    assert credited[0][1] == 0.0
    assert investment_books(account)["position"] == 0.0
    assert account["deposits"][0]["id"] == "DEP-1"
    assert account["balance_is_unallocated_cash"] is True


def test_failed_seal_restores_the_row_and_a_retry_moves_the_funds_once():
    account = _flagged_row()
    accounts = {"CUST-1": account}
    calls = {"raised": False}
    recorded = []

    def _record(**kwargs):
        if not calls["raised"]:
            calls["raised"] = True
            raise RuntimeError("seal failed")
        recorded.append(kwargs)
        return {"id": "TX-1", "nft_token_id": "NFT-1"}

    tracker = PortfolioTrackerService(
        investment_accounts=accounts,
        record_transaction_func=_record,
    )

    def credit(applied, remaining):
        return tracker.deposit_to_algo(
            "CUST-1",
            applied,
            "investment",
            debit_source=False,
            source_balance_after=remaining,
        )

    try:
        credit_settled_investment(account, 50.0, credit)
        raised = False
    except RuntimeError:
        raised = True
    assert raised is True
    assert investment_books(account)["position"] == 140.0
    assert account["balance"] == 40.0
    assert account["index_balance"] == 60.0
    assert account["algo_trading_profits"] == 7.0
    assert account["deposits"][0]["id"] == "DEP-1"
    assert tracker.algo_balances.get("CUST-1", {}).get("available", 0) == 0

    result = credit_settled_investment(account, 50.0, credit)
    assert result["success"] is True
    assert result["source_balance"] == 90.0
    assert recorded[0]["metadata"]["source_balance_after"] == 90.0
    assert tracker.algo_balances["CUST-1"]["available"] == 50.0
    assert investment_books(account)["position"] == 90.0
    assert account["algo_trading_profits"] == 57.0


def test_portfolio_transfer_cannot_duplicate_a_settled_withdrawal():
    account = _flagged_row()
    service, _recorded = _balance_service({"CUST-1": account})
    moved = []
    ready = threading.Barrier(2)

    def credit(applied, _remaining):
        moved.append(applied)
        return {"success": True}

    def settle():
        ready.wait(timeout=5)
        credit_settled_investment(account, 140.0, credit)

    def transfer():
        ready.wait(timeout=5)
        result = service.transfer_to_algo_trading("CUST-1", 140.0, "investment_account")
        if result.get("success"):
            moved.append(result["amount"])

    threads = [threading.Thread(target=settle), threading.Thread(target=transfer)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)
        assert not thread.is_alive()

    assert sum(moved) == 140.0
    assert investment_books(account)["position"] == 0.0
    assert account["deposits"][0]["id"] == "DEP-1"
    assert account["balance_is_unallocated_cash"] is True


def test_overlapping_wallet_deposits_credit_algo_once():
    wallet = {"balance": 100.0, "transactions": []}
    wallets = {"CUST-1": wallet}
    tracker = PortfolioTrackerService(
        health_wallets=wallets,
        record_transaction_func=lambda **_kwargs: {"id": "TX", "nft_token_id": "NFT"},
    )
    service, _recorded = _balance_service({})
    service.health_wallets = wallets
    results = []
    ready = threading.Barrier(2)

    def deposit():
        ready.wait(timeout=5)
        results.append(tracker.deposit_to_algo("CUST-1", 80.0, "health_wallet"))

    def transfer():
        ready.wait(timeout=5)
        results.append(service.transfer_to_algo_trading("CUST-1", 80.0, "health_wallet"))

    threads = [threading.Thread(target=deposit), threading.Thread(target=transfer)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)
        assert not thread.is_alive()

    assert sum(1 for row in results if row.get("success")) == 1
    assert wallet["balance"] == 20.0
    algo = float(tracker.algo_balances.get("CUST-1", {}).get("available", 0) or 0)
    algo += float(service.algo_trading_balances.get("CUST-1", {}).get("available", 0) or 0)
    assert algo == 80.0


def test_wallet_credit_during_the_seal_is_not_replaced():
    wallet = {"balance": 100.0, "transactions": []}
    service, _recorded = _balance_service({})
    service.health_wallets = {"CUST-1": wallet}

    def _record(**_kwargs):
        wallet["balance"] += 30.0
        return {"id": "TX-1", "nft_token_id": "NFT-1"}

    service.record_transaction = _record
    result = service.transfer_to_algo_trading("CUST-1", 40.0, "health_wallet")
    assert result["success"] is True
    assert wallet["balance"] == 90.0
    assert service.algo_trading_balances["CUST-1"]["available"] == 40.0


def test_algo_credit_during_the_seal_is_not_replaced():
    account = _flagged_row()
    service, _recorded = _balance_service({"CUST-1": account})
    service.algo_trading_balances["CUST-1"] = {
        "available": 0.0,
        "in_positions": 0.0,
        "total_pnl": 0.0,
        "transfers": [],
    }

    def _record(**_kwargs):
        service.algo_trading_balances["CUST-1"]["available"] += 25.0
        return {"id": "TX-1", "nft_token_id": "NFT-1"}

    service.record_transaction = _record
    result = service.transfer_to_algo_trading("CUST-1", 50.0, "investment_account")
    assert result["success"] is True
    assert service.algo_trading_balances["CUST-1"]["available"] == 75.0
    assert investment_books(account)["position"] == 90.0


def test_replaced_algo_bucket_still_receives_the_credit():
    account = _flagged_row()
    service, _recorded = _balance_service({"CUST-1": account})
    service.algo_trading_balances["CUST-1"] = {
        "available": 0.0,
        "in_positions": 0.0,
        "total_pnl": 0.0,
        "transfers": [],
    }

    def _record(**_kwargs):
        service.algo_trading_balances["CUST-1"] = {
            "available": 10.0,
            "in_positions": 0.0,
            "total_pnl": 0.0,
            "transfers": [],
        }
        return {"id": "TX-1", "nft_token_id": "NFT-1"}

    service.record_transaction = _record
    result = service.transfer_to_algo_trading("CUST-1", 50.0, "investment_account")
    assert result["success"] is True
    assert result["new_algo_balance"] == 60.0
    assert service.algo_trading_balances["CUST-1"]["available"] == 60.0
    assert investment_books(account)["position"] == 90.0


def test_refused_credit_puts_the_withdrawal_back():
    account = _flagged_row()

    def credit(applied, remaining):
        return {"success": False, "error": "declined"}

    result = credit_settled_investment(account, 50.0, credit)
    assert result["success"] is False
    assert result["error"] == "declined"
    assert result["available_balance"] == 140.0
    assert investment_books(account)["position"] == 140.0
    assert account["algo_trading_profits"] == 7.0
    assert account["deposits"][0]["id"] == "DEP-1"
