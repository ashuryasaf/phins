"""
Market data service (crypto + capital markets indexes) for PHINS PHI investments.

Goals:
- Provide a simple, dependency-free connector that can call public endpoints when available.
- Provide a fluent API usable from code and exposed via web endpoints.
- Provide safe fallbacks when outbound network access is unavailable.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Literal, Optional, Sequence, Tuple
import json
import time
import urllib.request
import urllib.parse
import os


MarketKind = Literal["crypto", "index", "fx"]
MarketSource = Literal["bloomberg", "live", "fallback"]


class MarketDataError(RuntimeError):
    pass


def _http_get_json(url: str, timeout_seconds: int = 6) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": "phins.ai/market-data"})
    with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
        raw = resp.read().decode("utf-8", errors="ignore")
        return json.loads(raw)


def _http_get_text(url: str, timeout_seconds: int = 6) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "phins.ai/market-data"})
    with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
        return resp.read().decode("utf-8", errors="ignore")


@dataclass(frozen=True)
class MarketQuote:
    symbol: str
    name: str
    kind: MarketKind
    currency: str
    price: float
    change_24h: float
    updated_at: str
    source: MarketSource = "fallback"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "name": self.name,
            "kind": self.kind,
            "currency": self.currency,
            "price": self.price,
            "change_24h": self.change_24h,
            "updated_at": self.updated_at,
            "source": self.source,
        }


class MarketDataClient:
    """
    Fluent market data client.

    Example:
        client = MarketDataClient().crypto(["BTC", "ETH"]).vs("USD").fetch()
    """

    def __init__(self):
        self._kind: MarketKind = "crypto"
        self._symbols: List[str] = []
        self._vs_currency: str = "USD"
        self._ttl_seconds: int = 60

    def crypto(self, symbols: Sequence[str]) -> "MarketDataClient":
        self._kind = "crypto"
        self._symbols = [str(s).upper() for s in symbols if str(s).strip()]
        return self

    def indexes(self, symbols: Sequence[str]) -> "MarketDataClient":
        self._kind = "index"
        self._symbols = [str(s).upper() for s in symbols if str(s).strip()]
        return self

    def fx(self, base: str, quote: str) -> "MarketDataClient":
        self._kind = "fx"
        self._symbols = [f"{str(base).upper()}/{str(quote).upper()}"]
        self._vs_currency = str(quote).upper()
        return self

    def vs(self, currency: str) -> "MarketDataClient":
        self._vs_currency = str(currency).upper()
        return self

    def cache_ttl(self, seconds: int) -> "MarketDataClient":
        self._ttl_seconds = max(5, int(seconds))
        return self

    def fetch(self) -> Dict[str, Any]:
        if not self._symbols:
            return {"items": [], "ts": datetime.utcnow().isoformat()}
        svc = MarketDataService(ttl_seconds=self._ttl_seconds)
        if self._kind == "crypto":
            quotes = svc.get_crypto_quotes(self._symbols, vs_currency=self._vs_currency)
        elif self._kind == "index":
            quotes = svc.get_index_quotes(self._symbols, currency=self._vs_currency)
        else:
            base, quote = self._symbols[0].split("/", 1)
            quotes = [svc.get_fx_quote(base, quote)]
        return {"items": [q.to_dict() for q in quotes], "ts": datetime.utcnow().isoformat()}


class MarketDataService:
    """
    Market-data service with in-memory cache.
    """

    def __init__(self, ttl_seconds: int = 60):
        self.ttl_seconds = max(10, int(ttl_seconds))
        self._cache: Dict[str, Tuple[float, Any]] = {}

    def _cache_get(self, key: str) -> Optional[Any]:
        now = time.time()
        hit = self._cache.get(key)
        if not hit:
            return None
        expires_at, payload = hit
        if now > expires_at:
            self._cache.pop(key, None)
            return None
        return payload

    def _cache_set(self, key: str, payload: Any) -> Any:
        self._cache[key] = (time.time() + self.ttl_seconds, payload)
        return payload

    # -----------------------------
    # Crypto
    # -----------------------------

    def get_crypto_quotes(self, symbols: Sequence[str], *, vs_currency: str = "USD") -> List[MarketQuote]:
        symbols = [str(s).upper() for s in symbols if str(s).strip()]
        vs_currency = str(vs_currency).upper()
        key = f"crypto:{vs_currency}:{','.join(symbols)}"
        cached = self._cache_get(key)
        if cached is not None:
            return cached

        # Try Bloomberg first (optional; requires credentials and a compatible endpoint).
        # This is intentionally adapter-based: Bloomberg's official offerings require licensing.
        bloomberg_base = (os.environ.get("BLOOMBERG_API_BASE_URL") or "").strip()  # e.g. https://<your-bloomberg-gateway>
        bloomberg_key = (os.environ.get("BLOOMBERG_API_KEY") or "").strip()
        if bloomberg_base and bloomberg_key:
            try:
                url = (
                    bloomberg_base.rstrip("/")
                    + "/quotes?"
                    + urllib.parse.urlencode(
                        {
                            "provider": "bloomberg",
                            "type": "crypto",
                            "symbols": ",".join(symbols),
                            "currency": vs_currency,
                            "api_key": bloomberg_key,
                        }
                    )
                )
                data = _http_get_json(url)
                items = data.get("items") if isinstance(data, dict) else None
                if isinstance(items, list) and items:
                    now = datetime.utcnow().isoformat()
                    out: List[MarketQuote] = []
                    for it in items:
                        if not isinstance(it, dict):
                            continue
                        sym = str(it.get("symbol") or "").upper()
                        if not sym:
                            continue
                        out.append(
                            MarketQuote(
                                symbol=sym,
                                name=str(it.get("name") or sym),
                                kind="crypto",
                                currency=str(it.get("currency") or vs_currency).upper(),
                                price=round(float(it.get("price") or 0.0), 4),
                                change_24h=round(float(it.get("change_24h") or 0.0), 4),
                                updated_at=str(it.get("updated_at") or now),
                                source="bloomberg",
                            )
                        )
                    if out:
                        return self._cache_set(key, out)
            except Exception:
                pass

        # Try CoinGecko (no API key)
        # Mapping symbol -> id is not perfect; handle common assets.
        symbol_to_id = {
            "BTC": "bitcoin",
            "ETH": "ethereum",
            "USDT": "tether",
            "SOL": "solana",
            "BNB": "binancecoin",
            "XRP": "ripple",
        }
        ids = [symbol_to_id.get(s, "") for s in symbols]
        ids = [i for i in ids if i]

        try:
            if ids:
                url = (
                    "https://api.coingecko.com/api/v3/simple/price?"
                    + urllib.parse.urlencode(
                        {
                            "ids": ",".join(ids),
                            "vs_currencies": vs_currency.lower(),
                            "include_24hr_change": "true",
                        }
                    )
                )
                data = _http_get_json(url)
                out: List[MarketQuote] = []
                now = datetime.utcnow().isoformat()
                for sym in symbols:
                    cid = symbol_to_id.get(sym)
                    if not cid or cid not in data:
                        continue
                    price = float(data[cid].get(vs_currency.lower(), 0.0))
                    ch = float(data[cid].get(f"{vs_currency.lower()}_24h_change", 0.0))
                    out.append(
                        MarketQuote(
                            symbol=sym,
                            name=sym,
                            kind="crypto",
                            currency=vs_currency,
                            price=round(price, 4),
                            change_24h=round(ch, 4),
                            updated_at=now,
                            source="live",
                        )
                    )
                if out:
                    return self._cache_set(key, out)
        except Exception:
            # fall back below
            pass

        # Fallback deterministic synthetic quotes
        now = datetime.utcnow().isoformat()
        fallback_prices = {
            "BTC": 65000.0,
            "ETH": 3500.0,
            "SOL": 180.0,
            "BNB": 600.0,
            "XRP": 0.62,
        }
        out = [
            MarketQuote(
                symbol=s,
                name=s,
                kind="crypto",
                currency=vs_currency,
                price=round(float(fallback_prices.get(s, 100.0)), 4),
                change_24h=0.0,
                updated_at=now,
                source="fallback",
            )
            for s in symbols
        ]
        return self._cache_set(key, out)

    # -----------------------------
    # Indexes (capital markets)
    # -----------------------------

    def get_index_quotes(self, symbols: Sequence[str], *, currency: str = "USD") -> List[MarketQuote]:
        """
        Fetch a small set of index quotes.

        Uses stooq.com as a public, no-key source (best-effort). Falls back to synthetic values.
        """
        symbols = [str(s).upper() for s in symbols if str(s).strip()]
        currency = str(currency).upper()
        key = f"idx:{currency}:{','.join(symbols)}"
        cached = self._cache_get(key)
        if cached is not None:
            return cached

        # Try Bloomberg first (optional; requires credentials and a compatible endpoint).
        bloomberg_base = (os.environ.get("BLOOMBERG_API_BASE_URL") or "").strip()
        bloomberg_key = (os.environ.get("BLOOMBERG_API_KEY") or "").strip()
        if bloomberg_base and bloomberg_key:
            try:
                url = (
                    bloomberg_base.rstrip("/")
                    + "/quotes?"
                    + urllib.parse.urlencode(
                        {
                            "provider": "bloomberg",
                            "type": "index",
                            "symbols": ",".join(symbols),
                            "currency": currency,
                            "api_key": bloomberg_key,
                        }
                    )
                )
                data = _http_get_json(url)
                items = data.get("items") if isinstance(data, dict) else None
                if isinstance(items, list) and items:
                    now = datetime.utcnow().isoformat()
                    out: List[MarketQuote] = []
                    for it in items:
                        if not isinstance(it, dict):
                            continue
                        sym = str(it.get("symbol") or "").upper()
                        if not sym:
                            continue
                        out.append(
                            MarketQuote(
                                symbol=sym,
                                name=str(it.get("name") or sym),
                                kind="index",
                                currency=str(it.get("currency") or currency).upper(),
                                price=round(float(it.get("price") or 0.0), 4),
                                change_24h=round(float(it.get("change_24h") or 0.0), 4),
                                updated_at=str(it.get("updated_at") or now),
                                source="bloomberg",
                            )
                        )
                    if out:
                        return self._cache_set(key, out)
            except Exception:
                pass

        # Stooq symbols mapping (common)
        # Note: Stooq uses caret-prefixed tickers like ^spx for S&P500.
        stooq_map = {
            "SPX": "^spx",
            "SP500": "^spx",
            "NASDAQ": "^ndx",
            "NDX": "^ndx",
            "DOW": "^dji",
            "DJI": "^dji",
            "FTSE": "^ukx",
            "FTSE100": "^ukx",
        }

        out: List[MarketQuote] = []
        now = datetime.utcnow().isoformat()
        # Stooq does not provide easy multi-currency quoting for indexes via this endpoint.
        # We treat a small set of common indexes as priced in their "native" currency and
        # convert to the requested currency using FX rates.
        native_currency = {
            "SPX": "USD",
            "SP500": "USD",
            "NASDAQ": "USD",
            "NDX": "USD",
            "DOW": "USD",
            "DJI": "USD",
            "FTSE": "GBP",
            "FTSE100": "GBP",
        }
        try:
            for sym in symbols:
                st = stooq_map.get(sym, "")
                if not st:
                    continue
                url = f"https://stooq.com/q/l/?s={urllib.parse.quote(st)}&f=sd2t2ohlcv&h&e=csv"
                csv_text = _http_get_text(url)
                lines = [l.strip() for l in csv_text.splitlines() if l.strip()]
                if len(lines) < 2:
                    continue
                # header: Symbol,Date,Time,Open,High,Low,Close,Volume
                parts = lines[1].split(",")
                if len(parts) < 7:
                    continue
                close_native = float(parts[6])
                sym_native_cur = native_currency.get(sym, "USD")
                px = close_native
                if currency and sym_native_cur and currency != sym_native_cur:
                    try:
                        fx = float(self.get_fx_quote(sym_native_cur, currency).price or 1.0)
                        px = close_native * fx
                    except Exception:
                        px = close_native
                out.append(
                    MarketQuote(
                        symbol=sym,
                        name=sym,
                        kind="index",
                        currency=currency,
                        price=round(float(px), 4),
                        change_24h=0.0,
                        updated_at=now,
                        source="live",
                    )
                )
            if out:
                return self._cache_set(key, out)
        except Exception:
            pass

        # Fallback synthetic
        fallback = {
            "SPX": 5900.0,
            "NASDAQ": 21000.0,
            "DOW": 44000.0,
            "FTSE": 8200.0,
        }
        out = [
            MarketQuote(
                symbol=s,
                name=s,
                kind="index",
                currency=currency,
                price=round(float(fallback.get(s, 1000.0)), 4),
                change_24h=0.0,
                updated_at=now,
                source="fallback",
            )
            for s in symbols
        ]
        return self._cache_set(key, out)

    # -----------------------------
    # FX
    # -----------------------------

    def get_fx_quote(self, base: str, quote: str) -> MarketQuote:
        base = str(base).upper()
        quote = str(quote).upper()
        key = f"fx:{base}:{quote}"
        cached = self._cache_get(key)
        if cached is not None:
            return cached

        now = datetime.utcnow().isoformat()
        # Best-effort live FX (no API key).
        try:
            data = _http_get_json(f"https://open.er-api.com/v6/latest/{urllib.parse.quote(base)}")
            if isinstance(data, dict) and data.get("result") == "success":
                rates = data.get("rates")
                if isinstance(rates, dict) and quote in rates:
                    price = float(rates[quote])
                    q_live = MarketQuote(
                        symbol=f"{base}/{quote}",
                        name=f"{base}/{quote}",
                        kind="fx",
                        currency=quote,
                        price=price,
                        change_24h=0.0,
                        updated_at=now,
                        source="live",
                    )
                    return self._cache_set(key, q_live)
        except Exception:
            pass

        # Fallback: stable-ish, conservative defaults.
        fallback_fx = {
            ("USD", "GBP"): 0.79,
            ("GBP", "USD"): 1.27,
            ("USD", "EUR"): 0.92,
            ("EUR", "USD"): 1.09,
            ("USD", "ILS"): 3.70,
            ("ILS", "USD"): 0.27,
            ("EUR", "ILS"): 4.05,
            ("ILS", "EUR"): 0.25,
            ("GBP", "ILS"): 4.70,
            ("ILS", "GBP"): 0.21,
        }
        price = float(fallback_fx.get((base, quote), 1.0))
        q = MarketQuote(symbol=f"{base}/{quote}", name=f"{base}/{quote}", kind="fx", currency=quote, price=price, change_24h=0.0, updated_at=now, source="fallback")
        return self._cache_set(key, q)


__all__ = [
    "MarketQuote",
    "MarketDataClient",
    "MarketDataService",
]

