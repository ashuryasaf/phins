"""
Static-integrity tests for the Authority pre-ruling meeting pack (date TBA).

The pack expands the Regulatory Meeting 27.7 outline into a regulator-facing
pre-ruling agenda pinned to the IL pitch dashboard:
- 60 minutes (hard timebox) with Mr. Avi Ovadia — Capital Market, Insurance &
  Savings Authority. Scope: pre-ruling on the PHINS insurance product; PHINS
  as a functional MGA (underwriting, billing, claims, actuary) acting as the
  managerial and operational bridge between a designated Israeli insurance
  company and an investment company (savings add-on risk — TBA); distribution
  (direct sales, collaborations, agents); adjustable actuarial methods; future
  steps (technology, policy, B2B contracts); and the future option to expand
  to other markets and become an insurance company.

These tests read the shipped static assets (no server required) and assert:
- the pitch dashboard carries the pre-ruling section with a timeboxed
  60-minute run of show covering all scope topics and the meeting goal,
- the section links the regulatory application PDFs and the 27.7 counsel
  pack it expands (and the referenced assets actually ship with the portal),
- the meeting is seeded in the admin meeting diary defaults.
"""

import importlib
import importlib.util
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
STATIC = REPO / "web_portal" / "static"
BRIEF_MD = STATIC / "investor-docs" / "regulatory-preruling-avi-ovadia-brief.md"
BRIEF_PDF = STATIC / "investor-docs" / "regulatory-preruling-avi-ovadia-brief.pdf"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Pitch dashboard — Authority Pre-Ruling section
# ---------------------------------------------------------------------------

def test_pitch_dashboard_preruling_section():
    pd = _read(STATIC / "pitch-dashboard.html")
    # section + nav link
    assert 'id="regulatory-preruling-avi-ovadia"' in pd
    assert '#regulatory-preruling-avi-ovadia' in pd
    assert "Regulatory Pre-Ruling Meeting" in pd
    # counterparty and regulator contact
    assert "Capital Market, Insurance &amp; Savings Authority" in pd
    assert "Avi Ovadia" in pd
    # 60-minute framing, date still open
    assert "60 minutes" in pd
    assert "60-minute" in pd
    assert "Date TBA" in pd


def test_preruling_scope_topics():
    pd = _read(STATIC / "pitch-dashboard.html").lower()
    # all requested scope topics present
    for topic in ("pre-ruling", "insurance product", "functional mga",
                  "underwriting", "billing", "claims", "actuar",
                  "designated israeli insurance company", "investment company",
                  "savings add-on", "direct", "collaborations", "agents",
                  "adjustable actuarial methods", "future steps",
                  "b2b contracts", "other markets",
                  "become an insurance company"):
        assert topic in pd, f"missing scope topic: {topic}"


def test_preruling_meeting_goal():
    pd = _read(STATIC / "pitch-dashboard.html").lower()
    # the meeting goal: a regulation path approving all PHINS assumptions and
    # an open discussion with the regulator on building future products
    assert "regulation path that approves all phins assumptions" in pd
    assert "future products" in pd


def test_preruling_60_minute_run_of_show():
    pd = _read(STATIC / "pitch-dashboard.html")
    assert 'id="reg-preruling-timeline"' in pd
    # productive, timeboxed segments summing to exactly 60 minutes
    for timebox in ("00–05", "05–15", "15–25", "25–32", "32–40", "40–48",
                    "48–55", "55–60"):
        assert timebox in pd, f"missing timebox: {timebox}"
    assert "hard timebox" in pd
    assert "Wrap-up" in pd


def test_preruling_mga_bridge_panel():
    pd = _read(STATIC / "pitch-dashboard.html")
    assert 'id="reg-preruling-mga-bridge"' in pd
    # the bridge table covers the operating functions PHINS runs
    for function in ("Underwriting", "Billing", "Claims", "Actuary",
                     "Savings add-on"):
        assert function in pd, f"missing MGA function: {function}"
    # risk stays with licensed counterparties
    assert "claims reserves stay on the carrier" in pd.lower()


def test_preruling_prep_and_outputs():
    pd = _read(STATIC / "pitch-dashboard.html")
    assert 'id="reg-preruling-scope-panel"' in pd
    assert 'id="reg-preruling-elevator"' in pd
    assert 'id="reg-preruling-outputs"' in pd
    assert "Elevator pitch" in pd
    assert "Decision outputs" in pd


def test_preruling_links_source_documents():
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


