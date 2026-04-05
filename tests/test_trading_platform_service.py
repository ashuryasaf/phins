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
