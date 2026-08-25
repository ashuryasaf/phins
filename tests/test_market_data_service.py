import pytest

from services.market_data_service import MarketDataService


class StubResponse:
    def __init__(self, json_payload=None, text_payload="", status_code=200):
        self._json_payload = json_payload
        self.text = text_payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._json_payload


def test_multi_asset_quotes_from_public_sources(monkeypatch):
    service = MarketDataService(cache_ttl_seconds=0)

    def fake_get(url, params=None, timeout=None, headers=None):
        if "coingecko.com" in url:
            return StubResponse(
                json_payload={"bitcoin": {"usd": 50000.0, "usd_24h_change": 2.15}}
            )
        if "stooq.com" in url:
            return StubResponse(
                text_payload=(
                    "Symbol,Date,Time,Open,High,Low,Close,Volume\n"
                    "SPY.US,2026-02-24,20:00:00,498.00,502.00,497.50,500.00,1200000\n"
                )
            )
        if "frankfurter.app" in url:
            return StubResponse(
                json_payload={
                    "amount": 1.0,
                    "base": "EUR",
                    "date": "2026-02-24",
                    "rates": {"USD": 1.08},
                }
            )
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr("services.market_data_service.requests.get", fake_get)
    data = service.get_multi_asset_quotes(["BTC", "SPY", "EUR"])

    assert data["prices"]["BTC"] == 50000.0
    assert data["prices"]["SPY"] == 500.0
    assert data["prices"]["EUR"] == 1.08
    assert data["quotes"]["BTC"]["asset_class"] == "crypto"
    assert data["quotes"]["SPY"]["asset_class"] == "equity"
    assert data["quotes"]["EUR"]["asset_class"] == "currency"
    assert data["integrity"]["validated_count"] == 3


def test_outlier_price_rejected_and_last_good_preserved(monkeypatch):
    service = MarketDataService(cache_ttl_seconds=0)
    calls = {"coingecko": 0}

    def fake_get(url, params=None, timeout=None, headers=None):
        if "coingecko.com" in url:
            calls["coingecko"] += 1
            if calls["coingecko"] == 1:
                return StubResponse(json_payload={"bitcoin": {"usd": 50000.0}})
            return StubResponse(json_payload={"bitcoin": {"usd": 5000000.0}})
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr("services.market_data_service.requests.get", fake_get)

    first = service.get_multi_asset_quotes(["BTC"])
    second = service.get_multi_asset_quotes(["BTC"])

    assert first["prices"]["BTC"] == 50000.0
    assert second["prices"]["BTC"] == 50000.0
    assert second["quotes"]["BTC"]["status"] == "stale_last_good"
    assert second["integrity"]["outliers_blocked"][0]["symbol"] == "BTC"


def test_bloomberg_provider_adapter_parses_enterprise_payload(monkeypatch):
    service = MarketDataService(cache_ttl_seconds=0)
    monkeypatch.setenv("PHINS_BLOOMBERG_QUOTES_API_URL", "https://example.com/bbg")

    def fake_get(url, params=None, timeout=None, headers=None):
        if "example.com/bbg" in url:
            return StubResponse(
                json_payload={
                    "quotes": [
                        {
                            "symbol": "SPY",
                            "price": "501.25",
                            "change_pct": "0.42",
                            "bid": "501.10",
                            "ask": "501.30",
                        }
                    ]
                }
            )
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr("services.market_data_service.requests.get", fake_get)
    data = service.get_multi_asset_quotes(["SPY"], provider_preference="bloomberg")

    assert data["provider"] == "bloomberg"
    assert data["prices"]["SPY"] == 501.25
    assert data["quotes"]["SPY"]["source"] == "bloomberg"


class StubTradingPlatform:
    def __init__(self, bars_by_symbol=None, connected=True):
        self._bars = bars_by_symbol or {}
        self.is_connected = connected
        self.requested_symbols = []

    def get_bars(self, symbol, timeframe="1Day", limit=100):
        self.requested_symbols.append(symbol)
        return self._bars.get(symbol, [])


