from urllib.request import urlopen


def _fetch(path: str) -> str:
    with urlopen(f"http://localhost:8000{path}") as resp:
        return resp.read().decode("utf-8")


def test_ui_clarity_script_injected_on_customer_dashboard_html():
    content = _fetch("/dashboard.html")
    assert '<script src="/ui-clarity.js"></script>' in content
    assert content.count('<script src="/ui-clarity.js"></script>') == 1


def test_ui_clarity_script_injected_on_login_html():
    content = _fetch("/login.html")
    assert '<script src="/ui-clarity.js"></script>' in content
    assert content.count('<script src="/ui-clarity.js"></script>') == 1


def test_ui_clarity_asset_contains_floating_voice_quick_actions_bootstrap():
    content = _fetch("/ui-clarity.js")
    assert 'const FLOATING_BAR_ID = "phins-vqa-bar";' in content
    assert 'Voice Quick Actions' in content
    assert "startFloatingVoiceInput" in content
    assert "dispatchFloatingQuery" in content
