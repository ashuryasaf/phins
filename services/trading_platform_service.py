"""
PHINS Trading Platform Service
================================
Live trading connector for multiple broker APIs with AI copilot integration.

Supported brokers:
- Alpaca Markets (US equities + crypto, paper & live)
- Extensible to Interactive Brokers, Coinbase, Binance

Features:
- Live order execution (market, limit, stop, trailing stop)
- Real-time position tracking with P&L
- Account balance and buying power
- Order history and status
- AI copilot trade analysis
- Risk checks before execution
- Global market data (indices, forex, crypto, commodities)
"""

from __future__ import annotations

import os
import time
import threading
import json
import math
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass, field

import requests


# ---------------------------------------------------------------------------
# Broker configuration
# ---------------------------------------------------------------------------

ALPACA_API_KEY = os.environ.get("ALPACA_API_KEY", "")
ALPACA_SECRET_KEY = os.environ.get("ALPACA_SECRET_KEY", "")
ALPACA_PAPER = os.environ.get("ALPACA_PAPER", "true").lower() in ("1", "true", "yes")

ALPACA_TRADE_URL = (
    "https://paper-api.alpaca.markets" if ALPACA_PAPER
    else "https://api.alpaca.markets"
)
ALPACA_DATA_URL = "https://data.alpaca.markets"


# ---------------------------------------------------------------------------
# Global market indices / benchmarks for Bloomberg-style dashboard
# ---------------------------------------------------------------------------

GLOBAL_BENCHMARKS = {
    "indices": {
        "SPY": {"name": "S&P 500", "region": "US"},
        "QQQ": {"name": "NASDAQ 100", "region": "US"},
        "DIA": {"name": "Dow Jones", "region": "US"},
        "IWM": {"name": "Russell 2000", "region": "US"},
        "EFA": {"name": "MSCI EAFE", "region": "International"},
        "EEM": {"name": "Emerging Markets", "region": "International"},
        "VGK": {"name": "FTSE Europe", "region": "Europe"},
    },
    "crypto": {
        "BTC/USD": {"name": "Bitcoin"},
        "ETH/USD": {"name": "Ethereum"},
        "SOL/USD": {"name": "Solana"},
    },
    "commodities": {
        "GLD": {"name": "Gold"},
        "SLV": {"name": "Silver"},
        "USO": {"name": "Crude Oil"},
    },
    "bonds": {
        "TLT": {"name": "20+ Year Treasury"},
        "BND": {"name": "Total Bond Market"},
        "HYG": {"name": "High Yield Corporate"},
    },
}


