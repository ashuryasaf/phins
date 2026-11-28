"""Integrity checks for the Admin Supplier Details letterhead sheet.

The Supplier Details modal previously used ``background: var(--bg-card)``,
but ``--bg-card`` is undefined on the unified surface, so the panel was
transparent. The redesign must keep every supplier field and action while
rendering an opaque PHINS letterhead sheet.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "web_portal" / "static" / "admin-supplier-dashboard.html"


def _html() -> str:
    return PAGE.read_text(encoding="utf-8")


def test_supplier_details_modal_is_opaque_phins_letterhead():
    html = _html()
    assert 'id="supplier-modal"' in html
    assert "supplier-detail-doc" in html
    assert "supplier-detail-banner" in html
    assert "supplier-detail-gold" in html
    assert 'id="modal-body"' in html
    assert 'id="modal-actions"' in html
    assert 'id="modal-kicker"' in html
    assert 'id="modal-title"' in html
    # Opaque white sheet on the letterhead panel (not undefined --bg-card).
    assert ".modal-content.supplier-detail-doc" in html
    assert "background: #ffffff" in html
    assert "color: #12284c" in html
    modal_css = html.split(".modal-content.supplier-detail-doc")[1].split(".supplier-detail-banner")[0]
    assert "var(--bg-card)" not in modal_css
    assert "#ffffff" in modal_css


def test_supplier_details_render_preserves_all_fields_and_actions():
    html = _html()
    # Profile / AI / business labels that staff rely on.
    for label in (
        "Company Name",
        "Supplier Type",
        "Contact",
        "Phone",
        "Website",
        "Status",
        "Trust Score",
        "Risk Score",
        "AI Recommendation",
        "Commission Rate",
        "Business Registration",
        "License Number",
        "Description",
        "Address",
    ):
        assert label in html, label

    # Same API + status transitions as before.
    assert "/api/admin/suppliers/${id}" in html
    assert "approveSupplier(" in html
    assert "rejectSupplier(" in html
    assert "suspendSupplier(" in html
    assert "reactivateSupplier(" in html
    assert "formatSupplierAddress" in html
    assert "setSupplierModalTitle" in html
    assert "formatCommissionPct" in html
    # Address parts must be escaped — never raw join of supplier fields.
    assert "].filter(Boolean).map(esc)" in html
    assert "[supplier.address, supplier.city, supplier.state, supplier.postal_code, supplier.country].filter(Boolean).join" not in html
    # Commission must not always be multiplied by 100 (supply-chain stores percent points).
    assert "pctScore(commission)" not in html


def test_format_commission_pct_handles_percent_points_and_fractions():
    html = _html()
    # Heuristic: values in (0, 1] are fractions; values > 1 are already percent points.
    assert "(n > 0 && n <= 1) ? (n * 100) : n" in html
