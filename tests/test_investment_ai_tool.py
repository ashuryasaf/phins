"""
Test suite for the Investment AI Tool service and API endpoints.

Tests cover:
- All 10 AI modules (service-layer unit tests)
- Access key authentication
- API endpoint integration (GET and POST)
- Error handling and edge cases
"""

import importlib
import json
import os
import sys
from urllib.request import urlopen, Request
from urllib.error import HTTPError

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.investment_ai_tool_service import (
    analyze_market_trends,
    analyze_portfolio_diversification,
    run_stock_screener,
    design_trading_strategy,
    run_technical_analysis,
    analyze_earnings_report,
    compare_growth_vs_dividend,
    get_algo_trading_bot_guide,
    design_risk_management_system,
    backtest_strategy,
    dispatch_investment_ai,
    get_modules_catalog,
    validate_investment_ai_access,
    get_access_key_display,
    STOCK_DATABASE,
    SECTOR_DATA,
    AVAILABLE_MODULES,
)

BASE_URL = os.environ.get("TEST_BASE_URL", "http://localhost:8000")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get(path, headers=None):
    req = Request(BASE_URL + path, headers=headers or {})
    with urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8")), resp.status


def _post(path, payload, headers=None):
    data = json.dumps(payload).encode("utf-8")
    h = {"Content-Type": "application/json"}
    h.update(headers or {})
    req = Request(BASE_URL + path, data=data, headers=h)
    with urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8")), resp.status


def _get_error(path, headers=None):
    try:
        req = Request(BASE_URL + path, headers=headers or {})
        with urlopen(req) as resp:
            return json.loads(resp.read().decode("utf-8")), resp.status
    except HTTPError as e:
        return json.loads(e.read().decode("utf-8")), e.code


def _post_error(path, payload, headers=None):
    try:
        data = json.dumps(payload).encode("utf-8")
        h = {"Content-Type": "application/json"}
        h.update(headers or {})
        req = Request(BASE_URL + path, data=data, headers=h)
        with urlopen(req) as resp:
            return json.loads(resp.read().decode("utf-8")), resp.status
    except HTTPError as e:
        return json.loads(e.read().decode("utf-8")), e.code


# ---------------------------------------------------------------------------
# Service-layer unit tests
# ---------------------------------------------------------------------------

class TestMarketResearch:
    def test_overview(self):
        result = analyze_market_trends()
        assert result["module"] == "market_research_trend_analysis"
        assert "market_overview" in result
        assert "bullish_sectors" in result["market_overview"]
        assert "top_opportunities" in result

    def test_by_sector(self):
        result = analyze_market_trends(sector="technology")
        assert "sector_analysis" in result
        sa = result["sector_analysis"]
        assert sa["sector"] == "Technology"
        assert sa["trend"] in ("bullish", "bearish", "neutral")
        assert "emerging_patterns" in result

    def test_by_stock(self):
        result = analyze_market_trends(stock="AAPL")
        assert "stock_analysis" in result
        sa = result["stock_analysis"]
        assert sa["symbol"] == "AAPL"
        assert "current_price" in sa
        assert "momentum_score" in sa

    def test_insights_generated(self):
        result = analyze_market_trends(sector="financials")
        assert "insights" in result
        assert len(result["insights"]) > 0


class TestPortfolioDiversification:
    def test_basic(self):
        result = analyze_portfolio_diversification(["AAPL", "MSFT"])
        assert result["module"] == "portfolio_diversification"
        assert "missing_sectors" in result
        assert "new_sector_recommendations" in result
        assert "diversification_score" in result

    def test_risk_tolerance(self):
        result = analyze_portfolio_diversification(["AAPL"], risk_tolerance="aggressive")
        assert result["target_allocation"]["equity"] == 70

    def test_empty_holdings(self):
        result = analyze_portfolio_diversification([])
        assert result["diversification_score"] == 0.0
        assert len(result["missing_sectors"]) == len(SECTOR_DATA)


class TestStockScreener:
    def test_default_screening(self):
        result = run_stock_screener()
        assert result["module"] == "ai_stock_screener"
        assert "matches" in result
        assert "methodology" in result
        assert result["total_screened"] == len(STOCK_DATABASE)

    def test_with_criteria(self):
        result = run_stock_screener({"pe_max": 30, "rsi_max": 60})
        for match in result["matches"]:
            assert match["pe_ratio"] <= 30
            assert match["rsi"] <= 60

    def test_no_matches(self):
        result = run_stock_screener({"pe_max": 1})
        assert result["total_matches"] == 0

    def test_composite_score(self):
        result = run_stock_screener()
        for match in result["matches"]:
            assert 0 <= match["composite_score"] <= 100


