"""
Static-integrity tests for the September 2026 Aspire-Invest meeting pack.

The pack is pinned to the IL pitch dashboard:
- September 2026 (date TBA), 60 minutes, Aspire-Invest
  Chief Distribution & Chief Investments
- bilingual (EN + HE) business plan, 1-hour outline, and mutual NDA
- 3-year scale identity targeting up to 250,000 issued policies
- reset actuarial specimen (age 42 · F ILS 1,000,000 · ILS 4,518)
- PHINS MGA 25% separated from insurance 75%; turnover option after year 3
- technology layer separated from the first unified insurance product
- no fundraising ask and no bidding price

These tests read the shipped static assets (no server required) and assert:
- the pitch dashboard carries the meeting section, nav, charts, and diary seed,
- downloadable EN/HE PDFs are linked and registered in the generator,
- the scale-scenario arithmetic identity is internally consistent,
- reserved fundraising / bid language is absent from this pack.
"""

import importlib
import importlib.util
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
STATIC = REPO / "web_portal" / "static"
DOCS = STATIC / "investor-docs"

STEMS = [
    ("aspire-invest-meeting-sep2026-brief", False,
     "September 2026", "Aspire-Invest", "4,518"),
    ("aspire-invest-meeting-sep2026-brief-he", True,
     "ספטמבר 2026", "אספייר-אינבסט", "4,518"),
    ("aspire-invest-business-plan-sep2026", False,
     "250,000", "Unified Insurance Contract", "4,518"),
    ("aspire-invest-business-plan-sep2026-he", True,
     "250,000", "חוזה הביטוח המאוחד", "4,518"),
    ("aspire-invest-nda-sep2026", False,
     "Aspire-Invest", "Mutual", "Confidential"),
    ("aspire-invest-nda-sep2026-he", True,
     "אספייר-אינבסט", "הדדי", "סודי"),
]

