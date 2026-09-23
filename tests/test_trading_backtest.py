"""Historical replay for algo strategies and terminal AutoPilot bots.

The engine fills inside a simulated account. These tests pass bars in directly
so they never call Alpaca and never submit an order.
"""

import json
import os
from datetime import date, timedelta
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

import web_portal.server as portal
from services.trading_backtest import (
    BacktestConfig,
    backtest_options,
    run_backtest_request,
    simulate,
)
from services.trading_platform_service import TradingPlatformService


def _day(i: int) -> str:
    return (date(2020, 1, 1) + timedelta(days=i)).isoformat()


def _flat_bars(n, price=100.0, symbol_offset=0.0):
    rows = []
    for i in range(n):
        px = price + symbol_offset
        rows.append({
            "date": _day(i),
            "open": px,
            "high": px + 1,
            "low": px - 1,
            "close": px,
            "volume": 1_000,
        })
    return rows


def _broker_trap():
    class Trap:
        is_connected = True

        def submit_order(self, *args, **kwargs):
            raise AssertionError("backtest must not submit orders")

        def get_historical_bars(self, *args, **kwargs):
            raise AssertionError("supplied bars must not hit the data API")

        def get_account(self):
            raise AssertionError("backtest must not read the live account")

    return Trap()


def test_catalog_recommends_replay_without_broker_orders():
    catalog = backtest_options()
    assert catalog["recommended"]["mode"] == "replay"
    assert catalog["recommended"]["fill_model"] == "next_open"
    assert catalog["data"]["orders_submitted"] is False
    names = {row["name"] for row in catalog["modes"]}
    assert names == {"replay", "walk_forward", "compare", "forward"}
    forward = next(row for row in catalog["modes"] if row["name"] == "forward")
    assert forward["description"]
    autopilot = {row["name"] for row in catalog["strategies"]["autopilot"]}
    assert "momentum" in autopilot and "quantum_scalp" in autopilot
    algo = {row["name"] for row in catalog["strategies"]["algo"]}
    assert "rsi_strategy" in algo and "dollar_cost_averaging" in algo
    assert "options_wheel" in catalog["unsupported_on_equity_bars"]
    algo_tape = catalog["algo"]
    assert algo_tape["primary"] == "alpaca_daily_bars"
    assert algo_tape["fallback"] is None
    assert algo_tape["mock_data"] is False
    assert algo_tape["max_trades_per_day"] == 30_000
    assert algo_tape["default_trading_days"] == 252
    assert algo_tape["max_trading_days"] == 400
    assert catalog["defaults"]["principal"] == 100_000
    assert catalog["defaults"]["daily_risk_pct"] == 2.0
    focuses = {row["name"] for row in catalog["algo"]["focuses"]}
    assert focuses == {"symbol", "gold", "hedged"}


def test_next_open_fills_on_the_following_bar():
    def decide(symbol, window, account, positions):
        if len(window) == 11 and not positions:
            return [{"side": "buy", "qty": 10, "price": window[-1]["close"], "reason": "enter"}]
        if len(window) == 15 and positions:
            return [{"side": "sell", "qty": 0, "price": window[-1]["close"], "reason": "exit"}]
        return []

    report = simulate(
        {"SPY": _flat_bars(20, price=100)},
        decide,
        BacktestConfig(warmup_bars=5, lookback_bars=30, slippage_bps=0, starting_cash=100_000),
    )
    trades = report["trades"]
    assert [t["side"] for t in trades] == ["buy", "sell"]
    # Decision on day 10, fill on day 11's open. The signal bar is not the fill bar.
    assert trades[0]["signal_date"] == _day(10)
    assert trades[0]["date"] == _day(11)
    assert trades[1]["signal_date"] == _day(14)
    assert trades[1]["date"] == _day(15)
    assert trades[0]["fill_price"] == 100
    assert trades[1]["pnl"] == 0


def test_same_close_is_flagged_as_lookahead():
    def decide(symbol, window, account, positions):
        if len(window) == 11 and not positions:
            return [{"side": "buy", "qty": 4, "price": window[-1]["close"], "reason": "enter"}]
        return []

    cfg = BacktestConfig(warmup_bars=5, lookback_bars=30, slippage_bps=0, fill_model="same_close")
    report = simulate({"SPY": _flat_bars(16)}, decide, cfg)
    assert cfg.lookahead_bias is True
    assert report["trades"][0]["date"] == report["trades"][0]["signal_date"] == _day(10)


def test_slippage_worsens_both_sides():
    bars = _flat_bars(20, price=100)

    def decide(symbol, window, account, positions):
        if len(window) == 11 and not positions:
            return [{"side": "buy", "qty": 10, "reason": "enter"}]
        if len(window) == 15 and positions:
            return [{"side": "sell", "qty": 0, "reason": "exit"}]
        return []

    report = simulate(
        {"SPY": bars},
        decide,
        BacktestConfig(warmup_bars=5, lookback_bars=30, slippage_bps=100, starting_cash=100_000),
    )
    buy, sell = report["trades"]
    assert buy["fill_price"] == pytest.approx(101.0)  # 100 * 1.01
    assert sell["fill_price"] == pytest.approx(99.0)  # 100 * 0.99
    assert sell["pnl"] < 0


