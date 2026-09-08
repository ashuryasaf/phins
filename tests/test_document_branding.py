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
    assert "פלטפורמת ביטוח מופעלת־AI" in js
    # gold / navy brand palette (RGB of #c9a04e and #0e2f63)
    assert "201, 160, 78" in js
    assert "14, 47, 99" in js
    # public API used by the generators
    for api in ("letterhead", "finalize", "preload", "PhinsPdfBrand",
                "preloadDocumentFonts", "applyDocumentFont",
                "toVisual", "wrapToVisual", "installRtlPainter"):
        assert api in js, f"helper missing API {api}"
    # chrome-only contract stated in the module
    assert "chrome ONLY" in js
    assert "/fonts/DejaVuSans.ttf" in js


def test_hebrew_pdf_converts_rtl_once_and_keeps_latin_acronyms():
    """Visual Hebrew is ours; jsPDF must not bidi again (that produced AGM/MAT)."""
    js = _read(STATIC / "phins-pdf-brand.js")
    lab = _read(STATIC / "phins-scenario-lab-pdf.js")
    assert "function toVisual" in js
    assert "function reverseRange" in js
    assert "disableJsPdfAutoBidi" in js
    assert "isInputVisual = true" in js
    assert "isOutputVisual = true" in js
    assert "isInputRtl = true" in js
    assert "isOutputRtl = true" in js
    assert "payload.text = original" not in js
    assert "installRtlPainter" in js
    assert "brand.installRtlPainter(doc)" in lab
    assert "brand.toVisual(text, true)" in lab
    assert "toVisual(pageText, rtl)" in js
    assert "מודל MGA" in lab
    assert "תמונת TAM" in lab
    assert "כ־MGA" in lab
    assert "ה־TAM" in lab
    assert "isInputRtl: true" not in js


def test_hebrew_tovisual_keeps_mga_tam_and_mirrors_hebrew_runs():
    """Load the brand helper and pin mixed-script visual order."""
    import json
    import shutil
    import subprocess

    node = shutil.which("node")
    if not node:
        pytest.skip("node is required to execute phins-pdf-brand.js")
    script = r"""
const fs = require('fs');
const vm = require('vm');
const code = fs.readFileSync(process.env.PHINS_BRAND_JS, 'utf8');
const ctx = {
  window: {},
  fetch: function () { return Promise.resolve({ ok: false }); }
};
vm.createContext(ctx);
vm.runInContext(code, ctx);
const tv = ctx.window.PhinsPdfBrand.toVisual;
if (typeof tv !== 'function') throw new Error('toVisual missing');
const samples = {
  mga: tv('מודל MGA', true),
  tam: tv('תמונת TAM', true),
  mgaHyphen: tv('כ-MGA', true),
  tamHyphen: tv('ה-TAM', true),
  mgaMaqaf: tv('כ־MGA', true),
  tamMaqaf: tv('ה־TAM', true),
  ai: tv('מופעלת-AI', true),
  aiMaqaf: tv('מופעלת־AI', true),
  footer: tv('פינס — מעבדת תרחישים · מסמך משקיעים חסוי', true),
  tagline: tv('פלטפורמת ביטוח מופעלת־AI · ביטוח בריאות אישי וחיסכון', true),
  page: tv('עמוד 1 מתוך 6', true)
};
console.log(JSON.stringify(samples));
"""
    proc = subprocess.run(
        [node, "-e", script],
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, "PHINS_BRAND_JS": str(STATIC / "phins-pdf-brand.js")},
    )
    samples = json.loads(proc.stdout)
    assert "MGA" in samples["mga"] and "AGM" not in samples["mga"]
    assert "TAM" in samples["tam"] and "MAT" not in samples["tam"]
    assert "MGA" in samples["mgaHyphen"] and "AGM" not in samples["mgaHyphen"]
    assert "TAM" in samples["tamHyphen"] and "MAT" not in samples["tamHyphen"]
    assert "MGA" in samples["mgaMaqaf"] and "AGM" not in samples["mgaMaqaf"]
    assert "TAM" in samples["tamMaqaf"] and "MAT" not in samples["tamMaqaf"]
    assert "AI" in samples["ai"] and "IA" not in samples["ai"]
    assert "AI" in samples["aiMaqaf"] and "IA" not in samples["aiMaqaf"]
    # Visual-order paint: Hebrew runs reverse, Latin stays.
    assert "סניפ" in samples["footer"]
    assert "פינס" not in samples["footer"]
    assert "MGA" not in samples["footer"]
    assert "AI" in samples["tagline"] and "IA" not in samples["tagline"]
    # Page "עמוד 1 מתוך 6" must paint visual so it does not read as ךותמ / דומע.
    assert "דומע" in samples["page"]
    assert "ךותמ" in samples["page"]
    assert "1" in samples["page"] and "6" in samples["page"]
    assert "עמוד" not in samples["page"]
    assert "מתוך" not in samples["page"]



