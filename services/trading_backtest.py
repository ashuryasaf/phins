"""
Historical replay for the algo-trading page and the terminal AutoPilot bots.

The live decision functions stay in charge:

- Terminal AutoPilot strategies are ``AutoPilotStrategy.evaluate`` (the same
  call ``AutoPilotEngine.evaluate_bot`` makes).
- Algo-page strategies are the ``AlgoTradingService`` methods behind
  ``generate_signal`` (RSI, MACD, momentum, and the rest of the equity set).

Terminal AutoPilot replays Alpaca historical bars. The algo-trading page
replays Alpaca's daily bars (real OHLC, one decision per session) so the
equity rules run on the horizon they were written for. Supplied bars and
Alpha Vantage are not used, and missing prices are never invented. A
scalping or grid run uses real 5-minute bars when Alpaca has them. The
charts are windows of those daily candles: one session, one week, one
month, one quarter, and one year. Fills happen in a simulated cash account.
This module never calls ``submit_order`` and never mutates AutoPilot bot state.

Recommended setup: mode ``replay``, fill model ``next_open``, 5 bps of
slippage, one year of sessions. ``next_open`` fills the signal on the
following bar's open, so the decision cannot see its own fill.
``walk_forward`` repeats that replay on consecutive windows. ``compare``
ranks several strategies on the same bars and the same costs.
"""

from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

logger = logging.getLogger("phins.trading_backtest")

_SYMBOL_RE = re.compile(r"^[A-Z0-9][A-Z0-9./-]{0,14}$")

MAX_BARS = 2000
MAX_SYMBOLS = 8
MAX_STRATEGIES = 6
MAX_TRADES_PER_DAY = 30_000
MAX_TRADING_DAYS = 400
DEFAULT_TRADING_DAYS = 252
MIN_TAPE_PRINTS = 30
# Chart windows are counts of real daily candles, shortest range first.
CHART_WINDOWS = (("day", 1), ("week", 5), ("month", 21), ("quarter", 63), ("year", 252))
_INTRADAY_STRATEGIES = frozenset({"scalping", "grid_trading"})
DEFAULT_LOOKBACK = 100  # live AutoPilot evaluate loads 100 daily bars
DEFAULT_WARMUP = 80
DEFAULT_CASH = 100_000.0
DEFAULT_SLIPPAGE_BPS = 5.0

# Equity strategies on the algo page. Options structures need a chain, not
# a stock bar, so they are listed and refused rather than silently skipped.
_ALGO_METHODS = {
    "rsi_strategy": "_rsi_strategy",
    "macd_crossover": "_macd_strategy",
    "momentum": "_momentum_strategy",
    "mean_reversion": "_mean_reversion_strategy",
    "trend_following": "_trend_following_strategy",
    "breakout": "_breakout_strategy",
    "ai_adaptive": "_ai_adaptive_strategy",
    "dollar_cost_averaging": "_dca_strategy",
    "dca": "_dca_strategy",
    "scalping": "_scalping_strategy",
    "swing_trading": "_swing_trading_strategy",
    "grid_trading": "_grid_trading_strategy",
}
_ALGO_ACCUMULATE = {"dollar_cost_averaging", "dca"}
_ALGO_UNSUPPORTED = (
    "options_wheel",
    "covered_call",
    "cash_secured_put",
    "iron_condor",
    "protective_put",
    "arbitrage",
)

DecideFn = Callable[[str, List[Dict[str, Any]], Dict[str, Any], List[Dict[str, Any]]], List[Dict[str, Any]]]


@dataclass
class BacktestConfig:
    starting_cash: float = DEFAULT_CASH
    slippage_bps: float = DEFAULT_SLIPPAGE_BPS
    commission_per_share: float = 0.0
    commission_bps: float = 0.0
    fill_model: str = "next_open"  # next_open | same_close
    lookback_bars: int = DEFAULT_LOOKBACK
    warmup_bars: int = DEFAULT_WARMUP
    risk_per_trade: float = 0.02
    max_position_size: float = 0.05
    max_open_positions: int = 5
    stop_loss_pct: float = 0.0
    take_profit_pct: float = 0.0
    folds: int = 4
    # None leaves the fill engine uncapped (in-memory unit tests).
    # Algo requests set this to MAX_TRADES_PER_DAY.
    max_trades_per_day: Optional[int] = None
    # 0 disables the session loss cap. API requests default this to 2,
    # matching a live AutoPilot bot's max_daily_loss.
    daily_risk_pct: float = 0.0

    @property
    def lookahead_bias(self) -> bool:
        return self.fill_model == "same_close"


@dataclass
class _Position:
    qty: int
    avg_price: float
    stop: Optional[float] = None
    take_profit: Optional[float] = None


def backtest_options() -> Dict[str, Any]:
    """Catalog the modes, fill models, and strategies a caller can run."""
    from services.ai_trading_engine import AutoPilotEngine

    autopilot = AutoPilotEngine.available_strategies()
    algo = [
        {
            "name": name,
            "description": _algo_blurb(name),
            "accumulates": name in _ALGO_ACCUMULATE,
        }
        for name in _ALGO_METHODS
        if name != "dca"
    ]
    return {
        "recommended": {
            "mode": "replay",
            "fill_model": "next_open",
            "timeframe": "1Day",
            "slippage_bps": DEFAULT_SLIPPAGE_BPS,
            "lookback_bars": DEFAULT_LOOKBACK,
            "warmup_bars": DEFAULT_WARMUP,
            "why": (
                "Replay the same AutoPilot evaluate() and algo-page strategy "
                "functions on Alpaca historical bars. Fill at the next bar's "
                "open so the signal cannot see the fill. Alpaca is contacted "
                "only for market data; no orders are submitted."
            ),
        },
        "modes": [
            {
                "name": "replay",
                "label": "Historical replay",
                "recommended": True,
                "description": (
                    "One strategy, one window. Decisions use the trailing "
                    "lookback (100 bars, matching a live AutoPilot evaluate) "
                    "and a position is entered only when flat."
                ),
            },
            {
                "name": "walk_forward",
                "label": "Walk-forward windows",
                "recommended": False,
                "description": (
                    "The same rules on consecutive out-of-sample slices. "
                    "Strategies are not refit; the report shows whether the "
                    "edge holds up across the sample."
                ),
            },
            {
                "name": "compare",
                "label": "Compare strategies",
                "recommended": False,
                "description": (
                    "Run several strategies on identical bars, costs, and "
                    "sizing, then rank them by Sharpe ratio."
                ),
            },
            {
                "name": "forward",
                "label": "Forward from the latest print",
                "recommended": False,
                "description": (
                    "Replay the real tape through the latest print, then "
                    "hold the strategy's next order until a later print "
                    "arrives. Future prices are not invented."
                ),
            },
        ],
        "fill_models": [
            {
                "name": "next_open",
                "label": "Next bar open",
                "recommended": True,
                "lookahead_bias": False,
                "description": "Signal at the close, fill at the next bar's open, then apply slippage.",
            },
            {
                "name": "same_close",
                "label": "Same bar close",
                "recommended": False,
                "lookahead_bias": True,
                "description": "Optimistic fill at the signal bar's close. Reported with lookahead_bias=true.",
            },
        ],
        "sources": [
            {
                "name": "autopilot",
                "label": "Terminal AutoPilot",
                "strategies": [row["name"] for row in autopilot],
            },
            {
                "name": "algo",
                "label": "Algo trading page",
                "strategies": [row["name"] for row in algo],
            },
        ],
        "strategies": {"autopilot": autopilot, "algo": algo},
        "unsupported_on_equity_bars": list(_ALGO_UNSUPPORTED),
        "defaults": {
            "starting_cash": DEFAULT_CASH,
            "principal": DEFAULT_CASH,
            "daily_risk_pct": 2.0,
            "slippage_bps": DEFAULT_SLIPPAGE_BPS,
            "commission_per_share": 0.0,
            "risk_per_trade": 0.02,
            "max_position_size": 0.05,
            "max_open_positions": 5,
            "timeframe": "1Day",
            "adjustment": "all",
            "feed": "iex",
        },
        "limits": {
            "max_bars": MAX_BARS,
            "max_symbols": MAX_SYMBOLS,
            "max_strategies": MAX_STRATEGIES,
            "max_trades_per_day": MAX_TRADES_PER_DAY,
            "max_trading_days": MAX_TRADING_DAYS,
        },
        "data": {
            "primary": "alpaca_historical",
            "fallback": "alpha_vantage_daily",
            "orders_submitted": False,
        },
        "algo": {
            "primary": "alpaca_daily_bars",
            "fallback": None,
            "mock_data": False,
            "max_trades_per_day": MAX_TRADES_PER_DAY,
            "max_trading_days": MAX_TRADING_DAYS,
            "default_trading_days": DEFAULT_TRADING_DAYS,
            "timeframe": "trades",
            "description": (
                "Algo-page backtests replay real Alpaca daily bars, one "
                "decision per session, with the prior year available as "
                "indicator history. Charts show that same daily OHLC over "
                "one session, one week, one month, one quarter, and one year, "
                "so the annual window has the most candles. Supplied bars "
                "and Alpha Vantage are not used, and no prices are invented."
            ),
        },
        "position_model": (
            "Long-only. A buy while flat opens the position; further buys are "
            "ignored until a sell, stop, or target closes it. Dollar-cost "
            "averaging is the exception and keeps adding until max_position_size."
        ),
    }


