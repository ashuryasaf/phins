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

import os
from pathlib import Path
from urllib.request import Request, urlopen

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


# ---------------------------------------------------------------------------
# Unicorn tab documents (deck, executive summary, seed 5-pager)
# ---------------------------------------------------------------------------

UNICORN_DOCS = [
    "unicorn-investor-deck.html",
    "unicorn-executive-summary.html",
    "seed-investor-deck.html",
]


@pytest.mark.parametrize("fname", UNICORN_DOCS)
def test_unicorn_document_carries_branded_letterhead(fname):
    doc = _read(STATIC / fname)
    # real shield logo in the on-screen brand header
    assert "/phins-logo.svg" in doc, f"{fname} missing shield logo"
    # print letterhead with the unified wordmark + tagline + gold/navy rules
    assert 'class="phins-letterhead"' in doc, f"{fname} missing letterhead"
    assert BRAND_TAGLINE.replace("&", "&amp;") in doc
    assert f"#{GOLD}" in doc
    assert f"#{NAVY}" in doc
    assert "print-color-adjust: exact" in doc


# ---------------------------------------------------------------------------
# Templated investor documents (country pitches, prospectuses, NDAs,
# business-plan presentation) and the addressed risk 1-pagers
# ---------------------------------------------------------------------------

def _templated_docs():
    docs = sorted(STATIC.glob("*capital-markets-pitch.html"))
    docs += sorted(STATIC.glob("*-prospectus.html"))
    docs += sorted(STATIC.glob("nda-*.html"))
    docs += [STATIC / "PHINS_Business_Plan_Presentation.html"]
    return docs


def test_templated_docs_discovered():
    names = {p.name for p in _templated_docs()}
    # representative anchors so the glob never silently goes empty
    for expected in ("israel-capital-markets-pitch.html",
                     "israel-isa-prospectus.html", "nda-israel.html",
                     "PHINS_Business_Plan_Presentation.html"):
        assert expected in names
    assert len(names) >= 55


@pytest.mark.parametrize("doc_path", _templated_docs(), ids=lambda p: p.name)
def test_templated_document_carries_shield_logo_and_gold_rule(doc_path):
    doc = _read(doc_path)
    assert "/phins-logo.svg" in doc, f"{doc_path.name} missing shield logo"
    assert "PHINS unified document branding" in doc, \
        f"{doc_path.name} missing brand CSS"
    # gold letterhead rule with print-color preservation
    assert f"3px solid #{GOLD}" in doc, f"{doc_path.name} missing gold rule"
    assert "print-color-adjust: exact" in doc, \
        f"{doc_path.name} missing print-color preservation"
    # brand icon containers no longer fall back to the emoji shield
    assert '"logo-icon">🛡️' not in doc and '"cover-logo-icon">🛡️' not in doc


@pytest.mark.parametrize("fname", ["phins-risk-1pager-goldsobel.html",
                                   "phins-risk-1pager-fefferman.html"])
def test_risk_1pager_uses_raster_logo_for_canvas_pdf(fname):
    doc = _read(STATIC / fname)
    # html2canvas rasterizes the page for the jsPDF download; the PNG logo
    # renders reliably there (dimensionless SVGs can be dropped)
    assert "/phins-logo.png" in doc, f"{fname} missing raster shield logo"
    assert "PHINS unified document branding" in doc
    assert f"#{GOLD}" in doc


@pytest.mark.skipif(not os.environ.get("TEST_BASE_URL"),
                    reason="embedded server base URL not available")
def test_logo_assets_served_with_real_image_types():
    """The brand helper fetches /phins-logo.png for the jsPDF letterhead;
    under X-Content-Type-Options: nosniff both logo assets must be served
    with their real image mime types."""
    base = os.environ["TEST_BASE_URL"].rstrip("/")
    with urlopen(Request(base + "/phins-logo.png")) as resp:
        assert resp.status == 200
        assert resp.headers.get("Content-Type") == "image/png"
        assert resp.read(8) == b"\x89PNG\r\n\x1a\n"
    with urlopen(Request(base + "/phins-logo.svg")) as resp:
        assert resp.status == 200
        assert (resp.headers.get("Content-Type") or "").startswith("image/svg+xml")


def test_actuary_briefing_pdf_regenerated_with_letterhead():
    pdf = INTERNAL / "exec-actuary-briefing.pdf"
    assert pdf.is_file()
    data = pdf.read_bytes()
    assert data[:5] == b"%PDF-"
    assert b"%%EOF" in data[-2048:]
    # the branded regeneration embeds the shield raster (image XObject);
    # the pre-branding render had no images at all
    assert b"/Image" in data, "briefing PDF missing the letterhead logo image"
