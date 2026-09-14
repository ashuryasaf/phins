"""
B12 safety controls for the AutoPilot engine: kill switch, daily loss caps,
shadow/paper mode via strategy-version promotion, and fail-closed audit on
the execution path.

The strategy layer is bypassed (``evaluate_bot`` is stubbed) so each test
drives a known set of intended actions through the gates that sit between
"strategy says buy" and ``trading_platform.submit_order``.
"""

import pytest

import services.ai_audit_bridge as bridge
import services.ai_trading_engine as engine_mod
from services.ai_trading_engine import (
    AutoPilotEngine,
    DEFAULT_STRATEGY_VERSION,
    audit_required,
)


class FakePlatform:
    """Minimal broker double. ``is_connected`` mirrors the real platform's
    property so the ``auto`` audit policy can be exercised both ways."""

    def __init__(self, connected=False, portfolio_value=100_000.0, on_submit=None):
        self.is_connected = connected
        self.portfolio_value = portfolio_value
        self.orders = []
        self._on_submit = on_submit

    def get_account(self):
        return {"portfolio_value": self.portfolio_value, "equity": self.portfolio_value,
                "buying_power": self.portfolio_value}

    def get_positions(self):
        return []

    def submit_order(self, **kwargs):
        self.orders.append(kwargs)
        if self._on_submit:
            self._on_submit(self, kwargs)
        return {"id": f"ord-{len(self.orders)}", "status": "accepted"}


def _stub_signals(engine, actions):
    """Make every evaluation return ``actions`` for AAPL."""
    def fake_eval(bot_id, bars_by_symbol=None):
        return {"bot_id": bot_id, "strategy": "momentum",
                "signals": {"AAPL": {"actions": [dict(a) for a in actions], "analysis": "stub"}}}
    engine.evaluate_bot = fake_eval


BUY = {"side": "buy", "qty": 10, "price": 100.0, "reason": "test", "confidence": 0.9}


@pytest.fixture
def audit_calls(monkeypatch):
    """Capture audit rows; persist succeeds unless the test flips ``ok``."""
    state = {"ok": True, "calls": []}

    def fake_record(**kwargs):
        state["calls"].append(kwargs)
        return state["ok"]

    monkeypatch.setattr(bridge, 'record_ai_audit', fake_record)
    return state


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in (engine_mod.TRADING_HALT_ENV, engine_mod.AUDIT_REQUIRED_ENV,
                 engine_mod.GLOBAL_DAILY_LOSS_PCT_ENV, engine_mod.GLOBAL_DAILY_LOSS_ABS_ENV):
        monkeypatch.delenv(name, raising=False)


def _make_engine_with_bot(actions=(BUY,), config=None):
    engine = AutoPilotEngine()
    created = engine.create_bot("momentum", ["AAPL"], config or {})
    _stub_signals(engine, list(actions))
    return engine, created["id"]


# --------------------------------------------------------------------------
# Baseline: a promoted, unhalted bot still submits exactly as before
# --------------------------------------------------------------------------

def test_live_bot_submits_and_records_audit_parity(audit_calls):
    engine, bot_id = _make_engine_with_bot()
    platform = FakePlatform()
    result = engine.execute_bot_trades(bot_id, platform)

    assert len(platform.orders) == 1
    assert platform.orders[0]["symbol"] == "AAPL" and platform.orders[0]["side"] == "buy"
    assert len(result) == 1
    rec = result[0]
    assert rec["mode"] == "live"
    assert rec["strategy_version"] == DEFAULT_STRATEGY_VERSION
    assert rec["audit_persisted"] is True
    assert "error" not in rec
    # intent row before submission, executed row after
    assert [c["action"] for c in audit_calls["calls"]] == ['ai_bot_trade_intent', 'ai_bot_trade_executed']
    assert audit_calls["calls"][0]["details"]["phase"] == "intent"
    bots = engine.get_bots()[0]
    assert bots["trade_count"] == 1 and bots["shadow_trade_count"] == 0 and bots["mode"] == "live"
    # exits still match the executed entry
    exit_res = engine.record_trade_exit(bot_id, "AAPL", 110.0, 10)
    assert exit_res["pnl"] == 100.0


# --------------------------------------------------------------------------
# Kill switch
# --------------------------------------------------------------------------

def test_env_halt_blocks_execution_before_any_broker_call(monkeypatch, audit_calls):
    engine, bot_id = _make_engine_with_bot()
    monkeypatch.setenv(engine_mod.TRADING_HALT_ENV, "true")
    platform = FakePlatform()

    result = engine.execute_bot_trades(bot_id, platform)

    assert platform.orders == []
    assert result == [{"error": "Trading halted", "halted": True, "blocked": True,
                       "reason": f"{engine_mod.TRADING_HALT_ENV} is set", "source": "env"}]
    assert engine.get_bots()[0]["blocked_count"] == 1
    assert engine.get_bots()[0]["trade_count"] == 0
    assert audit_calls["calls"] == []  # nothing to audit: no intent was formed


