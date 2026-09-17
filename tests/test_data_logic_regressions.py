import inspect
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import services.trading_platform_service as trading_platform_module
from services.algo_trading_service import AlgoTradingService


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DYNAMIC_CUSTOMERS_FILE = PROJECT_ROOT / "database" / "dynamic_customers.json"
INVITATION_CODES_FILE = PROJECT_ROOT / "database" / "invitation_codes.json"


def test_algo_trading_live_history_preserves_crypto_pair_separator(monkeypatch):
    class FakeTradingPlatform:
        is_connected = True

        def __init__(self):
            self.crypto_calls = []

        def get_crypto_bars(self, symbol, timeframe, limit):
            self.crypto_calls.append(symbol)
            return {
                "bars": {
                    symbol: [
                        {
                            "t": "2026-04-23T00:00:00Z",
                            "o": 1.0,
                            "h": 1.0,
                            "l": 1.0,
                            "c": 1.0,
                            "v": 1.0,
                        }
                    ]
                }
            }

        def get_bars(self, symbol, timeframe, limit):
            return []

    fake_platform = FakeTradingPlatform()
    monkeypatch.setattr(
        trading_platform_module,
        "get_trading_platform",
        lambda: fake_platform,
    )

    service = AlgoTradingService.__new__(AlgoTradingService)
    service.portfolio_service = SimpleNamespace(MARKET_DATA={})
    service.price_history = {}

    service._try_load_live_history()

    assert "BTC/USD" in fake_platform.crypto_calls
    assert "ETH/USD" in fake_platform.crypto_calls
    assert "BTCUSD" not in fake_platform.crypto_calls
    assert "ETHUSD" not in fake_platform.crypto_calls


def test_run_server_seeds_sample_data_when_db_init_already_done():
    import web_portal.server as server

    source = inspect.getsource(server.run_server)
    guarded_branch = source.split(
        "elif USE_DATABASE and database_enabled and _db_init_done:",
        1,
    )[1].split(
        "# Seed customer accounts",
        1,
    )[0]

    assert "seed_sample_data()" in guarded_branch


def test_seed_invitation_usage_customer_ids_match_dynamic_customers():
    dynamic_customers = json.loads(DYNAMIC_CUSTOMERS_FILE.read_text())
    invitation_codes = json.loads(INVITATION_CODES_FILE.read_text())

    customer_ids_by_email = {
        customer["email"]: customer["customer_id"]
        for customer in dynamic_customers
        if customer.get("email") and customer.get("customer_id")
    }

    mismatches = []
    for code in invitation_codes.get("admin_codes", {}).values():
        for usage in code.get("used_by", []):
            email = usage.get("email")
            if not email or email not in customer_ids_by_email:
                continue
            if usage.get("customer_id") != customer_ids_by_email[email]:
                mismatches.append(email)

    assert not mismatches, f"Invitation usage records reference wrong customer IDs: {mismatches}"


def test_seed_dynamic_customers_rehashes_redacted_password_salt(tmp_path, monkeypatch):
    import database.seeds as seeds_module

    dynamic_customers_file = tmp_path / "dynamic_customers.json"
    dynamic_customers_file.write_text(
        json.dumps(
            [
                {
                    "username": "customer@example.com",
                    "email": "customer@example.com",
                    "password": "customer-password",
                    "password_hash": "stored-hash",
                    "password_salt": "REDACTED",
                }
            ]
        )
    )

    class StubUserRepo:
        def __init__(self):
            self.created = []

        def get_by_username(self, username):
            return None

        def create(self, **kwargs):
            self.created.append(kwargs)

    repo = StubUserRepo()
    monkeypatch.setattr(seeds_module, "DYNAMIC_CUSTOMERS_FILE", dynamic_customers_file)
    monkeypatch.setattr(
        seeds_module,
        "hash_password",
        lambda password: {"hash": "rehash", "salt": "fresh-salt"},
    )

    seeds_module.seed_dynamic_customers(None, repo)

    assert len(repo.created) == 1
    assert repo.created[0]["password_hash"] == "rehash"
    assert repo.created[0]["password_salt"] == "fresh-salt"


