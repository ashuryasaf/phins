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


def test_ai_copilot_analyze_uses_atr_for_trade_levels(monkeypatch):
    service = TradingPlatformService()

    import services.ai_trading_engine as ai_trading_engine

    monkeypatch.setattr(
        service,
        "get_bars",
        lambda symbol, timeframe="1Day", limit=100: [
            {"close": 99.0},
            {"close": 100.0},
        ],
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
    assert result["data_source"] == "alpaca_live"
    assert result["last_close"] == 100.0
    assert result["price"] == 100.0


def test_ai_copilot_analyze_prefers_live_trade_over_stale_daily_close(monkeypatch):
    """The displayed price must reflect the latest live trade, not the
    previous daily bar's close. This regression covers the QBTS report
    where ANALYZE showed yesterday's $21 close while the symbol was
    actively trading near $31."""
    service = TradingPlatformService()
    service._connected = True

    import services.ai_trading_engine as ai_trading_engine

    monkeypatch.setattr(
        service,
        "get_bars",
        lambda symbol, timeframe="1Day", limit=100: [
            {"close": 19.0},
            {"close": 21.0},
        ],
    )
    monkeypatch.setattr(service, "get_positions", lambda: [])
    monkeypatch.setattr(
        service,
        "get_account",
        lambda: {"buying_power": 10000, "portfolio_value": 10000},
    )
    monkeypatch.setattr(
        service,
        "get_latest_trade",
        lambda symbol: {
            "symbol": symbol,
            "price": 31.0,
            "size": 100,
            "timestamp": "2026-05-22T15:30:00Z",
            "exchange": "V",
        },
    )
    # Should not be reached because get_latest_trade succeeds.
    def _fail_latest_bar(symbol):
        raise AssertionError("get_stock_latest_bar should not run when trade is fresh")
    monkeypatch.setattr(service, "get_stock_latest_bar", _fail_latest_bar)
    monkeypatch.setattr(
        ai_trading_engine,
        "compute_technicals",
        lambda bars: {"indicators": {"atr_14": 1.0}},
    )
    captured = {}
    def _capture_signals(technicals, price):
        captured["price"] = price
        return {"recommendation": "BUY", "composite_score": 2, "confidence": 0.6, "details": []}
    monkeypatch.setattr(ai_trading_engine, "generate_signals", _capture_signals)
    monkeypatch.setattr(ai_trading_engine, "compute_risk_metrics", lambda bars, positions: {})

    result = service.ai_copilot_analyze("QBTS")

    assert result["price"] == 31.0
    assert result["last_close"] == 21.0
    assert result["quote_source"] == "alpaca_latest_trade"
    assert result["live_quote_at"] == "2026-05-22T15:30:00Z"
    # Stop/take-profit math must follow the live price, not the stale close.
    assert result["trade_suggestion"]["stop_loss"] == 29.0
    assert result["trade_suggestion"]["take_profit"] == 34.0
    # Signals must also see the live price so RSI/MACD comparisons line up.
    assert captured["price"] == 31.0


def test_ai_copilot_analyze_falls_back_to_latest_bar_when_no_trade(monkeypatch):
    """When IEX has no recent trade, fall back to the latest intraday bar
    instead of the stale daily close."""
    service = TradingPlatformService()
    service._connected = True

    import services.ai_trading_engine as ai_trading_engine

    monkeypatch.setattr(
        service,
        "get_bars",
        lambda symbol, timeframe="1Day", limit=100: [
            {"close": 19.0},
            {"close": 21.0},
        ],
    )
    monkeypatch.setattr(service, "get_positions", lambda: [])
    monkeypatch.setattr(
        service,
        "get_account",
        lambda: {"buying_power": 10000, "portfolio_value": 10000},
    )
    monkeypatch.setattr(service, "get_latest_trade", lambda symbol: None)
    monkeypatch.setattr(
        service,
        "get_stock_latest_bar",
        lambda symbol: {"bar": {"c": 30.5, "t": "2026-05-22T15:25:00Z"}, "symbol": symbol},
    )
    monkeypatch.setattr(
        ai_trading_engine,
        "compute_technicals",
        lambda bars: {"indicators": {"atr_14": 1.0}},
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

    result = service.ai_copilot_analyze("QBTS")

    assert result["price"] == 30.5
    assert result["last_close"] == 21.0
    assert result["quote_source"] == "alpaca_latest_bar"


def test_ai_copilot_analyze_keeps_last_close_when_live_quote_unavailable(monkeypatch):
    """If both live-quote endpoints fail/return invalid data, fall back to
    the daily close so the analysis still runs (existing behavior)."""
    service = TradingPlatformService()
    service._connected = True

    import services.ai_trading_engine as ai_trading_engine

    monkeypatch.setattr(
        service,
        "get_bars",
        lambda symbol, timeframe="1Day", limit=100: [
            {"close": 19.0},
            {"close": 21.0},
        ],
    )
    monkeypatch.setattr(service, "get_positions", lambda: [])
    monkeypatch.setattr(
        service,
        "get_account",
        lambda: {"buying_power": 10000, "portfolio_value": 10000},
    )
    monkeypatch.setattr(service, "get_latest_trade", lambda symbol: None)
    monkeypatch.setattr(service, "get_stock_latest_bar", lambda symbol: None)
    monkeypatch.setattr(
        ai_trading_engine,
        "compute_technicals",
        lambda bars: {"indicators": {"atr_14": 1.0}},
    )
    monkeypatch.setattr(
        ai_trading_engine,
        "generate_signals",
        lambda technicals, price: {
            "recommendation": "HOLD",
            "composite_score": 0,
            "confidence": 0.4,
            "details": [],
        },
    )
    monkeypatch.setattr(ai_trading_engine, "compute_risk_metrics", lambda bars, positions: {})

    result = service.ai_copilot_analyze("QBTS")

    assert result["price"] == 21.0
    assert result["last_close"] == 21.0
    assert result["quote_source"] == "alpaca_live"


def test_ai_copilot_analyze_falls_back_to_alpha_vantage(monkeypatch):
    """When Alpaca returns no bars, copilot must transparently fall back
    to Alpha Vantage daily bars and still produce a real analysis."""
    service = TradingPlatformService()

    import services.ai_trading_engine as ai_trading_engine
    import services.alpha_vantage_service as alpha_vantage_service

    monkeypatch.setattr(
        service,
        "get_bars",
        lambda symbol, timeframe="1Day", limit=100: [],
    )
    monkeypatch.setattr(service, "get_positions", lambda: [])
    monkeypatch.setattr(
        service,
        "get_account",
        lambda: {"buying_power": 10000, "portfolio_value": 10000},
    )

    class _FakeAV:
        def get_daily(self, symbol, outputsize="compact"):
            assert symbol == "NVDA"
            return {
                "symbol": symbol,
                "series_type": "daily",
                "bars": [
                    {"date": "2026-05-09", "open": 122.0, "high": 126.0,
                     "low": 121.0, "close": 125.0, "volume": 1000},
                    {"date": "2026-05-08", "open": 119.0, "high": 121.0,
                     "low": 118.0, "close": 120.0, "volume": 900},
                    {"date": "2026-05-07", "open": 117.0, "high": 119.5,
                     "low": 116.5, "close": 118.0, "volume": 800},
                ],
                "bar_count": 3,
                "latest_price": 125.0,
                "source": "alpha_vantage",
            }

    monkeypatch.setattr(
        alpha_vantage_service,
        "get_alpha_vantage_service",
        lambda: _FakeAV(),
    )
    monkeypatch.setattr(
        ai_trading_engine,
        "compute_technicals",
        lambda bars: {"indicators": {"atr_14": 2.0}},
    )
    monkeypatch.setattr(
        ai_trading_engine,
        "generate_signals",
        lambda technicals, price: {
            "recommendation": "BUY",
            "composite_score": 2,
            "confidence": 0.55,
            "details": [],
        },
    )
    monkeypatch.setattr(
        ai_trading_engine,
        "compute_risk_metrics",
        lambda bars, positions: {},
    )

    result = service.ai_copilot_analyze("NVDA")

    assert "error" not in result
    assert result["symbol"] == "NVDA"
    assert result["data_source"] == "alpha_vantage_fallback"
    assert result["bars_count"] == 3
    # Bars must be reordered ascending by date so the latest close (125.0)
    # is what feeds `price` and the trade suggestion math.
    assert result["price"] == 125.0
    assert result["last_close"] == 125.0
    # No Alpaca connection in this test, so live-quote lookup is skipped
    # and the fallback source is preserved.
    assert result["quote_source"] == "alpha_vantage_fallback"
    assert result["trade_suggestion"]["stop_loss"] == 121.0
    assert result["trade_suggestion"]["take_profit"] == 131.0


def test_ai_copilot_analyze_returns_error_when_no_data_anywhere(monkeypatch):
    """Both Alpaca and Alpha Vantage empty -> structured error, no mock data."""
    service = TradingPlatformService()
    import services.alpha_vantage_service as alpha_vantage_service

    monkeypatch.setattr(
        service,
        "get_bars",
        lambda symbol, timeframe="1Day", limit=100: [],
    )

    class _EmptyAV:
        def get_daily(self, symbol, outputsize="compact"):
            return None

    monkeypatch.setattr(
        alpha_vantage_service,
        "get_alpha_vantage_service",
        lambda: _EmptyAV(),
    )

    result = service.ai_copilot_analyze("ZZZZ")
    assert "error" in result
    assert result["symbol"] == "ZZZZ"
    assert result["data_source"] == "none"
    assert "ALPACA_API_KEY" in result["error"]
    assert "ALPHA_VANTAGE_API_KEY" in result["error"]


def test_ai_copilot_analyze_rejects_empty_symbol():
    service = TradingPlatformService()
    result = service.ai_copilot_analyze("   ")
    assert "error" in result
    assert "Symbol is required" in result["error"]


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