def test_runtime_halt_and_resume(audit_calls):
    engine, bot_id = _make_engine_with_bot()
    platform = FakePlatform()

    status = engine.halt_trading("ops drill", actor="admin:alice")
    assert status["halted"] is True and status["source"] == "runtime"
    assert status["reason"] == "ops drill" and status["actor"] == "admin:alice"
    assert status["at"]

    result = engine.execute_bot_trades(bot_id, platform)
    assert platform.orders == []
    assert result[0]["halted"] is True and result[0]["source"] == "runtime"

    status = engine.resume_trading(actor="admin:alice")
    assert status["halted"] is False and status["source"] is None
    assert engine.execute_bot_trades(bot_id, platform)[0].get("error") is None
    assert len(platform.orders) == 1

    actions = [c["action"] for c in audit_calls["calls"]]
    assert actions[:2] == ['ai_trading_halted', 'ai_trading_resumed']
    assert audit_calls["calls"][0]["entity_type"] == "trading_control"


def test_env_halt_cannot_be_lifted_via_resume(monkeypatch, audit_calls):
    engine, bot_id = _make_engine_with_bot()
    engine.halt_trading("x")
    monkeypatch.setenv(engine_mod.TRADING_HALT_ENV, "1")
    status = engine.resume_trading()
    assert status["runtime_flag"] is False
    assert status["halted"] is True and status["source"] == "env"
    assert "note" in status
    assert engine.execute_bot_trades(bot_id, FakePlatform())[0]["halted"] is True


def test_halt_tripped_mid_run_stops_remaining_orders(audit_calls):
    engine, bot_id = _make_engine_with_bot(actions=[BUY, {**BUY, "qty": 5}])

    def trip(platform, order):
        engine.halt_trading("circuit breaker")

    platform = FakePlatform(on_submit=trip)
    result = engine.execute_bot_trades(bot_id, platform)

    assert len(platform.orders) == 1          # first went out, second stopped
    assert len(result) == 2
    assert "error" not in result[0]
    assert result[1]["halted"] is True and result[1]["blocked"] is True
    assert engine.get_bots()[0]["trade_count"] == 1


def test_health_probe_reports_halt(monkeypatch, audit_calls):
    import sys
    import types
    engine = AutoPilotEngine()
    fake_platform_mod = types.SimpleNamespace(_autopilot_engine=engine)
    monkeypatch.setitem(sys.modules, 'services.trading_platform_service', fake_platform_mod)
    assert engine_mod._trading_engine_health()["halted"] is False
    engine.halt_trading("probe")
    probe = engine_mod._trading_engine_health()
    assert probe["halted"] is True and probe["halt_source"] == "runtime"
    assert probe["status"] == "degraded"


# --------------------------------------------------------------------------
# Daily loss caps
# --------------------------------------------------------------------------

def test_bot_daily_loss_cap_blocks_at_threshold_and_logs(audit_calls):
    engine, bot_id = _make_engine_with_bot()
    platform = FakePlatform(portfolio_value=100_000)
    # default max_daily_loss = 2% -> cap is -2000
    engine._bots[bot_id]["daily_pnl"] = -2000.0
    assert "error" not in engine.execute_bot_trades(bot_id, platform)[0]  # at the cap: still allowed
    engine._bots[bot_id]["daily_pnl"] = -2000.01
    result = engine.execute_bot_trades(bot_id, platform)

    assert len(platform.orders) == 1  # only the first run submitted
    assert result[0]["error"] == "Daily loss limit reached"
    assert result[0]["reason"] == "bot_daily_loss_cap" and result[0]["cap"] == -2000.0
    blocked = [c for c in audit_calls["calls"] if c["action"] == 'ai_bot_trade_blocked']
    assert len(blocked) == 1 and blocked[0]["details"]["reason"] == "bot_daily_loss_cap"
    assert engine.get_bot_performance(bot_id)["last_block"]["reason"] == "bot_daily_loss_cap"


