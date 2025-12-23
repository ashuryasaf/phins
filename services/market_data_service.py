from __future__ import annotations

import csv
import io
import time
from dataclasses import dataclass
from typing import Dict, Any, List, Optional

import requests


@dataclass
class CachedValue:
    value: Any
    expires_at: float


class MarketDataService:
    """
    Minimal market data service:
    - Crypto spot prices via CoinGecko (no API key, rate limited)
    - Index quotes via Stooq CSV (no API key)
    """

    # Common coin symbol → CoinGecko id mapping
    COINGECKO_IDS: Dict[str, str] = {
        "BTC": "bitcoin",
        "ETH": "ethereum",
        "USDT": "tether",
        "USDC": "usd-coin",
        "SOL": "solana",
        "BNB": "binancecoin",
        "XRP": "ripple",
        "ADA": "cardano",
        "DOGE": "dogecoin",
    }

    def __init__(self, cache_ttl_seconds: int = 30, timeout_seconds: int = 8):
        self._ttl = cache_ttl_seconds
        self._timeout = timeout_seconds
        self._cache: Dict[str, CachedValue] = {}

    def _get_cached(self, key: str) -> Any:
        now = time.time()
        hit = self._cache.get(key)
        if hit and now < hit.expires_at:
            return hit.value
        return None

    def _set_cached(self, key: str, value: Any) -> None:
        self._cache[key] = CachedValue(value=value, expires_at=time.time() + self._ttl)

    def get_crypto_prices_usd(self, symbols: List[str]) -> Dict[str, Any]:
        symbols_norm = [s.strip().upper() for s in symbols if s and s.strip()]
        symbols_norm = list(dict.fromkeys(symbols_norm))  # unique preserve order
        cache_key = f"crypto:{','.join(symbols_norm)}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        ids = []
        unknown = []
        for s in symbols_norm:
            cid = self.COINGECKO_IDS.get(s)
            if not cid:
                unknown.append(s)
            else:
                ids.append(cid)

        if not ids:
            result = {"source": "coingecko", "prices": {}, "unknown": unknown}
            self._set_cached(cache_key, result)
            return result

        url = "https://api.coingecko.com/api/v3/simple/price"
        params = {"ids": ",".join(ids), "vs_currencies": "usd"}
        resp = requests.get(url, params=params, timeout=self._timeout)
        resp.raise_for_status()
        data = resp.json()

        prices = {}
        for sym, cid in self.COINGECKO_IDS.items():
            if cid in ids and cid in data and "usd" in data[cid]:
                prices[sym] = float(data[cid]["usd"])

        result = {"source": "coingecko", "prices": prices, "unknown": unknown}
        self._set_cached(cache_key, result)
        return result

    def get_index_quotes(self, symbols: List[str]) -> Dict[str, Any]:
        """
        Stooq supports many tickers. Common ones:
        - ^spx  (S&P 500)
        - ^ndq  (NASDAQ 100)
        - ^dji  (Dow Jones)
        """
        symbols_norm = [s.strip().lower() for s in symbols if s and s.strip()]
        symbols_norm = list(dict.fromkeys(symbols_norm))
        cache_key = f"index:{','.join(symbols_norm)}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        quotes: Dict[str, Any] = {}
        for s in symbols_norm:
            url = "https://stooq.com/q/l/"
            params = {"s": s, "f": "sd2t2ohlcv", "h": "", "e": "csv"}
            resp = requests.get(url, params=params, timeout=self._timeout)
            resp.raise_for_status()
            text = resp.text.strip()
            reader = csv.DictReader(io.StringIO(text))
            row = next(reader, None)
            if not row or row.get("Close") in (None, "", "N/A"):
                quotes[s] = {"status": "unavailable"}
                continue
            quotes[s] = {
                "status": "ok",
                "date": row.get("Date"),
                "time": row.get("Time"),
                "open": row.get("Open"),
                "high": row.get("High"),
                "low": row.get("Low"),
                "close": row.get("Close"),
                "volume": row.get("Volume"),
            }

        result = {"source": "stooq", "quotes": quotes}
        self._set_cached(cache_key, result)
        return result

