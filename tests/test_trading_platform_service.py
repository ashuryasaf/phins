import sys
import types

import web_portal

from services.trading_platform_service import (
    TradingPlatformService,
    _VALID_SIDES,
    _VALID_ORDER_TYPES,
    _VALID_TIF,
)


def test_submit_bracket_order_records_to_ledger(monkeypatch):
    service = TradingPlatformService()
    service._connected = True

    recorded = {}

    def fake_trade_request(method, path, body):
        assert method == "POST"
        assert path == "/orders"
        assert body["order_class"] == "bracket"
        return {
            "id": "ord-bracket",
            "symbol": "AAPL",
            "side": "buy",
            "qty": "5",
            "status": "accepted",
            "filled_avg_price": None,
            "legs": [{"id": "leg-1"}],
        }

    def fake_record(order_result, customer_id="TERMINAL", position_snapshot=None):
        recorded["order_result"] = order_result
        recorded["customer_id"] = customer_id
        recorded["position_snapshot"] = position_snapshot

    monkeypatch.setattr(service, "_trade_request", fake_trade_request)
    monkeypatch.setattr(service, "_record_trade_to_ledger", fake_record)

    result = service.submit_bracket_order(
        symbol="AAPL",
        side="buy",
        qty=5,
        take_profit_price=210,
        stop_loss_price=190,
    )

    assert result["order_id"] == "ord-bracket"
    assert recorded["order_result"]["type"] == "bracket"
    assert recorded["order_result"]["side"] == "buy"
    assert recorded["order_result"]["qty"] == "5"


def test_submit_oco_order_records_to_ledger(monkeypatch):
    service = TradingPlatformService()
    service._connected = True

    recorded = {}

    def fake_trade_request(method, path, body):
        assert method == "POST"
        assert path == "/orders"
        assert body["order_class"] == "oco"
        return {
            "id": "ord-oco",
            "symbol": "AAPL",
            "side": "sell",
            "qty": "5",
            "status": "accepted",
            "filled_avg_price": None,
            "legs": [{"id": "leg-1"}],
        }

    def fake_record(order_result, customer_id="TERMINAL", position_snapshot=None):
        recorded["order_result"] = order_result
        recorded["customer_id"] = customer_id
        recorded["position_snapshot"] = position_snapshot

    monkeypatch.setattr(service, "_trade_request", fake_trade_request)
    monkeypatch.setattr(service, "_get_position_snapshot", lambda symbol: {"symbol": symbol, "qty": 5})
    monkeypatch.setattr(service, "_record_trade_to_ledger", fake_record)

    result = service.submit_oco_order(
        symbol="AAPL",
        qty=5,
        take_profit_price=210,
        stop_loss_price=190,
    )

    assert result["order_id"] == "ord-oco"
    assert recorded["order_result"]["type"] == "oco"
    assert recorded["order_result"]["side"] == "sell"
    assert recorded["order_result"]["qty"] == "5"


def test_record_trade_to_ledger_stores_realized_gain_metadata(monkeypatch):
    service = TradingPlatformService()

    captured = {}
    fake_portal = types.ModuleType("web_portal.server")
    fake_portal.TRANSACTION_LEDGER = {}

    def fake_record_transaction(**kwargs):
        captured.update(kwargs)
        return kwargs

    fake_portal.record_transaction = fake_record_transaction
    monkeypatch.setitem(sys.modules, "web_portal.server", fake_portal)
    monkeypatch.setattr(web_portal, "server", fake_portal, raising=False)

    service._record_trade_to_ledger(
        {
            "order_id": "ord-sell",
            "symbol": "AAPL",
            "side": "sell",
            "qty": "10",
            "filled_avg_price": "200",
            "type": "market",
            "status": "filled",
            "broker": "alpaca",
        },
        position_snapshot={
            "symbol": "AAPL",
            "qty": 10,
            "avg_entry_price": 180,
            "cost_basis": 1800,
        },
    )

    assert captured["amount"] == 2000
    assert captured["metadata"]["estimated_cost_basis"] == 1800
    assert captured["metadata"]["realized_gain"] == 200


def test_get_pretax_balance_sheet_uses_realized_gain_metadata(monkeypatch):
    service = TradingPlatformService()

    fake_portal = types.ModuleType("web_portal.server")
    fake_portal.TRANSACTION_LEDGER = {
        "TX-1": {
            "id": "TX-1",
            "customer_id": "TERMINAL",
            "type": "trade_sell",
            "amount": 2000,
            "metadata": {
                "symbol": "AAPL",
                "realized_gain": 200,
            },
        }
    }

    monkeypatch.setitem(sys.modules, "web_portal.server", fake_portal)
    monkeypatch.setattr(web_portal, "server", fake_portal, raising=False)
    monkeypatch.setattr(service, "get_account", lambda: {"cash": 1000, "equity": 1500})
    monkeypatch.setattr(service, "get_positions", lambda: [])

    result = service.get_pretax_balance_sheet()

    assert result["gains_losses"]["realized_total"] == 200
    assert result["tax_estimates"]["est_tax_realized"] == 74