def run_backtest_request(
    body: Optional[Dict[str, Any]],
    *,
    default_source: str = "autopilot",
    platform: Any = None,
) -> Dict[str, Any]:
    """Validate a request body and run the selected mode. Never submits orders."""
    payload = body if isinstance(body, dict) else {}
    try:
        source = str(payload.get("source") or default_source).strip().lower()
        if source not in ("autopilot", "algo"):
            raise ValueError("source must be 'autopilot' or 'algo'")
        mode = str(payload.get("mode") or "replay").strip().lower()
        if mode not in ("replay", "walk_forward", "compare", "forward"):
            raise ValueError("mode must be 'replay', 'walk_forward', 'compare', or 'forward'")
        fill_model = str(payload.get("fill_model") or "next_open").strip().lower()
        if fill_model not in ("next_open", "same_close"):
            raise ValueError("fill_model must be 'next_open' or 'same_close'")
        if mode == "forward" and fill_model != "next_open":
            raise ValueError(
                "A forward test fills on the next real print. Use fill_model 'next_open'."
            )

        raw_principal = payload.get("principal")
        if raw_principal in (None, ""):
            raw_principal = payload.get("starting_cash")
        config = BacktestConfig(
            starting_cash=_clamp_float(raw_principal, DEFAULT_CASH, 1_000.0, 100_000_000.0),
            daily_risk_pct=_clamp_float(payload.get("daily_risk_pct"), 2.0, 0.0, 25.0),
            slippage_bps=_clamp_float(payload.get("slippage_bps"), DEFAULT_SLIPPAGE_BPS, 0.0, 200.0),
            commission_per_share=_clamp_float(payload.get("commission_per_share"), 0.0, 0.0, 5.0),
            commission_bps=_clamp_float(payload.get("commission_bps"), 0.0, 0.0, 100.0),
            fill_model=fill_model,
            lookback_bars=_clamp_int(payload.get("lookback_bars"), DEFAULT_LOOKBACK, 20, 400),
            warmup_bars=_clamp_int(payload.get("warmup_bars"), DEFAULT_WARMUP, 10, 400),
            risk_per_trade=_clamp_float(payload.get("risk_per_trade"), 0.02, 0.001, 0.25),
            max_position_size=_clamp_float(payload.get("max_position_size"), 0.05, 0.01, 1.0),
            max_open_positions=_clamp_int(payload.get("max_open_positions"), 5, 1, 20),
            stop_loss_pct=_clamp_float(payload.get("stop_loss_pct"), 0.0, 0.0, 50.0),
            take_profit_pct=_clamp_float(payload.get("take_profit_pct"), 0.0, 0.0, 200.0),
            folds=_clamp_int(payload.get("folds"), 4, 2, 8),
        )
        strategies = _resolve_strategies(payload, source, mode)
        warmup_note = None
        tape_meta = None
        trading_days = None
        if source == "algo":
            for name in strategies:
                _assert_algo_strategy(name)
            if payload.get("bars"):
                raise ValueError(
                    "Algo backtests replay Alpaca daily bars only. "
                    "Supplied bars are not accepted."
                )
            raw_days = payload.get("trading_days")
            if raw_days in (None, ""):
                raw_days = payload.get("days")
            trading_days = _clamp_int(raw_days, DEFAULT_TRADING_DAYS, 1, MAX_TRADING_DAYS)
            config.max_trades_per_day = _clamp_int(
                payload.get("max_trades_per_day"), MAX_TRADES_PER_DAY, 1, MAX_TRADES_PER_DAY,
            )
            if payload.get("max_position_size") in (None, ""):
                # One position, up to the whole principal, so the reported
                # gain is the strategy's gain. Still long-only, still with slippage.
                config.max_position_size = 1.0
            symbols = _clean_symbols(payload.get("symbols") or payload.get("symbol"))
            if not symbols:
                raise ValueError("At least one symbol is required")
            if len(symbols) != 1:
                raise ValueError("Algo replay runs one symbol at a time.")
            bars_by_symbol, data_sources, tape_meta = _resolve_algo_history(
                platform, symbols, strategies,
                trading_days=trading_days,
                warmup_bars=config.warmup_bars,
                feed=str(payload.get("feed") or "iex"),
            )
            timeframe = str(tape_meta.get("timeframe") or "1Day")
            warmup_note = _fit_tape_warmup(bars_by_symbol, config)
        else:
            timeframe = str(payload.get("timeframe") or "1Day").strip() or "1Day"
            limit = _clamp_int(payload.get("limit") or payload.get("days"), 252, 30, MAX_BARS)
            symbols = _clean_symbols(payload.get("symbols") or payload.get("symbol"))
            supplied = _clean_supplied_bars(payload.get("bars"))
            if supplied:
                symbols = list(supplied.keys())[:MAX_SYMBOLS]
                supplied = {sym: supplied[sym] for sym in symbols}
            if not symbols:
                raise ValueError("At least one symbol is required")
            bars_by_symbol, data_sources = _resolve_bars(
                platform, symbols, supplied, timeframe=timeframe,
                start=payload.get("start"), end=payload.get("end"), limit=limit,
                feed=str(payload.get("feed") or "iex"),
            )
        _require_history(bars_by_symbol, config)

        if mode == "compare":
            result = _compare(bars_by_symbol, source, strategies, config)
        elif mode == "walk_forward":
            decide = _make_decide(source, strategies[0], config)
            result = _walk_forward(bars_by_symbol, decide, config)
            result["strategy"] = strategies[0]
        elif mode == "forward":
            decide = _make_decide(source, strategies[0], config)
            result = simulate(bars_by_symbol, decide, config)
            result["strategy"] = strategies[0]
            result["forward_test"] = _forward_test(result)
        else:
            decide = _make_decide(source, strategies[0], config)
            result = simulate(bars_by_symbol, decide, config)
            result["strategy"] = strategies[0]

        result.update({
            "source": source,
            "mode": mode,
            "symbols": symbols,
            "timeframe": timeframe,
            "data_sources": data_sources,
            "simulated": True,
            "orders_submitted": 0,
            "broker_orders": False,
            "fill_model": config.fill_model,
            "lookahead_bias": config.lookahead_bias,
            "slippage_bps": config.slippage_bps,
            "principal": config.starting_cash,
            "daily_risk_pct": config.daily_risk_pct,
            "daily_risk_halted_days": list(result.get("daily_risk_halted_days") or []),
            "disclaimer": (
                "Simulated replay of the live decision rules. "
                "Past results are not a prediction of live trading. "
                "No orders were submitted to Alpaca."
            ),
        })
        if source == "algo":
            meta = tape_meta or {}
            gains = _accumulated_gains(_gains_curve(result), config.starting_cash)
            result.update({
                "mock_data": False,
                "data_source": meta.get("price_path") or "alpaca_daily_bars",
                "small_trades": False,
                "small_trade_note": meta.get("note"),
                "max_trades_per_day": config.max_trades_per_day,
                "trading_days": trading_days,
                "sessions": meta.get("sessions") or [],
                "tape_trades_per_day": meta.get("tape_trades_per_day") or {},
                "truncated_days": meta.get("truncated_days") or [],
                "trades_per_day": result.get("fills_per_day") or {},
                "warmup_bars": config.warmup_bars,
                "warmup_note": warmup_note,
                "candles": meta.get("candles") or {},
                "accumulated_gains": gains,
            })
        return result
    except ValueError as exc:
        return {"error": str(exc)}


