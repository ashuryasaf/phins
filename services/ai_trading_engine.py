"""
PHINS AI Trading Engine
=======================
Real AI-powered trading analysis engine using ONLY live Alpaca data.
Provides technical indicator computation, signal generation, risk analytics,
auto-pilot strategy bots, and a live market screener.

Consumed by trading_platform_service.py — does NOT import other PHINS services.
"""

from __future__ import annotations

import math
import time
import threading
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Universe of symbols by sector
# ---------------------------------------------------------------------------

UNIVERSE: Dict[str, List[str]] = {
    "mega_cap": ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "BRK.B", "JPM", "V"],
    "tech": ["CRM", "ADBE", "INTC", "AMD", "QCOM", "AVGO", "ORCL", "NFLX", "PYPL", "SQ"],
    "finance": ["GS", "MS", "BAC", "C", "WFC", "AXP", "BLK", "SCHW", "USB", "PNC"],
    "energy": ["XOM", "CVX", "COP", "SLB", "EOG", "MPC", "PSX", "VLO", "OXY", "HAL"],
    "healthcare": ["UNH", "JNJ", "PFE", "ABBV", "MRK", "LLY", "TMO", "ABT", "DHR", "BMY"],
    "consumer": ["WMT", "COST", "HD", "MCD", "NKE", "SBUX", "TGT", "LOW", "TJX", "DG"],
    "industrial": ["CAT", "DE", "HON", "UPS", "BA", "RTX", "LMT", "GE", "MMM", "EMR"],
    "etf_indices": ["SPY", "QQQ", "DIA", "IWM", "VTI", "EFA", "EEM", "VGK", "EWJ", "FXI"],
    "sector_etfs": ["XLK", "XLF", "XLE", "XLV", "XLI", "XLP", "XLY", "XLU", "XLRE", "XLC"],
    "commodities": ["GLD", "SLV", "USO", "UNG", "CPER", "DBA", "PALL", "PPLT", "WEAT", "CORN"],
    "bonds": ["TLT", "IEF", "BND", "HYG", "LQD", "TIP", "AGG", "MUB", "SHY", "GOVT"],
    "crypto": [
        "BTC/USD", "ETH/USD", "SOL/USD", "DOGE/USD", "AVAX/USD",
        "LINK/USD", "DOT/USD", "ADA/USD", "MATIC/USD", "SHIB/USD",
    ],
}

ALL_EQUITY_SYMBOLS: List[str] = [
    s for sector, syms in UNIVERSE.items() if sector != "crypto" for s in syms
]


# ---------------------------------------------------------------------------
# Numeric helpers — safe from NaN, Inf, division-by-zero
# ---------------------------------------------------------------------------

def _sf(val: Any, default: float = 0.0) -> float:
    """Safe float conversion."""
    if val is None:
        return default
    try:
        f = float(val)
        return f if math.isfinite(f) else default
    except (ValueError, TypeError):
        return default


def _safe_div(num: float, den: float, default: float = 0.0) -> float:
    if den == 0.0 or not math.isfinite(num) or not math.isfinite(den):
        return default
    result = num / den
    return result if math.isfinite(result) else default


def _extract_closes(bars: List[Dict]) -> List[float]:
    return [_sf(b.get("close")) for b in bars if _sf(b.get("close")) != 0.0]


def _extract_field(bars: List[Dict], key: str) -> List[float]:
    return [_sf(b.get(key)) for b in bars]


# ---------------------------------------------------------------------------
# 1. Technical indicator computation
# ---------------------------------------------------------------------------

def _sma(values: List[float], period: int) -> List[float]:
    """Simple Moving Average over a list. Returns list of same length (NaN-padded)."""
    result: List[float] = []
    for i in range(len(values)):
        if i < period - 1:
            result.append(float("nan"))
        else:
            window = values[i - period + 1: i + 1]
            result.append(sum(window) / period)
    return result


def _ema(values: List[float], period: int) -> List[float]:
    """Exponential Moving Average. First value seeded with SMA."""
    if not values or period <= 0:
        return []
    result: List[float] = []
    k = 2.0 / (period + 1)
    seed_vals = values[:period]
    if len(seed_vals) < period:
        return [float("nan")] * len(values)
    seed = sum(seed_vals) / period
    for i in range(len(values)):
        if i < period - 1:
            result.append(float("nan"))
        elif i == period - 1:
            result.append(seed)
        else:
            prev = result[-1]
            if not math.isfinite(prev):
                result.append(values[i])
            else:
                result.append(values[i] * k + prev * (1.0 - k))
    return result


def _rsi(closes: List[float], period: int = 14) -> List[float]:
    """Wilder-smoothed RSI."""
    if len(closes) < period + 1:
        return [float("nan")] * len(closes)

    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [max(d, 0.0) for d in deltas]
    losses = [abs(min(d, 0.0)) for d in deltas]

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    rsi_vals: List[float] = [float("nan")] * period
    rs = _safe_div(avg_gain, avg_loss, default=100.0)
    rsi_vals.append(100.0 - _safe_div(100.0, 1.0 + rs, default=0.0))

    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        rs = _safe_div(avg_gain, avg_loss, default=100.0)
        rsi_vals.append(100.0 - _safe_div(100.0, 1.0 + rs, default=0.0))

    return rsi_vals


def _macd(closes: List[float], fast: int = 12, slow: int = 26, signal_period: int = 9) -> Tuple[List[float], List[float], List[float]]:
    """MACD line, signal line, histogram."""
    ema_fast = _ema(closes, fast)
    ema_slow = _ema(closes, slow)
    macd_line: List[float] = []
    for ef, es in zip(ema_fast, ema_slow):
        if math.isfinite(ef) and math.isfinite(es):
            macd_line.append(ef - es)
        else:
            macd_line.append(float("nan"))

    valid_macd = [v for v in macd_line if math.isfinite(v)]
    signal_line_raw = _ema(valid_macd, signal_period) if valid_macd else []

    signal_line: List[float] = []
    vi = 0
    for v in macd_line:
        if math.isfinite(v):
            signal_line.append(signal_line_raw[vi] if vi < len(signal_line_raw) else float("nan"))
            vi += 1
        else:
            signal_line.append(float("nan"))

    histogram: List[float] = []
    for m, s in zip(macd_line, signal_line):
        if math.isfinite(m) and math.isfinite(s):
            histogram.append(m - s)
        else:
            histogram.append(float("nan"))

    return macd_line, signal_line, histogram


def _bollinger(closes: List[float], period: int = 20, num_std: float = 2.0) -> Tuple[List[float], List[float], List[float]]:
    """Bollinger Bands: upper, middle (SMA), lower."""
    middle = _sma(closes, period)
    upper: List[float] = []
    lower: List[float] = []
    for i in range(len(closes)):
        if i < period - 1 or not math.isfinite(middle[i]):
            upper.append(float("nan"))
            lower.append(float("nan"))
        else:
            window = closes[i - period + 1: i + 1]
            mean = middle[i]
            variance = sum((x - mean) ** 2 for x in window) / period
            std = math.sqrt(variance)
            upper.append(mean + num_std * std)
            lower.append(mean - num_std * std)
    return upper, middle, lower


def _atr(bars: List[Dict], period: int = 14) -> List[float]:
    """Average True Range."""
    if len(bars) < 2:
        return [float("nan")] * len(bars)

    tr_vals: List[float] = [float("nan")]
    for i in range(1, len(bars)):
        h = _sf(bars[i].get("high"))
        l = _sf(bars[i].get("low"))
        pc = _sf(bars[i - 1].get("close"))
        tr = max(h - l, abs(h - pc), abs(l - pc))
        tr_vals.append(tr)

    atr_vals: List[float] = [float("nan")] * period
    valid_tr = [v for v in tr_vals[1:] if math.isfinite(v)]
    if len(valid_tr) < period:
        return [float("nan")] * len(bars)

    atr_val = sum(valid_tr[:period]) / period
    atr_vals.append(atr_val)

    for i in range(period + 1, len(tr_vals)):
        if math.isfinite(tr_vals[i]):
            atr_val = (atr_val * (period - 1) + tr_vals[i]) / period
        atr_vals.append(atr_val)

    return atr_vals


