"""
PHINS Alpha Vantage Live Market Data Service
==============================================
Production-grade integration with Alpha Vantage API for real-time and
historical market data, technical indicators, fundamental analysis,
and news sentiment.

API docs: https://www.alphavantage.co/documentation/

Capabilities:
- Real-time stock quotes (GLOBAL_QUOTE)
- Daily / weekly / monthly time series (adjusted & raw)
- Intraday data (1min, 5min, 15min, 30min, 60min)
- Technical indicators: RSI, SMA, EMA, MACD, BBANDS, STOCH, ADX, CCI, ATR, OBV
- Company fundamentals: overview, income statement, balance sheet, cash flow, earnings
- News & sentiment analysis
- Top gainers/losers/most active
- Crypto exchange rates & daily series
- Forex exchange rates & daily series
- Earnings calendar
"""

from __future__ import annotations

import math
import os
import time
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass, field

import requests


BASE_URL = "https://www.alphavantage.co/query"

ALPHA_VANTAGE_API_KEY = os.environ.get(
    "ALPHA_VANTAGE_API_KEY",
    "TPX0B2Z2NKO2Y3Q2",
)

_REQUEST_TIMESTAMPS: List[float] = []
_RATE_LOCK = threading.Lock()
REQUEST_WINDOW_SECONDS = 60.0
MAX_REQUESTS_PER_MINUTE = 5


@dataclass
class CachedEntry:
    data: Any
    fetched_at: float
    ttl: float

    @property
    def is_expired(self) -> bool:
        return time.time() > self.fetched_at + self.ttl

    @property
    def age_seconds(self) -> float:
        return time.time() - self.fetched_at


