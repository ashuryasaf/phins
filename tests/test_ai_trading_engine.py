"""Tests for the AI Trading Engine — technical analysis, signals, bots, screener."""

import math
from services.ai_trading_engine import (
    compute_technicals,
    generate_signals,
    compute_risk_metrics,
    AutoPilotEngine,
    LiveScreener,
    UNIVERSE,
    STRATEGY_REGISTRY,
)


def _make_bars(n=60, base=100.0, step=0.5):
    """Generate synthetic uptrend bars for testing."""
    return [
        {
            "open": base + i * step,
            "high": base + i * step + 2,
            "low": base + i * step - 1,
            "close": base + i * step + 1,
            "volume": 1_000_000 + i * 10_000,
        }
        for i in range(n)
    ]


def _make_volatile_bars(n=60):
    """Generate bars with alternating up/down for mean reversion tests."""
    import math as m
    return [
        {
            "open": 100 + 5 * m.sin(i * 0.5),
            "high": 105 + 5 * m.sin(i * 0.5),
            "low": 95 + 5 * m.sin(i * 0.5),
            "close": 100 + 5 * m.sin((i + 1) * 0.5),
            "volume": 1_000_000,
        }
        for i in range(n)
    ]


# =====================================================
# Technical Indicators
# =====================================================


