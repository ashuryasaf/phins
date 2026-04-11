import sys
import types

import web_portal

from services.trading_platform_service import TradingPlatformService


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


def test_record_trade_to_ledger_skips_when_no_fill_price(monkeypatch):
    """Verify that trades with null filled_avg_price and no broker fill
    are silently skipped rather than recorded with amount=0."""
    service = TradingPlatformService()
    service._connected = True

    captured = {}
    fake_portal = types.ModuleType("web_portal.server")
    fake_portal.TRANSACTION_LEDGER = {}

    def fake_record_transaction(**kwargs):
        captured.update(kwargs)
        return kwargs

    fake_portal.record_transaction = fake_record_transaction
    monkeypatch.setitem(sys.modules, "web_portal.server", fake_portal)
    monkeypatch.setattr(web_portal, "server", fake_portal, raising=False)

    monkeypatch.setattr(service, "_poll_fill_price", lambda order_id: None)

    service._record_trade_to_ledger(
        {
            "order_id": "ord-pending",
            "symbol": "AAPL",
            "side": "buy",
            "qty": "10",
            "filled_avg_price": None,
            "type": "market",
            "status": "accepted",
            "broker": "alpaca",
        },
    )

    assert captured == {}, "No transaction should be recorded when fill price is unavailable"


def test_record_trade_to_ledger_polls_for_fill_price(monkeypatch):
    """Verify that when filled_avg_price is null, the method polls the
    broker and records the correct amount once the fill price arrives."""
    service = TradingPlatformService()
    service._connected = True

    captured = {}
    fake_portal = types.ModuleType("web_portal.server")
    fake_portal.TRANSACTION_LEDGER = {}

    def fake_record_transaction(**kwargs):
        captured.update(kwargs)
        return kwargs

    fake_portal.record_transaction = fake_record_transaction
    monkeypatch.setitem(sys.modules, "web_portal.server", fake_portal)
    monkeypatch.setattr(web_portal, "server", fake_portal, raising=False)

    monkeypatch.setattr(service, "_poll_fill_price", lambda order_id: "200")

    service._record_trade_to_ledger(
        {
            "order_id": "ord-pending",
            "symbol": "AAPL",
            "side": "buy",
            "qty": "10",
            "filled_avg_price": None,
            "type": "market",
            "status": "accepted",
            "broker": "alpaca",
        },
    )

    assert captured["amount"] == 2000
    assert captured["metadata"]["price"] == "200"


def test_record_trade_sell_no_fill_price_skips_negative_gain(monkeypatch):
    """The original bug: selling with null fill price produced
    realized_gain = -cost_basis. Verify this no longer happens."""
    service = TradingPlatformService()
    service._connected = True

    captured = {}
    fake_portal = types.ModuleType("web_portal.server")
    fake_portal.TRANSACTION_LEDGER = {}

    def fake_record_transaction(**kwargs):
        captured.update(kwargs)
        return kwargs

    fake_portal.record_transaction = fake_record_transaction
    monkeypatch.setitem(sys.modules, "web_portal.server", fake_portal)
    monkeypatch.setattr(web_portal, "server", fake_portal, raising=False)

    monkeypatch.setattr(service, "_poll_fill_price", lambda order_id: None)

    service._record_trade_to_ledger(
        {
            "order_id": "ord-sell",
            "symbol": "AAPL",
            "side": "sell",
            "qty": "10",
            "filled_avg_price": None,
            "type": "market",
            "status": "accepted",
            "broker": "alpaca",
        },
        position_snapshot={
            "symbol": "AAPL",
            "qty": 10,
            "avg_entry_price": 180,
            "cost_basis": 1800,
        },
    )

    assert captured == {}, "Sell with no fill price must not produce a negative realized_gain entry"


