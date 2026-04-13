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
# Support both env var names for secret key (align server.py and service)
ALPACA_SECRET_KEY = (
    os.environ.get("ALPACA_SECRET_KEY", "")
    or os.environ.get("ALPACA_API_SECRET", "")
)
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

_VALID_SIDES = {"buy", "sell"}
_VALID_ORDER_TYPES = {"market", "limit", "stop", "stop_limit", "trailing_stop"}
_VALID_TIF = {"day", "gtc", "opg", "cls", "ioc", "fok"}
_MAX_RETRIES = 2
_RETRY_BACKOFF = 1.0


# ---------------------------------------------------------------------------
# Global market indices / benchmarks for Bloomberg-style dashboard
# ---------------------------------------------------------------------------

GLOBAL_BENCHMARKS = {
    "indices": {
        "SPY": {"name": "S&P 500", "region": "US"},
        "QQQ": {"name": "NASDAQ 100", "region": "US"},
        "DIA": {"name": "Dow Jones", "region": "US"},
        "IWM": {"name": "Russell 2000", "region": "US"},
        "VTI": {"name": "Total Market", "region": "US"},
        "EFA": {"name": "MSCI EAFE", "region": "International"},
        "EEM": {"name": "Emerging Markets", "region": "International"},
        "VGK": {"name": "FTSE Europe", "region": "Europe"},
        "EWJ": {"name": "Japan (Nikkei)", "region": "Asia"},
        "FXI": {"name": "China Large-Cap", "region": "Asia"},
    },
    "mega_caps": {
        "AAPL": {"name": "Apple"},
        "MSFT": {"name": "Microsoft"},
        "NVDA": {"name": "NVIDIA"},
        "GOOGL": {"name": "Alphabet"},
        "AMZN": {"name": "Amazon"},
        "META": {"name": "Meta"},
        "TSLA": {"name": "Tesla"},
    },
    "crypto": {
        "BTC/USD": {"name": "Bitcoin"},
        "ETH/USD": {"name": "Ethereum"},
        "SOL/USD": {"name": "Solana"},
        "DOGE/USD": {"name": "Dogecoin"},
        "AVAX/USD": {"name": "Avalanche"},
    },
    "commodities": {
        "GLD": {"name": "Gold"},
        "SLV": {"name": "Silver"},
        "USO": {"name": "Crude Oil"},
        "UNG": {"name": "Natural Gas"},
        "CPER": {"name": "Copper"},
    },
    "bonds": {
        "TLT": {"name": "20+ Year Treasury"},
        "IEF": {"name": "7-10 Year Treasury"},
        "BND": {"name": "Total Bond Market"},
        "HYG": {"name": "High Yield Corporate"},
        "LQD": {"name": "Investment Grade"},
    },
    "sectors": {
        "XLK": {"name": "Technology"},
        "XLF": {"name": "Financials"},
        "XLE": {"name": "Energy"},
        "XLV": {"name": "Healthcare"},
        "XLI": {"name": "Industrials"},
    },
}

# Live price cache — populated exclusively from Alpaca API data.
# No static/mock prices. Missing data is reported as None.
_LIVE_PRICE_CACHE: Dict[str, Dict[str, Any]] = {}

# Map Alpha Vantage lookup symbols for items that need translation
_AV_SYMBOL_MAP: Dict[str, str] = {
    "BTC/USD": "BTC",
    "ETH/USD": "ETH",
    "SOL/USD": "SOL",
    "DOGE/USD": "DOGE",
    "AVAX/USD": "AVAX",
}