class TestTradingStrategy:
    def test_momentum(self):
        result = design_trading_strategy(strategy_type="momentum")
        assert result["module"] == "automated_trading_strategy"
        assert result["strategy"]["name"] == "Momentum Breakout"
        assert "entry_signals" in result["strategy"]
        assert "exit_signals" in result["strategy"]
        assert "stop_loss" in result["strategy"]

    def test_mean_reversion(self):
        result = design_trading_strategy(strategy_type="mean_reversion")
        assert result["strategy"]["name"] == "Mean Reversion"

    def test_risk_adjustments(self):
        result = design_trading_strategy(risk_level="conservative")
        assert result["risk_adjustments"]["position_scale"] == 0.5

    def test_optimization_notes(self):
        result = design_trading_strategy()
        assert "optimization_notes" in result
        assert len(result["optimization_notes"]) > 0


class TestTechnicalAnalysis:
    def test_valid_stock(self):
        result = run_technical_analysis("AAPL")
        assert result["module"] == "technical_analysis"
        assert result["symbol"] == "AAPL"
        assert "indicators" in result
        assert "recommendation" in result
        assert result["recommendation"] in ("STRONG BUY", "BUY", "HOLD", "SELL", "STRONG SELL")

    def test_invalid_stock(self):
        result = run_technical_analysis("XYZFAKE")
        assert "error" in result

    def test_indicators_present(self):
        result = run_technical_analysis("MSFT")
        ind = result["indicators"]
        assert "rsi" in ind
        assert "moving_averages" in ind
        assert "macd" in ind
        assert "bollinger_bands" in ind
        assert "volume" in ind


class TestEarningsAnalysis:
    def test_valid_company(self):
        result = analyze_earnings_report("MSFT")
        assert result["module"] == "earnings_report_analysis"
        assert "key_metrics" in result
        km = result["key_metrics"]
        assert "revenue" in km
        assert "earnings_per_share" in km
        assert "investor_focus_areas" in result

    def test_invalid_company(self):
        result = analyze_earnings_report("NOTREAL")
        assert "error" in result


class TestGrowthVsDividend:
    def test_default_comparison(self):
        result = compare_growth_vs_dividend()
        assert result["module"] == "growth_vs_dividend"
        assert "growth_stock" in result
        assert "dividend_stock" in result
        assert "comparison" in result
        assert "ideal_conditions" in result

    def test_custom_stocks(self):
        result = compare_growth_vs_dividend("META", "O")
        assert result["growth_stock"]["symbol"] == "META"
        assert result["dividend_stock"]["symbol"] == "O"

    def test_invalid_stock(self):
        result = compare_growth_vs_dividend("FAKE123", "JNJ")
        assert "error" in result


class TestAlgoTradingBots:
    def test_guide(self):
        result = get_algo_trading_bot_guide()
        assert result["module"] == "algo_trading_bots"
        assert "setup_guide" in result
        guide = result["setup_guide"]
        assert "step_1_platform_selection" in guide
        assert "step_6_live_deployment" in guide
        assert "recommended_python_libraries" in result

    def test_strategy_parameter(self):
        result = get_algo_trading_bot_guide("scalping")
        assert result["strategy"] == "scalping"


class TestRiskManagement:
    def test_default(self):
        result = design_risk_management_system()
        assert result["module"] == "automated_risk_management"
        assert "volatility_assessment" in result
        assert "position_sizing" in result
        assert "stop_loss_system" in result
        assert "dynamic_adjustments" in result

    def test_custom_values(self):
        result = design_risk_management_system(portfolio_value=500000, max_risk_per_trade=0.01)
        assert result["portfolio_value"] == 500000


class TestBacktesting:
    def test_default(self):
        result = backtest_strategy()
        assert result["module"] == "backtesting_strategies"
        assert "results" in result
        assert "risk_metrics" in result
        assert "backtesting_guide" in result

    def test_custom_params(self):
        result = backtest_strategy(
            strategy_type="scalping",
            period_years=3,
            initial_capital=50000,
            symbols=["AAPL", "MSFT"],
        )
        assert result["configuration"]["strategy"] == "scalping"
        assert result["configuration"]["initial_capital"] == 50000

    def test_results_structure(self):
        result = backtest_strategy()
        r = result["results"]
        assert "final_portfolio_value" in r
        assert "win_rate" in r
        assert "profit_factor" in r
        rm = result["risk_metrics"]
        assert "sharpe_ratio" in rm
        assert "max_drawdown" in rm