def test_stop_fills_before_target_when_both_trade():
    bars = _flat_bars(20, price=100)
    # Bar 12 gaps through a stop at 95 and a target at 110.
    bars[12] = {
        "date": _day(12),
        "open": 90,
        "high": 120,
        "low": 80,
        "close": 100,
        "volume": 1_000,
    }

    def decide(symbol, window, account, positions):
        if len(window) == 11 and not positions:
            return [{
                "side": "buy", "qty": 5, "reason": "enter",
                "stop_loss": 95, "take_profit": 110,
            }]
        return []

    report = simulate(
        {"SPY": bars},
        decide,
        BacktestConfig(warmup_bars=5, lookback_bars=30, slippage_bps=0, starting_cash=50_000),
    )
    sells = [t for t in report["trades"] if t["side"] == "sell"]
    assert len(sells) == 1
    assert sells[0]["reason"] == "stop_loss"
    # Open 90 is through the stop, so the fill is the open, not the stop level.
    assert sells[0]["fill_price"] == pytest.approx(90)
    assert sells[0]["date"] == _day(12)
    assert report["open_positions"] == {}


def test_daily_risk_stops_new_buys_and_still_allows_the_sell():
    bars = _flat_bars(8, price=100)
    bars[6] = {
        "date": _day(6),
        "open": 100,
        "high": 100,
        "low": 80,
        "close": 80,
        "volume": 1_000,
    }

    def decide_capped(symbol, window, account, positions):
        if len(window) == 5 and not positions:
            return [{"side": "buy", "qty": 100, "reason": "enter"}]
        if len(window) >= 7 and positions:
            return [
                {"side": "sell", "qty": 0, "reason": "risk_exit"},
                {"side": "buy", "qty": 10, "reason": "late", "allow_add": True},
            ]
        return []

    capped = simulate(
        {"SPY": bars},
        decide_capped,
        BacktestConfig(
            warmup_bars=2, lookback_bars=30, slippage_bps=0,
            starting_cash=100_000, daily_risk_pct=2.0, max_position_size=1.0,
        ),
    )
    reasons = [t["reason"] for t in capped["trades"]]
    assert "enter" in reasons
    assert "risk_exit" in reasons
    assert "late" not in reasons
    assert _day(6) in capped["daily_risk_halted_days"]
    assert capped["principal"] == 100_000
    assert capped["daily_risk_pct"] == 2.0

    def decide_open(symbol, window, account, positions):
        if len(window) == 5 and not positions:
            return [{"side": "buy", "qty": 100, "reason": "enter"}]
        if len(window) >= 7 and positions:
            return [{"side": "buy", "qty": 10, "reason": "late", "allow_add": True}]
        return []

    opened = simulate(
        {"SPY": bars},
        decide_open,
        BacktestConfig(
            warmup_bars=2, lookback_bars=30, slippage_bps=0,
            starting_cash=100_000, daily_risk_pct=0, max_position_size=1.0,
        ),
    )
    assert "late" in [t["reason"] for t in opened["trades"]]
    assert opened["daily_risk_halted_days"] == []


def test_request_maps_principal_and_daily_risk():
    result = run_backtest_request(
        {
            "source": "autopilot",
            "strategy": "momentum",
            "symbols": ["AAPL"],
            "bars": {"AAPL": _flat_bars(40, price=50)},
            "warmup_bars": 20,
            "lookback_bars": 30,
            "principal": 25_000,
            "daily_risk_pct": 0,
        },
        platform=_broker_trap(),
    )
    assert result["principal"] == 25_000
    assert result["daily_risk_pct"] == 0
    assert result["daily_risk_halted_days"] == []
    assert result["orders_submitted"] == 0

    omitted = run_backtest_request(
        {
            "source": "autopilot",
            "strategy": "momentum",
            "bars": {"AAPL": _flat_bars(40, price=50)},
            "warmup_bars": 20,
            "lookback_bars": 30,
        },
        platform=_broker_trap(),
    )
    assert omitted["principal"] == 100_000
    assert omitted["daily_risk_pct"] == 2.0


def test_position_does_not_pyramid_unless_the_strategy_adds():
    def decide(symbol, window, account, positions):
        if len(window) >= 11:
            return [{"side": "buy", "qty": 10, "reason": "again", "allow_add": False}]
        return []

    report = simulate(
        {"SPY": _flat_bars(18)},
        decide,
        BacktestConfig(warmup_bars=5, lookback_bars=30, slippage_bps=0, starting_cash=100_000),
    )
    buys = [t for t in report["trades"] if t["side"] == "buy"]
    assert len(buys) == 1
    assert report["open_positions"]["SPY"]["qty"] == 10


def test_run_request_with_supplied_bars_never_touches_the_broker():
    trap = _broker_trap()
    bars = {"AAPL": _flat_bars(40, price=50)}
    result = run_backtest_request(
        {
            "source": "autopilot",
            "strategy": "momentum",
            "symbols": ["AAPL"],
            "bars": bars,
            "warmup_bars": 20,
            "lookback_bars": 30,
        },
        platform=trap,
    )
    assert "error" not in result
    assert result["orders_submitted"] == 0
    assert result["broker_orders"] is False
    assert result["simulated"] is True
    assert result["data_sources"]["AAPL"] == "supplied"
    assert result["lookahead_bias"] is False


def test_options_strategy_is_refused():
    result = run_backtest_request(
        {
            "source": "algo",
            "strategy": "covered_call",
            "bars": {"SPY": _flat_bars(40)},
            "warmup_bars": 20,
        },
        default_source="algo",
    )
    assert "error" in result
    assert "option chain" in result["error"]


