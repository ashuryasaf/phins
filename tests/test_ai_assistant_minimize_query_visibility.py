from pathlib import Path


STATIC_DIR = Path(__file__).resolve().parents[1] / "web_portal" / "static"
DASHBOARD_PATH = STATIC_DIR / "dashboard.html"
ADMIN_DASHBOARD_PATH = STATIC_DIR / "admin.html"


def test_customer_assistant_minimize_keeps_query_input_available():
    content = DASHBOARD_PATH.read_text(encoding="utf-8")

    assert 'id="ai-panel-minimize-btn"' in content
    assert 'id="ai-query-row"' in content
    assert '#ai-assistant-panel[data-minimized="true"] #ai-help-panel' in content
    assert '#ai-assistant-panel[data-minimized="true"] #voice-recording-indicator' in content
    assert '#ai-assistant-panel[data-minimized="true"] #ai-quick-actions' in content
    assert '#ai-assistant-panel[data-minimized="true"] #ai-response-area' in content
    assert '#ai-assistant-panel[data-minimized="true"] #ai-query-row' in content
    assert "function toggleAIPanel()" in content
    assert "toggleButton.textContent = '🎤➕';" in content
    assert "toggleButton.textContent = '➖';" in content
    assert "stopVoiceInput()" in content


def test_admin_assistant_minimize_keeps_query_input_available():
    content = ADMIN_DASHBOARD_PATH.read_text(encoding="utf-8")

    assert 'id="admin-ai-panel-minimize-btn"' in content
    assert 'id="admin-ai-query-row"' in content
    assert '#admin-ai-assistant-panel[data-minimized="true"] #admin-ai-help-panel' in content
    assert '#admin-ai-assistant-panel[data-minimized="true"] #admin-ai-quick-actions' in content
    assert '#admin-ai-assistant-panel[data-minimized="true"] #admin-ai-response-area' in content
    assert '#admin-ai-assistant-panel[data-minimized="true"] #admin-ai-query-row' in content
    # The AI assistance tab strip was removed; it must not come back as
    # minimized-only chrome either.
    assert "admin-ai-tab-bar" not in content
    assert "function toggleAdminAIPanel()" in content
    assert "toggleButton.textContent = '+';" in content
    assert "toggleButton.textContent = '−';" in content
    assert "stopAdminAssistantVoiceInput()" in content