def test_global_daily_loss_cap_across_bots(monkeypatch, audit_calls):
    engine = AutoPilotEngine()
    a = engine.create_bot("momentum", ["AAPL"], {})["id"]
    b = engine.create_bot("breakout", ["AAPL"], {})["id"]
    _stub_signals(engine, [BUY])
    platform = FakePlatform(portfolio_value=100_000)
    # each bot is inside its own 2% cap, together they breach a 3000 global cap
    engine._bots[a]["daily_pnl"] = -1900.0
    engine._bots[b]["daily_pnl"] = -1900.0
    monkeypatch.setenv(engine_mod.GLOBAL_DAILY_LOSS_ABS_ENV, "3000")

    result = engine.execute_bot_trades(a, platform)
    assert platform.orders == []
    assert result[0]["reason"] == "global_daily_loss_cap"
    assert result[0]["global_daily_pnl"] == -3800.0 and result[0]["cap"] == -3000.0


def test_global_pct_cap_defaults_to_five_percent(audit_calls):
    engine = AutoPilotEngine()
    a = engine.create_bot("momentum", ["AAPL"], {"max_daily_loss": 0.10})["id"]
    _stub_signals(engine, [BUY])
    engine._bots[a]["daily_pnl"] = -5000.01  # within bot cap (10%), beyond global 5%
    result = engine.execute_bot_trades(a, FakePlatform(portfolio_value=100_000))
    assert result[0]["reason"] == "global_daily_loss_cap"


def test_daily_pnl_rolls_over_on_utc_day_change(audit_calls):
    engine, bot_id = _make_engine_with_bot()
    engine._bots[bot_id]["daily_pnl"] = -50_000.0
    engine._bots[bot_id]["pnl_day"] = "2000-01-01"
    platform = FakePlatform()
    result = engine.execute_bot_trades(bot_id, platform)
    assert "error" not in result[0]
    assert len(platform.orders) == 1
    assert engine.get_bots()[0]["daily_pnl"] == 0.0
    assert engine._bots[bot_id]["pnl_day"] == AutoPilotEngine._today()


def test_reset_daily_pnl_stamps_day(audit_calls):
    engine, bot_id = _make_engine_with_bot()
    engine._bots[bot_id]["daily_pnl"] = -1.0
    engine._bots[bot_id]["pnl_day"] = "2000-01-01"
    engine.reset_daily_pnl()
    assert engine._bots[bot_id]["daily_pnl"] == 0.0
    assert engine._bots[bot_id]["pnl_day"] == AutoPilotEngine._today()


# --------------------------------------------------------------------------
# Shadow / paper mode
# --------------------------------------------------------------------------

def test_unpromoted_strategy_version_runs_in_shadow_and_never_submits(audit_calls):
    engine, bot_id = _make_engine_with_bot(config={"strategy_version": "2.0-beta"})
    assert engine.get_bots()[0]["mode"] == "shadow"
    platform = FakePlatform(connected=True)

    result = engine.execute_bot_trades(bot_id, platform)

    assert platform.orders == []
    assert len(result) == 1
    rec = result[0]
    assert rec["shadow"] is True and rec["mode"] == "shadow"
    assert rec["order_result"] == {"shadow": True, "submitted": False}
    assert rec["strategy_version"] == "2.0-beta"
    bot = engine.get_bots()[0]
    assert bot["trade_count"] == 0 and bot["shadow_trade_count"] == 1
    assert [c["action"] for c in audit_calls["calls"]] == ['ai_bot_trade_shadow']
    # shadow intents are not open entries
    assert "error" in engine.record_trade_exit(bot_id, "AAPL", 110.0, 10)
    perf = engine.get_bot_performance(bot_id)
    assert perf["mode"] == "shadow" and perf["recent_shadow_trades"][0]["symbol"] == "AAPL"


def test_promotion_moves_bot_to_live_on_next_execution(audit_calls):
    engine, bot_id = _make_engine_with_bot(config={"strategy_version": "2.0"})
    platform = FakePlatform()
    engine.execute_bot_trades(bot_id, platform)
    assert platform.orders == []

    assert "error" in engine.promote_strategy_version("nope", "2.0")
    assert "error" in engine.promote_strategy_version("momentum", "")
    promoted = engine.promote_strategy_version("momentum", "2.0", actor="admin:bob")
    assert promoted["promoted_versions"] == [DEFAULT_STRATEGY_VERSION, "2.0"]
    assert engine.promoted_versions()["momentum"] == [DEFAULT_STRATEGY_VERSION, "2.0"]
    assert engine.get_bots()[0]["mode"] == "live"

    engine.execute_bot_trades(bot_id, platform)
    assert len(platform.orders) == 1
    assert any(c["action"] == 'ai_trading_strategy_promoted' for c in audit_calls["calls"])


def test_explicit_shadow_config_wins_over_promotion(audit_calls):
    engine, bot_id = _make_engine_with_bot(config={"shadow": True})
    assert engine.get_bots()[0]["mode"] == "shadow"
    platform = FakePlatform()
    result = engine.execute_bot_trades(bot_id, platform)
    assert platform.orders == [] and result[0]["shadow"] is True


