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


def test_ui_clarity_asset_contains_admin_hierarchy_voice_actions():
    content = _fetch("/ui-clarity.js")
    assert "PHINS admin AI Assistant" in content
    assert "run_actuary_portfolio_simulation" in content
    assert 'label: "Admin"' in content
    assert 'label: "Underwriter"' in content
    assert 'label: "Claims"' in content
    assert 'label: "Billing"' in content
    assert 'label: "Accountant"' in content
    assert 'label: "Actuary"' in content
    assert 'label: "Actuary Sim"' in content
    assert 'label: "Investments"' in content
    assert 'label: "AI + BI"' in content
    assert 'label: "Media"' in content
    assert 'label: "Foundations"' in content
    assert 'label: "Video Agents"' in content
    assert 'label: "Pitch"' in content
    assert 'label: "Risk"' in content
    assert 'label: "Reports"' in content
    assert 'label: "Logout"' in content
    assert "open actuary dashboard" in content
    assert "/underwriter-dashboard.html" in content
    assert "/claims-adjuster-dashboard.html" in content
    assert "/accountant-dashboard.html" in content
    assert "/actuary-dashboard.html" in content
    assert "/billing.html" in content
    assert "/savings-portfolio.html" in content
    assert "/admin-media.html" in content
    assert "/admin-foundations.html" in content
    assert "/video-agents.html" in content
    assert "/pitch-dashboard.html" in content
    assert "/risk-dashboard.html" in content
    assert '/risk-reports-dashboard.html' in content
    assert 'id: "admin_logout"' in content
    assert "Logout now?" in content
    assert '"/billing.html"' in content
    assert '"/savings-portfolio.html"' in content
    assert '"/admin-foundations.html"' in content


def test_ui_clarity_observer_avoids_floating_self_render_loop():
    content = _fetch("/ui-clarity.js")
    assert "if (actionsNode.dataset.context === context)" in content
    assert "actionsNode.dataset.context = context;" in content
    assert "targetElement && targetElement.closest && targetElement.closest(`#${FLOATING_BAR_ID}`)" in content
    assert "node.closest && node.closest(`#${FLOATING_BAR_ID}`)" in content
    assert "characterData: true" not in content


def test_ui_clarity_staff_paths_cover_billing_and_foundation_contexts():
    content = _fetch("/ui-clarity.js")
    assert '"/billing.html"' in content
    assert '"/admin-foundations.html"' in content
