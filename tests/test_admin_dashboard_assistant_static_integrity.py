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


def test_admin_dashboard_hero_text_removed_and_mic_leads_main():
    content = ADMIN_DASHBOARD_PATH.read_text(encoding="utf-8")

    # The old hero heading and subtitle are gone.
    assert "<h1>Admin Dashboard</h1>" not in content
    assert "Comprehensive system management and oversight" not in content
    assert '<div class="welcome-section">' not in content

    # The Admin AI Mic panel is the first element inside <main>.
    placement_pattern = re.compile(
        r'<main class="container"[^>]*>\s*'
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
        "#admin-ai-quick-actions",
        "#admin-ai-response-area",
    ):
        assert (
            f'#admin-ai-assistant-panel[data-minimized="true"] {selector}' in content
        )


def test_admin_ai_assistant_tab_bar_removed_but_domain_routing_kept():
    content = ADMIN_DASHBOARD_PATH.read_text(encoding="utf-8")

    # The visible AI assistance tab strip is removed.
    assert 'id="admin-ai-tab-bar"' not in content
    assert "admin-ai-tab-btn" not in content
    assert 'data-tab="' not in content

    # Internal domain routing still covers every admin domain so voice/text
    # commands keep working.
    expected_domains = {
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
    tabs_block = re.search(r"const ADMIN_ASSISTANT_TABS = \{(.*?)\n    \};", content, flags=re.S)
    assert tabs_block
    declared = set(re.findall(r"^\s{6}(\w+): \{", tabs_block.group(1), flags=re.M))
    assert expected_domains.issubset(declared)

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


def test_admin_ai_assistant_covers_newer_admin_functions():
    content = ADMIN_DASHBOARD_PATH.read_text(encoding="utf-8")

    # Newer admin dashboard functions must be reachable through the AI mic.
    action_to_function = {
        "export_customer_data": "exportCustomerData",
        "sync_policy_ledgers": "syncPolicyLedgers",
        "sync_claims_ledger": "syncClaimsLedger",
        "allocate_all_savings": "allocateAllSavings",
        "generate_missing_billing": "generateMissingBilling",
        "refresh_business_inquiries": "loadBusinessInquiries",
        "run_batch_probability_analysis": "runBatchProbabilityAnalysis",
        "batch_generate_marketing_videos": "batchGenerateMarketingVideos",
        "view_test_data": "toggleTestDataPanel",
    }
    for action_id, function_name in action_to_function.items():
        assert f"{action_id}:" in content, action_id
        assert f"{function_name}(" in content, function_name

    # Voice/text keyword routing exists for the new actions.
    for keyword in [
        "allocate savings",
        "missing bills",
        "export customers",
        "sync policy ledger",
        "sync claims ledger",
        "probability analysis",
        "business inquiries",
        "test data",
        "generate all videos",
    ]:
        assert keyword in content, keyword


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
    assert "confirm: '⚠️ Queue AI video generation for every campaign blueprint?" in content
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
    assert ">Show More Actions<" in content
    assert ">AI + BI Insights<" in content

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


def test_admin_overview_unified_phins_gradient_and_clean_labels():
    content = ADMIN_DASHBOARD_PATH.read_text(encoding="utf-8")

    # Unified deep-navy brand gradient (logo redesign design language) across
    # dark sections and the AI mic panel.
    navy_gradient = "linear-gradient(135deg, #060d1f 0%, #0d1b3e 100%)"
    assert content.count(navy_gradient) >= 6
    # The AI mic panel uses the aurora glass shared with the customer panel.
    assert "rgba(9, 17, 38, 0.97)" in content

    # Legacy non-brand section gradients are gone.
    for legacy in [
        "#ff6b35 0%, #f7931e 100%",                # orange invitations
        "#1a237e 0%, #283593 50%",                 # indigo analytics
        "#1e3a5f 0%, #2d5a87 100%",                # slate AI claims bot
        "#0d47a1 0%, #1565c0 50%, #1976d2 100%",   # interim light-blue pass
    ]:
        assert legacy not in content, legacy

    # Brand display type for section headings.
    assert "font-family: 'Space Grotesk', 'Inter', sans-serif;" in content

    # Section headers read as clean text without decorative emoji icons.
    for header in [
        "<h2>Customer Management — Recent Activity</h2>",
        "<h2>Sales Division — Policy Management</h2>",
        "<h2>Underwriting Division — Risk Assessment</h2>",
        "<h2>Claims Division — ADL-Based Disability Claims</h2>",
        "<h2>Accounting Division — Billing & Payments</h2>",
        "<h2>Reinsurance Division — Partner Management</h2>",
        "<h2>Legal Division — Compliance & Disputes</h2>",
        "<h2>Marketplace Division — Services & Products</h2>",
    ]:
        assert header in content, header
    assert "Insurance Pipeline Overview</h3>" in content
    assert "General Reserves — Balance Sheet</h3>" in content

    # Nav operational tabs are emoji-free.
    nav = re.search(r'<nav class="phins-nav"[^>]*>(.*?)</nav>', content, flags=re.S)
    assert nav
    emoji_re = re.compile(r"[\U0001F000-\U0001FAFF\u2600-\u27BF]")
    assert not emoji_re.search(nav.group(1))


def test_admin_mobile_nav_uses_navy_glass_not_blue_stripe_gradient():
    content = ADMIN_DASHBOARD_PATH.read_text(encoding="utf-8")

    # The old 135deg #0d47a1→#1565c0 drawer painted diagonal "strips///"
    # through the semi-transparent mobile chips. The open menu must use
    # the unified deep-navy glass instead.
    mobile_nav = re.search(
        r"@media screen and \(max-width: 1024px\)\s*\{(.*?)@media screen and \(max-width: 768px\)",
        content,
        flags=re.S,
    )
    assert mobile_nav, "expected admin mobile nav breakpoint"
    block = mobile_nav.group(1)
    assert "linear-gradient(135deg, #0d47a1 0%, #1565c0 100%)" not in block
    assert "#060d1f" in block
    assert "rgba(16, 31, 63, 0.96)" in block
    assert "linear-gradient(180deg, #f7e2a0 0%, #e3bf6f 100%)" in block
    assert "linear-gradient(180deg, #ffffff 0%, #b7d3ff 100%)" in content
    assert ".phins-logo-text { display: none; }" not in content
    # Mobile wordmark drops clipped-gradient dither ("///" hatch) for ice ink.
    assert "-webkit-text-fill-color: #eaf1ff;" in content
    assert "#admin-ai-assistant-panel" in content
    assert "#091126" in content
