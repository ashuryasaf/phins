import re
from pathlib import Path


ADMIN_DASHBOARD_PATH = Path(__file__).resolve().parents[1] / "web_portal" / "static" / "admin.html"


def test_admin_ai_mic_panel_present_without_branded_assistant_title():
    content = ADMIN_DASHBOARD_PATH.read_text(encoding="utf-8")

    assert 'id="admin-ai-assistant-panel"' in content
    assert 'aria-label="Admin AI Mic"' in content
    assert "PHINS admin AI Assistant" not in content
    assert 'id="admin-ai-query-input"' in content
    assert 'id="admin-ai-voice-btn"' in content
    assert 'id="admin-ai-response-area"' in content
    assert "💬 Commands (voice or text):" in content
    assert "Use voice, text, or buttons to run existing dashboard functions with built-in integrity safeguards." in content


def test_admin_ai_mic_positioned_under_admin_dashboard_header():
    content = ADMIN_DASHBOARD_PATH.read_text(encoding="utf-8")

    placement_pattern = re.compile(
        r'<div class="welcome-section">.*?<h1>Admin Dashboard</h1>.*?'
        r'<p class="muted-text">Comprehensive system management and oversight</p>.*?</div>\s*'
        r'<!--\s*=+\s*ADMIN AI MIC\s*=+\s*-->\s*'
        r'<!--.*?-->\s*'
        r'<div id="admin-ai-assistant-panel"[^>]*data-minimized="true"[^>]*>',
        flags=re.S,
    )
    assert placement_pattern.search(content)


def test_admin_ai_mic_stays_visible_when_panel_minimized():
    content = ADMIN_DASHBOARD_PATH.read_text(encoding="utf-8")

    # Query row (ask + mic) must remain available in the minimized top view.
    assert "#admin-ai-assistant-panel[data-minimized=\"true\"] #admin-ai-query-row" in content
    assert re.search(
        r'#admin-ai-assistant-panel\[data-minimized="true"\] #admin-ai-query-row\s*\{\s*'
        r'margin-bottom:\s*0\s*!important;',
        content,
        flags=re.S,
    )

    # Expanded chrome stays collapsed until the user expands the panel.
    for selector in (
        "#admin-ai-help-panel",
        "#admin-ai-tab-bar",
        "#admin-ai-quick-actions",
        "#admin-ai-response-area",
    ):
        assert (
            f'#admin-ai-assistant-panel[data-minimized="true"] {selector}' in content
        )


def test_admin_ai_assistant_tabs_and_wiring_cover_core_admin_domains():
    content = ADMIN_DASHBOARD_PATH.read_text(encoding="utf-8")

    expected_tabs = {
        "overview",
        "customers",
        "policies",
        "underwriting",
        "claims",
        "billing",
        "marketplace",
        "analytics",
        "invitations",
        "growth",
        "operations",
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
    assert "run_actuary_simulation" in content
    assert "approve_all_pending_underwriting" in content
    assert "confirm: '⚠️ Reconcile balance sheet now?" in content
    assert "confirm: '⚠️ Clean demo/test data now?" in content
    assert "confirm: '⚠️ Execute bill-all for eligible active policies?" in content
    assert "confirm: '📐 Run portfolio actuarial simulation?" in content
    assert "confirm: '⚠️ Approve all pending underwriting applications?" in content
    assert "integrity: 'guarded'" in content
    assert "⚠️ High-impact actions are confirmation-gated for data integrity." in content

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
    assert "Voice input available after login validation" in content
    assert "onclick=\"startAdminAssistantVoiceInput()\"" in content

    assert 'id="admin-ai-quick-actions"' in content
    assert 'id="admin-ai-more-actions"' in content
    assert 'id="admin-ai-more-toggle"' in content
    assert "⬇️ Show More Actions" in content
    assert "🤖📊 AI + BI Insights" in content

    assert 'title="Help"' in content
    assert 'title="Expand"' in content
    assert "toggleButton.title = 'Minimize'" in content
    assert "toggleButton.title = 'Expand'" in content


def test_admin_ai_mic_command_keywords_cover_core_functionality():
    content = ADMIN_DASHBOARD_PATH.read_text(encoding="utf-8")

    command_phrases = [
        "run actuary simulation",
        "open console",
        "system health check",
        "reconcile balance sheet",
        "run AI BI insights",
        "process all claims",
        "refresh customers",
        "approve all underwriting",
        "bill all policies",
    ]
    for phrase in command_phrases:
        assert phrase.lower() in content.lower()

    action_keyword_groups = [
        "actuary sim",
        "open console",
        "system health",
        "ai bi",
        "reconcile",
        "cleanup",
        "bill all",
        "process claims",
        "approve all pending",
        "validate pipelines",
        "refresh all",
    ]
    for keyword in action_keyword_groups:
        assert keyword in content
