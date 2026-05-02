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

    expected_transaction_ids = [
        "CLAIM-PAY-SEED-CLM-ASAF-001",
        "CLAIM-PAY-SEED-CLM-ASAF-002",
        "CLAIM-PAY-SEED-CLM-ASAF-003",
    ]
    expected_total = 19050.0

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
