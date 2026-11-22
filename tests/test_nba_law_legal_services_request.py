"""Request for legal services sent to NBA Law (22 November 2026).

The outward document carries the five practice areas as services, deliverables,
timing, and capacity, with no internal meeting-preparation notes, canonical
figures only, and a confidential gate on every edition.
"""

import importlib.util
import re
from pathlib import Path

import pytest

from security import confidential_access as ca
from services.business_plan_model import compute_plan

REPO = Path(__file__).resolve().parents[1]
STATIC = REPO / "web_portal" / "static"
DOCS = STATIC / "investor-docs"
STEM = "nba-law-legal-services-request-22nov2026"
MD_NAME = f"investor-docs/{STEM}.md"


def _md() -> str:
    return (DOCS / f"{STEM}.md").read_text(encoding="utf-8")


def _generator():
    spec = importlib.util.spec_from_file_location(
        "generate_investor_pdfs", REPO / "scripts" / "generate_investor_pdfs.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_request_covers_the_five_areas_and_the_capacity_asked():
    md = _md()
    assert md.startswith("# PHINS — Request for Legal Services")
    for heading in ("## 1. Corporate and contracts", "## 2. Intellectual property", "## 3. Tax",
                    "## 4. Israeli and segmented regulation", "## 5. Insurance and reinsurance commercial",
                    "## Engagement capacity requested", "## Materials PHINS will provide",
                    "## Key dates", "## Notice"):
        assert heading in md, heading
    assert md.count("**Services requested**") == 5
    assert md.count("**Deliverables:**") == 5
    for needle in ("Naschitz, Brandes, Amir & Co.", "Keshet Sirota-Leviner", "22 November 2026, 12:00–13:00",
                   "coordinating partner", "named partner", "conflict check", "fee proposal per area"):
        assert needle.lower() in md.lower(), needle


def test_no_meeting_preparation_notes():
    md = _md().lower()
    for internal in ("do not open", "run of show", "talking points", "keshet's desk", "state no rate",
                     "do not state", "hard stop", "phins strength", "decision outputs", "elevator",
                     "pitch-dashboard", "pitch dashboard", "meeting diary", "point of view",
                     "/legal/", "services/", "ai_decision_log", "ledger decides"):
        assert internal not in md, internal


def test_figures_are_canonical():
    plan = compute_plan()
    funding = plan["funding"]
    factors = {f["id"]: f["default"] for f in plan["factors"]}
    assert plan["plan_version"] == "unified-2026.10-v1"
    assert (funding["seed"], funding["pre_money"], funding["post_money"], funding["series_a_indicative"]) == (
        6_000_000, 24_000_000, 30_000_000, 18_000_000)
    assert factors["cession_rate"] == 0.18 and factors["ceding_commission"] == 0.25
    assert plan["carrier_view"]["rows"][0]["ceded_premium"] == 9_758_880
    md = _md()
    for needle in ("unified-2026.10-v1", "ILS 6,000,000", "ILS 24,000,000", "ILS 30,000,000",
                   "ILS 18,000,000", "ILS 9,758,880", "18% quota share", "25% ceding commission"):
        assert needle in md, needle
    assert set(re.findall(r"\d+(?:\.\d+)?%", md)) <= {"25%", "75%", "18%"}
    assert "no insurer agreement is signed" in md
    assert "Neither round is closed." in md
    assert "is not yet approved" in md
    assert "No agreement with an insurer, a reinsurer, an investor, or the firm is recorded as signed, and no regulatory approval is recorded." in md
    for claim in ("has approved", "approved the product", "has been approved", "agreement was signed"):
        assert claim not in md.lower(), claim


def test_listed_materials_exist():
    for path in ("legal/incorporation-delaware.html", "legal/founder-agreement.html",
                 "legal/cofounder-exit-clause.html", "legal/cap-table.html",
                 "legal/shareholders-agreement.html", "legal/term-sheet.html",
                 "legal/employment-agreement.html", "legal/offer-letter.html",
                 "legal/esop-agreement.html", "legal/hr-policies.html", "terms-of-use.html",
                 "privacy-policy.html", "legal/ip-assignment.html", "legal/trademark-ip.html",
                 "legal/nda.html", "legal/financial-model.html", "business-plan.html",
                 "investor-docs/swiss-re-israel-meeting-8dec2026-deck.pdf",
                 "investor-docs/israel-regulatory-application-he.pdf"):
        assert (STATIC / path).is_file(), path


def test_registered_rendered_and_downloadable():
    mod = _generator()
    assert (MD_NAME, f"investor-docs/{STEM}.pdf",
            "PHINS — Request for Legal Services · Naschitz, Brandes, Amir & Co. (NBA Law) · 22 November 2026"
            ) in mod.DOCUMENTS
    meta = mod.DESIGNED_BRIEFS[MD_NAME]
    assert meta["html"] == f"investor-docs/{STEM}.html"
    html_doc = (DOCS / f"{STEM}.html").read_text(encoding="utf-8")
    assert "linear-gradient(135deg, #060d1f 0%, #0e2f63 46%, #123f82 100%)" in html_doc
    assert 'class="phins-doc-logo"' in html_doc and "Space Grotesk" in html_doc
    pdf = (DOCS / f"{STEM}.pdf").read_bytes()
    assert pdf[:5] == b"%PDF-" and b"%%EOF" in pdf[-2048:]
    dash = (STATIC / "pitch-dashboard.html").read_text(encoding="utf-8")
    section = dash[dash.index('<section id="nba-law-meeting-22nov"'):]
    section = section[:section.index("</section>")]
    assert f'href="/investor-docs/{STEM}.html"' in section
    assert f'href="/investor-docs/{STEM}.pdf" target="_blank" rel="noopener" class="exec-dl-btn" download' in section


def test_designed_html_is_a_fresh_render(tmp_path):
    mod = _generator()
    title = next(t for src, _pdf, t in mod.DOCUMENTS if src == MD_NAME)
    out = tmp_path / "request.html"
    mod.write_designed_brief(str(DOCS / f"{STEM}.md"), str(out), mod.DESIGNED_BRIEFS[MD_NAME], title)
    assert out.read_text(encoding="utf-8") == (DOCS / f"{STEM}.html").read_text(encoding="utf-8")


def test_every_edition_is_confidential_and_the_pdf_is_staff_only():
    for ext in ("html", "pdf", "md"):
        path = f"/investor-docs/{STEM}.{ext}"
        assert ca.is_confidential_path(path), path
        assert ca.is_confidential_path(path.upper()), path
    assert ca.is_downloadable_document(f"/investor-docs/{STEM}.pdf")


# ---------------------------------------------------------------------------
# Hebrew edition
# ---------------------------------------------------------------------------

HE_STEM = f"{STEM}.he"
HE_MD_NAME = f"investor-docs/{HE_STEM}.md"
_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?%?")


def _he_md() -> str:
    return (DOCS / f"{HE_STEM}.md").read_text(encoding="utf-8")


def test_hebrew_request_mirrors_the_english_structure():
    he, en = _he_md(), _md()
    assert he.startswith("# PHINS — בקשה לשירותים משפטיים")
    for heading in ("## נמען", "## על PHINS", "## ההיקף במבט אחד", "## 1. תאגידים וחוזים",
                    "## 2. קניין רוחני", "## 3. מיסים", "## 4. רגולציה ישראלית ומגזרית",
                    "## 5. חוזים מסחריים בביטוח ובביטוח משנה", "## מתכונת ההתקשרות המבוקשת",
                    "## החומרים ש-PHINS תמסור", "## תאריכים מרכזיים", "## הבהרה"):
        assert heading in he, heading
    assert he.count("**השירותים המבוקשים**") == 5
    assert he.count("**תוצרים:**") == 5
    for needle in ("נשיץ, ברנדס, אמיר ושות'", "קשת סירוטה-לוינר", "NBA Law", "12:00–13:00",
                   "שותף מתאם", "בדיקת ניגוד עניינים", "הצעת שכר טרחה"):
        assert needle in he, needle

    def shape(md):
        lines = md.splitlines()
        return (
            len(lines),
            [i for i, line in enumerate(lines) if line.startswith("## ")],
            [i for i, line in enumerate(lines) if line.startswith("- ")],
            [i for i, line in enumerate(lines) if line.startswith("|")],
            [line.count("|") for line in lines if line.startswith("|")],
        )

    # Same sections, bullets and table cells on the same lines as the English.
    assert shape(he) == shape(en)


def test_hebrew_request_carries_the_same_figures_and_no_preparation_notes():
    he, en = _he_md(), _md()
    assert sorted(_NUMBER.findall(he)) == sorted(_NUMBER.findall(en))
    plan = compute_plan()
    funding = plan["funding"]
    for amount in (funding["seed"], funding["pre_money"], funding["post_money"],
                   funding["series_a_indicative"], plan["carrier_view"]["rows"][0]["ceded_premium"]):
        assert float(amount).is_integer(), amount
        figure = f"{int(amount):,}"
        assert he.count(f"₪{figure}") == en.count(f"ILS {figure}") == 2, figure
    assert "ILS" not in he
    assert plan["plan_version"] in he
    assert set(re.findall(r"\d+(?:\.\d+)?%", he)) <= {"25%", "75%", "18%"}
    # The denials travel with the translation.
    for denial in ("PHINS אינה מבטח מורשה", "אף אחד מהסבבים לא נסגר.", "וטרם אושר.",
                   "לא נרשם כחתום שום הסכם עם מבטח, מבטח משנה, משקיע או המשרד, ולא נרשם שום אישור רגולטורי."):
        assert denial in he, denial
    lowered = he.lower()
    for internal in ("pitch-dashboard", "pitch dashboard", "/legal/", "services/", "ai_decision_log",
                     "talking points", "run of show", "נקודות לשיחה", "הכנה לפגישה", "אל תפתח",
                     "לא לציין", "עמדת phins", "יומן הפגישות"):
        assert internal not in lowered, internal


def test_hebrew_request_is_registered_right_to_left_and_downloadable(tmp_path):
    mod = _generator()
    title = next(t for src, _pdf, t in mod.DOCUMENTS if src == HE_MD_NAME)
    assert (HE_MD_NAME, f"investor-docs/{HE_STEM}.pdf", title) in mod.DOCUMENTS
    assert "בקשה לשירותים משפטיים" in title and "NBA Law" in title
    assert HE_MD_NAME in mod.RTL_DOCUMENTS
    assert MD_NAME not in mod.RTL_DOCUMENTS
    meta = mod.DESIGNED_BRIEFS[HE_MD_NAME]
    assert meta["html"] == f"investor-docs/{HE_STEM}.html"
    assert meta["lang"] == "he"
    html_doc = (DOCS / f"{HE_STEM}.html").read_text(encoding="utf-8")
    assert '<html lang="he" dir="rtl"' in html_doc
    assert "linear-gradient(135deg, #060d1f 0%, #0e2f63 46%, #123f82 100%)" in html_doc
    assert 'class="phins-doc-logo"' in html_doc and "Space Grotesk" in html_doc
    assert "בקשה לשירותים משפטיים" in html_doc and "₪9,758,880" in html_doc
    out = tmp_path / "request.he.html"
    mod.write_designed_brief(str(DOCS / f"{HE_STEM}.md"), str(out), meta, title)
    assert out.read_text(encoding="utf-8") == html_doc
    pdf = (DOCS / f"{HE_STEM}.pdf").read_bytes()
    assert pdf[:5] == b"%PDF-" and b"%%EOF" in pdf[-2048:]
    dash = (STATIC / "pitch-dashboard.html").read_text(encoding="utf-8")
    section = dash[dash.index('<section id="nba-law-meeting-22nov"'):]
    section = section[:section.index("</section>")]
    download = 'target="_blank" rel="noopener" class="exec-dl-btn" download'
    assert f'href="/investor-docs/{HE_STEM}.html"' in section
    assert f'href="/investor-docs/{HE_STEM}.pdf" {download}' in section
    # The documents card offers both languages, and the share list both HTML editions.
    assert dash.count(f'href="/investor-docs/{HE_STEM}.html"') == 2
    assert dash.count(f'href="/investor-docs/{HE_STEM}.pdf" {download}') == 2
    assert f'<option value="/investor-docs/{STEM}.html">' in dash
    assert f'<option value="/investor-docs/{HE_STEM}.html">' in dash


def _hebrew_units(mod):
    """Every separately laid-out Hebrew text: title, letterhead lines, paragraphs, cells."""
    meta = mod.DESIGNED_BRIEFS[HE_MD_NAME]
    units = [next(t for src, _pdf, t in mod.DOCUMENTS if src == HE_MD_NAME)]
    units += [meta[key] for key in ("eyebrow", "subtitle", "footer")]
    for line in _he_md().splitlines():
        if not line.strip():
            continue
        if line.startswith("|"):
            if set(line) <= set("|-: "):
                continue
            units += [cell.strip() for cell in line.strip().strip("|").split("|")]
        else:
            units.append(re.sub(r"^(#+|>|-)\s*", "", line).strip())
    return [mod._rtl_plain(unit) for unit in units if re.search(r"[\u0590-\u05ff]", unit)]


def test_hebrew_request_displays_in_reading_order():
    """Bidi pitfalls that scramble a right-to-left line are absent from the text.

    A number that follows a Latin word joins that word's left-to-right run, so
    "(NBA Law) · 22 November" would show the day inside the firm's name; and a
    closing bracket after a Latin word moves to the other side of the run.
    """
    pytest.importorskip("bidi")
    mod = _generator()
    units = _hebrew_units(mod)
    assert len(units) > 100
    latin_then_number = re.compile(
        r"[A-Za-z][A-Za-z0-9.\-]*[^\u0590-\u05ffA-Za-z0-9]*\s[^\u0590-\u05ffA-Za-z0-9]*₪?\d"
    )
    for unit in units:
        assert not latin_then_number.search(unit), unit
        depth = 0
        for ch in mod._bidi_line(unit):
            depth += {"(": 1, ")": -1}.get(ch, 0)
            assert depth >= 0, unit
        assert depth == 0, unit


def test_hebrew_request_lines_are_not_wrapped_twice():
    """A pre-wrapped right-to-left line must fit the frame reportlab lays it in.

    When it does not, reportlab wraps the visual-order line again and the
    logical start of the line drops to the row below (a figure then reads
    after the label that follows it).
    """
    pytest.importorskip("bidi")
    mod = _generator()
    if mod._register_hebrew_font() != "PHINSHebrew":
        pytest.skip("no Hebrew-capable font on this host")
    styles = mod._rtl_styles()
    inner = mod.FRAME_WIDTH - 12.0  # reportlab Frame: 6pt padding each side
    for key in ("title", "h1", "h2", "h3", "body", "bullet", "quote"):
        assert mod._rtl_width_for(styles, key) <= inner - styles[key].leftIndent - styles[key].rightIndent
    seen = []
    real = mod._rtl_paragraph

    def spy(text, style, max_width):
        para = real(text, style, max_width)
        lines = mod._rtl_break_lines(text, style.fontName, style.fontSize, max(1.0, max_width))
        seen.append((para, len(lines), style, max_width, text))
        return para

    mod._rtl_paragraph = spy
    try:
        title = next(t for src, _pdf, t in mod.DOCUMENTS if src == HE_MD_NAME)
        mod.markdown_to_story(_he_md(), title, styles)
    finally:
        mod._rtl_paragraph = real
    top_level = 0
    for para, expected_lines, style, max_width, text in seen:
        own = [key for key in ("title", "h1", "h2", "h3", "body", "bullet", "quote") if styles[key] is style]
        if not own or abs(max_width - mod._rtl_width_for(styles, own[0])) > 0.01:
            continue  # a table cell is laid out in its own column
        top_level += 1
        para.wrap(inner, 100000)
        assert len(para.blPara.lines) == expected_lines, text
    assert top_level >= 70
    from pypdf import PdfReader

    assert len(PdfReader(str(DOCS / f"{HE_STEM}.pdf")).pages) == 4


def test_hebrew_editions_are_confidential_and_share_only_as_html():
    for ext in ("html", "pdf", "md"):
        path = f"/investor-docs/{HE_STEM}.{ext}"
        assert ca.is_confidential_path(path), path
        assert ca.is_confidential_path(path.upper()), path
    assert ca.is_downloadable_document(f"/investor-docs/{HE_STEM}.pdf")
    assert ca.is_downloadable_document(f"/investor-docs/{HE_STEM}.md")
    assert not ca.is_downloadable_document(f"/investor-docs/{HE_STEM}.html")
    # Each language is its own link: one does not open the other.
    assert not ca.share_covers(f"/investor-docs/{STEM}.html", f"/investor-docs/{HE_STEM}.html")
    assert not ca.share_covers(f"/investor-docs/{HE_STEM}.html", f"/investor-docs/{STEM}.html")
    assert not ca.share_covers(f"/investor-docs/{HE_STEM}.html", f"/investor-docs/{HE_STEM}.pdf")