# Reset actuarial identity (must hold).
NEW_ISSUES = (25_000, 75_000, 150_000)
RISK_PREMIUM = 4_518
SCALE_EOY = [24_000, 94_080, 230_554]
SCALE_AVG = [12_000, 59_040, 162_317]
SCALE_GWP = [54_216_000, 266_742_720, 733_348_206]
SCALE_PHINS = [13_554_000, 66_685_680, 183_337_052]
SCALE_INS = [40_662_000, 200_057_040, 550_011_154]
RETIRED_SCALE_GWP = ("43,200,000", "212,544,000", "584,341,200")
RETIRED_SCALE_REV = ("10,800,000", "53,136,000", "146,085,300")


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _load_generator():
    spec = importlib.util.spec_from_file_location(
        "generate_investor_pdfs", REPO / "scripts" / "generate_investor_pdfs.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _aspire_section(html: str) -> str:
    start = html.index('id="aspire-invest-meeting-sep2026"')
    end = html.index('id="exec-summary-section"')
    return html[start:end]


# ---------------------------------------------------------------------------
# Pitch dashboard — section, nav, bilingual downloads
# ---------------------------------------------------------------------------

def test_pitch_dashboard_aspire_invest_section():
    pd = _read(STATIC / "pitch-dashboard.html")
    assert 'id="aspire-invest-meeting-sep2026"' in pd
    assert "#aspire-invest-meeting-sep2026" in pd
    assert "Aspire-Invest — September 2026" in pd
    assert "Chief Distribution" in pd
    assert "Chief Investments" in pd
    assert "Hanna Hollander" in pd
    assert 'id="aspire-60min-timeline"' in pd
    assert 'id="aspire-scale-identity"' in pd
    assert 'id="aspire-charts-panel"' in pd
    assert 'id="aspire-two-layers"' in pd
    assert 'id="aspire-why-room"' in pd


def test_aspire_section_separates_technology_and_product():
    section = _aspire_section(_read(STATIC / "pitch-dashboard.html"))
    assert "Layer A" in section
    assert "Layer B" in section
    assert "Unified Insurance Contract" in section
    assert "actuarial" in section.lower()
    assert "3+ ADL" in section
    assert "not a licensed insurer" in section.lower() or "is not a licensed insurer" in section


def test_aspire_60_minute_run_of_show():
    section = _aspire_section(_read(STATIC / "pitch-dashboard.html"))
    for timebox in ("00–05", "05–12", "12–24", "24–36", "36–46", "46–55", "55–60"):
        assert timebox in section, f"missing Aspire timebox: {timebox}"
    assert "hard timebox" in section.lower() or "hard stop" in section.lower()


def test_aspire_scale_identity_numbers():
    section = _aspire_section(_read(STATIC / "pitch-dashboard.html"))
    for needle in (
        "250,000", "25,000", "75,000", "150,000",
        "24,000", "94,080", "230,554",
        "12,000", "59,040", "162,317",
        "54,216,000", "266,742,720", "733,348,206",
        "13,554,000", "66,685,680", "183,337,052",
        "40,662,000", "200,057,040", "550,011,154",
        "4,518", "25%", "75%",
        "48,794,400", "240,068,448", "660,013,385",
        "aspire-configurator", "0.20",
    ):
        assert needle in section, f"missing scale-identity figure: {needle}"
    # Retired ILS 3,600 / small-book contrast is gone — one unified book.
    for retired in RETIRED_SCALE_GWP + RETIRED_SCALE_REV:
        assert retired not in section, f"retired scale figure still in Aspire section: {retired}"
    for forbidden in (
        "do not mix the two books",
        "do not overwrite",
        "Conservative IL book",
        "conservative IL book",
        "₪3,600",
        "ILS 3,600",
        "4,000 / 12,000 / 28,000",
    ):
        assert forbidden not in section, f"two-book language still in Aspire section: {forbidden}"


def test_aspire_charts_separate_phins_and_insurance_take():
    section = _aspire_section(_read(STATIC / "pitch-dashboard.html"))
    assert 'id="aspire-charts-panel"' in section
    assert "PHINS MGA" in section
    assert "Insurance take" in section or "insurance take" in section
    assert "turnover option" in section.lower()
    assert "aspire-phins" in section
    assert "aspire-ins" in section
    assert "aspire-ins-turnover" in section
    assert "Savings flow" in section
    assert "1,000,000" in section
    assert "average age 42" in section.lower() or "age 42" in section


def test_aspire_pack_has_no_fundraise_or_bid():
    section = _aspire_section(_read(STATIC / "pitch-dashboard.html"))
    # The reserved-topics panel may mention the words in a "will not table"
    # list. The *ask itself* must not appear as a priced figure.
    for forbidden in ("₪6.0M", "₪24M", "₪30M", "6.0M seed", "24M pre", "30M post"):
        assert forbidden not in section, f"reserved figure leaked into Aspire pack: {forbidden}"
    assert "no fundraising ask" in section.lower() or "No fundraising ask" in section
    assert "no bidding price" in section.lower() or "no bid" in section.lower()


def test_dashboard_offers_bilingual_aspire_pdfs():
    pd = _read(STATIC / "pitch-dashboard.html")
    for stem, _rtl, *_rest in STEMS:
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


# ---------------------------------------------------------------------------
# Admin meeting diary — seeded default
# ---------------------------------------------------------------------------

def test_diary_seeds_aspire_invest_meeting():
    pd = _read(STATIC / "pitch-dashboard.html")
    assert "phins.il.meeting.diary.v7" in pd
    assert "Aspire-Invest — Chief Distribution" in pd
    assert "2026-09" in pd
    assert "250,000 issued" in pd
    assert "aspire-invest-business-plan-sep2026.pdf" in pd
    assert "4,518" in pd


# ---------------------------------------------------------------------------
# Downloadable meeting documents
# ---------------------------------------------------------------------------

def test_generator_includes_aspire_pack():
    mod = _load_generator()
    srcs = {src for src, _pdf, _title in mod.DOCUMENTS}
    outs = {pdf for _src, pdf, _title in mod.DOCUMENTS}
    for stem, rtl, *_rest in STEMS:
        md = f"investor-docs/{stem}.md"
        pdf = f"investor-docs/{stem}.pdf"
        assert md in srcs, f"generator missing {md}"
        assert pdf in outs, f"generator missing {pdf}"
        if rtl:
            assert md in mod.RTL_DOCUMENTS
        else:
            assert md not in mod.RTL_DOCUMENTS
            assert not mod._source_has_hebrew(str(DOCS / f"{stem}.md"))


def test_generator_check_passes_with_aspire_pack():
    mod = _load_generator()
    assert mod.main(["--check"]) == 0


@pytest.mark.parametrize("stem,rtl,needle_a,needle_b,needle_c", STEMS)
def test_aspire_markdown_carries_the_pack(stem, rtl, needle_a, needle_b, needle_c):
    md_path = DOCS / f"{stem}.md"
    assert md_path.is_file(), f"missing markdown: {md_path.name}"
    md = md_path.read_text(encoding="utf-8")
    for needle in (needle_a, needle_b, needle_c):
        assert needle in md, f"{md_path.name} missing {needle!r}"
    # Reserved commercial figures must not appear in this pack.
    for forbidden in ("₪6.0M", "ILS 6.0M", "₪24M", "₪30M"):
        assert forbidden not in md, f"{md_path.name} leaked reserved figure {forbidden}"


def test_business_plan_scale_identity_reconciles():
    """Every derived line in the EN / HE business plan matches the stated identity."""
    md = _read(DOCS / "aspire-invest-business-plan-sep2026.md")
    he = _read(DOCS / "aspire-invest-business-plan-sep2026-he.md")

    assert sum(NEW_ISSUES) == 250_000

    eoy = 0
    derived_eoy = []
    derived_avg = []
    derived_gwp = []
    derived_phins = []
    derived_ins = []
    for new in NEW_ISSUES:
        persist = round(eoy * 0.92)
        new_if = round(new * 0.96)
        opening = eoy
        eoy = persist + new_if
        avg = (opening + eoy) / 2
        gwp = avg * RISK_PREMIUM
        phins = round(gwp * 0.25)
        ins = gwp - phins
        derived_eoy.append(eoy)
        derived_avg.append(avg)
        derived_gwp.append(int(gwp) if gwp == int(gwp) else gwp)
        derived_phins.append(int(phins) if phins == int(phins) else phins)
        derived_ins.append(int(ins) if ins == int(ins) else ins)

    assert derived_eoy == SCALE_EOY
    assert derived_avg == SCALE_AVG
    assert derived_gwp == SCALE_GWP
    assert derived_phins == SCALE_PHINS
    assert derived_ins == SCALE_INS
    for gwp, phins, ins in zip(derived_gwp, derived_phins, derived_ins):
        assert phins + ins == gwp

    for doc in (md, he):
        for n in (
            "250,000", "24,000", "94,080", "230,554",
            "12,000", "59,040", "162,317",
            "54,216,000", "266,742,720", "733,348,206",
            "13,554,000", "66,685,680", "183,337,052",
            "40,662,000", "200,057,040", "550,011,154",
            "4,518",
            "48,794,400", "240,068,448", "660,013,385",
            "0.20",
        ):
            assert n in doc, f"scale identity missing {n}"
        assert "turnover" in doc.lower() or "מחזור" in doc
        for retired in RETIRED_SCALE_GWP + RETIRED_SCALE_REV:
            assert retired not in doc, f"retired scale figure still in plan: {retired}"
        for forbidden in (
            "do not overwrite",
            "do not mix",
            "Conservative IL book",
            "conservative IL book",
            "ספר ישראל השמרני",
            "ILS 3,600",
            "4,000 / 12,000 / 28,000",
        ):
            assert forbidden not in doc, f"two-book language still in plan: {forbidden}"


def test_business_plan_separates_takes_and_savings():
    md = _read(DOCS / "aspire-invest-business-plan-sep2026.md")
    assert "PHINS MGA" in md
    assert "Insurance take" in md
    assert "300%" in md
    assert "30%" in md
    assert "0.20" in md
    assert "48,794,400" in md
    assert "660,013,385" in md
    assert "8,584.20" in md
    assert "/api/pitch/aspire-identity" in md
    assert "Israel pilot" in md or "Israel-pilot" in md
    assert "f(42)" in md
    assert "1.255" in md
    assert "376.50" in md
    assert "one-third" not in md
    assert "1/3" not in md


@pytest.mark.parametrize("stem,rtl,needle_a,needle_b,needle_c", STEMS)
def test_aspire_pdf_is_valid(stem, rtl, needle_a, needle_b, needle_c):
    pdf_path = DOCS / f"{stem}.pdf"
    assert pdf_path.is_file(), f"PDF was not generated: {pdf_path.name}"
    data = pdf_path.read_bytes()
    assert data[:5] == b"%PDF-", "not a valid PDF header"
    assert b"%%EOF" in data[-2048:], "missing PDF EOF marker"
    assert len(data) > 4096, "PDF unexpectedly small"


@pytest.mark.parametrize("stem,rtl,needle_a,needle_b,needle_c", STEMS)
def test_aspire_pdf_preserves_content(stem, rtl, needle_a, needle_b, needle_c):
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

    # Hebrew PDFs are bidi-reordered; assert a stable Latin / digit token
    # that survives visual reordering, plus the markdown source needles.
    for needle in (needle_a, needle_b, needle_c):
        assert needle in md, f"canonical markdown drifted, missing {needle!r}"
        if rtl and re.search(r"[\u0590-\u05FF]", needle):
            # Digit / Latin needles are checked separately for RTL PDFs.
            continue
        assert needle in text, f"PDF missing canonical content {needle!r}"
    if rtl:
        assert "250,000" in text or "60" in text or "PHINS" in text