def test_pitch_dashboard_loads_brand_helper():
    pd = _read(STATIC / "pitch-dashboard.html")
    assert '<script src="/phins-pdf-brand.js"></script>' in pd
    assert '<script src="/phins-scenario-lab-pdf.js"></script>' in pd


def test_pitch_dashboard_generators_use_brand_helper():
    pd = _read(STATIC / "pitch-dashboard.html")
    lab = _read(STATIC / "phins-scenario-lab-pdf.js")
    # four client-generated PDFs: exec summary, country pitch, tech-investor
    # plan stay inline; the scenario-lab assessment lives in the shared module
    assert pd.count("window.PhinsPdfBrand.letterhead(doc") == 3
    assert pd.count("window.PhinsPdfBrand.finalize(doc") == 3
    assert "brand.letterhead(doc" in lab
    assert "brand.finalize(doc" in lab
    # branded titles per generator
    assert '"PHINS Platform — Executive Summary"' in pd
    assert "PHINS Scenario Lab — Market Assessment" in lab
    assert '"PHINS — " + m.d.name + " — Investor Pitch"' in pd
    assert '"PHINS Technologies — Technology Investor Business Plan"' in pd
    # generators fail closed when the helper is unavailable
    assert pd.count("|| !window.PhinsPdfBrand") == 4


def test_pitch_dashboard_generator_data_unchanged():
    """Branding must not alter the generated document data."""
    pd = _read(STATIC / "pitch-dashboard.html")
    lab = _read(STATIC / "phins-scenario-lab-pdf.js")
    # canonical data anchors of the four generators are untouched
    assert "phins-executive-summary.pdf" in pd
    assert "phins-scenario-lab-" in lab
    assert "phins-investor-pitch-" in pd
    assert "phins-tech-investor-business-plan.pdf" in pd
    assert "Data integrity notice" in pd
    assert "public evidence stays locked" in lab


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
    "phins-investment-deck.html",
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
def test_unicorn_gradient_text_has_print_fallback(fname):
    """Gradient headlines (background-clip:text + transparent fill) are
    invisible in most print/PDF renderers — the gradient paints as a block
    behind transparent glyphs. Every deck that uses the technique must carry
    a solid-color print override so titles stay legible in the saved PDF."""
    doc = _read(STATIC / fname)
    if "text-fill-color: transparent" not in doc:
        pytest.skip(f"{fname} uses no gradient text")
    assert "-webkit-text-fill-color:" in doc.split("@media print", 1)[-1], \
        f"{fname} missing print fallback for gradient text"
    # the override must re-assert an opaque fill
    assert doc.count("text-fill-color: transparent") >= 1
    assert ("!important" in doc.split("@media print", 1)[-1])


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


# ---------------------------------------------------------------------------
# Unicorn report series — adjustable operating cost + platform-refresh claims
# ---------------------------------------------------------------------------

def test_deck_module_count_claims_match_service_layer():
    """The report series quotes the number of deployed service modules; keep
    the claim reconciled to the actual service layer so the decks never
    overstate (or silently understate) the platform."""
    services = Path(__file__).resolve().parents[1] / "services"
    count = len(list(services.glob("*.py")))
    for fname in ("unicorn-investor-deck.html", "unicorn-executive-summary.html",
                  "seed-investor-deck.html"):
        doc = _read(STATIC / fname)
        assert "64+" not in doc, f"{fname} still carries the stale 64+ module claim"
        assert f"{count} service module" in doc or f"{count} deployed service" in doc \
            or f"{count}-service-module" in doc, \
            f"{fname} module-count claim out of sync with services/ ({count})"


