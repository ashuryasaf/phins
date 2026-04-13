"""
PHINS Investment AI Tool Service
=================================
Super AI-powered investment analysis platform with 10 core capabilities:

1. Market Research & Trend Analysis
2. Portfolio Diversification
3. AI-Powered Stock Screener
4. Automated Trading Strategy
5. Technical Analysis
6. Earnings Report Analysis
7. Growth vs Dividend Stocks
8. Algorithmic Trading Bots
9. Automated Risk Management
10. Backtesting Trading Strategies

Each module generates actionable AI-driven insights using market data,
technical indicators, and quantitative models.
"""

import math
import random
import hashlib
import hmac
import secrets
import os
import json
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field, asdict
from enum import Enum
from collections import deque


# ---------------------------------------------------------------------------
# Alpha Vantage live data integration
# ---------------------------------------------------------------------------

_av_service = None

try:
    from services.alpha_vantage_service import get_alpha_vantage_service
    _av_service = get_alpha_vantage_service()
    LIVE_DATA_AVAILABLE = True
except ImportError:
    LIVE_DATA_AVAILABLE = False


def _get_live_quote(symbol: str) -> Optional[Dict[str, Any]]:
    """Fetch a live quote from Alpha Vantage, returns None on failure."""
    if not LIVE_DATA_AVAILABLE or not _av_service:
        return None
    try:
        return _av_service.get_quote(symbol)
    except Exception:
        return None


def _get_live_technical_profile(symbol: str) -> Optional[Dict[str, Any]]:
    """Fetch full technical profile from Alpha Vantage."""
    if not LIVE_DATA_AVAILABLE or not _av_service:
        return None
    try:
        return _av_service.get_full_technical_profile(symbol)
    except Exception:
        return None


def _get_live_fundamentals(symbol: str) -> Optional[Dict[str, Any]]:
    """Fetch fundamentals from Alpha Vantage."""
    if not LIVE_DATA_AVAILABLE or not _av_service:
        return None
    try:
        return _av_service.get_full_fundamental_profile(symbol)
    except Exception:
        return None


