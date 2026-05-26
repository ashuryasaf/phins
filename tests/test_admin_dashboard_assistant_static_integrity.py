import re
from pathlib import Path


ADMIN_DASHBOARD_PATH = Path(__file__).resolve().parents[1] / "web_portal" / "static" / "admin.html"


def test_admin_ai_assistant_panel_present_with_customer_style_attribution():
    content = ADMIN_DASHBOARD_PATH.read_text(encoding="utf-8")

    assert 'id="admin-ai-assistant-panel"' in content
    assert "PHINS admin AI Assistant" in content
    assert "Ask me anything about the admin dashboard (voice or text)" in content
    assert "Design adapted from customer PHINS AI Assistant for style integrity" in content
    assert "💬 Try asking (voice or text):" in content
    assert 'id="admin-ai-query-input"' in content
    assert 'id="admin-ai-response-area"' in content


def test_admin_ai_assistant_positioned_under_admin_dashboard_header():
    content = ADMIN_DASHBOARD_PATH.read_text(encoding="utf-8")

    placement_pattern = re.compile(
        r'<div class="welcome-section">.*?<h1>Admin Dashboard</h1>.*?'
        r'<p class="muted-text">Comprehensive system management and oversight</p>.*?</div>\s*'
        r'<!--\s*=+\s*PHINS ADMIN AI ASSISTANT\s*=+\s*-->\s*'
        r'<div id="admin-ai-assistant-panel">',
        flags=re.S,
    )
    assert placement_pattern.search(content)


def test_admin_ai_assistant_tabs_and_wiring_cover_core_admin_domains():
    content = ADMIN_DASHBOARD_PATH.read_text(encoding="utf-8")

    expected_tabs = {
        "overview",
        "financials",
        "customers",
        "policies",
        "underwriting",
        "claims",
        "billing",
        "marketplace",
        "analytics",
        "invitations",
        "reinsurance",
        "legal",
        "growth",
    }
    found_tabs = set(re.findall(r'data-tab="([^"]+)"', content))
    assert expected_tabs.issubset(found_tabs)

    required_functions = [
        "function initAdminAssistant()",
        "function adminAssistantSwitchTab(tabId)",
        "async function adminAssistantQuickAction(actionId)",
        "async function adminAssistantRunAction(actionId)",
        "function adminAssistantActionFromQuery(query)",
        "function initAdminAssistantVoiceRecognition()",
        "function startAdminAssistantVoiceInput()",
        "function stopAdminAssistantVoiceInput()",
        "function preprocessAdminAssistantVoiceInput(transcript)",
        "function showAdminAssistantVoiceFeedback(transcript)",
        "async function adminAssistantProcessQuery()",
        "function adminAssistantSetStatus(kind, text)",
    ]
    for signature in required_functions:
        assert signature in content

    # Ensure key domain refresh functions are wired through assistant actions.
    for function_name in [
        "loadDashboardStats",
        "loadBalanceSheet",
        "loadAIInsights",
        "loadCustomerList",
        "loadPolicies",
        "loadUnderwritingApplications",
        "loadClaims",
        "loadBillingData",
        "loadMarketplaceData",
        "loadPlatformAnalytics",
        "loadInvitationCodes",
        "loadReinsuranceData",
        "loadLegalData",
        "loadLatestMarketingCampaign",
    ]:
        assert function_name in content


def test_admin_ai_assistant_integrity_guards_and_section_ids_present():
    content = ADMIN_DASHBOARD_PATH.read_text(encoding="utf-8")

    # High-impact operations should remain confirmation-gated in assistant mappings.
    assert "reconcile_balance_sheet" in content
    assert "cleanup_demo_data" in content
    assert "bill_all_policies" in content
    assert "confirm: '⚠️ Reconcile balance sheet now?" in content
    assert "confirm: '⚠️ Clean demo/test data now?" in content
    assert "confirm: '⚠️ Execute bill-all for eligible active policies?" in content

    # Reinsurance and legal sections get explicit ids for assistant navigation coverage.
    # Tolerate additional attributes (e.g. data-collapsible) being added later.
    assert re.search(r'<section\s+id="reinsurance"\s+class="section-content"[^>]*>', content)
    assert re.search(r'<section\s+id="legal"\s+class="section-content"[^>]*>', content)


def test_admin_ai_assistant_voice_and_quick_action_controls_present():
    content = ADMIN_DASHBOARD_PATH.read_text(encoding="utf-8")

    assert 'id="admin-ai-voice-btn"' in content
    assert 'id="admin-ai-voice-recording-indicator"' in content
    assert 'id="admin-ai-voice-transcript"' in content
    assert "🎤 Listening... Speak now" in content

    assert 'id="admin-ai-quick-actions"' in content
    assert 'id="admin-ai-more-actions"' in content
    assert 'id="admin-ai-more-toggle"' in content
    assert "⬇️ Show More Actions" in content
    assert "🤖📊 AI + BI Insights" in content

    # Ensure customer-assistant parity language for multi-input orchestration is present.
    assert "Use voice, text, or buttons to run existing dashboard functions with built-in integrity safeguards." in content
    assert "title=\"Help\"" in content
    assert "title=\"Minimize\"" in content