def simulate(
    bars_by_symbol: Dict[str, List[Dict[str, Any]]],
    decide: DecideFn,
    config: Optional[BacktestConfig] = None,
) -> Dict[str, Any]:
    """
    Walk aligned bars, call ``decide`` once per symbol per bar after warmup,
    and fill in a simulated account.

    ``decide`` receives ``(symbol, window, account, positions)`` and returns
    action dicts shaped like AutoPilot evaluate() (``side``, ``qty``, ``price``,
    ``reason``). ``qty`` 0 on a sell closes the position.
    """
    cfg = config or BacktestConfig()
    series = {
        sym: _normalize_series(rows)
        for sym, rows in bars_by_symbol.items()
        if rows
    }
    if not series:
        raise ValueError("No bars to replay")
    clock, by_date = _align(series)
    if len(clock) <= cfg.warmup_bars:
        raise ValueError(
            f"Need more than {cfg.warmup_bars} bars after alignment; got {len(clock)}. "
            "Request a longer window or a lower warmup_bars."
        )

    # Index windows against the aligned clock so a multi-symbol join cannot
    # point into a bar the clock skipped.
    aligned: Dict[str, List[Dict[str, Any]]] = {
        sym: [by_date[stamp][sym] for stamp in clock]
        for sym in series
    }

    cash = float(cfg.starting_cash)
    positions: Dict[str, _Position] = {}
    pending: Dict[str, Dict[str, Any]] = {}
    last_close: Dict[str, float] = {}
    trades: List[Dict[str, Any]] = []
    equity_curve: List[Dict[str, Any]] = []
    exposure_flags: List[int] = []
    fills_by_day: Dict[str, int] = {}
    session_open_equity: Dict[str, float] = {}
    risk_halted: List[str] = []

    for idx, stamp in enumerate(clock):
        todays = by_date.get(stamp, {})
        prior_close = dict(last_close)
        box = _CashBox(cash)
        for sym, bar in todays.items():
            if cfg.fill_model == "next_open" and sym in pending:
                _fill(sym, bar, pending.pop(sym), "open", box, positions, trades, cfg, fills_by_day)
            last_close[sym] = float(bar["close"])
            if sym in positions:
                reason, exit_px = _protective_exit(positions[sym], bar)
                if reason and exit_px is not None:
                    # A stop or target may close the position after the day's
                    # discretionary cap has already been reached.
                    _fill(
                        sym, bar,
                        {
                            "side": "sell",
                            "qty": positions[sym].qty,
                            "reason": reason,
                            "signal_price": exit_px,
                            "signal_date": str(bar.get("date") or stamp),
                        },
                        "stop", box, positions, trades, cfg, fills_by_day, override_price=exit_px,
                    )
        cash = box.cash

        equity = _mark(cash, positions, last_close)
        if todays:
            session_day = _session_day(next(iter(todays.values())))
            if session_day not in session_open_equity:
                # Mark the open of the session at the previous close so a
                # one-bar day (terminal) and a gap both count as loss.
                session_open_equity[session_day] = _session_open_equity(
                    cash, positions, prior_close, todays,
                )
            if _daily_risk_hit(cfg, session_open_equity[session_day], equity):
                if session_day not in risk_halted:
                    risk_halted.append(session_day)
        for sym, bar in todays.items():
            if idx < cfg.warmup_bars:
                continue
            window = _window(aligned[sym], idx, cfg.lookback_bars)
            if len(window) < 2:
                continue
            account = {
                "portfolio_value": equity,
                "equity": equity,
                "buying_power": cash,
            }
            pos_rows = [
                {"symbol": name, "qty": pos.qty, "avg_entry_price": pos.avg_price}
                for name, pos in positions.items() if pos.qty > 0
            ]
            try:
                actions = decide(sym, window, account, pos_rows) or []
            except Exception:
                logger.exception("backtest decision failed for %s at %s", sym, stamp)
                continue
            price = float(bar["close"])
            signal_stamp = str(bar.get("date") or stamp)
            if _fill_cap_reached(cfg, fills_by_day, bar):
                continue
            if _session_day(bar) in risk_halted:
                actions = [
                    action for action in actions
                    if isinstance(action, dict) and str(action.get("side") or "").lower() != "buy"
                ]
            for action in actions:
                if not isinstance(action, dict):
                    continue
                order = _prepare_order(action, sym, price, cash, equity, positions, cfg, signal_stamp)
                if order is None:
                    continue
                if cfg.fill_model == "same_close":
                    box = _CashBox(cash)
                    _fill(sym, bar, order, "close", box, positions, trades, cfg, fills_by_day)
                    cash = box.cash
                    equity = _mark(cash, positions, last_close)
                else:
                    pending[sym] = order
                break  # one action per symbol per bar

        equity = _mark(cash, positions, last_close)
        curve_date = stamp
        session = str(stamp)[:10]
        if todays:
            curve_bar = next(iter(todays.values()))
            curve_date = str(curve_bar.get("date") or stamp)
            session = _session_day(curve_bar)
        equity_curve.append({
            "date": curve_date,
            "session_date": session,
            "equity": round(equity, 2),
        })
        exposure_flags.append(1 if any(p.qty > 0 for p in positions.values()) else 0)

    # A signal on the final print has no following price. Keep it as the
    # order that waits for the next real print. Do not invent that price.
    as_of = None
    if clock:
        last_rows = by_date.get(clock[-1]) or {}
        if last_rows:
            as_of = str(next(iter(last_rows.values())).get("date") or "")
    forward_orders = [
        {
            "symbol": sym,
            "side": order.get("side"),
            "qty": order.get("qty"),
            "signal_price": order.get("signal_price"),
            "signal_date": order.get("signal_date"),
            "reason": order.get("reason") or "",
            "status": "awaiting_next_print",
        }
        for sym, order in pending.items()
    ]
    unfilled = len(forward_orders)
    ending = _mark(cash, positions, last_close)
    metrics = _metrics(equity_curve, trades, cfg.starting_cash, exposure_flags)
    metrics["benchmark_return_pct"] = _benchmark(series, cfg.warmup_bars)
    open_positions = {
        sym: {"qty": pos.qty, "avg_price": round(pos.avg_price, 4)}
        for sym, pos in positions.items() if pos.qty > 0
    }
    public_trades = []
    for trade in trades:
        row = {k: v for k, v in trade.items() if not k.startswith("_")}
        public_trades.append(row)
    return {
        "metrics": metrics,
        "equity_curve": _downsample(equity_curve, 240),
        "trades": public_trades[-200:],
        "trade_count": len([t for t in public_trades if t.get("side") in ("buy", "sell")]),
        "open_positions": open_positions,
        "ending_equity": round(ending, 2),
        "cash": round(cash, 2),
        "unfilled_signals": unfilled,
        "as_of": as_of,
        "forward_orders": forward_orders,
        "bars": len(clock),
        "fills_per_day": dict(fills_by_day),
        "max_trades_per_day": cfg.max_trades_per_day,
        "principal": cfg.starting_cash,
        "daily_risk_pct": cfg.daily_risk_pct,
        "daily_risk_halted_days": list(risk_halted),
    }


# ---------------------------------------------------------------------------
# Modes
# ---------------------------------------------------------------------------

def _forward_test(result: Dict[str, Any]) -> Dict[str, Any]:
    """The present→next-print step. The next price is not simulated."""
    return {
        "future_prices_used": False,
        "as_of": result.get("as_of"),
        "awaiting_next_print": result.get("forward_orders") or [],
        "note": (
            "Replay stops at the latest Alpaca print. "
            "An order listed here waits for the next real print. "
            "That print has not happened, so it is not filled."
        ),
    }


def _compare(
    bars_by_symbol: Dict[str, List[Dict[str, Any]]],
    source: str,
    strategies: List[str],
    config: BacktestConfig,
) -> Dict[str, Any]:
    runs = []
    for name in strategies:
        decide = _make_decide(source, name, config)
        report = simulate(bars_by_symbol, decide, config)
        report["strategy"] = name
        runs.append(_summary(report))
    ranked = sorted(
        runs,
        key=lambda row: (
            row["metrics"].get("sharpe_ratio") is not None,
            row["metrics"].get("sharpe_ratio") or -999,
            row["metrics"].get("total_return_pct") or -999,
        ),
        reverse=True,
    )
    for i, row in enumerate(ranked, start=1):
        row["rank"] = i
    return {
        "ranking": [
            {
                "rank": row["rank"],
                "strategy": row["strategy"],
                "total_return_pct": row["metrics"].get("total_return_pct"),
                "sharpe_ratio": row["metrics"].get("sharpe_ratio"),
                "max_drawdown_pct": row["metrics"].get("max_drawdown_pct"),
                "trade_count": row["trade_count"],
            }
            for row in ranked
        ],
        "runs": ranked,
    }


def _walk_forward(
    bars_by_symbol: Dict[str, List[Dict[str, Any]]],
    decide: DecideFn,
    config: BacktestConfig,
) -> Dict[str, Any]:
    series = {sym: _normalize_series(rows) for sym, rows in bars_by_symbol.items()}
    clock, _ = _align(series)
    n = len(clock)
    usable = n - config.warmup_bars
    fold_len = usable // config.folds
    if fold_len < 5:
        raise ValueError(
            f"Not enough bars for {config.folds} walk-forward folds "
            f"({usable} tradable bars). Request more history or fewer folds."
        )
    folds = []
    compound = 1.0
    for i in range(config.folds):
        test_start = config.warmup_bars + i * fold_len
        test_end = n if i == config.folds - 1 else test_start + fold_len
        slice_from = max(0, test_start - config.warmup_bars)
        if len(series) == 1:
            sym, rows = next(iter(series.items()))
            sliced = {sym: rows[slice_from:test_end]}
            start_label = str(rows[test_start].get("date"))
            end_label = str(rows[test_end - 1].get("date"))
        else:
            # Map clock stamps back onto each series by date.
            window_stamps = set(clock[slice_from:test_end])
            sliced = {}
            for sym, rows in series.items():
                piece = [bar for bar in rows if str(bar.get("date")) in window_stamps]
                if piece:
                    sliced[sym] = piece
            start_label = clock[test_start] if test_start < n else None
            end_label = clock[test_end - 1]
        report = simulate(sliced, decide, config)
        ret = report["metrics"].get("total_return_pct")
        if ret is not None:
            compound *= 1.0 + (ret / 100.0)
        folds.append({
            "fold": i + 1,
            "start": start_label,
            "end": end_label,
            "metrics": report["metrics"],
            "trade_count": report["trade_count"],
            "ending_equity": report["ending_equity"],
        })
    sharpes = [f["metrics"].get("sharpe_ratio") for f in folds if f["metrics"].get("sharpe_ratio") is not None]
    return {
        "folds": folds,
        "fold_count": len(folds),
        "stitched_return_pct": round((compound - 1.0) * 100.0, 2),
        "sharpe_min": round(min(sharpes), 3) if sharpes else None,
        "sharpe_max": round(max(sharpes), 3) if sharpes else None,
        "note": (
            "Each fold replays the same rules on a fresh account. "
            "Strategies are not refit between folds."
        ),
    }