def test_get_account_reloads_before_not_connected_fallback(monkeypatch):
    service = TradingPlatformService()
    service._connected = False

    reload_calls = {"count": 0}

    def fake_reload_keys():
        reload_calls["count"] += 1
        service._connected = True

    def fail_not_connected_account():
        raise AssertionError("get_account should not return the disconnected fallback after a successful reload")

    def fake_trade_request(method, path, body=None):
        assert method == "GET"
        assert path == "/account"
        return {
            "id": "acct-1",
            "status": "ACTIVE",
            "currency": "USD",
            "buying_power": "1000",
            "cash": "750",
            "portfolio_value": "1250",
            "equity": "1250",
            "last_equity": "1200",
            "long_market_value": "500",
            "short_market_value": "0",
            "unrealized_pl": "50",
            "unrealized_plpc": "0.04",
            "daytrade_count": 1,
            "pattern_day_trader": False,
            "trading_blocked": False,
        }

    monkeypatch.setattr(service, "_reload_keys", fake_reload_keys)
    monkeypatch.setattr(service, "_not_connected_account", fail_not_connected_account)
    monkeypatch.setattr(service, "_trade_request", fake_trade_request)

    result = service.get_account()

    assert reload_calls["count"] == 1
    assert result["account_id"] == "acct-1"
    assert result["connected"] is True


def test_positions_and_orders_reload_before_returning_empty_results(monkeypatch):
    service = TradingPlatformService()
    service._connected = False

    reload_calls = {"count": 0}

    def fake_reload_keys():
        reload_calls["count"] += 1
        service._connected = True

    def fake_trade_request(method, path, body=None):
        assert method == "GET"
        if path == "/positions":
            return [{
                "symbol": "AAPL",
                "qty": "2",
                "side": "long",
                "avg_entry_price": "180",
                "current_price": "200",
                "market_value": "400",
                "cost_basis": "360",
                "unrealized_pl": "40",
                "unrealized_plpc": "0.11",
                "change_today": "0.01",
                "asset_class": "us_equity",
            }]
        assert path == "/orders?status=all&limit=20"
        return [{
            "id": "ord-1",
            "symbol": "AAPL",
            "side": "buy",
            "qty": "2",
            "type": "market",
            "status": "filled",
            "filled_qty": "2",
            "filled_avg_price": "200",
            "limit_price": None,
            "created_at": "2026-04-06T00:00:00Z",
            "updated_at": "2026-04-06T00:00:01Z",
        }]

    monkeypatch.setattr(service, "_reload_keys", fake_reload_keys)
    monkeypatch.setattr(service, "_trade_request", fake_trade_request)

    positions = service.get_positions()
    service._connected = False
    orders = service.get_orders()

    assert reload_calls["count"] == 2
    assert positions[0]["symbol"] == "AAPL"
    assert orders[0]["order_id"] == "ord-1"


def test_submit_order_reloads_before_fetching_sell_snapshot(monkeypatch):
    service = TradingPlatformService()
    service._connected = False

    sequence = []
    recorded = {}

    def fake_reload_keys():
        sequence.append("reload")
        service._connected = True

    def fake_get_position_snapshot(symbol):
        sequence.append("snapshot")
        assert service._connected is True
        assert symbol == "AAPL"
        return {"symbol": "AAPL", "qty": 5, "avg_entry_price": 180, "cost_basis": 900}

    def fake_trade_request(method, path, body=None):
        sequence.append("trade")
        assert method == "POST"
        assert path == "/orders"
        assert body["side"] == "sell"
        return {
            "id": "ord-sell",
            "symbol": "AAPL",
            "side": "sell",
            "qty": "5",
            "notional": None,
            "type": "market",
            "time_in_force": "day",
            "status": "filled",
            "filled_qty": "5",
            "filled_avg_price": "200",
            "limit_price": None,
            "stop_price": None,
            "created_at": "2026-04-06T00:00:00Z",
        }

    def fake_record_trade(order_result, customer_id="TERMINAL", position_snapshot=None):
        recorded["order_result"] = order_result
        recorded["position_snapshot"] = position_snapshot

    monkeypatch.setattr(service, "_reload_keys", fake_reload_keys)
    monkeypatch.setattr(service, "_get_position_snapshot", fake_get_position_snapshot)
    monkeypatch.setattr(service, "_trade_request", fake_trade_request)
    monkeypatch.setattr(service, "_record_trade_to_ledger", fake_record_trade)

    result = service.submit_order("AAPL", "sell", qty=5)

    assert sequence == ["reload", "snapshot", "trade"]
    assert result["order_id"] == "ord-sell"
    assert recorded["position_snapshot"]["cost_basis"] == 900


