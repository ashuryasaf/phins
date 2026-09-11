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
    assert "Commands (voice or text):" in content
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
    assert "confirm: ' Reconcile balance sheet now?" in content
    assert "confirm: ' Clean demo/test data now?" in content
    assert "confirm: ' Execute bill-all for eligible active policies?" in content
    assert "confirm: ' Run portfolio actuarial simulation?" in content
    assert "confirm: ' Approve all pending underwriting applications?" in content
    assert "confirm: ' Queue AI video generation for every campaign blueprint?" in content
    assert "integrity: 'guarded'" in content
    assert "High-impact actions are confirmation-gated for data integrity." in content

    # Reinsurance and legal sections get explicit ids for assistant navigation coverage.
    # Tolerate additional attributes (e.g. data-collapsible) being added later.
    assert re.search(r'<section\s+id="reinsurance"\s+class="section-content"[^>]*>', content)
    assert re.search(r'<section\s+id="legal"\s+class="section-content"[^>]*>', content)


def test_admin_ai_assistant_voice_and_quick_action_controls_present():
    content = ADMIN_DASHBOARD_PATH.read_text(encoding="utf-8")

    assert 'id="admin-ai-voice-btn"' in content
    assert 'id="admin-ai-voice-recording-indicator"' in content
    assert 'id="admin-ai-voice-transcript"' in content
    assert "Listening... Speak now" in content
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
    assert "background: #e3bf6f;" in block
    # bottom:0 + top:60px against the backdrop-filter header collapses
    # the open drawer to ~0px. The hamburger must size from content.
    assert "bottom: auto;" in block
    assert "bottom: 0;" not in block
    assert "overflow-y: auto;" in block
    assert "linear-gradient(180deg, #ffffff 0%, #b7d3ff 100%)" in content
    assert ".phins-logo-text { display: none; }" not in content
    # Mobile wordmark drops clipped-gradient dither ("///" hatch) for ice ink.
    assert "-webkit-text-fill-color: #eaf1ff;" in content
    assert "#admin-ai-assistant-panel" in content
    assert "#091126" in content


def test_admin_ai_monte_carlo_evaluation_button_wired_read_only():
    content = ADMIN_DASHBOARD_PATH.read_text(encoding="utf-8")

    # Quick-action button is present and routes through the assistant action registry.
    assert 'id="admin-ai-monte-carlo-btn"' in content
    assert "adminAssistantQuickAction('run_monte_carlo_evaluation')" in content
    assert ">Monte Carlo Eval</button>" in content

    # Registry entry is read-only (no confirmation gate needed) and maps to the operations domain.
    registry = re.search(
        r"run_monte_carlo_evaluation:\s*\{(.*?)\n\s*\},", content, flags=re.S
    )
    assert registry, "expected run_monte_carlo_evaluation action registry entry"
    assert "adminRunMonteCarloEvaluation()" in registry.group(1)
    assert "integrity: 'safe'" in registry.group(1)
    assert "confirm:" not in registry.group(1)
    assert "run_monte_carlo_evaluation: 'operations'" in content
    assert "'run_actuary_simulation', 'run_monte_carlo_evaluation'" in content

    # Voice/text commands resolve to the action.
    assert "action: 'run_monte_carlo_evaluation'" in content
    assert "'monte carlo'" in content
    assert '"Run Monte Carlo evaluation"' in content

    # Runner hits the read-only BI endpoint with GET only and surfaces the integrity seal.
    runner = re.search(
        r"async function adminRunMonteCarloEvaluation\(\)\s*\{(.*?)\n\s*async function adminRunSystemHealth",
        content,
        flags=re.S,
    )
    assert runner, "expected adminRunMonteCarloEvaluation implementation"
    body = runner.group(1)
    assert "/api/bi/monte-carlo-evaluation?" in body
    assert "method: 'POST'" not in body
    assert "integrity.read_only === true" in body
    assert "integrity.side_effects" in body
    assert "observed_inputs_unchanged" in body
    assert "results_sha256" in body


def test_admin_ai_monte_carlo_conclusions_and_guarded_apply_flow():
    content = ADMIN_DASHBOARD_PATH.read_text(encoding="utf-8")

    # Conclusions + next moves are rendered from the sealed report.
    assert "function adminMcConclusionsHtml(" in content
    assert "function adminMcNextMovesHtml(" in content
    assert "adminMcConclusionsHtml(data.conclusions)" in content
    assert "adminMcNextMovesHtml(data.next_moves)" in content
    assert 'id="admin-mc-conclusions"' in content
    assert "Suggested next moves" in content

    # Fix / redirect buttons exist and route through the move id, never free-form payloads.
    assert "onclick=\"adminMcApplyFix('${adminAssistantEscapeHtml(m.id)}')\"" in content
    assert "onclick=\"adminMcOpenSource('${adminAssistantEscapeHtml(m.id)}')\"" in content
    assert "Review &amp; apply fix" in content
    assert ">Open source</button>" in content
    # Light-card button style (the dark-panel .admin-ai-action-btn is unreadable on the cards).
    assert ".admin-mc-btn {" in content
    assert 'class="admin-mc-btn primary" onclick="adminMcApplyFix(' in content

    apply_fn = re.search(
        r"async function adminMcApplyFix\(moveId\)\s*\{(.*?)\n\s*async function adminRunMonteCarloEvaluation",
        content,
        flags=re.S,
    )
    assert apply_fn, "expected adminMcApplyFix implementation"
    body = apply_fn.group(1)
    # Only the audited underwriting config endpoint may be driven, only for adjustable moves.
    assert "action.kind !== 'adjust'" in body
    assert "target.api.path !== '/api/actuarial/config'" in body
    # Confirmation gate, live-value verification before write, and audit reason with the seal.
    assert "window.confirm(` Apply Monte Carlo advisory to live underwriting config?" in body
    assert "target.api.read_back.path" in body
    assert "Aborted: live configuration changed since this evaluation" in body
    assert "change_reason:" in body and "results_sha256=" in body
    # Post-apply read-back verification and re-run affordance.
    assert "Applied and verified" in body
    assert "adminAssistantQuickAction('run_monte_carlo_evaluation')" in body


def test_actuary_dashboard_supports_section_deep_links():
    actuary = (ADMIN_DASHBOARD_PATH.parent / "actuary-dashboard.html").read_text(encoding="utf-8")
    assert "function openSectionFromHash()" in actuary
    assert "openSectionFromHash();" in actuary
    assert "window.addEventListener('hashchange', openSectionFromHash);" in actuary
    for section in ("section-underwriting", "section-reserves"):
        assert f'<section id="{section}"' in actuary