def _get_live_news(tickers: Optional[str] = None, topics: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Fetch news sentiment from Alpha Vantage."""
    if not LIVE_DATA_AVAILABLE or not _av_service:
        return None
    try:
        return _av_service.get_news_sentiment(tickers=tickers, topics=topics, limit=10)
    except Exception:
        return None


def _get_live_daily(symbol: str, outputsize: str = "compact") -> Optional[Dict[str, Any]]:
    """Fetch daily time series from Alpha Vantage."""
    if not LIVE_DATA_AVAILABLE or not _av_service:
        return None
    try:
        return _av_service.get_daily(symbol, outputsize=outputsize)
    except Exception:
        return None


def _get_live_gainers_losers() -> Optional[Dict[str, Any]]:
    """Fetch top gainers/losers from Alpha Vantage."""
    if not LIVE_DATA_AVAILABLE or not _av_service:
        return None
    try:
        return _av_service.get_top_gainers_losers()
    except Exception:
        return None


def _get_live_weekly(symbol: str) -> Optional[Dict[str, Any]]:
    if not LIVE_DATA_AVAILABLE or not _av_service:
        return None
    try:
        return _av_service.get_weekly(symbol)
    except Exception:
        return None


def _get_live_intraday(symbol: str, interval: str = "5min") -> Optional[Dict[str, Any]]:
    if not LIVE_DATA_AVAILABLE or not _av_service:
        return None
    try:
        return _av_service.get_intraday(symbol, interval=interval)
    except Exception:
        return None


def _get_live_vix() -> float:
    """Get VIX-like volatility estimate from live SPY data."""
    try:
        from services.trading_platform_service import get_trading_platform
        from services.ai_trading_engine import compute_risk_metrics
        tp = get_trading_platform()
        if tp.is_connected:
            bars = tp.get_bars("SPY", "1Day", 30)
            if bars and len(bars) >= 5:
                risk = compute_risk_metrics(bars, [])
                vol = risk.get("volatility_annual", 0.2)
                return round(vol * 100, 1)
    except Exception:
        pass
    quote = _get_live_quote("VIX")
    if quote and quote.get("price"):
        return float(quote["price"])
    return 20.0


def _get_live_company_overview(symbol: str) -> Optional[Dict[str, Any]]:
    if not LIVE_DATA_AVAILABLE or not _av_service:
        return None
    try:
        return _av_service.get_company_overview(symbol)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Access control: single-user API key
# ---------------------------------------------------------------------------

_INVESTMENT_AI_ACCESS_KEY = os.environ.get(
    "INVESTMENT_AI_ACCESS_KEY",
    None,
)

_GENERATED_KEY: Optional[str] = None


def _get_or_create_access_key() -> str:
    """Return the configured access key or generate a persistent one."""
    global _GENERATED_KEY
    if _INVESTMENT_AI_ACCESS_KEY:
        return _INVESTMENT_AI_ACCESS_KEY
    if _GENERATED_KEY is None:
        _GENERATED_KEY = f"invai_{secrets.token_urlsafe(32)}"
    return _GENERATED_KEY


def validate_investment_ai_access(provided_key: str) -> bool:
    """Validate that the provided key matches the access key."""
    if not provided_key:
        return False
    expected = _get_or_create_access_key()
    return hmac.compare_digest(provided_key, expected)


def get_access_key_display() -> str:
    """Return the current access key (for admin provisioning)."""
    return _get_or_create_access_key()


# ---------------------------------------------------------------------------
# Sector metadata (structural/thematic — not price data)
# Prices and YTD returns are fetched live from Alpaca/Alpha Vantage.
# ---------------------------------------------------------------------------

# Sector metadata. `trend`, `ytd_return`, `pe_avg`, `volatility` are neutral
# defaults — overwritten by live data when fetched from Alpaca sector ETFs.
SECTOR_DATA: Dict[str, Dict[str, Any]] = {
    "technology": {
        "name": "Technology", "etf": "XLK", "trend": "neutral", "ytd_return": 0, "pe_avg": 0, "volatility": "medium",
        "top_stocks": ["AAPL", "MSFT", "NVDA", "GOOGL", "META"],
        "emerging": ["AI infrastructure", "quantum computing", "edge AI"],
    },
    "healthcare": {
        "name": "Healthcare", "etf": "XLV", "trend": "neutral", "ytd_return": 0, "pe_avg": 0, "volatility": "medium",
        "top_stocks": ["JNJ", "UNH", "PFE", "ABT", "TMO"],
        "emerging": ["GLP-1 therapeutics", "AI diagnostics", "gene therapy"],
    },
    "financials": {
        "name": "Financials", "etf": "XLF", "trend": "neutral", "ytd_return": 0, "pe_avg": 0, "volatility": "medium",
        "top_stocks": ["JPM", "BAC", "GS", "MS", "V"],
        "emerging": ["embedded finance", "blockchain settlement", "AI underwriting"],
    },
    "energy": {
        "name": "Energy", "etf": "XLE", "trend": "neutral", "ytd_return": 0, "pe_avg": 0, "volatility": "high",
        "top_stocks": ["XOM", "CVX", "COP", "SLB", "EOG"],
        "emerging": ["green hydrogen", "small modular reactors", "grid storage"],
    },
    "consumer_discretionary": {
        "name": "Consumer Discretionary", "etf": "XLY", "trend": "neutral", "ytd_return": 0, "pe_avg": 0, "volatility": "high",
        "top_stocks": ["AMZN", "TSLA", "HD", "NKE", "SBUX"],
        "emerging": ["social commerce", "personalized retail AI", "EV infrastructure"],
    },
    "industrials": {
        "name": "Industrials", "etf": "XLI", "trend": "neutral", "ytd_return": 0, "pe_avg": 0, "volatility": "medium",
        "top_stocks": ["CAT", "UNP", "HON", "GE", "RTX"],
        "emerging": ["robotics automation", "reshoring supply chains", "defense tech"],
    },
    "real_estate": {
        "name": "Real Estate", "etf": "XLRE", "trend": "neutral", "ytd_return": 0, "pe_avg": 0, "volatility": "low",
        "top_stocks": ["PLD", "AMT", "EQIX", "SPG", "O"],
        "emerging": ["data center REITs", "logistics hubs", "AI-managed properties"],
    },
    "utilities": {
        "name": "Utilities", "etf": "XLU", "trend": "neutral", "ytd_return": 0, "pe_avg": 0, "volatility": "low",
        "top_stocks": ["NEE", "DUK", "SO", "D", "AEP"],
        "emerging": ["grid modernization", "nuclear renaissance", "distributed energy"],
    },
    "materials": {
        "name": "Materials", "etf": "XLB", "trend": "neutral", "ytd_return": 0, "pe_avg": 0, "volatility": "medium",
        "top_stocks": ["LIN", "APD", "ECL", "SHW", "FCX"],
        "emerging": ["rare earth processing", "sustainable packaging", "advanced alloys"],
    },
    "communication_services": {
        "name": "Communication Services", "etf": "XLC", "trend": "neutral", "ytd_return": 0, "pe_avg": 0, "volatility": "medium",
        "top_stocks": ["GOOGL", "META", "NFLX", "DIS", "T"],
        "emerging": ["AI content generation", "spatial computing", "6G R&D"],
    },
    "crypto": {
        "name": "Cryptocurrency", "etf": None, "trend": "neutral", "ytd_return": 0, "pe_avg": None, "volatility": "very_high",
        "top_stocks": ["BTC", "ETH", "SOL", "BNB", "ADA"],
        "emerging": ["DeFi 2.0", "real-world asset tokenization", "ZK rollups"],
    },
}

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

import time as _time


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
    quote = _get_live_quote(symbol)
    if quote and quote.get("price"):
        result["price"] = float(quote["price"])
        result["volume"] = int(quote.get("volume", 0))
        result["data_source"] = "alpha_vantage"
        profile = _get_live_technical_profile(symbol)
        if profile:
            ind = profile.get("indicators", {})
            result["rsi"] = ind.get("rsi") or 50
            result["ma50"] = ind.get("sma_50") or result["price"]
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


# ---------------------------------------------------------------------------
# Helper: deterministic "AI" variation seeded by input
# ---------------------------------------------------------------------------

def _seed_from(text: str) -> random.Random:
    h = int(hashlib.sha256(text.encode()).hexdigest(), 16)
    return random.Random(h)


def _format_large_number(n: float) -> str:
    if n >= 1_000_000_000_000:
        return f"${n / 1_000_000_000_000:.2f}T"
    if n >= 1_000_000_000:
        return f"${n / 1_000_000_000:.2f}B"
    if n >= 1_000_000:
        return f"${n / 1_000_000:.2f}M"
    return f"${n:,.2f}"


def _rsi_signal(rsi: float) -> str:
    if rsi >= 70:
        return "overbought"
    if rsi >= 60:
        return "bullish"
    if rsi >= 40:
        return "neutral"
    if rsi >= 30:
        return "bearish"
    return "oversold"


def _ma_signal(price: float, ma50: float, ma200: float) -> str:
    above_50 = price > ma50
    above_200 = price > ma200
    if above_50 and above_200:
        if ma50 > ma200:
            return "strong_uptrend"
        return "uptrend"
    if not above_50 and not above_200:
        if ma50 < ma200:
            return "strong_downtrend"
        return "downtrend"
    return "mixed"


# ===================================================================
# MODULE 1: Market Research & Trend Analysis
# ===================================================================

def analyze_market_trends(sector: str = "", stock: str = "") -> Dict[str, Any]:
    """
    Analyze current trends in the stock market focusing on a sector or stock.
    Identifies emerging patterns and suggests investment opportunities.
    Uses live Alpha Vantage data when available, falls back to static data.
    """
    result: Dict[str, Any] = {
        "module": "market_research_trend_analysis",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data_source": "live" if LIVE_DATA_AVAILABLE else "static",
    }

    if stock:
        sym = stock.upper()
        s = STOCK_DATABASE.get(sym, {})
        sec = SECTOR_DATA.get(s.get("sector", ""), {})
        rsi = s.get("rsi", 50) if s else 50
        momentum_score = rsi

        live_quote = _get_live_quote(sym)
        live_overview = None
        live_news = None
        if LIVE_DATA_AVAILABLE and _av_service:
            try:
                live_overview = _av_service.get_company_overview(sym)
            except Exception:
                pass
            live_news = _get_live_news(sym)

        price = (live_quote or {}).get("price") or s.get("price")
        pe = (live_overview or {}).get("pe_ratio") or s.get("pe")
        ma50 = (live_overview or {}).get("50_day_ma") or s.get("ma50", 0)
        ma200 = (live_overview or {}).get("200_day_ma") or s.get("ma200", 0)
        volume = (live_quote or {}).get("volume") or s.get("volume")
        mkt_cap = (live_overview or {}).get("market_cap") or s.get("market_cap", 0)
        beta = (live_overview or {}).get("beta") or s.get("beta")
        change_pct = (live_quote or {}).get("change_percent")

        result["stock_analysis"] = {
            "symbol": sym,
            "name": (live_overview or {}).get("name") or s.get("name", sym),
            "sector": (live_overview or {}).get("sector") or s.get("sector", "unknown"),
            "industry": (live_overview or {}).get("industry"),
            "current_price": price,
            "previous_close": (live_quote or {}).get("previous_close"),
            "change_percent": change_pct,
            "pe_ratio": pe,
            "forward_pe": (live_overview or {}).get("forward_pe"),
            "peg_ratio": (live_overview or {}).get("peg_ratio"),
            "eps": (live_overview or {}).get("eps") or s.get("eps"),
            "ma50": ma50,
            "ma200": ma200,
            "ma_signal": _ma_signal(price, ma50, ma200) if price and ma50 and ma200 else "unknown",
            "volume": volume,
            "market_cap": _format_large_number(mkt_cap) if mkt_cap else None,
            "beta": beta,
            "dividend_yield": (live_overview or {}).get("dividend_yield") or s.get("dividend_yield"),
            "52_week_high": (live_overview or {}).get("52_week_high"),
            "52_week_low": (live_overview or {}).get("52_week_low"),
            "analyst_target_price": (live_overview or {}).get("analyst_target_price"),
            "momentum_score": round(momentum_score, 1),
            "sector_trend": sec.get("trend", "unknown"),
            "sector_ytd_return": sec.get("ytd_return"),
            "live_data": live_quote is not None,
        }
        if live_news and live_news.get("articles"):
            result["news_sentiment"] = live_news["articles"][:5]
        result["emerging_patterns"] = sec.get("emerging", [])
        similar = [k for k, v in STOCK_DATABASE.items() if v.get("sector") == s.get("sector") and k != sym]
        result["related_opportunities"] = similar[:5]

        # Live market movers
        movers = _get_live_gainers_losers()
        if movers:
            result["market_movers"] = {
                "top_gainers": movers.get("top_gainers", [])[:5],
                "top_losers": movers.get("top_losers", [])[:5],
            }

    elif sector and sector.lower().replace(" ", "_") in SECTOR_DATA:
        key = sector.lower().replace(" ", "_")
        sec = SECTOR_DATA[key]
        result["sector_analysis"] = {
            "sector": sec["name"],
            "trend": sec["trend"],
            "ytd_return": sec["ytd_return"],
            "average_pe": sec["pe_avg"],
            "volatility": sec["volatility"],
            "top_stocks": sec["top_stocks"],
        }
        result["emerging_patterns"] = sec["emerging"]

        # Enrich top stocks with live quotes
        opportunities = []
        for sym in sec["top_stocks"]:
            stock_data = dict(STOCK_DATABASE.get(sym, {}))
            live_q = _get_live_quote(sym)
            if live_q:
                stock_data["price"] = live_q["price"]
                stock_data["change_percent"] = live_q.get("change_percent")
                stock_data["live"] = True
            stock_data["stock"] = sym
            opportunities.append(stock_data)
        result["investment_opportunities"] = opportunities

        # Live news for sector
        sector_news = _get_live_news()
        if sector_news and sector_news.get("articles"):
            result["sector_news"] = sector_news["articles"][:5]

    else:
        result["market_overview"] = {
            "sectors": {
                k: {"name": v["name"], "trend": v["trend"], "ytd_return": v["ytd_return"]}
                for k, v in SECTOR_DATA.items()
            },
            "bullish_sectors": [v["name"] for v in SECTOR_DATA.values() if v["trend"] == "bullish"],
            "bearish_sectors": [v["name"] for v in SECTOR_DATA.values() if v["trend"] == "bearish"],
        }
        result["top_opportunities"] = [
            {"sector": v["name"], "emerging": v["emerging"]}
            for v in sorted(SECTOR_DATA.values(), key=lambda x: x["ytd_return"], reverse=True)[:5]
        ]
        movers = _get_live_gainers_losers()
        if movers:
            result["market_movers"] = movers

    result["insights"] = _generate_market_insights(sector, stock)
    return result


def _generate_market_insights(sector: str, stock: str) -> List[str]:
    base_insights = [
        "AI-driven sectors continue to outperform traditional value plays.",
        "Federal Reserve policy signals suggest a stable rate environment for the near term.",
        "Institutional money flow indicates rotation into quality growth names.",
        "Geopolitical factors creating selective opportunities in defense and energy.",
        "Earnings revisions trending positive for large-cap technology stocks.",
    ]
    rng = _seed_from(f"{sector}:{stock}:{datetime.now(timezone.utc).strftime('%Y-%m-%d')}")
    rng.shuffle(base_insights)
    return base_insights[:3]


# ===================================================================
# MODULE 2: Portfolio Diversification
# ===================================================================

def analyze_portfolio_diversification(
    current_holdings: List[str],
    risk_tolerance: str = "moderate",
) -> Dict[str, Any]:
    """
    Propose strategies to diversify a portfolio while minimizing risk.
    """
    held_sectors = set()
    for sym in current_holdings:
        s = STOCK_DATABASE.get(sym.upper())
        if s:
            held_sectors.add(s["sector"])

    all_sectors = set(SECTOR_DATA.keys())
    missing_sectors = all_sectors - held_sectors

    recommendations: List[Dict[str, Any]] = []
    for sec_key in sorted(missing_sectors):
        sec = SECTOR_DATA[sec_key]
        picks = [sym for sym in sec["top_stocks"] if sym in STOCK_DATABASE][:2]
        recommendations.append({
            "sector": sec["name"],
            "rationale": f"Portfolio lacks {sec['name']} exposure; sector shows {sec['trend']} trend with {sec['ytd_return']}% YTD.",
            "suggested_stocks": picks,
            "sector_volatility": sec["volatility"],
        })

    risk_map = {
        "conservative": {"equity": 30, "fixed_income": 45, "alternatives": 10, "cash": 15},
        "moderate": {"equity": 50, "fixed_income": 30, "alternatives": 15, "cash": 5},
        "aggressive": {"equity": 70, "fixed_income": 10, "alternatives": 18, "cash": 2},
    }
    target_allocation = risk_map.get(risk_tolerance, risk_map["moderate"])

    correlation_reduction = []
    if "technology" in held_sectors and "utilities" not in held_sectors:
        correlation_reduction.append("Add utilities (NEE, DUK) to reduce tech correlation.")
    if "consumer_discretionary" in held_sectors and "healthcare" not in held_sectors:
        correlation_reduction.append("Healthcare adds defensive balance against cyclical consumer exposure.")
    if len(held_sectors) < 4:
        correlation_reduction.append("Significant concentration risk — aim for at least 5 sectors.")

    return {
        "module": "portfolio_diversification",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "current_holdings": current_holdings,
        "held_sectors": sorted(held_sectors),
        "missing_sectors": sorted(missing_sectors),
        "target_allocation": target_allocation,
        "new_sector_recommendations": recommendations,
        "correlation_insights": correlation_reduction,
        "diversification_score": round(min(100, len(held_sectors) / len(all_sectors) * 100), 1),
    }


# ===================================================================
# MODULE 3: AI-Powered Stock Screener
# ===================================================================

class ScreenerCriteria:
    """Configurable stock screening criteria."""
    def __init__(
        self,
        pe_max: float = 50.0,
        pe_min: float = 0.0,
        rsi_max: float = 70.0,
        rsi_min: float = 30.0,
        min_volume: int = 1_000_000,
        min_market_cap: float = 10_000_000_000,
        above_ma50: bool = True,
        above_ma200: bool = True,
        min_revenue_growth: Optional[float] = None,
        max_beta: Optional[float] = None,
        sectors: Optional[List[str]] = None,
    ):
        self.pe_max = pe_max
        self.pe_min = pe_min
        self.rsi_max = rsi_max
        self.rsi_min = rsi_min
        self.min_volume = min_volume
        self.min_market_cap = min_market_cap
        self.above_ma50 = above_ma50
        self.above_ma200 = above_ma200
        self.min_revenue_growth = min_revenue_growth
        self.max_beta = max_beta
        self.sectors = sectors


def run_stock_screener(criteria: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    AI-powered stock screener using fundamental and technical indicators.
    """
    c = ScreenerCriteria(**(criteria or {}))
    results = []

    for sym, s in STOCK_DATABASE.items():
        if s["pe"] is None:
            continue
        if not (c.pe_min <= s["pe"] <= c.pe_max):
            continue
        if not (c.rsi_min <= s["rsi"] <= c.rsi_max):
            continue
        if s["volume"] < c.min_volume:
            continue
        if s["market_cap"] < c.min_market_cap:
            continue
        if c.above_ma50 and s["price"] < s["ma50"]:
            continue
        if c.above_ma200 and s["price"] < s["ma200"]:
            continue
        if c.min_revenue_growth is not None and (s["revenue_growth"] is None or s["revenue_growth"] < c.min_revenue_growth):
            continue
        if c.max_beta is not None and s["beta"] > c.max_beta:
            continue
        if c.sectors and s["sector"] not in c.sectors:
            continue

        ma_sig = _ma_signal(s["price"], s["ma50"], s["ma200"])
        composite_score = _compute_composite_score(s)
        results.append({
            "symbol": sym,
            "name": s["name"],
            "sector": s["sector"],
            "price": s["price"],
            "pe_ratio": s["pe"],
            "rsi": s["rsi"],
            "rsi_signal": _rsi_signal(s["rsi"]),
            "ma_signal": ma_sig,
            "volume": s["volume"],
            "market_cap": _format_large_number(s["market_cap"]),
            "revenue_growth": s["revenue_growth"],
            "dividend_yield": s["dividend_yield"],
            "beta": s["beta"],
            "composite_score": composite_score,
        })

    results.sort(key=lambda x: x["composite_score"], reverse=True)

    return {
        "module": "ai_stock_screener",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "criteria_applied": {
            "pe_range": f"{c.pe_min}-{c.pe_max}",
            "rsi_range": f"{c.rsi_min}-{c.rsi_max}",
            "min_volume": c.min_volume,
            "above_ma50": c.above_ma50,
            "above_ma200": c.above_ma200,
        },
        "matches": results,
        "total_screened": len(STOCK_DATABASE),
        "total_matches": len(results),
        "methodology": {
            "fundamental": ["P/E ratio", "Revenue growth", "EPS", "Dividend yield"],
            "technical": ["RSI", "50-day MA", "200-day MA", "Volume trends"],
            "composite": "Weighted score: 30% fundamentals, 40% technicals, 30% momentum",
        },
    }


def _compute_composite_score(s: Dict[str, Any]) -> float:
    score = 50.0
    if s["pe"] and s["pe"] < 25:
        score += 10
    elif s["pe"] and s["pe"] > 50:
        score -= 10
    rsi = s["rsi"]
    if 40 <= rsi <= 60:
        score += 10
    elif rsi > 70:
        score -= 5
    elif rsi < 30:
        score += 5
    if s["price"] > s["ma50"]:
        score += 8
    if s["price"] > s["ma200"]:
        score += 7
    if s.get("revenue_growth") and s["revenue_growth"] > 10:
        score += 10
    if s.get("dividend_yield") and s["dividend_yield"] > 2:
        score += 5
    if s.get("beta") and s["beta"] < 1.2:
        score += 5
    return round(min(100, max(0, score)), 1)


# ===================================================================
# MODULE 4: Automated Trading Strategy
# ===================================================================

def design_trading_strategy(
    market: str = "US Equities",
    strategy_type: str = "momentum",
    risk_level: str = "moderate",
) -> Dict[str, Any]:
    """
    Design a data-driven automated trading strategy with entry/exit signals.
    """
    strategies = {
        "momentum": {
            "name": "Momentum Breakout",
            "description": "Captures strong directional moves by entering when price breaks above resistance with volume confirmation.",
            "entry_signals": [
                "Price closes above 20-day high with volume > 150% of 20-day average",
                "RSI crosses above 50 from below (confirming momentum shift)",
                "MACD histogram turns positive with increasing bars",
            ],
            "exit_signals": [
                "Price closes below 10-day EMA",
                "RSI divergence detected (price higher, RSI lower)",
                "Volume dries up below 50% of average for 3 consecutive days",
            ],
            "stop_loss": "2 ATR below entry price (dynamic trailing)",
            "take_profit": "3:1 reward-to-risk ratio or trailing stop at 1.5 ATR",
            "position_sizing": "Risk 1-2% of portfolio per trade",
            "backtest_expected": {"win_rate": 42, "avg_rr": 2.8, "sharpe": 1.45, "max_drawdown": 12},
        },
        "mean_reversion": {
            "name": "Mean Reversion",
            "description": "Profits from price returning to its statistical mean after extreme deviations.",
            "entry_signals": [
                "Price > 2 standard deviations below 50-day SMA",
                "RSI below 25 (extreme oversold)",
                "Bollinger Band squeeze followed by touch of lower band",
            ],
            "exit_signals": [
                "Price returns to 50-day SMA",
                "RSI returns to 50 (mean normalized)",
                "Take profit at upper Bollinger Band",
            ],
            "stop_loss": "3% below entry or below previous swing low",
            "take_profit": "Return to mean (50-day SMA) or upper Bollinger Band",
            "position_sizing": "Risk 1% of portfolio; scale in at 2.5 and 3 standard deviations",
            "backtest_expected": {"win_rate": 65, "avg_rr": 1.4, "sharpe": 1.28, "max_drawdown": 8},
        },
        "trend_following": {
            "name": "Trend Following",
            "description": "Rides established trends using moving average crossovers and ADX confirmation.",
            "entry_signals": [
                "50-day EMA crosses above 200-day EMA (golden cross)",
                "ADX > 25 confirming trend strength",
                "Price above both EMAs with positive slope",
            ],
            "exit_signals": [
                "50-day EMA crosses below 200-day EMA (death cross)",
                "ADX drops below 20 (trend weakening)",
                "Price closes below 50-day EMA for 3 consecutive days",
            ],
            "stop_loss": "Below 200-day EMA or 5% trailing stop",
            "take_profit": "No fixed target — ride the trend with trailing stops",
            "position_sizing": "Risk 2% per position; max 6 correlated positions",
            "backtest_expected": {"win_rate": 38, "avg_rr": 3.5, "sharpe": 1.62, "max_drawdown": 15},
        },
        "scalping": {
            "name": "High-Frequency Scalping",
            "description": "Quick in-and-out trades capturing small price movements with high frequency.",
            "entry_signals": [
                "1-minute VWAP reclaim with volume spike",
                "Order flow imbalance > 60% on bid side",
                "Price at key support level with RSI(5) < 20",
            ],
            "exit_signals": [
                "Target hit: 0.2-0.5% profit per trade",
                "Time stop: exit if no movement in 5 minutes",
                "VWAP rejection on second test",
            ],
            "stop_loss": "0.1% below entry (tight stops mandatory)",
            "take_profit": "0.2-0.5% per trade, 2:1 minimum R:R",
            "position_sizing": "Larger position sizes (3-5% of capital) due to tight stops",
            "backtest_expected": {"win_rate": 58, "avg_rr": 1.8, "sharpe": 2.1, "max_drawdown": 5},
        },
    }

    strat = strategies.get(strategy_type, strategies["momentum"])

    risk_adjustments = {
        "conservative": {"position_scale": 0.5, "max_positions": 3, "stop_multiplier": 1.5},
        "moderate": {"position_scale": 1.0, "max_positions": 5, "stop_multiplier": 1.0},
        "aggressive": {"position_scale": 1.5, "max_positions": 8, "stop_multiplier": 0.7},
    }
    risk_adj = risk_adjustments.get(risk_level, risk_adjustments["moderate"])

    return {
        "module": "automated_trading_strategy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "market": market,
        "strategy": strat,
        "risk_profile": risk_level,
        "risk_adjustments": risk_adj,
        "optimization_notes": [
            "Strategy parameters should be re-optimized quarterly using walk-forward analysis.",
            "Consider regime detection to switch strategies in trending vs. ranging markets.",
            "Transaction costs and slippage must be included in backtest for realistic results.",
            "Use out-of-sample data for final validation to avoid overfitting.",
        ],
    }


def _try_ai_engine_technical(sym: str) -> Optional[Dict[str, Any]]:
    """Use AI trading engine with Alpaca bars for real technical analysis."""
    try:
        from services.trading_platform_service import get_trading_platform
        from services.ai_trading_engine import compute_technicals, generate_signals
        tp = get_trading_platform()
        if not tp.is_connected:
            return None
        fetch_sym = sym.replace("/", "") if "/" in sym else sym
        bars = tp.get_bars(fetch_sym, "1Day", 100)
        if not bars or len(bars) < 10:
            return None
        techs = compute_technicals(bars)
        ind = techs.get("indicators", {})
        price = float(bars[-1].get("close", 0))
        if price <= 0:
            return None
        signals = generate_signals(techs, price)
        meta = _STOCK_META.get(sym, {"name": sym, "sector": "unknown"})
        return {
            "module": "technical_analysis",
            "symbol": sym,
            "name": meta.get("name", sym),
            "data_source": "alpaca_live",
            "current_price": price,
            "recommendation": signals.get("recommendation", "HOLD"),
            "composite_score": signals.get("composite_score", 0),
            "confidence": signals.get("confidence", 0),
            "indicators": {
                "rsi_14": {"value": ind.get("rsi_14"), "signal": _rsi_signal(ind.get("rsi_14", 50))},
                "macd": {"value": ind.get("macd_line"), "signal_line": ind.get("macd_signal"), "histogram": ind.get("macd_histogram")},
                "bollinger_bands": {"upper": ind.get("bb_upper"), "middle": ind.get("bb_middle"), "lower": ind.get("bb_lower"), "width": ind.get("bb_width")},
                "moving_averages": {"sma_20": ind.get("sma_20"), "sma_50": ind.get("sma_50"), "ema_12": ind.get("ema_12"), "ema_26": ind.get("ema_26")},
                "atr_14": ind.get("atr_14"),
                "stochastic": {"k": ind.get("stoch_k"), "d": ind.get("stoch_d")},
                "obv": ind.get("obv"),
                "volume_ratio": ind.get("volume_ratio"),
            },
            "signal_details": signals.get("details", []),
            "bars_analyzed": len(bars),
        }
    except Exception:
        return None


# ===================================================================
# MODULE 5: Technical Analysis
# ===================================================================

def run_technical_analysis(stock: str) -> Dict[str, Any]:
    """
    Evaluate a stock using technical analysis indicators.
    Produces a Buy / Sell / Hold recommendation.
    Uses live Alpha Vantage data when available.
    """
    sym = stock.upper()
    s = STOCK_DATABASE.get(sym)

    # Try live technical profile first
    live_profile = _get_live_technical_profile(sym)
    if live_profile and live_profile.get("quote"):
        return _build_live_technical_result(sym, live_profile, s)

    # Try AI engine with Alpaca bars
    ai_result = _try_ai_engine_technical(sym)
    if ai_result:
        return ai_result

    if not s:
        return {"module": "technical_analysis", "error": f"Stock '{sym}' not found. Try a US stock symbol like AAPL, MSFT, NVDA."}

    rsi_sig = _rsi_signal(s.get("rsi", 50))
    ma_sig = _ma_signal(s.get("price", 0), s.get("ma50", 0), s.get("ma200", 0))

    macd_value = 0
    macd_signal_val = 0
    macd_histogram = 0

    price = s.get("price", 0)
    ma50 = s.get("ma50", price)
    bb_upper = ma50 * 1.04 if ma50 else price * 1.04
    bb_lower = ma50 * 0.96 if ma50 else price * 0.96
    bb_position = "upper" if price > bb_upper else ("lower" if price < bb_lower else "middle")

    vol_avg = s.get("volume", 0)
    vol_today = vol_avg
    vol_trend = "average"

    score = 0
    if rsi_sig in ("bullish", "neutral"):
        score += 1
    elif rsi_sig == "oversold":
        score += 2
    elif rsi_sig == "overbought":
        score -= 1
    if ma_sig in ("strong_uptrend", "uptrend"):
        score += 2
    elif ma_sig in ("strong_downtrend", "downtrend"):
        score -= 2
    if macd_histogram > 0:
        score += 1
    else:
        score -= 1
    if vol_trend == "above_average":
        score += 1

    if score >= 3:
        recommendation = "STRONG BUY"
    elif score >= 1:
        recommendation = "BUY"
    elif score >= -1:
        recommendation = "HOLD"
    elif score >= -3:
        recommendation = "SELL"
    else:
        recommendation = "STRONG SELL"

    support = round(s["ma200"] * 0.97, 2)
    resistance = round(s["price"] * 1.08, 2)

    return {
        "module": "technical_analysis",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data_source": "static",
        "symbol": sym,
        "name": s["name"],
        "current_price": s["price"],
        "indicators": {
            "rsi": {"value": s["rsi"], "signal": rsi_sig},
            "moving_averages": {
                "ma50": s["ma50"],
                "ma200": s["ma200"],
                "signal": ma_sig,
                "golden_cross": s["ma50"] > s["ma200"],
            },
            "macd": {
                "value": round(macd_value, 3),
                "signal_line": round(macd_signal_val, 3),
                "histogram": round(macd_histogram, 3),
                "bullish": macd_histogram > 0,
            },
            "bollinger_bands": {
                "upper": round(bb_upper, 2),
                "lower": round(bb_lower, 2),
                "position": bb_position,
            },
            "volume": {
                "current": vol_today,
                "average": vol_avg,
                "trend": vol_trend,
            },
        },
        "support_level": support,
        "resistance_level": resistance,
        "technical_score": score,
        "recommendation": recommendation,
    }


def _build_live_technical_result(sym: str, profile: Dict[str, Any], static: Optional[Dict] = None) -> Dict[str, Any]:
    """Build a technical analysis result from live Alpha Vantage data."""
    q = profile.get("quote", {})
    ind = profile.get("indicators", {})
    signals = profile.get("signals", {})

    rsi_val = (ind.get("rsi") or {}).get("value")
    sma50_val = (ind.get("sma_50") or {}).get("value")
    sma200_val = (ind.get("sma_200") or {}).get("value")
    macd_data = ind.get("macd") or {}
    bb_data = ind.get("bollinger_bands") or {}
    adx_data = ind.get("adx") or {}
    atr_data = ind.get("atr") or {}

    price = q.get("price") if q else None

    rsi_sig = _rsi_signal(rsi_val) if rsi_val else "unknown"
    ma_sig = _ma_signal(price, sma50_val, sma200_val) if price and sma50_val and sma200_val else "unknown"
    bb_pos = "upper" if price and bb_data.get("upper") and price >= bb_data["upper"] else (
        "lower" if price and bb_data.get("lower") and price <= bb_data["lower"] else "middle"
    )

    support = round(sma200_val * 0.97, 2) if sma200_val else None
    resistance = round(price * 1.08, 2) if price else None

    return {
        "module": "technical_analysis",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data_source": "live",
        "symbol": sym,
        "name": (static or {}).get("name", sym),
        "current_price": price,
        "previous_close": q.get("previous_close") if q else None,
        "change": q.get("change") if q else None,
        "change_percent": q.get("change_percent") if q else None,
        "indicators": {
            "rsi": {"value": rsi_val, "signal": rsi_sig},
            "moving_averages": {
                "ma50": sma50_val,
                "ma200": sma200_val,
                "signal": ma_sig,
                "golden_cross": sma50_val > sma200_val if sma50_val and sma200_val else None,
            },
            "macd": {
                "value": macd_data.get("macd"),
                "signal_line": macd_data.get("signal"),
                "histogram": macd_data.get("histogram"),
                "bullish": (macd_data.get("histogram") or 0) > 0,
            },
            "bollinger_bands": {
                "upper": bb_data.get("upper"),
                "middle": bb_data.get("middle"),
                "lower": bb_data.get("lower"),
                "position": bb_pos,
            },
            "adx": {"value": adx_data.get("value"), "trend_strength": "strong" if (adx_data.get("value") or 0) > 25 else "weak"},
            "atr": {"value": atr_data.get("value")},
            "volume": {
                "current": q.get("volume") if q else None,
            },
        },
        "support_level": support,
        "resistance_level": resistance,
        "technical_score": signals.get("composite_score", 0),
        "recommendation": signals.get("recommendation", "HOLD"),
        "signal_details": signals.get("details", []),
    }


# ===================================================================
# MODULE 6: Earnings Report Analysis
# ===================================================================

def analyze_earnings_report(company: str) -> Dict[str, Any]:
    """
    Interpret a company's earnings report, highlighting key metrics.
    Uses live Alpha Vantage fundamental data when available.
    """
    sym = company.upper()
    s = STOCK_DATABASE.get(sym)

    # Try live fundamental data
    live_fundamentals = _get_live_fundamentals(sym)
    if live_fundamentals and live_fundamentals.get("overview"):
        return _build_live_earnings_result(sym, live_fundamentals, s)

    if not s:
        return {"module": "earnings_report_analysis", "error": f"Company '{sym}' not found. Try a US stock symbol like AAPL, MSFT."}

    market_cap = s.get("market_cap") or 0
    eps_actual = s.get("eps") or 0
    revenue_growth = s.get("revenue_growth") or 0
    revenue = market_cap * 0.06 if market_cap else 0
    net_income = revenue * 0.12 if revenue else 0
    gross_margin = 0
    operating_margin = 0
    free_cash_flow = net_income
    eps_estimate = eps_actual
    eps_surprise = 0
    beat = False
    revenue_estimate = revenue
    revenue_surprise = 0

    return {
        "module": "earnings_report_analysis",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data_source": s.get("data_source", "live"),
        "symbol": sym,
        "name": s["name"],
        "key_metrics": {
            "revenue": _format_large_number(revenue),
            "revenue_growth_yoy": f"{s['revenue_growth']}%",
            "net_income": _format_large_number(net_income),
            "earnings_per_share": {
                "actual": round(eps_actual, 2),
                "estimate": eps_estimate,
                "surprise_pct": eps_surprise,
                "beat_estimate": beat,
            },
            "gross_margin": f"{round(gross_margin * 100, 1)}%",
            "operating_margin": f"{round(operating_margin * 100, 1)}%",
            "free_cash_flow": _format_large_number(free_cash_flow),
            "pe_ratio": s["pe"],
        },
        "revenue_surprise": {
            "actual_vs_estimate": f"{revenue_surprise:+.2f}%",
            "beat": revenue > revenue_estimate,
        },
        "impact_assessment": {
            "short_term": "Positive" if beat else "Negative",
            "price_reaction_expected": f"{'+'if beat else '-'}{abs(eps_surprise) * 0.5:.1f}%",
            "analyst_revision_likely": beat and abs(eps_surprise) > 5,
        },
        "investor_focus_areas": [
            "Earnings Per Share (EPS) vs consensus — the primary driver of post-earnings moves.",
            "Revenue growth rate — shows top-line demand trajectory.",
            "Operating margins — indicate pricing power and cost discipline.",
            "Forward guidance — management outlook often matters more than the reported quarter.",
            "Free cash flow — validates earnings quality; cash flow should track or exceed net income.",
        ],
    }


def _build_live_earnings_result(sym: str, fundamentals: Dict[str, Any], static: Optional[Dict] = None) -> Dict[str, Any]:
    """Build earnings analysis from live Alpha Vantage fundamental data."""
    ov = fundamentals.get("overview", {})
    earnings = fundamentals.get("earnings", {})
    news = fundamentals.get("news", {})

    quarterly = (earnings or {}).get("quarterly_earnings", [])
    latest_q = quarterly[0] if quarterly else {}

    eps_actual = None
    eps_estimate = None
    eps_surprise = None
    beat = None
    if latest_q:
        eps_actual = _safe_float_or(latest_q.get("reportedEPS"))
        eps_estimate = _safe_float_or(latest_q.get("estimatedEPS"))
        eps_surprise = _safe_float_or(latest_q.get("surprisePercentage"))
        if eps_actual is not None and eps_estimate is not None:
            beat = eps_actual > eps_estimate

    revenue_ttm = ov.get("revenue_ttm")
    profit_margin = ov.get("profit_margin")
    operating_margin = ov.get("operating_margin")

    return {
        "module": "earnings_report_analysis",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data_source": "live",
        "symbol": sym,
        "name": ov.get("name", sym),
        "description": ov.get("description"),
        "sector": ov.get("sector"),
        "industry": ov.get("industry"),
        "key_metrics": {
            "revenue_ttm": _format_large_number(revenue_ttm) if revenue_ttm else None,
            "gross_profit_ttm": _format_large_number(ov.get("gross_profit_ttm")) if ov.get("gross_profit_ttm") else None,
            "ebitda": _format_large_number(ov.get("ebitda")) if ov.get("ebitda") else None,
            "earnings_per_share": {
                "current_eps": ov.get("eps"),
                "latest_quarter_actual": eps_actual,
                "latest_quarter_estimate": eps_estimate,
                "surprise_pct": eps_surprise,
                "beat_estimate": beat,
                "fiscal_date": latest_q.get("fiscalDateEnding"),
            },
            "profit_margin": f"{round(profit_margin * 100, 2)}%" if profit_margin else None,
            "operating_margin": f"{round(operating_margin * 100, 2)}%" if operating_margin else None,
            "return_on_equity": f"{round(ov.get('return_on_equity', 0) * 100, 2)}%" if ov.get("return_on_equity") else None,
            "pe_ratio": ov.get("pe_ratio"),
            "forward_pe": ov.get("forward_pe"),
            "peg_ratio": ov.get("peg_ratio"),
            "price_to_sales": ov.get("price_to_sales"),
            "price_to_book": ov.get("price_to_book"),
            "ev_to_revenue": ov.get("ev_to_revenue"),
            "ev_to_ebitda": ov.get("ev_to_ebitda"),
            "market_cap": _format_large_number(ov.get("market_cap")) if ov.get("market_cap") else None,
            "dividend_yield": f"{round(ov.get('dividend_yield', 0) * 100, 2)}%" if ov.get("dividend_yield") else None,
            "beta": ov.get("beta"),
            "52_week_high": ov.get("52_week_high"),
            "52_week_low": ov.get("52_week_low"),
            "analyst_target_price": ov.get("analyst_target_price"),
        },
        "quarterly_earnings_history": [
            {
                "date": q.get("fiscalDateEnding"),
                "reported_eps": q.get("reportedEPS"),
                "estimated_eps": q.get("estimatedEPS"),
                "surprise_pct": q.get("surprisePercentage"),
            }
            for q in quarterly[:8]
        ],
        "news_sentiment": (news or {}).get("articles", [])[:5],
        "investor_focus_areas": [
            "Earnings Per Share (EPS) vs consensus — the primary driver of post-earnings moves.",
            "Revenue growth rate — shows top-line demand trajectory.",
            "Operating margins — indicate pricing power and cost discipline.",
            "Forward guidance — management outlook often matters more than the reported quarter.",
            "Free cash flow — validates earnings quality; cash flow should track or exceed net income.",
            "PEG ratio — balances P/E against growth rate for fairer valuation.",
        ],
    }


def _safe_float_or(val, default=None):
    if val is None:
        return default
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


# ===================================================================
# MODULE 7: Growth vs Dividend Stocks
# ===================================================================

def compare_growth_vs_dividend(
    growth_stock: str = "NVDA",
    dividend_stock: str = "JNJ",
) -> Dict[str, Any]:
    """
    Compare growth stocks and dividend stocks with real examples.
    """
    g = STOCK_DATABASE.get(growth_stock.upper())
    d = STOCK_DATABASE.get(dividend_stock.upper())
    if not g:
        return {"module": "growth_vs_dividend", "error": f"Growth stock '{growth_stock}' not found."}
    if not d:
        return {"module": "growth_vs_dividend", "error": f"Dividend stock '{dividend_stock}' not found."}

    return {
        "module": "growth_vs_dividend",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "growth_stock": {
            "symbol": growth_stock.upper(),
            "name": g["name"],
            "price": g["price"],
            "pe_ratio": g["pe"],
            "revenue_growth": g["revenue_growth"],
            "dividend_yield": g["dividend_yield"],
            "beta": g["beta"],
            "profile": "High growth, low/no dividend, higher volatility",
        },
        "dividend_stock": {
            "symbol": dividend_stock.upper(),
            "name": d["name"],
            "price": d["price"],
            "pe_ratio": d["pe"],
            "revenue_growth": d["revenue_growth"],
            "dividend_yield": d["dividend_yield"],
            "beta": d["beta"],
            "profile": "Stable income, lower growth, lower volatility",
        },
        "comparison": {
            "growth_advantages": [
                "Higher potential capital appreciation",
                "Compound returns from reinvested earnings",
                "Typically outperform in bull markets and low-rate environments",
                "Companies reinvesting in R&D and expansion",
            ],
            "growth_risks": [
                "Higher valuation multiples increase downside risk",
                "No income during market downturns",
                "More sensitive to interest rate increases",
                "Dependent on meeting aggressive growth expectations",
            ],
            "dividend_advantages": [
                "Steady income stream regardless of market conditions",
                "Dividend reinvestment compounds returns over decades",
                "Lower volatility provides portfolio stability",
                "Tax-advantaged qualified dividends in many jurisdictions",
            ],
            "dividend_risks": [
                "Lower total return potential in strong bull markets",
                "Dividend cuts can cause sharp price drops",
                "May underperform in rapidly growing sectors",
                "Inflation can erode real income if dividend growth lags",
            ],
        },
        "ideal_conditions": {
            "favor_growth": [
                "Low interest rate environment",
                "Early/mid-stage bull market",
                "Strong economic expansion",
                "Long investment horizon (10+ years)",
            ],
            "favor_dividend": [
                "High interest rate / uncertainty environment",
                "Late-cycle or recessionary markets",
                "Need for portfolio income (retirement, distributions)",
                "Risk-averse investor profile",
            ],
        },
        "recommendation": (
            "A balanced approach often works best: core dividend holdings for stability "
            "and income, with a growth allocation for capital appreciation. "
            "Typical split: 60/40 dividend/growth for conservative, 40/60 for aggressive."
        ),
    }


# ===================================================================
# MODULE 8: Algorithmic Trading Bots
# ===================================================================

def get_algo_trading_bot_guide(strategy: str = "momentum") -> Dict[str, Any]:
    """
    Step-by-step guide to setting up an algorithmic trading bot.
    """
    return {
        "module": "algo_trading_bots",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "strategy": strategy,
        "setup_guide": {
            "step_1_platform_selection": {
                "title": "Choose Your Platform",
                "platforms": [
                    {"name": "QuantConnect", "language": "Python/C#", "data": "Free historical data", "best_for": "Backtesting & live trading", "cost": "Free tier available"},
                    {"name": "TradingView", "language": "Pine Script", "data": "Real-time charts", "best_for": "Visual strategy design", "cost": "Free with Pro plans"},
                    {"name": "MetaTrader 5", "language": "MQL5", "data": "Broker data", "best_for": "Forex & CFD trading", "cost": "Free"},
                    {"name": "Alpaca", "language": "Python", "data": "Real-time US equities", "best_for": "Commission-free algo trading", "cost": "Free"},
                    {"name": "Interactive Brokers", "language": "Python/Java", "data": "Global markets", "best_for": "Professional multi-asset trading", "cost": "Varies"},
                ],
            },
            "step_2_strategy_logic": {
                "title": "Define Strategy Logic",
                "components": [
                    "Signal generation: Define entry/exit conditions using technical indicators",
                    "Risk management: Position sizing, stop-loss, take-profit rules",
                    "Order execution: Market, limit, or conditional orders",
                    "Portfolio management: Max exposure, correlation limits, rebalancing",
                ],
                "example_pseudocode": (
                    "if RSI(14) < 30 and Price > SMA(200) and Volume > Avg_Volume * 1.5:\n"
                    "    BUY(symbol, quantity=position_size(risk=0.02))\n"
                    "    SET_STOP_LOSS(price * 0.97)\n"
                    "    SET_TAKE_PROFIT(price * 1.06)\n"
                    "elif RSI(14) > 70 or Price < SMA(50):\n"
                    "    SELL(symbol, quantity=ALL)"
                ),
            },
            "step_3_data_pipeline": {
                "title": "Set Up Data Pipeline",
                "components": [
                    "Historical data: Download OHLCV data for backtesting (Yahoo Finance API, Alpha Vantage)",
                    "Real-time feed: WebSocket or REST API for live prices",
                    "Data cleaning: Handle gaps, splits, dividends in historical data",
                    "Feature engineering: Calculate indicators (RSI, MACD, Bollinger Bands)",
                ],
            },
            "step_4_backtesting": {
                "title": "Backtest Thoroughly",
                "process": [
                    "Run strategy on 5+ years of historical data",
                    "Use walk-forward optimization (train on 70%, test on 30%)",
                    "Account for transaction costs, slippage, and market impact",
                    "Evaluate: Sharpe ratio > 1.5, Max drawdown < 15%, Win rate > 40%",
                ],
            },
            "step_5_paper_trading": {
                "title": "Paper Trade Before Going Live",
                "duration": "Minimum 30 days of paper trading",
                "checkpoints": [
                    "Results match backtest expectations within 20%",
                    "Order execution timing is acceptable",
                    "No unexpected errors or edge cases",
                    "Drawdown stays within limits",
                ],
            },
            "step_6_live_deployment": {
                "title": "Deploy to Live Trading",
                "checklist": [
                    "Start with 10-25% of intended capital",
                    "Monitor closely for first 2 weeks",
                    "Set up alerts for anomalous behavior",
                    "Daily P&L reconciliation",
                    "Kill switch for emergency stop",
                    "Scale up gradually as confidence builds",
                ],
            },
        },
        "recommended_python_libraries": [
            {"name": "pandas", "purpose": "Data manipulation & time series"},
            {"name": "numpy", "purpose": "Numerical computation"},
            {"name": "ta-lib / pandas-ta", "purpose": "Technical indicators"},
            {"name": "backtrader / zipline", "purpose": "Backtesting frameworks"},
            {"name": "alpaca-trade-api", "purpose": "Live trading execution"},
            {"name": "ccxt", "purpose": "Crypto exchange connectivity"},
        ],
    }


# ===================================================================
# MODULE 9: Automated Risk Management
# ===================================================================

def design_risk_management_system(
    market: str = "US Equities",
    portfolio_value: float = 100000,
    max_risk_per_trade: float = 0.02,
) -> Dict[str, Any]:
    """
    Design an automated risk management system with dynamic adjustments.
    """
    current_vix = _get_live_vix()
    volatility_regime = "low" if current_vix < 18 else ("medium" if current_vix < 25 else "high")

    vol_multipliers = {"low": 1.0, "medium": 0.7, "high": 0.4}
    effective_risk = max_risk_per_trade * vol_multipliers[volatility_regime]

    position_size_dollars = portfolio_value * effective_risk
    max_portfolio_risk = portfolio_value * 0.06

    return {
        "module": "automated_risk_management",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "market": market,
        "portfolio_value": portfolio_value,
        "volatility_assessment": {
            "vix_proxy": current_vix,
            "regime": volatility_regime,
            "risk_multiplier": vol_multipliers[volatility_regime],
        },
        "position_sizing": {
            "base_risk_per_trade": f"{max_risk_per_trade * 100}%",
            "adjusted_risk_per_trade": f"{effective_risk * 100:.2f}%",
            "max_position_dollars": round(position_size_dollars, 2),
            "max_portfolio_risk": round(max_portfolio_risk, 2),
            "formula": "Position Size = (Portfolio * Risk%) / (Entry - Stop Loss)",
        },
        "stop_loss_system": {
            "initial_stop": {
                "method": "ATR-based (2x ATR from entry)",
                "description": "Set initial stop at 2x Average True Range below entry for long positions.",
            },
            "trailing_stop": {
                "method": "Chandelier Exit",
                "description": "Trail stop at highest high minus 3x ATR, locks in profits as price advances.",
                "activation": "Activate after position is 1R in profit (risk amount).",
            },
            "time_stop": {
                "method": "Maximum holding period",
                "description": "Exit if position shows no progress after 10 trading days.",
            },
        },
        "dynamic_adjustments": [
            {
                "trigger": f"VIX rises above 25 (currently {current_vix})",
                "action": "Reduce position sizes by 30%, tighten stops to 1.5x ATR",
            },
            {
                "trigger": "3 consecutive losing trades",
                "action": "Reduce position size by 50%, require extra confirmation signal",
            },
            {
                "trigger": "Portfolio drawdown exceeds 5%",
                "action": "Halt new positions, tighten all trailing stops, review strategy",
            },
            {
                "trigger": "Correlation spike across holdings",
                "action": "Reduce net exposure, add hedging positions (VIX calls, inverse ETFs)",
            },
        ],
        "risk_metrics_monitored": [
            "Value at Risk (VaR) — 95% confidence daily",
            "Maximum Drawdown — trailing 30/60/90 day windows",
            "Sharpe Ratio — rolling 30-day (target > 1.5)",
            "Beta exposure — portfolio vs benchmark",
            "Sector concentration — max 30% in any single sector",
        ],
    }


def _backtest_from_live_bars(symbols: List[str], period_years: int = 5) -> Dict[str, Any]:
    """Compute real backtest metrics from Alpaca bar data."""
    try:
        from services.trading_platform_service import get_trading_platform
        from services.ai_trading_engine import compute_risk_metrics
        tp = get_trading_platform()
        if not tp.is_connected:
            raise RuntimeError("not connected")

        all_returns = []
        for sym in symbols[:5]:
            bars = tp.get_bars(sym, "1Day", 200)
            if not bars or len(bars) < 10:
                continue
            closes = [float(b.get("close", 0)) for b in bars if float(b.get("close", 0)) > 0]
            for i in range(1, len(closes)):
                all_returns.append((closes[i] - closes[i-1]) / closes[i-1])

        if not all_returns:
            raise RuntimeError("no data")

        wins = [r for r in all_returns if r > 0]
        losses = [r for r in all_returns if r < 0]
        total_trades = len(all_returns)
        win_rate = len(wins) / max(1, total_trades)
        avg_win_pct = (sum(wins) / max(1, len(wins))) * 100 if wins else 0
        avg_loss_pct = abs(sum(losses) / max(1, len(losses))) * 100 if losses else 0
        total_return_pct = sum(all_returns)

        cumulative = [1.0]
        for r in all_returns:
            cumulative.append(cumulative[-1] * (1 + r))
        peak = cumulative[0]
        max_dd = 0
        for v in cumulative:
            if v > peak:
                peak = v
            dd = (peak - v) / peak if peak > 0 else 0
            if dd > max_dd:
                max_dd = dd

        avg_ret = sum(all_returns) / len(all_returns)
        std_ret = (sum((r - avg_ret)**2 for r in all_returns) / max(1, len(all_returns) - 1)) ** 0.5
        sharpe = round((avg_ret / max(0.0001, std_ret)) * (252 ** 0.5), 2)
        down_rets = [r for r in all_returns if r < 0]
        down_std = (sum(r**2 for r in down_rets) / max(1, len(down_rets))) ** 0.5 if down_rets else 0.0001
        sortino = round((avg_ret / max(0.0001, down_std)) * (252 ** 0.5), 2)

        monthly = []
        chunk = max(1, len(all_returns) // 12)
        for i in range(0, len(all_returns), chunk):
            mr = sum(all_returns[i:i+chunk]) * 100
            monthly.append(round(mr, 2))

        return {
            "total_trades": total_trades,
            "win_rate": win_rate,
            "avg_win_pct": round(avg_win_pct, 2),
            "avg_loss_pct": round(avg_loss_pct, 2),
            "total_return_pct": total_return_pct,
            "max_drawdown": round(max_dd * 100, 2),
            "sharpe": sharpe,
            "sortino": sortino,
            "monthly_returns": monthly,
            "data_source": "alpaca_live",
        }
    except Exception:
        return {
            "total_trades": 0, "win_rate": 0.5, "avg_win_pct": 0, "avg_loss_pct": 0,
            "total_return_pct": 0, "max_drawdown": 0, "sharpe": 0, "sortino": 0,
            "monthly_returns": [], "data_source": "unavailable",
        }


# ===================================================================
# MODULE 10: Backtesting Trading Strategies
# ===================================================================

def backtest_strategy(
    strategy_type: str = "momentum",
    period_years: int = 5,
    initial_capital: float = 100000,
    symbols: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Guide through backtesting a trading strategy with simulated results.
    """
    if not symbols:
        symbols = ["AAPL", "MSFT", "GOOGL", "AMZN", "META"]

    # Compute backtest from real Alpaca bar data when available
    bt = _backtest_from_live_bars(symbols, period_years)
    total_trades = bt.get("total_trades", 0)
    win_rate = bt.get("win_rate", 0.5)
    winning = int(total_trades * win_rate)
    losing = total_trades - winning

    avg_win_pct = bt.get("avg_win_pct", 3.0)
    avg_loss_pct = bt.get("avg_loss_pct", 2.0)
    profit_factor = (winning * avg_win_pct) / max(1, losing * avg_loss_pct)

    total_return_pct = bt.get("total_return_pct", 0)
    final_value = initial_capital * (1 + total_return_pct)
    annualized_return = ((final_value / max(1, initial_capital)) ** (1 / max(1, period_years)) - 1) * 100

    max_drawdown = bt.get("max_drawdown", 10.0)
    sharpe = bt.get("sharpe", 0)
    sortino = bt.get("sortino", 0)
    calmar = annualized_return / max(1, max_drawdown)

    monthly_returns = bt.get("monthly_returns", [])

    equity_curve = [initial_capital]
    for mr in monthly_returns:
        equity_curve.append(round(equity_curve[-1] * (1 + mr / 100), 2))

    return {
        "module": "backtesting_strategies",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "configuration": {
            "strategy": strategy_type,
            "period": f"{period_years} years",
            "initial_capital": initial_capital,
            "symbols": symbols,
        },
        "results": {
            "final_portfolio_value": round(final_value, 2),
            "total_return_pct": round(total_return_pct * 100, 2),
            "annualized_return_pct": round(annualized_return, 2),
            "total_trades": total_trades,
            "winning_trades": winning,
            "losing_trades": losing,
            "win_rate": round(win_rate * 100, 1),
            "avg_win": f"{avg_win_pct:.2f}%",
            "avg_loss": f"-{avg_loss_pct:.2f}%",
            "profit_factor": round(profit_factor, 2),
        },
        "risk_metrics": {
            "max_drawdown": f"{max_drawdown:.1f}%",
            "sharpe_ratio": round(sharpe, 2),
            "sortino_ratio": round(sortino, 2),
            "calmar_ratio": round(calmar, 2),
        },
        "monthly_returns_sample": monthly_returns[:12],
        "equity_curve_sample": equity_curve[:13],
        "backtesting_guide": {
            "step_1": "Collect clean OHLCV data for all target symbols over the test period.",
            "step_2": "Implement strategy logic with exact entry/exit rules and indicator calculations.",
            "step_3": "Run simulation trade-by-trade, accounting for commissions ($0.005/share) and slippage (0.05%).",
            "step_4": "Calculate performance metrics: Sharpe, Sortino, Max Drawdown, Win Rate, Profit Factor.",
            "step_5": "Perform walk-forward analysis: optimize on 70% of data, validate on remaining 30%.",
            "step_6": "Stress test: run on different market regimes (2008 crisis, 2020 COVID, 2022 bear).",
            "step_7": "Compare against benchmark (S&P 500 buy-and-hold) for alpha calculation.",
        },
        "recommended_tools": [
            {"tool": "Python + Backtrader", "best_for": "Custom strategy backtesting with detailed analytics"},
            {"tool": "QuantConnect Lean", "best_for": "Cloud-based backtesting with live deployment"},
            {"tool": "Zipline (Quantopian)", "best_for": "Event-driven backtesting in Python"},
            {"tool": "TradingView Strategy Tester", "best_for": "Visual backtesting with Pine Script"},
            {"tool": "MetaTrader Strategy Tester", "best_for": "Forex and CFD strategy optimization"},
        ],
    }


# ===================================================================
# Unified dispatch for the AI tool
# ===================================================================

AVAILABLE_MODULES = {
    "market_research": {
        "name": "Market Research & Trend Analysis",
        "description": "Analyze current trends, identify emerging patterns, suggest opportunities.",
        "handler": "analyze_market_trends",
    },
    "portfolio_diversification": {
        "name": "Portfolio Diversification",
        "description": "Propose diversification strategies to minimize risk.",
        "handler": "analyze_portfolio_diversification",
    },
    "stock_screener": {
        "name": "AI-Powered Stock Screener",
        "description": "Screen stocks using fundamental and technical indicators.",
        "handler": "run_stock_screener",
    },
    "trading_strategy": {
        "name": "Automated Trading Strategy",
        "description": "Design data-driven trading strategies with entry/exit signals.",
        "handler": "design_trading_strategy",
    },
    "technical_analysis": {
        "name": "Technical Analysis",
        "description": "Evaluate a stock with RSI, MACD, moving averages, and more.",
        "handler": "run_technical_analysis",
    },
    "earnings_analysis": {
        "name": "Earnings Report Analysis",
        "description": "Interpret earnings reports and key financial metrics.",
        "handler": "analyze_earnings_report",
    },
    "growth_vs_dividend": {
        "name": "Growth vs Dividend Stocks",
        "description": "Compare growth and dividend strategies with real examples.",
        "handler": "compare_growth_vs_dividend",
    },
    "algo_trading_bots": {
        "name": "Algorithmic Trading Bots",
        "description": "Step-by-step guide to setting up algorithmic trading bots.",
        "handler": "get_algo_trading_bot_guide",
    },
    "risk_management": {
        "name": "Automated Risk Management",
        "description": "Design automated risk management systems with dynamic stops.",
        "handler": "design_risk_management_system",
    },
    "backtesting": {
        "name": "Backtesting Trading Strategies",
        "description": "Guide through backtesting with simulated results and metrics.",
        "handler": "backtest_strategy",
    },
    "live_quote": {
        "name": "Live Stock Quote",
        "description": "Real-time stock quote from Alpha Vantage (price, change, volume).",
        "handler": "get_live_stock_quote",
        "requires_live": True,
    },
    "live_history": {
        "name": "Historical Price Data",
        "description": "Daily OHLCV history for a stock from Alpha Vantage.",
        "handler": "get_live_stock_history",
        "requires_live": True,
    },
    "news_sentiment": {
        "name": "News & Sentiment",
        "description": "AI-analyzed market news with sentiment scores from Alpha Vantage.",
        "handler": "get_news_analysis",
        "requires_live": True,
    },
    "market_movers": {
        "name": "Market Movers",
        "description": "Top gainers, losers, and most active stocks right now.",
        "handler": "get_market_movers",
        "requires_live": True,
    },
    "deep_dive": {
        "name": "Deep Dive Analysis",
        "description": "Full stock analysis: multi-timeframe charts (1D-5Y), technicals, fundamentals, signals.",
        "handler": "deep_dive_analysis",
        "requires_live": True,
    },
    "compare_stocks": {
        "name": "Stock Comparison",
        "description": "Compare 2-5 stocks side-by-side: performance, fundamentals, normalized charts.",
        "handler": "compare_stocks",
        "requires_live": True,
    },
    "algo_bridge": {
        "name": "Algo-Investment Bridge",
        "description": "Bridge AI analysis to algo trading: signals, allocation, strategy recommendations.",
        "handler": "algo_investment_bridge",
    },
}


# ===================================================================
# NEW LIVE DATA MODULES
# ===================================================================

def get_live_stock_quote(symbol: str = "AAPL") -> Dict[str, Any]:
    """Get a real-time stock quote from Alpha Vantage."""
    sym = symbol.upper()
    live = _get_live_quote(sym)
    if not live:
        s = STOCK_DATABASE.get(sym)
        if s:
            return {
                "module": "live_quote", "data_source": "static", "symbol": sym,
                "name": s.get("name", sym), "price": s["price"],
                "note": "Live data unavailable, showing cached static price.",
            }
        return {"module": "live_quote", "error": f"Could not fetch quote for '{sym}'."}
    return {
        "module": "live_quote",
        "data_source": "live",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **live,
    }


def get_live_stock_history(symbol: str = "AAPL", outputsize: str = "compact") -> Dict[str, Any]:
    """Get daily price history from Alpha Vantage."""
    sym = symbol.upper()
    daily = _get_live_daily(sym, outputsize=outputsize)
    if not daily:
        return {"module": "live_history", "error": f"Could not fetch history for '{sym}'. Try again later (rate limited)."}
    bars = daily.get("bars", [])
    return {
        "module": "live_history",
        "data_source": "live",
        "symbol": sym,
        "bar_count": len(bars),
        "latest": bars[0] if bars else None,
        "bars": bars[:60],
        "source": "alpha_vantage",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def get_news_analysis(tickers: str = "", topics: str = "") -> Dict[str, Any]:
    """Get AI-analyzed news sentiment from Alpha Vantage."""
    news = _get_live_news(tickers=tickers or None, topics=topics or None)
    if not news:
        news = {}
    articles = news.get("articles") or news.get("feed") or []
    if not articles and isinstance(news, dict):
        feed = news.get("feed", [])
        if feed:
            articles = [{
                "title": item.get("title"),
                "url": item.get("url", "#"),
                "time_published": item.get("time_published"),
                "summary": item.get("summary"),
                "source": item.get("source"),
                "overall_sentiment_score": item.get("overall_sentiment_score"),
                "overall_sentiment_label": item.get("overall_sentiment_label"),
            } for item in feed[:10]]
    return {
        "module": "news_sentiment",
        "data_source": "live" if news.get("source") == "alpha_vantage" else "cached",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "articles": articles,
        "total": len(articles),
    }


def get_market_movers() -> Dict[str, Any]:
    """Get top gainers, losers, and most active stocks. Never returns empty."""
    movers = _get_live_gainers_losers()
    if not movers:
        movers = _get_fallback_movers()
    source = movers.get("source", "cached")
    return {
        "module": "market_movers",
        "data_source": "live" if source == "alpha_vantage" else "cached",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "top_gainers": movers.get("top_gainers", []),
        "top_losers": movers.get("top_losers", []),
        "most_actively_traded": movers.get("most_actively_traded", []),
        "last_updated": movers.get("last_updated", "Cached market data"),
    }


def _get_fallback_movers() -> Dict[str, Any]:
    """Import fallback data from Alpha Vantage service."""
    try:
        from services.alpha_vantage_service import _FALLBACK_MARKET_MOVERS
        return _FALLBACK_MARKET_MOVERS
    except ImportError:
        return {"top_gainers": [], "top_losers": [], "most_actively_traded": []}


# ===================================================================
# MODULE: Deep Dive Stock Analysis (multi-timeframe + full profile)
# ===================================================================

def deep_dive_analysis(symbol: str = "AAPL", timeframe: str = "1M") -> Dict[str, Any]:
    """
    Comprehensive single-stock deep dive: quote, fundamentals, technicals,
    multi-timeframe price data, and AI trading signals.
    """
    sym = symbol.upper()

    quote = _get_live_quote(sym)
    overview = _get_live_company_overview(sym)
    technical = _get_live_technical_profile(sym)
    news = _get_live_news(sym)

    TIMEFRAME_MAP = {
        "1D": ("intraday", "5min", 78),
        "1W": ("intraday", "60min", 35),
        "1M": ("daily", None, 22),
        "3M": ("daily", None, 65),
        "1Y": ("daily", None, 252),
        "5Y": ("weekly", None, 260),
    }
    series_type, interval, bar_limit = TIMEFRAME_MAP.get(timeframe, ("daily", None, 22))

    bars = []
    if series_type == "intraday" and interval:
        data = _get_live_intraday(sym, interval)
        if data:
            bars = data.get("bars", [])[:bar_limit]
    elif series_type == "weekly":
        data = _get_live_weekly(sym)
        if data:
            bars = data.get("bars", [])[:bar_limit]
    else:
        data = _get_live_daily(sym)
        if data:
            bars = data.get("bars", [])[:bar_limit]

    static = STOCK_DATABASE.get(sym, {})
    price = (quote or {}).get("price") or static.get("price")
    name = (overview or {}).get("name") or static.get("name", sym)

    signals = {}
    if technical and technical.get("signals"):
        signals = technical["signals"]

    result = {
        "module": "deep_dive",
        "data_source": "live" if quote else "static",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "symbol": sym,
        "name": name,
        "timeframe": timeframe,
        "price": price,
        "change_percent": (quote or {}).get("change_percent"),
        "previous_close": (quote or {}).get("previous_close"),
        "volume": (quote or {}).get("volume") or static.get("volume"),
        "overview": {
            "sector": (overview or {}).get("sector") or static.get("sector"),
            "industry": (overview or {}).get("industry"),
            "market_cap": (overview or {}).get("market_cap"),
            "pe_ratio": (overview or {}).get("pe_ratio") or static.get("pe"),
            "forward_pe": (overview or {}).get("forward_pe"),
            "eps": (overview or {}).get("eps") or static.get("eps"),
            "dividend_yield": (overview or {}).get("dividend_yield") or static.get("dividend_yield"),
            "beta": (overview or {}).get("beta") or static.get("beta"),
            "52_week_high": (overview or {}).get("52_week_high"),
            "52_week_low": (overview or {}).get("52_week_low"),
            "analyst_target": (overview or {}).get("analyst_target_price"),
            "profit_margin": (overview or {}).get("profit_margin"),
            "return_on_equity": (overview or {}).get("return_on_equity"),
        },
        "technicals": {
            "rsi": ((technical or {}).get("indicators", {}).get("rsi", {}) or {}).get("value"),
            "sma_50": ((technical or {}).get("indicators", {}).get("sma_50", {}) or {}).get("value"),
            "sma_200": ((technical or {}).get("indicators", {}).get("sma_200", {}) or {}).get("value"),
            "macd": (technical or {}).get("indicators", {}).get("macd", {}),
            "bollinger_bands": (technical or {}).get("indicators", {}).get("bollinger_bands", {}),
            "adx": ((technical or {}).get("indicators", {}).get("adx", {}) or {}).get("value"),
            "atr": ((technical or {}).get("indicators", {}).get("atr", {}) or {}).get("value"),
        },
        "signals": signals,
        "chart_data": {
            "timeframe": timeframe,
            "bars": bars,
            "bar_count": len(bars),
        },
        "news": (news or {}).get("articles", [])[:5],
        "available_timeframes": ["1D", "1W", "1M", "3M", "1Y", "5Y"],
    }
    return result


# ===================================================================
# MODULE: Stock Comparison (side-by-side multi-stock)
# ===================================================================

def compare_stocks(symbols: str = "AAPL,MSFT", timeframe: str = "1M") -> Dict[str, Any]:
    """
    Compare 2-5 stocks side-by-side: price performance, fundamentals, and
    normalized chart data for overlay comparison.
    """
    sym_list = [s.strip().upper() for s in symbols.split(",") if s.strip()][:5]
    if len(sym_list) < 2:
        return {"module": "compare_stocks", "error": "Provide at least 2 comma-separated symbols."}

    TIMEFRAME_MAP = {
        "1D": ("daily", 1), "1W": ("daily", 5), "1M": ("daily", 22),
        "3M": ("daily", 65), "1Y": ("daily", 252), "5Y": ("daily", 252),
    }
    _, bar_limit = TIMEFRAME_MAP.get(timeframe, ("daily", 22))

    stocks = []
    for sym in sym_list:
        quote = _get_live_quote(sym)
        overview = _get_live_company_overview(sym)
        static = STOCK_DATABASE.get(sym, {})
        daily = _get_live_daily(sym)
        bars = (daily or {}).get("bars", [])[:bar_limit] if daily else []

        price = (quote or {}).get("price") or static.get("price")
        first_price = bars[-1]["close"] if bars and bars[-1].get("close") else price

        perf_pct = round(((price - first_price) / first_price) * 100, 2) if price and first_price and first_price > 0 else 0

        normalized = []
        if bars and first_price and first_price > 0:
            for b in reversed(bars):
                normalized.append({
                    "date": b["date"],
                    "value": round(((b["close"] or 0) / first_price - 1) * 100, 2),
                })

        stocks.append({
            "symbol": sym,
            "name": (overview or {}).get("name") or static.get("name", sym),
            "price": price,
            "change_percent": (quote or {}).get("change_percent"),
            "period_return": perf_pct,
            "pe_ratio": (overview or {}).get("pe_ratio") or static.get("pe"),
            "market_cap": (overview or {}).get("market_cap") or static.get("market_cap"),
            "dividend_yield": (overview or {}).get("dividend_yield") or static.get("dividend_yield"),
            "beta": (overview or {}).get("beta") or static.get("beta"),
            "eps": (overview or {}).get("eps") or static.get("eps"),
            "sector": (overview or {}).get("sector") or static.get("sector"),
            "chart_data": normalized,
            "bar_count": len(bars),
        })

    return {
        "module": "compare_stocks",
        "data_source": "live" if LIVE_DATA_AVAILABLE else "static",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "timeframe": timeframe,
        "stocks": stocks,
        "available_timeframes": ["1D", "1W", "1M", "3M", "1Y", "5Y"],
    }


# ===================================================================
# MODULE: Algo-Investment Bridge (trade from AI analysis)
# ===================================================================

def algo_investment_bridge(
    action: str = "status",
    symbol: str = "",
    amount: float = 0,
    strategy: str = "momentum",
    customer_id: str = "",
) -> Dict[str, Any]:
    """
    Bridge between Investment AI analysis and algo trading / portfolio execution.
    Actions: status, signal, recommend_allocation
    """
    result: Dict[str, Any] = {
        "module": "algo_bridge",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "action": action,
    }

    if action == "signal" and symbol:
        sym = symbol.upper()
        profile = _get_live_technical_profile(sym)
        signals = (profile or {}).get("signals", {})
        quote = _get_live_quote(sym)
        static = STOCK_DATABASE.get(sym, {})

        recommendation = signals.get("recommendation", "HOLD")
        algo_action = "buy" if "BUY" in recommendation else ("sell" if "SELL" in recommendation else "hold")

        result["symbol"] = sym
        result["price"] = (quote or {}).get("price") or static.get("price")
        result["ai_recommendation"] = recommendation
        result["composite_score"] = signals.get("composite_score", 0)
        result["signal_details"] = signals.get("details", [])
        result["suggested_algo_action"] = algo_action
        result["suggested_strategies"] = _suggest_strategies(signals)
        result["risk_assessment"] = _assess_trade_risk(sym, signals, static)

    elif action == "recommend_allocation":
        result["portfolio_recommendations"] = [
            {"category": "Index Funds", "allocation": "40-50%", "rationale": "Core stability from broad market exposure", "suggested": ["SPY", "QQQ", "VTI"]},
            {"category": "Growth Stocks", "allocation": "20-30%", "rationale": "Higher return potential from AI/tech leaders", "suggested": ["NVDA", "MSFT", "GOOGL"]},
            {"category": "Bonds/Fixed Income", "allocation": "10-20%", "rationale": "Downside protection and income", "suggested": ["BND", "TLT", "LQD"]},
            {"category": "Crypto", "allocation": "5-10%", "rationale": "Alternative asset diversification", "suggested": ["BTC", "ETH"]},
            {"category": "Dividend", "allocation": "10-15%", "rationale": "Steady income stream", "suggested": ["JNJ", "O", "NEE"]},
        ]
        result["algo_strategies"] = [
            {"strategy": "momentum", "best_for": "Trending markets, strong directional moves"},
            {"strategy": "mean_reversion", "best_for": "Range-bound markets, oversold recoveries"},
            {"strategy": "trend_following", "best_for": "Long-term trends, lower frequency"},
            {"strategy": "dca", "best_for": "Regular contributions, averaging into positions"},
        ]

    else:
        result["bridge_status"] = "active"
        result["capabilities"] = [
            "Generate AI trading signals for any stock",
            "Get portfolio allocation recommendations",
            "Cross-reference algo strategies with AI analysis",
            "Risk assessment for trade decisions",
        ]
        result["usage"] = {
            "signal": "Set action=signal, symbol=AAPL to get AI trading signal",
            "allocate": "Set action=recommend_allocation for portfolio split advice",
        }

    return result


def _suggest_strategies(signals: Dict) -> List[Dict[str, str]]:
    score = signals.get("composite_score", 0)
    details = signals.get("details", [])
    has_trend = any("trend" in str(d.get("signal", "")).lower() for d in details)
    has_oversold = any("oversold" in str(d.get("signal", "")).lower() for d in details)

    strategies = []
    if score >= 2 and has_trend:
        strategies.append({"strategy": "trend_following", "confidence": "high", "reason": "Strong trend confirmed by multiple indicators"})
    if score >= 1:
        strategies.append({"strategy": "momentum", "confidence": "medium", "reason": "Positive momentum detected"})
    if has_oversold:
        strategies.append({"strategy": "mean_reversion", "confidence": "medium", "reason": "Oversold conditions suggest bounce potential"})
    strategies.append({"strategy": "dca", "confidence": "always", "reason": "Dollar-cost averaging is always appropriate for long-term positions"})
    return strategies


def _assess_trade_risk(sym: str, signals: Dict, static: Dict) -> Dict[str, Any]:
    score = signals.get("composite_score", 0)
    beta = static.get("beta", 1.0) or 1.0
    risk_level = "low" if abs(score) <= 1 and beta < 1.0 else ("high" if abs(score) >= 3 or beta > 1.5 else "medium")
    return {
        "risk_level": risk_level,
        "beta": beta,
        "signal_strength": abs(score),
        "max_suggested_allocation": "2%" if risk_level == "high" else ("5%" if risk_level == "medium" else "8%"),
        "stop_loss_suggestion": f"{max(2, round(beta * 3, 1))}% below entry",
    }


def dispatch_investment_ai(module: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Central dispatcher for all Investment AI modules.
    """
    handlers = {
        "market_research": analyze_market_trends,
        "portfolio_diversification": analyze_portfolio_diversification,
        "stock_screener": run_stock_screener,
        "trading_strategy": design_trading_strategy,
        "technical_analysis": run_technical_analysis,
        "earnings_analysis": analyze_earnings_report,
        "growth_vs_dividend": compare_growth_vs_dividend,
        "algo_trading_bots": get_algo_trading_bot_guide,
        "risk_management": design_risk_management_system,
        "backtesting": backtest_strategy,
        "live_quote": get_live_stock_quote,
        "live_history": get_live_stock_history,
        "news_sentiment": get_news_analysis,
        "market_movers": get_market_movers,
        "deep_dive": deep_dive_analysis,
        "compare_stocks": compare_stocks,
        "algo_bridge": algo_investment_bridge,
    }

    handler = handlers.get(module)
    if not handler:
        return {
            "error": f"Unknown module '{module}'",
            "available_modules": list(AVAILABLE_MODULES.keys()),
        }

    try:
        if module == "stock_screener":
            return handler(criteria=params if params else None)
        if module == "market_movers":
            return handler()
        return handler(**params)
    except TypeError as e:
        return {"error": f"Invalid parameters for module '{module}': {e}"}
    except Exception as e:
        return {"error": f"Error executing module '{module}': {e}"}


def get_modules_catalog() -> Dict[str, Any]:
    """Return the catalog of available AI modules."""
    return {
        "tool": "PHINS Investment AI",
        "version": "3.0.0",
        "live_data": LIVE_DATA_AVAILABLE,
        "data_provider": "Alpha Vantage" if LIVE_DATA_AVAILABLE else "Static",
        "modules": AVAILABLE_MODULES,
        "total_modules": len(AVAILABLE_MODULES),
        "available_stocks": sorted(STOCK_DATABASE.keys()),
        "available_sectors": sorted(SECTOR_DATA.keys()),
        "note": "Modules with requires_live=True use real-time Alpha Vantage data. All other modules use live data when available with static fallback.",
    }
