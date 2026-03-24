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


def test_ui_clarity_script_injected_on_landing_root_html():
    content = _fetch("/")
    assert '<script src="/ui-clarity.js"></script>' in content
    assert content.count('<script src="/ui-clarity.js"></script>') == 1


def test_ui_clarity_asset_contains_floating_voice_quick_actions_bootstrap():
    content = _fetch("/ui-clarity.js")
    assert 'const FLOATING_BAR_ID = "phins-vqa-bar";' in content
    assert 'Voice Quick Actions' in content
    assert "startFloatingVoiceInput" in content
    assert "dispatchFloatingQuery" in content


def test_ui_clarity_asset_contains_admin_hierarchy_voice_actions():
    content = _fetch("/ui-clarity.js")
    assert "PHINS admin AI Assistant" in content
    assert "run_actuary_portfolio_simulation" in content
    assert "open actuary dashboard" in content
    assert "/underwriter-dashboard.html" in content
    assert "/claims-adjuster-dashboard.html" in content
    assert "/accountant-dashboard.html" in content
    assert "/actuary-dashboard.html" in content
    assert "/admin-media.html" in content
    assert "/admin-foundations.html" in content
    assert '/risk-reports-dashboard.html' in content
    assert 'id: "admin_logout"' in content
    assert "Logout now?" in content


def test_ui_clarity_skips_floating_bar_on_public_paths():
    content = _fetch("/ui-clarity.js")
    assert "function hasCredentialedSession()" in content
    assert "function isPublicNoAssistantPath(pathname)" in content
    assert "function shouldEnableFloatingAssistant()" in content
    assert 'return p === "/" || p === "" || p === "/index.html" || p === "/login" || p === "/login.html";' in content
    assert "if (!shouldEnableAssistant) {" in content
    assert "return;" in content
    assert 'document.body.classList.add("ux-compact-dashboard");' in content
    assert "const shouldEnableAssistant = shouldEnableFloatingAssistant();" in content