class TradingPlatformService:
    """
    Unified trading platform with broker API integration,
    position management, and AI copilot support.
    """

    def __init__(self):
        self._reload_keys()
        self._data_url = ALPACA_DATA_URL
        self._timeout = 10
        self._cache: Dict[str, Any] = {}
        self._cache_ts: Dict[str, float] = {}

    def _reload_keys(self) -> None:
        """Re-read API keys from environment (supports hot-reload after Railway redeploy)."""
        self._api_key = os.environ.get("ALPACA_API_KEY", "") or ALPACA_API_KEY
        self._secret_key = (
            os.environ.get("ALPACA_SECRET_KEY", "")
            or os.environ.get("ALPACA_API_SECRET", "")
            or ALPACA_SECRET_KEY
        )
        is_paper = os.environ.get("ALPACA_PAPER", "true").lower() in ("1", "true", "yes")
        self._trade_url = "https://paper-api.alpaca.markets" if is_paper else "https://api.alpaca.markets"
        self._connected = bool(self._api_key and self._secret_key)

    @property
    def is_connected(self) -> bool:
        if not self._connected:
            self._reload_keys()
        return self._connected

    @property
    def is_paper(self) -> bool:
        return os.environ.get("ALPACA_PAPER", "true").lower() in ("1", "true", "yes")

    def get_connection_status(self) -> Dict[str, Any]:
        """Diagnostic: show connection state and key configuration."""
        self._reload_keys()
        alive = False
        latency_ms = None
        account_status = None
        if self._connected:
            alive, latency_ms, account_status = self._ping_broker()
        return {
            "connected": self._connected,
            "alive": alive,
            "latency_ms": latency_ms,
            "account_status": account_status,
            "api_key_set": bool(self._api_key),
            "api_key_prefix": self._api_key[:8] + "..." if len(self._api_key) > 8 else ("(empty)" if not self._api_key else "(short)"),
            "secret_key_set": bool(self._secret_key),
            "paper_mode": self.is_paper,
            "trade_url": self._trade_url,
            "data_url": self._data_url,
            "env_ALPACA_API_KEY": "(set)" if os.environ.get("ALPACA_API_KEY") else "(not set)",
            "env_ALPACA_SECRET_KEY": "(set)" if os.environ.get("ALPACA_SECRET_KEY") else "(not set)",
            "env_ALPACA_PAPER": os.environ.get("ALPACA_PAPER", "(not set)"),
        }

    def _ping_broker(self) -> Tuple[bool, Optional[float], Optional[str]]:
        """Lightweight health check: GET /v2/account and measure latency."""
        t0 = time.time()
        try:
            resp = requests.get(
                f"{self._trade_url}/v2/account",
                headers=self._headers(),
                timeout=5,
            )
            latency_ms = round((time.time() - t0) * 1000, 1)
            if resp.status_code == 200:
                data = resp.json()
                return True, latency_ms, data.get("status")
            return False, latency_ms, f"HTTP {resp.status_code}"
        except Exception as e:
            latency_ms = round((time.time() - t0) * 1000, 1)
            return False, latency_ms, str(e)

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
        last_err = None
        for attempt in range(_MAX_RETRIES + 1):
            try:
                resp = requests.request(
                    method, url,
                    headers=self._headers(),
                    json=body,
                    timeout=self._timeout,
                )
                if resp.status_code == 204:
                    return {"success": True}
                if resp.status_code == 429:
                    last_err = "HTTP 429 rate limited"
                    if attempt < _MAX_RETRIES:
                        time.sleep(_RETRY_BACKOFF * (attempt + 1))
                    continue
                if resp.status_code >= 400:
                    return {"error": resp.json() if resp.text else resp.reason, "status": resp.status_code}
                return resp.json()
            except requests.exceptions.ConnectionError as e:
                last_err = str(e)
                if attempt < _MAX_RETRIES:
                    time.sleep(_RETRY_BACKOFF * (attempt + 1))
            except Exception as e:
                return {"error": str(e)}
        return {"error": f"Request failed after {_MAX_RETRIES + 1} attempts: {last_err}"}

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
        if not self.is_connected:
            return self._not_connected_account()
        cached = self._cached("account", 15.0)
        if cached:
            return cached
        raw = self._trade_request("GET", "/account")
        if not raw or "error" in raw:
            return self._not_connected_account()
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
        if not self.is_connected:
            return []
        cached = self._cached("positions", 10.0)
        if cached:
            return cached
        raw = self._trade_request("GET", "/positions")
        if not raw or isinstance(raw, dict) and "error" in raw:
            return []
        if not isinstance(raw, list):
            return []
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

    def _get_position_snapshot(self, symbol: str) -> Optional[Dict[str, Any]]:
        for position in self.get_positions():
            if position.get("symbol") == symbol.upper():
                return position
        return None

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
        """Submit a live order to the broker with input validation."""
        if not symbol or not symbol.strip():
            return {"error": "symbol is required"}
        if side.lower() not in _VALID_SIDES:
            return {"error": f"Invalid side '{side}'. Must be 'buy' or 'sell'."}
        if order_type.lower() not in _VALID_ORDER_TYPES:
            return {"error": f"Invalid order_type '{order_type}'. Must be one of: {', '.join(sorted(_VALID_ORDER_TYPES))}"}
        if time_in_force.lower() not in _VALID_TIF:
            return {"error": f"Invalid time_in_force '{time_in_force}'. Must be one of: {', '.join(sorted(_VALID_TIF))}"}

        if qty is not None:
            qty_f = _sf(qty)
            if qty_f is None or qty_f <= 0:
                return {"error": "qty must be a positive number"}
        if notional is not None:
            notional_f = _sf(notional)
            if notional_f is None or notional_f <= 0:
                return {"error": "notional must be a positive number"}
        if limit_price is not None:
            lp = _sf(limit_price)
            if lp is None or lp <= 0:
                return {"error": "limit_price must be a positive number"}
        if stop_price is not None:
            sp = _sf(stop_price)
            if sp is None or sp <= 0:
                return {"error": "stop_price must be a positive number"}

        body: Dict[str, Any] = {
            "symbol": symbol.upper().strip(),
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

        if not self.is_connected:
            return self._not_connected_error()
        position_snapshot = self._get_position_snapshot(symbol) if side.lower() == "sell" else None

        raw = self._trade_request("POST", "/orders", body)
        if not raw:
            return {"error": "Order submission failed"}
        if "error" in raw:
            return raw

        self._cache.pop("positions", None)
        self._cache.pop("account", None)

        result = {
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
        self._record_trade_to_ledger(result, position_snapshot=position_snapshot)
        return result

    def get_orders(self, status: str = "all", limit: int = 20) -> List[Dict[str, Any]]:
        if not self.is_connected:
            return []
        raw = self._trade_request("GET", f"/orders?status={status}&limit={limit}")
        if not raw or not isinstance(raw, list):
            return []
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
        if not self.is_connected:
            return self._not_connected_error()
        return self._trade_request("DELETE", f"/orders/{order_id}") or {"error": "Cancel failed"}

    def cancel_all_orders(self) -> Dict[str, Any]:
        if not self.is_connected:
            return self._not_connected_error()
        return self._trade_request("DELETE", "/orders") or {"error": "Cancel all failed"}

    def close_position(self, symbol: str, qty: Optional[float] = None) -> Dict[str, Any]:
        if not self.is_connected:
            return self._not_connected_error()
        params = f"/{symbol}"
        if qty is not None:
            params += f"?qty={qty}"
        result = self._trade_request("DELETE", f"/positions{params}") or {"error": "Close failed"}
        if "error" not in result:
            self._record_trade_to_ledger({"symbol": symbol, "side": "sell", "qty": str(qty or "all"), "status": "closed", "broker": "alpaca"})
        return result

    def close_all_positions(self) -> Dict[str, Any]:
        if not self.is_connected:
            return self._not_connected_error()
        return self._trade_request("DELETE", "/positions") or {"error": "Close all failed"}

    def get_open_position(self, symbol: str) -> Dict[str, Any]:
        if not self.is_connected:
            return self._not_connected_error()
        raw = self._trade_request("GET", f"/positions/{symbol}")
        if not raw or "error" in raw:
            return raw or {"error": f"Position {symbol} not found"}
        return {
            "symbol": raw.get("symbol"),
            "qty": _sf(raw.get("qty")),
            "side": raw.get("side"),
            "avg_entry_price": _sf(raw.get("avg_entry_price")),
            "current_price": _sf(raw.get("current_price")),
            "market_value": _sf(raw.get("market_value")),
            "cost_basis": _sf(raw.get("cost_basis")),
            "unrealized_pl": _sf(raw.get("unrealized_pl")),
            "unrealized_pl_pct": _sf(raw.get("unrealized_plpc")),
            "asset_class": raw.get("asset_class"),
            "asset_id": raw.get("asset_id"),
        }

    # ------------------------------------------------------------------
    # ASSET LOOKUP
    # ------------------------------------------------------------------

    def get_asset(self, symbol: str) -> Dict[str, Any]:
        if not self.is_connected:
            try:
                from services.investment_ai_tool_service import STOCK_DATABASE
                s = STOCK_DATABASE.get(symbol.upper())
                if s:
                    return {"symbol": symbol.upper(), "name": s.get("name"), "class": "us_equity", "tradable": True, "fractionable": True, "source": "static"}
            except Exception:
                pass
            return {"error": f"Asset {symbol} not found"}
        raw = self._trade_request("GET", f"/assets/{symbol.upper()}")
        if not raw or "error" in raw:
            return raw or {"error": f"Asset {symbol} not found"}
        return {
            "id": raw.get("id"), "symbol": raw.get("symbol"), "name": raw.get("name"),
            "class": raw.get("class"), "exchange": raw.get("exchange"),
            "status": raw.get("status"), "tradable": raw.get("tradable"),
            "marginable": raw.get("marginable"), "shortable": raw.get("shortable"),
            "fractionable": raw.get("fractionable"), "easy_to_borrow": raw.get("easy_to_borrow"),
        }

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
        if not self.is_connected:
            return {"period": period, "timeframe": "1D", "base_value": 0, "points": [], "count": 0, "current_equity": 0, "total_pnl": 0, "total_pnl_pct": 0, "connected": False}
        cache_key = f"port_hist:{period}:{timeframe}"
        cached = self._cached(cache_key, 120.0)
        if cached:
            return cached
        raw = self._trade_request("GET", f"/account/portfolio/history?period={period}&timeframe={timeframe}")
        if not raw or "error" in raw:
            return {"period": period, "timeframe": "1D", "base_value": 0, "points": [], "count": 0, "current_equity": 0, "total_pnl": 0, "total_pnl_pct": 0, "connected": False}
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

    # _demo_portfolio_history removed — live data only

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
        if not self.is_connected:
            return []
        raw = self._trade_request("GET", "/watchlists")
        if not raw or not isinstance(raw, list):
            return []
        return [{"id": w.get("id"), "name": w.get("name"), "symbols": [a.get("symbol") for a in w.get("assets", [])]} for w in raw]

    def create_watchlist(self, name: str, symbols: List[str]) -> Dict[str, Any]:
        if not self.is_connected:
            return self._not_connected_error()
        return self._trade_request("POST", "/watchlists", {"name": name, "symbols": symbols}) or {}

    def add_to_watchlist(self, watchlist_id: str, symbol: str) -> Dict[str, Any]:
        if not self.is_connected:
            return {"success": True}
        return self._trade_request("POST", f"/watchlists/{watchlist_id}", {"symbol": symbol}) or {}

    def remove_from_watchlist(self, watchlist_id: str, symbol: str) -> Dict[str, Any]:
        if not self.is_connected:
            return self._not_connected_error()
        return self._trade_request("DELETE", f"/watchlists/{watchlist_id}/{symbol}") or {}

    def get_watchlist_by_id(self, watchlist_id: str) -> Dict[str, Any]:
        if not self.is_connected:
            return self._not_connected_error()
        raw = self._trade_request("GET", f"/watchlists/{watchlist_id}")
        if not raw or "error" in raw:
            return raw or {}
        return {"id": raw.get("id"), "name": raw.get("name"), "symbols": [a.get("symbol") for a in raw.get("assets", [])]}

    def update_watchlist(self, watchlist_id: str, name: Optional[str] = None, symbols: Optional[List[str]] = None) -> Dict[str, Any]:
        if not self.is_connected:
            return self._not_connected_error()
        body: Dict[str, Any] = {}
        if name:
            body["name"] = name
        if symbols is not None:
            body["symbols"] = symbols
        return self._trade_request("PUT", f"/watchlists/{watchlist_id}", body) or {}

    def delete_watchlist(self, watchlist_id: str) -> Dict[str, Any]:
        if not self.is_connected:
            return self._not_connected_error()
        return self._trade_request("DELETE", f"/watchlists/{watchlist_id}") or {}

    # ==================================================================
    # MARKET CLOCK & ASSETS
    # ==================================================================

    def get_clock(self) -> Dict[str, Any]:
        if not self.is_connected:
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

    def get_calendar(self, start: str = "", end: str = "") -> List[Dict[str, Any]]:
        if not self.is_connected:
            return []
        params = "?"
        if start:
            params += f"start={start}&"
        if end:
            params += f"end={end}&"
        raw = self._trade_request("GET", f"/calendar{params.rstrip('&?')}")
        return raw if isinstance(raw, list) else []

    def get_corporate_actions(self, symbols: str = "", types: str = "", limit: int = 20) -> List[Dict[str, Any]]:
        if not self.is_connected:
            return []
        params = f"?limit={limit}"
        if symbols:
            params += f"&symbols={symbols}"
        if types:
            params += f"&types={types}"
        raw = self._trade_request("GET", f"/corporate-actions/announcements{params}")
        return raw if isinstance(raw, list) else []

    # ------------------------------------------------------------------
    # STOCK MARKET DATA (full MCP alignment)
    # ------------------------------------------------------------------

    def get_stock_quote(self, symbol: str, start: str = "", end: str = "", limit: int = 100) -> Optional[Dict]:
        params: Dict[str, str] = {"limit": str(limit), "feed": "iex"}
        if start:
            params["start"] = start
        if end:
            params["end"] = end
        return self._data_request(f"/v2/stocks/{symbol.upper()}/quotes", params)

    def get_stock_trades(self, symbol: str, start: str = "", end: str = "", limit: int = 100) -> Optional[Dict]:
        params: Dict[str, str] = {"limit": str(limit), "feed": "iex"}
        if start:
            params["start"] = start
        if end:
            params["end"] = end
        return self._data_request(f"/v2/stocks/{symbol.upper()}/trades", params)

    def get_stock_latest_bar(self, symbol: str) -> Optional[Dict]:
        return self._data_request(f"/v2/stocks/{symbol.upper()}/bars/latest", {"feed": "iex"})

    # ------------------------------------------------------------------
    # CRYPTO MARKET DATA (full MCP alignment)
    # ------------------------------------------------------------------

    def get_crypto_bars(self, symbol: str, timeframe: str = "1Day", limit: int = 100) -> Optional[Dict]:
        loc = symbol.upper().replace("/", "%2F") if "/" in symbol else f"{symbol.upper()}%2FUSD"
        return self._data_request(f"/v1beta3/crypto/us/bars", {"symbols": symbol.upper().replace("/", "%2F") if "/" in symbol else f"{symbol.upper()}/USD", "timeframe": timeframe, "limit": str(limit)})

    def get_crypto_quotes(self, symbol: str, limit: int = 100) -> Optional[Dict]:
        sym = symbol.upper() if "/" in symbol else f"{symbol.upper()}/USD"
        return self._data_request(f"/v1beta3/crypto/us/quotes", {"symbols": sym, "limit": str(limit)})

    def get_crypto_trades(self, symbol: str, limit: int = 100) -> Optional[Dict]:
        sym = symbol.upper() if "/" in symbol else f"{symbol.upper()}/USD"
        return self._data_request(f"/v1beta3/crypto/us/trades", {"symbols": sym, "limit": str(limit)})

    def get_crypto_latest_quote(self, symbol: str) -> Optional[Dict]:
        sym = symbol.upper() if "/" in symbol else f"{symbol.upper()}/USD"
        return self._data_request(f"/v1beta3/crypto/us/latest/quotes", {"symbols": sym})

    def get_crypto_latest_bar(self, symbol: str) -> Optional[Dict]:
        sym = symbol.upper() if "/" in symbol else f"{symbol.upper()}/USD"
        return self._data_request(f"/v1beta3/crypto/us/latest/bars", {"symbols": sym})

    def get_crypto_latest_trade(self, symbol: str) -> Optional[Dict]:
        sym = symbol.upper() if "/" in symbol else f"{symbol.upper()}/USD"
        return self._data_request(f"/v1beta3/crypto/us/latest/trades", {"symbols": sym})

    def get_crypto_snapshot(self, symbol: str) -> Optional[Dict]:
        sym = symbol.upper() if "/" in symbol else f"{symbol.upper()}/USD"
        return self._data_request(f"/v1beta3/crypto/us/snapshots", {"symbols": sym})

    def get_crypto_orderbook(self, symbol: str) -> Optional[Dict]:
        sym = symbol.upper() if "/" in symbol else f"{symbol.upper()}/USD"
        return self._data_request(f"/v1beta3/crypto/us/latest/orderbooks", {"symbols": sym})

    # ------------------------------------------------------------------
    # OPTIONS MARKET DATA (full MCP alignment)
    # ------------------------------------------------------------------

    def get_option_contracts(self, underlying_symbol: str = "", expiration_date: str = "", option_type: str = "", strike_price_gte: Optional[float] = None, strike_price_lte: Optional[float] = None, limit: int = 50) -> Optional[Dict]:
        params: Dict[str, str] = {"limit": str(limit)}
        if underlying_symbol:
            params["underlying_symbols"] = underlying_symbol.upper()
        if expiration_date:
            params["expiration_date"] = expiration_date
        if option_type:
            params["type"] = option_type
        if strike_price_gte is not None:
            params["strike_price_gte"] = str(strike_price_gte)
        if strike_price_lte is not None:
            params["strike_price_lte"] = str(strike_price_lte)
        return self._data_request(f"/v2/options/contracts", params)

    def get_option_latest_quote(self, symbol: str) -> Optional[Dict]:
        return self._data_request(f"/v2/options/quotes/latest", {"symbols": symbol.upper(), "feed": "indicative"})

    def get_option_snapshot(self, symbol: str) -> Optional[Dict]:
        return self._data_request(f"/v2/options/snapshots", {"symbols": symbol.upper(), "feed": "indicative"})

    # ------------------------------------------------------------------
    # CRYPTO + OPTIONS TRADING (full MCP alignment)
    # ------------------------------------------------------------------

    def place_crypto_order(self, symbol: str, side: str, qty: Optional[float] = None, notional: Optional[float] = None, order_type: str = "market", time_in_force: str = "gtc", limit_price: Optional[float] = None) -> Dict[str, Any]:
        if not self.is_connected:
            return self._not_connected_error()
        sym = symbol.upper() if "/" in symbol else f"{symbol.upper()}/USD"
        body: Dict[str, Any] = {"symbol": sym, "side": side.lower(), "type": order_type, "time_in_force": time_in_force}
        if qty is not None:
            body["qty"] = str(qty)
        elif notional is not None:
            body["notional"] = str(notional)
        if limit_price is not None:
            body["limit_price"] = str(limit_price)
        raw = self._trade_request("POST", "/orders", body)
        if raw and "error" not in raw:
            self._record_trade_to_ledger({"symbol": sym, "side": side, "qty": str(qty or ""), "status": raw.get("status"), "broker": "alpaca", "order_id": raw.get("id")})
            self._cache.pop("positions", None)
        return raw or {"error": "Crypto order failed"}

    def place_option_order(self, symbol: str, side: str, qty: float, order_type: str = "market", time_in_force: str = "day", limit_price: Optional[float] = None) -> Dict[str, Any]:
        if not self.is_connected:
            return self._not_connected_error()
        body: Dict[str, Any] = {"symbol": symbol.upper(), "side": side.lower(), "qty": str(qty), "type": order_type, "time_in_force": time_in_force}
        if limit_price is not None:
            body["limit_price"] = str(limit_price)
        raw = self._trade_request("POST", "/orders", body)
        if raw and "error" not in raw:
            self._record_trade_to_ledger({"symbol": symbol, "side": side, "qty": str(qty), "status": raw.get("status"), "broker": "alpaca", "order_id": raw.get("id"), "type": "option"})
            self._cache.pop("positions", None)
        return raw or {"error": "Option order failed"}

    def search_assets(self, query: str = "", asset_class: str = "us_equity", status: str = "active") -> List[Dict[str, Any]]:
        if not self.is_connected:
            from services.ai_trading_engine import UNIVERSE
            all_syms = [s for syms in UNIVERSE.values() for s in syms if "/" not in s]
            q = query.upper()
            return [{"symbol": s, "name": s, "asset_class": "us_equity", "tradable": True} for s in all_syms if q in s][:20]
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
        if not self.is_connected:
            return []
        params = f"?page_size={limit}"
        if activity_type:
            params += f"&activity_type={activity_type}"
        raw = self._trade_request("GET", f"/account/activities{params}")
        if not raw or not isinstance(raw, list):
            return []
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

    # _demo_activities removed — live data only

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
        position_snapshot = self._get_position_snapshot(symbol) if side.lower() == "sell" else None
        if not self.is_connected:
            return self._not_connected_error()
        raw = self._trade_request("POST", "/orders", body)
        if not raw:
            return {"error": "Bracket order failed"}
        if "error" in raw:
            return raw
        self._cache.pop("positions", None)
        self._cache.pop("account", None)
        result = {
            "order_id": raw.get("id"),
            "symbol": raw.get("symbol"),
            "side": raw.get("side"),
            "qty": raw.get("qty"),
            "type": "bracket",
            "status": raw.get("status"),
            "filled_avg_price": raw.get("filled_avg_price"),
            "legs": raw.get("legs", []),
            "broker": "alpaca",
        }
        self._record_trade_to_ledger(result, position_snapshot=position_snapshot)
        return result

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
        if not self.is_connected:
            return self._not_connected_error()
        position_snapshot = self._get_position_snapshot(symbol)
        raw = self._trade_request("POST", "/orders", body)
        if not raw:
            return {"error": "OCO order failed"}
        if "error" in raw:
            return raw
        self._cache.pop("positions", None)
        self._cache.pop("account", None)
        result = {
            "order_id": raw.get("id"),
            "symbol": raw.get("symbol"),
            "side": raw.get("side"),
            "qty": raw.get("qty"),
            "type": "oco",
            "status": raw.get("status"),
            "filled_avg_price": raw.get("filled_avg_price"),
            "legs": raw.get("legs", []),
            "broker": "alpaca",
        }
        self._record_trade_to_ledger(result, position_snapshot=position_snapshot)
        return result

    # ==================================================================
    # GLOBAL BENCHMARKS
    # ==================================================================

    def get_global_dashboard(self) -> Dict[str, Any]:
        """
        Bloomberg-style global market overview — 100% live Alpaca data.
        Returns only what we can fetch in real-time. No mock/baseline fallback.
        """
        cached = self._cached("global_dash", 60.0)
        if cached:
            return cached

        live_prices = self._fetch_global_prices()

        dashboard: Dict[str, List[Dict]] = {}
        for category_key in GLOBAL_BENCHMARKS:
            dashboard[category_key] = []

        for category_key, category_data in GLOBAL_BENCHMARKS.items():
            for sym, meta in category_data.items():
                live = live_prices.get(sym, {})
                price = live.get("price")
                change = live.get("change_pct")
                dashboard[category_key].append({
                    "symbol": sym,
                    "name": meta["name"],
                    "price": price,
                    "change_pct": change,
                    "region": meta.get("region"),
                    "source": "live" if price else "unavailable",
                })

        result = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "dashboard": dashboard,
            "broker_connected": self._connected,
            "paper_mode": self.is_paper,
        }
        self._set_cache("global_dash", result)
        return result

    def _fetch_global_prices(self) -> Dict[str, Dict[str, Any]]:
        """
        Fetch real-time prices for all global benchmarks.
        Strategy: use EVERY available source, spaced to avoid rate limits.
        1. Alpaca Data API multi-snapshot (all equities in 1 call — no rate limit)
        2. Alpaca Data API crypto snapshots (1 call for all crypto)
        3. Alpha Vantage equity quotes (spaced 1.5s apart for premium)
        4. Alpha Vantage crypto exchange rates
        5. Baseline always available as final fallback
        """
        prices: Dict[str, Dict[str, Any]] = {}

        all_syms = []
        for cat in GLOBAL_BENCHMARKS.values():
            all_syms.extend(cat.keys())
        equity_syms = [s for s in all_syms if "/" not in s]
        crypto_syms = [s for s in all_syms if "/" in s]

        # Source 1: Alpaca Data API multi-snapshot (ONE call, all equities)
        # This works even without a trading account — data API is separate
        try:
            snap_data = self._data_request(
                f"/v2/stocks/snapshots",
                {"symbols": ",".join(equity_syms), "feed": "iex"},
            )
            if snap_data and isinstance(snap_data, dict):
                for sym, data in snap_data.items():
                    trade = data.get("latestTrade", {})
                    daily = data.get("dailyBar", {})
                    prev = data.get("prevDailyBar", {})
                    price = _sf(trade.get("p")) or _sf(daily.get("c"))
                    if price and price > 0:
                        prev_close = _sf(prev.get("c"))
                        change_pct = None
                        if prev_close and prev_close > 0:
                            change_pct = f"{((price - prev_close) / prev_close * 100):+.2f}"
                        prices[sym] = {"price": price, "change_pct": change_pct}
        except Exception as e:
            print(f"[TradingPlatform] Alpaca snapshot failed: {e}")

        # Source 2: Alpaca Data API crypto snapshots (ONE call, all crypto)
        try:
            crypto_data = self._data_request(
                f"/v1beta3/crypto/us/snapshots",
                {"symbols": ",".join(s if "/" in s else f"{s}/USD" for s in crypto_syms)},
            )
            if crypto_data and isinstance(crypto_data, dict):
                snap_map = crypto_data.get("snapshots", crypto_data)
                for api_sym, data in snap_map.items():
                    trade = data.get("latestTrade", {})
                    daily = data.get("dailyBar", {})
                    price = _sf(trade.get("p")) or _sf(daily.get("c"))
                    if price and price > 0:
                        display_sym = api_sym if "/" in api_sym else f"{api_sym}/USD"
                        for orig_sym in crypto_syms:
                            if orig_sym.replace("/USD", "") == api_sym.replace("/USD", ""):
                                display_sym = orig_sym
                                break
                        prices[display_sym] = {"price": price, "change_pct": None}
        except Exception as e:
            print(f"[TradingPlatform] Alpaca crypto snapshot failed: {e}")

        # Source 3: Alpha Vantage for any symbols still missing
        missing = [s for s in all_syms if s not in prices]
        if missing:
            try:
                from services.alpha_vantage_service import get_alpha_vantage_service
                av = get_alpha_vantage_service()
            except Exception:
                av = None

            if av:
                for sym in missing:
                    if "/" in sym:
                        av_sym = _AV_SYMBOL_MAP.get(sym, sym.split("/")[0])
                        try:
                            cr = av.get_crypto_exchange_rate(av_sym, "USD")
                            if cr and cr.get("exchange_rate"):
                                prices[sym] = {"price": cr["exchange_rate"], "change_pct": None}
                        except Exception:
                            pass
                    else:
                        try:
                            q = av.get_quote(sym)
                            if q and q.get("price"):
                                prices[sym] = {"price": q["price"], "change_pct": q.get("change_percent")}
                        except Exception:
                            pass
                    time.sleep(0.8)

        # Cache live prices for cross-module access
        for sym, data in prices.items():
            if data.get("price"):
                _LIVE_PRICE_CACHE[sym] = data

        return prices

    # ==================================================================
    # AI COPILOT
    # ==================================================================

    def ai_copilot_analyze(self, symbol: str, context: str = "") -> Dict[str, Any]:
        """
        AI Copilot: real-time analysis powered by live Alpaca data.
        Uses ai_trading_engine for technicals and signals — zero mock data.
        """
        from services.ai_trading_engine import compute_technicals, generate_signals, compute_risk_metrics

        sym = symbol.upper()

        # Fetch live bars from Alpaca
        bars_raw = self.get_bars(sym, timeframe="1Day", limit=100)
        if not bars_raw:
            return {"error": f"No market data available for {sym}. Verify symbol and Alpaca connection."}

        # Compute real technicals from live bars
        technicals = compute_technicals(bars_raw)
        indicators = technicals.get("indicators", {})

        latest_bar = bars_raw[-1] if bars_raw else {}
        price = _sf(latest_bar.get("close")) or 0
        if not price or price <= 0:
            return {"error": f"No live price for {sym}"}

        # Generate AI signals from real technicals
        signals = generate_signals(technicals, price)
        recommendation = signals.get("recommendation", "HOLD")
        score = signals.get("composite_score", 0)
        confidence = signals.get("confidence", 0)

        # Risk metrics from real data
        positions = self.get_positions()
        risk = compute_risk_metrics(bars_raw, positions)

        # Current position
        current_position = None
        for pos in positions:
            if pos.get("symbol") == sym:
                current_position = pos
                break

        account = self.get_account()
        buying_power = _sf(account.get("buying_power")) or 0

        risk_pct = 0.02
        if abs(score) >= 3:
            risk_pct = 0.03
        elif abs(score) <= 1:
            risk_pct = 0.01

        portfolio_val = _sf(account.get("portfolio_value")) or _sf(account.get("equity")) or 0
        max_trade_value = portfolio_val * risk_pct if portfolio_val > 0 else 0
        suggested_qty = int(max_trade_value / price) if price > 0 else 0

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
            if (_sf(current_position.get("unrealized_pl")) or 0) > 0:
                copilot_action = "take_profit"

        atr = _sf(indicators.get("atr_14"))
        stop_loss = round(price - (atr * 2), 2) if atr and atr > 0 else round(price * 0.97, 2)
        take_profit = round(price + (atr * 3), 2) if atr and atr > 0 else round(price * 1.06, 2)

        # Try to get news from investment AI if available
        news_data = {}
        try:
            from services.investment_ai_tool_service import _get_live_news
            news_raw = _get_live_news(sym)
            if news_raw:
                articles = (news_raw or {}).get("articles", [])[:3]
                scores_list = [a.get("overall_sentiment_score", 0) for a in articles if a.get("overall_sentiment_score")]
                sentiment_avg = sum(scores_list) / len(scores_list) if scores_list else 0
                news_data = {
                    "avg_score": round(sentiment_avg, 3),
                    "label": "bullish" if sentiment_avg > 0.1 else ("bearish" if sentiment_avg < -0.1 else "neutral"),
                    "articles": articles,
                }
        except Exception:
            news_data = {"avg_score": 0, "label": "unavailable", "articles": []}

        return {
            "symbol": sym,
            "price": price,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "ai_recommendation": recommendation,
            "composite_score": score,
            "confidence": round(confidence, 2),
            "copilot_action": copilot_action,
            "signal_details": signals.get("details", []),
            "technicals": {
                "rsi": indicators.get("rsi_14"),
                "macd": indicators.get("macd_line"),
                "macd_signal": indicators.get("macd_signal"),
                "macd_histogram": indicators.get("macd_histogram"),
                "bb_upper": indicators.get("bb_upper"),
                "bb_middle": indicators.get("bb_middle"),
                "bb_lower": indicators.get("bb_lower"),
                "bb_width": indicators.get("bb_width"),
                "sma_20": indicators.get("sma_20"),
                "sma_50": indicators.get("sma_50"),
                "ema_12": indicators.get("ema_12"),
                "ema_26": indicators.get("ema_26"),
                "atr": indicators.get("atr_14"),
                "obv": indicators.get("obv"),
                "vwap": indicators.get("vwap"),
                "stoch_k": indicators.get("stoch_k"),
                "stoch_d": indicators.get("stoch_d"),
                "volume_ratio": indicators.get("volume_ratio"),
            },
            "risk_metrics": risk,
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
            "news_sentiment": news_data,
            "bars_count": len(bars_raw),
            "data_source": "alpaca_live",
        }

    # ==================================================================
    # LIVE-ONLY MODE (no mock data — broker connection required)
    # ==================================================================

    def _not_connected_account(self) -> Dict[str, Any]:
        self._reload_keys()
        api_key_status = "(set)" if os.environ.get("ALPACA_API_KEY") else "(NOT SET)"
        secret_status = "(set)" if os.environ.get("ALPACA_SECRET_KEY") else "(NOT SET)"
        return {
            "account_id": None,
            "status": "NOT_CONNECTED",
            "currency": "USD",
            "buying_power": 0, "cash": 0, "portfolio_value": 0, "equity": 0,
            "last_equity": 0, "long_market_value": 0, "short_market_value": 0,
            "unrealized_pl": 0, "unrealized_pl_pct": 0,
            "day_trade_count": 0, "pattern_day_trader": False,
            "trading_blocked": True,
            "paper": False, "broker": "none", "connected": False,
            "message": f"Broker not connected. ALPACA_API_KEY {api_key_status}, ALPACA_SECRET_KEY {secret_status}.",
            "debug": {
                "api_key_env": api_key_status,
                "secret_key_env": secret_status,
                "api_key_len": len(os.environ.get("ALPACA_API_KEY", "")),
                "secret_key_len": len(os.environ.get("ALPACA_SECRET_KEY", "")),
            },
        }

    def _not_connected_error(self) -> Dict[str, Any]:
        api_key_status = "(set)" if os.environ.get("ALPACA_API_KEY") else "(NOT SET)"
        secret_status = "(set)" if os.environ.get("ALPACA_SECRET_KEY") else "(NOT SET)"
        return {
            "error": f"Broker not connected. ALPACA_API_KEY {api_key_status}, ALPACA_SECRET_KEY {secret_status}. "
                     f"Add both as Railway environment variables and redeploy.",
            "connected": False,
            "debug": {
                "api_key_env": api_key_status,
                "secret_key_env": secret_status,
                "api_key_len": len(os.environ.get("ALPACA_API_KEY", "")),
                "secret_key_len": len(os.environ.get("ALPACA_SECRET_KEY", "")),
            },
        }

    # ==================================================================
    # LEDGER INTEGRATION — record all trades to PHINS transaction ledger
    # ==================================================================

    def _record_trade_to_ledger(
        self,
        order_result: Dict,
        customer_id: str = "TERMINAL",
        position_snapshot: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Record a completed trade to TRANSACTION_LEDGER + NFT ledger."""
        if not order_result or "error" in order_result:
            return
        try:
            import web_portal.server as portal
            symbol = order_result.get("symbol", "")
            side = order_result.get("side", "")
            qty = order_result.get("qty") or order_result.get("filled_qty") or "0"
            price = order_result.get("filled_avg_price") or "0"
            qty_float = _sf(qty) or 0
            price_float = _sf(price) or 0
            amount = qty_float * price_float if qty_float and price_float else 0
            realized_gain = 0.0
            estimated_cost_basis = 0.0

            if side == "sell" and position_snapshot and position_snapshot.get("side") != "short":
                position_qty = abs(_sf(position_snapshot.get("qty")) or 0)
                matched_qty = min(qty_float, position_qty)
                avg_entry_price = _sf(position_snapshot.get("avg_entry_price"))
                if avg_entry_price is None and position_qty > 0:
                    avg_entry_price = (_sf(position_snapshot.get("cost_basis")) or 0) / position_qty
                avg_entry_price = avg_entry_price or 0
                estimated_cost_basis = matched_qty * avg_entry_price
                realized_gain = (matched_qty * price_float) - estimated_cost_basis

            portal.record_transaction(
                customer_id=customer_id,
                tx_type=f"trade_{side}",
                amount=amount,
                description=f"Terminal trade: {side.upper()} {qty} {symbol} @ ${price}",
                metadata={
                    "order_id": order_result.get("order_id"),
                    "symbol": symbol,
                    "side": side,
                    "qty": qty,
                    "price": price,
                    "estimated_cost_basis": round(estimated_cost_basis, 2),
                    "realized_gain": round(realized_gain, 2),
                    "order_type": order_result.get("type"),
                    "status": order_result.get("status"),
                    "broker": order_result.get("broker", "alpaca"),
                    "source_system": "trading_terminal",
                    "actor": customer_id,
                },
            )
        except Exception as e:
            print(f"[TradingPlatform] Ledger record failed: {e}")

    # ==================================================================
    # PRE-TAX BALANCE SHEET
    # ==================================================================

    def get_pretax_balance_sheet(self, customer_id: str = "TERMINAL") -> Dict[str, Any]:
        """
        Individual pre-tax balance sheet from live broker data + ledger.
        Assets: cash + positions at market value.
        Liabilities: short positions (if any).
        Income: realized gains from ledger.
        """
        account = self.get_account()
        positions = self.get_positions()

        cash = _sf(account.get("cash")) or 0
        long_value = sum(_sf(p.get("market_value")) or 0 for p in positions if p.get("side") != "short")
        short_value = abs(sum(_sf(p.get("market_value")) or 0 for p in positions if p.get("side") == "short"))
        total_cost = sum(_sf(p.get("cost_basis")) or 0 for p in positions)
        unrealized_gains = sum(_sf(p.get("unrealized_pl")) or 0 for p in positions)
        unrealized_gains_positive = sum(_sf(p.get("unrealized_pl")) or 0 for p in positions if (_sf(p.get("unrealized_pl")) or 0) > 0)
        unrealized_losses = sum(_sf(p.get("unrealized_pl")) or 0 for p in positions if (_sf(p.get("unrealized_pl")) or 0) < 0)

        # Realized gains from ledger
        realized_gains = 0
        realized_count = 0
        try:
            import web_portal.server as portal
            for tx in portal.TRANSACTION_LEDGER.values():
                if tx.get("type") in ("trade_sell",) and tx.get("customer_id") == customer_id:
                    metadata = tx.get("metadata", {}) if isinstance(tx.get("metadata"), dict) else {}
                    realized_gains += _sf(metadata.get("realized_gain")) or 0
                    realized_count += 1
        except Exception:
            pass

        total_assets = cash + long_value
        total_liabilities = short_value
        net_worth = total_assets - total_liabilities
        equity = _sf(account.get("equity")) or net_worth

        # Tax estimates (simplified US rates)
        short_term_rate = 0.37
        long_term_rate = 0.20
        est_tax_on_unrealized = unrealized_gains_positive * short_term_rate if unrealized_gains_positive > 0 else 0
        est_tax_on_realized = realized_gains * short_term_rate if realized_gains > 0 else 0

        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "customer_id": customer_id,
            "assets": {
                "cash": round(cash, 2),
                "long_positions_value": round(long_value, 2),
                "total_assets": round(total_assets, 2),
            },
            "liabilities": {
                "short_positions_value": round(short_value, 2),
                "total_liabilities": round(total_liabilities, 2),
            },
            "equity": {
                "net_worth": round(net_worth, 2),
                "broker_equity": round(equity, 2),
                "cost_basis": round(total_cost, 2),
            },
            "gains_losses": {
                "unrealized_total": round(unrealized_gains, 2),
                "unrealized_gains": round(unrealized_gains_positive, 2),
                "unrealized_losses": round(unrealized_losses, 2),
                "realized_total": round(realized_gains, 2),
                "realized_trade_count": realized_count,
            },
            "tax_estimates": {
                "short_term_rate": f"{short_term_rate*100}%",
                "long_term_rate": f"{long_term_rate*100}%",
                "est_tax_unrealized": round(est_tax_on_unrealized, 2),
                "est_tax_realized": round(est_tax_on_realized, 2),
                "total_est_tax": round(est_tax_on_unrealized + est_tax_on_realized, 2),
                "after_tax_equity": round(net_worth - est_tax_on_unrealized - est_tax_on_realized, 2),
            },
            "positions": [
                {
                    "symbol": p.get("symbol"),
                    "qty": _sf(p.get("qty")),
                    "side": p.get("side"),
                    "cost_basis": _sf(p.get("cost_basis")),
                    "market_value": _sf(p.get("market_value")),
                    "unrealized_pl": _sf(p.get("unrealized_pl")),
                }
                for p in positions
            ],
            "connected": self._connected,
        }

    # ==================================================================
    # DATA INTEGRITY — reconcile broker vs ledger
    # ==================================================================

    def reconcile_integrity(self, customer_id: str = "TERMINAL") -> Dict[str, Any]:
        """
        Validate data integrity: compare broker positions with ledger entries.
        """
        positions = self.get_positions()
        account = self.get_account()

        ledger_trades = []
        try:
            import web_portal.server as portal
            for tx_id, tx in portal.TRANSACTION_LEDGER.items():
                if tx.get("customer_id") == customer_id and tx.get("type", "").startswith("trade_"):
                    ledger_trades.append(tx)
        except Exception:
            pass

        broker_symbols = {p.get("symbol") for p in positions}
        ledger_symbols = {tx.get("metadata", {}).get("symbol") for tx in ledger_trades if tx.get("metadata")}

        in_broker_not_ledger = broker_symbols - ledger_symbols
        in_ledger_not_broker = ledger_symbols - broker_symbols - {None, ""}

        issues = []
        if in_broker_not_ledger:
            issues.append({"type": "broker_only", "symbols": list(in_broker_not_ledger), "message": "Positions in broker but no ledger entry — may predate ledger integration"})
        if in_ledger_not_broker:
            issues.append({"type": "ledger_only", "symbols": list(in_ledger_not_broker), "message": "Ledger entries but no broker position — positions may have been closed"})

        broker_value = sum(_sf(p.get("market_value")) or 0 for p in positions)
        broker_equity = _sf(account.get("equity")) or 0

        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "status": "clean" if not issues else "discrepancies_found",
            "broker_positions": len(positions),
            "ledger_trades": len(ledger_trades),
            "broker_equity": round(broker_equity, 2),
            "broker_position_value": round(broker_value, 2),
            "issues": issues,
            "connected": self._connected,
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
        if not self.is_connected:
            return self._not_connected_error()
        return self._broker_request("POST", "/accounts", account_data) or {"error": "Account creation failed"}

    def broker_get_accounts(self) -> List[Dict[str, Any]]:
        if not self.is_connected:
            return []
        raw = self._broker_request("GET", "/accounts")
        if isinstance(raw, list):
            return raw
        return [raw] if raw and "error" not in raw else []

    def broker_get_account(self, account_id: str) -> Dict[str, Any]:
        if not self.is_connected:
            return {"id": account_id, "status": "ACTIVE", "currency": "USD"}
        return self._broker_request("GET", f"/accounts/{account_id}") or {}

    def broker_create_ach_relationship(self, account_id: str, ach_data: Dict) -> Dict[str, Any]:
        """Establish ACH bank relationship for funding."""
        if not self.is_connected:
            return self._not_connected_error()
        return self._broker_request("POST", f"/accounts/{account_id}/ach_relationships", ach_data) or {"error": "ACH setup failed"}

    def broker_get_ach_relationships(self, account_id: str) -> List[Dict]:
        if not self.is_connected:
            return []
        raw = self._broker_request("GET", f"/accounts/{account_id}/ach_relationships")
        return raw if isinstance(raw, list) else []

    def broker_create_transfer(self, account_id: str, transfer_data: Dict) -> Dict[str, Any]:
        """Fund account via ACH transfer."""
        if not self.is_connected:
            return self._not_connected_error()
        return self._broker_request("POST", f"/accounts/{account_id}/transfers", transfer_data) or {"error": "Transfer failed"}

    def broker_create_journal(self, journal_data: Dict) -> Dict[str, Any]:
        """Journal cash/securities between accounts (instant funding)."""
        if not self.is_connected:
            return self._not_connected_error()
        return self._broker_request("POST", "/journals", journal_data) or {"error": "Journal failed"}

    def broker_submit_order(self, account_id: str, order_data: Dict) -> Dict[str, Any]:
        """Submit order for a specific broker account (v1 Broker API)."""
        if not self.is_connected:
            return self._not_connected_error()
        raw = self._broker_request("POST", f"/trading/accounts/{account_id}/orders", order_data)
        return raw or {"error": "Order failed"}

    def broker_get_assets(self, status: str = "active", asset_class: str = "") -> List[Dict]:
        """Get all tradable assets from Broker API."""
        cache_key = f"broker_assets:{status}:{asset_class}"
        cached = self._cached(cache_key, 3600.0)
        if cached:
            return cached
        if not self.is_connected:
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
# Auto-Pilot Engine singleton
# ---------------------------------------------------------------------------

_autopilot_engine = None


def get_autopilot_engine():
    global _autopilot_engine
    if _autopilot_engine is None:
        from services.ai_trading_engine import AutoPilotEngine
        _autopilot_engine = AutoPilotEngine()
    return _autopilot_engine


# ---------------------------------------------------------------------------
# Live Screener singleton
# ---------------------------------------------------------------------------

_live_screener = None


def get_live_screener():
    global _live_screener
    if _live_screener is None:
        from services.ai_trading_engine import LiveScreener
        _live_screener = LiveScreener()
    return _live_screener


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_instance: Optional[TradingPlatformService] = None


def get_trading_platform() -> TradingPlatformService:
    global _instance
    if _instance is None:
        _instance = TradingPlatformService()
    return _instance