class TestDispatcher:
    def test_valid_module(self):
        result = dispatch_investment_ai("technical_analysis", {"stock": "AAPL"})
        assert result["module"] == "technical_analysis"

    def test_unknown_module(self):
        result = dispatch_investment_ai("nonexistent_module", {})
        assert "error" in result
        assert "available_modules" in result

    def test_invalid_params(self):
        result = dispatch_investment_ai("technical_analysis", {"invalid_kwarg": True})
        assert "error" in result


class TestModulesCatalog:
    def test_catalog(self):
        catalog = get_modules_catalog()
        assert catalog["total_modules"] == 14
        assert "modules" in catalog
        assert "available_stocks" in catalog
        assert "available_sectors" in catalog
        assert "market_research" in catalog["modules"]


class TestLiveDataModules:
    """Tests for the 4 new live data modules (work in both live & static modes)."""

    def test_live_quote_known_stock(self):
        from services.investment_ai_tool_service import get_live_stock_quote
        result = get_live_stock_quote("AAPL")
        assert result["module"] == "live_quote"
        assert result["symbol"] == "AAPL"

    def test_live_quote_unknown_stock(self):
        from services.investment_ai_tool_service import get_live_stock_quote
        result = get_live_stock_quote("ZZZZZZNOTREAL")
        assert result["module"] == "live_quote"

    def test_market_movers(self):
        from services.investment_ai_tool_service import get_market_movers
        result = get_market_movers()
        assert result["module"] == "market_movers"

    def test_news_analysis(self):
        from services.investment_ai_tool_service import get_news_analysis
        result = get_news_analysis()
        assert result["module"] == "news_sentiment"

    def test_dispatcher_live_quote(self):
        result = dispatch_investment_ai("live_quote", {"symbol": "MSFT"})
        assert result.get("module") == "live_quote" or "error" in result

    def test_dispatcher_market_movers(self):
        result = dispatch_investment_ai("market_movers", {})
        assert result.get("module") == "market_movers" or "error" in result

    def test_data_source_field(self):
        result = analyze_market_trends(stock="AAPL")
        assert "data_source" in result


class TestAlphaVantageService:
    """Unit tests for the Alpha Vantage service layer."""

    def test_service_importable(self):
        from services.alpha_vantage_service import get_alpha_vantage_service, AlphaVantageService
        svc = get_alpha_vantage_service()
        assert isinstance(svc, AlphaVantageService)

    def test_signal_computation(self):
        from services.alpha_vantage_service import _compute_signals
        signals = _compute_signals(
            price=150.0, rsi=35.0, sma50=145.0, sma200=140.0,
            macd_data={"histogram": 0.5}, adx=28.0,
            bb_data={"upper": 160.0, "lower": 135.0},
        )
        assert "recommendation" in signals
        assert "composite_score" in signals
        assert signals["composite_score"] > 0

    def test_api_key_has_default(self):
        import services.alpha_vantage_service as avs
        assert avs.ALPHA_VANTAGE_API_KEY is not None

    def test_non_blocking_rate_check(self):
        import services.alpha_vantage_service as avs
        svc = avs.AlphaVantageService(api_key="test")
        assert svc._can_make_request() in (True, False)

    def test_information_responses_return_cached(self, monkeypatch):
        import services.alpha_vantage_service as avs

        class DummyResponse:
            def raise_for_status(self):
                return None
            def json(self):
                return {"Information": "Thank you for using Alpha Vantage!"}

        svc = avs.AlphaVantageService(api_key="test")
        monkeypatch.setattr(svc, "_can_make_request", lambda: True)
        monkeypatch.setattr(svc, "_record_request", lambda: None)
        monkeypatch.setattr(avs.requests, "get", lambda *args, **kwargs: DummyResponse())

        data = svc._fetch({"function": "GLOBAL_QUOTE", "symbol": "AAPL"}, cache_ttl=60.0)
        assert data is None

    def test_missing_api_key_returns_cached_value_without_request(self, monkeypatch):
        import services.alpha_vantage_service as avs

        svc = avs.AlphaVantageService(api_key=None)
        svc._cache["function=GLOBAL_QUOTE&symbol=AAPL"] = avs.CachedEntry(
            data={"Global Quote": {"01. symbol": "AAPL"}},
            fetched_at=avs.time.time(),
            ttl=60.0,
        )

        def unexpected_request(*args, **kwargs):
            raise AssertionError("requests.get should not be called without an API key")

        monkeypatch.setattr(avs.requests, "get", unexpected_request)

        data = svc._fetch({"function": "GLOBAL_QUOTE", "symbol": "AAPL"}, cache_ttl=60.0)

        assert data == {"Global Quote": {"01. symbol": "AAPL"}}


class TestAccessKey:
    def test_generated_key_consistency(self):
        key = get_access_key_display()
        assert key
        assert validate_investment_ai_access(key)

    def test_invalid_key(self):
        assert not validate_investment_ai_access("")
        assert not validate_investment_ai_access("wrong_key")

    def test_empty_key(self):
        assert not validate_investment_ai_access("")