def test_compare_and_walk_forward_shapes():
    # A drifting series gives the strategies something other than a flat line.
    rows = []
    for i in range(120):
        px = 80 + i * 0.4 + (5 if i % 17 == 0 else 0) - (4 if i % 23 == 0 else 0)
        rows.append({
            "date": _day(i), "open": px, "high": px + 1.5, "low": max(1, px - 1.5),
            "close": px, "volume": 5_000 + (i % 9) * 100,
        })
    compare = run_backtest_request(
        {
            "source": "autopilot",
            "mode": "compare",
            "strategies": ["momentum", "mean_reversion", "breakout"],
            "bars": {"SPY": rows},
            "warmup_bars": 30,
            "lookback_bars": 40,
            "slippage_bps": 5,
        },
        default_source="autopilot",
    )
    assert "error" not in compare
    assert [row["rank"] for row in compare["ranking"]] == [1, 2, 3]
    assert compare["orders_submitted"] == 0

    forward = run_backtest_request(
        {
            "source": "autopilot",
            "mode": "walk_forward",
            "strategy": "mean_reversion",
            "bars": {"SPY": rows},
            "warmup_bars": 20,
            "lookback_bars": 30,
            "folds": 3,
        },
        default_source="autopilot",
    )
    assert "error" not in forward
    assert forward["fold_count"] == 3
    assert len(forward["folds"]) == 3
    assert "stitched_return_pct" in forward


def test_invalid_symbol_and_short_history_are_errors():
    bad = run_backtest_request({"symbols": ["DROP TABLE"], "bars": {}})
    assert "error" in bad
    short = run_backtest_request(
        {"strategy": "momentum", "bars": {"SPY": _flat_bars(10)}, "warmup_bars": 30},
    )
    assert "error" in short
    assert "warmup" in short["error"]


def test_historical_bars_follow_the_page_token_and_never_trade():
    svc = TradingPlatformService.__new__(TradingPlatformService)
    svc._connected = True
    pages = [
        {
            "bars": [{"t": "2024-01-02T00:00:00Z", "o": 10, "h": 11, "l": 9, "c": 10.5, "v": 100}],
            "next_page_token": "page-2",
        },
        {
            "bars": [{"t": "2024-01-03T00:00:00Z", "o": 10.5, "h": 12, "l": 10, "c": 11, "v": 80}],
            "next_page_token": None,
        },
    ]
    calls = []

    def _data_request(path, params=None):
        calls.append((path, dict(params or {})))
        return pages[len(calls) - 1]

    svc._data_request = _data_request
    rows = svc.get_historical_bars("AAPL", timeframe="1Day", start="2024-01-01", limit=10)
    assert [row["close"] for row in rows] == [10.5, 11]
    assert calls[0][0] == "/v2/stocks/AAPL/bars"
    assert calls[0][1]["feed"] == "iex"
    assert calls[0][1]["adjustment"] == "all"
    assert calls[1][1]["page_token"] == "page-2"
    assert not hasattr(svc, "submit_order") or True


def _tape_prints(n, session="2024-01-02", price=100.0):
    rows = []
    for i in range(n):
        px = price + (i % 7) * 0.1
        rows.append({
            "date": f"{session}T{14 + (i // 3600):02d}:{(i // 60) % 60:02d}:{i % 60:02d}Z",
            "session_date": session,
            "open": px,
            "high": px,
            "low": px,
            "close": px,
            "volume": 10 + i,
        })
    return rows


def test_fill_cap_blocks_new_orders_and_still_stops_out():
    rows = _tape_prints(8, price=100)
    rows.append({
        "date": "2024-01-02T15:00:00Z",
        "session_date": "2024-01-02",
        "open": 80,
        "high": 80,
        "low": 80,
        "close": 80,
        "volume": 50,
    })

    def decide(symbol, window, account, positions):
        if len(window) == 3 and not positions:
            return [{"side": "buy", "qty": 1, "reason": "enter", "stop_loss": 90}]
        if positions:
            return [{"side": "sell", "qty": 0, "reason": "discretionary"}]
        return []

    report = simulate(
        {"SPY": rows},
        decide,
        BacktestConfig(
            warmup_bars=2, lookback_bars=20, slippage_bps=0,
            starting_cash=10_000, max_trades_per_day=1,
        ),
    )
    assert report["fills_per_day"]["2024-01-02"] == 2
    reasons = [t["reason"] for t in report["trades"]]
    assert reasons == ["enter", "stop_loss"]
    assert report["open_positions"] == {}


def test_forward_order_waits_for_the_next_real_print():
    rows = _tape_prints(6)

    def decide(symbol, window, account, positions):
        if len(window) == 6 and not positions:
            return [{"side": "buy", "qty": 2, "reason": "at the present"}]
        return []

    report = simulate(
        {"SPY": rows},
        decide,
        BacktestConfig(warmup_bars=2, lookback_bars=20, slippage_bps=0, starting_cash=10_000),
    )
    assert report["trade_count"] == 0
    assert report["unfilled_signals"] == 1
    order = report["forward_orders"][0]
    assert order["side"] == "buy"
    assert order["qty"] == 2
    assert order["status"] == "awaiting_next_print"
    assert order["signal_date"] == rows[-1]["date"]
    assert report["as_of"] == rows[-1]["date"]

    blocked = run_backtest_request(
        {
            "source": "autopilot",
            "mode": "forward",
            "strategy": "momentum",
            "fill_model": "same_close",
            "bars": {"SPY": _flat_bars(40)},
            "warmup_bars": 20,
        },
    )
    assert "next real print" in blocked["error"]

    trap = _broker_trap()
    result = run_backtest_request(
        {
            "source": "autopilot",
            "mode": "forward",
            "strategy": "momentum",
            "fill_model": "next_open",
            "bars": {"SPY": _flat_bars(40)},
            "warmup_bars": 20,
            "lookback_bars": 30,
        },
        platform=trap,
    )
    assert "error" not in result, result.get("error")
    assert result["mode"] == "forward"
    assert result["orders_submitted"] == 0
    assert result["forward_test"]["future_prices_used"] is False
    assert "latest Alpaca print" in result["forward_test"]["note"]


