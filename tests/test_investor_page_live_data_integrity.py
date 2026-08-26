"""Live-data integrity for the PR #546 investor pages.

Empty books must not invent Excellent/100 health, $0.15 AI transfers,
or seeded MARKET_DATA / advanced_market_data quotes.
"""

from services.savings_pipeline_service import SavingsPipelineService


def test_empty_pipeline_health_is_no_activity():
    service = SavingsPipelineService()
    account = service.get_or_create_account("CUST-EMPTY-BOOK-001")
    health = service._calculate_pipeline_health(account)
    assert health["status"] == "no_activity"
    assert health["score"] == 0
    assert "No live pipeline balances" in health["issues"]


def test_empty_pipeline_ai_does_not_invent_transfers():
    service = SavingsPipelineService()
    rec = service.get_ai_recommendation("CUST-EMPTY-BOOK-002")
    assert rec["recommendations"] == []
    assert rec["suggested_actions"] == []
    assert rec["ai_confidence"] == 0
    assert rec["current_allocation"] == {"wallet": 0, "investment": 0, "algo_trading": 0}
    assert "Increase emergency fund" not in str(rec)
    assert rec["optimal_allocation"]["wallet"] == 15
    assert rec["optimal_allocation"]["investment"] == 60
    assert rec["optimal_allocation"]["algo_trading"] == 25


def test_funded_pipeline_health_is_not_no_activity():
    service = SavingsPipelineService()
    customer_id = "CUST-FUNDED-BOOK-001"
    service.deposit_to_pipeline(customer_id, 1000)
    service.allocate_cash_balance(customer_id)
    account = service.get_or_create_account(customer_id)
    health = service._calculate_pipeline_health(account)
    assert health["status"] != "no_activity"
    assert health["score"] > 0
    rec = service.get_ai_recommendation(customer_id)
    assert rec["ai_confidence"] >= 0
    dest_total = (
        account.wallet_balance + account.investment_balance + account.algo_trading_balance
    )
    assert dest_total > 0


def test_market_overview_does_not_emit_seed_signals():
    from services.algo_trading_service import AlgoTradingService
    from services.investment_portfolio_service import InvestmentPortfolioService

    algo = AlgoTradingService(InvestmentPortfolioService())
    algo.signals.clear()
    overview = algo.get_market_overview()
    assert overview.get("assets") == []
    assert algo.get_all_signals() == []


def test_live_quote_helpers_drop_seed_cache():
    from web_portal.server import (
        build_live_market_payload,
        filter_overview_assets_to_live,
        price_history_is_live,
    )

    assert build_live_market_payload({}) == {}
    assert build_live_market_payload({"prices": {"SPY": 478.50}, "quotes": {}}) == {
        "SPY": {
            "price": 478.50,
            "name": "SPY",
            "class": "",
            "change_24h": 0.0,
            "is_live": True,
            "source": "live",
        }
    }
    seed_assets = [
        {"symbol": "SPY", "price": 478.50},
        {"symbol": "AAPL", "price": 193.50},
    ]
    assert filter_overview_assets_to_live(seed_assets, {}) == []
    assert filter_overview_assets_to_live(seed_assets, {"QQQ": 405.20}) == []
    live_only = filter_overview_assets_to_live(seed_assets, {"SPY": 512.10})
    assert [row["symbol"] for row in live_only] == ["SPY"]

    seed_history = [{"price": 478.50, "source": "portfolio_seed"}] * 50
    assert price_history_is_live(seed_history) is False
    live_history = [{"price": 512.10, "source": "alpaca"}] * 20
    assert price_history_is_live(live_history) is True


def _http_get(path: str) -> dict:
    import json
    import os
    import urllib.request

    base = os.environ.get("TEST_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
    with urllib.request.urlopen(base + path, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def test_http_empty_pipeline_analytics_is_honest():
    body = _http_get("/api/pipeline/analytics?customer_id=CUST-HTTP-EMPTY-001")
    health = body.get("pipeline_health") or {}
    assert health.get("status") == "no_activity"
    assert health.get("score") == 0
    assert body.get("balances", {}).get("total_balance", 0) == 0


def test_http_empty_pipeline_ai_is_honest():
    body = _http_get("/api/pipeline/ai-recommendation?customer_id=CUST-HTTP-EMPTY-002")
    assert body.get("recommendations") == []
    assert body.get("ai_confidence", 0) == 0
    assert "Increase emergency fund" not in str(body)


def test_http_savings_market_data_is_not_seed_book():
    body = _http_get("/api/savings/market-data")
    data = body.get("market_data") or {}
    assert body.get("source") in ("live", "none")
    if body.get("source") == "none":
        assert data == {}
    seed_hits = 0
    seed_book = {"SPY": 478.50, "QQQ": 405.20, "GLD": 188.50, "^SPX": 4785.00}
    for symbol, seed_price in seed_book.items():
        price = float((data.get(symbol) or {}).get("price") or 0)
        if price and abs(price - seed_price) < 0.001:
            seed_hits += 1
    assert seed_hits < 3, "seeded MARKET_DATA book leaked onto investor market-data"


def test_http_extended_market_is_not_seed_book():
    body = _http_get("/api/algo/market/extended")
    assert body.get("data_source") in ("live", "none")
    if body.get("data_source") == "none":
        assert body.get("assets") == []
    assets = {row.get("symbol"): row.get("price") for row in body.get("assets") or []}
    seed_hits = 0
    if assets.get("AAPL") is not None and abs(float(assets["AAPL"]) - 193.50) < 0.05:
        seed_hits += 1
    if assets.get("MSFT") is not None and abs(float(assets["MSFT"]) - 378.20) < 0.05:
        seed_hits += 1
    if assets.get("BTC") is not None and abs(float(assets["BTC"]) - 43250.00) < 1:
        seed_hits += 1
    assert seed_hits < 2, "advanced_market_data seed book leaked onto /api/algo/market/extended"


def test_http_algo_signals_omit_seed_book():
    body = _http_get("/api/algo/signals?limit=50")
    assert "signals" in body
    seed_prices = {405.20, 92.30, 478.50, 72.50, 78.90, 188.50, 193.50}
    hits = 0
    for signal in body.get("signals") or []:
        price = float(signal.get("current_price") or signal.get("price") or 0)
        if any(abs(price - seed) < 0.001 for seed in seed_prices):
            hits += 1
    assert hits < 3, "seed-priced momentum signals leaked onto /api/algo/signals"