def _summary(report: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "strategy": report.get("strategy"),
        "metrics": report.get("metrics"),
        "equity_curve": report.get("equity_curve"),
        "trade_count": report.get("trade_count"),
        "ending_equity": report.get("ending_equity"),
        "trades": (report.get("trades") or [])[-30:],
    }


# ---------------------------------------------------------------------------
# Decision adapters — live functions, no broker
# ---------------------------------------------------------------------------

def _make_decide(source: str, strategy: str, config: BacktestConfig) -> DecideFn:
    if source == "autopilot":
        return _autopilot_decide(strategy)
    return _algo_decide(strategy, config)


def _autopilot_decide(strategy_name: str) -> DecideFn:
    from services.ai_trading_engine import STRATEGY_REGISTRY, compute_technicals

    if strategy_name not in STRATEGY_REGISTRY:
        known = ", ".join(sorted(STRATEGY_REGISTRY))
        raise ValueError(f"Unknown AutoPilot strategy '{strategy_name}'. Available: {known}")
    strategy = STRATEGY_REGISTRY[strategy_name]()

    def decide(symbol, window, account, positions):
        technicals = compute_technicals(window)
        evaluation = strategy.evaluate(window, technicals, account, positions)
        actions = []
        for action in evaluation.get("actions") or []:
            if isinstance(action, dict):
                actions.append({**action, "symbol": symbol})
        return actions

    return decide


def _assert_algo_strategy(strategy_name: str) -> str:
    key = strategy_name.strip().lower()
    if key in _ALGO_UNSUPPORTED:
        raise ValueError(
            f"'{strategy_name}' needs an option chain and is not replayed on equity bars. "
            f"Use one of: {', '.join(n for n in _ALGO_METHODS if n != 'dca')}."
        )
    if key not in _ALGO_METHODS:
        known = ", ".join(n for n in _ALGO_METHODS if n != "dca")
        raise ValueError(f"Unknown algo strategy '{strategy_name}'. Available: {known}")
    return key


def _algo_decide(strategy_name: str, config: BacktestConfig) -> DecideFn:
    from services.algo_trading_service import AlgoTradingService, SignalType

    key = _assert_algo_strategy(strategy_name)
    method_name = _ALGO_METHODS[key]
    # Avoid AlgoTradingService(), which pulls live bars during init.
    service = AlgoTradingService.__new__(AlgoTradingService)
    method = getattr(service, method_name)
    accumulate = key in _ALGO_ACCUMULATE
    buy_types = {SignalType.BUY, SignalType.STRONG_BUY}
    sell_types = {SignalType.SELL, SignalType.STRONG_SELL}

    def decide(symbol, window, account, positions):
        indicators = _indicators_from_bars(service, symbol, window)
        if indicators.current_price <= 0:
            return []
        signal_type, confidence, reasoning = method(indicators)
        price = indicators.current_price
        if signal_type in buy_types:
            equity = float(account.get("portfolio_value") or config.starting_cash)
            fraction = min(0.2, config.max_position_size) if accumulate else config.max_position_size
            notional = equity * fraction
            qty = int(notional / price) if price > 0 else 0
            if qty <= 0:
                return []
            atr = float(indicators.atr_14 or 0)
            if atr <= 0:
                atr = price * 0.01
            # Trend systems keep a wide stop and no target so winners are not cut.
            # Mean-reversion systems take the profit at a measured multiple of ATR.
            runners = key in {
                "momentum", "trend_following", "breakout", "macd_crossover",
                "ai_adaptive", "dollar_cost_averaging", "dca",
                "mean_reversion", "rsi_strategy", "swing_trading", "grid_trading",
                "scalping",
            }
            order = {
                "side": "buy",
                "qty": qty,
                "price": price,
                "reason": reasoning,
                "confidence": confidence,
                "allow_add": accumulate,
                "stop_loss": round(price - (3.0 if runners else 2.0) * atr, 4),
            }
            if not runners:
                order["take_profit"] = round(price + 2.5 * atr, 4)
            return [order]
        if signal_type in sell_types:
            return [{
                "side": "sell",
                "qty": 0,
                "price": price,
                "reason": reasoning,
                "confidence": confidence,
            }]
        return []

    return decide


def _ema_series(prices: List[float], period: int) -> List[float]:
    if len(prices) < period or period <= 0:
        return []
    multiplier = 2 / (period + 1)
    ema = sum(prices[:period]) / period
    out = [ema]
    for price in prices[period:]:
        ema = (price - ema) * multiplier + ema
        out.append(ema)
    return out


def _wilder_rsi(prices: List[float], period: int = 14) -> Tuple[float, float]:
    if len(prices) < period + 1:
        return 50.0, 50.0
    gains = []
    losses = []
    for prev, price in zip(prices, prices[1:]):
        change = price - prev
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    def _rsi(gain: float, loss: float) -> float:
        if loss <= 0:
            return 100.0
        rs = gain / loss
        return 100.0 - (100.0 / (1.0 + rs))

    values = [_rsi(avg_gain, avg_loss)]
    for gain, loss in zip(gains[period:], losses[period:]):
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
        values.append(_rsi(avg_gain, avg_loss))
    if len(values) == 1:
        return values[-1], values[-1]
    return values[-1], values[-2]


def _macd_snapshot(prices: List[float]) -> Tuple[float, float, float, float]:
    """MACD line, signal, histogram, and the previous histogram.

    The signal is the EMA of the MACD series. A repeated scalar is not a signal.
    """
    ema_fast = _ema_series(prices, 12)
    ema_slow = _ema_series(prices, 26)
    if len(ema_slow) < 2 or len(ema_fast) < len(ema_slow):
        return 0.0, 0.0, 0.0, 0.0
    offset = len(ema_fast) - len(ema_slow)
    macd = [fast - slow for fast, slow in zip(ema_fast[offset:], ema_slow)]
    signal = _ema_series(macd, 9)
    if len(signal) < 2:
        return macd[-1], macd[-1], 0.0, 0.0
    aligned = macd[-len(signal):]
    hist = aligned[-1] - signal[-1]
    hist_prev = aligned[-2] - signal[-2]
    return aligned[-1], signal[-1], hist, hist_prev


def _bar_atr(bars: List[Dict[str, Any]], period: int = 14) -> float:
    prev_close = None
    true_ranges = []
    for bar in bars:
        try:
            close = float(bar.get("close") or 0)
            high = float(bar.get("high") if bar.get("high") is not None else close)
            low = float(bar.get("low") if bar.get("low") is not None else close)
        except (TypeError, ValueError):
            continue
        if close <= 0:
            continue
        if prev_close is None:
            true_range = high - low
        else:
            true_range = max(high - low, abs(high - prev_close), abs(low - prev_close))
        true_ranges.append(max(true_range, 0.0))
        prev_close = close
    if not true_ranges:
        return 0.0
    if len(true_ranges) < period:
        return sum(true_ranges) / len(true_ranges)
    atr = sum(true_ranges[:period]) / period
    for true_range in true_ranges[period:]:
        atr = (atr * (period - 1) + true_range) / period
    return atr