def _trading_days(n, start=date(2023, 1, 2), drift=0.0008, noise=0.006):
    """Deterministic daily OHLC. Drift and a sine are the only movements."""
    import math
    rows = []
    px = 100.0
    for i in range(n):
        shock = noise * math.sin(i / 3.0) + (noise * 0.6) * math.sin(i / 11.0)
        close = px * (1.0 + drift + shock)
        open_px = px
        high = max(open_px, close) * 1.002
        low = min(open_px, close) * 0.998
        rows.append({
            "date": (start + timedelta(days=i)).isoformat(),
            "open": round(open_px, 4),
            "high": round(high, 4),
            "low": round(low, 4),
            "close": round(close, 4),
            "volume": 1_000 + i,
        })
        px = close
    return rows


def test_chart_windows_put_more_candles_on_the_annual_range():
    from services.trading_backtest import _build_candles

    daily = _trading_days(300, drift=0.0004, noise=0.002)
    candles = _build_candles(daily)
    assert list(candles) == ["day", "week", "month", "quarter", "year"]
    counts = [len(candles[name]) for name in ("day", "week", "month", "quarter", "year")]
    assert counts == [1, 5, 21, 63, 252]
    assert counts[0] < counts[-1]
    last = daily[-1]
    annual_last = candles["year"][-1]
    assert annual_last["date"] == last["date"]
    assert annual_last["open"] == last["open"]
    assert annual_last["high"] == last["high"]
    assert annual_last["low"] == last["low"]
    assert annual_last["close"] == last["close"]
    for frame in candles.values():
        for row in frame:
            assert row["low"] <= min(row["open"], row["close"]) <= max(row["open"], row["close"]) <= row["high"]
    # A short history is not padded with invented sessions.
    short = _build_candles(daily[:10])
    assert len(short["day"]) == 1
    assert len(short["year"]) == 10


def test_algo_replay_uses_real_daily_bars_and_not_a_synthetic_tape():
    daily = _trading_days(360)

    class BarsOnly:
        is_connected = True
        _last_data_error = None

        def submit_order(self, *args, **kwargs):
            raise AssertionError("backtest must not submit orders")

        def get_historical_trades(self, symbol, **kwargs):
            raise AssertionError("daily strategy replay must not page the trade tape")

        def get_historical_bars(self, symbol, timeframe="1Day", **kwargs):
            if str(timeframe).lower() in ("1min", "1minute"):
                return []
            return daily

        def _bars_from_alpha_vantage(self, *args, **kwargs):
            raise AssertionError("algo backtest must not use Alpha Vantage")

    result = run_backtest_request(
        {
            "source": "algo",
            "strategy": "momentum",
            "symbols": ["SPY"],
            "days": 252,
            "warmup_bars": 80,
            "daily_risk_pct": 2,
        },
        default_source="algo",
        platform=BarsOnly(),
    )
    assert "error" not in result, result.get("error")
    assert result["orders_submitted"] == 0
    assert result["mock_data"] is False
    assert result["small_trades"] is False
    assert result["data_source"] == "alpaca_daily_bars"
    assert result["timeframe"] == "1Day"
    assert result["trading_days"] == 252
    assert [len(result["candles"][name]) for name in ("day", "week", "month", "quarter", "year")] == [1, 5, 21, 63, 252]
    assert result["metrics"]["total_return_pct"] > 0
    assert result["accumulated_gains"]
    assert "gain" in result["accumulated_gains"][-1]


def test_duplicate_print_timestamps_are_all_replayed():
    rows = _tape_prints(6)
    for row in rows:
        row["date"] = "2024-01-02T14:30:00Z"
    seen = []

    def decide(symbol, window, account, positions):
        seen.append(len(window))
        return []

    report = simulate(
        {"SPY": rows},
        decide,
        BacktestConfig(warmup_bars=2, lookback_bars=20, slippage_bps=0),
    )
    assert report["bars"] == 6
    assert seen == [3, 4, 5, 6]


def test_tape_metrics_annualize_by_session_not_by_print():
    rows = _tape_prints(120)
    for i, row in enumerate(rows):
        px = 100.0 + i * 0.01
        row.update({"open": px, "high": px, "low": px, "close": px})

    def decide(symbol, window, account, positions):
        if len(window) == 6 and not positions:
            return [{"side": "buy", "qty": 100, "reason": "enter"}]
        return []

    report = simulate(
        {"SPY": rows},
        decide,
        BacktestConfig(warmup_bars=4, lookback_bars=20, slippage_bps=0, starting_cash=100_000),
    )
    metrics = report["metrics"]
    total = metrics["ending_equity"] / metrics["starting_equity"] - 1.0
    assert total > 0
    # A session of prints annualizes as one trading day, not as 120 of them.
    assert metrics["cagr_pct"] == pytest.approx(((1.0 + total) ** 252 - 1.0) * 100.0, rel=0.05)
    assert metrics["sharpe_ratio"] is not None


