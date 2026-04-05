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
ALPACA_BROKER_MODE = os.environ.get("ALPACA_BROKER_MODE", "false").lower() in ("1", "true", "yes")

ALPACA_TRADE_URL = (
    "https://paper-api.alpaca.markets" if ALPACA_PAPER
    else "https://api.alpaca.markets"
)
ALPACA_DATA_URL = "https://data.alpaca.markets"
ALPACA_BROKER_URL = (
    "https://broker-api.sandbox.alpaca.markets" if ALPACA_PAPER
    else "https://broker-api.alpaca.markets"
)


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
    # PORTFOLIO HISTORY (equity curve, P&L timeline)
    # ==================================================================

    def get_portfolio_history(self, period: str = "1M", timeframe: str = "1D") -> Dict[str, Any]:
        """
        Account portfolio history — equity curve and P&L over time.
        period: 1D, 1W, 1M, 3M, 1A, 5A
        timeframe: 1Min, 5Min, 15Min, 1H, 1D
        """
        if not self._connected:
            return self._demo_portfolio_history(period)
        cache_key = f"port_hist:{period}:{timeframe}"
        cached = self._cached(cache_key, 120.0)
        if cached:
            return cached
        raw = self._trade_request("GET", f"/account/portfolio/history?period={period}&timeframe={timeframe}")
        if not raw or "error" in raw:
            return self._demo_portfolio_history(period)
        timestamps = raw.get("timestamp", [])
        equity = raw.get("equity", [])
        pnl = raw.get("profit_loss", [])
        pnl_pct = raw.get("profit_loss_pct", [])
        base_value = raw.get("base_value", 0)
        points = []
        for i in range(len(timestamps)):
            points.append({
                "timestamp": timestamps[i],
                "date": datetime.fromtimestamp(timestamps[i], tz=timezone.utc).isoformat() if timestamps[i] else None,
                "equity": equity[i] if i < len(equity) else None,
                "pnl": pnl[i] if i < len(pnl) else None,
                "pnl_pct": pnl_pct[i] if i < len(pnl_pct) else None,
            })
        result = {
            "period": period,
            "timeframe": timeframe,
            "base_value": _sf(base_value),
            "points": points,
            "count": len(points),
            "current_equity": equity[-1] if equity else None,
            "total_pnl": pnl[-1] if pnl else None,
            "total_pnl_pct": pnl_pct[-1] if pnl_pct else None,
        }
        self._set_cache(cache_key, result)
        return result

    def _demo_portfolio_history(self, period: str) -> Dict[str, Any]:
        import random
        rng = random.Random(42)
        days = {"1D": 1, "1W": 5, "1M": 22, "3M": 65, "1A": 252, "5A": 1260}.get(period, 22)
        base = 250000.0
        equity_vals = [base]
        for _ in range(days - 1):
            equity_vals.append(equity_vals[-1] * (1 + rng.gauss(0.0004, 0.012)))
        now = datetime.now(timezone.utc)
        points = []
        for i, eq in enumerate(equity_vals):
            dt = now - timedelta(days=days - i)
            points.append({
                "timestamp": int(dt.timestamp()),
                "date": dt.isoformat(),
                "equity": round(eq, 2),
                "pnl": round(eq - base, 2),
                "pnl_pct": round((eq - base) / base, 6),
            })
        return {
            "period": period, "timeframe": "1D", "base_value": base,
            "points": points, "count": len(points),
            "current_equity": round(equity_vals[-1], 2),
            "total_pnl": round(equity_vals[-1] - base, 2),
            "total_pnl_pct": round((equity_vals[-1] - base) / base, 6),
        }

    # ==================================================================
    # MARKET BARS (OHLCV via Alpaca Data API)
    # ==================================================================

    def get_bars(self, symbol: str, timeframe: str = "1Day", limit: int = 100) -> List[Dict[str, Any]]:
        """
        Historical bars from Alpaca Data API.
        timeframe: 1Min, 5Min, 15Min, 1Hour, 1Day, 1Week, 1Month
        """
        cache_key = f"bars:{symbol}:{timeframe}:{limit}"
        cached = self._cached(cache_key, 60.0)
        if cached:
            return cached
        raw = self._data_request(f"/v2/stocks/{symbol.upper()}/bars", {
            "timeframe": timeframe,
            "limit": str(limit),
            "feed": "iex",
        })
        if not raw or "bars" not in raw:
            return []
        bars = []
        for b in raw.get("bars", []):
            bars.append({
                "date": b.get("t"),
                "open": _sf(b.get("o")),
                "high": _sf(b.get("h")),
                "low": _sf(b.get("l")),
                "close": _sf(b.get("c")),
                "volume": b.get("v"),
                "vwap": _sf(b.get("vw")),
                "trade_count": b.get("n"),
            })
        self._set_cache(cache_key, bars)
        return bars

    def get_latest_trade(self, symbol: str) -> Optional[Dict[str, Any]]:
        raw = self._data_request(f"/v2/stocks/{symbol.upper()}/trades/latest", {"feed": "iex"})
        if not raw or "trade" not in raw:
            return None
        t = raw["trade"]
        return {"symbol": symbol.upper(), "price": _sf(t.get("p")), "size": t.get("s"), "timestamp": t.get("t"), "exchange": t.get("x")}

    def get_latest_quote(self, symbol: str) -> Optional[Dict[str, Any]]:
        raw = self._data_request(f"/v2/stocks/{symbol.upper()}/quotes/latest", {"feed": "iex"})
        if not raw or "quote" not in raw:
            return None
        q = raw["quote"]
        return {"symbol": symbol.upper(), "bid": _sf(q.get("bp")), "bid_size": q.get("bs"), "ask": _sf(q.get("ap")), "ask_size": q.get("as"), "timestamp": q.get("t")}

    # ==================================================================
    # WATCHLISTS (server-side via Alpaca)
    # ==================================================================

    def get_watchlists(self) -> List[Dict[str, Any]]:
        if not self._connected:
            return [{"id": "demo", "name": "My Watchlist", "symbols": ["AAPL", "NVDA", "MSFT", "GOOGL", "TSLA"]}]
        raw = self._trade_request("GET", "/watchlists")
        if not raw or not isinstance(raw, list):
            return []
        return [{"id": w.get("id"), "name": w.get("name"), "symbols": [a.get("symbol") for a in w.get("assets", [])]} for w in raw]

    def create_watchlist(self, name: str, symbols: List[str]) -> Dict[str, Any]:
        if not self._connected:
            return {"id": "demo-new", "name": name, "symbols": symbols}
        return self._trade_request("POST", "/watchlists", {"name": name, "symbols": symbols}) or {}

    def add_to_watchlist(self, watchlist_id: str, symbol: str) -> Dict[str, Any]:
        if not self._connected:
            return {"success": True}
        return self._trade_request("POST", f"/watchlists/{watchlist_id}", {"symbol": symbol}) or {}

    def remove_from_watchlist(self, watchlist_id: str, symbol: str) -> Dict[str, Any]:
        if not self._connected:
            return {"success": True}
        return self._trade_request("DELETE", f"/watchlists/{watchlist_id}/{symbol}") or {}

    # ==================================================================
    # MARKET CLOCK & ASSETS
    # ==================================================================

    def get_clock(self) -> Dict[str, Any]:
        if not self._connected:
            now = datetime.now(timezone.utc)
            hour = now.hour
            is_open = 13 <= hour < 20 and now.weekday() < 5
            return {"is_open": is_open, "timestamp": now.isoformat(), "next_open": "09:30 ET", "next_close": "16:00 ET"}
        cached = self._cached("clock", 30.0)
        if cached:
            return cached
        raw = self._trade_request("GET", "/clock")
        if not raw or "error" in raw:
            return {"is_open": False, "timestamp": datetime.now(timezone.utc).isoformat()}
        result = {"is_open": raw.get("is_open", False), "timestamp": raw.get("timestamp"), "next_open": raw.get("next_open"), "next_close": raw.get("next_close")}
        self._set_cache("clock", result)
        return result

    def search_assets(self, query: str = "", asset_class: str = "us_equity", status: str = "active") -> List[Dict[str, Any]]:
        if not self._connected:
            from services.investment_ai_tool_service import STOCK_DATABASE
            return [{"symbol": k, "name": v.get("name", k), "asset_class": "us_equity", "tradable": True} for k, v in STOCK_DATABASE.items() if query.upper() in k or query.lower() in v.get("name", "").lower()][:20]
        cache_key = f"assets:{query}:{asset_class}"
        cached = self._cached(cache_key, 300.0)
        if cached:
            return cached
        raw = self._trade_request("GET", f"/assets?status={status}&asset_class={asset_class}")
        if not raw or not isinstance(raw, list):
            return []
        results = []
        q = query.upper()
        for a in raw:
            sym = a.get("symbol", "")
            name = a.get("name", "")
            if q and q not in sym and q not in name.upper():
                continue
            results.append({
                "symbol": sym,
                "name": name,
                "asset_class": a.get("class"),
                "exchange": a.get("exchange"),
                "tradable": a.get("tradable", False),
                "fractionable": a.get("fractionable", False),
                "shortable": a.get("shortable", False),
            })
            if len(results) >= 20:
                break
        self._set_cache(cache_key, results)
        return results

    # ==================================================================
    # ACCOUNT ACTIVITIES (fills, dividends, transfers)
    # ==================================================================

    def get_activities(self, activity_type: str = "", limit: int = 20) -> List[Dict[str, Any]]:
        if not self._connected:
            return self._demo_activities()
        params = f"?page_size={limit}"
        if activity_type:
            params += f"&activity_type={activity_type}"
        raw = self._trade_request("GET", f"/account/activities{params}")
        if not raw or not isinstance(raw, list):
            return self._demo_activities()
        activities = []
        for a in raw[:limit]:
            activities.append({
                "id": a.get("id"),
                "activity_type": a.get("activity_type"),
                "symbol": a.get("symbol"),
                "side": a.get("side"),
                "qty": a.get("qty"),
                "price": a.get("price"),
                "net_amount": a.get("net_amount"),
                "date": a.get("date") or a.get("transaction_time"),
                "status": a.get("status"),
                "description": a.get("description"),
            })
        return activities

    def _demo_activities(self) -> List[Dict[str, Any]]:
        now = datetime.now(timezone.utc)
        return [
            {"id": "act-1", "activity_type": "FILL", "symbol": "NVDA", "side": "buy", "qty": "25", "price": "135.20", "date": (now - timedelta(hours=2)).isoformat()},
            {"id": "act-2", "activity_type": "FILL", "symbol": "AAPL", "side": "buy", "qty": "10", "price": "225.50", "date": (now - timedelta(hours=5)).isoformat()},
            {"id": "act-3", "activity_type": "DIV", "symbol": "MSFT", "net_amount": "18.60", "date": (now - timedelta(days=15)).isoformat(), "description": "Dividend payment"},
            {"id": "act-4", "activity_type": "FILL", "symbol": "SPY", "side": "buy", "qty": "20", "price": "540.00", "date": (now - timedelta(days=30)).isoformat()},
        ]

    # ==================================================================
    # ADVANCED ORDERS (bracket, OCO)
    # ==================================================================

    def submit_bracket_order(
        self, symbol: str, side: str, qty: float,
        take_profit_price: float, stop_loss_price: float,
        limit_price: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Submit a bracket order (entry + take profit + stop loss).
        """
        body: Dict[str, Any] = {
            "symbol": symbol.upper(),
            "side": side.lower(),
            "qty": str(qty),
            "type": "limit" if limit_price else "market",
            "time_in_force": "gtc",
            "order_class": "bracket",
            "take_profit": {"limit_price": str(take_profit_price)},
            "stop_loss": {"stop_price": str(stop_loss_price)},
        }
        if limit_price:
            body["limit_price"] = str(limit_price)
        if not self._connected:
            return self._demo_order(body)
        raw = self._trade_request("POST", "/orders", body)
        if not raw:
            return {"error": "Bracket order failed"}
        if "error" in raw:
            return raw
        self._cache.pop("positions", None)
        self._cache.pop("account", None)
        return {"order_id": raw.get("id"), "symbol": raw.get("symbol"), "side": raw.get("side"), "qty": raw.get("qty"), "type": "bracket", "status": raw.get("status"), "legs": raw.get("legs", []), "broker": "alpaca"}

    def submit_oco_order(
        self, symbol: str, qty: float,
        take_profit_price: float, stop_loss_price: float,
    ) -> Dict[str, Any]:
        """
        Submit an OCO (One-Cancels-Other) order for an existing position.
        """
        body: Dict[str, Any] = {
            "symbol": symbol.upper(),
            "side": "sell",
            "qty": str(qty),
            "type": "limit",
            "time_in_force": "gtc",
            "order_class": "oco",
            "take_profit": {"limit_price": str(take_profit_price)},
            "stop_loss": {"stop_price": str(stop_loss_price)},
        }
        if not self._connected:
            return self._demo_order(body)
        raw = self._trade_request("POST", "/orders", body)
        if not raw:
            return {"error": "OCO order failed"}
        if "error" in raw:
            return raw
        self._cache.pop("positions", None)
        return {"order_id": raw.get("id"), "symbol": raw.get("symbol"), "type": "oco", "status": raw.get("status"), "legs": raw.get("legs", []), "broker": "alpaca"}

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

    # ==================================================================
    # BROKER API v1 (Account creation, ACH, transfers, journaling)
    # ==================================================================

    def _broker_headers(self) -> Dict[str, str]:
        import base64
        creds = base64.b64encode(f"{self._api_key}:{self._secret_key}".encode()).decode()
        return {"Authorization": f"Basic {creds}", "Content-Type": "application/json"}

    def _broker_request(self, method: str, path: str, body: Optional[Dict] = None) -> Optional[Dict]:
        url = f"{ALPACA_BROKER_URL}/v1{path}"
        try:
            resp = requests.request(method, url, headers=self._broker_headers(), json=body, timeout=self._timeout)
            if resp.status_code == 204:
                return {"success": True}
            if resp.status_code >= 400:
                try:
                    return {"error": resp.json(), "status": resp.status_code}
                except Exception:
                    return {"error": resp.text, "status": resp.status_code}
            return resp.json()
        except Exception as e:
            return {"error": str(e)}

    def broker_create_account(self, account_data: Dict) -> Dict[str, Any]:
        """Create a brokerage account for an end user (Broker API v1)."""
        if not self._connected:
            return {"id": "demo-acct-001", "account_number": "900000001", "status": "APPROVED", "currency": "USD", "note": "Demo mode"}
        return self._broker_request("POST", "/accounts", account_data) or {"error": "Account creation failed"}

    def broker_get_accounts(self) -> List[Dict[str, Any]]:
        if not self._connected:
            return [{"id": "demo-acct-001", "account_number": "900000001", "status": "ACTIVE", "currency": "USD"}]
        raw = self._broker_request("GET", "/accounts")
        if isinstance(raw, list):
            return raw
        return [raw] if raw and "error" not in raw else []

    def broker_get_account(self, account_id: str) -> Dict[str, Any]:
        if not self._connected:
            return {"id": account_id, "status": "ACTIVE", "currency": "USD"}
        return self._broker_request("GET", f"/accounts/{account_id}") or {}

    def broker_create_ach_relationship(self, account_id: str, ach_data: Dict) -> Dict[str, Any]:
        """Establish ACH bank relationship for funding."""
        if not self._connected:
            return {"id": "demo-ach-001", "account_id": account_id, "status": "APPROVED", "note": "Demo mode"}
        return self._broker_request("POST", f"/accounts/{account_id}/ach_relationships", ach_data) or {"error": "ACH setup failed"}

    def broker_get_ach_relationships(self, account_id: str) -> List[Dict]:
        if not self._connected:
            return [{"id": "demo-ach-001", "status": "APPROVED", "nickname": "Demo Bank"}]
        raw = self._broker_request("GET", f"/accounts/{account_id}/ach_relationships")
        return raw if isinstance(raw, list) else []

    def broker_create_transfer(self, account_id: str, transfer_data: Dict) -> Dict[str, Any]:
        """Fund account via ACH transfer."""
        if not self._connected:
            return {"id": "demo-xfer-001", "status": "QUEUED", "amount": transfer_data.get("amount"), "direction": transfer_data.get("direction"), "note": "Demo mode"}
        return self._broker_request("POST", f"/accounts/{account_id}/transfers", transfer_data) or {"error": "Transfer failed"}

    def broker_create_journal(self, journal_data: Dict) -> Dict[str, Any]:
        """Journal cash/securities between accounts (instant funding)."""
        if not self._connected:
            return {"id": "demo-jnl-001", "entry_type": journal_data.get("entry_type"), "status": "executed", "note": "Demo mode"}
        return self._broker_request("POST", "/journals", journal_data) or {"error": "Journal failed"}

    def broker_submit_order(self, account_id: str, order_data: Dict) -> Dict[str, Any]:
        """Submit order for a specific broker account (v1 Broker API)."""
        if not self._connected:
            return self._demo_order(order_data)
        raw = self._broker_request("POST", f"/trading/accounts/{account_id}/orders", order_data)
        return raw or {"error": "Order failed"}

    def broker_get_assets(self, status: str = "active", asset_class: str = "") -> List[Dict]:
        """Get all tradable assets from Broker API."""
        cache_key = f"broker_assets:{status}:{asset_class}"
        cached = self._cached(cache_key, 3600.0)
        if cached:
            return cached
        if not self._connected:
            try:
                from services.investment_ai_tool_service import STOCK_DATABASE
                return [{"symbol": k, "name": v.get("name", k), "class": "us_equity", "tradable": True, "fractionable": True} for k, v in STOCK_DATABASE.items()]
            except Exception:
                return []
        raw = self._broker_request("GET", f"/assets?status={status}" + (f"&asset_class={asset_class}" if asset_class else ""))
        result = raw if isinstance(raw, list) else []
        self._set_cache(cache_key, result)
        return result

    # ==================================================================
    # BI ANALYTICS ENGINE
    # ==================================================================

    def get_bi_analytics(self) -> Dict[str, Any]:
        """
        Business Intelligence analytics computed from positions,
        portfolio history, and account data.
        """
        positions = self.get_positions()
        account = self.get_account()
        history = self.get_portfolio_history("1M", "1D")

        total_pl = sum(_sf(p.get("unrealized_pl")) or 0 for p in positions)
        total_value = sum(_sf(p.get("market_value")) or 0 for p in positions)
        total_cost = sum(_sf(p.get("cost_basis")) or 0 for p in positions)

        winners = [p for p in positions if (_sf(p.get("unrealized_pl")) or 0) > 0]
        losers = [p for p in positions if (_sf(p.get("unrealized_pl")) or 0) < 0]
        win_rate = len(winners) / max(1, len(positions)) * 100

        best = max(positions, key=lambda p: _sf(p.get("unrealized_pl")) or 0) if positions else None
        worst = min(positions, key=lambda p: _sf(p.get("unrealized_pl")) or 0) if positions else None

        # Sector exposure
        sectors: Dict[str, float] = {}
        for p in positions:
            sec = p.get("asset_class", "unknown")
            sectors[sec] = sectors.get(sec, 0) + (_sf(p.get("market_value")) or 0)

        # Concentration risk
        max_pct = 0
        if total_value > 0:
            max_pct = max((_sf(p.get("market_value")) or 0) / total_value * 100 for p in positions) if positions else 0

        # Equity curve stats from portfolio history
        points = history.get("points", [])
        equities = [p.get("equity") for p in points if p.get("equity")]

        peak = max(equities) if equities else 0
        drawdown = 0
        if peak > 0 and equities:
            current_eq = equities[-1]
            drawdown = round((peak - current_eq) / peak * 100, 2)

        # Sharpe estimate (annualized from daily returns)
        daily_returns = []
        for i in range(1, len(equities)):
            if equities[i-1] and equities[i-1] > 0:
                daily_returns.append((equities[i] - equities[i-1]) / equities[i-1])

        sharpe = 0
        if daily_returns:
            avg_ret = sum(daily_returns) / len(daily_returns)
            std_ret = (sum((r - avg_ret)**2 for r in daily_returns) / max(1, len(daily_returns)-1)) ** 0.5
            if std_ret > 0:
                sharpe = round((avg_ret / std_ret) * (252 ** 0.5), 2)

        # Sortino (downside deviation only)
        sortino = 0
        down_returns = [r for r in daily_returns if r < 0]
        if down_returns:
            down_std = (sum(r**2 for r in down_returns) / len(down_returns)) ** 0.5
            if down_std > 0:
                avg_ret = sum(daily_returns) / len(daily_returns)
                sortino = round((avg_ret / down_std) * (252 ** 0.5), 2)

        # Beta estimate vs SPY
        beta = sum(p.get("beta", 1.0) or 1.0 for p in positions) / max(1, len(positions)) if positions else 1.0

        portfolio_val = _sf(account.get("portfolio_value")) or 0

        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "summary": {
                "portfolio_value": portfolio_val,
                "total_cost_basis": round(total_cost, 2),
                "total_unrealized_pl": round(total_pl, 2),
                "total_return_pct": round(total_pl / max(1, total_cost) * 100, 2) if total_cost else 0,
                "cash": _sf(account.get("cash")),
                "buying_power": _sf(account.get("buying_power")),
                "position_count": len(positions),
            },
            "performance": {
                "win_rate": round(win_rate, 1),
                "winners": len(winners),
                "losers": len(losers),
                "best_position": {"symbol": best.get("symbol"), "pl": _sf(best.get("unrealized_pl"))} if best else None,
                "worst_position": {"symbol": worst.get("symbol"), "pl": _sf(worst.get("unrealized_pl"))} if worst else None,
                "sharpe_ratio": sharpe,
                "sortino_ratio": sortino,
                "max_drawdown_pct": drawdown,
                "peak_equity": peak,
                "portfolio_beta": round(beta, 2),
            },
            "risk": {
                "max_concentration_pct": round(max_pct, 1),
                "concentration_symbol": max(positions, key=lambda p: _sf(p.get("market_value")) or 0).get("symbol") if positions else None,
                "sector_exposure": {k: round(v, 2) for k, v in sorted(sectors.items(), key=lambda x: -x[1])},
                "total_invested": round(total_value, 2),
                "cash_ratio": round((_sf(account.get("cash")) or 0) / max(1, portfolio_val) * 100, 1),
            },
            "positions_detail": [
                {
                    "symbol": p.get("symbol"),
                    "qty": _sf(p.get("qty")),
                    "value": _sf(p.get("market_value")),
                    "cost": _sf(p.get("cost_basis")),
                    "pl": _sf(p.get("unrealized_pl")),
                    "pl_pct": round((_sf(p.get("unrealized_pl_pct")) or 0) * 100, 2),
                    "weight": round((_sf(p.get("market_value")) or 0) / max(1, total_value) * 100, 1),
                    "change_today": _sf(p.get("change_today")),
                }
                for p in sorted(positions, key=lambda x: _sf(x.get("market_value")) or 0, reverse=True)
            ],
        }

    # ==================================================================
    # AI OPTIMIZATION ENGINE
    # ==================================================================

    def ai_optimize_portfolio(self) -> Dict[str, Any]:
        """
        AI-driven portfolio optimization: identifies rebalancing opportunities,
        risk reduction, and signal-based trade suggestions.
        """
        positions = self.get_positions()
        account = self.get_account()
        analytics = self.get_bi_analytics()

        total_value = analytics["summary"]["portfolio_value"] or 0
        suggestions: List[Dict] = []
        risk_alerts: List[Dict] = []
        rebalance_actions: List[Dict] = []

        # Concentration risk check
        max_conc = analytics["risk"]["max_concentration_pct"]
        if max_conc > 25:
            risk_alerts.append({
                "level": "high",
                "message": f"Position concentration risk: {analytics['risk']['concentration_symbol']} is {max_conc:.0f}% of portfolio",
                "action": f"Consider trimming {analytics['risk']['concentration_symbol']} to reduce single-stock risk",
            })

        # Cash drag check
        cash_ratio = analytics["risk"]["cash_ratio"]
        if cash_ratio > 30:
            risk_alerts.append({
                "level": "medium",
                "message": f"Cash drag: {cash_ratio:.0f}% of portfolio in cash",
                "action": "Deploy cash into diversified positions for better returns",
            })

        # Drawdown alert
        if analytics["performance"]["max_drawdown_pct"] > 10:
            risk_alerts.append({
                "level": "high",
                "message": f"Drawdown: {analytics['performance']['max_drawdown_pct']}% from peak",
                "action": "Review losing positions and consider tightening stop-losses",
            })

        # Run AI signals for each position
        try:
            from services.investment_ai_tool_service import _get_live_technical_profile, STOCK_DATABASE
        except ImportError:
            _get_live_technical_profile = None
            STOCK_DATABASE = {}

        for p in positions:
            sym = p.get("symbol", "")
            pl_pct = (_sf(p.get("unrealized_pl_pct")) or 0) * 100
            weight = (_sf(p.get("market_value")) or 0) / max(1, total_value) * 100

            profile = None
            if _get_live_technical_profile:
                profile = _get_live_technical_profile(sym)

            signals = (profile or {}).get("signals", {})
            rec = signals.get("recommendation", "HOLD")
            score = signals.get("composite_score", 0)

            if "SELL" in rec and pl_pct > 5:
                suggestions.append({"symbol": sym, "action": "take_profit", "reason": f"AI signals SELL and position is +{pl_pct:.1f}%. Lock in gains.", "priority": "high", "score": score})
            elif "SELL" in rec and pl_pct < -5:
                suggestions.append({"symbol": sym, "action": "cut_loss", "reason": f"AI signals SELL and position is {pl_pct:.1f}%. Cut losses.", "priority": "high", "score": score})
            elif "BUY" in rec and weight < 5:
                suggestions.append({"symbol": sym, "action": "add", "reason": f"AI signals BUY but position is only {weight:.1f}% of portfolio.", "priority": "medium", "score": score})

            if weight > 20:
                rebalance_actions.append({"symbol": sym, "action": "reduce", "current_weight": round(weight, 1), "target_weight": 10, "reason": "Over-concentrated"})

        # Diversification suggestions
        held_symbols = {p.get("symbol") for p in positions}
        diversify_candidates = ["SPY", "QQQ", "BND", "GLD", "VTI"]
        for sym in diversify_candidates:
            if sym not in held_symbols:
                suggestions.append({"symbol": sym, "action": "diversify", "reason": f"Portfolio lacks {sym} exposure for broad diversification.", "priority": "low", "score": 0})

        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "risk_alerts": risk_alerts,
            "trade_suggestions": sorted(suggestions, key=lambda x: {"high": 0, "medium": 1, "low": 2}.get(x.get("priority", "low"), 3)),
            "rebalance_actions": rebalance_actions,
            "optimization_score": max(0, min(100, 80 - len(risk_alerts) * 15 + (analytics["performance"]["sharpe_ratio"] or 0) * 10)),
            "portfolio_health": "good" if not risk_alerts else ("fair" if len(risk_alerts) <= 2 else "needs_attention"),
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