def _indicators_from_bars(service: Any, symbol: str, bars: List[Dict[str, Any]]):
    """Indicators for one completed bar. Support and resistance exclude this close."""
    from services.algo_trading_service import TechnicalIndicators

    prices = [float(b.get("close") or 0) for b in bars if float(b.get("close") or 0) > 0]
    highs = []
    lows = []
    for bar, close in zip(bars, prices):
        try:
            high = float(bar.get("high") if bar.get("high") is not None else close)
            low = float(bar.get("low") if bar.get("low") is not None else close)
        except (TypeError, ValueError):
            high, low = close, close
        highs.append(max(high, close))
        lows.append(min(low, close) if low > 0 else close)
    volumes = [float(b.get("volume") or 0) for b in bars]
    current = prices[-1] if prices else 0.0
    if current <= 0:
        return TechnicalIndicators(symbol=symbol, timestamp="")
    sma_20 = sum(prices[-20:]) / 20 if len(prices) >= 20 else current
    sma_50 = sum(prices[-50:]) / 50 if len(prices) >= 50 else current
    sma_200 = sum(prices[-200:]) / 200 if len(prices) >= 200 else 0.0
    ema_12 = service._calculate_ema(prices, 12)
    ema_26 = service._calculate_ema(prices, 26)
    rsi, rsi_prev = _wilder_rsi(prices, 14)
    macd_line, macd_signal, histogram, histogram_prev = _macd_snapshot(prices)
    std_20 = service._calculate_std(prices[-20:]) if len(prices) >= 20 else 0
    atr = _bar_atr(bars[-60:], 14)
    prior_prices = prices[-21:-1] if len(prices) >= 21 else prices[:-1]
    prior_highs = highs[-21:-1] if len(highs) >= 21 else highs[:-1]
    prior_lows = lows[-21:-1] if len(lows) >= 21 else lows[:-1]
    prior_high = max(prior_highs) if prior_highs else current
    prior_low = min(prior_lows) if prior_lows else current
    vol_now = volumes[-1] if volumes else 0
    vol_prev = volumes[-2] if len(volumes) >= 2 else 0
    lookback = prices[-21] if len(prices) >= 21 else (prices[0] if prices else current)
    return_20 = ((current / lookback) - 1) * 100 if lookback > 0 else 0.0
    return TechnicalIndicators(
        symbol=symbol,
        timestamp=str(bars[-1].get("date") or ""),
        current_price=current,
        price_change_24h=((current / prices[-2]) - 1) * 100 if len(prices) >= 2 and prices[-2] > 0 else 0,
        price_change_7d=return_20,
        sma_20=sma_20,
        sma_50=sma_50,
        sma_200=sma_200,
        ema_12=ema_12,
        ema_26=ema_26,
        rsi_14=rsi,
        rsi_prev=rsi_prev,
        macd_line=macd_line,
        macd_signal=macd_signal,
        macd_histogram=histogram,
        macd_histogram_prev=histogram_prev,
        bb_upper=sma_20 + (2 * std_20),
        bb_middle=sma_20,
        bb_lower=sma_20 - (2 * std_20),
        volume_24h=vol_now,
        volume_change=((vol_now / vol_prev) - 1) * 100 if vol_prev > 0 else 0,
        atr_14=atr,
        support_level=min(prior_prices) if prior_prices else current * 0.95,
        resistance_level=max(prior_prices) if prior_prices else current * 1.05,
        signal_mode="bar",
        return_20d=return_20,
        prior_high=prior_high,
        prior_low=prior_low,
        sma_50_rising=len(prices) >= 60 and sma_50 > (sum(prices[-60:-10]) / 50),
    )


# ---------------------------------------------------------------------------
# Fills
# ---------------------------------------------------------------------------

class _CashBox:
    def __init__(self, cash: float) -> None:
        self.cash = cash


def _prepare_order(
    action: Dict[str, Any],
    symbol: str,
    price: float,
    cash: float,
    equity: float,
    positions: Dict[str, _Position],
    cfg: BacktestConfig,
    stamp: str,
) -> Optional[Dict[str, Any]]:
    side = str(action.get("side") or "").lower()
    held = positions.get(symbol)
    held_qty = held.qty if held else 0
    qty = int(action.get("qty") or 0)
    if side == "sell":
        if held_qty <= 0:
            return None
        if qty <= 0:
            qty = held_qty
        qty = min(qty, held_qty)
    elif side == "buy":
        if price <= 0:
            return None
        if held_qty > 0 and not action.get("allow_add"):
            return None
        open_names = {name for name, pos in positions.items() if pos.qty > 0}
        if symbol not in open_names and len(open_names) >= cfg.max_open_positions:
            return None
        if qty <= 0:
            return None
        cap = equity * cfg.max_position_size
        held_value = held_qty * price
        room = max(0.0, cap - held_value)
        per = _buy_unit_cost(price, cfg)
        affordable = int(cash / per) if per > 0 else 0
        capped = int(room / per) if per > 0 else 0
        qty = min(qty, affordable, capped)
        if qty <= 0:
            return None
    else:
        return None

    stop = _as_float(action.get("stop_loss"))
    target = _as_float(action.get("take_profit"))
    if side == "buy" and cfg.stop_loss_pct > 0:
        stop = price * (1.0 - cfg.stop_loss_pct / 100.0)
    if side == "buy" and cfg.take_profit_pct > 0:
        target = price * (1.0 + cfg.take_profit_pct / 100.0)
    return {
        "side": side,
        "qty": qty,
        "reason": str(action.get("reason") or "")[:300],
        "confidence": action.get("confidence"),
        "signal_price": price,
        "signal_date": stamp,
        "stop_loss": stop,
        "take_profit": target,
    }


def _buy_unit_cost(price: float, cfg: BacktestConfig) -> float:
    slipped = price * (1.0 + cfg.slippage_bps / 10_000.0)
    return slipped * (1.0 + cfg.commission_bps / 10_000.0) + cfg.commission_per_share


def _session_day(bar: Dict[str, Any]) -> str:
    explicit = bar.get("session_date")
    if explicit:
        return str(explicit)[:10]
    stamp = str(bar.get("date") or "")
    if len(stamp) >= 10 and stamp[4] == "-" and stamp[7] == "-":
        return stamp[:10]
    return stamp or "session"


def _session_open_equity(
    cash: float,
    positions: Dict[str, _Position],
    prior_close: Dict[str, float],
    todays: Dict[str, Dict[str, Any]],
) -> float:
    """Equity at the start of the session, before this bar's close.

    Held names use the previous print. A name with no prior print uses this
    bar's open, so the first price in the run is not treated as a loss.
    """
    marks = dict(prior_close)
    for sym, bar in todays.items():
        if sym not in marks:
            marks[sym] = float(bar.get("open") or bar.get("close") or 0)
    return _mark(cash, positions, marks)


def _daily_risk_hit(cfg: BacktestConfig, session_open: float, equity: float) -> bool:
    """True once this session's loss reaches daily_risk_pct of the principal."""
    if cfg.daily_risk_pct <= 0 or cfg.starting_cash <= 0:
        return False
    loss = session_open - equity
    cap = cfg.starting_cash * cfg.daily_risk_pct / 100.0
    return loss >= cap - 1e-6


def _fill_cap_reached(
    cfg: BacktestConfig,
    fills_by_day: Dict[str, int],
    bar: Dict[str, Any],
) -> bool:
    cap = cfg.max_trades_per_day
    if cap is None:
        return False
    return fills_by_day.get(_session_day(bar), 0) >= cap


def _fill(
    symbol: str,
    bar: Dict[str, Any],
    order: Dict[str, Any],
    price_field: str,
    box: _CashBox,
    positions: Dict[str, _Position],
    trades: List[Dict[str, Any]],
    cfg: BacktestConfig,
    fills_by_day: Optional[Dict[str, int]] = None,
    override_price: Optional[float] = None,
) -> None:
    side = order["side"]
    qty = int(order["qty"])
    if qty <= 0:
        return
    if override_price is not None:
        raw = float(override_price)
        if side == "sell":
            raw = raw * (1.0 - cfg.slippage_bps / 10_000.0)
        else:
            raw = raw * (1.0 + cfg.slippage_bps / 10_000.0)
    else:
        raw_px = float(bar.get(price_field) or bar.get("close") or 0)
        if raw_px <= 0:
            return
        if side == "buy":
            raw = raw_px * (1.0 + cfg.slippage_bps / 10_000.0)
        else:
            raw = raw_px * (1.0 - cfg.slippage_bps / 10_000.0)
    if raw <= 0:
        return
    notional = qty * raw
    commission = qty * cfg.commission_per_share + notional * cfg.commission_bps / 10_000.0
    pnl = None
    if side == "buy":
        cost = notional + commission
        if cost > box.cash + 1e-6:
            return
        box.cash -= cost
        held = positions.get(symbol)
        if held and held.qty > 0:
            total_qty = held.qty + qty
            held.avg_price = ((held.avg_price * held.qty) + cost) / total_qty
            held.qty = total_qty
            if order.get("stop_loss"):
                held.stop = float(order["stop_loss"])
            if order.get("take_profit"):
                held.take_profit = float(order["take_profit"])
        else:
            positions[symbol] = _Position(
                qty=qty,
                avg_price=(cost / qty),
                stop=float(order["stop_loss"]) if order.get("stop_loss") else None,
                take_profit=float(order["take_profit"]) if order.get("take_profit") else None,
            )
    else:
        held = positions.get(symbol)
        if not held or held.qty <= 0:
            return
        qty = min(qty, held.qty)
        notional = qty * raw
        commission = qty * cfg.commission_per_share + notional * cfg.commission_bps / 10_000.0
        proceeds = notional - commission
        box.cash += proceeds
        pnl = proceeds - (held.avg_price * qty)
        held.qty -= qty
        if held.qty <= 0:
            positions.pop(symbol, None)
    trades.append({
        "symbol": symbol,
        "side": side,
        "qty": qty,
        "fill_price": round(raw, 6),
        "date": bar.get("date"),
        "signal_date": order.get("signal_date"),
        "signal_price": order.get("signal_price"),
        "commission": round(commission, 6),
        "reason": order.get("reason") or "",
        "confidence": order.get("confidence"),
        "pnl": round(pnl, 4) if pnl is not None else None,
        "_cash_after": box.cash,
    })
    if fills_by_day is not None:
        day = _session_day(bar)
        fills_by_day[day] = fills_by_day.get(day, 0) + 1