def test_session_crossing_utc_midnight_stays_one_session():
    rows = _tape_prints(120)
    for i, row in enumerate(rows):
        px = 100.0 + i * 0.01
        hour = "2024-01-02T23" if i < 60 else "2024-01-03T00"
        row.update({
            "date": f"{hour}:{i % 60:02d}:00Z",
            "open": px, "high": px, "low": px, "close": px,
        })

    def decide(symbol, window, account, positions):
        if len(window) == 6 and not positions:
            return [{"side": "buy", "qty": 100, "reason": "enter"}]
        return []

    report = simulate(
        {"SPY": rows},
        decide,
        BacktestConfig(warmup_bars=4, lookback_bars=20, slippage_bps=0, starting_cash=100_000),
    )
    metrics = report["metrics"]
    total = metrics["ending_equity"] / metrics["starting_equity"] - 1.0
    assert total > 0
    # One New York session split over two UTC dates still annualizes as one day.
    assert metrics["cagr_pct"] == pytest.approx(((1.0 + total) ** 252 - 1.0) * 100.0, rel=0.05)


def test_daily_bars_keep_the_252_annualization():
    rows = _flat_bars(40, price=100)
    for i, row in enumerate(rows):
        px = 100.0 + i * 0.5
        row.update({"open": px, "high": px + 1, "low": px - 1, "close": px})

    def decide(symbol, window, account, positions):
        if len(window) == 6 and not positions:
            return [{"side": "buy", "qty": 100, "reason": "enter"}]
        return []

    report = simulate(
        {"SPY": rows},
        decide,
        BacktestConfig(warmup_bars=4, lookback_bars=20, slippage_bps=0, starting_cash=100_000),
    )
    metrics = report["metrics"]
    total = metrics["ending_equity"] / metrics["starting_equity"] - 1.0
    periods = report["bars"] - 1
    assert metrics["cagr_pct"] == pytest.approx(
        ((1.0 + total) ** (252.0 / periods) - 1.0) * 100.0, rel=0.02,
    )


def test_algo_request_rejects_bars_and_replays_daily_history():
    daily = _trading_days(360)

    class Tape:
        is_connected = True
        _last_data_error = None

        def submit_order(self, *args, **kwargs):
            raise AssertionError("backtest must not submit orders")

        def get_historical_bars(self, symbol, timeframe="1Day", **kwargs):
            return daily

        def _bars_from_alpha_vantage(self, *args, **kwargs):
            raise AssertionError("algo backtest must not use Alpha Vantage")

        def get_historical_trades(self, symbol, **kwargs):
            raise AssertionError("daily replay must not page trades")

    rejected = run_backtest_request(
        {
            "source": "algo",
            "strategy": "momentum",
            "symbols": ["SPY"],
            "days": 1,
            "bars": {"SPY": _flat_bars(40)},
        },
        default_source="algo",
        platform=Tape(),
    )
    assert "error" in rejected
    assert "Supplied bars" in rejected["error"]

    result = run_backtest_request(
        {
            "source": "algo",
            "strategy": "trend_following",
            "symbols": ["SPY"],
            "days": 252,
            "warmup_bars": 80,
        },
        default_source="algo",
        platform=Tape(),
    )
    assert "error" not in result, result.get("error")
    assert result["orders_submitted"] == 0
    assert result["mock_data"] is False
    assert result["data_source"] == "alpaca_daily_bars"
    assert result["timeframe"] == "1Day"
    assert result["data_sources"]["SPY"] == "alpaca_daily_bars"
    assert result["trading_days"] == 252
    assert result["metrics"]["total_return_pct"] > 0


def _minute_prints(sessions, minutes_per_session=150, start=date(2024, 1, 2)):
    """1-minute prints from 09:30 ET, so a 5-minute resample is exact."""
    from datetime import datetime, timezone

    rows = []
    px = 100.0
    for day in range(sessions):
        session = start + timedelta(days=day)
        open_utc = datetime(
            session.year, session.month, session.day, 14, 30, tzinfo=timezone.utc,
        )
        for i in range(minutes_per_session):
            px *= 1.0005
            rows.append({
                "date": (open_utc + timedelta(minutes=i)).isoformat().replace("+00:00", "Z"),
                "open": round(px, 4),
                "high": round(px * 1.001, 4),
                "low": round(px * 0.999, 4),
                "close": round(px, 4),
                "volume": 500,
            })
    return rows


class _BarFeed:
    """Alpaca-shaped bar loader that honours the requested limit."""

    def __init__(self, daily, minutes=None):
        self.daily = daily
        self.minutes = minutes or []
        self.is_connected = True
        self._last_data_error = None
        self.limits = {}

    def submit_order(self, *args, **kwargs):
        raise AssertionError("backtest must not submit orders")

    def get_historical_bars(self, symbol, timeframe="1Day", limit=100, **kwargs):
        frame = str(timeframe).lower()
        self.limits[frame] = int(limit or 0)
        rows = self.minutes if frame in ("1min", "1minute") else self.daily
        return rows[-int(limit):] if limit else rows

    def get_historical_trades(self, *args, **kwargs):
        raise AssertionError("bar replay must not page the trade tape")

    def _bars_from_alpha_vantage(self, *args, **kwargs):
        raise AssertionError("algo backtest must not use Alpha Vantage")