def test_preruling_expands_27jul_outline():
    """The pre-ruling pack expands the 27.7 counsel outline: both sections
    coexist and cross-link each other."""
    pd = _read(STATIC / "pitch-dashboard.html")
    assert 'id="regulatory-meeting-27jul"' in pd
    section = pd.split('id="regulatory-preruling-avi-ovadia"', 1)[1]
    section = section.split("</section>", 1)[0]
    assert 'href="#regulatory-meeting-27jul"' in section
    counsel = pd.split('id="regulatory-meeting-27jul"', 1)[1]
    counsel = counsel.split("</section>", 1)[0]
    assert 'href="#regulatory-preruling-avi-ovadia"' in counsel


def test_preruling_registered_in_fold_nav():
    pd = _read(STATIC / "pitch-dashboard.html")
    fold_ids = pd.split("PITCH_FOLD_IDS", 1)[1].split("];", 1)[0]
    assert '"regulatory-preruling-avi-ovadia"' in fold_ids


# ---------------------------------------------------------------------------
# Admin meeting diary — seeded defaults
# ---------------------------------------------------------------------------

def test_diary_seeds_preruling_meeting():
    pd = _read(STATIC / "pitch-dashboard.html")
    assert ("Mr. Avi Ovadia — "
            "Capital Market, Insurance & Savings Authority") in pd
    assert "60 min" in pd
    assert "/investor-docs/regulatory-preruling-avi-ovadia-brief.pdf" in pd


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


def test_generator_includes_preruling_brief():
    mod = _load_generator()
    srcs = {src for src, _pdf, _title in mod.DOCUMENTS}
    outs = {pdf for _src, pdf, _title in mod.DOCUMENTS}
    assert "investor-docs/regulatory-preruling-avi-ovadia-brief.md" in srcs
    assert "investor-docs/regulatory-preruling-avi-ovadia-brief.pdf" in outs
    # brief stays LTR-only so regeneration never needs the Hebrew/bidi path
    assert ("investor-docs/regulatory-preruling-avi-ovadia-brief.md"
            not in mod.RTL_DOCUMENTS)
    assert not mod._source_has_hebrew(str(BRIEF_MD))


def test_generator_check_passes():
    mod = _load_generator()
    assert mod.main(["--check"]) == 0


def test_preruling_brief_markdown_carries_the_pack():
    md = BRIEF_MD.read_text(encoding="utf-8")
    assert "Mr. Avi Ovadia" in md
    assert "Capital Market, Insurance & Savings Authority" in md
    assert "TBA" in md
    for topic in ("pre-ruling", "insurance product", "functional MGA",
                  "underwriting", "billing", "claims", "actuar",
                  "designated Israeli insurance company",
                  "investment company", "savings add-on",
                  "adjustable actuarial methods", "future steps",
                  "B2B contracts", "other markets",
                  "become an insurance company"):
        assert topic.lower() in md.lower(), f"missing scope topic: {topic}"
    assert ("regulation path that approves all PHINS assumptions"
            in md), "missing the meeting goal"
    for timebox in ("00–05", "05–15", "15–25", "25–32", "32–40", "40–48",
                    "48–55", "55–60"):
        assert timebox in md, f"missing timebox: {timebox}"
    assert "/investor-docs/israel-regulatory-application-he.pdf" in md


def test_preruling_brief_pdf_is_valid():
    assert BRIEF_PDF.is_file(), "meeting brief PDF was not generated"
    data = BRIEF_PDF.read_bytes()
    assert data[:5] == b"%PDF-", "not a valid PDF header"
    assert b"%%EOF" in data[-2048:], "missing PDF EOF marker"
    assert len(data) > 4096, "PDF unexpectedly small"


def test_preruling_brief_pdf_preserves_content():
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

    for needle in ("Avi Ovadia", "functional MGA", "pre-ruling",
                   "investment company", "B2B contracts", "Wrap-up"):
        assert needle in md, f"canonical markdown drifted, missing {needle!r}"
        assert needle in text, f"PDF missing canonical content {needle!r}"


def test_dashboard_offers_preruling_brief_pdf():
    pd = _read(STATIC / "pitch-dashboard.html")
    # open action points at the PDF
    assert ('/investor-docs/regulatory-preruling-avi-ovadia-brief.pdf"'
            ' target="_blank" rel="noopener" class="exec-dl-btn">📄 Open'
            ' Pre-Ruling Brief') in pd
    # an explicit downloadable PDF link is present
    assert ('/investor-docs/regulatory-preruling-avi-ovadia-brief.pdf"'
            ' target="_blank" rel="noopener" class="exec-dl-btn" download') in pd
