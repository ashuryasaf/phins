import re
from pathlib import Path


ADMIN_DASHBOARD_PATH = Path(__file__).resolve().parents[1] / "web_portal" / "static" / "admin.html"


def test_admin_ai_assistant_panel_present_with_customer_style_attribution():
    content = ADMIN_DASHBOARD_PATH.read_text(encoding="utf-8")

    assert 'id="admin-ai-assistant-panel"' in content
    assert "PHINS admin AI Assistant" in content
    assert "Design adapted from customer PHINS AI Assistant for style integrity" in content
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
        "async function adminAssistantRunAction(actionId)",
        "async function adminAssistantProcessQuery()",
        "function adminAssistantSetStatus(kind, text)",
    ]
    for signature in required_functions:
        assert signature in content

    # Ensure key domain refresh functions are wired through assistant actions.
    for function_name in [
        "loadDashboardStats",
        "loadBalanceSheet",
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
    assert '<section id="reinsurance" class="section-content">' in content
    assert '<section id="legal" class="section-content">' in content