class TestLiveDataParameterForwarding:
    def test_live_stock_history_forwards_outputsize(self, monkeypatch):
        import services.investment_ai_tool_service as service

        captured = {}

        class DummyAlphaVantage:
            def get_daily(self, symbol, outputsize="compact"):
                captured["symbol"] = symbol
                captured["outputsize"] = outputsize
                return {"bars": [{"date": "2026-01-01", "close": 100.0}]}

        monkeypatch.setattr(service, "LIVE_DATA_AVAILABLE", True)
        monkeypatch.setattr(service, "_av_service", DummyAlphaVantage())

        result = service.get_live_stock_history("msft", outputsize="full")

        assert result["module"] == "live_history"
        assert captured == {"symbol": "MSFT", "outputsize": "full"}

    def test_news_analysis_forwards_topics(self, monkeypatch):
        import services.investment_ai_tool_service as service

        captured = {}

        class DummyAlphaVantage:
            def get_news_sentiment(self, tickers=None, topics=None, limit=10):
                captured["tickers"] = tickers
                captured["topics"] = topics
                captured["limit"] = limit
                return {"articles": [], "total": 0, "source": "alpha_vantage"}

        monkeypatch.setattr(service, "LIVE_DATA_AVAILABLE", True)
        monkeypatch.setattr(service, "_av_service", DummyAlphaVantage())

        result = service.get_news_analysis(tickers="AAPL", topics="technology")

        assert result["module"] == "news_sentiment"
        assert captured == {"tickers": "AAPL", "topics": "technology", "limit": 10}


# ---------------------------------------------------------------------------
# API integration tests
# ---------------------------------------------------------------------------

class TestInvestmentAiApi:
    @pytest.fixture(autouse=True)
    def _get_key(self):
        self.api_key = get_access_key_display()

    def test_modules_endpoint(self):
        data, status = _get(f"/api/investment-ai/modules?api_key={self.api_key}")
        assert status == 200
        assert data["total_modules"] == 14
        assert "live_data" in data

    def test_modules_endpoint_no_key(self):
        data, status = _get_error("/api/investment-ai/modules")
        assert status == 401
        assert "error" in data

    def test_analyze_get_market_research(self):
        data, status = _get(
            f"/api/investment-ai/analyze?module=market_research&sector=technology&api_key={self.api_key}"
        )
        assert status == 200
        assert "sector_analysis" in data

    def test_analyze_get_technical_analysis(self):
        data, status = _get(
            f"/api/investment-ai/analyze?module=technical_analysis&stock=AAPL&api_key={self.api_key}"
        )
        assert status == 200
        assert data["symbol"] == "AAPL"
        assert "recommendation" in data

    def test_analyze_get_missing_module(self):
        data, status = _get_error(
            f"/api/investment-ai/analyze?api_key={self.api_key}"
        )
        assert status == 400

    def test_analyze_post_stock_screener(self):
        data, status = _post(
            "/api/investment-ai/analyze",
            {"module": "stock_screener", "params": {"pe_max": 40}},
            {"X-Investment-AI-Key": self.api_key},
        )
        assert status == 200
        assert "matches" in data
        for m in data["matches"]:
            assert m["pe_ratio"] <= 40

    def test_analyze_post_backtesting(self):
        data, status = _post(
            "/api/investment-ai/analyze",
            {
                "module": "backtesting",
                "params": {
                    "strategy_type": "momentum",
                    "period_years": 3,
                    "initial_capital": 50000,
                },
            },
            {"X-Investment-AI-Key": self.api_key},
        )
        assert status == 200
        assert "results" in data
        assert data["configuration"]["initial_capital"] == 50000

    def test_analyze_post_invalid_key(self):
        data, status = _post_error(
            "/api/investment-ai/analyze",
            {"module": "technical_analysis", "params": {"stock": "AAPL"}},
            {"X-Investment-AI-Key": "bad_key"},
        )
        assert status == 401

    def test_analyze_post_missing_module(self):
        data, status = _post_error(
            "/api/investment-ai/analyze",
            {"params": {"stock": "AAPL"}},
            {"X-Investment-AI-Key": self.api_key},
        )
        assert status == 400

    def test_access_key_endpoint_requires_admin(self):
        data, status = _get_error("/api/investment-ai/access-key")
        assert status == 403

    def test_static_page_served(self):
        req = Request(BASE_URL + "/investment-ai.html")
        with urlopen(req) as resp:
            body = resp.read().decode("utf-8")
            assert resp.status == 200
            assert "Investment AI" in body