def test_seed_sample_data_wallet_claim_reconciliation_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setenv("USE_SQLITE", "1")
    monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "seed_wallet_reconciliation.db"))
    monkeypatch.setenv("USE_DATABASE", "true")

    from database import init_database, reset_connection
    from database.seeds import seed_sample_data
    import web_portal.server as portal

    expected_transaction_ids = []
    expected_total = 0.0

    reset_connection()
    init_database(drop_existing=True)
    portal.HEALTH_WALLETS.clear()

    seed_sample_data()

    wallet = portal.HEALTH_WALLETS["CUST-ASAF-001"]
    claim_transaction_ids = [tx["id"] for tx in wallet["transactions"]]
    assert wallet["balance"] == pytest.approx(expected_total)
    assert claim_transaction_ids == expected_transaction_ids

    seed_sample_data()

    wallet = portal.HEALTH_WALLETS["CUST-ASAF-001"]
    claim_transaction_ids = [tx["id"] for tx in wallet["transactions"]]
    assert wallet["balance"] == pytest.approx(expected_total)
    assert claim_transaction_ids == expected_transaction_ids


def test_seed_policies_are_kernel_priced_phins_unified(tmp_path, monkeypatch):
    monkeypatch.setenv("USE_SQLITE", "1")
    monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "seed_kernel_only.db"))
    monkeypatch.setenv("USE_DATABASE", "true")

    from database import init_database, reset_connection
    from database.seeds import (
        FALSE_DEMO_POLICY_IDS,
        KERNEL_SEED_POLICY_TYPES,
        seed_sample_data,
    )
    from services.pricing_shadow_service import POLICY_TYPE_TO_PRODUCT
    import web_portal.server as portal

    reset_connection()
    init_database(drop_existing=True)
    portal.POLICIES.clear()
    portal.CLAIMS.clear()
    portal.BILLING.clear()
    portal.HEALTH_WALLETS.clear()
    portal.TRANSACTION_LEDGER.clear()

    seed_sample_data()

    for policy_id in FALSE_DEMO_POLICY_IDS:
        assert policy_id not in portal.POLICIES, policy_id

    active = [
        p for p in portal.POLICIES.values()
        if isinstance(p, dict) and str(p.get("status") or "").lower() not in (
            "cancelled", "canceled", "void", "retired"
        )
    ]
    for policy in active:
        ptype = str(policy.get("type") or "").strip().lower()
        assert ptype in KERNEL_SEED_POLICY_TYPES, policy.get("id")
        assert ptype in POLICY_TYPE_TO_PRODUCT, policy.get("id")
        assert policy.get("id") not in FALSE_DEMO_POLICY_IDS

    assert "CLM-ASAF-001" not in portal.CLAIMS
    assert "CLM-ASAF-002" not in portal.CLAIMS
    assert "CLM-ASAF-003" not in portal.CLAIMS
    assert "CLM-ASAF-004" not in portal.CLAIMS
    assert "CLM-ASAF-005" not in portal.CLAIMS
    cash_types = {
        str(tx.get("type") or "")
        for tx in portal.TRANSACTION_LEDGER.values()
        if isinstance(tx, dict)
        and str((tx.get("metadata") or {}).get("policy_id") or tx.get("policy_id") or "")
        in FALSE_DEMO_POLICY_IDS
    }
    assert not cash_types