@pytest.mark.parametrize("fname", ["unicorn-investor-deck.html",
                                   "seed-investor-deck.html"])
def test_deck_operating_cost_is_adjustable(fname):
    doc = _read(STATIC / fname)
    # configurator inputs
    assert 'id="c-opexfix"' in doc, f"{fname} missing fixed-opex control"
    assert 'id="c-opexvar"' in doc, f"{fname} missing variable-opex control"
    # persisted state + factors applied in compute()
    assert "opexFixPct" in doc and "opexVarPct" in doc
    assert "BASE.opexFixed[i] * ofx" in doc
    assert "BASE.opexVar[i] * m * ovr" in doc
    # defaults preserve the canonical base (100% = identity)
    assert 'value="100"' in doc
    assert "opexFixPct: 100" in doc and "opexVarPct: 100" in doc
    # the modeled EBITDA-positive year follows the adjusted cost side
    assert "ebitdaPosYear" in doc


def test_unicorn_deck_runway_and_kpis_follow_opex():
    doc = _read(STATIC / "unicorn-investor-deck.html")
    # dynamic runway row (was a static "EBITDA-positive by 2030 (base)" label)
    assert 'data-calc="cap_runway_v"' in doc
    assert 'data-i18n="cap_r_runway_v"' not in doc
    # 2031 operating cost KPI surfaced next to revenue/EBITDA
    assert 'data-calc="kpi_opex31"' in doc
    # integrity notice lists operating-cost factors among base assumptions
    assert "operating-cost factors" in doc


def test_seed_deck_ebitda_positive_year_is_dynamic():
    doc = _read(STATIC / "seed-investor-deck.html")
    assert doc.count('data-calc="ebitda_pos"') >= 2  # cover metric + unicorn note


def test_series_reflects_agentos_v1_and_momentum():
    """The decks must reflect platform reality: AgentOS v1 shipped after the
    deck was originally assembled, plus the June–July 2026 momentum items."""
    deck = _read(STATIC / "unicorn-investor-deck.html")
    assert "AgentOS v1" in deck
    assert 'data-i18n="prod_momentum"' in deck
    for anchor in ("ledger-anchored commission", "actuarial appraisal simulation",
                   "regulatory application memorandum", "Draft 3.1"):
        assert anchor in deck, f"unicorn deck missing momentum anchor: {anchor}"
    summary = _read(STATIC / "unicorn-executive-summary.html")
    assert "AgentOS v1" in summary
    assert "regulatory application memorandum" in summary
    assert "Draft 3.1" in summary
    seed = _read(STATIC / "seed-investor-deck.html")
    assert "AgentOS v1" in seed


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


@pytest.mark.skipif(not os.environ.get("TEST_BASE_URL"),
                    reason="embedded server base URL not available")
def test_document_fonts_served_with_font_ttf():
    """Hebrew Scenario Lab PDFs fetch /fonts/DejaVuSans.ttf under nosniff."""
    base = os.environ["TEST_BASE_URL"].rstrip("/")
    for name in ("DejaVuSans.ttf", "DejaVuSans-Bold.ttf"):
        with urlopen(Request(base + "/fonts/" + name)) as resp:
            assert resp.status == 200
            assert resp.headers.get("Content-Type") == "font/ttf"
            assert resp.read(4) == b"\x00\x01\x00\x00"


def test_actuary_briefing_pdf_regenerated_with_letterhead():
    pdf = INTERNAL / "exec-actuary-briefing.pdf"
    assert pdf.is_file()
    data = pdf.read_bytes()
    assert data[:5] == b"%PDF-"
    assert b"%%EOF" in data[-2048:]
    # the branded regeneration embeds the shield raster (image XObject);
    # the pre-branding render had no images at all
    assert b"/Image" in data, "briefing PDF missing the letterhead logo image"
