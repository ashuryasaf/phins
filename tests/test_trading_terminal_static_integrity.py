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
