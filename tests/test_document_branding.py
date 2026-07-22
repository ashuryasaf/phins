"""
Static-integrity tests for the unified PHINS document branding.

Every downloadable document surfaced by the pitch dashboard and the
Corporate / Legal & Funding Document Center must carry the same first-level
document identity introduced with the branded investor PDFs
(scripts/generate_investor_pdfs.py): the PHINS shield logo, the wordmark +
tagline text, and the gold (#c9a04e) / navy (#0e2f63) letterhead rules.

Covered download surfaces:
- the four client-generated (jsPDF) downloads on /pitch-dashboard.html
  (executive summary, scenario-lab assessment, country investor pitch,
  and the "PHINS Technologies — Business Plan for Technology Investors" tab)
  via the shared /phins-pdf-brand.js helper,
- the /legal/*.html print documents linked from
  /corporate-legal-dashboard.html (legal-docs.js + legal-docs.css),
- the internal print documents linked from the partner-meetings /
  investor-meeting sections, plus the regenerated actuary-briefing PDF.

Data-integrity note: the brand helper draws chrome only (letterhead, rules,
footers); these tests also pin that contract by asserting the canonical
content anchors of each surface remain untouched.
"""

from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[1] / "web_portal" / "static"
INTERNAL = STATIC / "internal"
LEGAL = STATIC / "legal"

BRAND_TAGLINE = "Personal Health Insurance & Savings · AI-Operated Insurance Platform"
GOLD = "c9a04e"
NAVY = "0e2f63"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Shared jsPDF brand helper
# ---------------------------------------------------------------------------

def test_pdf_brand_helper_exists_with_brand_identity():
    helper = STATIC / "phins-pdf-brand.js"
    assert helper.is_file(), "missing shared jsPDF brand helper"
    js = _read(helper)
    # logo asset + wordmark + tagline
    assert "/phins-logo.png" in js
    assert "PHINS" in js
    assert BRAND_TAGLINE in js
    # gold / navy brand palette (RGB of #c9a04e and #0e2f63)
    assert "201, 160, 78" in js
    assert "14, 47, 99" in js
    # public API used by the generators
    for api in ("letterhead", "finalize", "preload", "PhinsPdfBrand"):
        assert api in js, f"helper missing API {api}"
    # chrome-only contract stated in the module
    assert "chrome ONLY" in js


def test_pitch_dashboard_loads_brand_helper():
    pd = _read(STATIC / "pitch-dashboard.html")
    assert '<script src="/phins-pdf-brand.js"></script>' in pd


def test_pitch_dashboard_generators_use_brand_helper():
    pd = _read(STATIC / "pitch-dashboard.html")
    # all four client-generated PDFs draw the branded letterhead + footer
    assert pd.count("window.PhinsPdfBrand.letterhead(doc") == 4
    assert pd.count("window.PhinsPdfBrand.finalize(doc") == 4
    # branded titles per generator
    assert '"PHINS Platform — Executive Summary"' in pd
    assert '"PHI Permanent 3+ ADL Executive Business Assessment"' in pd
    assert '"PHINS — " + m.d.name + " — Investor Pitch"' in pd
    assert '"PHINS Technologies — Technology Investor Business Plan"' in pd
    # generators fail closed when the helper is unavailable
    assert pd.count("|| !window.PhinsPdfBrand") == 4


def test_pitch_dashboard_generator_data_unchanged():
    """Branding must not alter the generated document data."""
    pd = _read(STATIC / "pitch-dashboard.html")
    # canonical data anchors of the four generators are untouched
    assert "phins-executive-summary.pdf" in pd
    assert "phi-permanent-3-adl-executive-business-assessment-" in pd
    assert "phins-investor-pitch-" in pd
    assert "phins-tech-investor-business-plan.pdf" in pd
    assert "Data integrity notice" in pd


# ---------------------------------------------------------------------------
# Corporate / Legal & Funding Document Center (/legal/*.html)
# ---------------------------------------------------------------------------

def test_legal_docs_letterhead_uses_logo_and_tagline():
    js = _read(LEGAL / "legal-docs.js")
    # document letterhead + site header carry the shield logo image
    assert js.count('/phins-logo.svg') >= 2
    assert BRAND_TAGLINE.replace("&", "&amp;") in js


def test_legal_docs_css_carries_brand_palette():
    css = _read(LEGAL / "legal-docs.css")
    assert f"--brand-gold: #{GOLD}" in css
    assert f"--brand-navy: #{NAVY}" in css
    # gold + navy double rule on the document head
    assert "border-bottom: 2.2px solid var(--brand-gold)" in css
    assert ".ld-doc-head::after" in css
    # letterhead colors survive print / save-as-PDF
    assert "print-color-adjust: exact" in css


def test_corporate_legal_dashboard_header_uses_logo():
    html = _read(STATIC / "corporate-legal-dashboard.html")
    assert "/phins-logo.svg" in html


# ---------------------------------------------------------------------------
# Internal print documents (partner meetings + investor meeting + briefing)
# ---------------------------------------------------------------------------

INTERNAL_DOCS = [
    "phins-ai-tech-partner-business-plan.html",
    "phins-insurer-mga-business-plan.html",
    "phins-investor-business-plan.html",
    "exec-actuary-briefing.html",
]


@pytest.mark.parametrize("fname", INTERNAL_DOCS)
def test_internal_document_carries_branded_letterhead(fname):
    doc = _read(INTERNAL / fname)
    assert 'class="phins-letterhead"' in doc, f"{fname} missing letterhead"
    assert "/phins-logo.svg" in doc
    assert BRAND_TAGLINE.replace("&", "&amp;") in doc
    # gold / navy rules with print-color preservation
    assert f"#{GOLD}" in doc
    assert f"#{NAVY}" in doc
    assert "print-color-adjust: exact" in doc


def test_actuary_briefing_pdf_regenerated_with_letterhead():
    pdf = INTERNAL / "exec-actuary-briefing.pdf"
    assert pdf.is_file()
    data = pdf.read_bytes()
    assert data[:5] == b"%PDF-"
    assert b"%%EOF" in data[-2048:]
    # the branded regeneration embeds the shield raster (image XObject);
    # the pre-branding render had no images at all
    assert b"/Image" in data, "briefing PDF missing the letterhead logo image"