def _obv(bars: List[Dict]) -> List[float]:
    """On-Balance Volume."""
    if not bars:
        return []
    closes = _extract_field(bars, "close")
    volumes = _extract_field(bars, "volume")
    obv_vals: List[float] = [volumes[0] if volumes else 0.0]
    for i in range(1, len(bars)):
        if closes[i] > closes[i - 1]:
            obv_vals.append(obv_vals[-1] + volumes[i])
        elif closes[i] < closes[i - 1]:
            obv_vals.append(obv_vals[-1] - volumes[i])
        else:
            obv_vals.append(obv_vals[-1])
    return obv_vals


def _vwap(bars: List[Dict]) -> List[float]:
    """Cumulative VWAP — meaningful for intraday bars."""
    cum_vol = 0.0
    cum_tp_vol = 0.0
    result: List[float] = []
    for b in bars:
        h = _sf(b.get("high"))
        l = _sf(b.get("low"))
        c = _sf(b.get("close"))
        v = _sf(b.get("volume"))
        tp = (h + l + c) / 3.0 if (h + l + c) > 0 else 0.0
        cum_vol += v
        cum_tp_vol += tp * v
        result.append(_safe_div(cum_tp_vol, cum_vol))
    return result


def _stochastic(bars: List[Dict], k_period: int = 14, d_period: int = 3, smooth_k: int = 3) -> Tuple[List[float], List[float]]:
    """Stochastic Oscillator %K and %D."""
    if len(bars) < k_period:
        return [float("nan")] * len(bars), [float("nan")] * len(bars)

    highs = _extract_field(bars, "high")
    lows = _extract_field(bars, "low")
    closes = _extract_field(bars, "close")

    raw_k: List[float] = []
    for i in range(len(bars)):
        if i < k_period - 1:
            raw_k.append(float("nan"))
        else:
            h_max = max(highs[i - k_period + 1: i + 1])
            l_min = min(lows[i - k_period + 1: i + 1])
            raw_k.append(_safe_div(closes[i] - l_min, h_max - l_min, 0.5) * 100.0)

    pct_k = _sma(
        [v if math.isfinite(v) else 50.0 for v in raw_k],
        smooth_k,
    )
    pct_d = _sma(
        [v if math.isfinite(v) else 50.0 for v in pct_k],
        d_period,
    )
    return pct_k, pct_d


def _last_finite(series: List[float]) -> Optional[float]:
    for v in reversed(series):
        if math.isfinite(v):
            return round(v, 6)
    return None


def _last_n_finite(series: List[float], n: int = 2) -> List[Optional[float]]:
    out: List[Optional[float]] = []
    for v in reversed(series):
        if math.isfinite(v):
            out.append(round(v, 6))
            if len(out) >= n:
                break
    out.reverse()
    return out


def compute_technicals(bars: List[Dict]) -> Dict[str, Any]:
    """
    Compute a full suite of technical indicators from OHLCV bars.

    Each bar must have keys: open, high, low, close, volume.
    Returns a dict with the latest value (and recent values where useful)
    for every indicator.
    """
    if not bars:
        return {"error": "no_bars", "indicators": {}}

    closes = _extract_closes(bars)
    if len(closes) < 2:
        return {"error": "insufficient_data", "bar_count": len(bars), "indicators": {}}

    rsi_vals = _rsi(closes)
    macd_line, signal_line, histogram = _macd(closes)
    bb_upper, bb_middle, bb_lower = _bollinger(closes)
    sma20 = _sma(closes, 20)
    sma50 = _sma(closes, 50)
    ema12 = _ema(closes, 12)
    ema26 = _ema(closes, 26)
    atr_vals = _atr(bars)
    obv_vals = _obv(bars)
    vwap_vals = _vwap(bars)
    stoch_k, stoch_d = _stochastic(bars)

    bb_width = None
    bbu = _last_finite(bb_upper)
    bbl = _last_finite(bb_lower)
    bbm = _last_finite(bb_middle)
    if bbu is not None and bbl is not None and bbm and bbm > 0:
        bb_width = round((bbu - bbl) / bbm, 6)

    indicators: Dict[str, Any] = {
        "rsi_14": _last_finite(rsi_vals),
        "macd_line": _last_finite(macd_line),
        "macd_signal": _last_finite(signal_line),
        "macd_histogram": _last_finite(histogram),
        "macd_prev_histogram": (_last_n_finite(histogram, 2) or [None, None])[0],
        "bb_upper": bbu,
        "bb_middle": bbm,
        "bb_lower": bbl,
        "bb_width": bb_width,
        "sma_20": _last_finite(sma20),
        "sma_50": _last_finite(sma50),
        "ema_12": _last_finite(ema12),
        "ema_26": _last_finite(ema26),
        "atr_14": _last_finite(atr_vals),
        "obv": _last_finite(obv_vals),
        "vwap": _last_finite(vwap_vals),
        "stoch_k": _last_finite(stoch_k),
        "stoch_d": _last_finite(stoch_d),
    }

    prev_ema12 = _last_n_finite(ema12, 2)
    prev_ema26 = _last_n_finite(ema26, 2)
    prev_sma20 = _last_n_finite(sma20, 2)
    prev_sma50 = _last_n_finite(sma50, 2)
    prev_macd = _last_n_finite(macd_line, 2)
    prev_signal = _last_n_finite(signal_line, 2)
    prev_stoch_k = _last_n_finite(stoch_k, 2)
    prev_stoch_d = _last_n_finite(stoch_d, 2)

    indicators["_prev"] = {
        "ema_12": prev_ema12,
        "ema_26": prev_ema26,
        "sma_20": prev_sma20,
        "sma_50": prev_sma50,
        "macd_line": prev_macd,
        "macd_signal": prev_signal,
        "stoch_k": prev_stoch_k,
        "stoch_d": prev_stoch_d,
    }

    latest_vol = _sf(bars[-1].get("volume")) if bars else 0.0
    vol_sma = _sma(_extract_field(bars, "volume"), 20)
    avg_vol = _last_finite(vol_sma)
    indicators["volume_latest"] = latest_vol
    indicators["volume_sma_20"] = avg_vol
    indicators["volume_ratio"] = round(_safe_div(latest_vol, avg_vol or 1.0), 4) if avg_vol else None

    indicators["bar_count"] = len(bars)
    indicators["latest_close"] = closes[-1] if closes else None

    return {"indicators": indicators}


# ---------------------------------------------------------------------------
# 2. Signal generation
# ---------------------------------------------------------------------------

def _crossover(prev: List[Optional[float]], current_a: Optional[float], current_b: Optional[float], key_a: str, key_b: str) -> Optional[str]:
    """Detect crossover: returns 'bullish' / 'bearish' / None."""
    prev_vals = prev or []
    if len(prev_vals) < 2 or current_a is None or current_b is None:
        return None
    pa, pb = prev_vals[0], prev_vals[1] if len(prev_vals) > 1 else prev_vals[0]
    if pa is None or pb is None:
        return None
    if pa <= pb and current_a > current_b:
        return "bullish"
    if pa >= pb and current_a < current_b:
        return "bearish"
    return None


