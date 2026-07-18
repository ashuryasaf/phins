"""
Tests for the Israel regulatory application memorandum (EN + HE) surfaced on
the pitch dashboard's Israel section with downloadable PDFs.

Covers:
- the generator (``scripts/generate_investor_pdfs.py``) lists both language
  versions, marks the Hebrew one RTL, and ``--check`` passes,
- the shipped PDFs exist and are valid,
- the canonical markdown keeps the real product parameters (1:4 contract
  ratio, 3+ ADL trigger, age-65 disability cut-off, filed table anchors), and
- the pitch dashboard links both documents with downloadable PDFs.
"""

import importlib.util
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
STATIC = REPO / "web_portal" / "static"
DOCS = STATIC / "investor-docs"

EN_MD = DOCS / "israel-regulatory-application-en.md"
HE_MD = DOCS / "israel-regulatory-application-he.md"
EN_PDF = DOCS / "israel-regulatory-application-en.pdf"
HE_PDF = DOCS / "israel-regulatory-application-he.pdf"


def _load_generator():
    spec = importlib.util.spec_from_file_location(
        "generate_investor_pdfs", REPO / "scripts" / "generate_investor_pdfs.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_generator_lists_both_language_versions():
    mod = _load_generator()
    srcs = {src for src, _pdf, _title in mod.DOCUMENTS}
    outs = {pdf for _src, pdf, _title in mod.DOCUMENTS}
    assert "investor-docs/israel-regulatory-application-en.md" in srcs
    assert "investor-docs/israel-regulatory-application-he.md" in srcs
    assert "investor-docs/israel-regulatory-application-en.pdf" in outs
    assert "investor-docs/israel-regulatory-application-he.pdf" in outs
    # the Hebrew version is rendered right-to-left
    assert "investor-docs/israel-regulatory-application-he.md" in mod.RTL_DOCUMENTS
    assert "investor-docs/israel-regulatory-application-en.md" not in mod.RTL_DOCUMENTS


def test_generator_check_passes():
    mod = _load_generator()
    assert mod.main(["--check"]) == 0


def test_pdfs_are_valid():
    for pdf in (EN_PDF, HE_PDF):
        assert pdf.is_file(), f"{pdf.name} was not generated"
        data = pdf.read_bytes()
        assert data[:5] == b"%PDF-", f"{pdf.name}: not a valid PDF header"
        assert b"%%EOF" in data[-2048:], f"{pdf.name}: missing PDF EOF marker"
        assert len(data) > 4096, f"{pdf.name}: PDF unexpectedly small"


def test_markdown_preserves_real_product_parameters():
    """Both language versions must describe the real PHINS product — life
    insurance with a disability mechanism at the 1:4 contract ratio — and the
    filed actuarial table anchors."""
    en = EN_MD.read_text(encoding="utf-8")
    he = HE_MD.read_text(encoding="utf-8")

    for needle in ("L ÷ 4", "1:4", "3+ ADL", "Section 40", "0.25", "0.20",
                   "age 65", "f(3) = 0.30", "f(25) = 1.00", "f(80) = 2.50",
                   "3.5%", "15%", "10%", "V2.0", "500,000", "125,000"):
        assert needle in en, f"EN memo missing canonical parameter {needle!r}"

    for needle in ("L ÷ 4", "1:4", "3+ ADL", "סעיף 40", "רשות שוק ההון",
                   "ביטוח חיים", "גיל 65", "f(3) = 0.30", "f(80) = 2.50",
                   "V2.0", "500,000", "125,000"):
        assert needle in he, f"HE memo missing canonical parameter {needle!r}"

    # pure-risk statement (no savings / surrender value) present in both
    assert "no cash or surrender value" in en.lower() or "no cash" in en.lower()
    assert "ערך פדיון" in he


def test_markdown_uses_filed_actuarial_tables():
    """The filed rates must match the platform's central V2.0 tables."""
    en = EN_MD.read_text(encoding="utf-8")
    # mortality per-1000 anchors
    for rate in ("0.5", "1.2", "2.5", "5.0", "12.0", "30.0", "75.0"):
        assert rate in en, f"missing mortality anchor {rate}"
    # disability incidence per-1000 anchors
    for rate in ("2.0", "4.0", "8.0", "15.0", "50.0", "80.0"):
        assert rate in en, f"missing disability incidence anchor {rate}"
    # lapse anchors
    for rate in ("8%", "5%", "4%", "3%", "2%", "1%"):
        assert rate in en, f"missing lapse anchor {rate}"


def test_hebrew_renders_right_to_left():
    """Regression: Hebrew must be drawn in visual (right-to-left) order.

    reportlab's ``wordWrap='RTL'`` is a silent no-op without the proprietary
    ``rlbidi`` package, which rendered the Hebrew memo mirrored. The
    generator now bidi-reorders each wrapped line itself, so the draw string
    of a Hebrew paragraph must be the visual form (per-line reversal of the
    logical text).
    """
    pytest.importorskip("bidi", reason="python-bidi needed for RTL rendering")
    mod = _load_generator()
    styles = mod._rtl_styles()

    # single line: logical "שלום עולם" draws as "םלוע םולש" (fully mirrored)
    para = mod._rtl_paragraph("שלום עולם", styles["body"], 400)
    assert para.text == "םלוע םולש"

    # multi-line: wrapping happens on the logical text BEFORE the bidi pass,
    # so the first visual line contains the beginning of the sentence
    long_text = "פינס מבקשת אישור לתוכנית ביטוח חיים אחת עם מנגנון נכות קבועה"
    narrow = mod._rtl_paragraph(long_text, styles["body"], 150)
    lines = narrow.text.split("<br/>")
    assert len(lines) > 1
    assert lines[0].endswith("סניפ")  # visual form of leading word "פינס"

    # RTL styles must not rely on reportlab's no-op wordWrap='RTL'
    assert styles["body"].wordWrap != "RTL"

    # numbers / Latin stay left-to-right inside the RTL line
    mixed = mod._rtl_paragraph("יחס חוזי 1:4 לפי סעיף 40", styles["body"], 400)
    assert "1:4" in mixed.text and "40" in mixed.text


def test_dashboard_links_documents_with_downloadable_pdfs():
    pd = (STATIC / "pitch-dashboard.html").read_text(encoding="utf-8")
    assert "/investor-docs/israel-regulatory-application-en.pdf" in pd
    assert "/investor-docs/israel-regulatory-application-he.pdf" in pd
    # explicit downloadable links for both languages
    assert ('/investor-docs/israel-regulatory-application-en.pdf" target="_blank" '
            'rel="noopener" class="exec-dl-btn" download') in pd
    assert ('/investor-docs/israel-regulatory-application-he.pdf" target="_blank" '
            'rel="noopener" class="exec-dl-btn" download') in pd
    # canonical markdown sources remain linked
    assert "/investor-docs/israel-regulatory-application-en.md" in pd
    assert "/investor-docs/israel-regulatory-application-he.md" in pd
