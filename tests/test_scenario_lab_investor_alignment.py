"""Scenario Lab numbers stay reconcilable with the Investor Meeting book.

The TAM snapshot remains an adjustable planning layer. Public evidence is
not rewritten. The pinned Israel book (ILS 4,518, 25% PHINS take, persistency
in-force) must match the Investor Meeting identity exactly, and the branded
EN/HE PDF generator must carry those figures plus the investor-story /
readiness charts without emoji chrome.
"""

import ast
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PITCH = REPO / "web_portal" / "static" / "pitch-dashboard.html"
LAB_PDF = REPO / "web_portal" / "static" / "phins-scenario-lab-pdf.js"
BRAND = REPO / "web_portal" / "static" / "phins-pdf-brand.js"
FONTS = REPO / "web_portal" / "static" / "fonts"


def _html() -> str:
    return PITCH.read_text(encoding="utf-8")


def _lab() -> str:
    return LAB_PDF.read_text(encoding="utf-8")


def _object_literal(source: str, name: str) -> dict:
    match = re.search(
        rf"(?:const|var|let)\s+{re.escape(name)}\s*=\s*(\{{)",
        source,
    )
    assert match, f"could not find {name}"
    start = match.start(1)
    depth = 0
    blob = None
    for i, ch in enumerate(source[start:], start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                blob = source[start:i + 1]
                break
    assert blob, f"unbalanced object for {name}"
    blob = re.sub(r"//.*?$", "", blob, flags=re.M)
    blob = re.sub(r",(\s*[}\]])", r"\1", blob)
    blob = re.sub(r"([{\[,]\s*)([A-Za-z_][A-Za-z0-9_]*)\s*:", r'\1"\2":', blob)
    return ast.literal_eval(blob)


def test_israel_book_identity_matches_investor_meeting():
    html = _html()
    book = _object_literal(html, "IL_PLANNING_BOOK")
    assert book["annualPremium"] == 4518
    assert book["monthlyPremium"] == 376.5
    assert book["phinsTakeRate"] == 0.25
    assert book["insuranceTakeRate"] == 0.75
    assert book["churn"] == 0.08
    assert book["eoyPolicies"] == [24000, 94080, 230554]
    assert book["avgInForce"] == [12000, 59040, 162317]
    assert book["newIssues"] == [25000, 75000, 150000]
    assert book["seedRound"] == 6_000_000
    assert book["preMoney"] == 24_000_000
    assert book["postMoney"] == 30_000_000
    assert book["seedRound"] + book["preMoney"] == book["postMoney"]
    for i in range(3):
        assert book["avgInForce"][i] * book["annualPremium"] == book["riskGwp"][i]
        assert round(book["riskGwp"][i] * book["phinsTakeRate"]) == book["phinsNetRevenue"][i]
        assert book["riskGwp"][i] - book["phinsNetRevenue"][i] == book["insuranceTake"][i]

    meeting = html.split('id="investor-meeting-section"', 1)[1].split(
        'id="scenario-assessment-section"', 1
    )[0]
    assert 'data-ils="4518"' in meeting
    assert "24,000" in meeting and "94,080" in meeting and "230,554" in meeting
    assert "25%" in meeting
    assert 'data-ils="54216000"' in meeting
    assert 'data-ils="183337052"' in meeting
    assert 'value="6000000"' in meeting
    assert 'value="24000000"' in meeting


def test_israel_scenario_default_premium_is_published_tables():
    html = _html()
    israel = html.split('id: "israel"', 1)[1].split('id: "usa"', 1)[0]
    assert "annualPremium: 4518" in israel
    assert "annualPremium: 2400" not in israel
    assert "takeRate: 25.0" in israel
    # Public evidence layer is unchanged (Taub / NII / CBS quotes).
    assert "346,000 elderly people" in israel
    assert "more than 5.0 million people held private LTC cover" in israel


def test_scenario_lab_pdf_is_bilingual_branded_and_emoji_free():
    lab = _lab()
    brand = BRAND.read_text(encoding="utf-8")
    assert "PHINS Scenario Lab — Market Assessment" in lab
    assert "פינס — תזכיר מעבדת התרחישים למשקיעים ולרגולטור" in lab
    assert "A visual investor story: where the PHINS thesis is strongest" in lab
    assert "קריאת משקיע: היכן התזה של פינס חזקה ביותר" in lab
    assert "Market readiness" in lab
    assert "מוכנות שוק להשקה" in lab
    assert "Canonical Israel book" in lab
    assert "תיק ישראל — בסיס התכנון ממפגש המשקיעים" in lab
    assert "brand.letterhead" in lab
    assert "wrapToVisual" in lab
    assert "toVisual" in lab
    assert "bidiVisual" not in lab
    assert "Data-integrity contract" in lab
    assert "🇮🇱" not in lab
    assert "⚠️" not in lab
    assert "stripMarks" in lab
    assert "opts.rtl" in brand
    assert (FONTS / "DejaVuSans.ttf").is_file()
    assert (FONTS / "DejaVuSans-Bold.ttf").is_file()
    assert (FONTS / "NOTICE.txt").is_file()


def test_hebrew_scenario_lab_pdf_uses_regulator_register_and_live_formula():
    lab = _lab()
    # High-register insurance Hebrew — not calques from the English lab UI.
    assert "שיעור החדרה" in lab
    assert "פרמיה שנמסרה לביטוח משנה" in lab
    assert "אוכלוסיית יעד" in lab
    assert "תרחיש לפי מספר מבוטחים" in lab
    assert "שיעור מסירה לביטוח משנה" in lab
    assert "משמעות לפינס" in lab
    assert "קבוצות שיוך" in lab
    assert "תיאום שירותי טיפול" in lab
    assert "זהות תכנונית קבועה" in lab
    assert "שלוש שכבות נתונים" in lab
    assert "שכבה א — ראיות ציבוריות נעולות" in lab
    assert "שכבה ב — תמונת TAM ניתנת לכיול" in lab
    assert "שכבה ג — תיק ישראל הקבוע" in lab
    assert "מילון מונחים במסמך זה" in lab
    assert "MARKET_COPY_HE" in lab
    assert "buildFormulaNote" in lab
    assert "never pastes English" in lab
    # Reject the previous calque register.
    assert "שיעור הצמדה" not in lab
    assert "פרמיה מותרת" not in lab
    assert "חיים ברי-הגעה" not in lab
    assert "מצב חיים" not in lab
    assert "קריאת רוחב" not in lab
    assert "אפיניות" not in lab
    assert "תזמור" not in lab
    assert "זהות נעוצה" not in lab
    assert "ספר ישראל הקנוני" not in lab
    # Hebrew notes are authored per market; English lab strings are not the HE path.
    assert "opts.modeNote" not in lab
    assert "region.reinsuranceNote" not in lab
    # Public evidence columns stay in source language; only PHINS read-through is translated.
    copy_he = lab.split("he: {", 1)[1].split("MARKET_NAME_HE", 1)[0]
    assert "346,000 elderly people" not in copy_he
    assert MARKET_IDS_IN_HEBREW_COPY(lab)


def MARKET_IDS_IN_HEBREW_COPY(lab: str) -> bool:
    block = lab.split("var MARKET_COPY_HE = {", 1)[1].split("};", 1)[0]
    for market_id in (
        "israel",
        "usa",
        "canada",
        "wneurope",
        "sweden",
        "middleeast",
        "japan",
        "australia",
        "portugal",
    ):
        assert f"{market_id}:" in block, market_id
    assert "albania" not in block
    return True


def test_scenario_lab_ui_exposes_hebrew_and_readiness_surfaces():
    html = _html()
    assert 'id="download-pdf-he"' in html
    assert "הורדת PDF (עברית)" in html
    assert 'id="invdocs-download-lab-en"' in html
    assert 'id="invdocs-download-lab-he"' in html
    assert 'id="readiness-bar-chart"' in html
    assert 'id="il-book-panel"' in html
    assert 'id="phins-take-card"' in html
    assert "IL_PLANNING_BOOK" in html
    start = html.index('id="scenario-assessment-section"')
    end = html.index("<!-- /#scenario-assessment-section -->")
    block = html[start:end]
    assert "Market readiness" in block
    assert "A visual investor story: where the PHINS thesis is strongest" in block


def test_public_evidence_not_rewritten_by_planning_book():
    html = _html()
    assert "Public LTC benefit spend exceeds NIS 16 billion annually" in html
    assert "IL_PLANNING_BOOK" in html
    assert "Reported public evidence" in html
    lab = _lab()
    assert "never written back into public statistics" in lab or "never as reported public" in lab


def test_sweden_replaces_albania_on_scenario_lab():
    html = _html()
    start = html.index("const marketData = [")
    end = html.index("    ];", start)
    block = html[start:end]
    assert 'id: "sweden"' in block
    assert 'id: "albania"' not in block
    assert "352,000 people aged 65+" in block
    assert "808,000 people" in block
    assert "SEK 5.1 billion" in block
    assert "annualPremium: 6312" in block
    assert round(5_100_000_000 / 808_000) == 6312
    lab = _lab()
    assert "sweden: 'שוודיה'" in lab
    assert "albania" not in lab
    assert "sweden: 'stageTopup'" in lab