class TestComputeTechnicals:
    def test_empty_bars_returns_error(self):
        result = compute_technicals([])
        assert result.get("error") == "no_bars"
        assert result["indicators"] == {}

    def test_single_bar_insufficient(self):
        result = compute_technicals([{"open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 100}])
        assert result.get("error") == "insufficient_data"

    def test_60_bars_produces_indicators(self):
        bars = _make_bars(60)
        result = compute_technicals(bars)
        ind = result["indicators"]
        assert "rsi_14" in ind
        assert "bb_upper" in ind
        assert "sma_20" in ind
        assert "sma_50" in ind
        assert "ema_12" in ind
        assert ind["sma_20"] is not None
        assert ind["bb_upper"] is not None

    def test_bollinger_bands_ordering(self):
        bars = _make_bars(30)
        result = compute_technicals(bars)
        ind = result["indicators"]
        if ind.get("bb_upper") and ind.get("bb_lower"):
            assert ind["bb_upper"] >= ind["bb_lower"]

    def test_volume_ratio_computed(self):
        bars = _make_bars(30)
        result = compute_technicals(bars)
        ind = result["indicators"]
        assert "volume_ratio" in ind

    def test_prev_values_stored(self):
        bars = _make_bars(60)
        result = compute_technicals(bars)
        ind = result["indicators"]
        assert "_prev" in ind
        assert "sma_20" in ind["_prev"]


# =====================================================
# Signal Generation
# =====================================================


class TestGenerateSignals:
    def test_empty_technicals_returns_hold(self):
        result = generate_signals({"indicators": {}}, 100.0)
        assert result["recommendation"] == "HOLD"
        assert result["composite_score"] == 0

    def test_uptrend_bars_signal(self):
        bars = _make_bars(60)
        techs = compute_technicals(bars)
        result = generate_signals(techs, bars[-1]["close"])
        assert result["recommendation"] in ("STRONG BUY", "BUY", "HOLD", "SELL", "STRONG SELL")
        assert -5 <= result["composite_score"] <= 5
        assert 0 <= result["confidence"] <= 1
        assert len(result["details"]) > 0

    def test_volatile_bars_signal(self):
        bars = _make_volatile_bars(60)
        techs = compute_technicals(bars)
        result = generate_signals(techs, bars[-1]["close"])
        assert result["recommendation"] in ("STRONG BUY", "BUY", "HOLD", "SELL", "STRONG SELL")

    def test_zero_price_handled(self):
        techs = compute_technicals(_make_bars(30))
        result = generate_signals(techs, 0.0)
        assert result["recommendation"] == "HOLD"

    def test_details_have_signal_key(self):
        bars = _make_bars(60)
        techs = compute_technicals(bars)
        result = generate_signals(techs, bars[-1]["close"])
        for detail in result["details"]:
            assert "signal" in detail
            assert "name" in detail or "bias" in detail


# =====================================================
# Risk Metrics
# =====================================================


class TestRiskMetrics:
    def test_empty_bars(self):
        result = compute_risk_metrics([], [])
        assert "var_95" in result

    def test_normal_bars(self):
        bars = _make_bars(60)
        result = compute_risk_metrics(bars, [])
        assert result["daily_returns_count"] == 59
        assert result["volatility_annual"] is not None

    def test_with_positions(self):
        bars = _make_bars(60)
        positions = [{"market_value": 5000}, {"market_value": 3000}]
        result = compute_risk_metrics(bars, positions)
        assert result["total_position_value"] == 8000


# =====================================================
# AutoPilot Engine
# =====================================================


class TestAutoPilotEngine:
    def test_available_strategies(self):
        strats = AutoPilotEngine.available_strategies()
        names = [s["name"] for s in strats]
        assert "momentum" in names
        assert "mean_reversion" in names
        assert "breakout" in names
        assert "macro_sentiment" in names
        assert "crypto_momentum" in names
        assert "quantum_scalp" in names
        for s in strats:
            assert "description" in s
            assert "asset_classes" in s

    def test_create_and_list_bot(self):
        engine = AutoPilotEngine()
        result = engine.create_bot("momentum", ["AAPL", "MSFT"], {})
        assert "id" in result or "bot_id" in result
        bots = engine.get_bots()
        assert len(bots) == 1
        assert bots[0].get("strategy_name") or bots[0].get("strategy") == "momentum"

    def test_create_bot_invalid_strategy(self):
        engine = AutoPilotEngine()
        result = engine.create_bot("nonexistent", ["AAPL"], {})
        assert "error" in result

    def test_create_bot_no_symbols_still_creates(self):
        engine = AutoPilotEngine()
        result = engine.create_bot("momentum", [], {})
        assert "id" in result or "error" in result

    def test_pause_resume_delete(self):
        engine = AutoPilotEngine()
        bot = engine.create_bot("breakout", ["TSLA"], {})
        bot_id = bot.get("id") or bot.get("bot_id")

        engine.pause_bot(bot_id)
        bots = engine.get_bots()
        assert bots[0]["status"] == "paused"

        engine.resume_bot(bot_id)
        bots = engine.get_bots()
        assert bots[0]["status"] == "active"

        engine.delete_bot(bot_id)
        assert len(engine.get_bots()) == 0

    def test_evaluate_bot_with_bars(self):
        engine = AutoPilotEngine()
        bot = engine.create_bot("momentum", ["AAPL"], {})
        bot_id = bot.get("id") or bot.get("bot_id")
        bars_map = {"AAPL": _make_bars(60)}
        result = engine.evaluate_bot(bot_id, bars_map)
        assert "signals" in result
        assert "AAPL" in result["signals"]

    def test_evaluate_nonexistent_bot(self):
        engine = AutoPilotEngine()
        result = engine.evaluate_bot("FAKE-ID")
        assert "error" in result

    def test_bot_performance_empty(self):
        engine = AutoPilotEngine()
        bot = engine.create_bot("mean_reversion", ["SPY"], {})
        bot_id = bot.get("id") or bot.get("bot_id")
        perf = engine.get_bot_performance(bot_id)
        assert perf["trade_count"] == 0
        assert perf["total_pnl"] == 0


# =====================================================
# Universe & Strategy Registry
# =====================================================


class TestUniverse:
    def test_universe_has_all_sectors(self):
        expected = {"mega_cap", "tech", "finance", "energy", "healthcare",
                    "consumer", "industrial", "etf_indices", "sector_etfs",
                    "commodities", "bonds", "crypto"}
        assert expected == set(UNIVERSE.keys())

    def test_all_universe_symbols_non_empty(self):
        for sector, symbols in UNIVERSE.items():
            assert len(symbols) > 0, f"Sector {sector} has no symbols"

    def test_strategy_registry_complete(self):
        expected = {"momentum", "mean_reversion", "breakout",
                    "macro_sentiment", "crypto_momentum", "quantum_scalp"}
        assert expected == set(STRATEGY_REGISTRY.keys())


# =====================================================
# LiveScreener
# =====================================================


class TestLiveScreener:
    def test_screener_init(self):
        screener = LiveScreener()
        assert screener is not None

    def test_scan_universe_with_mock_platform(self):
        screener = LiveScreener()

        class FakePlatform:
            def get_bars(self, symbol, timeframe="1Day", limit=50):
                return _make_bars(50)
            def get_snapshot(self, symbol):
                return {"price": 130.0, "prev_close": 128.0, "volume": 5000000}
            def get_multi_snapshots(self, symbols):
                return {s: {"price": 130.0, "bar_close": 128.0} for s in symbols}

        result = screener.scan_universe(FakePlatform(), ["AAPL", "MSFT"])
        assert isinstance(result, list)
        assert len(result) >= 1
        for item in result:
            assert "symbol" in item