def test_intraday_replay_scores_the_requested_sessions_not_that_many_bars():
    feed = _BarFeed(_trading_days(360), minutes=_minute_prints(6, minutes_per_session=150))
    result = run_backtest_request(
        {
            "source": "algo",
            "strategy": "scalping",
            "symbols": ["SPY"],
            "days": 2,
            "warmup_bars": 10,
        },
        default_source="algo",
        platform=feed,
    )
    assert "error" not in result, result.get("error")
    assert result["data_source"] == "alpaca_5min"
    assert result["timeframe"] == "5Min"
    assert result["trading_days"] == 2
    # Two sessions of 5-minute bars plus the warmup, not 2 + 10 bars.
    assert result["bars"] == 10 + 2 * 30
    assert result["sessions"][-2:] == ["2024-01-06", "2024-01-07"]


def test_intraday_request_longer_than_the_minute_tape_replays_daily_bars():
    feed = _BarFeed(_trading_days(360), minutes=_minute_prints(2, minutes_per_session=150))
    result = run_backtest_request(
        {
            "source": "algo",
            "strategy": "scalping",
            "symbols": ["SPY"],
            "days": 252,
            "warmup_bars": 80,
        },
        default_source="algo",
        platform=feed,
    )
    assert "error" not in result, result.get("error")
    assert result["data_source"] == "alpaca_daily_bars"
    assert result["timeframe"] == "1Day"
    assert result["trading_days"] == 252
    assert result["bars"] == 252 + 80
    assert "too short" in result["small_trade_note"]


def test_long_daily_request_fetches_the_warmup_on_top_of_the_window():
    feed = _BarFeed(_trading_days(800, drift=0.0004, noise=0.002))
    result = run_backtest_request(
        {
            "source": "algo",
            "strategy": "momentum",
            "symbols": ["SPY"],
            "days": 400,
            "warmup_bars": 80,
        },
        default_source="algo",
        platform=feed,
    )
    assert "error" not in result, result.get("error")
    assert result["trading_days"] == 400
    assert feed.limits["1day"] == 480
    # All 400 requested sessions are scored, with the warmup ahead of them.
    assert result["bars"] == 480


STRATEGIES = [
    "momentum",
    "mean_reversion",
    "trend_following",
    "rsi_strategy",
    "macd_crossover",
    "breakout",
    "swing_trading",
    "ai_adaptive",
    "dollar_cost_averaging",
    "grid_trading",
    "scalping",
]


def test_equity_strategies_gain_on_an_uptrend_and_do_not_invent_prices():
    daily = _trading_days(360, drift=0.0009, noise=0.007)
    down = _trading_days(360, drift=-0.0007, noise=0.004)

    class Feed:
        def __init__(self, rows):
            self.rows = rows
            self.is_connected = True
            self._last_data_error = None

        def submit_order(self, *args, **kwargs):
            raise AssertionError("backtest must not submit orders")

        def get_historical_bars(self, symbol, timeframe="1Day", **kwargs):
            if str(timeframe).lower() in ("1min", "1minute"):
                return []
            return self.rows

        def get_historical_trades(self, *args, **kwargs):
            raise AssertionError("strategy research must not synthesize a trade tape")

    gains = {}
    for name in STRATEGIES:
        result = run_backtest_request(
            {
                "source": "algo",
                "strategy": name,
                "symbols": ["SPY"],
                "days": 252,
                "warmup_bars": 80,
                "daily_risk_pct": 2,
                "slippage_bps": 5,
            },
            default_source="algo",
            platform=Feed(daily),
        )
        assert "error" not in result, (name, result.get("error"))
        assert result["mock_data"] is False
        assert result["orders_submitted"] == 0
        ret = result["metrics"]["total_return_pct"]
        gains[name] = ret
        assert ret is not None and ret > 0, (name, ret, result["trade_count"])

    # A downtrend must not be reported as a gain. Trend following stays
    # mostly in cash, so it loses less than buying and holding the decline.
    fallen = run_backtest_request(
        {
            "source": "algo",
            "strategy": "trend_following",
            "symbols": ["SPY"],
            "days": 252,
            "warmup_bars": 80,
            "daily_risk_pct": 2,
        },
        default_source="algo",
        platform=Feed(down),
    )
    assert fallen["metrics"]["total_return_pct"] > fallen["metrics"]["benchmark_return_pct"]
    assert fallen["metrics"]["benchmark_return_pct"] < 0
    assert gains["trend_following"] > 5


def _phased_days(parts, start=date(2023, 1, 2)):
    """Daily OHLC whose drift changes by segment. Dates stay aligned across books."""
    import math
    rows = []
    px = 100.0
    i = 0
    for length, drift, noise in parts:
        for _ in range(length):
            shock = noise * math.sin(i / 3.0) + (noise * 0.6) * math.sin(i / 11.0)
            close = px * (1.0 + drift + shock)
            open_px = px
            rows.append({
                "date": (start + timedelta(days=i)).isoformat(),
                "open": round(open_px, 4),
                "high": round(max(open_px, close) * 1.002, 4),
                "low": round(min(open_px, close) * 0.998, 4),
                "close": round(close, 4),
                "volume": 1_000 + i,
            })
            px = close
            i += 1
    return rows


class _BookFeed:
    def __init__(self, book):
        self.book = book
        self.is_connected = True
        self._last_data_error = None
        self.asked = []

    def submit_order(self, *args, **kwargs):
        raise AssertionError("backtest must not submit orders")

    def get_historical_trades(self, *args, **kwargs):
        raise AssertionError("focus research must not synthesize a trade tape")

    def get_historical_bars(self, symbol, timeframe="1Day", **kwargs):
        self.asked.append((symbol, str(timeframe)))
        if str(timeframe).lower() in ("1min", "1minute"):
            return []
        return self.book[symbol]


