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


def test_supplier_portal_supports_query_param_tab_activation():
    content = _fetch("/supplier-portal.html")
    assert "function selectSupplierPortalTab(tabId)" in content
    assert "const requestedTab = new URLSearchParams(window.location.search).get('tab');" in content
    assert "selectSupplierPortalTab(requestedTab || 'offers');" in content


def test_ui_clarity_asset_contains_floating_voice_quick_actions_bootstrap():
    content = _fetch("/ui-clarity.js")
    assert 'const FLOATING_BAR_ID = "phins-vqa-bar";' in content
    assert 'Voice Quick Actions' in content
    assert "startFloatingVoiceInput" in content
    assert "dispatchFloatingQuery" in content


def test_ui_clarity_asset_contains_admin_hierarchy_voice_actions():
    content = _fetch("/ui-clarity.js")
    assert "Admin AI Mic" in content
    assert "PHINS admin AI Assistant" not in content
    assert "Admin AI Mic ready." in content
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


def test_ui_clarity_asset_contains_supplier_voice_actions_and_hierarchy():
    content = _fetch("/ui-clarity.js")
    assert 'return "supplier";' in content
    assert "Supplier Voice Quick Actions" in content
    assert 'id: "supplier_orders"' in content
    assert 'id: "supplier_settlements"' in content
    assert 'id: "supplier_offers"' in content
    assert 'id: "supplier_profile"' in content
    assert 'id: "supplier_new_offer"' in content
    assert 'id: "supplier_logout"' in content
    assert "/supplier-portal.html" in content
    assert "/supplier-portal.html?tab=orders" in content
    assert "/supplier-portal.html?tab=settlements" in content
    assert "/supplier-portal.html?tab=offers" in content
    assert "/supplier-portal.html?tab=profile" in content
    assert "Opening supplier offer form." in content
    assert "Refreshing supplier dashboard." in content
    assert "Refreshing supplier settlements." in content
    assert "Refreshing supplier orders." in content
    assert "Refreshing supplier offers." in content
    assert "supplier dispute" in content
    assert "supplier refund" in content
    assert "supplier settlement status" in content


def test_ui_clarity_asset_requires_authenticated_session_before_render():
    content = _fetch("/ui-clarity.js")
    assert "async function resolveFloatingAuth()" in content
    assert "if (!token) {" in content
    assert "const response = await fetch(\"/api/session/validate\"" in content
    assert "floatingAuthAllowed = [\"customer\", \"supplier\"].includes(role) || isAdminRole(role);" in content
    assert "if (authAllowed) {" in content
    assert "removeFloatingBar();" in content
    assert "ensureFloatingBar();" in content


def test_ui_clarity_suppresses_floating_bar_on_public_pages():
    content = _fetch("/ui-clarity.js")
    assert "function isPublicPage(pathname)" in content
    assert '"/index.html"' in content
    assert '"/login.html"' in content
    assert "const onPublicPage = isPublicPage(window.location.pathname);" in content
    assert "onPublicPage ? false : await resolveFloatingAuth();" in content


def test_customer_dashboard_voice_button_starts_disabled_until_session_validates():
    content = _fetch("/dashboard.html")
    assert 'id="voice-btn"' in content
    assert "Voice input available after login validation" in content
    assert "voiceBtn.disabled = false;" in content
    assert "voiceBtn.disabled = true;" in content


def test_admin_dashboard_voice_button_starts_disabled_until_session_validates():
    content = _fetch("/admin.html")
    assert 'id="admin-ai-voice-btn"' in content
    assert "Voice input available after login validation" in content
    assert "voiceBtn.disabled = false;" in content
    assert "voiceBtn.disabled = true;" in content


def test_ui_clarity_observer_avoids_floating_self_render_loop():
    content = _fetch("/ui-clarity.js")
    assert "if (actionsNode.dataset.context === context)" in content
    assert "actionsNode.dataset.context = context;" in content
    assert "targetElement && targetElement.closest && targetElement.closest(`#${FLOATING_BAR_ID}`)" in content
    assert "node.closest && node.closest(`#${FLOATING_BAR_ID}`)" in content
    assert "characterData: true" not in content