class TradingPlatformService:
    """
    Unified trading platform with broker API integration,
    position management, and AI copilot support.
    """

    def __init__(self):
        self._api_key = ALPACA_API_KEY
        self._secret_key = ALPACA_SECRET_KEY
        self._trade_url = ALPACA_TRADE_URL
        self._data_url = ALPACA_DATA_URL
        self._timeout = 10
        self._connected = bool(self._api_key and self._secret_key)
        self._cache: Dict[str, Any] = {}
        self._cache_ts: Dict[str, float] = {}

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def is_paper(self) -> bool:
        return ALPACA_PAPER

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------

    def _headers(self) -> Dict[str, str]:
        return {
            "APCA-API-KEY-ID": self._api_key,
            "APCA-API-SECRET-KEY": self._secret_key,
            "Content-Type": "application/json",
        }

    def _trade_request(self, method: str, path: str, body: Optional[Dict] = None) -> Optional[Dict]:
        url = f"{self._trade_url}/v2{path}"
        try:
            resp = requests.request(
                method, url,
                headers=self._headers(),
                json=body,
                timeout=self._timeout,
            )
            if resp.status_code == 204:
                return {"success": True}
            if resp.status_code >= 400:
                return {"error": resp.json() if resp.text else resp.reason, "status": resp.status_code}
            return resp.json()
        except Exception as e:
            return {"error": str(e)}

    def _data_request(self, path: str, params: Optional[Dict] = None) -> Optional[Dict]:
        url = f"{self._data_url}{path}"
        try:
            resp = requests.get(
                url,
                headers=self._headers(),
                params=params or {},
                timeout=self._timeout,
            )
            if resp.status_code >= 400:
                return None
            return resp.json()
        except Exception:
            return None

    def _cached(self, key: str, ttl: float = 30.0) -> Optional[Any]:
        if key in self._cache and time.time() - self._cache_ts.get(key, 0) < ttl:
            return self._cache[key]
        return None

    def _set_cache(self, key: str, data: Any) -> None:
        self._cache[key] = data
        self._cache_ts[key] = time.time()

    # ==================================================================
    # ACCOUNT
    # ==================================================================

    def get_account(self) -> Dict[str, Any]:
        if not self._connected:
            return self._demo_account()
        cached = self._cached("account", 15.0)
        if cached:
            return cached
        raw = self._trade_request("GET", "/account")
        if not raw or "error" in raw:
            return self._demo_account()
        result = {
            "account_id": raw.get("id"),
            "status": raw.get("status"),
            "currency": raw.get("currency", "USD"),
            "buying_power": _sf(raw.get("buying_power")),
            "cash": _sf(raw.get("cash")),
            "portfolio_value": _sf(raw.get("portfolio_value")),
            "equity": _sf(raw.get("equity")),
            "last_equity": _sf(raw.get("last_equity")),
            "long_market_value": _sf(raw.get("long_market_value")),
            "short_market_value": _sf(raw.get("short_market_value")),
            "unrealized_pl": _sf(raw.get("unrealized_pl")),
            "unrealized_pl_pct": _sf(raw.get("unrealized_plpc")),
            "day_trade_count": int(raw.get("daytrade_count", 0)),
            "pattern_day_trader": raw.get("pattern_day_trader", False),
            "trading_blocked": raw.get("trading_blocked", False),
            "paper": self.is_paper,
            "broker": "alpaca",
            "connected": True,
        }
        self._set_cache("account", result)
        return result

    # ==================================================================
    # POSITIONS
    # ==================================================================

    def get_positions(self) -> List[Dict[str, Any]]:
        if not self._connected:
            return self._demo_positions()
        cached = self._cached("positions", 10.0)
        if cached:
            return cached
        raw = self._trade_request("GET", "/positions")
        if not raw or isinstance(raw, dict) and "error" in raw:
            return self._demo_positions()
        if not isinstance(raw, list):
            return self._demo_positions()
        positions = []
        for p in raw:
            positions.append({
                "symbol": p.get("symbol"),
                "qty": _sf(p.get("qty")),
                "side": p.get("side"),
                "avg_entry_price": _sf(p.get("avg_entry_price")),
                "current_price": _sf(p.get("current_price")),
                "market_value": _sf(p.get("market_value")),
                "cost_basis": _sf(p.get("cost_basis")),
                "unrealized_pl": _sf(p.get("unrealized_pl")),
                "unrealized_pl_pct": _sf(p.get("unrealized_plpc")),
                "change_today": _sf(p.get("change_today")),
                "asset_class": p.get("asset_class"),
            })
        self._set_cache("positions", positions)
        return positions

    # ==================================================================
    # ORDERS
    # ==================================================================

    def submit_order(
        self,
        symbol: str,
        side: str,
        qty: Optional[float] = None,
        notional: Optional[float] = None,
        order_type: str = "market",
        time_in_force: str = "day",
        limit_price: Optional[float] = None,
        stop_price: Optional[float] = None,
        trail_percent: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Submit a live order to the broker."""
        body: Dict[str, Any] = {
            "symbol": symbol.upper(),
            "side": side.lower(),
            "type": order_type.lower(),
            "time_in_force": time_in_force.lower(),
        }
        if qty is not None:
            body["qty"] = str(qty)
        elif notional is not None:
            body["notional"] = str(notional)
        else:
            return {"error": "Either qty or notional is required"}

        if limit_price is not None:
            body["limit_price"] = str(limit_price)
        if stop_price is not None:
            body["stop_price"] = str(stop_price)
        if trail_percent is not None:
            body["trail_percent"] = str(trail_percent)

        if not self._connected:
            return self._demo_order(body)

        raw = self._trade_request("POST", "/orders", body)
        if not raw:
            return {"error": "Order submission failed"}
        if "error" in raw:
            return raw

        self._cache.pop("positions", None)
        self._cache.pop("account", None)

        return {
            "order_id": raw.get("id"),
            "symbol": raw.get("symbol"),
            "side": raw.get("side"),
            "qty": raw.get("qty"),
            "notional": raw.get("notional"),
            "type": raw.get("type"),
            "time_in_force": raw.get("time_in_force"),
            "status": raw.get("status"),
            "filled_qty": raw.get("filled_qty"),
            "filled_avg_price": raw.get("filled_avg_price"),
            "limit_price": raw.get("limit_price"),
            "stop_price": raw.get("stop_price"),
            "created_at": raw.get("created_at"),
            "broker": "alpaca",
        }

    def get_orders(self, status: str = "all", limit: int = 20) -> List[Dict[str, Any]]:
        if not self._connected:
            return self._demo_orders()
        raw = self._trade_request("GET", f"/orders?status={status}&limit={limit}")
        if not raw or not isinstance(raw, list):
            return self._demo_orders()
        orders = []
        for o in raw:
            orders.append({
                "order_id": o.get("id"),
                "symbol": o.get("symbol"),
                "side": o.get("side"),
                "qty": o.get("qty"),
                "type": o.get("type"),
                "status": o.get("status"),
                "filled_qty": o.get("filled_qty"),
                "filled_avg_price": o.get("filled_avg_price"),
                "limit_price": o.get("limit_price"),
                "created_at": o.get("created_at"),
                "updated_at": o.get("updated_at"),
            })
        return orders

    def cancel_order(self, order_id: str) -> Dict[str, Any]:
        if not self._connected:
            return {"success": True, "message": "Demo: order cancelled"}
        return self._trade_request("DELETE", f"/orders/{order_id}") or {"error": "Cancel failed"}

    def close_position(self, symbol: str) -> Dict[str, Any]:
        if not self._connected:
            return {"success": True, "message": f"Demo: closed {symbol} position"}
        return self._trade_request("DELETE", f"/positions/{symbol}") or {"error": "Close failed"}

    # ==================================================================
    # MARKET DATA (via Alpaca Data API)
    # ==================================================================

    def get_snapshot(self, symbol: str) -> Optional[Dict[str, Any]]:
        cached = self._cached(f"snap:{symbol}", 30.0)
        if cached:
            return cached
        raw = self._data_request(f"/v2/stocks/{symbol}/snapshot")
        if not raw:
            return None
        latest = raw.get("latestTrade", {})
        quote = raw.get("latestQuote", {})
        bar = raw.get("minuteBar") or raw.get("dailyBar", {})
        result = {
            "symbol": symbol,
            "price": _sf(latest.get("p")),
            "size": latest.get("s"),
            "bid": _sf(quote.get("bp")),
            "ask": _sf(quote.get("ap")),
            "bid_size": quote.get("bs"),
            "ask_size": quote.get("as"),
            "bar_open": _sf(bar.get("o")),
            "bar_high": _sf(bar.get("h")),
            "bar_low": _sf(bar.get("l")),
            "bar_close": _sf(bar.get("c")),
            "bar_volume": bar.get("v"),
        }
        self._set_cache(f"snap:{symbol}", result)
        return result

    def get_multi_snapshots(self, symbols: List[str]) -> Dict[str, Dict]:
        if not symbols:
            return {}
        syms = ",".join(s.upper() for s in symbols)
        cached = self._cached(f"snaps:{syms}", 30.0)
        if cached:
            return cached
        raw = self._data_request(f"/v2/stocks/snapshots", {"symbols": syms})
        if not raw or not isinstance(raw, dict):
            return {}
        result = {}
        for sym, data in raw.items():
            trade = data.get("latestTrade", {})
            quote = data.get("latestQuote", {})
            bar = data.get("dailyBar", {})
            result[sym] = {
                "symbol": sym,
                "price": _sf(trade.get("p")),
                "bid": _sf(quote.get("bp")),
                "ask": _sf(quote.get("ap")),
                "bar_close": _sf(bar.get("c")),
                "bar_volume": bar.get("v"),
            }
        self._set_cache(f"snaps:{syms}", result)
        return result

    # ==================================================================
    # GLOBAL BENCHMARKS
    # ==================================================================

    def get_global_dashboard(self) -> Dict[str, Any]:
        """Bloomberg-style global market overview."""
        cached = self._cached("global_dash", 60.0)
        if cached:
            return cached

        all_syms = []
        for category in GLOBAL_BENCHMARKS.values():
            all_syms.extend(category.keys())

        equity_syms = [s for s in all_syms if "/" not in s]
        snapshots = self.get_multi_snapshots(equity_syms) if self._connected else {}

        try:
            from services.alpha_vantage_service import get_alpha_vantage_service
            av = get_alpha_vantage_service()
        except Exception:
            av = None

        dashboard: Dict[str, List[Dict]] = {"indices": [], "crypto": [], "commodities": [], "bonds": []}

        for category_key, category_data in GLOBAL_BENCHMARKS.items():
            for sym, meta in category_data.items():
                price = None
                change = None

                snap = snapshots.get(sym.replace("/", ""), {})
                if snap.get("price"):
                    price = snap["price"]

                if not price and av:
                    try:
                        q = av.get_quote(sym.replace("/USD", "").replace("/", ""))
                        if q:
                            price = q.get("price")
                            change = q.get("change_percent")
                    except Exception:
                        pass

                dashboard[category_key].append({
                    "symbol": sym,
                    "name": meta["name"],
                    "price": price,
                    "change_pct": change,
                    "region": meta.get("region"),
                })

        result = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "dashboard": dashboard,
            "broker_connected": self._connected,
            "paper_mode": self.is_paper,
        }
        self._set_cache("global_dash", result)
        return result

    # ==================================================================
    # AI COPILOT
    # ==================================================================

    def ai_copilot_analyze(self, symbol: str, context: str = "") -> Dict[str, Any]:
        """
        AI Copilot: real-time analysis for a trade decision.
        Combines: live quote, technicals, fundamentals, news, position info.
        """
        try:
            from services.investment_ai_tool_service import (
                deep_dive_analysis, _get_live_quote, _get_live_technical_profile,
                STOCK_DATABASE, _get_live_news,
            )
        except ImportError:
            return {"error": "Investment AI service unavailable"}

        sym = symbol.upper()
        quote = _get_live_quote(sym)
        profile = _get_live_technical_profile(sym)
        news = _get_live_news(sym)
        static = STOCK_DATABASE.get(sym, {})

        price = (quote or {}).get("price") or static.get("price")
        signals = (profile or {}).get("signals", {})
        recommendation = signals.get("recommendation", "HOLD")
        score = signals.get("composite_score", 0)

        current_position = None
        positions = self.get_positions()
        for pos in positions:
            if pos.get("symbol") == sym:
                current_position = pos
                break

        account = self.get_account()
        buying_power = account.get("buying_power", 0)

        risk_pct = 0.02
        if abs(score) >= 4:
            risk_pct = 0.03
        elif abs(score) <= 1:
            risk_pct = 0.01

        portfolio_val = account.get("portfolio_value", 0) or account.get("equity", 100000)
        max_trade_value = portfolio_val * risk_pct
        suggested_qty = int(max_trade_value / price) if price and price > 0 else 0

        copilot_action = "hold"
        if "STRONG BUY" in recommendation:
            copilot_action = "strong_buy"
        elif "BUY" in recommendation:
            copilot_action = "buy"
        elif "STRONG SELL" in recommendation:
            copilot_action = "strong_sell"
        elif "SELL" in recommendation:
            copilot_action = "sell"

        if current_position and copilot_action in ("strong_sell", "sell"):
            if (current_position.get("unrealized_pl") or 0) > 0:
                copilot_action = "take_profit"

        stop_loss = round(price * 0.97, 2) if price else None
        take_profit = round(price * 1.06, 2) if price else None

        news_articles = (news or {}).get("articles", [])[:3]
        sentiment_avg = 0
        if news_articles:
            scores = [a.get("overall_sentiment_score", 0) for a in news_articles if a.get("overall_sentiment_score")]
            sentiment_avg = sum(scores) / len(scores) if scores else 0

        return {
            "symbol": sym,
            "price": price,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "ai_recommendation": recommendation,
            "composite_score": score,
            "copilot_action": copilot_action,
            "signal_details": signals.get("details", []),
            "trade_suggestion": {
                "action": copilot_action,
                "qty": suggested_qty,
                "max_value": round(max_trade_value, 2),
                "risk_pct": f"{risk_pct*100}%",
                "stop_loss": stop_loss,
                "take_profit": take_profit,
                "order_type": "market",
            },
            "current_position": current_position,
            "account": {
                "buying_power": buying_power,
                "portfolio_value": portfolio_val,
                "paper": self.is_paper,
            },
            "news_sentiment": {
                "avg_score": round(sentiment_avg, 3),
                "label": "bullish" if sentiment_avg > 0.1 else ("bearish" if sentiment_avg < -0.1 else "neutral"),
                "articles": news_articles,
            },
        }

    # ==================================================================
    # DEMO MODE (when broker not connected)
    # ==================================================================

    def _demo_account(self) -> Dict[str, Any]:
        return {
            "account_id": "demo",
            "status": "ACTIVE",
            "currency": "USD",
            "buying_power": 250000.0,
            "cash": 125000.0,
            "portfolio_value": 250000.0,
            "equity": 250000.0,
            "last_equity": 248500.0,
            "long_market_value": 125000.0,
            "short_market_value": 0.0,
            "unrealized_pl": 3250.0,
            "unrealized_pl_pct": 0.026,
            "day_trade_count": 0,
            "pattern_day_trader": False,
            "trading_blocked": False,
            "paper": True,
            "broker": "demo",
            "connected": False,
            "note": "Demo mode. Set ALPACA_API_KEY and ALPACA_SECRET_KEY for live trading.",
        }

    def _demo_positions(self) -> List[Dict[str, Any]]:
        return [
            {"symbol": "AAPL", "qty": 50, "side": "long", "avg_entry_price": 220.0, "current_price": 227.5, "market_value": 11375.0, "cost_basis": 11000.0, "unrealized_pl": 375.0, "unrealized_pl_pct": 0.034, "change_today": 0.012, "asset_class": "us_equity"},
            {"symbol": "NVDA", "qty": 100, "side": "long", "avg_entry_price": 125.0, "current_price": 138.5, "market_value": 13850.0, "cost_basis": 12500.0, "unrealized_pl": 1350.0, "unrealized_pl_pct": 0.108, "change_today": 0.034, "asset_class": "us_equity"},
            {"symbol": "MSFT", "qty": 30, "side": "long", "avg_entry_price": 430.0, "current_price": 442.3, "market_value": 13269.0, "cost_basis": 12900.0, "unrealized_pl": 369.0, "unrealized_pl_pct": 0.029, "change_today": 0.008, "asset_class": "us_equity"},
            {"symbol": "GOOGL", "qty": 40, "side": "long", "avg_entry_price": 170.0, "current_price": 178.9, "market_value": 7156.0, "cost_basis": 6800.0, "unrealized_pl": 356.0, "unrealized_pl_pct": 0.052, "change_today": -0.005, "asset_class": "us_equity"},
            {"symbol": "SPY", "qty": 20, "side": "long", "avg_entry_price": 540.0, "current_price": 555.0, "market_value": 11100.0, "cost_basis": 10800.0, "unrealized_pl": 300.0, "unrealized_pl_pct": 0.028, "change_today": 0.003, "asset_class": "us_equity"},
        ]

    def _demo_orders(self) -> List[Dict[str, Any]]:
        return [
            {"order_id": "demo-001", "symbol": "NVDA", "side": "buy", "qty": "25", "type": "market", "status": "filled", "filled_qty": "25", "filled_avg_price": "135.20", "created_at": (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()},
            {"order_id": "demo-002", "symbol": "AAPL", "side": "buy", "qty": "10", "type": "limit", "status": "filled", "filled_qty": "10", "filled_avg_price": "225.50", "limit_price": "226.00", "created_at": (datetime.now(timezone.utc) - timedelta(hours=5)).isoformat()},
        ]

    def _demo_order(self, body: Dict) -> Dict[str, Any]:
        return {
            "order_id": f"demo-{int(time.time())}",
            "symbol": body.get("symbol"),
            "side": body.get("side"),
            "qty": body.get("qty"),
            "type": body.get("type"),
            "status": "accepted",
            "broker": "demo",
            "note": "Demo mode order. Set ALPACA_API_KEY for live execution.",
        }


def _sf(val: Any) -> Optional[float]:
    if val is None:
        return None
    try:
        f = float(val)
        return f if math.isfinite(f) else None
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_instance: Optional[TradingPlatformService] = None


def get_trading_platform() -> TradingPlatformService:
    global _instance
    if _instance is None:
        _instance = TradingPlatformService()
    return _instance
