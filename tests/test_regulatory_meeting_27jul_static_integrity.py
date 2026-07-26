"""
Static-integrity tests for the 27 July 2026 regulatory meeting pack.

One meeting is pinned to the IL pitch dashboard:
- 27 July 2026 (30 minutes, hard timebox) with Herzog Fox Neeman & Co.
  Advocates — regulatory manager Mrs. Neta Dorfman Raviv. Scope: introduction
  to the platform and product regulatory posture, IP protection, B2B
  contracts, and the global view, based on the PHINS business plan and the
  published Israel regulatory application memorandum (Hebrew canonical).

These tests read the shipped static assets (no server required) and assert:
- the pitch dashboard carries the Regulatory Meeting section with a timeboxed
  30-minute run of show covering all four scope topics,
- the section links the Hebrew regulatory application PDF (and the assets it
  references actually ship with the portal),
- the meeting is seeded in the admin meeting diary defaults.
"""

import importlib
import importlib.util
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
STATIC = REPO / "web_portal" / "static"
BRIEF_MD = STATIC / "investor-docs" / "regulatory-meeting-27jul-brief.md"
BRIEF_PDF = STATIC / "investor-docs" / "regulatory-meeting-27jul-brief.pdf"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Pitch dashboard — Regulatory Meeting section
# ---------------------------------------------------------------------------

def test_pitch_dashboard_regulatory_meeting_section():
    pd = _read(STATIC / "pitch-dashboard.html")
    # section + nav link
    assert 'id="regulatory-meeting-27jul"' in pd
    assert '#regulatory-meeting-27jul' in pd
    assert "Regulatory Meeting — 27 July 2026" in pd
    # counterparty and regulatory manager
    assert "Herzog Fox Neeman" in pd
    assert "Neta Dorfman Raviv" in pd
    # 30-minute framing
    assert "30 minutes" in pd
    assert "30-minute" in pd


def test_regulatory_meeting_scope_topics():
    pd = _read(STATIC / "pitch-dashboard.html").lower()
    # all four requested scope topics present
    for topic in ("product regulatory", "ip protection", "b2b contracts",
                  "global view"):
        assert topic in pd, f"missing scope topic: {topic}"


def test_regulatory_meeting_30_minute_run_of_show():
    pd = _read(STATIC / "pitch-dashboard.html")
    assert 'id="reg-30m-timeline"' in pd
    # productive, timeboxed segments summing to exactly 30 minutes
    for timebox in ("00–03", "03–09", "09–15", "15–21", "21–27", "27–30"):
        assert timebox in pd, f"missing timebox: {timebox}"
    assert "hard timebox" in pd
    assert "Wrap-up" in pd


def test_regulatory_meeting_prep_and_outputs():
    pd = _read(STATIC / "pitch-dashboard.html")
    assert 'id="reg-scope-panel"' in pd
    assert 'id="reg-elevator"' in pd
    assert 'id="reg-outputs"' in pd
    assert "Elevator pitch" in pd
    assert "Decision outputs" in pd


def test_regulatory_meeting_links_source_documents():
    pd = _read(STATIC / "pitch-dashboard.html")
    # anchored to the published regulatory application (HE canonical + EN)
    assert "/investor-docs/israel-regulatory-application-he.pdf" in pd
    assert "/investor-docs/israel-regulatory-application-en.pdf" in pd
    # anchored to the PHINS business plan
    assert "/internal/phins-investor-business-plan.html" in pd
    # the referenced assets actually ship with the portal
    assert (STATIC / "investor-docs" /
            "israel-regulatory-application-he.pdf").is_file()
    assert (STATIC / "investor-docs" /
            "israel-regulatory-application-en.pdf").is_file()
    assert (STATIC / "internal" /
            "phins-investor-business-plan.html").is_file()


# ---------------------------------------------------------------------------
# Admin meeting diary — seeded defaults
# ---------------------------------------------------------------------------

