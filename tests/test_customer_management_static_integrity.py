"""Static integrity for the customer-management dashboard redesign.

Locks the unified PHINS chrome (shield emblem, theme tokens, Space Grotesk)
and the data-binding contract used by pipeline stats, customer rows, and
billing-pending repair — so a visual restyle cannot drop IDs or APIs.
"""

from pathlib import Path


PAGE = Path(__file__).resolve().parents[1] / "web_portal" / "static" / "customer-management.html"


def _html() -> str:
    return PAGE.read_text(encoding="utf-8")


def test_customer_management_uses_unified_phins_chrome():
    html = _html()
    assert 'href="/phins-theme.css"' in html
    assert 'src="/phins-logo.svg"' in html
    assert html.count("/phins-logo.svg") >= 2  # header emblem + brand banner
    assert 'class="phins-header"' in html
    assert 'class="phins-logo-text"' in html
    assert "Space Grotesk" in html
    assert "--phins-navy" in html
    assert "--phins-gold" in html
    assert 'class="page-brand-banner"' in html
    assert "Customer Management &amp; Pipeline Validation" in html
    # Legacy purple/emoji chrome must stay gone
    assert "class=\"topbar\"" not in html
    assert "🛡️ PHINS Insurance" not in html
    assert "#667eea" not in html
    assert "#764ba2" not in html


def test_customer_management_preserves_data_binding_ids():
    html = _html()
    for element_id in (
        "stats-grid",
        "total-customers",
        "total-applications",
        "active-policies",
        "pending-billing",
        "total-wallets",
        "stage-application",
        "stage-underwriting",
        "stage-approved",
        "stage-active",
        "stage-billing",
        "count-application",
        "count-underwriting",
        "count-approved",
        "count-active",
        "count-billing",
        "search-input",
        "repair-billing-btn",
        "customer-table-body",
        "validation-modal",
        "modal-title",
        "validation-results",
        "contact-modal",
        "contact-modal-title",
        "contact-template",
        "contact-channel-pills",
        "contact-subject",
        "contact-message",
        "contact-send-btn",
        "contact-result",
    ):
        assert f'id="{element_id}"' in html, f"missing #{element_id}"


def test_customer_management_preserves_pipeline_and_repair_apis():
    html = _html()
    assert "/api/admin/pipeline-stats" in html
    assert "/api/admin/customers" in html
    assert "/api/admin/validate-customer/" in html
    assert "/api/admin/billing-pending/repair" in html
    assert "/api/admin/customers/" in html
    assert "/contact" in html
    assert "openContactModal" in html
    assert "sendCustomerContact" in html
    # Token keys used by the rest of the admin/customer portal
    assert "localStorage.getItem('phins_token')" in html
    assert "sessionStorage.getItem('authToken')" in html


def test_customer_management_preserves_row_and_integrity_fields():
    html = _html()
    for field in (
        "pipeline_stage",
        "outstanding_bills",
        "active_policies",
        "policies_count",
        "total_premium_due",
        "wallet_balance",
        "billing_pending",
        "data_integrity_ok",
        "total_outstanding_after",
        "pending_billing_customers_after",
        "autopay_coverage_active_policies",
        "amount_settled",
        "amount_remaining",
        "normalized_policies",
        "stage_transition",
    ):
        assert field in html, f"missing data field {field}"


def test_customer_management_preserves_pipeline_stage_badges():
    html = _html()
    for stage in (
        "registered",
        "underwriting",
        "approved",
        "active_policy",
        "billing_pending",
        "fully_active",
    ):
        assert f"'{stage}'" in html, f"missing stage badge {stage}"


def test_customer_management_escapes_customer_fields():
    html = _html()
    assert "function escHtml" in html
    assert "<strong>${customer.name}</strong>" not in html
    assert "<td>${customer.email}</td>" not in html
    assert "<code>${customer.id}</code>" not in html
    assert "onclick=\"validateCustomer('${customer.id}')\"" not in html
    assert "onclick=\"openContactModal('${customer.id}')\"" not in html
    assert "onclick=\"repairCustomerBilling('${customer.id}')\"" not in html
    assert "data-customer-id=" in html
    assert "this.dataset.customerId" in html
    assert "${escHtml(customer.name)}" in html
    assert "${escHtml(customer.email)}" in html