def generate_signals(technicals: Dict[str, Any], price: float) -> Dict[str, Any]:
    """
    Generate composite trading signals from technical indicators.

    Returns:
        {
            "recommendation": "STRONG BUY|BUY|HOLD|SELL|STRONG SELL",
            "composite_score": float (-5 to 5),
            "details": [list of signal dicts],
            "confidence": float (0–1),
        }
    """
    ind = technicals.get("indicators", {})
    if not ind or price <= 0:
        return {
            "recommendation": "HOLD",
            "composite_score": 0.0,
            "details": [],
            "confidence": 0.0,
        }

    prev = ind.get("_prev", {})
    signals: List[Dict[str, Any]] = []
    score = 0.0
    max_possible = 0.0

    # --- RSI ---
    rsi = ind.get("rsi_14")
    if rsi is not None:
        max_possible += 2.0
        if rsi < 25:
            signals.append({"name": "RSI", "signal": "STRONG BUY", "value": rsi, "note": "Deeply oversold"})
            score += 2.0
        elif rsi < 30:
            signals.append({"name": "RSI", "signal": "BUY", "value": rsi, "note": "Oversold"})
            score += 1.0
        elif rsi > 75:
            signals.append({"name": "RSI", "signal": "STRONG SELL", "value": rsi, "note": "Deeply overbought"})
            score -= 2.0
        elif rsi > 70:
            signals.append({"name": "RSI", "signal": "SELL", "value": rsi, "note": "Overbought"})
            score -= 1.0
        else:
            signals.append({"name": "RSI", "signal": "NEUTRAL", "value": rsi, "note": "Neutral range"})

    # --- MACD crossover ---
    macd_val = ind.get("macd_line")
    macd_sig = ind.get("macd_signal")
    macd_hist = ind.get("macd_histogram")
    prev_hist = ind.get("macd_prev_histogram")
    if macd_val is not None and macd_sig is not None:
        max_possible += 2.0
        prev_macd = prev.get("macd_line", [])
        prev_signal = prev.get("macd_signal", [])
        if len(prev_macd) >= 2 and len(prev_signal) >= 2:
            prev_m, prev_s = prev_macd[0], prev_signal[0]
            if prev_m is not None and prev_s is not None:
                if prev_m <= prev_s and macd_val > macd_sig:
                    signals.append({"name": "MACD", "signal": "BUY", "value": macd_val, "note": "Bullish crossover"})
                    score += 1.5
                elif prev_m >= prev_s and macd_val < macd_sig:
                    signals.append({"name": "MACD", "signal": "SELL", "value": macd_val, "note": "Bearish crossover"})
                    score -= 1.5
                elif macd_val > macd_sig:
                    signals.append({"name": "MACD", "signal": "BUY", "value": macd_val, "note": "Bullish momentum"})
                    score += 0.5
                else:
                    signals.append({"name": "MACD", "signal": "SELL", "value": macd_val, "note": "Bearish momentum"})
                    score -= 0.5
        elif macd_val > macd_sig:
            signals.append({"name": "MACD", "signal": "BUY", "value": macd_val, "note": "Above signal line"})
            score += 0.5
        else:
            signals.append({"name": "MACD", "signal": "SELL", "value": macd_val, "note": "Below signal line"})
            score -= 0.5

    if macd_hist is not None and prev_hist is not None:
        if macd_hist > 0 and prev_hist < 0:
            signals.append({"name": "MACD_HIST", "signal": "BUY", "value": macd_hist, "note": "Histogram turned positive"})
            score += 0.5
        elif macd_hist < 0 and prev_hist > 0:
            signals.append({"name": "MACD_HIST", "signal": "SELL", "value": macd_hist, "note": "Histogram turned negative"})
            score -= 0.5

    # --- Bollinger Bands ---
    bbu = ind.get("bb_upper")
    bbl = ind.get("bb_lower")
    bbm = ind.get("bb_middle")
    bb_width = ind.get("bb_width")
    if bbu is not None and bbl is not None:
        max_possible += 1.5
        if price <= bbl:
            signals.append({"name": "BB", "signal": "BUY", "value": price, "note": "At/below lower band"})
            score += 1.5
        elif price >= bbu:
            signals.append({"name": "BB", "signal": "SELL", "value": price, "note": "At/above upper band"})
            score -= 1.5
        elif bbm is not None and price < bbm:
            signals.append({"name": "BB", "signal": "BUY", "value": price, "note": "Below middle band"})
            score += 0.3
        elif bbm is not None:
            signals.append({"name": "BB", "signal": "SELL", "value": price, "note": "Above middle band"})
            score -= 0.3

        if bb_width is not None and bb_width < 0.04:
            signals.append({"name": "BB_SQUEEZE", "signal": "NEUTRAL", "value": bb_width, "note": "Tight squeeze — breakout imminent"})

    # --- SMA / EMA crossovers ---
    sma20 = ind.get("sma_20")
    sma50 = ind.get("sma_50")
    ema12 = ind.get("ema_12")
    ema26 = ind.get("ema_26")

    if sma20 is not None and sma50 is not None:
        max_possible += 2.0
        prev_sma20 = prev.get("sma_20", [])
        prev_sma50 = prev.get("sma_50", [])
        if len(prev_sma20) >= 2 and len(prev_sma50) >= 2:
            p20, p50 = prev_sma20[0], prev_sma50[0]
            if p20 is not None and p50 is not None:
                if p20 <= p50 and sma20 > sma50:
                    signals.append({"name": "GOLDEN_CROSS", "signal": "STRONG BUY", "value": sma20, "note": "SMA20 crossed above SMA50"})
                    score += 2.0
                elif p20 >= p50 and sma20 < sma50:
                    signals.append({"name": "DEATH_CROSS", "signal": "STRONG SELL", "value": sma20, "note": "SMA20 crossed below SMA50"})
                    score -= 2.0
                elif sma20 > sma50:
                    signals.append({"name": "SMA_TREND", "signal": "BUY", "value": sma20, "note": "SMA20 > SMA50 (uptrend)"})
                    score += 0.5
                else:
                    signals.append({"name": "SMA_TREND", "signal": "SELL", "value": sma20, "note": "SMA20 < SMA50 (downtrend)"})
                    score -= 0.5
        elif sma20 > sma50:
            signals.append({"name": "SMA_TREND", "signal": "BUY", "value": sma20, "note": "SMA20 > SMA50"})
            score += 0.5
        else:
            signals.append({"name": "SMA_TREND", "signal": "SELL", "value": sma20, "note": "SMA20 < SMA50"})
            score -= 0.5

    if ema12 is not None and ema26 is not None:
        max_possible += 1.0
        if ema12 > ema26:
            signals.append({"name": "EMA_TREND", "signal": "BUY", "value": ema12, "note": "EMA12 > EMA26"})
            score += 0.5
        else:
            signals.append({"name": "EMA_TREND", "signal": "SELL", "value": ema12, "note": "EMA12 < EMA26"})
            score -= 0.5

    # --- Price vs SMA ---
    if sma20 is not None:
        max_possible += 1.0
        if price > sma20:
            signals.append({"name": "PRICE_SMA20", "signal": "BUY", "value": price, "note": "Price above SMA20"})
            score += 0.5
        else:
            signals.append({"name": "PRICE_SMA20", "signal": "SELL", "value": price, "note": "Price below SMA20"})
            score -= 0.5

    # --- Volume confirmation ---
    vol_ratio = ind.get("volume_ratio")
    if vol_ratio is not None:
        max_possible += 1.0
        if vol_ratio > 1.5:
            direction = "BUY" if score > 0 else "SELL"
            signals.append({"name": "VOLUME", "signal": direction, "value": vol_ratio, "note": f"High volume confirms trend ({vol_ratio:.2f}x avg)"})
            score += 0.5 if score > 0 else -0.5
        elif vol_ratio < 0.5:
            signals.append({"name": "VOLUME", "signal": "NEUTRAL", "value": vol_ratio, "note": "Low volume — weak conviction"})
        else:
            signals.append({"name": "VOLUME", "signal": "NEUTRAL", "value": vol_ratio, "note": "Normal volume"})

    # --- Stochastic ---
    stoch_k = ind.get("stoch_k")
    stoch_d = ind.get("stoch_d")
    if stoch_k is not None and stoch_d is not None:
        max_possible += 1.5
        if stoch_k < 20 and stoch_d < 20:
            signals.append({"name": "STOCH", "signal": "BUY", "value": stoch_k, "note": "Stochastic oversold"})
            score += 1.0
        elif stoch_k > 80 and stoch_d > 80:
            signals.append({"name": "STOCH", "signal": "SELL", "value": stoch_k, "note": "Stochastic overbought"})
            score -= 1.0
        else:
            prev_k = prev.get("stoch_k", [])
            prev_d = prev.get("stoch_d", [])
            if len(prev_k) >= 2 and len(prev_d) >= 2:
                pk, pd = prev_k[0], prev_d[0]
                if pk is not None and pd is not None:
                    if pk <= pd and stoch_k > stoch_d:
                        signals.append({"name": "STOCH", "signal": "BUY", "value": stoch_k, "note": "Bullish crossover"})
                        score += 0.5
                    elif pk >= pd and stoch_k < stoch_d:
                        signals.append({"name": "STOCH", "signal": "SELL", "value": stoch_k, "note": "Bearish crossover"})
                        score -= 0.5
                    else:
                        signals.append({"name": "STOCH", "signal": "NEUTRAL", "value": stoch_k, "note": "No crossover"})
                else:
                    signals.append({"name": "STOCH", "signal": "NEUTRAL", "value": stoch_k, "note": "Insufficient history"})
            else:
                signals.append({"name": "STOCH", "signal": "NEUTRAL", "value": stoch_k, "note": "Neutral range"})

    clamped = max(-5.0, min(5.0, score))
    confidence = min(1.0, abs(clamped) / 5.0) if max_possible > 0 else 0.0

    if clamped >= 3.0:
        rec = "STRONG BUY"
    elif clamped >= 1.0:
        rec = "BUY"
    elif clamped <= -3.0:
        rec = "STRONG SELL"
    elif clamped <= -1.0:
        rec = "SELL"
    else:
        rec = "HOLD"

    return {
        "recommendation": rec,
        "composite_score": round(clamped, 2),
        "details": signals,
        "confidence": round(confidence, 3),
    }