def test_diary_seeds_27jul_regulatory_meeting():
    pd = _read(STATIC / "pitch-dashboard.html")
    assert '2026-07-27' in pd
    # the diary row references the counterparty, duration, and pack
    assert ("Herzog Fox Neeman & Co. Advocates — "
            "Mrs. Neta Dorfman Raviv (Regulatory Manager)") in pd
    assert "30 min" in pd
    assert "Regulatory Meeting 27.7 section" in pd


# ---------------------------------------------------------------------------
# Downloadable meeting brief PDF
# ---------------------------------------------------------------------------

def _load_generator():
    spec = importlib.util.spec_from_file_location(
        "generate_investor_pdfs", REPO / "scripts" / "generate_investor_pdfs.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_generator_includes_meeting_brief():
    mod = _load_generator()
    srcs = {src for src, _pdf, _title in mod.DOCUMENTS}
    outs = {pdf for _src, pdf, _title in mod.DOCUMENTS}
    assert "investor-docs/regulatory-meeting-27jul-brief.md" in srcs
    assert "investor-docs/regulatory-meeting-27jul-brief.pdf" in outs
    # brief stays LTR-only so regeneration never needs the Hebrew/bidi path
    assert "investor-docs/regulatory-meeting-27jul-brief.md" not in mod.RTL_DOCUMENTS
    assert not mod._source_has_hebrew(str(BRIEF_MD))


def test_generator_check_passes():
    mod = _load_generator()
    assert mod.main(["--check"]) == 0


def test_meeting_brief_markdown_carries_the_pack():
    md = BRIEF_MD.read_text(encoding="utf-8")
    assert "27 July 2026" in md
    assert "Herzog Fox Neeman & Co. Advocates" in md
    assert "Mrs. Neta Dorfman Raviv" in md
    for topic in ("product regulatory", "IP protection", "B2B contracts",
                  "global view"):
        assert topic.lower() in md.lower(), f"missing scope topic: {topic}"
    for timebox in ("00–03", "03–09", "09–15", "15–21", "21–27", "27–30"):
        assert timebox in md, f"missing timebox: {timebox}"
    assert "/investor-docs/israel-regulatory-application-he.pdf" in md


def test_meeting_brief_pdf_is_valid():
    assert BRIEF_PDF.is_file(), "meeting brief PDF was not generated"
    data = BRIEF_PDF.read_bytes()
    assert data[:5] == b"%PDF-", "not a valid PDF header"
    assert b"%%EOF" in data[-2048:], "missing PDF EOF marker"
    assert len(data) > 4096, "PDF unexpectedly small"


def test_meeting_brief_pdf_preserves_content():
    """The PDF is generated from the markdown, so the meeting facts the
    counterparty pack shows must reconcile to the canonical source."""
    PdfReader = None
    for name in ("pypdf", "PyPDF2"):
        try:
            PdfReader = importlib.import_module(name).PdfReader
            break
        except Exception:
            continue
    if PdfReader is None:
        pytest.skip("no PDF text-extraction library available")

    reader = PdfReader(str(BRIEF_PDF))
    text = "\n".join((page.extract_text() or "") for page in reader.pages)
    md = BRIEF_MD.read_text(encoding="utf-8")

    for needle in ("Herzog Fox Neeman", "Neta Dorfman Raviv", "27 July 2026",
                   "IP protection", "B2B contracts", "Wrap-up"):
        assert needle in md, f"canonical markdown drifted, missing {needle!r}"
        assert needle in text, f"PDF missing canonical content {needle!r}"


def test_dashboard_offers_meeting_brief_pdf():
    pd = _read(STATIC / "pitch-dashboard.html")
    # open action points at the PDF
    assert ('/investor-docs/regulatory-meeting-27jul-brief.pdf" target="_blank"'
            ' rel="noopener" class="exec-dl-btn">📄 Open Meeting Brief') in pd
    # an explicit downloadable PDF link is present
    assert ('/investor-docs/regulatory-meeting-27jul-brief.pdf" target="_blank"'
            ' rel="noopener" class="exec-dl-btn" download') in pd
