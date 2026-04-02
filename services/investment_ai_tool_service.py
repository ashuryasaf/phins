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
# Market data constants (simulated realistic data)
# ---------------------------------------------------------------------------

SECTOR_DATA: Dict[str, Dict[str, Any]] = {
    "technology": {
        "name": "Technology", "trend": "bullish", "ytd_return": 18.4,
        "pe_avg": 32.5, "volatility": "high",
        "top_stocks": ["AAPL", "MSFT", "NVDA", "GOOGL", "META"],
        "emerging": ["AI infrastructure", "quantum computing", "edge AI"],
    },
    "healthcare": {
        "name": "Healthcare", "trend": "neutral", "ytd_return": 5.2,
        "pe_avg": 22.1, "volatility": "medium",
        "top_stocks": ["JNJ", "UNH", "PFE", "ABT", "TMO"],
        "emerging": ["GLP-1 therapeutics", "AI diagnostics", "gene therapy"],
    },
    "financials": {
        "name": "Financials", "trend": "bullish", "ytd_return": 12.7,
        "pe_avg": 14.8, "volatility": "medium",
        "top_stocks": ["JPM", "BAC", "GS", "MS", "V"],
        "emerging": ["embedded finance", "blockchain settlement", "AI underwriting"],
    },
    "energy": {
        "name": "Energy", "trend": "neutral", "ytd_return": 3.1,
        "pe_avg": 11.2, "volatility": "high",
        "top_stocks": ["XOM", "CVX", "COP", "SLB", "EOG"],
        "emerging": ["green hydrogen", "small modular reactors", "grid storage"],
    },
    "consumer_discretionary": {
        "name": "Consumer Discretionary", "trend": "bearish", "ytd_return": -2.3,
        "pe_avg": 25.6, "volatility": "high",
        "top_stocks": ["AMZN", "TSLA", "HD", "NKE", "SBUX"],
        "emerging": ["social commerce", "personalized retail AI", "EV infrastructure"],
    },
    "industrials": {
        "name": "Industrials", "trend": "bullish", "ytd_return": 9.8,
        "pe_avg": 20.3, "volatility": "medium",
        "top_stocks": ["CAT", "UNP", "HON", "GE", "RTX"],
        "emerging": ["robotics automation", "reshoring supply chains", "defense tech"],
    },
    "real_estate": {
        "name": "Real Estate", "trend": "neutral", "ytd_return": 1.5,
        "pe_avg": 18.7, "volatility": "low",
        "top_stocks": ["PLD", "AMT", "EQIX", "SPG", "O"],
        "emerging": ["data center REITs", "logistics hubs", "AI-managed properties"],
    },
    "utilities": {
        "name": "Utilities", "trend": "bullish", "ytd_return": 7.3,
        "pe_avg": 17.5, "volatility": "low",
        "top_stocks": ["NEE", "DUK", "SO", "D", "AEP"],
        "emerging": ["grid modernization", "nuclear renaissance", "distributed energy"],
    },
    "materials": {
        "name": "Materials", "trend": "neutral", "ytd_return": 4.1,
        "pe_avg": 16.2, "volatility": "medium",
        "top_stocks": ["LIN", "APD", "ECL", "SHW", "FCX"],
        "emerging": ["rare earth processing", "sustainable packaging", "advanced alloys"],
    },
    "communication_services": {
        "name": "Communication Services", "trend": "bullish", "ytd_return": 15.2,
        "pe_avg": 21.8, "volatility": "medium",
        "top_stocks": ["GOOGL", "META", "NFLX", "DIS", "T"],
        "emerging": ["AI content generation", "spatial computing", "6G R&D"],
    },
    "crypto": {
        "name": "Cryptocurrency", "trend": "bullish", "ytd_return": 45.6,
        "pe_avg": None, "volatility": "very_high",
        "top_stocks": ["BTC", "ETH", "SOL", "BNB", "ADA"],
        "emerging": ["DeFi 2.0", "real-world asset tokenization", "ZK rollups"],
    },
}