# ---------------------------------------------------------------------------
# 3. Risk metrics
# ---------------------------------------------------------------------------

def compute_risk_metrics(bars: List[Dict], positions: Optional[List[Dict]] = None) -> Dict[str, Any]:
    """
    Compute portfolio risk metrics from historical bars.

    Parameters:
        bars: OHLCV bars (daily recommended) for the primary asset or portfolio proxy.
        positions: optional list of position dicts (each with qty, market_value, unrealized_pl).

    Returns dict with VaR, max drawdown, volatility, beta, Sharpe, Sortino.
    """
    if not bars or len(bars) < 3:
        return {
            "var_95": None,
            "var_99": None,
            "max_drawdown": None,
            "volatility_annual": None,
            "beta_vs_spy": None,
            "sharpe_ratio": None,
            "sortino_ratio": None,
            "daily_returns_count": 0,
        }

    closes = _extract_closes(bars)
    if len(closes) < 3:
        return {
            "var_95": None, "var_99": None, "max_drawdown": None,
            "volatility_annual": None, "beta_vs_spy": None,
            "sharpe_ratio": None, "sortino_ratio": None,
            "daily_returns_count": 0,
        }

    returns: List[float] = []
    for i in range(1, len(closes)):
        if closes[i - 1] != 0:
            returns.append((closes[i] - closes[i - 1]) / closes[i - 1])

    if not returns:
        return {
            "var_95": None, "var_99": None, "max_drawdown": None,
            "volatility_annual": None, "beta_vs_spy": None,
            "sharpe_ratio": None, "sortino_ratio": None,
            "daily_returns_count": 0,
        }

    sorted_r = sorted(returns)
    n = len(sorted_r)

    var_95_idx = max(0, int(n * 0.05) - 1)
    var_99_idx = max(0, int(n * 0.01) - 1)
    var_95 = round(sorted_r[var_95_idx] * 100, 4)
    var_99 = round(sorted_r[var_99_idx] * 100, 4)

    # Max drawdown from equity curve
    peak = closes[0]
    max_dd = 0.0
    for c in closes:
        if c > peak:
            peak = c
        dd = _safe_div(peak - c, peak) if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd

    mean_r = sum(returns) / len(returns)
    var_r = sum((r - mean_r) ** 2 for r in returns) / len(returns)
    daily_vol = math.sqrt(var_r) if var_r >= 0 else 0.0
    annual_vol = daily_vol * math.sqrt(252)

    risk_free_daily = 0.05 / 252
    excess_returns = [r - risk_free_daily for r in returns]
    mean_excess = sum(excess_returns) / len(excess_returns)
    sharpe = round(_safe_div(mean_excess * math.sqrt(252), annual_vol), 4) if annual_vol > 0 else 0.0

    downside = [r for r in excess_returns if r < 0]
    if downside:
        downside_var = sum(r ** 2 for r in downside) / len(downside)
        downside_vol = math.sqrt(downside_var) * math.sqrt(252)
        sortino = round(_safe_div(mean_excess * math.sqrt(252), downside_vol), 4)
    else:
        sortino = round(sharpe * 1.5, 4)

    position_value = 0.0
    if positions:
        for p in positions:
            position_value += abs(_sf(p.get("market_value")))

    return {
        "var_95": var_95,
        "var_99": var_99,
        "max_drawdown": round(max_dd * 100, 4),
        "volatility_annual": round(annual_vol * 100, 4),
        "beta_vs_spy": None,
        "sharpe_ratio": sharpe,
        "sortino_ratio": sortino,
        "daily_returns_count": len(returns),
        "mean_daily_return": round(mean_r * 100, 4),
        "total_position_value": round(position_value, 2),
    }


def compute_beta(asset_bars: List[Dict], benchmark_bars: List[Dict]) -> Optional[float]:
    """
    Compute beta of asset vs benchmark from aligned daily bars.
    Both bar lists should cover the same dates for meaningful results.
    """
    asset_closes = _extract_closes(asset_bars)
    bench_closes = _extract_closes(benchmark_bars)

    min_len = min(len(asset_closes), len(bench_closes))
    if min_len < 10:
        return None

    asset_closes = asset_closes[-min_len:]
    bench_closes = bench_closes[-min_len:]

    a_ret: List[float] = []
    b_ret: List[float] = []
    for i in range(1, min_len):
        if asset_closes[i - 1] != 0 and bench_closes[i - 1] != 0:
            a_ret.append((asset_closes[i] - asset_closes[i - 1]) / asset_closes[i - 1])
            b_ret.append((bench_closes[i] - bench_closes[i - 1]) / bench_closes[i - 1])

    if len(a_ret) < 5:
        return None

    mean_a = sum(a_ret) / len(a_ret)
    mean_b = sum(b_ret) / len(b_ret)

    cov = sum((a - mean_a) * (b - mean_b) for a, b in zip(a_ret, b_ret)) / len(a_ret)
    var_b = sum((b - mean_b) ** 2 for b in b_ret) / len(b_ret)

    beta = _safe_div(cov, var_b)
    return round(beta, 4) if math.isfinite(beta) else None


# ---------------------------------------------------------------------------
# 4 & 5. Auto-pilot strategies
# ---------------------------------------------------------------------------

class AutoPilotStrategy:
    """Base class for auto-pilot trading strategies."""

    name: str = "base"
    description: str = "Base strategy"
    asset_classes: List[str] = []

    def evaluate(
        self,
        bars: List[Dict],
        technicals: Dict[str, Any],
        account: Dict[str, Any],
        positions: List[Dict],
    ) -> Dict[str, Any]:
        """
        Evaluate the strategy and return action recommendations.

        Returns:
            {
                "actions": [{"symbol": str, "side": str, "qty": int, "reason": str, "confidence": float}],
                "analysis": str,
            }
        """
        return {"actions": [], "analysis": "Base strategy — no action"}

    def risk_check(self, action: Dict[str, Any], account: Dict[str, Any], positions: List[Dict]) -> bool:
        """Pre-trade risk validation. Returns True if action passes."""
        buying_power = _sf(account.get("buying_power"))
        if buying_power <= 0:
            return False
        qty = _sf(action.get("qty"))
        if qty <= 0:
            return False
        portfolio_val = _sf(account.get("portfolio_value")) or _sf(account.get("equity")) or 100000
        estimated_cost = qty * _sf(action.get("price", 0))
        if estimated_cost > portfolio_val * 0.10:
            return False
        if action.get("side") == "buy" and estimated_cost > buying_power:
            return False
        return True