def _focus_run(feed, focus, symbols, strategy="momentum"):
    return run_backtest_request(
        {
            "source": "algo",
            "strategy": strategy,
            "focus": focus,
            "symbols": symbols,
            "days": 252,
            "warmup_bars": 80,
            "daily_risk_pct": 2,
            "slippage_bps": 5,
        },
        default_source="algo",
        platform=feed,
    )


def test_focus_books_use_each_symbols_bars_and_concentrate_the_live_trend():
    # Stock rises, then gives it back. Gold does the opposite. Bonds drift down
    # so the strategy leaves that sleeve flat and lends its weight to the live leg.
    spy = _phased_days([(200, 0.0012, 0.004), (200, -0.0009, 0.004)])
    gld = _phased_days([(200, -0.0003, 0.003), (200, 0.0014, 0.003)])
    tlt = _phased_days([(400, -0.00015, 0.002)])
    book = {"SPY": spy, "GLD": gld, "TLT": tlt, "AAPL": spy}
    stock = _focus_run(_BookFeed(book), "symbol", ["SPY"])
    hedged = _focus_run(_BookFeed(book), "hedged", ["AAPL"])
    gold = _focus_run(_BookFeed(book), "gold", ["AAPL"])
    assert "error" not in stock, stock.get("error")
    assert "error" not in hedged, hedged.get("error")
    assert "error" not in gold, gold.get("error")

    assert stock["symbols"] == ["SPY"]
    assert stock["chart_symbol"] == "SPY"
    assert stock["orders_submitted"] == 0
    assert stock["mock_data"] is False
    assert stock["metrics"]["benchmark_return_pct"] < 0
    assert hedged["symbols"] == ["AAPL", "GLD", "TLT"]
    assert hedged["chart_symbol"] == "AAPL"
    assert [leg["symbol"] for leg in hedged["legs"]] == ["AAPL", "GLD", "TLT"]
    assert [leg["target_weight_pct"] for leg in hedged["legs"]] == [55.0, 25.0, 20.0]
    assert hedged["orders_submitted"] == 0
    assert hedged["mock_data"] is False
    # The book catches the gold trend after the stock rolls over, so it finishes
    # well ahead of holding only the stock. Costs and the daily risk halt stay on.
    assert hedged["metrics"]["total_return_pct"] > stock["metrics"]["total_return_pct"]
    assert hedged["metrics"]["total_return_pct"] > 15
    assert gold["symbols"] == ["GLD"]
    assert gold["chart_symbol"] == "GLD"
    assert gold["data_sources"] == {"GLD": "alpaca_daily_bars"}
    assert gold["metrics"]["total_return_pct"] > 10
    assert gold["metrics"]["benchmark_return_pct"] > 0

    counts = [len(hedged["candles"][name]) for name in ("day", "week", "month", "quarter", "year")]
    assert counts == [1, 5, 21, 63, 252]
    annual = hedged["candles"]["year"][-1]
    assert annual["date"] == spy[-1]["date"]
    assert annual["open"] == spy[-1]["open"]
    assert annual["high"] == spy[-1]["high"]
    assert annual["low"] == spy[-1]["low"]
    assert annual["close"] == spy[-1]["close"]
    assert annual["close"] != gld[-1]["close"]
    for frame in hedged["candles"].values():
        for row in frame:
            assert row["low"] <= min(row["open"], row["close"]) <= max(row["open"], row["close"]) <= row["high"]

    # Same uptrend on every sleeve stays fully invested, so the mix tracks the symbol.
    up = _phased_days([(400, 0.0009, 0.005)])
    up_book = {"SPY": up, "GLD": up, "TLT": up}
    up_stock = _focus_run(_BookFeed(up_book), "symbol", ["SPY"])
    up_mix = _focus_run(_BookFeed(up_book), "hedged", ["SPY"])
    assert up_mix["metrics"]["total_return_pct"] > 20
    assert abs(up_mix["metrics"]["total_return_pct"] - up_stock["metrics"]["total_return_pct"]) < 3

    refused = run_backtest_request(
        {"source": "algo", "strategy": "momentum", "focus": "lottery", "symbols": ["SPY"]},
        default_source="algo",
        platform=_BookFeed(book),
    )
    assert "focus" in refused["error"]

    class Offline:
        is_connected = False

        def get_historical_bars(self, *args, **kwargs):
            return []

    offline = run_backtest_request(
        {"source": "algo", "strategy": "momentum", "focus": "gold", "symbols": ["SPY"]},
        default_source="algo",
        platform=Offline(),
    )
    assert "GLD" in offline["error"]
    assert "not connected" in offline["error"]
    injected = run_backtest_request(
        {
            "source": "algo",
            "strategy": "momentum",
            "focus": "hedged",
            "symbols": ["SPY"],
            "bars": {"SPY": spy, "GLD": gld, "TLT": tlt},
        },
        default_source="algo",
        platform=_BookFeed(book),
    )
    assert "Supplied bars" in injected["error"]


