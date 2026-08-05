"""
Static-integrity tests for the August 2026 VC meeting packs.

Three meetings are pinned to the IL pitch dashboard:
- 5 August 2026 (13:00, 20 min) with Mrs. Orna Carni — Partner, Fintl VC
  (founder, technology, regulation)
- 6 August 2026 (13:00, 20 min) with Mrs. Orna Carni — Partner, Fintl VC
  (technology, regulation, funding, actuary)
- 19 August 2026 (19:00, 5 min) with Mr. Lotan Levkovitch — Partner, Grove VC
  (founder, technology, regulation, funding)

These tests read the shipped static assets (no server required) and assert:
- the pitch dashboard carries short presentation sections for each meeting,
- downloadable brief PDFs are linked and registered in the generator,
- the meetings are seeded in the admin meeting diary defaults.
"""

import importlib
import importlib.util
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
STATIC = REPO / "web_portal" / "static"
DOCS = STATIC / "investor-docs"

BRIEFS = [
    ("fintl-vc-meeting-5aug-brief", "5 August 2026", "Orna Carni", "Fintl"),
    ("fintl-vc-meeting-6aug-brief", "6 August 2026", "Orna Carni", "Fintl"),
    ("grove-vc-meeting-19aug-brief", "19 August 2026", "Lotan Levkovitch", "Grove"),
]


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _load_generator():
    spec = importlib.util.spec_from_file_location(
        "generate_investor_pdfs", REPO / "scripts" / "generate_investor_pdfs.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Pitch dashboard — sections & nav
# ---------------------------------------------------------------------------

def test_pitch_dashboard_fintl_vc_section():
    pd = _read(STATIC / "pitch-dashboard.html")
    assert 'id="fintl-vc-meetings-aug"' in pd
    assert "#fintl-vc-meetings-aug" in pd
    assert "Fintl VC Meetings — 5 &amp; 6 August 2026" in pd
    assert "Orna Carni" in pd
    assert "Fintl VC" in pd
    assert 'id="fintl-5aug-panel"' in pd
    assert 'id="fintl-6aug-panel"' in pd


def test_pitch_dashboard_grove_vc_section():
    pd = _read(STATIC / "pitch-dashboard.html")
    assert 'id="grove-vc-meeting-19aug"' in pd
    assert "#grove-vc-meeting-19aug" in pd
    assert "Grove VC Meeting — 19 August 2026" in pd
    assert "Lotan Levkovitch" in pd
    assert "Grove VC" in pd
    assert 'id="grove-5m-timeline"' in pd
    assert "5-minute" in pd or "5 minutes" in pd


def test_fintl_meeting_scope_topics():
    pd = _read(STATIC / "pitch-dashboard.html")
    # Meeting 1 topics
    fintl = pd[pd.index('id="fintl-vc-meetings-aug"'):pd.index('id="grove-vc-meeting-19aug"')]
    for topic in ("founder", "technology", "regulation", "funding", "actuary"):
        assert topic in fintl.lower(), f"missing Fintl scope topic: {topic}"


def test_grove_meeting_scope_topics():
    pd = _read(STATIC / "pitch-dashboard.html")
    grove = pd[pd.index('id="grove-vc-meeting-19aug"'):pd.index('id="exec-summary-section"')]
    for topic in ("founder", "technology", "regulation", "funding"):
        assert topic in grove.lower(), f"missing Grove scope topic: {topic}"


def test_fintl_20_minute_run_of_show():
    pd = _read(STATIC / "pitch-dashboard.html")
    # 5 Aug timeboxes
    for timebox in ("00–03", "03–08", "08–14", "14–18", "18–20"):
        assert timebox in pd, f"missing 5 Aug timebox: {timebox}"
    # 6 Aug timeboxes
    for timebox in ("00–02", "02–07", "07–11", "11–16", "16–19", "19–20"):
        assert timebox in pd, f"missing 6 Aug timebox: {timebox}"


def test_grove_5_minute_run_of_show():
    pd = _read(STATIC / "pitch-dashboard.html")
    for timebox in ("00–01", "01–02:30", "02:30–03:30", "03:30–04:30", "04:30–05:00"):
        assert timebox in pd, f"missing Grove timebox: {timebox}"


# ---------------------------------------------------------------------------
# Admin meeting diary — seeded defaults
# ---------------------------------------------------------------------------

def test_diary_seeds_aug_vc_meetings():
    pd = _read(STATIC / "pitch-dashboard.html")
    assert "2026-08-05" in pd
    assert "2026-08-06" in pd
    assert "2026-08-19" in pd
    assert "Mrs. Orna Carni — Partner, Fintl VC" in pd
    assert "Mr. Lotan Levkovitch — Partner, Grove VC" in pd
    assert "13:00 · 20 min" in pd
    assert "19:00 · 5 min" in pd
    assert "fintl-vc-meeting-5aug-brief.pdf" in pd
    assert "fintl-vc-meeting-6aug-brief.pdf" in pd
    assert "grove-vc-meeting-19aug-brief.pdf" in pd
    # bumped storage key so returning browsers pick up the new seeded rows
    assert "phins.il.meeting.diary.v2" in pd


# ---------------------------------------------------------------------------
# Downloadable meeting brief PDFs
# ---------------------------------------------------------------------------

def test_generator_includes_vc_meeting_briefs():
    mod = _load_generator()
    srcs = {src for src, _pdf, _title in mod.DOCUMENTS}
    outs = {pdf for _src, pdf, _title in mod.DOCUMENTS}
    for stem, _date, _person, _firm in BRIEFS:
        md = f"investor-docs/{stem}.md"
        pdf = f"investor-docs/{stem}.pdf"
        assert md in srcs, f"generator missing {md}"
        assert pdf in outs, f"generator missing {pdf}"
        assert md not in mod.RTL_DOCUMENTS
        assert not mod._source_has_hebrew(str(DOCS / f"{stem}.md"))


def test_generator_check_passes_with_vc_briefs():
    mod = _load_generator()
    assert mod.main(["--check"]) == 0


@pytest.mark.parametrize("stem,date,person,firm", BRIEFS)
def test_meeting_brief_markdown_carries_the_pack(stem, date, person, firm):
    md_path = DOCS / f"{stem}.md"
    assert md_path.is_file(), f"missing brief markdown: {md_path.name}"
    md = md_path.read_text(encoding="utf-8")
    assert date in md
    assert person in md
    assert firm in md
    assert "Elevator pitch" in md
    assert "Decision outputs" in md
    assert "hard timebox" in md.lower() or "hard timeboxes" in md.lower()


@pytest.mark.parametrize("stem,date,person,firm", BRIEFS)
def test_meeting_brief_pdf_is_valid(stem, date, person, firm):
    pdf_path = DOCS / f"{stem}.pdf"
    assert pdf_path.is_file(), f"meeting brief PDF was not generated: {pdf_path.name}"
    data = pdf_path.read_bytes()
    assert data[:5] == b"%PDF-", "not a valid PDF header"
    assert b"%%EOF" in data[-2048:], "missing PDF EOF marker"
    assert len(data) > 4096, "PDF unexpectedly small"


@pytest.mark.parametrize("stem,date,person,firm", BRIEFS)
def test_meeting_brief_pdf_preserves_content(stem, date, person, firm):
    pdf_path = DOCS / f"{stem}.pdf"
    md_path = DOCS / f"{stem}.md"
    PdfReader = None
    for name in ("pypdf", "PyPDF2"):
        try:
            PdfReader = importlib.import_module(name).PdfReader
            break
        except Exception:
            continue
    if PdfReader is None:
        pytest.skip("no PDF text-extraction library available")

    reader = PdfReader(str(pdf_path))
    text = "\n".join((page.extract_text() or "") for page in reader.pages)
    md = md_path.read_text(encoding="utf-8")

    for needle in (person, firm, date):
        assert needle in md, f"canonical markdown drifted, missing {needle!r}"
        assert needle in text, f"PDF missing canonical content {needle!r}"


def test_dashboard_offers_vc_meeting_brief_pdfs():
    pd = _read(STATIC / "pitch-dashboard.html")
    for stem, _date, _person, _firm in BRIEFS:
        open_link = (
            f'/investor-docs/{stem}.pdf" target="_blank" rel="noopener" '
            f'class="exec-dl-btn">'
        )
        download_link = (
            f'/investor-docs/{stem}.pdf" target="_blank" rel="noopener" '
            f'class="exec-dl-btn" download'
        )
        assert open_link in pd, f"missing open link for {stem}"
        assert download_link in pd, f"missing download link for {stem}"