def _protective_exit(pos: _Position, bar: Dict[str, Any]) -> Tuple[Optional[str], Optional[float]]:
    """Stop is assumed to fill before the target when both trade in one bar."""
    low = float(bar.get("low") if bar.get("low") is not None else bar.get("close") or 0)
    high = float(bar.get("high") if bar.get("high") is not None else bar.get("close") or 0)
    open_px = float(bar.get("open") if bar.get("open") is not None else bar.get("close") or 0)
    stop_hit = pos.stop is not None and low <= pos.stop
    target_hit = pos.take_profit is not None and high >= pos.take_profit
    if stop_hit:
        level = float(pos.stop)
        # A gap through the stop fills at the open, which is worse.
        price = open_px if open_px < level else level
        return "stop_loss", price
    if target_hit:
        level = float(pos.take_profit)
        price = open_px if open_px > level else level
        return "take_profit", price
    return None, None


# ---------------------------------------------------------------------------
# Bars, metrics
# ---------------------------------------------------------------------------

def _resolve_bars(
    platform: Any,
    symbols: List[str],
    supplied: Dict[str, List[Dict[str, Any]]],
    *,
    timeframe: str,
    start: Any,
    end: Any,
    limit: int,
    feed: str,
) -> Tuple[Dict[str, List[Dict[str, Any]]], Dict[str, str]]:
    bars: Dict[str, List[Dict[str, Any]]] = {}
    sources: Dict[str, str] = {}
    if supplied:
        for sym in symbols:
            rows = supplied.get(sym) or []
            if not rows:
                raise ValueError(f"No supplied bars for {sym}")
            bars[sym] = rows[-MAX_BARS:]
            sources[sym] = "supplied"
        return bars, sources

    missing: List[str] = []
    for sym in symbols:
        rows, source = _load_symbol_bars(
            platform, sym, timeframe=timeframe, start=start, end=end, limit=limit, feed=feed,
        )
        if not rows:
            missing.append(sym)
            continue
        bars[sym] = rows[-MAX_BARS:]
        sources[sym] = source
    if missing and not bars:
        detail = ""
        last = getattr(platform, "_last_data_error", None) if platform is not None else None
        if last:
            detail = f" {last}"
        elif platform is None or not getattr(platform, "is_connected", False):
            detail = " Alpaca is not connected (set ALPACA_API_KEY and ALPACA_SECRET_KEY)."
        raise ValueError(f"No historical bars for {', '.join(missing)}.{detail}")
    if missing:
        raise ValueError(f"No historical bars for {', '.join(missing)}.")
    return bars, sources


def _resolve_algo_history(
    platform: Any,
    symbols: List[str],
    strategies: List[str],
    *,
    trading_days: int,
    warmup_bars: int,
    feed: str,
) -> Tuple[Dict[str, List[Dict[str, Any]]], Dict[str, str], Dict[str, Any]]:
    """Load real Alpaca OHLC for one symbol. Never synthesizes prices."""
    sym = symbols[0]
    if platform is None or not getattr(platform, "is_connected", False):
        raise ValueError(
            f"No Alpaca bars for {sym}. Alpaca is not connected "
            "(set ALPACA_API_KEY and ALPACA_SECRET_KEY)."
        )
    feed_name = feed if feed in ("iex", "sip") else "iex"
    # The scored window and the indicator warmup both come out of this fetch,
    # and the candle charts still want a year of sessions behind them.
    daily_limit = min(max(MAX_TRADING_DAYS, trading_days + warmup_bars), MAX_BARS)
    daily = _safe_historical_bars(platform, sym, "1Day", daily_limit, feed_name)
    intraday = len(strategies) == 1 and strategies[0] in _INTRADAY_STRATEGIES
    note = (
        "Decisions use completed Alpaca bars. One signal per bar, filled at the next open. "
        "The annual chart is a year of those daily candles; the daily chart is the latest session."
    )
    rows = daily
    source_name = "alpaca_daily_bars"
    timeframe = "1Day"
    # Daily bars are one per session, so the window is a bar count.
    play = rows[-(trading_days + warmup_bars):]
    if intraday:
        minutes = _safe_historical_bars(platform, sym, "1Min", MAX_BARS, feed_name)
        five = _resample_minutes(minutes, 5) if minutes else []
        # trading_days counts sessions, not 5-minute bars, so the intraday tape
        # is sliced by session and is only used when it covers the request.
        intraday_play = _session_window(five, trading_days, warmup_bars)
        if intraday_play:
            rows = five
            play = intraday_play
            source_name = "alpaca_5min"
            timeframe = "5Min"
            note = (
                "Scalping and grid replay real 5-minute Alpaca bars resampled from 1-minute bars. "
                "No prices were interpolated."
            )
        elif daily:
            note = (
                "Intraday Alpaca bars were too short for this strategy, so the replay used "
                "real daily bars. No prices were invented."
            )
    if not rows:
        last = getattr(platform, "_last_data_error", None)
        detail = f" {last}" if last else " The feed returned no bars."
        raise ValueError(f"No Alpaca bars for {sym}.{detail} No prices were invented.")
    history = _daily_ohlc(daily or rows)
    if len(play) < 20:
        raise ValueError(
            f"{sym} returned {len(play)} Alpaca bars. "
            "A strategy replay needs at least 20. No prices were invented."
        )
    meta = {
        "tape_trades_per_day": {},
        "truncated_days": [],
        "sessions": _session_list(play),
        "price_path": source_name,
        "small_trades": False,
        "timeframe": timeframe,
        "note": note,
        "candles": _build_candles(history or play),
    }
    return {sym: play}, {sym: source_name}, meta


_NY = ZoneInfo("America/New_York")
_CANDLE_FRAMES = ("day", "week", "month", "quarter", "year")


def _safe_historical_bars(platform: Any, symbol: str, timeframe: str, limit: int, feed: str) -> List[Dict[str, Any]]:
    loader = getattr(platform, "get_historical_bars", None)
    if not callable(loader):
        return []
    try:
        rows = loader(
            symbol,
            timeframe=timeframe,
            start=None,
            end=None,
            limit=limit,
            feed=feed if feed in ("iex", "sip") else "iex",
        ) or []
    except Exception:
        logger.debug("Alpaca %s bars unavailable for %s", timeframe, symbol, exc_info=True)
        return []
    return rows if isinstance(rows, list) else []



def _session_list(prints: List[Dict[str, Any]]) -> List[str]:
    days: List[str] = []
    for row in prints:
        day = _session_day(row)
        if day not in days:
            days.append(day)
    return days


def _session_window(
    rows: List[Dict[str, Any]],
    sessions: int,
    warmup_bars: int,
) -> List[Dict[str, Any]]:
    """The last ``sessions`` sessions of intraday bars plus the warmup before them.

    Empty when the tape does not reach that many sessions or cannot cover the
    warmup, so the caller falls back to daily bars instead of scoring a shorter
    window than the request asked for.
    """
    if sessions <= 0:
        return []
    days = _session_list(rows)
    if len(days) < sessions:
        return []
    first = days[-sessions]
    start = next((i for i, row in enumerate(rows) if _session_day(row) == first), None)
    if start is None or start < warmup_bars:
        return []
    return rows[start - warmup_bars:]


def _bar_session(row: Dict[str, Any]) -> str:
    if row.get("session_date"):
        return str(row["session_date"])[:10]
    return _session_from_stamp(str(row.get("date") or row.get("t") or ""))


def _session_from_stamp(stamp: str) -> str:
    text = (stamp or "").strip()
    if "T" in text:
        try:
            moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
            if moment.tzinfo is None:
                moment = moment.replace(tzinfo=timezone.utc)
            return moment.astimezone(_NY).date().isoformat()
        except ValueError:
            pass
    return text[:10]