def test_ai_copilot_analyze_uses_atr_for_trade_levels(monkeypatch):
    service = TradingPlatformService()

    import services.ai_trading_engine as ai_trading_engine

    monkeypatch.setattr(
        service,
        "get_bars",
        lambda symbol, timeframe="1Day", limit=100: [{"close": 100.0}],
    )
    monkeypatch.setattr(service, "get_positions", lambda: [])
    monkeypatch.setattr(
        service,
        "get_account",
        lambda: {"buying_power": 10000, "portfolio_value": 10000},
    )
    monkeypatch.setattr(
        ai_trading_engine,
        "compute_technicals",
        lambda bars: {"indicators": {"atr_14": 2.5}},
    )
    monkeypatch.setattr(
        ai_trading_engine,
        "generate_signals",
        lambda technicals, price: {
            "recommendation": "BUY",
            "composite_score": 2,
            "confidence": 0.6,
            "details": [],
        },
    )
    monkeypatch.setattr(ai_trading_engine, "compute_risk_metrics", lambda bars, positions: {})

    result = service.ai_copilot_analyze("AAPL")

    assert result["technicals"]["atr"] == 2.5
    assert result["trade_suggestion"]["stop_loss"] == 95.0
    assert result["trade_suggestion"]["take_profit"] == 107.5


# ==================================================================
# INPUT VALIDATION TESTS
# ==================================================================


def test_submit_order_rejects_invalid_side():
    service = TradingPlatformService()
    service._connected = True
    result = service.submit_order("AAPL", "hold", qty=1)
    assert "error" in result
    assert "Invalid side" in result["error"]


def test_submit_order_rejects_invalid_order_type():
    service = TradingPlatformService()
    service._connected = True
    result = service.submit_order("AAPL", "buy", qty=1, order_type="magic")
    assert "error" in result
    assert "Invalid order_type" in result["error"]


def test_submit_order_rejects_invalid_tif():
    service = TradingPlatformService()
    service._connected = True
    result = service.submit_order("AAPL", "buy", qty=1, time_in_force="forever")
    assert "error" in result
    assert "Invalid time_in_force" in result["error"]


def test_submit_order_rejects_empty_symbol():
    service = TradingPlatformService()
    service._connected = True
    result = service.submit_order("", "buy", qty=1)
    assert "error" in result
    assert "symbol" in result["error"].lower()


def test_submit_order_rejects_negative_qty():
    service = TradingPlatformService()
    service._connected = True
    result = service.submit_order("AAPL", "buy", qty=-5)
    assert "error" in result
    assert "positive" in result["error"].lower()


def test_submit_order_rejects_zero_limit_price():
    service = TradingPlatformService()
    service._connected = True
    result = service.submit_order("AAPL", "buy", qty=1, order_type="limit", limit_price=0)
    assert "error" in result
    assert "limit_price" in result["error"]


def test_submit_order_rejects_negative_stop_price():
    service = TradingPlatformService()
    service._connected = True
    result = service.submit_order("AAPL", "buy", qty=1, order_type="stop", stop_price=-10)
    assert "error" in result
    assert "stop_price" in result["error"]


def test_valid_sides_constant():
    assert "buy" in _VALID_SIDES
    assert "sell" in _VALID_SIDES
    assert "hold" not in _VALID_SIDES


def test_valid_order_types_constant():
    assert "market" in _VALID_ORDER_TYPES
    assert "limit" in _VALID_ORDER_TYPES
    assert "stop" in _VALID_ORDER_TYPES
    assert "trailing_stop" in _VALID_ORDER_TYPES
    assert "magic" not in _VALID_ORDER_TYPES


def test_valid_tif_constant():
    assert "day" in _VALID_TIF
    assert "gtc" in _VALID_TIF
    assert "ioc" in _VALID_TIF
    assert "forever" not in _VALID_TIF


# ==================================================================
# CONNECTION HEALTH CHECK TESTS
# ==================================================================


def test_ping_broker_returns_tuple(monkeypatch):
    service = TradingPlatformService()
    service._connected = True
    service._api_key = "test-key"
    service._secret_key = "test-secret"

    import requests as _requests

    class FakeResp:
        status_code = 200
        def json(self):
            return {"status": "ACTIVE"}

    def fake_get(url, headers=None, timeout=None):
        return FakeResp()

    monkeypatch.setattr(_requests, "get", fake_get)
    alive, latency, status = service._ping_broker()
    assert alive is True
    assert latency is not None
    assert status == "ACTIVE"


