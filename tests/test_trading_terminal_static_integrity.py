from pathlib import Path


TRADING_TERMINAL_PATH = Path(__file__).resolve().parents[1] / "web_portal" / "static" / "trading-terminal.html"


def test_order_debounce_starts_when_order_is_confirmed():
    content = TRADING_TERMINAL_PATH.read_text(encoding="utf-8")

    assert "if (!confirm(confirmMsg)) return;\n    lastOrderNonce = Date.now();" in content
    assert "lastOrderNonce = now;" not in content


def test_copilot_risk_metrics_use_backend_keys_without_double_scaling():
    content = TRADING_TERMINAL_PATH.read_text(encoding="utf-8")

    assert "rm.volatility_annual" in content
    assert "rm.sharpe_ratio" in content
    assert "(rm.volatility*100)" not in content
    assert "(rm.var_95*100)" not in content
    assert "(rm.max_drawdown*100)" not in content


def test_sector_heatmap_iterates_sector_object_entries():
    content = TRADING_TERMINAL_PATH.read_text(encoding="utf-8")

    assert "Object.entries(d.sectors || {}).forEach(([name, s]) => {" in content
    assert "(d.sectors || []).forEach" not in content


# --- B12 safety controls surfaced on the AutoPilot tab -----------------------

def test_autopilot_tab_has_kill_switch_controls():
    content = TRADING_TERMINAL_PATH.read_text(encoding="utf-8")

    assert 'id="apHaltBtn"' in content and 'onclick="toggleTradingHalt()"' in content
    assert 'id="apHaltBanner"' in content
    assert "apiFetch('/api/terminal/autopilot/halt')" in content
    assert "apiPost('/api/terminal/autopilot/halt'" in content
    assert "apiPost('/api/terminal/autopilot/resume'" in content
    # loadBots refreshes the halt state so the banner is never stale
    assert "loadHaltStatus();" in content


def test_autopilot_env_halt_cannot_be_resumed_from_ui():
    content = TRADING_TERMINAL_PATH.read_text(encoding="utf-8")

    assert "btn.disabled = h.source === 'env';" in content
    assert "'HALTED (ENV)'" in content


def test_autopilot_halt_reason_and_actor_are_escaped():
    content = TRADING_TERMINAL_PATH.read_text(encoding="utf-8")

    assert "apEscape(h.reason || '')" in content
    assert "apEscape(h.actor)" in content
    assert "apEscape(b.strategy_version" in content


def test_autopilot_backtest_is_a_read_only_replay():
    content = TRADING_TERMINAL_PATH.read_text(encoding="utf-8")

    assert 'id="apBtMode"' in content
    assert 'id="apBtPrincipal"' in content
    assert 'id="apBtDailyRisk"' in content
    assert 'id="apBtFocus"' in content
    assert 'value="hedged"' in content
    assert "daily_risk_pct" in content
    assert 'value="replay"' in content and "Replay (recommended)" in content
    assert 'value="next_open"' in content
    assert "runAutoPilotBacktest" in content
    assert "/api/terminal/backtest" in content
    assert "No orders are sent." in content


def test_autopilot_table_shows_mode_and_execute_is_gated_by_halt():
    content = TRADING_TERMINAL_PATH.read_text(encoding="utf-8")

    assert "<th>Mode</th>" in content
    assert "b.mode === 'shadow'" in content
    assert "if (apHalted) { showToast('Trading is halted. Resume before executing.', 'error'); return; }" in content