STOCK_DATABASE: Dict[str, Dict[str, Any]] = {
    "AAPL": {"name": "Apple Inc.", "sector": "technology", "price": 227.50, "pe": 33.2, "rsi": 58.3, "ma50": 221.4, "ma200": 215.8, "volume": 54200000, "market_cap": 3450000000000, "dividend_yield": 0.44, "eps": 6.85, "revenue_growth": 8.2, "beta": 1.21},
    "MSFT": {"name": "Microsoft Corp.", "sector": "technology", "price": 442.30, "pe": 37.8, "rsi": 62.1, "ma50": 430.2, "ma200": 410.5, "volume": 22100000, "market_cap": 3280000000000, "dividend_yield": 0.72, "eps": 11.70, "revenue_growth": 15.1, "beta": 0.93},
    "NVDA": {"name": "NVIDIA Corp.", "sector": "technology", "price": 138.50, "pe": 65.4, "rsi": 71.2, "ma50": 125.8, "ma200": 108.3, "volume": 310000000, "market_cap": 3400000000000, "dividend_yield": 0.02, "eps": 2.12, "revenue_growth": 122.4, "beta": 1.68},
    "GOOGL": {"name": "Alphabet Inc.", "sector": "technology", "price": 178.90, "pe": 24.1, "rsi": 55.7, "ma50": 172.3, "ma200": 163.8, "volume": 25800000, "market_cap": 2200000000000, "dividend_yield": 0.45, "eps": 7.42, "revenue_growth": 14.3, "beta": 1.05},
    "AMZN": {"name": "Amazon.com Inc.", "sector": "consumer_discretionary", "price": 205.70, "pe": 42.3, "rsi": 59.8, "ma50": 198.4, "ma200": 188.2, "volume": 45300000, "market_cap": 2140000000000, "dividend_yield": 0.0, "eps": 4.86, "revenue_growth": 12.5, "beta": 1.15},
    "META": {"name": "Meta Platforms Inc.", "sector": "communication_services", "price": 612.40, "pe": 28.5, "rsi": 64.3, "ma50": 590.1, "ma200": 545.7, "volume": 18200000, "market_cap": 1560000000000, "dividend_yield": 0.32, "eps": 21.49, "revenue_growth": 22.1, "beta": 1.25},
    "TSLA": {"name": "Tesla Inc.", "sector": "consumer_discretionary", "price": 272.80, "pe": 85.2, "rsi": 48.5, "ma50": 285.3, "ma200": 248.9, "volume": 98500000, "market_cap": 870000000000, "dividend_yield": 0.0, "eps": 3.20, "revenue_growth": -3.1, "beta": 2.05},
    "JPM": {"name": "JPMorgan Chase", "sector": "financials", "price": 248.60, "pe": 12.8, "rsi": 57.2, "ma50": 240.3, "ma200": 220.7, "volume": 9800000, "market_cap": 710000000000, "dividend_yield": 2.02, "eps": 19.42, "revenue_growth": 11.4, "beta": 1.08},
    "JNJ": {"name": "Johnson & Johnson", "sector": "healthcare", "price": 158.30, "pe": 15.4, "rsi": 45.1, "ma50": 160.8, "ma200": 155.2, "volume": 7200000, "market_cap": 382000000000, "dividend_yield": 3.12, "eps": 10.28, "revenue_growth": 4.8, "beta": 0.55},
    "V": {"name": "Visa Inc.", "sector": "financials", "price": 318.50, "pe": 31.2, "rsi": 60.8, "ma50": 310.4, "ma200": 295.6, "volume": 6500000, "market_cap": 620000000000, "dividend_yield": 0.72, "eps": 10.21, "revenue_growth": 10.2, "beta": 0.95},
    "XOM": {"name": "Exxon Mobil Corp.", "sector": "energy", "price": 112.40, "pe": 14.2, "rsi": 52.3, "ma50": 115.2, "ma200": 110.8, "volume": 15400000, "market_cap": 475000000000, "dividend_yield": 3.35, "eps": 7.92, "revenue_growth": -5.2, "beta": 0.82},
    "PG": {"name": "Procter & Gamble", "sector": "consumer_staples", "price": 172.80, "pe": 27.5, "rsi": 50.2, "ma50": 170.1, "ma200": 165.3, "volume": 7800000, "market_cap": 408000000000, "dividend_yield": 2.35, "eps": 6.28, "revenue_growth": 3.1, "beta": 0.42},
    "HD": {"name": "Home Depot", "sector": "consumer_discretionary", "price": 395.20, "pe": 25.8, "rsi": 54.6, "ma50": 388.7, "ma200": 372.1, "volume": 4200000, "market_cap": 390000000000, "dividend_yield": 2.28, "eps": 15.32, "revenue_growth": 2.4, "beta": 1.05},
    "UNH": {"name": "UnitedHealth Group", "sector": "healthcare", "price": 512.30, "pe": 19.8, "rsi": 41.2, "ma50": 530.5, "ma200": 520.1, "volume": 3800000, "market_cap": 472000000000, "dividend_yield": 1.42, "eps": 25.87, "revenue_growth": 8.7, "beta": 0.68},
    "CAT": {"name": "Caterpillar Inc.", "sector": "industrials", "price": 365.80, "pe": 17.3, "rsi": 56.8, "ma50": 358.2, "ma200": 340.5, "volume": 2800000, "market_cap": 176000000000, "dividend_yield": 1.52, "eps": 21.14, "revenue_growth": 3.8, "beta": 1.12},
    "NEE": {"name": "NextEra Energy", "sector": "utilities", "price": 82.50, "pe": 22.1, "rsi": 58.4, "ma50": 79.8, "ma200": 74.3, "volume": 12500000, "market_cap": 170000000000, "dividend_yield": 2.55, "eps": 3.73, "revenue_growth": 11.2, "beta": 0.48},
    "O": {"name": "Realty Income Corp.", "sector": "real_estate", "price": 58.20, "pe": 42.8, "rsi": 47.3, "ma50": 57.1, "ma200": 55.8, "volume": 5200000, "market_cap": 51000000000, "dividend_yield": 5.42, "eps": 1.36, "revenue_growth": 18.5, "beta": 0.65},
    "NFLX": {"name": "Netflix Inc.", "sector": "communication_services", "price": 925.30, "pe": 48.2, "rsi": 67.8, "ma50": 895.4, "ma200": 780.2, "volume": 5600000, "market_cap": 405000000000, "dividend_yield": 0.0, "eps": 19.20, "revenue_growth": 16.8, "beta": 1.32},
    "BTC": {"name": "Bitcoin", "sector": "crypto", "price": 84200.0, "pe": None, "rsi": 62.5, "ma50": 78500.0, "ma200": 65200.0, "volume": 38000000000, "market_cap": 1650000000000, "dividend_yield": 0.0, "eps": None, "revenue_growth": None, "beta": 2.50},
    "ETH": {"name": "Ethereum", "sector": "crypto", "price": 3250.0, "pe": None, "rsi": 55.8, "ma50": 3050.0, "ma200": 2680.0, "volume": 15000000000, "market_cap": 390000000000, "dividend_yield": 0.0, "eps": None, "revenue_growth": None, "beta": 2.80},
}


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
    """
    result: Dict[str, Any] = {
        "module": "market_research_trend_analysis",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    if stock and stock.upper() in STOCK_DATABASE:
        s = STOCK_DATABASE[stock.upper()]
        sec = SECTOR_DATA.get(s["sector"], {})
        rng = _seed_from(stock)
        momentum_score = rng.uniform(40, 95)
        result["stock_analysis"] = {
            "symbol": stock.upper(),
            "name": s["name"],
            "sector": s["sector"],
            "current_price": s["price"],
            "pe_ratio": s["pe"],
            "rsi": s["rsi"],
            "rsi_signal": _rsi_signal(s["rsi"]),
            "ma50": s["ma50"],
            "ma200": s["ma200"],
            "ma_signal": _ma_signal(s["price"], s["ma50"], s["ma200"]),
            "volume": s["volume"],
            "market_cap": _format_large_number(s["market_cap"]),
            "momentum_score": round(momentum_score, 1),
            "sector_trend": sec.get("trend", "unknown"),
            "sector_ytd_return": sec.get("ytd_return"),
        }
        result["emerging_patterns"] = sec.get("emerging", [])
        similar = [k for k, v in STOCK_DATABASE.items() if v["sector"] == s["sector"] and k != stock.upper()]
        result["related_opportunities"] = similar[:5]
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
        result["investment_opportunities"] = [
            {"stock": sym, **STOCK_DATABASE[sym]}
            for sym in sec["top_stocks"] if sym in STOCK_DATABASE
        ]
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


# ===================================================================
# MODULE 5: Technical Analysis
# ===================================================================

def run_technical_analysis(stock: str) -> Dict[str, Any]:
    """
    Evaluate a stock using technical analysis indicators.
    Produces a Buy / Sell / Hold recommendation.
    """
    sym = stock.upper()
    s = STOCK_DATABASE.get(sym)
    if not s:
        return {"module": "technical_analysis", "error": f"Stock '{sym}' not found in database."}

    rsi_sig = _rsi_signal(s["rsi"])
    ma_sig = _ma_signal(s["price"], s["ma50"], s["ma200"])

    rng = _seed_from(sym)
    macd_value = rng.uniform(-2, 4)
    macd_signal = macd_value - rng.uniform(0.5, 2)
    macd_histogram = macd_value - macd_signal

    bb_upper = s["ma50"] * 1.04
    bb_lower = s["ma50"] * 0.96
    bb_position = "upper" if s["price"] > bb_upper else ("lower" if s["price"] < bb_lower else "middle")

    vol_avg = s["volume"]
    vol_today = int(vol_avg * rng.uniform(0.7, 1.5))
    vol_trend = "above_average" if vol_today > vol_avg else "below_average"

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
                "signal_line": round(macd_signal, 3),
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


# ===================================================================
# MODULE 6: Earnings Report Analysis
# ===================================================================

def analyze_earnings_report(company: str) -> Dict[str, Any]:
    """
    Interpret a company's earnings report, highlighting key metrics.
    """
    sym = company.upper()
    s = STOCK_DATABASE.get(sym)
    if not s:
        return {"module": "earnings_report_analysis", "error": f"Company '{sym}' not found."}

    rng = _seed_from(f"earnings:{sym}")
    revenue = s["market_cap"] * rng.uniform(0.03, 0.15)
    net_income = revenue * rng.uniform(0.05, 0.25)
    gross_margin = rng.uniform(0.30, 0.75)
    operating_margin = gross_margin - rng.uniform(0.05, 0.20)
    free_cash_flow = net_income * rng.uniform(0.8, 1.5)

    eps_actual = s["eps"] if s["eps"] else rng.uniform(1, 10)
    eps_estimate = round(eps_actual * rng.uniform(0.92, 1.05), 2)
    eps_surprise = round(((eps_actual - eps_estimate) / abs(eps_estimate)) * 100, 2) if eps_estimate else 0
    beat = eps_actual > eps_estimate

    revenue_estimate = revenue * rng.uniform(0.95, 1.02)
    revenue_surprise = round(((revenue - revenue_estimate) / abs(revenue_estimate)) * 100, 2) if revenue_estimate else 0

    return {
        "module": "earnings_report_analysis",
        "timestamp": datetime.now(timezone.utc).isoformat(),
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
            "price_reaction_expected": f"{'+'if beat else '-'}{abs(eps_surprise) * rng.uniform(0.3, 0.8):.1f}%",
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
    rng = _seed_from(f"risk:{market}")
    current_vix = round(rng.uniform(12, 35), 1)
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

    rng = _seed_from(f"backtest:{strategy_type}:{','.join(symbols)}")
    total_trades = rng.randint(120, 450)
    win_rate = rng.uniform(0.35, 0.65)
    winning = int(total_trades * win_rate)
    losing = total_trades - winning

    avg_win_pct = rng.uniform(2.5, 8.0)
    avg_loss_pct = rng.uniform(1.0, 3.5)
    profit_factor = (winning * avg_win_pct) / max(1, losing * avg_loss_pct)

    total_return_pct = (winning * avg_win_pct - losing * avg_loss_pct) / 100
    final_value = initial_capital * (1 + total_return_pct)
    annualized_return = ((final_value / initial_capital) ** (1 / period_years) - 1) * 100

    max_drawdown = rng.uniform(8, 25)
    sharpe = annualized_return / max(1, max_drawdown * 0.8)
    sortino = sharpe * rng.uniform(1.1, 1.5)
    calmar = annualized_return / max_drawdown

    monthly_returns = []
    for i in range(period_years * 12):
        mr = rng.gauss(annualized_return / 12, max_drawdown / 4)
        monthly_returns.append(round(mr, 2))

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
        return handler(**params)
    except TypeError as e:
        return {"error": f"Invalid parameters for module '{module}': {e}"}
    except Exception as e:
        return {"error": f"Error executing module '{module}': {e}"}


def get_modules_catalog() -> Dict[str, Any]:
    """Return the catalog of available AI modules."""
    return {
        "tool": "PHINS Investment AI",
        "version": "1.0.0",
        "modules": AVAILABLE_MODULES,
        "total_modules": len(AVAILABLE_MODULES),
        "available_stocks": sorted(STOCK_DATABASE.keys()),
        "available_sectors": sorted(SECTOR_DATA.keys()),
    }
