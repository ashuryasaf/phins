"""Static integrity for the customer dashboard book + chrome unification.

Locks:
- kernel-aligned 50/50 allocation defaults (retired 25/75)
- +/- collapse on every customer tab
- framed brand chrome (Space Grotesk + gradient logo mark)
- book binding IDs and APIs used by every customer tab
"""

from pathlib import Path


PAGE = Path(__file__).resolve().parents[1] / "web_portal" / "static" / "dashboard.html"


def _html() -> str:
    return PAGE.read_text(encoding="utf-8")


CUSTOMER_TABS = (
    "customer-info-panel",
    "health-wallet",
    "activity-log",
    "purchase-history",
    "nft-ledger",
    "policies",
    "claims",
    "billing-settings",
    "investment-portfolio",
    "referrals",
)


def test_customer_tabs_are_collapsible_with_plus_minus():
    html = _html()
    assert "function initCollapsibleSections()" in html
    assert "btn.textContent = collapsed ? '+' : '−'" in html
    assert "phins.customer.collapsed.v1" in html
    for tab_id in CUSTOMER_TABS:
        assert f'id="{tab_id}"' in html
        assert f'id="{tab_id}"' in html
        # Each tab must opt into the shared collapse contract.
        start = html.find(f'id="{tab_id}"')
        window = html[max(0, start - 80): start + 220]
        assert "data-collapsible" in window, f"{tab_id} is not collapsible"


def test_customer_tabs_use_unified_brand_chrome():
    html = _html()
    assert 'href="/phins-theme.css"' in html
    assert 'src="/phins-logo.svg"' in html
    assert "Space Grotesk" in html
    assert "class=\"customer-tab\"" in html or "customer-tab" in html
    assert "tab-brand-mark" in html
    assert html.count('class="tab-brand-mark"') >= 8
    assert "linear-gradient(135deg, #f7e2a0 0%, #e3bf6f 55%, #b8893b 100%)" in html


def test_dashboard_uses_kernel_allocation_defaults_not_legacy_25_75():
    html = _html()
    assert "savings_pct: 50" in html
    assert "risk_pct: 50" in html
    assert "DEFAULT_CUSTOMER_ALLOCATION" in html
    assert "50% → Investments" in html
    assert "50% → Coverage" in html
    assert "function allocationForPolicy(" in html
    assert "function syncCustomerBookDisplays()" in html
    # Retired hardcoded premium-split copy must not remain as a live default.
    assert "Your premium savings (25%)" not in html
    assert "Savings (25%)" not in html
    assert "savings_pct: 25" not in html
    assert "risk_pct: 75" not in html
    assert "amountDue * 0.25" not in html


def test_dashboard_preserves_customer_book_bindings():
    html = _html()
    for element_id in (
        "activity-log",
        "activity-log-table",
        "purchase-history",
        "purchase-history-table",
        "nft-ledger",
        "nft-ledger-table",
        "policies",
        "policies-table",
        "claims",
        "claims-table",
        "billing-settings",
        "billing-savings-allocation",
        "billing-risk-allocation",
        "billing-paid-months-table",
        "billing-history-table",
        "premium-allocation-table",
        "investment-portfolio",
        "portfolio-value",
        "health-wallet",
        "wallet-balance-display",
    ):
        assert f'id="{element_id}"' in html, f"missing book binding #{element_id}"

    for endpoint in (
        "/api/customer/allocation",
        "/api/statement",
        "/api/customer/activity-log",
        "/api/policies",
        "/api/claims",
        "/api/investment/unified",
        "/api/billing",
    ):
        assert endpoint in html, f"missing book API {endpoint}"


def test_dashboard_loads_book_after_auth_not_at_parse_time():
    html = _html()
    assert "loadBillingDetails()," in html or "loadBillingDetails()" in html
    # Parse-time races that used to fire before customer_id was resolved.
    assert "\n    loadStatementData();\n" not in html
    assert "\n    loadPurchaseHistory();\n" not in html
    assert "\n    loadActivityLog();\n" not in html
    assert "\n    loadNFTLedger();\n" not in html
    assert "\n    loadBillingDetails();\n" not in html
