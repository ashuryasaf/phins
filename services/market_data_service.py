from __future__ import annotations

import csv
import io
import math
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests


@dataclass
class CachedValue:
    value: Any
    expires_at: float


class MarketDataService:
    """
    Real-time multi-asset market data service with integrity safeguards.

    Provider order:
    1) Optional enterprise Bloomberg/Reuters adapters (via env URLs)
    2) Reliable public fallbacks:
       - Crypto: CoinGecko
       - Stocks/Bonds/Indexes/ETFs: Stooq
       - FX rates: Frankfurter (ECB-backed)
    """

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
        "AVAX": "avalanche-2",
        "DOT": "polkadot",
        "LINK": "chainlink",
        "MATIC": "matic-network",
    }

    CURRENCY_CODES = {
        "USD",
        "EUR",
        "GBP",
        "JPY",
        "CHF",
        "ILS",
        "AUD",
        "CAD",
        "NZD",
        "SEK",
        "NOK",
    }

    SYMBOL_CLASS_OVERRIDES: Dict[str, str] = {
        # Equities / ETFs
        "SPY": "equity",
        "QQQ": "equity",
        "VTI": "equity",
        "VXUS": "equity",
        "VWO": "equity",
        "AAPL": "equity",
        "MSFT": "equity",
        "NVDA": "equity",
        "GOOGL": "equity",
        "AMZN": "equity",
        "META": "equity",
        "TSLA": "equity",
        # Bonds / bond ETFs
        "BND": "bond",
        "TLT": "bond",
        "SHY": "bond",
        "LQD": "bond",
        "HYG": "bond",
        "EMB": "bond",
        "TIPS": "bond",
        "MUB": "bond",
        # Commodities / commodity ETFs
        "GLD": "commodity",
        "SLV": "commodity",
        "USO": "commodity",
        "UNG": "commodity",
        "CPER": "commodity",
        "PALL": "commodity",
        "CORN": "commodity",
        "WEAT": "commodity",
        # Indexes
        "^SPX": "index",
        "^NDX": "index",
        "^DJI": "index",
        "^FTSE": "index",
        "^DAX": "index",
        "^TA125": "index",
        # FX pairs
        "EURUSD": "currency_pair",
        "GBPUSD": "currency_pair",
        "USDJPY": "currency_pair",
        "USDCHF": "currency_pair",
        "AUDUSD": "currency_pair",
        "USDCAD": "currency_pair",
    }

    STOOQ_SYMBOL_MAP: Dict[str, str] = {
        "^SPX": "^spx",
        "^NDX": "^ndq",
        "^DJI": "^dji",
        "^FTSE": "^ukx",
        "^DAX": "^dax",
        "^TA125": "^ta125",
    }

    # Maximum acceptable single-update move before using last good value.
    OUTLIER_THRESHOLD_BY_CLASS: Dict[str, float] = {
        "crypto": 0.80,
        "equity": 0.35,
        "bond": 0.20,
        "commodity": 0.35,
        "index": 0.25,
        "currency": 0.10,
        "currency_pair": 0.10,
    }

    # Maximum age (seconds) for a "last good quote" before it expires.
    # After expiry, a new price is accepted even if it exceeds the outlier threshold.
    LAST_GOOD_QUOTE_MAX_AGE_SECONDS: int = 300  # 5 minutes

    def __init__(self, cache_ttl_seconds: int = 30, timeout_seconds: int = 8):
        self._ttl = cache_ttl_seconds
        self._timeout = timeout_seconds
        self._cache: Dict[str, CachedValue] = {}
        self._last_good_quotes: Dict[str, tuple] = {}  # symbol -> (price, timestamp)

    # ---------------------------------------------------------------------
    # Compatibility methods used elsewhere in the codebase
    # ---------------------------------------------------------------------
    def get_crypto_prices_usd(self, symbols: List[str]) -> Dict[str, Any]:
        symbols_norm = self._normalize_symbols(symbols)
        result = self.get_multi_asset_quotes(symbols_norm, provider_preference="auto")
        prices = {}
        for symbol in symbols_norm:
            quote = result["quotes"].get(symbol)
            if not quote:
                continue
            if quote.get("asset_class") != "crypto":
                continue
            if quote.get("status") not in ("ok", "stale_last_good"):
                continue
            prices[symbol] = quote["price"]

        unknown = [s for s in symbols_norm if s not in self.COINGECKO_IDS]
        return {
            "source": result.get("provider", "public"),
            "prices": prices,
            "unknown": unknown,
            "timestamp": result.get("timestamp"),
            "integrity": result.get("integrity", {}),
        }

    def get_index_quotes(self, symbols: List[str]) -> Dict[str, Any]:
        symbols_requested = [str(s or "").strip() for s in symbols if str(s or "").strip()]
        symbols_norm = self._normalize_symbols(symbols_requested)
        result = self.get_multi_asset_quotes(symbols_norm, provider_preference="auto")

        quotes: Dict[str, Any] = {}
        for requested in symbols_requested:
            symbol = requested.upper()
            normalized_key = requested.lower()
            quote = result["quotes"].get(symbol)
            if not quote or quote.get("status") == "unavailable":
                quotes[normalized_key] = {"status": "unavailable"}
                continue
            quotes[normalized_key] = {
                "status": quote.get("status", "ok"),
                "date": quote.get("date"),
                "time": quote.get("time"),
                "open": quote.get("open"),
                "high": quote.get("high"),
                "low": quote.get("low"),
                "close": quote.get("price"),
                "volume": quote.get("volume"),
                "source": quote.get("source", "stooq"),
            }

        return {
            "source": result.get("provider", "public"),
            "quotes": quotes,
            "timestamp": result.get("timestamp"),
            "integrity": result.get("integrity", {}),
        }

    # ---------------------------------------------------------------------
    # New multi-asset quote API used by dashboards
    # ---------------------------------------------------------------------
    def get_multi_asset_quotes(
        self, symbols: List[str], provider_preference: str = "auto"
    ) -> Dict[str, Any]:
        symbols_norm = self._normalize_symbols(symbols)
        cache_key = f"multi:{provider_preference.lower()}:{','.join(symbols_norm)}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        if not symbols_norm:
            empty = {
                "provider": "public",
                "timestamp": self._now_iso(),
                "quotes": {},
                "prices": {},
                "unknown": [],
                "integrity": {
                    "validated_count": 0,
                    "outliers_blocked": [],
                    "source_breakdown": {},
                },
            }
            self._set_cached(cache_key, empty)
            return empty

        provider = provider_preference.strip().lower()
        provider_used = "public"
        quotes: Dict[str, Dict[str, Any]] = {}
        unknown: List[str] = []
        outliers: List[Dict[str, Any]] = []

        remaining = list(symbols_norm)

        if provider in {"bloomberg", "reuters"}:
            enterprise_quotes = self._fetch_enterprise_quotes(remaining, provider)
            if enterprise_quotes:
                provider_used = provider
                quotes.update(enterprise_quotes)
                remaining = [s for s in remaining if s not in enterprise_quotes]
            else:
                provider_used = f"{provider}_fallback"

        crypto_symbols = [s for s in remaining if self._classify_symbol(s) == "crypto"]
        fx_symbols = [
            s
            for s in remaining
            if self._classify_symbol(s) in {"currency", "currency_pair"}
        ]
        security_symbols = [s for s in remaining if s not in set(crypto_symbols + fx_symbols)]

        quotes.update(self._fetch_public_crypto_quotes(crypto_symbols))
        quotes.update(self._fetch_public_fx_quotes(fx_symbols))
        quotes.update(self._fetch_public_stooq_quotes(security_symbols))

        # Integrity guardrails: block invalid / outlier updates.
        for symbol in symbols_norm:
            raw = quotes.get(symbol)
            if not raw:
                unknown.append(symbol)
                continue
            quotes[symbol] = self._enforce_integrity(symbol, raw, outliers)

        prices = {
            symbol: quote["price"]
            for symbol, quote in quotes.items()
            if quote.get("status") in ("ok", "stale_last_good")
            and self._safe_float(quote.get("price")) is not None
        }

        result = {
            "provider": provider_used,
            "timestamp": self._now_iso(),
            "quotes": quotes,
            "prices": prices,
            "unknown": unknown,
            "integrity": {
                "validated_count": len(prices),
                "outliers_blocked": outliers,
                "source_breakdown": self._source_breakdown(quotes),
            },
        }
        self._set_cached(cache_key, result)
        return result

    # ---------------------------------------------------------------------
    # Enterprise provider hooks (optional)
    # ---------------------------------------------------------------------
    def _fetch_enterprise_quotes(
        self, symbols: List[str], provider: str
    ) -> Dict[str, Dict[str, Any]]:
        endpoint, api_key = self._enterprise_config(provider)
        if not endpoint or not symbols:
            return {}

        headers = {"Accept": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        try:
            resp = requests.get(
                endpoint,
                params={"symbols": ",".join(symbols)},
                headers=headers,
                timeout=self._timeout,
            )
            resp.raise_for_status()
            payload = resp.json()
        except Exception:
            return {}

        parsed: Dict[str, Dict[str, Any]] = {}
        entries = self._extract_quote_entries(payload)
        for entry in entries:
            symbol = str(
                entry.get("symbol")
                or entry.get("ticker")
                or entry.get("security")
                or entry.get("ric")
                or ""
            ).upper()
            if not symbol:
                continue
            price = self._safe_float(
                entry.get("price")
                if entry.get("price") is not None
                else entry.get("last")
            )
            if price is None or price <= 0:
                continue

            bid = self._safe_float(entry.get("bid"))
            ask = self._safe_float(entry.get("ask"))
            change_pct = self._safe_float(
                entry.get("change_pct")
                if entry.get("change_pct") is not None
                else entry.get("pctChange")
            )
            parsed[symbol] = {
                "symbol": symbol,
                "asset_class": self._classify_symbol(symbol),
                "price": price,
                "bid": bid,
                "ask": ask,
                "change_pct": change_pct,
                "source": provider,
                "as_of": entry.get("timestamp")
                or entry.get("as_of")
                or self._now_iso(),
            }
        return parsed

    def _enterprise_config(self, provider: str) -> tuple[Optional[str], Optional[str]]:
        if provider == "bloomberg":
            return (
                os.environ.get("PHINS_BLOOMBERG_QUOTES_API_URL")
                or os.environ.get("BLOOMBERG_QUOTES_API_URL"),
                os.environ.get("PHINS_BLOOMBERG_API_KEY")
                or os.environ.get("BLOOMBERG_API_KEY"),
            )
        if provider == "reuters":
            return (
                os.environ.get("PHINS_REUTERS_QUOTES_API_URL")
                or os.environ.get("REUTERS_QUOTES_API_URL"),
                os.environ.get("PHINS_REUTERS_API_KEY")
                or os.environ.get("REUTERS_API_KEY"),
            )
        return None, None

    def _extract_quote_entries(self, payload: Any) -> List[Dict[str, Any]]:
        if isinstance(payload, list):
            return [p for p in payload if isinstance(p, dict)]
        if not isinstance(payload, dict):
            return []
        if isinstance(payload.get("quotes"), dict):
            return [
                {"symbol": symbol, **(quote if isinstance(quote, dict) else {"price": quote})}
                for symbol, quote in payload["quotes"].items()
            ]
        if isinstance(payload.get("quotes"), list):
            return [p for p in payload["quotes"] if isinstance(p, dict)]
        if isinstance(payload.get("data"), list):
            return [p for p in payload["data"] if isinstance(p, dict)]
        return []

    # ---------------------------------------------------------------------
    # Public providers
    # ---------------------------------------------------------------------
    def _fetch_public_crypto_quotes(self, symbols: List[str]) -> Dict[str, Dict[str, Any]]:
        if not symbols:
            return {}

        id_to_symbol: Dict[str, str] = {}
        for symbol in symbols:
            coin_id = self.COINGECKO_IDS.get(symbol)
            if coin_id:
                id_to_symbol[coin_id] = symbol

        if not id_to_symbol:
            return {}

        try:
            resp = requests.get(
                "https://api.coingecko.com/api/v3/simple/price",
                params={
                    "ids": ",".join(id_to_symbol.keys()),
                    "vs_currencies": "usd",
                    "include_24hr_change": "true",
                },
                timeout=self._timeout,
            )
            resp.raise_for_status()
            payload = resp.json()
        except Exception:
            return {}

        quotes: Dict[str, Dict[str, Any]] = {}
        for coin_id, symbol in id_to_symbol.items():
            coin_data = payload.get(coin_id) or {}
            price = self._safe_float(coin_data.get("usd"))
            if price is None or price <= 0:
                continue
            change_pct = self._safe_float(coin_data.get("usd_24h_change"))
            quotes[symbol] = {
                "symbol": symbol,
                "asset_class": "crypto",
                "price": price,
                "change_pct": change_pct,
                "source": "coingecko",
                "as_of": self._now_iso(),
            }
        return quotes

    def _fetch_public_fx_quotes(self, symbols: List[str]) -> Dict[str, Dict[str, Any]]:
        quotes: Dict[str, Dict[str, Any]] = {}
        for symbol in symbols:
            base_ccy: Optional[str] = None
            quote_ccy: Optional[str] = None

            if len(symbol) == 3 and symbol in self.CURRENCY_CODES and symbol != "USD":
                base_ccy = symbol
                quote_ccy = "USD"
            elif (
                len(symbol) == 6
                and symbol[:3] in self.CURRENCY_CODES
                and symbol[3:] in self.CURRENCY_CODES
            ):
                base_ccy = symbol[:3]
                quote_ccy = symbol[3:]

            if not base_ccy or not quote_ccy:
                continue

            try:
                resp = requests.get(
                    "https://api.frankfurter.app/latest",
                    params={"from": base_ccy, "to": quote_ccy},
                    timeout=self._timeout,
                )
                resp.raise_for_status()
                payload = resp.json()
            except Exception:
                continue

            rates = payload.get("rates") or {}
            price = self._safe_float(rates.get(quote_ccy))
            if price is None or price <= 0:
                continue

            quotes[symbol] = {
                "symbol": symbol,
                "asset_class": self._classify_symbol(symbol),
                "price": price,
                "source": "frankfurter_ecb",
                "date": payload.get("date"),
                "as_of": self._now_iso(),
            }
        return quotes

    def _fetch_public_stooq_quotes(self, symbols: List[str]) -> Dict[str, Dict[str, Any]]:
        quotes: Dict[str, Dict[str, Any]] = {}
        for symbol in symbols:
            stooq_symbol = self._to_stooq_symbol(symbol)
            try:
                resp = requests.get(
                    "https://stooq.com/q/l/",
                    params={"s": stooq_symbol, "f": "sd2t2ohlcv", "h": "", "e": "csv"},
                    timeout=self._timeout,
                )
                resp.raise_for_status()
                row = next(csv.DictReader(io.StringIO(resp.text.strip())), None)
            except Exception:
                row = None

            if not row:
                continue

            close = self._safe_float(row.get("Close"))
            if close is None or close <= 0:
                continue

            open_px = self._safe_float(row.get("Open"))
            high = self._safe_float(row.get("High"))
            low = self._safe_float(row.get("Low"))
            volume = self._safe_float(row.get("Volume"))
            change_pct = None
            if open_px is not None and open_px > 0:
                change_pct = ((close - open_px) / open_px) * 100.0

            quotes[symbol] = {
                "symbol": symbol,
                "asset_class": self._classify_symbol(symbol),
                "price": close,
                "open": open_px,
                "high": high,
                "low": low,
                "volume": volume,
                "date": row.get("Date"),
                "time": row.get("Time"),
                "change_pct": change_pct,
                "source": "stooq",
                "as_of": self._now_iso(),
            }
        return quotes

    # ---------------------------------------------------------------------
    # Integrity helpers
    # ---------------------------------------------------------------------
    def _enforce_integrity(
        self, symbol: str, quote: Dict[str, Any], outliers: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        safe_quote = dict(quote)
        safe_quote["symbol"] = symbol
        safe_quote["asset_class"] = safe_quote.get("asset_class") or self._classify_symbol(symbol)

        price = self._safe_float(safe_quote.get("price"))
        stored = self._last_good_quotes.get(symbol)
        previous_price: Optional[float] = None
        previous_ts: Optional[float] = None
        if stored is not None:
            previous_price, previous_ts = stored

        now = time.time()
        is_stale = (
            previous_ts is not None
            and (now - previous_ts) > self.LAST_GOOD_QUOTE_MAX_AGE_SECONDS
        )

        if price is None or price <= 0:
            if previous_price is not None and previous_price > 0 and not is_stale:
                safe_quote["status"] = "stale_last_good"
                safe_quote["price"] = previous_price
                safe_quote["integrity_note"] = "invalid_live_price"
                return safe_quote
            safe_quote["status"] = "unavailable"
            return safe_quote

        if previous_price is not None and previous_price > 0 and not is_stale:
            change_ratio = abs(price - previous_price) / previous_price
            threshold = self.OUTLIER_THRESHOLD_BY_CLASS.get(
                safe_quote["asset_class"], 0.35
            )
            if change_ratio > threshold:
                outliers.append(
                    {
                        "symbol": symbol,
                        "rejected_price": price,
                        "last_good_price": previous_price,
                        "change_pct": round(change_ratio * 100, 2),
                        "threshold_pct": round(threshold * 100, 2),
                    }
                )
                safe_quote["status"] = "stale_last_good"
                safe_quote["price"] = previous_price
                safe_quote["integrity_note"] = "outlier_rejected"
                return safe_quote

        self._last_good_quotes[symbol] = (price, now)
        safe_quote["status"] = "ok"
        safe_quote["price"] = price
        return safe_quote

    def _source_breakdown(self, quotes: Dict[str, Dict[str, Any]]) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for quote in quotes.values():
            src = str(quote.get("source") or "unknown")
            counts[src] = counts.get(src, 0) + 1
        return counts

    # ---------------------------------------------------------------------
    # Utility helpers
    # ---------------------------------------------------------------------
    def _get_cached(self, key: str) -> Any:
        hit = self._cache.get(key)
        if hit and time.time() < hit.expires_at:
            return hit.value
        return None

    def _set_cached(self, key: str, value: Any) -> None:
        self._cache[key] = CachedValue(value=value, expires_at=time.time() + self._ttl)

    def _normalize_symbols(self, symbols: List[str]) -> List[str]:
        normalized: List[str] = []
        seen = set()
        for raw in symbols:
            symbol = str(raw or "").strip().upper()
            if not symbol or symbol in seen:
                continue
            seen.add(symbol)
            normalized.append(symbol)
        return normalized

    def _classify_symbol(self, symbol: str) -> str:
        if symbol in self.COINGECKO_IDS:
            return "crypto"
        if symbol in self.SYMBOL_CLASS_OVERRIDES:
            return self.SYMBOL_CLASS_OVERRIDES[symbol]
        if symbol in self.CURRENCY_CODES:
            return "currency"
        if (
            len(symbol) == 6
            and symbol[:3] in self.CURRENCY_CODES
            and symbol[3:] in self.CURRENCY_CODES
        ):
            return "currency_pair"
        if symbol.startswith("^"):
            return "index"
        return "equity"

    def _to_stooq_symbol(self, symbol: str) -> str:
        if symbol in self.STOOQ_SYMBOL_MAP:
            return self.STOOQ_SYMBOL_MAP[symbol]
        if symbol.startswith("^"):
            return symbol.lower()

        symbol_class = self._classify_symbol(symbol)
        if (
            symbol_class in {"equity", "bond", "commodity"}
            and symbol.isalpha()
            and len(symbol) <= 5
        ):
            return f"{symbol.lower()}.us"
        return symbol.lower()

    def _safe_float(self, value: Any) -> Optional[float]:
        try:
            converted = float(value)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(converted):
            return None
        return converted

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()