class MomentumStrategy(AutoPilotStrategy):
    """Rides trends using MACD + RSI + volume confirmation."""

    name = "momentum"
    description = "Trend-following momentum strategy using MACD crossovers, RSI confirmation, and volume analysis"
    asset_classes = ["equity", "etf", "crypto"]

    def evaluate(
        self,
        bars: List[Dict],
        technicals: Dict[str, Any],
        account: Dict[str, Any],
        positions: List[Dict],
    ) -> Dict[str, Any]:
        ind = technicals.get("indicators", {})
        if not ind:
            return {"actions": [], "analysis": "No technical data available"}

        actions: List[Dict[str, Any]] = []
        rsi = ind.get("rsi_14")
        macd_hist = ind.get("macd_histogram")
        prev_hist = ind.get("macd_prev_histogram")
        vol_ratio = ind.get("volume_ratio")
        price = ind.get("latest_close") or 0.0

        if price <= 0:
            return {"actions": [], "analysis": "No price data"}

        momentum_score = 0.0

        if macd_hist is not None and prev_hist is not None:
            if macd_hist > 0 and prev_hist <= 0:
                momentum_score += 2.0
            elif macd_hist > 0 and macd_hist > prev_hist:
                momentum_score += 1.0
            elif macd_hist < 0 and prev_hist >= 0:
                momentum_score -= 2.0
            elif macd_hist < 0 and macd_hist < prev_hist:
                momentum_score -= 1.0

        if rsi is not None:
            if 40 < rsi < 65:
                momentum_score += 0.5
            elif rsi > 75:
                momentum_score -= 1.5
            elif rsi < 25:
                momentum_score += 0.5

        if vol_ratio is not None and vol_ratio > 1.3:
            momentum_score *= 1.3

        portfolio_val = _sf(account.get("portfolio_value")) or _sf(account.get("equity")) or 100000
        conf = min(1.0, abs(momentum_score) / 4.0)

        if momentum_score >= 2.0:
            risk_frac = 0.02 * conf
            qty = max(1, int((portfolio_val * risk_frac) / price))
            actions.append({
                "side": "buy", "qty": qty, "price": price,
                "reason": f"Strong momentum (score={momentum_score:.1f}, RSI={rsi}, vol_ratio={vol_ratio})",
                "confidence": round(conf, 3),
            })
        elif momentum_score <= -2.0:
            actions.append({
                "side": "sell", "qty": 0, "price": price,
                "reason": f"Momentum reversal (score={momentum_score:.1f}, RSI={rsi})",
                "confidence": round(conf, 3),
            })

        analysis = f"Momentum score: {momentum_score:.2f} | RSI: {rsi} | MACD hist: {macd_hist} | Vol ratio: {vol_ratio}"
        return {"actions": actions, "analysis": analysis}


class MeanReversionStrategy(AutoPilotStrategy):
    """Buys oversold, sells overbought using RSI + Bollinger Bands."""

    name = "mean_reversion"
    description = "Mean reversion strategy — buys oversold conditions (RSI + BB lower), sells overbought"
    asset_classes = ["equity", "etf"]

    def evaluate(
        self,
        bars: List[Dict],
        technicals: Dict[str, Any],
        account: Dict[str, Any],
        positions: List[Dict],
    ) -> Dict[str, Any]:
        ind = technicals.get("indicators", {})
        if not ind:
            return {"actions": [], "analysis": "No technical data"}

        actions: List[Dict[str, Any]] = []
        rsi = ind.get("rsi_14")
        bbl = ind.get("bb_lower")
        bbu = ind.get("bb_upper")
        bbm = ind.get("bb_middle")
        price = ind.get("latest_close") or 0.0
        stoch_k = ind.get("stoch_k")

        if price <= 0:
            return {"actions": [], "analysis": "No price data"}

        score = 0.0

        if rsi is not None:
            if rsi < 30:
                score += 2.0
            elif rsi < 35:
                score += 1.0
            elif rsi > 70:
                score -= 2.0
            elif rsi > 65:
                score -= 1.0

        if bbl is not None and bbu is not None:
            if price <= bbl:
                score += 2.0
            elif bbm is not None and price < bbm:
                score += 0.5
            elif price >= bbu:
                score -= 2.0
            elif bbm is not None and price > bbm:
                score -= 0.5

        if stoch_k is not None:
            if stoch_k < 20:
                score += 1.0
            elif stoch_k > 80:
                score -= 1.0

        portfolio_val = _sf(account.get("portfolio_value")) or 100000
        conf = min(1.0, abs(score) / 5.0)

        if score >= 2.5:
            risk_frac = 0.02 * conf
            qty = max(1, int((portfolio_val * risk_frac) / price))
            actions.append({
                "side": "buy", "qty": qty, "price": price,
                "reason": f"Oversold reversion signal (score={score:.1f}, RSI={rsi}, near BB lower)",
                "confidence": round(conf, 3),
            })
        elif score <= -2.5:
            actions.append({
                "side": "sell", "qty": 0, "price": price,
                "reason": f"Overbought reversion signal (score={score:.1f}, RSI={rsi}, near BB upper)",
                "confidence": round(conf, 3),
            })

        return {
            "actions": actions,
            "analysis": f"Mean reversion score: {score:.2f} | RSI: {rsi} | BB range: [{bbl}, {bbu}] | Stoch %K: {stoch_k}",
        }


class BreakoutStrategy(AutoPilotStrategy):
    """Trades Bollinger Band breakouts with volume confirmation."""

    name = "breakout"
    description = "Breakout strategy — trades BB breakouts confirmed by volume surge"
    asset_classes = ["equity", "etf", "crypto"]

    def evaluate(
        self,
        bars: List[Dict],
        technicals: Dict[str, Any],
        account: Dict[str, Any],
        positions: List[Dict],
    ) -> Dict[str, Any]:
        ind = technicals.get("indicators", {})
        if not ind:
            return {"actions": [], "analysis": "No technical data"}

        actions: List[Dict[str, Any]] = []
        price = ind.get("latest_close") or 0.0
        bbu = ind.get("bb_upper")
        bbl = ind.get("bb_lower")
        bb_width = ind.get("bb_width")
        vol_ratio = ind.get("volume_ratio")
        macd_hist = ind.get("macd_histogram")

        if price <= 0 or bbu is None or bbl is None:
            return {"actions": [], "analysis": "Insufficient data for breakout analysis"}

        volume_confirmed = vol_ratio is not None and vol_ratio > 1.5
        was_squeezed = bb_width is not None and bb_width < 0.06

        portfolio_val = _sf(account.get("portfolio_value")) or 100000

        if price >= bbu and volume_confirmed:
            conf = 0.7 if was_squeezed else 0.5
            if macd_hist is not None and macd_hist > 0:
                conf += 0.15
            conf = min(1.0, conf)
            risk_frac = 0.015 * conf
            qty = max(1, int((portfolio_val * risk_frac) / price))
            actions.append({
                "side": "buy", "qty": qty, "price": price,
                "reason": f"Upside breakout above BB upper ({bbu:.2f}) with {vol_ratio:.2f}x volume",
                "confidence": round(conf, 3),
            })
        elif price <= bbl and volume_confirmed:
            conf = 0.6 if was_squeezed else 0.4
            actions.append({
                "side": "sell", "qty": 0, "price": price,
                "reason": f"Downside breakout below BB lower ({bbl:.2f}) with {vol_ratio:.2f}x volume",
                "confidence": round(conf, 3),
            })

        return {
            "actions": actions,
            "analysis": f"Breakout check | Price: {price} | BB: [{bbl}, {bbu}] | Width: {bb_width} | Vol ratio: {vol_ratio}",
        }