def test_record_trade_sell_polls_and_records_correct_gain(monkeypatch):
    """Sell order with null initial fill price should poll and record
    the correct realized_gain once the fill price is available."""
    service = TradingPlatformService()
    service._connected = True

    captured = {}
    fake_portal = types.ModuleType("web_portal.server")
    fake_portal.TRANSACTION_LEDGER = {}

    def fake_record_transaction(**kwargs):
        captured.update(kwargs)
        return kwargs

    fake_portal.record_transaction = fake_record_transaction
    monkeypatch.setitem(sys.modules, "web_portal.server", fake_portal)
    monkeypatch.setattr(web_portal, "server", fake_portal, raising=False)

    monkeypatch.setattr(service, "_poll_fill_price", lambda order_id: "200")

    service._record_trade_to_ledger(
        {
            "order_id": "ord-sell",
            "symbol": "AAPL",
            "side": "sell",
            "qty": "10",
            "filled_avg_price": None,
            "type": "market",
            "status": "accepted",
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
    assert captured["metadata"]["realized_gain"] == 200
    assert captured["metadata"]["estimated_cost_basis"] == 1800


def test_poll_fill_price_returns_price_on_fill(monkeypatch):
    """_poll_fill_price returns the filled price when the order fills."""
    service = TradingPlatformService()
    service._connected = True
    service._FILL_POLL_INTERVAL = 0.01
    service._FILL_POLL_MAX_WAIT = 0.1

    call_count = {"n": 0}

    def fake_trade_request(method, path, body=None):
        call_count["n"] += 1
        if call_count["n"] < 3:
            return {"id": "ord-1", "status": "accepted", "filled_avg_price": None}
        return {"id": "ord-1", "status": "filled", "filled_avg_price": "150.50"}

    monkeypatch.setattr(service, "_trade_request", fake_trade_request)

    result = service._poll_fill_price("ord-1")
    assert result == "150.50"
    assert call_count["n"] >= 3


def test_poll_fill_price_returns_none_on_cancel(monkeypatch):
    """_poll_fill_price returns None when the order is canceled."""
    service = TradingPlatformService()
    service._connected = True
    service._FILL_POLL_INTERVAL = 0.01
    service._FILL_POLL_MAX_WAIT = 0.1

    def fake_trade_request(method, path, body=None):
        return {"id": "ord-1", "status": "canceled", "filled_avg_price": None}

    monkeypatch.setattr(service, "_trade_request", fake_trade_request)

    result = service._poll_fill_price("ord-1")
    assert result is None


def test_poll_fill_price_returns_none_on_timeout(monkeypatch):
    """_poll_fill_price returns None when the order never fills."""
    service = TradingPlatformService()
    service._connected = True
    service._FILL_POLL_INTERVAL = 0.01
    service._FILL_POLL_MAX_WAIT = 0.05

    def fake_trade_request(method, path, body=None):
        return {"id": "ord-1", "status": "accepted", "filled_avg_price": None}

    monkeypatch.setattr(service, "_trade_request", fake_trade_request)

    result = service._poll_fill_price("ord-1")
    assert result is None


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


def test_close_position_passes_order_id_to_ledger(monkeypatch):
    service = TradingPlatformService()
    service._connected = True

    recorded = {}

    def fake_get_position_snapshot(symbol):
        assert symbol == "AAPL"
        return {"symbol": "AAPL", "qty": 5, "avg_entry_price": 180, "cost_basis": 900}

    def fake_trade_request(method, path, body=None):
        assert method == "DELETE"
        assert path == "/positions/AAPL"
        return {
            "id": "ord-close",
            "symbol": "AAPL",
            "side": "sell",
            "qty": "5",
            "status": "accepted",
            "filled_avg_price": None,
        }

    def fake_record_trade(order_result, customer_id="TERMINAL", position_snapshot=None):
        recorded["order_result"] = order_result
        recorded["position_snapshot"] = position_snapshot

    monkeypatch.setattr(service, "_get_position_snapshot", fake_get_position_snapshot)
    monkeypatch.setattr(service, "_trade_request", fake_trade_request)
    monkeypatch.setattr(service, "_record_trade_to_ledger", fake_record_trade)

    result = service.close_position("AAPL")

    assert result["id"] == "ord-close"
    assert recorded["order_result"]["order_id"] == "ord-close"
    assert recorded["order_result"]["filled_avg_price"] is None
    assert recorded["order_result"]["qty"] == "5"
    assert recorded["position_snapshot"]["cost_basis"] == 900
