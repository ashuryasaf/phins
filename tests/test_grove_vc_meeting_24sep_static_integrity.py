"""
Static-integrity tests for the 24 September 2026 Grove VC follow-up.

The call is a 30-minute Zoom 1:1 with Mr. Lotan Levkovitch — Partner, Grove VC,
the same host as the 19 August 2026 investor evening. Figures must match the
Investor Meeting book and the seeded Meeting Diary.
"""

import importlib
import importlib.util
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
STATIC = REPO / "web_portal" / "static"
DOCS = STATIC / "investor-docs"
STEM = "grove-vc-meeting-24sep-brief"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _section(pd: str) -> str:
    start = pd.index('id="grove-vc-meeting-24sep"')
    end = pd.index('id="aspire-invest-meeting-sep2026"', start)
    return pd[start:end]


def _load_generator():
    spec = importlib.util.spec_from_file_location(
        "generate_investor_pdfs", REPO / "scripts" / "generate_investor_pdfs.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_pitch_dashboard_section_and_nav():
    pd = _read(STATIC / "pitch-dashboard.html")
    assert 'id="grove-vc-meeting-24sep"' in pd
    assert 'href="#grove-vc-meeting-24sep"' in pd
    section = _section(pd)
    assert "24 September 2026" in section
    assert "Lotan Levkovitch" in section
    assert "Grove VC" in section
    assert "Zoom" in section
    assert "30 minutes" in section or "30-minute" in section
    assert 'href="#grove-vc-meeting-19aug"' in section
    assert 'href="#investor-meeting-section"' in section
    assert 'href="#il-meeting-diary"' in section


def test_scope_is_system_regulation_technology_and_investment():
    section = _section(_read(STATIC / "pitch-dashboard.html")).lower()
    for topic in (
        "modified system",
        "regulatory",
        "technology",
        "deep tech",
        "underwriting",
        "billing",
        "claims",
        "gate 5",
        "1 january 2027",
    ):
        assert topic in section, topic


def test_thirty_minute_run_of_show():
    section = _section(_read(STATIC / "pitch-dashboard.html"))
    for timebox in ("00–03", "03–09", "09–16", "16–22", "22–27", "27–30"):
        assert timebox in section, timebox


def test_figures_match_investor_meeting_book():
    section = _section(_read(STATIC / "pitch-dashboard.html"))
    for needle in (
        "₪6.0M",
        "₪24M",
        "₪30M",
        "ILS 4,518",
        "24,000 / 94,080 / 230,554",
        "12,000 / 59,040 / 162,317",
        "54,216,000",
        "266,742,720",
        "733,348,206",
        "13,554,000",
        "66,685,680",
        "183,337,052",
        "25%",
        "40.3%",
        "14.7%",
        "11.7%",
    ):
        assert needle in section, needle
    # Identity: average in-force × 4,518 = risk GWP; 25% is PHINS net.
    assert 12000 * 4518 == 54216000
    assert 59040 * 4518 == 266742720
    assert 162317 * 4518 == 733348206
    assert round(54216000 * 0.25) == 13554000
    assert round(266742720 * 0.25) == 66685680
    assert round(733348206 * 0.25) == 183337052
    # Build shares on a ₪6,000,000 round.
    shares = (0.403, 0.147, 0.087, 0.072, 0.108, 0.067, 0.117)
    assert abs(sum(shares) - 1.0) < 0.002


def test_diary_seeds_the_follow_up_and_bumps_storage():
    pd = _read(STATIC / "pitch-dashboard.html")
    assert 'var STORAGE_ID = "phins.il.meeting.diary.v8"' in pd
    assert "2026-09-24" in pd
    assert "Mr. Lotan Levkovitch — Partner, Grove VC (1:1 follow-up)" in pd
    assert "TBC · 30 min" in pd
    assert "Zoom" in pd
    assert "grove-vc-meeting-24sep-brief.pdf" in pd
    assert '"grove-vc-meeting-24sep"' in pd


def test_generator_includes_follow_up_brief():
    mod = _load_generator()
    srcs = {src for src, _pdf, _title in mod.DOCUMENTS}
    outs = {pdf for _src, pdf, _title in mod.DOCUMENTS}
    md = f"investor-docs/{STEM}.md"
    pdf = f"investor-docs/{STEM}.pdf"
    assert md in srcs
    assert pdf in outs
    assert md not in mod.RTL_DOCUMENTS
    assert not mod._source_has_hebrew(str(DOCS / f"{STEM}.md"))


def test_follow_up_brief_markdown():
    md = (DOCS / f"{STEM}.md").read_text(encoding="utf-8")
    assert "24 September 2026" in md
    assert "Lotan Levkovitch" in md
    assert "Grove" in md
    assert "Elevator" in md
    assert "Decision outputs" in md
    assert "hard timebox" in md.lower()
    for needle in ("4,518", "6.0M", "24M", "30M", "24,000 / 94,080 / 230,554"):
        assert needle in md, needle


def test_follow_up_brief_pdf_is_valid():
    pdf_path = DOCS / f"{STEM}.pdf"
    assert pdf_path.is_file()
    data = pdf_path.read_bytes()
    assert data[:5] == b"%PDF-"
    assert b"%%EOF" in data[-2048:]
    assert len(data) > 4096


def test_follow_up_brief_pdf_preserves_content():
    pdf_path = DOCS / f"{STEM}.pdf"
    md = (DOCS / f"{STEM}.md").read_text(encoding="utf-8")
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
    for needle in ("Lotan Levkovitch", "Grove", "24 September 2026"):
        assert needle in md
        assert needle in text