class MacroSentimentStrategy(AutoPilotStrategy):
    """Commodity/energy trend following with larger timeframes."""

    name = "macro_sentiment"
    description = "Macro trend-following for commodities/energy (USO, UNG, GLD) using SMA crossovers and momentum"
    asset_classes = ["commodity", "etf", "energy"]

    def evaluate(
        self,
        bars: List[Dict],
        technicals: Dict[str, Any],
        account: Dict[str, Any],
        positions: List[Dict],
    ) -> Dict[str, Any]:
        ind = technicals.get("indicators", {})
        if not ind:
            return {"actions": [], "analysis": "No technical data"}

        actions: List[Dict[str, Any]] = []
        price = ind.get("latest_close") or 0.0
        sma20 = ind.get("sma_20")
        sma50 = ind.get("sma_50")
        rsi = ind.get("rsi_14")
        atr = ind.get("atr_14")

        if price <= 0:
            return {"actions": [], "analysis": "No price data"}

        trend_score = 0.0

        if sma20 is not None and sma50 is not None:
            if sma20 > sma50 and price > sma20:
                trend_score += 2.0
            elif sma20 > sma50:
                trend_score += 1.0
            elif sma20 < sma50 and price < sma20:
                trend_score -= 2.0
            elif sma20 < sma50:
                trend_score -= 1.0

        if rsi is not None:
            if 45 < rsi < 70:
                trend_score += 0.5
            elif rsi > 75:
                trend_score -= 1.0
            elif rsi < 30:
                trend_score += 0.5

        portfolio_val = _sf(account.get("portfolio_value")) or 100000
        conf = min(1.0, abs(trend_score) / 3.0)

        if trend_score >= 2.0:
            risk_frac = 0.015 * conf
            qty = max(1, int((portfolio_val * risk_frac) / price))
            actions.append({
                "side": "buy", "qty": qty, "price": price,
                "reason": f"Macro uptrend (SMA20={sma20}, SMA50={sma50}, RSI={rsi})",
                "confidence": round(conf, 3),
            })
        elif trend_score <= -2.0:
            actions.append({
                "side": "sell", "qty": 0, "price": price,
                "reason": f"Macro downtrend (SMA20={sma20}, SMA50={sma50}, RSI={rsi})",
                "confidence": round(conf, 3),
            })

        return {
            "actions": actions,
            "analysis": f"Macro trend score: {trend_score:.2f} | SMA20: {sma20} | SMA50: {sma50} | ATR: {atr}",
        }


class CryptoMomentumStrategy(AutoPilotStrategy):
    """Crypto-specific momentum with higher volatility thresholds."""

    name = "crypto_momentum"
    description = "Crypto momentum strategy with wider RSI thresholds and higher volatility tolerance"
    asset_classes = ["crypto"]

    def evaluate(
        self,
        bars: List[Dict],
        technicals: Dict[str, Any],
        account: Dict[str, Any],
        positions: List[Dict],
    ) -> Dict[str, Any]:
        ind = technicals.get("indicators", {})
        if not ind:
            return {"actions": [], "analysis": "No technical data"}

        actions: List[Dict[str, Any]] = []
        price = ind.get("latest_close") or 0.0
        rsi = ind.get("rsi_14")
        macd_hist = ind.get("macd_histogram")
        prev_hist = ind.get("macd_prev_histogram")
        vol_ratio = ind.get("volume_ratio")
        ema12 = ind.get("ema_12")
        ema26 = ind.get("ema_26")

        if price <= 0:
            return {"actions": [], "analysis": "No price data"}

        score = 0.0

        if rsi is not None:
            if rsi < 25:
                score += 2.0
            elif rsi > 80:
                score -= 2.0
            elif rsi < 40:
                score += 0.5
            elif rsi > 65:
                score -= 0.5

        if macd_hist is not None and prev_hist is not None:
            if macd_hist > 0 and prev_hist <= 0:
                score += 2.0
            elif macd_hist > 0:
                score += 0.5
            elif macd_hist < 0 and prev_hist >= 0:
                score -= 2.0
            elif macd_hist < 0:
                score -= 0.5

        if ema12 is not None and ema26 is not None:
            if ema12 > ema26:
                score += 1.0
            else:
                score -= 1.0

        if vol_ratio is not None and vol_ratio > 2.0:
            score *= 1.2

        portfolio_val = _sf(account.get("portfolio_value")) or 100000
        conf = min(1.0, abs(score) / 5.0)
        crypto_alloc = 0.01

        if score >= 2.5:
            risk_frac = crypto_alloc * conf
            qty = max(1, int((portfolio_val * risk_frac) / price)) if price < portfolio_val else 1
            actions.append({
                "side": "buy", "qty": qty, "price": price,
                "reason": f"Crypto momentum bullish (score={score:.1f}, RSI={rsi})",
                "confidence": round(conf, 3),
            })
        elif score <= -2.5:
            actions.append({
                "side": "sell", "qty": 0, "price": price,
                "reason": f"Crypto momentum bearish (score={score:.1f}, RSI={rsi})",
                "confidence": round(conf, 3),
            })

        return {
            "actions": actions,
            "analysis": f"Crypto momentum score: {score:.2f} | RSI: {rsi} | MACD hist: {macd_hist} | Vol ratio: {vol_ratio}",
        }


class QuantumScalpStrategy(AutoPilotStrategy):
    """Short-timeframe mean reversion with tight risk controls."""

    name = "quantum_scalp"
    description = "Short-timeframe scalping strategy — tight mean reversion with strict risk limits"
    asset_classes = ["equity", "etf"]

    def evaluate(
        self,
        bars: List[Dict],
        technicals: Dict[str, Any],
        account: Dict[str, Any],
        positions: List[Dict],
    ) -> Dict[str, Any]:
        ind = technicals.get("indicators", {})
        if not ind:
            return {"actions": [], "analysis": "No technical data"}

        actions: List[Dict[str, Any]] = []
        price = ind.get("latest_close") or 0.0
        rsi = ind.get("rsi_14")
        bbl = ind.get("bb_lower")
        bbu = ind.get("bb_upper")
        bbm = ind.get("bb_middle")
        atr = ind.get("atr_14")
        stoch_k = ind.get("stoch_k")
        stoch_d = ind.get("stoch_d")

        if price <= 0 or bbm is None:
            return {"actions": [], "analysis": "Insufficient data for scalp"}

        deviation = _safe_div(price - bbm, bbm) * 100 if bbm > 0 else 0.0

        score = 0.0

        if deviation < -1.5:
            score += 2.0
        elif deviation < -0.8:
            score += 1.0
        elif deviation > 1.5:
            score -= 2.0
        elif deviation > 0.8:
            score -= 1.0

        if rsi is not None:
            if rsi < 30:
                score += 1.5
            elif rsi < 40:
                score += 0.5
            elif rsi > 70:
                score -= 1.5
            elif rsi > 60:
                score -= 0.5

        if stoch_k is not None and stoch_d is not None:
            if stoch_k < 20:
                score += 1.0
            elif stoch_k > 80:
                score -= 1.0

        portfolio_val = _sf(account.get("portfolio_value")) or 100000
        conf = min(1.0, abs(score) / 4.0)
        risk_frac = 0.005 * conf

        if score >= 2.0:
            qty = max(1, int((portfolio_val * risk_frac) / price))
            stop_dist = atr * 0.5 if atr and atr > 0 else price * 0.005
            actions.append({
                "side": "buy", "qty": qty, "price": price,
                "reason": f"Scalp buy — deviation {deviation:.2f}% from mean, RSI={rsi}",
                "confidence": round(conf, 3),
                "stop_loss": round(price - stop_dist, 2),
                "take_profit": round(bbm, 2),
            })
        elif score <= -2.0:
            stop_dist = atr * 0.5 if atr and atr > 0 else price * 0.005
            actions.append({
                "side": "sell", "qty": 0, "price": price,
                "reason": f"Scalp sell — deviation {deviation:.2f}% from mean, RSI={rsi}",
                "confidence": round(conf, 3),
                "stop_loss": round(price + stop_dist, 2),
                "take_profit": round(bbm, 2),
            })

        return {
            "actions": actions,
            "analysis": f"Scalp score: {score:.2f} | Deviation: {deviation:.2f}% | RSI: {rsi} | ATR: {atr}",
        }


# Strategy registry
STRATEGY_REGISTRY: Dict[str, type] = {
    "momentum": MomentumStrategy,
    "mean_reversion": MeanReversionStrategy,
    "breakout": BreakoutStrategy,
    "macro_sentiment": MacroSentimentStrategy,
    "crypto_momentum": CryptoMomentumStrategy,
    "quantum_scalp": QuantumScalpStrategy,
}


# ---------------------------------------------------------------------------
# 6. AutoPilotEngine — bot management
# ---------------------------------------------------------------------------