def test_seed_removes_false_demo_efrat_policy_and_keeps_wallets():
    """Restart seed removes the false Efrat policy but keeps persisted wallets."""
    import web_portal.server as portal

    portal.CUSTOMERS['CUST-EFRAT-001'] = {
        'id': 'CUST-EFRAT-001',
        'name': 'Efrat PHINS',
        'email': 'efrat@phins.ai',
        'status': 'active',
        'date_of_birth': '1990-06-15',
    }
    portal.POLICIES['POL-EFRAT-UNIFIED-001'] = {
        'id': 'POL-EFRAT-UNIFIED-001',
        'customer_id': 'CUST-EFRAT-001',
        'type': 'life',
        'coverage_amount': 500000.0,
        'annual_premium': 1552.50,
        'monthly_premium': 129.38,
        'status': 'active',
        'risk_score': 'low',
    }
    portal.BILLING['BILL-EFRAT-UNIFIED-001'] = {
        'id': 'BILL-EFRAT-UNIFIED-001',
        'policy_id': 'POL-EFRAT-UNIFIED-001',
        'customer_id': 'CUST-EFRAT-001',
        'amount': 129.38,
        'amount_paid': 129.38,
        'status': 'paid',
    }
    portal.HEALTH_WALLETS['CUST-EFRAT-001'] = {
        'customer_id': 'CUST-EFRAT-001',
        'balance': 321.45,
        'monthly_deposit': 25.0,
        'transactions': [{'id': 'TX-LEGACY-WALLET'}],
    }
    portal.INVESTMENT_ACCOUNTS['CUST-EFRAT-001'] = {
        'customer_id': 'CUST-EFRAT-001',
        'balance': 654.32,
        'deposits': [{'id': 'DEP-LEGACY-INVESTMENT'}],
    }

    portal._seed_startup_demo_fixtures()

    policy = portal.POLICIES.get('POL-EFRAT-UNIFIED-001')
    assert policy is None
    assert 'BILL-EFRAT-UNIFIED-001' not in portal.BILLING
    wallet = portal.HEALTH_WALLETS['CUST-EFRAT-001']
    assert float(wallet['balance']) == pytest.approx(321.45)
    assert wallet['transactions'] == [{'id': 'TX-LEGACY-WALLET'}]
    invest = portal.INVESTMENT_ACCOUNTS['CUST-EFRAT-001']
    assert float(invest['balance']) == pytest.approx(654.32)


def test_false_demo_wallet_purge_does_not_go_negative():
    """Spent false claim cash must not drive the kept wallet negative."""
    from database.seeds import _purge_false_demo_seed
    import web_portal.server as portal

    portal.CLAIMS['CLM-ASAF-001'] = {
        'id': 'CLM-ASAF-001',
        'policy_id': 'POL-ASAF-LIFE-001',
        'customer_id': 'CUST-ASAF-001',
        'status': 'Paid',
        'claimed_amount': 5000.0,
        'approved_amount': 5000.0,
    }
    portal.HEALTH_WALLETS['CUST-ASAF-001'] = {
        'customer_id': 'CUST-ASAF-001',
        'balance': 0.0,
        'transactions': [
            {
                'id': 'CLAIM-PAY-SEED-CLM-ASAF-001',
                'type': 'deposit',
                'amount': 5000.0,
                'claim_id': 'CLM-ASAF-001',
            },
            {
                'id': 'TX-WALLET-SPEND-REAL',
                'type': 'purchase',
                'amount': 5000.0,
            },
        ],
    }

    _purge_false_demo_seed(sync_memory=True)

    wallet = portal.HEALTH_WALLETS['CUST-ASAF-001']
    assert float(wallet['balance']) >= 0
    assert float(wallet['balance']) == pytest.approx(0.0)
    assert [tx['id'] for tx in wallet['transactions']] == ['TX-WALLET-SPEND-REAL']
    assert 'CLM-ASAF-001' not in portal.CLAIMS


def test_seed_mirrors_phins_customers_without_policies(tmp_path, monkeypatch):
    """Efrat/Asi/Shosh accounts must land in CUSTOMERS even with no policy."""
    monkeypatch.setenv("USE_SQLITE", "1")
    monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "seed_phins_customers.db"))
    monkeypatch.setenv("USE_DATABASE", "false")

    from database import init_database, reset_connection
    from database.seeds import seed_sample_data
    import web_portal.server as portal

    reset_connection()
    init_database(drop_existing=True)
    portal.CUSTOMERS.clear()
    portal.POLICIES.clear()

    seed_sample_data()

    for customer_id, email in (
        ('CUST-EFRAT-001', 'efrat@phins.ai'),
        ('CUST-ASI-001', 'asi@phins.ai'),
        ('CUST-SHOSH-001', 'shosh@phins.ai'),
    ):
        row = portal.CUSTOMERS.get(customer_id)
        assert row is not None, customer_id
        assert row.get('email') == email

    assert 'POL-EFRAT-UNIFIED-001' not in portal.POLICIES
    assert 'POL-ASI-UNIFIED-001' not in portal.POLICIES
    assert 'POL-SHOSH-UNIFIED-001' not in portal.POLICIES