def test_ping_broker_handles_failure(monkeypatch):
    service = TradingPlatformService()
    service._connected = True
    service._api_key = "test-key"
    service._secret_key = "test-secret"

    import requests as _requests

    def fake_get(url, headers=None, timeout=None):
        raise ConnectionError("unreachable")

    monkeypatch.setattr(_requests, "get", fake_get)
    alive, latency, status = service._ping_broker()
    assert alive is False
    assert latency is not None
    assert "unreachable" in status


def test_connection_status_includes_alive_field(monkeypatch):
    service = TradingPlatformService()
    monkeypatch.setenv("ALPACA_API_KEY", "pk-test")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "sk-test")

    monkeypatch.setattr(service, "_ping_broker", lambda: (True, 42.0, "ACTIVE"))
    status = service.get_connection_status()
    assert status["alive"] is True
    assert status["latency_ms"] == 42.0
    assert status["account_status"] == "ACTIVE"


def test_connection_status_not_connected_skips_ping():
    service = TradingPlatformService()
    service._connected = False
    service._api_key = ""
    service._secret_key = ""
    status = service.get_connection_status()
    assert status["alive"] is False
    assert status["latency_ms"] is None
    assert status["connected"] is False


# ==================================================================
# ENV VAR FALLBACK TESTS
# ==================================================================


def test_reload_keys_uses_api_secret_fallback(monkeypatch):
    service = TradingPlatformService()
    monkeypatch.setenv("ALPACA_API_KEY", "pk-test")
    monkeypatch.setenv("ALPACA_API_SECRET", "sk-test")
    monkeypatch.delenv("ALPACA_SECRET_KEY", raising=False)
    service._reload_keys()
    assert service._secret_key == "sk-test"
    assert service._connected is True


def test_reload_keys_prefers_secret_key_over_api_secret(monkeypatch):
    service = TradingPlatformService()
    monkeypatch.setenv("ALPACA_API_KEY", "pk-test")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "sk-primary")
    monkeypatch.setenv("ALPACA_API_SECRET", "sk-fallback")
    service._reload_keys()
    assert service._secret_key == "sk-primary"


# ==================================================================
# RETRY LOGIC TESTS
# ==================================================================


def test_trade_request_retries_on_connection_error(monkeypatch):
    service = TradingPlatformService()
    service._connected = True
    service._api_key = "test"
    service._secret_key = "test"

    import requests as _requests

    call_count = {"n": 0}

    class FakeResp:
        status_code = 200
        def json(self):
            return {"id": "order-1"}

    def fake_request(method, url, headers=None, json=None, timeout=None):
        call_count["n"] += 1
        if call_count["n"] < 3:
            raise _requests.exceptions.ConnectionError("temp failure")
        return FakeResp()

    monkeypatch.setattr(_requests, "request", fake_request)

    from services import trading_platform_service as mod
    monkeypatch.setattr(mod, "_RETRY_BACKOFF", 0.01)

    result = service._trade_request("POST", "/orders", {"symbol": "AAPL"})
    assert result["id"] == "order-1"
    assert call_count["n"] == 3


def test_trade_request_returns_error_after_max_retries(monkeypatch):
    service = TradingPlatformService()
    service._connected = True
    service._api_key = "test"
    service._secret_key = "test"

    import requests as _requests

    def fake_request(method, url, headers=None, json=None, timeout=None):
        raise _requests.exceptions.ConnectionError("persistent failure")

    monkeypatch.setattr(_requests, "request", fake_request)

    from services import trading_platform_service as mod
    monkeypatch.setattr(mod, "_RETRY_BACKOFF", 0.01)

    result = service._trade_request("GET", "/account")
    assert "error" in result
    assert "persistent failure" in result["error"]


def test_trade_request_surfaces_rate_limit_after_retry_exhaustion(monkeypatch):
    service = TradingPlatformService()
    service._connected = True
    service._api_key = "test"
    service._secret_key = "test"

    import requests as _requests

    class FakeResp:
        status_code = 429
        text = ""
        reason = "Too Many Requests"

    def fake_request(method, url, headers=None, json=None, timeout=None):
        return FakeResp()

    monkeypatch.setattr(_requests, "request", fake_request)

    from services import trading_platform_service as mod
    monkeypatch.setattr(mod, "_RETRY_BACKOFF", 0.01)

    result = service._trade_request("GET", "/account")
    assert result["error"] == "Request failed after 3 attempts: HTTP 429 rate limited"