def _daily_ohlc(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """One candle per session from real OHLC. Later rows in a session update the close."""
    daily: Dict[str, Dict[str, Any]] = {}
    order: List[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            close = float(row.get("close") if row.get("close") is not None else row.get("c"))
        except (TypeError, ValueError):
            continue
        if not math.isfinite(close) or close <= 0:
            continue
        day = _bar_session(row)
        if len(day) < 10:
            continue

        def _px(key: str, alt: str) -> float:
            raw = row.get(key) if row.get(key) is not None else row.get(alt)
            try:
                value = float(raw)
            except (TypeError, ValueError):
                return close
            if not math.isfinite(value) or value <= 0:
                return close
            return value

        open_px = _px("open", "o")
        high_px = max(_px("high", "h"), open_px, close)
        low_px = min(_px("low", "l"), open_px, close)
        try:
            volume = float(row.get("volume") if row.get("volume") is not None else (row.get("v") or 0))
        except (TypeError, ValueError):
            volume = 0.0
        bucket = daily.get(day)
        if bucket is None:
            daily[day] = {
                "date": day,
                "open": open_px,
                "high": high_px,
                "low": low_px,
                "close": close,
                "volume": volume,
            }
            order.append(day)
        else:
            bucket["high"] = max(bucket["high"], high_px)
            bucket["low"] = min(bucket["low"], low_px)
            bucket["close"] = close
            bucket["volume"] = float(bucket["volume"]) + volume
    return [daily[day] for day in order]


def _build_candles(rows: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """Windows of daily candles: 1 session, 5, 21, 63, and 252.

    Every frame is the same real daily OHLC. The annual window is the long
    one, so it holds more candles than the daily window.
    """
    day_rows = rows if rows and all(isinstance(r, dict) and len(str(r.get("date") or "")) == 10 for r in rows) else _daily_ohlc(rows)
    # Rows that are already one-per-day keep their OHLC. Mixed stamps are rolled first.
    if rows and any(len(str(r.get("date") or "")) > 10 for r in rows if isinstance(r, dict)):
        day_rows = _daily_ohlc(rows)
    frames = {}
    for name, count in CHART_WINDOWS:
        frames[name] = [dict(row) for row in day_rows[-count:]]
    return frames


def _resample_minutes(rows: List[Dict[str, Any]], minutes: int) -> List[Dict[str, Any]]:
    """Bucket real minute bars. The bucket OHLC is only those bars' prices."""
    buckets: Dict[str, Dict[str, Any]] = {}
    order: List[str] = []
    span = max(1, int(minutes))
    for row in rows:
        if not isinstance(row, dict):
            continue
        stamp = str(row.get("date") or row.get("t") or "")
        try:
            close = float(row.get("close") if row.get("close") is not None else row.get("c"))
        except (TypeError, ValueError):
            continue
        if not math.isfinite(close) or close <= 0 or "T" not in stamp:
            continue
        try:
            moment = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        except ValueError:
            continue
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        local = moment.astimezone(_NY)
        floored = local.replace(minute=(local.minute // span) * span, second=0, microsecond=0)
        key = floored.isoformat()
        high = float(row.get("high") if row.get("high") is not None else close)
        low = float(row.get("low") if row.get("low") is not None else close)
        open_px = float(row.get("open") if row.get("open") is not None else close)
        try:
            volume = float(row.get("volume") or 0)
        except (TypeError, ValueError):
            volume = 0.0
        bucket = buckets.get(key)
        if bucket is None:
            buckets[key] = {
                "date": floored.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
                "session_date": local.date().isoformat(),
                "open": open_px,
                "high": max(high, open_px, close),
                "low": min(low, open_px, close),
                "close": close,
                "volume": volume,
            }
            order.append(key)
        else:
            bucket["high"] = max(bucket["high"], high, close)
            bucket["low"] = min(bucket["low"], low, close)
            bucket["close"] = close
            bucket["volume"] = float(bucket["volume"]) + volume
    return [buckets[key] for key in order]



def _gains_curve(result: Dict[str, Any]) -> List[Dict[str, Any]]:
    curve = result.get("equity_curve")
    if curve:
        return curve
    if result.get("ranking") and result.get("runs"):
        winner = result["ranking"][0].get("strategy")
        for run in result["runs"]:
            if run.get("strategy") == winner and run.get("equity_curve"):
                return run["equity_curve"]
    folds = result.get("folds") or []
    points = []
    for fold in folds:
        equity = fold.get("ending_equity")
        if equity is None:
            continue
        points.append({"date": fold.get("end") or fold.get("start"), "equity": equity})
    return points


def _accumulated_gains(curve: List[Dict[str, Any]], starting_cash: float) -> List[Dict[str, Any]]:
    start = float(starting_cash or 0)
    gains = []
    for point in curve or []:
        try:
            equity = float(point.get("equity"))
        except (TypeError, ValueError):
            continue
        gain = equity - start
        gain_pct = ((equity / start) - 1.0) * 100.0 if start else 0.0
        gains.append({
            "date": point.get("date"),
            "equity": round(equity, 2),
            "gain": round(gain, 2),
            "gain_pct": round(gain_pct, 2),
        })
    return gains


def _fit_tape_warmup(
    bars_by_symbol: Dict[str, List[Dict[str, Any]]],
    config: BacktestConfig,
) -> Optional[str]:
    """Lower warmup when the real bar history is shorter than the default."""
    sym = min(bars_by_symbol, key=lambda name: len(bars_by_symbol[name]))
    shortest = len(bars_by_symbol[sym])
    if shortest > config.warmup_bars:
        return None
    if shortest < MIN_TAPE_PRINTS:
        raise ValueError(
            f"{sym} returned {shortest} Alpaca bars. "
            f"A replay needs at least {MIN_TAPE_PRINTS}. "
            "No prices were invented."
        )
    lowered = max(10, shortest // 3)
    if lowered >= shortest:
        lowered = shortest - 1
    config.warmup_bars = lowered
    return (
        f"Warmup lowered to {lowered} because {sym} has {shortest} real bars "
        "in the requested sessions."
    )


def _load_symbol_bars(
    platform: Any,
    symbol: str,
    *,
    timeframe: str,
    start: Any,
    end: Any,
    limit: int,
    feed: str,
) -> Tuple[List[Dict[str, Any]], str]:
    if platform is not None and getattr(platform, "is_connected", False):
        loader = getattr(platform, "get_historical_bars", None)
        if callable(loader):
            rows = loader(
                symbol,
                timeframe=timeframe,
                start=str(start) if start else None,
                end=str(end) if end else None,
                limit=limit,
                feed=feed if feed in ("iex", "sip") else "iex",
            ) or []
            if rows:
                return rows, "alpaca"
    daily = timeframe.lower() in ("1day", "1d", "day", "d")
    fallback = getattr(platform, "_bars_from_alpha_vantage", None) if platform is not None else None
    if daily and callable(fallback):
        rows, weekly = fallback(symbol, limit)
        if rows:
            return rows, "alpha_vantage_weekly" if weekly else "alpha_vantage"
    return [], "none"


def _require_history(bars_by_symbol: Dict[str, List[Dict[str, Any]]], cfg: BacktestConfig) -> None:
    for sym, rows in bars_by_symbol.items():
        if len(rows) <= cfg.warmup_bars:
            raise ValueError(
                f"{sym} has {len(rows)} bars; warmup is {cfg.warmup_bars}. "
                "Use a longer date range or lower warmup_bars."
            )


def _resolve_strategies(payload: Dict[str, Any], source: str, mode: str) -> List[str]:
    if mode == "compare":
        raw = payload.get("strategies")
        if not raw:
            raw = _default_compare_set(source)
        if isinstance(raw, str):
            raw = [part.strip() for part in raw.split(",") if part.strip()]
        names = [str(name).strip() for name in raw if str(name).strip()]
        if not names:
            raise ValueError("compare mode needs at least one strategy")
        if len(names) > MAX_STRATEGIES:
            names = names[:MAX_STRATEGIES]
        return names
    name = str(payload.get("strategy") or "").strip()
    if not name:
        name = "momentum"
    return [name]


def _default_compare_set(source: str) -> List[str]:
    if source == "autopilot":
        from services.ai_trading_engine import STRATEGY_REGISTRY
        preferred = ["momentum", "mean_reversion", "breakout", "macro_sentiment"]
        return [name for name in preferred if name in STRATEGY_REGISTRY][:MAX_STRATEGIES]
    return ["momentum", "mean_reversion", "rsi_strategy", "macd_crossover"]


def _clean_symbols(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        parts = [part.strip().upper() for part in value.split(",")]
    elif isinstance(value, list):
        parts = [str(part).strip().upper() for part in value]
    else:
        raise ValueError("symbols must be a list or a comma-separated string")
    out = []
    for sym in parts:
        if not sym:
            continue
        if not _SYMBOL_RE.match(sym):
            raise ValueError(f"Invalid symbol '{sym}'")
        if sym not in out:
            out.append(sym)
    if len(out) > MAX_SYMBOLS:
        raise ValueError(f"At most {MAX_SYMBOLS} symbols per backtest")
    return out


def _clean_supplied_bars(value: Any) -> Dict[str, List[Dict[str, Any]]]:
    if not value:
        return {}
    if not isinstance(value, dict):
        raise ValueError("bars must be an object keyed by symbol")
    cleaned: Dict[str, List[Dict[str, Any]]] = {}
    for raw_sym, rows in value.items():
        sym = str(raw_sym).strip().upper()
        if not _SYMBOL_RE.match(sym):
            raise ValueError(f"Invalid symbol '{sym}'")
        if not isinstance(rows, list) or not rows:
            raise ValueError(f"bars.{sym} must be a non-empty list")
        if len(rows) > MAX_BARS:
            rows = rows[-MAX_BARS:]
        normalized = []
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError(f"bars.{sym} contains a non-object row")
            bar = _normalize_bar(row, fallback_index=len(normalized))
            if bar is None:
                raise ValueError(f"bars.{sym} has a row without a positive close")
            normalized.append(bar)
        cleaned[sym] = normalized
    return cleaned


def _normalize_series(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for i, row in enumerate(rows):
        bar = _normalize_bar(row, fallback_index=i)
        if bar is not None:
            out.append(bar)
    out.sort(key=lambda bar: str(bar.get("date") or ""))
    return out


def _normalize_bar(row: Dict[str, Any], fallback_index: int) -> Optional[Dict[str, Any]]:
    try:
        close = float(row.get("close") if row.get("close") is not None else row.get("c"))
    except (TypeError, ValueError):
        return None
    if not math.isfinite(close) or close <= 0:
        return None

    def _px(key: str, alt: str) -> float:
        raw = row.get(key) if row.get(key) is not None else row.get(alt)
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return close
        if not math.isfinite(value) or value <= 0:
            return close
        return value

    date = row.get("date") or row.get("t") or f"bar-{fallback_index:05d}"
    bar = {
        "date": str(date),
        "open": _px("open", "o"),
        "high": _px("high", "h"),
        "low": _px("low", "l"),
        "close": close,
        "volume": row.get("volume") if row.get("volume") is not None else (row.get("v") or 0),
    }
    if row.get("session_date"):
        bar["session_date"] = str(row["session_date"])[:10]
    return bar


def _align(
    series: Dict[str, List[Dict[str, Any]]],
) -> Tuple[List[str], Dict[str, Dict[str, Dict[str, Any]]]]:
    """Inner-join symbols on bar date. A single symbol keeps every print."""
    if len(series) == 1:
        # Trade prints can share a timestamp. Key the clock by position so
        # a second print at the same instant is not dropped.
        sym, rows = next(iter(series.items()))
        clock = [f"{i:08d}" for i in range(len(rows))]
        by_date = {clock[i]: {sym: rows[i]} for i in range(len(rows))}
        return clock, by_date
    sets = []
    maps = {}
    for sym, rows in series.items():
        mapping = {str(bar["date"]): bar for bar in rows}
        maps[sym] = mapping
        sets.append(set(mapping))
    common = set.intersection(*sets) if sets else set()
    clock = sorted(common)
    by_date: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for stamp in clock:
        by_date[stamp] = {sym: maps[sym][stamp] for sym in series}
    return clock, by_date


def _window(rows: List[Dict[str, Any]], index: int, lookback: int) -> List[Dict[str, Any]]:
    start = max(0, index + 1 - lookback)
    return rows[start:index + 1]


def _mark(cash: float, positions: Dict[str, _Position], last_close: Dict[str, float]) -> float:
    equity = cash
    for sym, pos in positions.items():
        px = last_close.get(sym) or pos.avg_price
        equity += pos.qty * px
    return equity


def _metrics(
    curve: List[Dict[str, Any]],
    trades: List[Dict[str, Any]],
    starting_cash: float,
    exposure_flags: List[int],
) -> Dict[str, Any]:
    equities = [float(point["equity"]) for point in curve if point.get("equity") is not None]
    ending = equities[-1] if equities else starting_cash
    total_return = (ending / starting_cash - 1.0) if starting_cash else 0.0
    rets = []
    for prev, nxt in zip(equities, equities[1:]):
        if prev > 0:
            rets.append(nxt / prev - 1.0)
    per_year = _periods_per_year(curve)
    sharpe = _ratio(rets, downside=False, periods_per_year=per_year)
    sortino = _ratio(rets, downside=True, periods_per_year=per_year)
    max_dd = _max_drawdown(equities)
    periods = max(len(rets), 1)
    cagr = None
    if starting_cash > 0 and ending > 0 and periods >= 1:
        cagr = (ending / starting_cash) ** (per_year / periods) - 1.0
    calmar = None
    if cagr is not None and max_dd > 1e-9:
        calmar = cagr / max_dd
    closed = [t for t in trades if t.get("side") == "sell" and t.get("pnl") is not None]
    wins = [t for t in closed if float(t["pnl"]) > 0]
    losses = [t for t in closed if float(t["pnl"]) < 0]
    gross_win = sum(float(t["pnl"]) for t in wins)
    gross_loss = abs(sum(float(t["pnl"]) for t in losses))
    profit_factor = (gross_win / gross_loss) if gross_loss > 1e-9 else None
    exposure = (sum(exposure_flags) / len(exposure_flags)) if exposure_flags else 0.0
    return {
        "starting_equity": round(starting_cash, 2),
        "ending_equity": round(ending, 2),
        "total_return_pct": round(total_return * 100.0, 2),
        "cagr_pct": round(cagr * 100.0, 2) if cagr is not None else None,
        "sharpe_ratio": round(sharpe, 3) if sharpe is not None else None,
        "sortino_ratio": round(sortino, 3) if sortino is not None else None,
        "max_drawdown_pct": round(max_dd * 100.0, 2),
        "calmar_ratio": round(calmar, 3) if calmar is not None else None,
        "win_rate_pct": round(100.0 * len(wins) / len(closed), 1) if closed else None,
        "profit_factor": round(profit_factor, 3) if profit_factor is not None else None,
        "closed_trades": len(closed),
        "avg_win": round(gross_win / len(wins), 2) if wins else None,
        "avg_loss": round(-gross_loss / len(losses), 2) if losses else None,
        "exposure_pct": round(exposure * 100.0, 1),
    }


def _periods_per_year(curve: List[Dict[str, Any]]) -> float:
    """
    Annualization factor for whatever the curve is sampled at.

    Daily bars leave one point per session, so the factor stays 252. A trade
    tape leaves thousands of points on the same session; scaling by the points
    per session keeps CAGR, Sharpe, and Sortino on an annual footing instead of
    reading every print as a trading day.
    """
    sessions = {_session_day(point) for point in curve if point.get("date")}
    if not sessions or len(curve) <= len(sessions):
        return 252.0
    return 252.0 * (len(curve) / len(sessions))


def _ratio(rets: List[float], downside: bool, periods_per_year: float = 252.0) -> Optional[float]:
    if len(rets) < 5:
        return None
    mean = sum(rets) / len(rets)
    if downside:
        neg = [r for r in rets if r < 0]
        if len(neg) < 2:
            return None
        var = sum(r * r for r in neg) / len(neg)
    else:
        var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    if var <= 0:
        return None
    return (mean / math.sqrt(var)) * math.sqrt(periods_per_year)


def _max_drawdown(equities: List[float]) -> float:
    peak = equities[0] if equities else 0.0
    worst = 0.0
    for equity in equities:
        if equity > peak:
            peak = equity
        if peak > 0:
            worst = max(worst, (peak - equity) / peak)
    return worst


def _benchmark(series: Dict[str, List[Dict[str, Any]]], warmup: int) -> Optional[float]:
    rets = []
    for rows in series.values():
        if len(rows) <= warmup:
            continue
        start = float(rows[warmup]["close"])
        end = float(rows[-1]["close"])
        if start > 0:
            rets.append(end / start - 1.0)
    if not rets:
        return None
    return round(100.0 * sum(rets) / len(rets), 2)


def _downsample(points: List[Dict[str, Any]], cap: int) -> List[Dict[str, Any]]:
    if len(points) <= cap:
        return points
    step = max(1, len(points) // cap)
    sampled = points[::step]
    if sampled[-1] is not points[-1]:
        sampled.append(points[-1])
    return sampled


def _algo_blurb(name: str) -> str:
    blurbs = {
        "rsi_strategy": "Buy an RSI dip only while price is above the 50-day average.",
        "macd_crossover": "Buy a MACD histogram cross above zero in an uptrend.",
        "momentum": "Stay long while the 20-session return is positive and price holds the 50-day average.",
        "mean_reversion": "Buy the lower Bollinger Band in an uptrend and exit at the middle band.",
        "trend_following": "Stay long while the 20-day average is above the 50-day average.",
        "breakout": "Buy a close through the prior 20-session high. Exit through the prior 20-session low.",
        "ai_adaptive": "Stay long only when trend and momentum agree.",
        "dollar_cost_averaging": "Add while the 20-day average is not below the 50-day average.",
        "scalping": "Take with-trend closes and exit under the 20-period average.",
        "swing_trading": "Buy a dip that is still above the 50-day average.",
        "grid_trading": "Buy weakness inside the prior range only while the trend is up.",
    }
    return blurbs.get(name, name)


def _clamp_float(value: Any, default: float, lo: float, hi: float) -> float:
    if value is None or value == "":
        return default
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"Expected a number, got {value!r}")
    if not math.isfinite(number):
        raise ValueError("Numeric fields must be finite")
    return min(hi, max(lo, number))


def _clamp_int(value: Any, default: int, lo: int, hi: int) -> int:
    if value is None or value == "":
        return default
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"Expected an integer, got {value!r}")
    return min(hi, max(lo, number))


def _as_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number <= 0:
        return None
    return number