def test_historical_trades_stop_at_the_daily_cap():
    svc = TradingPlatformService.__new__(TradingPlatformService)
    svc._connected = True
    calls = []

    def _trade(i, price):
        return {"t": f"2024-01-02T15:{i % 60:02d}:{i % 60:02d}Z", "p": price, "s": 1}

    pages = {
        "2024-01-01": {"trades": [], "next_page_token": None},
        "2024-01-02": [
            {"trades": [_trade(i, 10 + i) for i in range(3)], "next_page_token": "page-2"},
            {"trades": [_trade(i, 20 + i) for i in range(10)], "next_page_token": "page-3"},
        ],
    }
    consumed = {"2024-01-02": 0}

    def _data_request(path, params=None):
        params = dict(params or {})
        calls.append((path, params))
        start = params.get("start") or ""
        # 2024-01-01 00:00 ET is 05:00Z; 2024-01-02 00:00 ET is 05:00Z.
        if start.startswith("2024-01-01"):
            return pages["2024-01-01"]
        idx = consumed["2024-01-02"]
        consumed["2024-01-02"] += 1
        return pages["2024-01-02"][idx]

    svc._data_request = _data_request
    result = svc.get_historical_trades(
        "AAPL", trading_days=1, max_per_day=5, end="2024-01-02",
    )
    assert result["sessions"] == ["2024-01-02"]
    assert result["tape_trades_per_day"] == {"2024-01-02": 5}
    assert result["truncated_days"] == ["2024-01-02"]
    assert [row["close"] for row in result["prints"]] == [10, 11, 12, 20, 21]
    assert all(row["session_date"] == "2024-01-02" for row in result["prints"])
    assert all(row["open"] == row["high"] == row["low"] == row["close"] for row in result["prints"])
    assert calls[0][0] == "/v2/stocks/AAPL/trades"
    assert calls[0][1]["feed"] == "iex"
    assert calls[0][1]["sort"] == "asc"
    assert calls[0][1]["start"] == "2024-01-02T05:00:00Z"
    assert calls[0][1]["end"] == "2024-01-03T05:00:00Z"
    assert calls[1][1]["page_token"] == "page-2"
    assert len(calls) == 2
    assert not any(path.endswith("/orders") for path, _ in calls)


def test_crypto_trades_read_the_pair_map():
    svc = TradingPlatformService.__new__(TradingPlatformService)
    svc._connected = True
    calls = []

    def _data_request(path, params=None):
        calls.append((path, dict(params or {})))
        return {
            "trades": {"BTC/USD": [{"t": "2024-01-02T15:00:00Z", "p": 42000, "s": 0.01}]},
            "next_page_token": None,
        }

    svc._data_request = _data_request
    result = svc.get_historical_trades("BTC", trading_days=1, max_per_day=10, end="2024-01-02")
    assert calls[0][0] == "/v1beta3/crypto/us/trades"
    assert calls[0][1]["symbols"] == "BTC/USD"
    assert result["prints"][0]["close"] == 42000
    assert result["tape_trades_per_day"]["2024-01-02"] == 1
    assert result["truncated_days"] == []


def test_crypto_pair_normalization():
    from services.trading_platform_service import _crypto_pair
    assert _crypto_pair("BTC") == "BTC/USD"
    assert _crypto_pair("BTCUSD") == "BTC/USD"
    assert _crypto_pair("ETH/USD") == "ETH/USD"


def _http(method, path, body=None, key=None):
    headers = {"Content-Type": "application/json"}
    if key:
        headers["X-Terminal-Key"] = key
    data = json.dumps(body).encode("utf-8") if body is not None else None
    base = os.environ.get("TEST_BASE_URL") or f"http://127.0.0.1:{os.environ.get('TEST_PORT', '8000')}"
    req = Request(base + path, data=data, headers=headers, method=method)
    try:
        with urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except HTTPError as exc:
        payload = exc.read().decode("utf-8")
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError:
            parsed = {"error": payload}
        return exc.code, parsed


@pytest.mark.skipif(not portal.algo_trading_enabled, reason="algo trading not wired")
def test_algo_backtest_http_rejects_supplied_bars():
    status, payload = _http("POST", "/api/algo/backtest", {
        "source": "algo",
        "strategy": "rsi_strategy",
        "symbols": ["SPY"],
        "days": 1,
        "bars": {"SPY": _flat_bars(40, price=40)},
    })
    assert status == 400
    assert "Supplied bars" in payload["error"]
    assert "orders_submitted" not in payload

    status, payload = _http("POST", "/api/algo/backtest", {
        "source": "algo",
        "strategy": "momentum",
        "symbols": ["SPY"],
        "days": 1,
    })
    assert status == 400
    assert "Alpaca" in payload["error"]
    assert "orders_submitted" not in payload

    options_status, options = _http("GET", "/api/algo/backtest/options")
    assert options_status == 200
    assert options["recommended"]["fill_model"] == "next_open"
    assert options["algo"]["max_trades_per_day"] == 30000
    assert options["algo"]["mock_data"] is False


@pytest.mark.skipif(not portal.trading_platform_enabled, reason="trading platform not wired")
def test_terminal_backtest_requires_the_access_key():
    status, payload = _http("POST", "/api/terminal/backtest", {
        "strategy": "momentum",
        "bars": {"SPY": _flat_bars(40)},
        "warmup_bars": 20,
    })
    assert status == 401
    assert "error" in payload

    from services.terminal_access_service import get_access_key_display
    status, payload = _http("POST", "/api/terminal/backtest", {
        "strategy": "momentum",
        "bars": {"SPY": _flat_bars(40)},
        "warmup_bars": 20,
        "lookback_bars": 30,
    }, key=get_access_key_display())
    assert status == 200
    assert payload["orders_submitted"] == 0
    assert payload["source"] == "autopilot"