def test_shadow_retention_is_bounded(audit_calls):
    engine, bot_id = _make_engine_with_bot(config={"shadow": True})
    platform = FakePlatform()
    for _ in range(engine_mod._SHADOW_TRADE_RETENTION + 20):
        engine.execute_bot_trades(bot_id, platform)
    assert len(engine._bots[bot_id]["shadow_trades"]) == engine_mod._SHADOW_TRADE_RETENTION


# --------------------------------------------------------------------------
# Fail-closed audit on the execution path
# --------------------------------------------------------------------------

def test_audit_required_policy(monkeypatch):
    assert audit_required(FakePlatform(connected=True)) is True
    assert audit_required(FakePlatform(connected=False)) is False
    assert audit_required(object()) is False
    monkeypatch.setenv(engine_mod.AUDIT_REQUIRED_ENV, "true")
    assert audit_required(FakePlatform(connected=False)) is True
    monkeypatch.setenv(engine_mod.AUDIT_REQUIRED_ENV, "false")
    assert audit_required(FakePlatform(connected=True)) is False


def test_connected_broker_with_unavailable_audit_submits_nothing(audit_calls):
    audit_calls["ok"] = False
    engine, bot_id = _make_engine_with_bot(actions=[BUY, {**BUY, "qty": 5}])
    platform = FakePlatform(connected=True)

    result = engine.execute_bot_trades(bot_id, platform)

    assert platform.orders == []
    assert len(result) == 1  # stopped after the first blocked intent
    assert result[0]["blocked"] is True and result[0]["reason"] == "audit_unavailable"
    assert result[0]["error"] == "Audit store unavailable; order not submitted"
    assert engine.get_bots()[0]["trade_count"] == 0
    assert engine.halt_status()["audit_degraded_at"] is not None
    # the failed intent write was attempted exactly once
    assert [c["action"] for c in audit_calls["calls"]] == ['ai_bot_trade_intent']


def test_audit_persister_raising_is_treated_as_unavailable(monkeypatch):
    def boom(**kwargs):
        raise RuntimeError("db down")
    monkeypatch.setattr(bridge, 'record_ai_audit', boom)
    engine, bot_id = _make_engine_with_bot()
    platform = FakePlatform(connected=True)
    result = engine.execute_bot_trades(bot_id, platform)
    assert platform.orders == []
    assert result[0]["reason"] == "audit_unavailable"


def test_demo_platform_keeps_best_effort_audit(audit_calls):
    """Unconnected (simulated) platform: no money moves, so a missing audit
    store does not block — the historical behaviour is preserved."""
    audit_calls["ok"] = False
    engine, bot_id = _make_engine_with_bot()
    platform = FakePlatform(connected=False)
    result = engine.execute_bot_trades(bot_id, platform)
    assert len(platform.orders) == 1
    assert result[0]["audit_persisted"] is False
    assert engine.halt_status()["audit_degraded_at"] is None


def test_audit_required_env_false_disables_fail_closed(monkeypatch, audit_calls):
    audit_calls["ok"] = False
    monkeypatch.setenv(engine_mod.AUDIT_REQUIRED_ENV, "false")
    engine, bot_id = _make_engine_with_bot()
    platform = FakePlatform(connected=True)
    assert "error" not in engine.execute_bot_trades(bot_id, platform)[0]
    assert len(platform.orders) == 1


def test_audit_required_env_true_forces_fail_closed_on_demo(monkeypatch, audit_calls):
    audit_calls["ok"] = False
    monkeypatch.setenv(engine_mod.AUDIT_REQUIRED_ENV, "true")
    engine, bot_id = _make_engine_with_bot()
    platform = FakePlatform(connected=False)
    result = engine.execute_bot_trades(bot_id, platform)
    assert platform.orders == [] and result[0]["reason"] == "audit_unavailable"


def test_audit_helper_returns_persisted_flag_and_never_raises(monkeypatch):
    monkeypatch.setattr(bridge, 'record_ai_audit', lambda **kw: True)
    assert engine_mod._audit_bot_trade({'bot_id': 'B'}) is True
    monkeypatch.setattr(bridge, 'record_ai_audit', lambda **kw: False)
    assert engine_mod._audit_bot_trade({'bot_id': 'B'}, required=True) is False
    monkeypatch.setattr(bridge, 'record_ai_audit',
                        lambda **kw: (_ for _ in ()).throw(RuntimeError("x")))
    assert engine_mod._audit_bot_trade({'bot_id': 'B'}, required=True) is False