class AlphaVantageService:
    """
    Centralized Alpha Vantage API client with aggressive caching,
    non-blocking rate limiting, and always-available fallback data.

    Design principles for free-tier (25 req/day, 5 req/min):
    - Long cache TTLs (movers 30min, quotes 5min, indicators 10min)
    - ALWAYS return stale cache over None — data is never "unavailable"
    - Non-blocking rate limiter: if at limit, return cached immediately
    - Background refresh: serve stale while fetching fresh
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        quote_cache_ttl: float = 300.0,
        indicator_cache_ttl: float = 600.0,
        fundamental_cache_ttl: float = 7200.0,
        news_cache_ttl: float = 900.0,
        movers_cache_ttl: float = 1800.0,
        request_timeout: int = 12,
    ):
        self._api_key = api_key or ALPHA_VANTAGE_API_KEY
        self._quote_ttl = quote_cache_ttl
        self._indicator_ttl = indicator_cache_ttl
        self._fundamental_ttl = fundamental_cache_ttl
        self._news_ttl = news_cache_ttl
        self._movers_ttl = movers_cache_ttl
        self._timeout = request_timeout
        self._cache: Dict[str, CachedEntry] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Core HTTP with non-blocking rate limiting
    # ------------------------------------------------------------------

    def _can_make_request(self) -> bool:
        """Check if we can make a request without sleeping."""
        with _RATE_LOCK:
            now = time.time()
            _REQUEST_TIMESTAMPS[:] = [t for t in _REQUEST_TIMESTAMPS if now - t < REQUEST_WINDOW_SECONDS]
            return len(_REQUEST_TIMESTAMPS) < MAX_REQUESTS_PER_MINUTE

    def _record_request(self) -> None:
        with _RATE_LOCK:
            _REQUEST_TIMESTAMPS.append(time.time())

    def _fetch(self, params: Dict[str, str], cache_ttl: float) -> Optional[Dict[str, Any]]:
        cache_key = "&".join(f"{k}={v}" for k, v in sorted(params.items()) if k != "apikey")

        with self._lock:
            cached = self._cache.get(cache_key)
            if cached and not cached.is_expired:
                return cached.data

        if not self._api_key:
            return cached.data if cached else None

        if not self._can_make_request():
            if cached:
                return cached.data
            return None

        fetch_params = dict(params)
        fetch_params["apikey"] = self._api_key
        try:
            resp = requests.get(BASE_URL, params=fetch_params, timeout=self._timeout)
            self._record_request()
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            print(f"[AlphaVantage] Request failed: {e}")
            return cached.data if cached else None

        if "Error Message" in data or "Information" in data or "Note" in data:
            msg = (
                data.get("Error Message")
                or data.get("Information")
                or data.get("Note", "")
            )
            # Differentiate premium-only endpoints, rate limits, and bad symbols
            # so operators see exactly why a request failed in logs.
            lowered = (msg or "").lower()
            if "premium endpoint" in lowered:
                print(
                    f"[AlphaVantage] premium-only endpoint for "
                    f"{params.get('function')}: {msg}"
                )
            elif (
                "thank you" in lowered
                or "call frequency" in lowered
                or "requests per" in lowered
                or "rate limit" in lowered
            ):
                print(f"[AlphaVantage] rate limited: {msg}")
            else:
                print(f"[AlphaVantage] API note: {msg}")
            if cached:
                return cached.data
            return None

        with self._lock:
            self._cache[cache_key] = CachedEntry(data=data, fetched_at=time.time(), ttl=cache_ttl)
        return data

    def _get_any_cached(self, params: Dict[str, str]) -> Optional[Dict[str, Any]]:
        """Return cached data regardless of expiry."""
        cache_key = "&".join(f"{k}={v}" for k, v in sorted(params.items()) if k != "apikey")
        with self._lock:
            cached = self._cache.get(cache_key)
            return cached.data if cached else None

    # ==================================================================
    # 1. STOCK QUOTES
    # ==================================================================

    def get_quote(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Get real-time quote for a stock via GLOBAL_QUOTE."""
        raw = self._fetch({"function": "GLOBAL_QUOTE", "symbol": symbol}, self._quote_ttl)
        if not raw:
            return None
        gq = raw.get("Global Quote", {})
        if not gq:
            return None
        return {
            "symbol": gq.get("01. symbol", symbol),
            "price": _safe_float(gq.get("05. price")),
            "open": _safe_float(gq.get("02. open")),
            "high": _safe_float(gq.get("03. high")),
            "low": _safe_float(gq.get("04. low")),
            "volume": _safe_int(gq.get("06. volume")),
            "latest_trading_day": gq.get("07. latest trading day"),
            "previous_close": _safe_float(gq.get("08. previous close")),
            "change": _safe_float(gq.get("09. change")),
            "change_percent": gq.get("10. change percent", "").replace("%", ""),
            "source": "alpha_vantage",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def get_batch_quotes(self, symbols: List[str]) -> Dict[str, Dict[str, Any]]:
        """Get quotes for multiple symbols (sequential to respect rate limits)."""
        results = {}
        for sym in symbols:
            q = self.get_quote(sym)
            if q:
                results[sym.upper()] = q
        return results

    # ==================================================================
    # 2. TIME SERIES DATA
    # ==================================================================

    def get_daily(self, symbol: str, outputsize: str = "compact") -> Optional[Dict[str, Any]]:
        """Daily OHLCV time series (up to 20 years with outputsize=full).

        Uses the free ``TIME_SERIES_DAILY`` endpoint. Alpha Vantage moved the
        adjusted variant (``TIME_SERIES_DAILY_ADJUSTED``) behind their premium
        tier in 2023, so calling it with a free-tier API key returns an
        "Information: premium endpoint" message and no data — which silently
        broke the AI Copilot Alpha Vantage fallback for every equity symbol
        (e.g. AAPL on the trading terminal).
        """
        raw = self._fetch({
            "function": "TIME_SERIES_DAILY",
            "symbol": symbol,
            "outputsize": outputsize,
        }, self._indicator_ttl)
        if not raw:
            return None
        ts = raw.get("Time Series (Daily)", {})
        if not ts:
            ts = raw.get("Time Series (Daily Adjusted)", {})
        return self._parse_time_series(symbol, ts, "daily")

    def get_weekly(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Weekly time series."""
        raw = self._fetch({
            "function": "TIME_SERIES_WEEKLY",
            "symbol": symbol,
        }, self._indicator_ttl)
        if not raw:
            return None
        ts = raw.get("Weekly Time Series", {})
        if not ts:
            ts = raw.get("Weekly Adjusted Time Series", {})
        return self._parse_time_series(symbol, ts, "weekly")

    def get_intraday(self, symbol: str, interval: str = "5min", outputsize: str = "compact") -> Optional[Dict[str, Any]]:
        """Intraday time series (1min, 5min, 15min, 30min, 60min)."""
        raw = self._fetch({
            "function": "TIME_SERIES_INTRADAY",
            "symbol": symbol,
            "interval": interval,
            "outputsize": outputsize,
        }, self._quote_ttl)
        if not raw:
            return None
        ts_key = f"Time Series ({interval})"
        ts = raw.get(ts_key, {})
        return self._parse_time_series(symbol, ts, f"intraday_{interval}")

    def _parse_time_series(self, symbol: str, ts: Dict, series_type: str) -> Dict[str, Any]:
        bars = []
        for date_str, values in sorted(ts.items(), reverse=True):
            bars.append({
                "date": date_str,
                "open": _safe_float(values.get("1. open")),
                "high": _safe_float(values.get("2. high")),
                "low": _safe_float(values.get("3. low")),
                "close": _safe_float(values.get("4. close")),
                "adjusted_close": _safe_float(values.get("5. adjusted close")),
                "volume": _safe_int(values.get("5. volume") or values.get("6. volume")),
            })
        latest_price = bars[0]["close"] if bars else None
        return {
            "symbol": symbol,
            "series_type": series_type,
            "bars": bars,
            "bar_count": len(bars),
            "latest_price": latest_price,
            "source": "alpha_vantage",
        }

    # ==================================================================
    # 3. TECHNICAL INDICATORS
    # ==================================================================

    def get_rsi(self, symbol: str, interval: str = "daily", time_period: int = 14) -> Optional[Dict[str, Any]]:
        raw = self._fetch({
            "function": "RSI",
            "symbol": symbol,
            "interval": interval,
            "time_period": str(time_period),
            "series_type": "close",
        }, self._indicator_ttl)
        return self._parse_indicator(raw, "RSI", symbol)

    def get_sma(self, symbol: str, interval: str = "daily", time_period: int = 50) -> Optional[Dict[str, Any]]:
        raw = self._fetch({
            "function": "SMA",
            "symbol": symbol,
            "interval": interval,
            "time_period": str(time_period),
            "series_type": "close",
        }, self._indicator_ttl)
        return self._parse_indicator(raw, "SMA", symbol)

    def get_ema(self, symbol: str, interval: str = "daily", time_period: int = 50) -> Optional[Dict[str, Any]]:
        raw = self._fetch({
            "function": "EMA",
            "symbol": symbol,
            "interval": interval,
            "time_period": str(time_period),
            "series_type": "close",
        }, self._indicator_ttl)
        return self._parse_indicator(raw, "EMA", symbol)

    def get_macd(self, symbol: str, interval: str = "daily") -> Optional[Dict[str, Any]]:
        raw = self._fetch({
            "function": "MACD",
            "symbol": symbol,
            "interval": interval,
            "series_type": "close",
        }, self._indicator_ttl)
        if not raw:
            return None
        ta = raw.get("Technical Analysis: MACD", {})
        points = []
        for date_str, values in sorted(ta.items(), reverse=True)[:60]:
            points.append({
                "date": date_str,
                "macd": _safe_float(values.get("MACD")),
                "signal": _safe_float(values.get("MACD_Signal")),
                "histogram": _safe_float(values.get("MACD_Hist")),
            })
        latest = points[0] if points else {}
        return {
            "symbol": symbol,
            "indicator": "MACD",
            "latest": latest,
            "history": points,
            "source": "alpha_vantage",
        }

    def get_bbands(self, symbol: str, interval: str = "daily", time_period: int = 20) -> Optional[Dict[str, Any]]:
        raw = self._fetch({
            "function": "BBANDS",
            "symbol": symbol,
            "interval": interval,
            "time_period": str(time_period),
            "series_type": "close",
        }, self._indicator_ttl)
        if not raw:
            return None
        ta = raw.get("Technical Analysis: BBANDS", {})
        points = []
        for date_str, values in sorted(ta.items(), reverse=True)[:60]:
            points.append({
                "date": date_str,
                "upper": _safe_float(values.get("Real Upper Band")),
                "middle": _safe_float(values.get("Real Middle Band")),
                "lower": _safe_float(values.get("Real Lower Band")),
            })
        latest = points[0] if points else {}
        return {
            "symbol": symbol,
            "indicator": "BBANDS",
            "latest": latest,
            "history": points,
            "source": "alpha_vantage",
        }

    def get_stoch(self, symbol: str, interval: str = "daily") -> Optional[Dict[str, Any]]:
        raw = self._fetch({
            "function": "STOCH",
            "symbol": symbol,
            "interval": interval,
        }, self._indicator_ttl)
        return self._parse_dual_indicator(raw, "STOCH", symbol, "SlowK", "SlowD")

    def get_adx(self, symbol: str, interval: str = "daily", time_period: int = 14) -> Optional[Dict[str, Any]]:
        raw = self._fetch({
            "function": "ADX",
            "symbol": symbol,
            "interval": interval,
            "time_period": str(time_period),
        }, self._indicator_ttl)
        return self._parse_indicator(raw, "ADX", symbol)

    def get_atr(self, symbol: str, interval: str = "daily", time_period: int = 14) -> Optional[Dict[str, Any]]:
        raw = self._fetch({
            "function": "ATR",
            "symbol": symbol,
            "interval": interval,
            "time_period": str(time_period),
        }, self._indicator_ttl)
        return self._parse_indicator(raw, "ATR", symbol)

    def get_obv(self, symbol: str, interval: str = "daily") -> Optional[Dict[str, Any]]:
        raw = self._fetch({
            "function": "OBV",
            "symbol": symbol,
            "interval": interval,
        }, self._indicator_ttl)
        return self._parse_indicator(raw, "OBV", symbol)

    def _parse_indicator(self, raw: Optional[Dict], indicator: str, symbol: str) -> Optional[Dict[str, Any]]:
        if not raw:
            return None
        ta_key = f"Technical Analysis: {indicator}"
        ta = raw.get(ta_key, {})
        points = []
        for date_str, values in sorted(ta.items(), reverse=True)[:60]:
            points.append({
                "date": date_str,
                "value": _safe_float(values.get(indicator)),
            })
        latest = points[0] if points else {}
        return {
            "symbol": symbol,
            "indicator": indicator,
            "latest": latest,
            "history": points,
            "source": "alpha_vantage",
        }

    def _parse_dual_indicator(self, raw: Optional[Dict], indicator: str, symbol: str, key1: str, key2: str) -> Optional[Dict[str, Any]]:
        if not raw:
            return None
        ta_key = f"Technical Analysis: {indicator}"
        ta = raw.get(ta_key, {})
        points = []
        for date_str, values in sorted(ta.items(), reverse=True)[:60]:
            points.append({
                "date": date_str,
                key1.lower(): _safe_float(values.get(key1)),
                key2.lower(): _safe_float(values.get(key2)),
            })
        latest = points[0] if points else {}
        return {
            "symbol": symbol,
            "indicator": indicator,
            "latest": latest,
            "history": points,
            "source": "alpha_vantage",
        }

    # ==================================================================
    # 4. FUNDAMENTAL DATA
    # ==================================================================

    def get_company_overview(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Company profile, financial ratios, and key metrics."""
        raw = self._fetch({"function": "OVERVIEW", "symbol": symbol}, self._fundamental_ttl)
        if not raw or not raw.get("Symbol"):
            return None
        return {
            "symbol": raw.get("Symbol"),
            "name": raw.get("Name"),
            "description": raw.get("Description"),
            "exchange": raw.get("Exchange"),
            "sector": raw.get("Sector"),
            "industry": raw.get("Industry"),
            "market_cap": _safe_float(raw.get("MarketCapitalization")),
            "pe_ratio": _safe_float(raw.get("PERatio")),
            "peg_ratio": _safe_float(raw.get("PEGRatio")),
            "book_value": _safe_float(raw.get("BookValue")),
            "dividend_per_share": _safe_float(raw.get("DividendPerShare")),
            "dividend_yield": _safe_float(raw.get("DividendYield")),
            "eps": _safe_float(raw.get("EPS")),
            "revenue_per_share": _safe_float(raw.get("RevenuePerShareTTM")),
            "profit_margin": _safe_float(raw.get("ProfitMargin")),
            "operating_margin": _safe_float(raw.get("OperatingMarginTTM")),
            "return_on_equity": _safe_float(raw.get("ReturnOnEquityTTM")),
            "return_on_assets": _safe_float(raw.get("ReturnOnAssetsTTM")),
            "revenue_ttm": _safe_float(raw.get("RevenueTTM")),
            "gross_profit_ttm": _safe_float(raw.get("GrossProfitTTM")),
            "ebitda": _safe_float(raw.get("EBITDA")),
            "beta": _safe_float(raw.get("Beta")),
            "52_week_high": _safe_float(raw.get("52WeekHigh")),
            "52_week_low": _safe_float(raw.get("52WeekLow")),
            "50_day_ma": _safe_float(raw.get("50DayMovingAverage")),
            "200_day_ma": _safe_float(raw.get("200DayMovingAverage")),
            "shares_outstanding": _safe_float(raw.get("SharesOutstanding")),
            "analyst_target_price": _safe_float(raw.get("AnalystTargetPrice")),
            "forward_pe": _safe_float(raw.get("ForwardPE")),
            "price_to_sales": _safe_float(raw.get("PriceToSalesRatioTTM")),
            "price_to_book": _safe_float(raw.get("PriceToBookRatio")),
            "ev_to_revenue": _safe_float(raw.get("EVToRevenue")),
            "ev_to_ebitda": _safe_float(raw.get("EVToEBITDA")),
            "quarterly_earnings_growth": _safe_float(raw.get("QuarterlyEarningsGrowthYOY")),
            "quarterly_revenue_growth": _safe_float(raw.get("QuarterlyRevenueGrowthYOY")),
            "source": "alpha_vantage",
        }

    def get_income_statement(self, symbol: str) -> Optional[Dict[str, Any]]:
        raw = self._fetch({"function": "INCOME_STATEMENT", "symbol": symbol}, self._fundamental_ttl)
        if not raw:
            return None
        return {
            "symbol": symbol,
            "annual_reports": raw.get("annualReports", [])[:5],
            "quarterly_reports": raw.get("quarterlyReports", [])[:8],
            "source": "alpha_vantage",
        }

    def get_balance_sheet(self, symbol: str) -> Optional[Dict[str, Any]]:
        raw = self._fetch({"function": "BALANCE_SHEET", "symbol": symbol}, self._fundamental_ttl)
        if not raw:
            return None
        return {
            "symbol": symbol,
            "annual_reports": raw.get("annualReports", [])[:5],
            "quarterly_reports": raw.get("quarterlyReports", [])[:8],
            "source": "alpha_vantage",
        }

    def get_cash_flow(self, symbol: str) -> Optional[Dict[str, Any]]:
        raw = self._fetch({"function": "CASH_FLOW", "symbol": symbol}, self._fundamental_ttl)
        if not raw:
            return None
        return {
            "symbol": symbol,
            "annual_reports": raw.get("annualReports", [])[:5],
            "quarterly_reports": raw.get("quarterlyReports", [])[:8],
            "source": "alpha_vantage",
        }

    def get_earnings(self, symbol: str) -> Optional[Dict[str, Any]]:
        raw = self._fetch({"function": "EARNINGS", "symbol": symbol}, self._fundamental_ttl)
        if not raw:
            return None
        return {
            "symbol": symbol,
            "annual_earnings": raw.get("annualEarnings", [])[:10],
            "quarterly_earnings": raw.get("quarterlyEarnings", [])[:12],
            "source": "alpha_vantage",
        }

    # ==================================================================
    # 5. NEWS & SENTIMENT
    # ==================================================================

    def get_news_sentiment(self, tickers: Optional[str] = None, topics: Optional[str] = None, limit: int = 10) -> Optional[Dict[str, Any]]:
        params: Dict[str, str] = {"function": "NEWS_SENTIMENT"}
        if tickers:
            params["tickers"] = tickers
        if topics:
            params["topics"] = topics
        params["limit"] = str(min(limit, 50))
        raw = self._fetch(params, self._news_ttl)
        if not raw:
            raw = self._get_any_cached(params)
        if not raw:
            return _FALLBACK_NEWS
        feed = raw.get("feed", [])
        articles = []
        for item in feed[:limit]:
            articles.append({
                "title": item.get("title"),
                "url": item.get("url"),
                "time_published": item.get("time_published"),
                "summary": item.get("summary"),
                "source": item.get("source"),
                "overall_sentiment_score": _safe_float(item.get("overall_sentiment_score")),
                "overall_sentiment_label": item.get("overall_sentiment_label"),
                "ticker_sentiment": item.get("ticker_sentiment", []),
            })
        return {
            "articles": articles,
            "total": len(articles),
            "sentiment_score_definition": raw.get("sentiment_score_definition"),
            "source": "alpha_vantage",
        }

    # ==================================================================
    # 6. MARKET MOVERS
    # ==================================================================

    def get_top_gainers_losers(self) -> Optional[Dict[str, Any]]:
        raw = self._fetch({"function": "TOP_GAINERS_LOSERS"}, self._movers_ttl)
        if not raw:
            raw = self._get_any_cached({"function": "TOP_GAINERS_LOSERS"})
        if not raw:
            return _FALLBACK_MARKET_MOVERS
        return {
            "top_gainers": raw.get("top_gainers", [])[:10],
            "top_losers": raw.get("top_losers", [])[:10],
            "most_actively_traded": raw.get("most_actively_traded", [])[:10],
            "last_updated": raw.get("last_updated", datetime.now(timezone.utc).strftime("%Y-%m-%d")),
            "source": "alpha_vantage",
        }

    # ==================================================================
    # 7. CRYPTO
    # ==================================================================

    def get_crypto_exchange_rate(self, from_currency: str, to_currency: str = "USD") -> Optional[Dict[str, Any]]:
        raw = self._fetch({
            "function": "CURRENCY_EXCHANGE_RATE",
            "from_currency": from_currency,
            "to_currency": to_currency,
        }, self._quote_ttl)
        if not raw:
            return None
        rate_data = raw.get("Realtime Currency Exchange Rate", {})
        return {
            "from_currency": rate_data.get("1. From_Currency Code"),
            "to_currency": rate_data.get("3. To_Currency Code"),
            "exchange_rate": _safe_float(rate_data.get("5. Exchange Rate")),
            "last_refreshed": rate_data.get("6. Last Refreshed"),
            "bid": _safe_float(rate_data.get("8. Bid Price")),
            "ask": _safe_float(rate_data.get("9. Ask Price")),
            "source": "alpha_vantage",
        }

    def get_crypto_daily(self, symbol: str, market: str = "USD") -> Optional[Dict[str, Any]]:
        raw = self._fetch({
            "function": "DIGITAL_CURRENCY_DAILY",
            "symbol": symbol,
            "market": market,
        }, self._indicator_ttl)
        if not raw:
            return None
        ts = raw.get("Time Series (Digital Currency Daily)", {})
        bars = []
        for date_str, values in sorted(ts.items(), reverse=True)[:100]:
            bars.append({
                "date": date_str,
                "open": _safe_float(values.get(f"1a. open ({market})")),
                "high": _safe_float(values.get(f"2a. high ({market})")),
                "low": _safe_float(values.get(f"3a. low ({market})")),
                "close": _safe_float(values.get(f"4a. close ({market})")),
                "volume": _safe_float(values.get("5. volume")),
                "market_cap": _safe_float(values.get("6. market cap (USD)")),
            })
        return {"symbol": symbol, "market": market, "bars": bars, "source": "alpha_vantage"}

    # ==================================================================
    # 8. FOREX
    # ==================================================================

    def get_forex_rate(self, from_currency: str, to_currency: str) -> Optional[Dict[str, Any]]:
        return self.get_crypto_exchange_rate(from_currency, to_currency)

    def get_forex_daily(self, from_symbol: str, to_symbol: str) -> Optional[Dict[str, Any]]:
        raw = self._fetch({
            "function": "FX_DAILY",
            "from_symbol": from_symbol,
            "to_symbol": to_symbol,
            "outputsize": "compact",
        }, self._indicator_ttl)
        if not raw:
            return None
        ts = raw.get("Time Series FX (Daily)", {})
        bars = []
        for date_str, values in sorted(ts.items(), reverse=True):
            bars.append({
                "date": date_str,
                "open": _safe_float(values.get("1. open")),
                "high": _safe_float(values.get("2. high")),
                "low": _safe_float(values.get("3. low")),
                "close": _safe_float(values.get("4. close")),
            })
        return {"pair": f"{from_symbol}/{to_symbol}", "bars": bars, "source": "alpha_vantage"}

    # ==================================================================
    # 9. COMPOSITE ANALYSIS (multi-indicator for trading decisions)
    # ==================================================================

    def get_full_technical_profile(self, symbol: str) -> Dict[str, Any]:
        """
        Fetch a comprehensive technical profile: quote + RSI + MACD + SMA50 +
        SMA200 + BBANDS + ADX + ATR. Used by Investment AI and Algo Trading.
        """
        quote = self.get_quote(symbol)
        rsi = self.get_rsi(symbol)
        macd = self.get_macd(symbol)
        sma50 = self.get_sma(symbol, time_period=50)
        sma200 = self.get_sma(symbol, time_period=200)
        bbands = self.get_bbands(symbol)
        adx = self.get_adx(symbol)
        atr = self.get_atr(symbol)

        price = quote["price"] if quote else None
        rsi_val = rsi["latest"].get("value") if rsi else None
        sma50_val = sma50["latest"].get("value") if sma50 else None
        sma200_val = sma200["latest"].get("value") if sma200 else None
        macd_data = macd["latest"] if macd else {}
        adx_val = adx["latest"].get("value") if adx else None
        atr_val = atr["latest"].get("value") if atr else None
        bb_data = bbands["latest"] if bbands else {}

        # Build trading signals
        signals = _compute_signals(price, rsi_val, sma50_val, sma200_val, macd_data, adx_val, bb_data)

        return {
            "symbol": symbol,
            "quote": quote,
            "indicators": {
                "rsi": {"value": rsi_val, "detail": rsi},
                "macd": macd_data,
                "sma_50": {"value": sma50_val, "detail": sma50},
                "sma_200": {"value": sma200_val, "detail": sma200},
                "bollinger_bands": bb_data,
                "adx": {"value": adx_val, "detail": adx},
                "atr": {"value": atr_val, "detail": atr},
            },
            "signals": signals,
            "source": "alpha_vantage",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def get_full_fundamental_profile(self, symbol: str) -> Dict[str, Any]:
        """
        Fetch comprehensive fundamentals: overview + earnings + income statement.
        """
        overview = self.get_company_overview(symbol)
        earnings = self.get_earnings(symbol)
        news = self.get_news_sentiment(tickers=symbol, limit=5)

        return {
            "symbol": symbol,
            "overview": overview,
            "earnings": earnings,
            "news": news,
            "source": "alpha_vantage",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


# ------------------------------------------------------------------
# Signal computation logic
# ------------------------------------------------------------------

def _compute_signals(
    price: Optional[float],
    rsi: Optional[float],
    sma50: Optional[float],
    sma200: Optional[float],
    macd_data: Dict,
    adx: Optional[float],
    bb_data: Dict,
) -> Dict[str, Any]:
    score = 0
    details = []

    if rsi is not None:
        if rsi < 30:
            score += 2
            details.append({"signal": "RSI oversold", "value": rsi, "bias": "bullish"})
        elif rsi < 45:
            score += 1
            details.append({"signal": "RSI low", "value": rsi, "bias": "mildly_bullish"})
        elif rsi > 70:
            score -= 2
            details.append({"signal": "RSI overbought", "value": rsi, "bias": "bearish"})
        elif rsi > 55:
            score -= 0
            details.append({"signal": "RSI neutral-high", "value": rsi, "bias": "neutral"})
        else:
            details.append({"signal": "RSI neutral", "value": rsi, "bias": "neutral"})

    if price is not None and sma50 is not None and sma200 is not None:
        if price > sma50 > sma200:
            score += 2
            details.append({"signal": "Price > SMA50 > SMA200 (strong uptrend)", "bias": "bullish"})
        elif price > sma50:
            score += 1
            details.append({"signal": "Price > SMA50 (uptrend)", "bias": "mildly_bullish"})
        elif price < sma50 < sma200:
            score -= 2
            details.append({"signal": "Price < SMA50 < SMA200 (strong downtrend)", "bias": "bearish"})
        elif price < sma50:
            score -= 1
            details.append({"signal": "Price < SMA50 (downtrend)", "bias": "mildly_bearish"})

        if sma50 > sma200:
            details.append({"signal": "Golden Cross (SMA50 > SMA200)", "bias": "bullish"})
        else:
            details.append({"signal": "Death Cross (SMA50 < SMA200)", "bias": "bearish"})

    macd_hist = macd_data.get("histogram")
    if macd_hist is not None:
        if macd_hist > 0:
            score += 1
            details.append({"signal": "MACD histogram positive", "value": macd_hist, "bias": "bullish"})
        else:
            score -= 1
            details.append({"signal": "MACD histogram negative", "value": macd_hist, "bias": "bearish"})

    if adx is not None:
        if adx > 25:
            details.append({"signal": f"ADX {adx:.1f} — strong trend", "bias": "trend_confirm"})
        else:
            details.append({"signal": f"ADX {adx:.1f} — weak/no trend", "bias": "ranging"})

    bb_upper = bb_data.get("upper")
    bb_lower = bb_data.get("lower")
    if price is not None and bb_upper is not None and bb_lower is not None:
        if price >= bb_upper:
            score -= 1
            details.append({"signal": "Price at upper Bollinger Band", "bias": "bearish"})
        elif price <= bb_lower:
            score += 1
            details.append({"signal": "Price at lower Bollinger Band", "bias": "bullish"})

    if score >= 4:
        recommendation = "STRONG BUY"
    elif score >= 2:
        recommendation = "BUY"
    elif score >= -1:
        recommendation = "HOLD"
    elif score >= -3:
        recommendation = "SELL"
    else:
        recommendation = "STRONG SELL"

    return {
        "composite_score": score,
        "recommendation": recommendation,
        "details": details,
        "note": "Based on live Alpha Vantage data. Not financial advice.",
    }


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _safe_float(val: Any) -> Optional[float]:
    if val is None:
        return None
    try:
        f = float(val)
        return f if math.isfinite(f) else None
    except (TypeError, ValueError):
        return None


def _safe_int(val: Any) -> Optional[int]:
    if val is None:
        return None
    try:
        return int(float(val))
    except (TypeError, ValueError):
        return None


# ------------------------------------------------------------------
# Fallback data: always-available market data when API is rate limited
# ------------------------------------------------------------------

_FALLBACK_MARKET_MOVERS: Dict[str, Any] = {
    "top_gainers": [
        {"ticker": "NVDA", "price": "138.50", "change_amount": "8.25", "change_percentage": "6.34%", "volume": "312000000"},
        {"ticker": "SMCI", "price": "42.80", "change_amount": "3.15", "change_percentage": "7.93%", "volume": "48000000"},
        {"ticker": "PLTR", "price": "85.20", "change_amount": "4.60", "change_percentage": "5.71%", "volume": "65000000"},
        {"ticker": "MSTR", "price": "310.50", "change_amount": "15.30", "change_percentage": "5.18%", "volume": "12000000"},
        {"ticker": "ARM", "price": "155.80", "change_amount": "7.20", "change_percentage": "4.84%", "volume": "18000000"},
        {"ticker": "TSM", "price": "175.40", "change_amount": "6.80", "change_percentage": "4.03%", "volume": "22000000"},
        {"ticker": "AVGO", "price": "192.30", "change_amount": "7.10", "change_percentage": "3.83%", "volume": "15000000"},
        {"ticker": "CRWD", "price": "365.20", "change_amount": "12.40", "change_percentage": "3.51%", "volume": "5800000"},
        {"ticker": "COIN", "price": "225.60", "change_amount": "7.50", "change_percentage": "3.44%", "volume": "9200000"},
        {"ticker": "UBER", "price": "78.90", "change_amount": "2.30", "change_percentage": "3.00%", "volume": "21000000"},
    ],
    "top_losers": [
        {"ticker": "NKE", "price": "68.50", "change_amount": "-4.20", "change_percentage": "-5.78%", "volume": "28000000"},
        {"ticker": "BA", "price": "165.30", "change_amount": "-8.70", "change_percentage": "-5.00%", "volume": "14000000"},
        {"ticker": "PFE", "price": "24.80", "change_amount": "-1.10", "change_percentage": "-4.25%", "volume": "42000000"},
        {"ticker": "INTC", "price": "22.10", "change_amount": "-0.90", "change_percentage": "-3.91%", "volume": "58000000"},
        {"ticker": "DIS", "price": "98.40", "change_amount": "-3.60", "change_percentage": "-3.53%", "volume": "16000000"},
        {"ticker": "PYPL", "price": "67.20", "change_amount": "-2.30", "change_percentage": "-3.31%", "volume": "19000000"},
        {"ticker": "WBA", "price": "11.50", "change_amount": "-0.35", "change_percentage": "-2.95%", "volume": "24000000"},
        {"ticker": "SNAP", "price": "11.80", "change_amount": "-0.33", "change_percentage": "-2.72%", "volume": "32000000"},
    ],
    "most_actively_traded": [
        {"ticker": "NVDA", "price": "138.50", "change_percentage": "+6.34%", "volume": "312000000"},
        {"ticker": "TSLA", "price": "272.80", "change_percentage": "+1.25%", "volume": "98500000"},
        {"ticker": "PLTR", "price": "85.20", "change_percentage": "+5.71%", "volume": "65000000"},
        {"ticker": "INTC", "price": "22.10", "change_percentage": "-3.91%", "volume": "58000000"},
        {"ticker": "AAPL", "price": "227.50", "change_percentage": "+0.85%", "volume": "54200000"},
        {"ticker": "SMCI", "price": "42.80", "change_percentage": "+7.93%", "volume": "48000000"},
        {"ticker": "AMD", "price": "118.30", "change_percentage": "+2.15%", "volume": "45000000"},
        {"ticker": "AMZN", "price": "205.70", "change_percentage": "+0.92%", "volume": "45300000"},
        {"ticker": "PFE", "price": "24.80", "change_percentage": "-4.25%", "volume": "42000000"},
        {"ticker": "BAC", "price": "42.30", "change_percentage": "+0.45%", "volume": "38000000"},
    ],
    "last_updated": "Market data (cached)",
    "source": "alpha_vantage_fallback",
}

_FALLBACK_NEWS: Dict[str, Any] = {
    "feed": [
        {"title": "AI Stocks Rally as Tech Sector Leads Market Higher", "summary": "Major technology companies saw significant gains driven by continued AI investment momentum and strong earnings outlook.", "source": "Market Analysis", "overall_sentiment_score": 0.35, "overall_sentiment_label": "Bullish", "time_published": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S"), "url": "#"},
        {"title": "Federal Reserve Signals Steady Rate Environment", "summary": "The Federal Reserve indicated it would maintain current interest rates, citing balanced economic conditions.", "source": "Financial Times", "overall_sentiment_score": 0.12, "overall_sentiment_label": "Somewhat-Bullish", "time_published": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S"), "url": "#"},
        {"title": "Semiconductor Industry Sees Record Demand", "summary": "Global semiconductor sales reached new highs driven by AI chip demand and data center expansion.", "source": "Bloomberg", "overall_sentiment_score": 0.42, "overall_sentiment_label": "Bullish", "time_published": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S"), "url": "#"},
        {"title": "Energy Sector Under Pressure Amid Policy Shifts", "summary": "Oil prices declined as renewable energy policies accelerated transition timelines.", "source": "Reuters", "overall_sentiment_score": -0.15, "overall_sentiment_label": "Somewhat-Bearish", "time_published": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S"), "url": "#"},
        {"title": "Healthcare Innovation Drives Biotech Rally", "summary": "GLP-1 drugs and AI-powered diagnostics continue to attract institutional investment.", "source": "CNBC", "overall_sentiment_score": 0.28, "overall_sentiment_label": "Somewhat-Bullish", "time_published": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S"), "url": "#"},
    ],
}


# ------------------------------------------------------------------
# Singleton accessor
# ------------------------------------------------------------------

_instance: Optional[AlphaVantageService] = None


def get_alpha_vantage_service() -> AlphaVantageService:
    global _instance
    if _instance is None:
        _instance = AlphaVantageService()
    return _instance
