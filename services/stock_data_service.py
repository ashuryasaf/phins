"""
PHINS Stock Data Service
========================
Shared live stock data helpers used by the trading platform and terminal:

- Alpha Vantage wrappers (quotes, technical profiles, news sentiment)
- Symbol metadata and a live-resolving STOCK_DATABASE proxy used as an
  offline/demo fallback when the broker connection is unavailable.

Data is resolved live from Alpaca bars (via the trading platform) with an
Alpha Vantage fallback, and cached briefly to avoid hammering providers.
"""

import time as _time
from typing import Any, Dict, Optional

_av_service = None

try:
    from services.alpha_vantage_service import get_alpha_vantage_service
    _av_service = get_alpha_vantage_service()
    LIVE_DATA_AVAILABLE = True
except ImportError:
    LIVE_DATA_AVAILABLE = False


def get_live_quote(symbol: str) -> Optional[Dict[str, Any]]:
    """Fetch a live quote from Alpha Vantage, returns None on failure."""
    if not LIVE_DATA_AVAILABLE or not _av_service:
        return None
    try:
        return _av_service.get_quote(symbol)
    except Exception:
        return None


def get_live_technical_profile(symbol: str) -> Optional[Dict[str, Any]]:
    """Fetch full technical profile from Alpha Vantage."""
    if not LIVE_DATA_AVAILABLE or not _av_service:
        return None
    try:
        return _av_service.get_full_technical_profile(symbol)
    except Exception:
        return None


def get_live_news(tickers: Optional[str] = None, topics: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Fetch news sentiment from Alpha Vantage."""
    if not LIVE_DATA_AVAILABLE or not _av_service:
        return None
    try:
        return _av_service.get_news_sentiment(tickers=tickers, topics=topics, limit=10)
    except Exception:
        return None


# Symbol metadata — names and sectors only. Prices, technicals, and fundamentals
# are resolved live from Alpaca bars + AI trading engine + Alpha Vantage.
_STOCK_META: Dict[str, Dict[str, str]] = {
    "AAPL": {"name": "Apple Inc.", "sector": "technology"},
    "MSFT": {"name": "Microsoft Corp.", "sector": "technology"},
    "NVDA": {"name": "NVIDIA Corp.", "sector": "technology"},
    "GOOGL": {"name": "Alphabet Inc.", "sector": "technology"},
    "AMZN": {"name": "Amazon.com Inc.", "sector": "consumer_discretionary"},
    "META": {"name": "Meta Platforms Inc.", "sector": "communication_services"},
    "TSLA": {"name": "Tesla Inc.", "sector": "consumer_discretionary"},
    "JPM": {"name": "JPMorgan Chase", "sector": "financials"},
    "JNJ": {"name": "Johnson & Johnson", "sector": "healthcare"},
    "V": {"name": "Visa Inc.", "sector": "financials"},
    "XOM": {"name": "Exxon Mobil Corp.", "sector": "energy"},
    "PG": {"name": "Procter & Gamble", "sector": "consumer_staples"},
    "HD": {"name": "Home Depot", "sector": "consumer_discretionary"},
    "UNH": {"name": "UnitedHealth Group", "sector": "healthcare"},
    "CAT": {"name": "Caterpillar Inc.", "sector": "industrials"},
    "NEE": {"name": "NextEra Energy", "sector": "utilities"},
    "O": {"name": "Realty Income Corp.", "sector": "real_estate"},
    "NFLX": {"name": "Netflix Inc.", "sector": "communication_services"},
    "BTC": {"name": "Bitcoin", "sector": "crypto"},
    "ETH": {"name": "Ethereum", "sector": "crypto"},
}

# Live data cache — populated on demand from Alpaca/Alpha Vantage
_live_stock_cache: Dict[str, Dict[str, Any]] = {}
_live_cache_ts: Dict[str, float] = {}
_LIVE_CACHE_TTL = 60.0


def _resolve_stock_data(symbol: str) -> Dict[str, Any]:
    """Resolve live stock data from Alpaca bars + Alpha Vantage.
    Returns a dict compatible with the old STOCK_DATABASE format."""
    now = _time.time()
    if symbol in _live_stock_cache and (now - _live_cache_ts.get(symbol, 0)) < _LIVE_CACHE_TTL:
        return _live_stock_cache[symbol]

    meta = _STOCK_META.get(symbol, {"name": symbol, "sector": "unknown"})
    result = {**meta, "price": 0, "pe": None, "rsi": 50, "ma50": 0, "ma200": 0,
              "volume": 0, "market_cap": 0, "dividend_yield": 0, "eps": None,
              "revenue_growth": None, "beta": 1.0, "data_source": "none"}

    # Try Alpaca bars + AI engine first
    try:
        from services.trading_platform_service import get_trading_platform
        from services.ai_trading_engine import compute_technicals
        tp = get_trading_platform()
        if tp.is_connected:
            fetch_sym = symbol.replace("/", "") if "/" in symbol else symbol
            bars = tp.get_bars(fetch_sym, "1Day", 60)
            if bars and len(bars) >= 2:
                techs = compute_technicals(bars)
                ind = techs.get("indicators", {})
                result["price"] = float(bars[-1].get("close", 0))
                result["volume"] = int(bars[-1].get("volume", 0))
                result["rsi"] = ind.get("rsi_14") or 50
                result["ma50"] = ind.get("sma_50") or result["price"]
                result["ma200"] = ind.get("sma_20") or result["price"]
                result["data_source"] = "alpaca"
                _live_stock_cache[symbol] = result
                _live_cache_ts[symbol] = now
                return result
    except Exception:
        pass

    # Fall back to Alpha Vantage
    quote = get_live_quote(symbol)
    if quote and quote.get("price"):
        result["price"] = float(quote["price"])
        result["volume"] = int(quote.get("volume", 0))
        result["data_source"] = "alpha_vantage"
        profile = get_live_technical_profile(symbol)
        if profile:
            ind = profile.get("indicators", {})
            rsi_obj = ind.get("rsi") or {}
            sma50_obj = ind.get("sma_50") or {}
            result["rsi"] = rsi_obj.get("value") or 50
            result["ma50"] = sma50_obj.get("value") or result["price"]
        _live_stock_cache[symbol] = result
        _live_cache_ts[symbol] = now
        return result

    result["data_source"] = "unavailable"
    _live_stock_cache[symbol] = result
    _live_cache_ts[symbol] = now
    return result


class _StockDatabaseProxy:
    """Dict-like proxy that resolves stock data live instead of from static values."""
    def get(self, symbol: str, default=None):
        if symbol not in _STOCK_META:
            result = _resolve_stock_data(symbol)
            if result.get("price", 0) <= 0:
                return default
            return result
        return _resolve_stock_data(symbol)

    def __getitem__(self, symbol: str):
        return _resolve_stock_data(symbol)

    def __contains__(self, symbol: str):
        if symbol in _STOCK_META:
            return True
        data = _resolve_stock_data(symbol)
        return data.get("price", 0) > 0

    def items(self):
        return [(s, _resolve_stock_data(s)) for s in _STOCK_META]

    def keys(self):
        return _STOCK_META.keys()

    def values(self):
        return [_resolve_stock_data(s) for s in _STOCK_META]

    def __len__(self):
        return len(_STOCK_META)

    def __iter__(self):
        return iter(_STOCK_META)


STOCK_DATABASE = _StockDatabaseProxy()

__all__ = [
    "LIVE_DATA_AVAILABLE",
    "get_live_quote",
    "get_live_technical_profile",
    "get_live_news",
    "STOCK_DATABASE",
]
