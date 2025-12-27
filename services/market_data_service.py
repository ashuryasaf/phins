"""
Market data service (crypto + capital markets indexes) for PHINS PHI investments.

Goals:
- Provide a simple, dependency-free connector that can call public endpoints when available.
- Provide a fluent API usable from code and exposed via web endpoints.
- Provide safe fallbacks when outbound network access is unavailable.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Literal, Optional, Sequence, Tuple
import json
import time
import urllib.request
import urllib.parse


MarketKind = Literal["crypto", "index", "fx"]


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

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "name": self.name,
            "kind": self.kind,
            "currency": self.currency,
            "price": self.price,
            "change_24h": self.change_24h,
            "updated_at": self.updated_at,
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
            return {"items": [], "ts": datetime.now(timezone.utc).isoformat()}
        svc = MarketDataService(ttl_seconds=self._ttl_seconds)
        if self._kind == "crypto":
            quotes = svc.get_crypto_quotes(self._symbols, vs_currency=self._vs_currency)
        elif self._kind == "index":
            quotes = svc.get_index_quotes(self._symbols, currency=self._vs_currency)
        else:
            base, quote = self._symbols[0].split("/", 1)
            quotes = [svc.get_fx_quote(base, quote)]
        return {"items": [q.to_dict() for q in quotes], "ts": datetime.now(timezone.utc).isoformat()}


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
                now = datetime.now(timezone.utc).isoformat()
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
                        )
                    )
                if out:
                    return self._cache_set(key, out)
        except Exception:
            # fall back below
            pass

        # Fallback deterministic synthetic quotes
        now = datetime.now(timezone.utc).isoformat()
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
        now = datetime.now(timezone.utc).isoformat()
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
                close = float(parts[6])
                out.append(
                    MarketQuote(
                        symbol=sym,
                        name=sym,
                        kind="index",
                        currency=currency,
                        price=round(close, 4),
                        change_24h=0.0,
                        updated_at=now,
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

        now = datetime.now(timezone.utc).isoformat()
        # No external source by default; provide stable-ish fallback.
        fallback_fx = {
            ("USD", "GBP"): 0.79,
            ("GBP", "USD"): 1.27,
            ("USD", "EUR"): 0.92,
            ("EUR", "USD"): 1.09,
        }
        price = float(fallback_fx.get((base, quote), 1.0))
        q = MarketQuote(symbol=f"{base}/{quote}", name=f"{base}/{quote}", kind="fx", currency=quote, price=price, change_24h=0.0, updated_at=now)
        return self._cache_set(key, q)


__all__ = [
    "MarketQuote",
    "MarketDataClient",
    "MarketDataService",
]

