from pathlib import Path


TRADING_TERMINAL_PATH = Path(__file__).resolve().parents[1] / "web_portal" / "static" / "trading-terminal.html"


def test_order_debounce_starts_when_order_is_confirmed():
    content = TRADING_TERMINAL_PATH.read_text(encoding="utf-8")

    assert "if (!confirm(confirmMsg)) return;\n    lastOrderNonce = Date.now();" in content
    assert "lastOrderNonce = now;" not in content