def test_alpaca_preferred_for_securities(monkeypatch):
    service = MarketDataService(cache_ttl_seconds=0)
    platform = StubTradingPlatform(
        bars_by_symbol={
            "SPY": [
                {"date": "2026-08-24T04:00:00Z", "open": 495.0, "high": 499.0,
                 "low": 494.0, "close": 498.0, "volume": 1000000},
                {"date": "2026-08-25T04:00:00Z", "open": 499.0, "high": 503.0,
                 "low": 498.5, "close": 501.0, "volume": 1100000},
            ]
        }
    )
    monkeypatch.setattr(
        "services.trading_platform_service.get_trading_platform", lambda: platform
    )

    def no_network(url, params=None, timeout=None, headers=None):
        raise AssertionError(f"Unexpected network call to {url}")

    monkeypatch.setattr("services.market_data_service.requests.get", no_network)

    data = service.get_multi_asset_quotes(["SPY"])

    quote = data["quotes"]["SPY"]
    assert quote["source"] == "alpaca"
    assert quote["price"] == 501.0
    assert quote["date"] == "2026-08-25"
    assert quote["change_pct"] == pytest.approx((501.0 - 498.0) / 498.0 * 100.0)
    assert data["prices"]["SPY"] == 501.0
    assert platform.requested_symbols == ["SPY"]


def test_alpaca_disconnected_falls_back_to_public_sources(monkeypatch):
    service = MarketDataService(cache_ttl_seconds=0)
    platform = StubTradingPlatform(connected=False)
    monkeypatch.setattr(
        "services.trading_platform_service.get_trading_platform", lambda: platform
    )

    def fake_get(url, params=None, timeout=None, headers=None):
        if "stooq.com" in url:
            return StubResponse(
                text_payload=(
                    "Symbol,Date,Time,Open,High,Low,Close,Volume\n"
                    "SPY.US,2026-02-24,20:00:00,498.00,502.00,497.50,500.00,1200000\n"
                )
            )
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr("services.market_data_service.requests.get", fake_get)

    data = service.get_multi_asset_quotes(["SPY"])

    assert platform.requested_symbols == []
    assert data["quotes"]["SPY"]["source"] == "stooq"
    assert data["prices"]["SPY"] == 500.0


def test_alpaca_skips_index_symbols(monkeypatch):
    service = MarketDataService(cache_ttl_seconds=0)
    platform = StubTradingPlatform(connected=True)
    monkeypatch.setattr(
        "services.trading_platform_service.get_trading_platform", lambda: platform
    )

    def fake_get(url, params=None, timeout=None, headers=None):
        if "stooq.com" in url:
            return StubResponse(
                text_payload=(
                    "Symbol,Date,Time,Open,High,Low,Close,Volume\n"
                    "^SPX,2026-02-24,20:00:00,4980.00,5020.00,4975.00,5000.00,0\n"
                )
            )
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr("services.market_data_service.requests.get", fake_get)

    data = service.get_multi_asset_quotes(["^SPX"])

    # Alpaca serves stocks/ETFs only; indexes go straight to Stooq.
    assert platform.requested_symbols == []
    assert data["quotes"]["^SPX"]["source"] == "stooq"


def test_crypto_compatibility_response_shape(monkeypatch):
    service = MarketDataService(cache_ttl_seconds=0)

    def fake_get(url, params=None, timeout=None, headers=None):
        if "coingecko.com" in url:
            return StubResponse(json_payload={"bitcoin": {"usd": 51000.0}})
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr("services.market_data_service.requests.get", fake_get)
    result = service.get_crypto_prices_usd(["BTC", "UNKNOWN"])

    assert result["prices"]["BTC"] == 51000.0
    assert "UNKNOWN" in result["unknown"]