class AutoPilotEngine:
    """Manages auto-pilot trading bots backed by strategy subclasses."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._bots: Dict[str, Dict[str, Any]] = {}

    def create_bot(
        self,
        strategy_name: str,
        symbols: List[str],
        config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Create a new auto-pilot bot."""
        if strategy_name not in STRATEGY_REGISTRY:
            return {"error": f"Unknown strategy: {strategy_name}. Available: {list(STRATEGY_REGISTRY.keys())}"}

        cfg = config or {}
        bot_id = f"BOT-{uuid.uuid4().hex[:8].upper()}"

        bot: Dict[str, Any] = {
            "id": bot_id,
            "strategy_name": strategy_name,
            "symbols": symbols,
            "config": {
                "max_position_size": cfg.get("max_position_size", 0.05),
                "max_daily_loss": cfg.get("max_daily_loss", 0.02),
                "max_open_positions": cfg.get("max_open_positions", 5),
                "risk_per_trade": cfg.get("risk_per_trade", 0.02),
            },
            "status": "active",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "trades": [],
            "daily_pnl": 0.0,
            "total_pnl": 0.0,
            "win_count": 0,
            "loss_count": 0,
            "trade_count": 0,
        }

        with self._lock:
            self._bots[bot_id] = bot

        return {
            "id": bot_id,
            "strategy": strategy_name,
            "symbols": symbols,
            "status": "active",
            "config": bot["config"],
        }

    def get_bots(self) -> List[Dict[str, Any]]:
        """List all bots with status."""
        with self._lock:
            return [
                {
                    "id": b["id"],
                    "strategy": b["strategy_name"],
                    "symbols": b["symbols"],
                    "status": b["status"],
                    "trade_count": b["trade_count"],
                    "total_pnl": round(b["total_pnl"], 2),
                    "daily_pnl": round(b["daily_pnl"], 2),
                    "win_rate": round(
                        _safe_div(b["win_count"], b["win_count"] + b["loss_count"]) * 100, 1
                    ),
                    "created_at": b["created_at"],
                }
                for b in self._bots.values()
            ]

    def evaluate_bot(self, bot_id: str, bars_by_symbol: Optional[Dict[str, List[Dict]]] = None) -> Dict[str, Any]:
        """
        Run strategy evaluation for a bot.

        Parameters:
            bot_id: the bot identifier.
            bars_by_symbol: pre-fetched bars keyed by symbol.
                            If None, caller must supply them from the trading platform.

        Returns dict with recommended actions per symbol.
        """
        with self._lock:
            bot = self._bots.get(bot_id)
            if not bot:
                return {"error": f"Bot {bot_id} not found"}
            if bot["status"] != "active":
                return {"error": f"Bot {bot_id} is {bot['status']}"}
            strategy_name = bot["strategy_name"]
            symbols = list(bot["symbols"])
            config = dict(bot["config"])

        strategy = STRATEGY_REGISTRY[strategy_name]()
        bars_map = bars_by_symbol or {}

        results: Dict[str, Any] = {"bot_id": bot_id, "strategy": strategy_name, "signals": {}}

        for sym in symbols:
            sym_bars = bars_map.get(sym, [])
            if not sym_bars:
                results["signals"][sym] = {"actions": [], "analysis": "No bars available"}
                continue

            techs = compute_technicals(sym_bars)
            evaluation = strategy.evaluate(sym_bars, techs, {"portfolio_value": 100000}, [])

            for action in evaluation.get("actions", []):
                action["symbol"] = sym

            results["signals"][sym] = evaluation

        return results

    def execute_bot_trades(
        self,
        bot_id: str,
        trading_platform: Any,
        bars_by_symbol: Optional[Dict[str, List[Dict]]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Execute recommended trades for a bot via the trading platform's submit_order.
        Returns list of order results.
        """
        with self._lock:
            bot = self._bots.get(bot_id)
            if not bot:
                return [{"error": f"Bot {bot_id} not found"}]
            if bot["status"] != "active":
                return [{"error": f"Bot {bot_id} is {bot['status']}"}]
            config = dict(bot["config"])

        eval_result = self.evaluate_bot(bot_id, bars_by_symbol)
        if "error" in eval_result:
            return [{"error": eval_result["error"]}]

        account = {}
        positions: List[Dict] = []
        try:
            account = trading_platform.get_account()
            positions = trading_platform.get_positions()
        except Exception:
            pass

        portfolio_val = _sf(account.get("portfolio_value")) or _sf(account.get("equity")) or 100000
        max_pos_size = config.get("max_position_size", 0.05)
        max_daily_loss = config.get("max_daily_loss", 0.02)
        max_open = config.get("max_open_positions", 5)

        with self._lock:
            if bot["daily_pnl"] < -(portfolio_val * max_daily_loss):
                return [{"error": "Daily loss limit reached", "daily_pnl": bot["daily_pnl"]}]

        open_count = len(positions)
        executed: List[Dict[str, Any]] = []

        for sym, sig_data in eval_result.get("signals", {}).items():
            for action in sig_data.get("actions", []):
                side = action.get("side")
                qty = int(action.get("qty", 0))
                price = _sf(action.get("price"))

                if side == "sell" and qty == 0:
                    held = [p for p in positions if p.get("symbol") == sym]
                    if held:
                        qty = abs(int(_sf(held[0].get("qty"))))
                    else:
                        continue

                if qty <= 0:
                    continue

                if side == "buy":
                    estimated_cost = qty * price
                    if estimated_cost > portfolio_val * max_pos_size:
                        qty = max(1, int((portfolio_val * max_pos_size) / price))

                    if open_count >= max_open:
                        continue

                strategy_inst = STRATEGY_REGISTRY[bot["strategy_name"]]()
                action_with_price = {**action, "price": price, "qty": qty}
                if not strategy_inst.risk_check(action_with_price, account, positions):
                    continue

                try:
                    order_result = trading_platform.submit_order(
                        symbol=sym,
                        side=side,
                        qty=qty,
                        order_type="market",
                        time_in_force="day",
                    )
                except Exception as e:
                    order_result = {"error": str(e)}

                trade_record = {
                    "bot_id": bot_id,
                    "symbol": sym,
                    "side": side,
                    "qty": qty,
                    "price": price,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "order_result": order_result,
                    "reason": action.get("reason", ""),
                    "confidence": action.get("confidence", 0.0),
                }

                with self._lock:
                    self._bots[bot_id]["trades"].append(trade_record)
                    self._bots[bot_id]["trade_count"] += 1
                    self._bots[bot_id]["updated_at"] = datetime.now(timezone.utc).isoformat()

                if side == "buy":
                    open_count += 1

                executed.append(trade_record)

        return executed

    def record_trade_exit(self, bot_id: str, symbol: str, exit_price: float, qty: int) -> Dict[str, Any]:
        """Record a trade exit and compute P&L."""
        with self._lock:
            bot = self._bots.get(bot_id)
            if not bot:
                return {"error": f"Bot {bot_id} not found"}

            matching_entries = [
                t for t in bot["trades"]
                if t.get("symbol") == symbol and t.get("side") == "buy" and not t.get("closed")
            ]
            if not matching_entries:
                return {"error": f"No open entry trade found for {symbol}"}

            entry = matching_entries[-1]
            entry_price = _sf(entry.get("price"))
            pnl = (exit_price - entry_price) * qty

            entry["closed"] = True
            entry["exit_price"] = exit_price
            entry["pnl"] = round(pnl, 2)
            entry["exit_timestamp"] = datetime.now(timezone.utc).isoformat()

            bot["total_pnl"] += pnl
            bot["daily_pnl"] += pnl
            if pnl >= 0:
                bot["win_count"] += 1
            else:
                bot["loss_count"] += 1
            bot["updated_at"] = datetime.now(timezone.utc).isoformat()

            return {"symbol": symbol, "pnl": round(pnl, 2), "total_pnl": round(bot["total_pnl"], 2)}

    def get_bot_performance(self, bot_id: str) -> Dict[str, Any]:
        """Return P&L, win rate, and trade history summary."""
        with self._lock:
            bot = self._bots.get(bot_id)
            if not bot:
                return {"error": f"Bot {bot_id} not found"}

            total_trades = bot["win_count"] + bot["loss_count"]
            win_rate = round(_safe_div(bot["win_count"], total_trades) * 100, 1) if total_trades > 0 else 0.0

            closed_trades = [t for t in bot["trades"] if t.get("closed")]
            pnl_values = [_sf(t.get("pnl")) for t in closed_trades]
            avg_pnl = round(sum(pnl_values) / len(pnl_values), 2) if pnl_values else 0.0

            best_trade = max(pnl_values) if pnl_values else 0.0
            worst_trade = min(pnl_values) if pnl_values else 0.0

            return {
                "bot_id": bot_id,
                "strategy": bot["strategy_name"],
                "status": bot["status"],
                "total_pnl": round(bot["total_pnl"], 2),
                "daily_pnl": round(bot["daily_pnl"], 2),
                "trade_count": bot["trade_count"],
                "closed_trades": len(closed_trades),
                "open_trades": bot["trade_count"] - len(closed_trades),
                "win_count": bot["win_count"],
                "loss_count": bot["loss_count"],
                "win_rate": win_rate,
                "avg_pnl_per_trade": avg_pnl,
                "best_trade": round(best_trade, 2),
                "worst_trade": round(worst_trade, 2),
                "recent_trades": bot["trades"][-10:],
            }

    def pause_bot(self, bot_id: str) -> Dict[str, Any]:
        with self._lock:
            bot = self._bots.get(bot_id)
            if not bot:
                return {"error": f"Bot {bot_id} not found"}
            bot["status"] = "paused"
            bot["updated_at"] = datetime.now(timezone.utc).isoformat()
            return {"id": bot_id, "status": "paused"}

    def resume_bot(self, bot_id: str) -> Dict[str, Any]:
        with self._lock:
            bot = self._bots.get(bot_id)
            if not bot:
                return {"error": f"Bot {bot_id} not found"}
            bot["status"] = "active"
            bot["updated_at"] = datetime.now(timezone.utc).isoformat()
            return {"id": bot_id, "status": "active"}

    def delete_bot(self, bot_id: str) -> Dict[str, Any]:
        with self._lock:
            bot = self._bots.pop(bot_id, None)
            if not bot:
                return {"error": f"Bot {bot_id} not found"}
            return {"id": bot_id, "status": "deleted", "final_pnl": round(bot["total_pnl"], 2)}

    def reset_daily_pnl(self) -> None:
        """Reset daily P&L for all bots (call at start of trading day)."""
        with self._lock:
            for bot in self._bots.values():
                bot["daily_pnl"] = 0.0


# ---------------------------------------------------------------------------
# 7. LiveScreener
# ---------------------------------------------------------------------------

class LiveScreener:
    """Scans a universe of symbols using live Alpaca data for trading signals."""

    SECTOR_ETFS: Dict[str, str] = {
        "XLK": "Technology",
        "XLF": "Financials",
        "XLE": "Energy",
        "XLV": "Healthcare",
        "XLI": "Industrials",
        "XLP": "Consumer Staples",
        "XLY": "Consumer Discretionary",
        "XLU": "Utilities",
        "XLRE": "Real Estate",
        "XLC": "Communication",
    }

    BROAD_UNIVERSE: List[str] = [
        s for sector, syms in UNIVERSE.items() if sector != "crypto" for s in syms
    ]

    def scan_universe(
        self,
        trading_platform: Any,
        symbols: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Fetch snapshots for all symbols and compute quick signals.
        Returns a sorted list of scanned results.
        """
        targets = symbols or self.BROAD_UNIVERSE
        results: List[Dict[str, Any]] = []

        for sym in targets:
            try:
                snap = trading_platform.get_snapshot(sym)
                if not snap:
                    continue

                price = _sf(snap.get("latest_trade", {}).get("price")
                            or snap.get("price")
                            or snap.get("close"))
                prev_close = _sf(snap.get("prev_daily_bar", {}).get("close")
                                 or snap.get("prev_close"))
                change_pct = _safe_div(price - prev_close, prev_close) * 100 if prev_close > 0 else 0.0
                volume = _sf(snap.get("daily_bar", {}).get("volume")
                             or snap.get("volume"))

                bars = trading_platform.get_bars(sym, timeframe="1Day", limit=50)
                techs = compute_technicals(bars) if bars else {}
                ind = techs.get("indicators", {})

                quick_signal = "NEUTRAL"
                rsi = ind.get("rsi_14")
                macd_hist = ind.get("macd_histogram")

                if rsi is not None:
                    if rsi < 30:
                        quick_signal = "OVERSOLD"
                    elif rsi > 70:
                        quick_signal = "OVERBOUGHT"

                if macd_hist is not None:
                    if macd_hist > 0 and quick_signal == "NEUTRAL":
                        quick_signal = "BULLISH"
                    elif macd_hist < 0 and quick_signal == "NEUTRAL":
                        quick_signal = "BEARISH"

                results.append({
                    "symbol": sym,
                    "price": round(price, 2),
                    "change_pct": round(change_pct, 2),
                    "volume": volume,
                    "rsi": round(rsi, 2) if rsi is not None else None,
                    "macd_histogram": round(macd_hist, 4) if macd_hist is not None else None,
                    "signal": quick_signal,
                    "bb_position": _bb_position(ind, price),
                })
            except Exception:
                continue

        results.sort(key=lambda x: abs(x.get("change_pct", 0)), reverse=True)
        return results

    def get_sector_heatmap(self, trading_platform: Any) -> Dict[str, Any]:
        """Sector ETF performance heatmap from live data."""
        sectors: Dict[str, Any] = {}
        for etf, sector_name in self.SECTOR_ETFS.items():
            try:
                snap = trading_platform.get_snapshot(etf)
                if not snap:
                    sectors[sector_name] = {"symbol": etf, "price": None, "change_pct": None}
                    continue

                price = _sf(snap.get("latest_trade", {}).get("price")
                            or snap.get("price")
                            or snap.get("close"))
                prev_close = _sf(snap.get("prev_daily_bar", {}).get("close")
                                 or snap.get("prev_close"))
                change_pct = _safe_div(price - prev_close, prev_close) * 100 if prev_close > 0 else 0.0

                sectors[sector_name] = {
                    "symbol": etf,
                    "price": round(price, 2),
                    "change_pct": round(change_pct, 2),
                    "status": "up" if change_pct > 0 else ("down" if change_pct < 0 else "flat"),
                }
            except Exception:
                sectors[sector_name] = {"symbol": etf, "price": None, "change_pct": None}

        sorted_sectors = dict(sorted(sectors.items(), key=lambda x: _sf(x[1].get("change_pct")), reverse=True))
        best = max(sectors.items(), key=lambda x: _sf(x[1].get("change_pct")), default=(None, {}))
        worst = min(sectors.items(), key=lambda x: _sf(x[1].get("change_pct")), default=(None, {}))

        return {
            "sectors": sorted_sectors,
            "best_sector": best[0],
            "worst_sector": worst[0],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def get_top_movers(
        self,
        trading_platform: Any,
        limit: int = 20,
    ) -> Dict[str, Any]:
        """Biggest gainers and losers from the broad equity universe."""
        scanned = self.scan_universe(trading_platform, self.BROAD_UNIVERSE)
        if not scanned:
            return {"gainers": [], "losers": [], "timestamp": datetime.now(timezone.utc).isoformat()}

        by_change = sorted(scanned, key=lambda x: x.get("change_pct", 0), reverse=True)
        half = max(1, limit // 2)

        return {
            "gainers": by_change[:half],
            "losers": list(reversed(by_change[-half:])),
            "total_scanned": len(scanned),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


def _bb_position(ind: Dict[str, Any], price: float) -> Optional[str]:
    """Describe price relative to Bollinger Bands."""
    bbu = ind.get("bb_upper")
    bbl = ind.get("bb_lower")
    bbm = ind.get("bb_middle")
    if bbu is None or bbl is None or price <= 0:
        return None
    if price >= bbu:
        return "above_upper"
    if price <= bbl:
        return "below_lower"
    if bbm is not None:
        return "above_mid" if price >= bbm else "below_mid"
    return "in_band"
