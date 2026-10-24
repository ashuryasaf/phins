"""Static integrity for pitch-dashboard foldable tabs + document viewer.

Covers per-tab Back-to-header controls and the in-page document viewer
(close via × — no Back-to-tab chrome; app/dashboard links navigate normally).
"""

from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PITCH = REPO / "web_portal" / "static" / "pitch-dashboard.html"


def _html() -> str:
    return PITCH.read_text(encoding="utf-8")


SECTION_IDS = [
    "investor-documents-section",
    "actuary-briefing-section",
    "freilichman-meeting-24sep",
    "investor-meeting-section",
    "partner-meetings-13jul",
    "regulatory-meeting-27jul",
    "regulatory-preruling-avi-ovadia",
    "fintl-vc-meetings-aug",
    "grove-vc-meeting-19aug",
    "grove-vc-meeting-24sep",
    "aspire-invest-meeting-sep2026",
    "nba-law-meeting-25oct",
    "aspire-ohayun-meeting-26oct",
    "uzan-followup-meeting-28oct",
    "dnr-benzvi-meeting-12nov",
    "exec-summary-section",
    "scenario-assessment-section",
    "techno-yes-section",
    "il-meeting-diary",
]


def test_pitch_header_branding_and_back_controls():
    html = _html()
    assert 'id="pitch-top"' in html
    assert 'src="/phins-logo.svg"' in html
    # Back-to-header lives on each tab body (injected), not the sticky header.
    assert 'id="pitch-back-header"' not in html
    assert "pitch-tab-back" in html
    assert "↑ Back to header" in html
    assert 'id="pitch-back-fab"' in html
    assert "Space Grotesk" in html
    assert "pitch-nav" in html
    # Header actions must not ship the admin back-link that the viewer hijacked.
    header = html.split('<nav class="pitch-nav"', 1)[0]
    assert "← Admin" not in header
    assert 'href="/admin.html"' not in header


def test_pitch_nav_links_cover_all_tabs():
    html = _html()
    for section_id in SECTION_IDS:
        assert f'href="#{section_id}"' in html, section_id
        assert f'id="{section_id}"' in html, section_id


def test_pitch_fold_script_registers_sections():
    html = _html()
    assert "PITCH_FOLD_IDS" in html
    assert "pitch-fold-toggle" in html
    assert "scrollToId" in html
    assert "injectTabBack" in html
    for section_id in (
        "investor-documents-section",
        "fintl-vc-meetings-aug",
        "grove-vc-meeting-19aug",
        "grove-vc-meeting-24sep",
        "aspire-invest-meeting-sep2026",
        "nba-law-meeting-25oct",
        "aspire-ohayun-meeting-26oct",
        "uzan-followup-meeting-28oct",
        "dnr-benzvi-meeting-12nov",
        "freilichman-meeting-24sep",
        "scenario-assessment-section",
        "techno-yes-section",
    ):
        assert f'"{section_id}"' in html


def test_pitch_document_viewer_return_controls():
    """Docs open in-viewer with × close; app pages are never intercepted."""
    html = _html()
    assert 'id="pitch-doc-viewer"' in html
    assert 'id="pitch-doc-close"' in html
    assert "wireDocViewer" in html
    assert "findSourceSectionId" in html
    assert "returnSectionId" in html
    assert "APP_NAV_EXCLUDE" in html
    viewer = html.split('id="pitch-doc-viewer"', 1)[1].split("</div>\n\n  <footer", 1)[0]
    assert "Back to tab" not in viewer
    assert 'id="pitch-doc-back"' not in html
    assert 'id="pitch-doc-fallback-back"' not in html
    assert "showLoadFailureFallback" in html
    assert "Document unavailable" in html
    # Presentation-only; does not rewrite document contents or bypass the gate.
    assert "Presentation-only intercept" in html


def test_pitch_fold_preserves_data_integrity_notices():
    """Folding / viewer is presentation-only — integrity copy must remain."""
    html = _html()
    assert "Data integrity notice" in html
    assert "hash-chained" in html or "append-only" in html
    assert "PHINS assumptions adjustable" in html
    # Share-link admin + diary tooling stay present.
    assert 'id="confidential-share-admin"' in html
    assert 'id="diary-table"' in html


def test_scenario_assessment_wraps_lab_content():
    html = _html()
    start = html.index('id="scenario-assessment-section"')
    end = html.index("<!-- /#scenario-assessment-section -->")
    block = html[start:end]
    assert "stats-strip" in block
    assert "Scenario Lab" in block
    assert "scenario-shell" in block or "Scenario lab" in block or "scenario-title" in block


# ---------------------------------------------------------------------------
# Techno Yes — architecture & long-term cost plan tab
# ---------------------------------------------------------------------------
TECHNO_YES_COST_KEYS = ("personnel", "ai_dev", "ai_runtime", "cloud", "security", "actuarial_reg")
TECHNO_YES_FIVE_YEAR_TOTAL_ILS = 43_376_000
TECHNO_YES_PAS_OPTION_ILS = 6_500_000


def _techno_yes_block() -> str:
    html = _html()
    start = html.index('<section id="techno-yes-section"')
    end = html.index("<!-- /#techno-yes-section -->")
    return html[start:end]


def _techno_yes_data() -> dict:
    import json

    block = _techno_yes_block()
    marker = 'id="techno-yes-data">'
    start = block.index(marker) + len(marker)
    end = block.index("</script>", start)
    return json.loads(block[start:end])


def test_techno_yes_tab_is_wired_like_the_other_tabs():
    html = _html()
    nav = html.split('<nav class="pitch-nav"', 1)[1].split("</nav>", 1)[0]
    assert 'href="#techno-yes-section" class="pitch-nav-link">Techno Yes</a>' in nav
    fold_ids = html.split("var PITCH_FOLD_IDS = [", 1)[1].split("];", 1)[0]
    assert '"techno-yes-section"' in fold_ids
    block = _techno_yes_block()
    # Direct-child banner is what makes the section foldable; stats strip matches the sibling tabs.
    assert block.lstrip().startswith('<section id="techno-yes-section" style="margin-bottom:28px;">')
    assert 'class="exec-summary-banner"' in block
    assert 'class="stats-strip"' in block
    assert "Techno Yes" in block
    # The new tab lives after the Scenario Lab so the Aspire slice stays untouched.
    assert html.index('id="techno-yes-section"') > html.index("<!-- /#scenario-assessment-section -->")
    assert html.index("<!-- /#techno-yes-section -->") < html.index("</main>")


def test_techno_yes_cost_plan_arithmetic_ties_to_the_scale_identity():
    import sys

    sys.path.insert(0, str(REPO))
    from services import aspire_scale_identity as identity

    data = _techno_yes_data()
    years = data["years"]
    assert [y["year"] for y in years] == [1, 2, 3, 4, 5]
    premium = data["risk_premium_ils"]
    assert premium == 4518
    for idx, year in enumerate(years):
        assert year["avg_lives"] == identity.UNIFIED_5Y_AVG[idx]
        assert year["eoy_lives"] == identity.UNIFIED_5Y_EOY[idx]
        assert year["opex"] == identity.UNIFIED_5Y_OPEX[idx]
        assert year["gwp"] == year["avg_lives"] * premium
        assert year["total"] == sum(year[k] for k in TECHNO_YES_COST_KEYS), year["year"]
        assert year["personnel"] == round(year["fte"] * year["loaded_month"] * 12), year["year"]
        # Technology stays a minority share of plan opex; from Y2 it sits under the 1.8–4.2% industry IT band
        # (Y1 is the build year on a small book and is allowed to touch the top of the band).
        assert 0.05 < year["total"] / year["opex"] < 0.10, year["year"]
        assert year["total"] / year["gwp"] < (0.043 if year["year"] == 1 else 0.02), year["year"]
    total = sum(y["total"] for y in years)
    assert total == TECHNO_YES_FIVE_YEAR_TOTAL_ILS
    assert 0.009 < total / sum(y["gwp"] for y in years) < 0.012
    assert sum(y["pas_option"] for y in years) == TECHNO_YES_PAS_OPTION_ILS
    assert [y["pas_option"] for y in years[:3]] == [0, 0, 0]
    assert all(years[i]["total"] < years[i + 1]["total"] for i in range(4))
    assert [l["key"] for l in data["cost_lines"]] == list(TECHNO_YES_COST_KEYS)


def test_techno_yes_competitors_and_sources_are_referenced_not_registered():
    data = _techno_yes_data()
    competitors = data["competitors"]
    assert len(competitors) >= 10
    models = {c["model"] for c in competitors}
    assert {"carrier", "mga", "platform", "reinsurer"} <= models
    for row in competitors:
        for key in ("name", "model", "fact", "partners", "lesson", "source_label", "url"):
            assert row.get(key), (row.get("name"), key)
        assert row["url"].startswith("https://"), row["name"]
    names = {c["name"] for c in competitors}
    assert {"Lemonade", "Root", "Hippo", "Ethos", "NEXT Insurance", "Swiss Re iptiQ"} <= names
    sources = data["sources"]
    assert len(sources) >= 20
    for src in sources:
        assert set(src) == {"label", "url", "date"}
        assert src["url"].startswith("https://")
    # The Scenario Lab research registry is parsed from this file by tests/test_business_plan.py;
    # Techno Yes references must never masquerade as registry entries.
    block = _techno_yes_block()
    assert "sourceType" not in block
    assert "evidenceStrength" not in block
    assert "aspire_scale_identity.py" in block
    assert "does not change any actuarial figure" in block


# ---------------------------------------------------------------------------
# 25 Oct – 12 Nov 2026 meetings. One Israel book, four points of view.
# ---------------------------------------------------------------------------

OCT_MEETINGS = (
    ("nba-law-meeting-25oct", "nba-law-meeting-25oct-brief",
     "Keshet Sirota-Leviner", "25 October 2026", "#regulatory-preruling-avi-ovadia"),
    ("aspire-ohayun-meeting-26oct", "aspire-ohayun-meeting-26oct-brief",
     "Eyal Ohayun", "26 October 2026", "#aspire-invest-meeting-sep2026"),
    ("uzan-followup-meeting-28oct", "uzan-followup-meeting-28oct-brief",
     "Meir Uzan", "28 October 2026", "#investor-meeting-section"),
    ("dnr-benzvi-meeting-12nov", "dnr-benzvi-meeting-12nov-brief",
     "Yosi Ben Zvi", "12 November 2026", "#partner-meetings-13jul"),
)


def _oct_section(html: str, section_id: str) -> str:
    start = html.index(f'id="{section_id}"')
    rest = html[start + 1:]
    end = rest.index('<section id="')
    return rest[:end]


def test_oct2026_meetings_address_the_unified_plan_and_an_earlier_bar():
    html = _html()
    assert "Meetings that address this standard" in html
    for section_id, stem, person, date, earlier in OCT_MEETINGS:
        section = _oct_section(html, section_id)
        assert person in section
        assert date in section
        assert 'href="#unified-business-plan-card"' in section
        assert 'href="/business-plan.html"' in section
        assert 'href="/business-plan.html#part-deck"' in section
        assert 'href="/business-plan.html#part-appendices"' in section
        assert f'href="{earlier}"' in section
        assert f'/investor-docs/{stem}.html"' in section
        assert f'/investor-docs/{stem}.pdf"' in section
        assert "download" in section
        for needle in ("4,518", "24,000 / 94,080 / 230,554", "13,554,000", "6,000,000", "unified-2026.10-v1"):
            assert needle in section, (section_id, needle)
    # This follow-up names Meir Uzan even if the configurator renames the June book.
    uzan = _oct_section(html, "uzan-followup-meeting-28oct")
    assert "inv-investor-name" not in uzan
    # The September bar links forward and still does not carry this follow-up's seed.
    aspire = html[html.index('id="aspire-invest-meeting-sep2026"'):html.index('id="nba-law-meeting-25oct"')]
    assert 'href="#aspire-ohayun-meeting-26oct"' in aspire
    assert "6,000,000" not in aspire
    assert "₪6.0M" not in aspire


def test_oct2026_israel_book_identity_holds():
    assert 12_000 * 4_518 == 54_216_000
    assert 59_040 * 4_518 == 266_742_720
    assert 162_317 * 4_518 == 733_348_206
    assert round(54_216_000 * 0.25) == 13_554_000
    assert round(266_742_720 * 0.25) == 66_685_680
    assert round(733_348_206 * 0.25) == 183_337_052
    assert 2_400_000 + 1_200_000 + 1_500_000 + 900_000 == 6_000_000
    html = _html()
    for section_id, *_rest in OCT_MEETINGS:
        section = _oct_section(html, section_id)
        assert "54,216,000" in section
        assert "183,337,052" in section


def test_freilichman_24sep_is_a_held_actuary_record():
    html = _html()
    briefing = html[html.index('id="actuary-briefing-section"'):html.index('id="freilichman-meeting-24sep"')]
    assert "26 May 2026" in briefing
    assert "Ori Freilichman" in briefing
    assert 'href="#freilichman-meeting-24sep"' in briefing
    section = html[html.index('id="freilichman-meeting-24sep"'):html.index('id="investor-meeting-section"')]
    assert "Thursday 24 September 2026" in section
    assert "22:00" in section
    assert "F.IL.A.A." in section
    assert "Held" in section
    assert "regulatory proof-of-concept" in section
    assert "12 October" in section
    assert 'href="#regulatory-preruling-avi-ovadia"' in section
    assert 'href="#actuary-briefing-section"' in section
    assert 'href="#grove-vc-meeting-24sep"' in section
    assert 'href="#unified-business-plan-card"' in section
    assert 'href="/business-plan.html"' in section
    assert 'href="/business-plan.html#part-deck"' in section
    assert 'href="/business-plan.html#part-appendices"' in section
    assert "/investor-docs/freilichman-meeting-24sep-brief.pdf" in section
    assert "download" in section
    for needle in ("4,518", "24,000 / 94,080 / 230,554", "13,554,000", "6,000,000", "unified-2026.10-v1"):
        assert needle in section, needle
    # Terms that were not set must stay unset.
    assert "board of directors" in section
    assert "did not subscribe" in section or "no subscription" in section
    assert "26 May" in section
    preruling = html[html.index('id="regulatory-preruling-avi-ovadia"'):html.index('id="fintl-vc-meetings-aug"')]
    assert 'href="#freilichman-meeting-24sep"' in preruling
    grove = html[html.index('id="grove-vc-meeting-24sep"'):html.index('id="aspire-invest-meeting-sep2026"')]
    assert 'href="#freilichman-meeting-24sep"' in grove
    assert 'time: "22:00"' in html
    assert "Mr. Ori Freilichman, F.IL.A.A. — actuary" in html
    assert 'status: "Held"' in html[html.index("Mr. Ori Freilichman, F.IL.A.A. — actuary"):html.index("Mr. Ori Freilichman, F.IL.A.A. — actuary") + 800]
    record = (REPO / "web_portal/static/investor-docs/freilichman-meeting-24sep-brief.html").read_text(encoding="utf-8")
    md = (REPO / "web_portal/static/investor-docs/freilichman-meeting-24sep-brief.md").read_text(encoding="utf-8")
    assert "Ori Freilichman" in md and "22:00" in md and "Held" in md
    assert "linear-gradient(135deg, #060d1f 0%, #0e2f63 46%, #123f82 100%)" in record
    assert "Space Grotesk" in record and 'class="phins-doc-logo"' in record
    pdf = (REPO / "web_portal/static/investor-docs/freilichman-meeting-24sep-brief.pdf").read_bytes()
    assert pdf[:5] == b"%PDF-" and b"%%EOF" in pdf[-2048:]


def test_oct2026_diary_seed_and_designed_briefs():
    import importlib.util

    html = _html()
    assert 'var STORAGE_ID = "phins.il.meeting.diary.v10"' in html
    assert "phins.il.meeting.diary.v9" in html
    for date, person in (
        ("2026-10-25", "Keshet Sirota-Leviner"),
        ("2026-10-26", "Eyal Ohayun"),
        ("2026-10-28", "Meir Uzan"),
        ("2026-11-12", "Yosi Ben Zvi"),
    ):
        assert date in html
        assert person in html
    spec = importlib.util.spec_from_file_location(
        "generate_investor_pdfs", REPO / "scripts" / "generate_investor_pdfs.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    docs = REPO / "web_portal" / "static" / "investor-docs"
    srcs = {src for src, _pdf, _title in mod.DOCUMENTS}
    for _section, stem, person, date, _earlier in OCT_MEETINGS:
        md_name = f"investor-docs/{stem}.md"
        assert md_name in srcs
        assert md_name in mod.DESIGNED_BRIEFS
        html_doc = (docs / f"{stem}.html").read_text(encoding="utf-8")
        md = (docs / f"{stem}.md").read_text(encoding="utf-8")
        assert person in md and date in md
        assert "linear-gradient(135deg, #060d1f 0%, #0e2f63 46%, #123f82 100%)" in html_doc
        assert "Space Grotesk" in html_doc
        assert 'class="phins-doc-logo"' in html_doc
        assert 'href="/business-plan.html"' in html_doc
        pdf = (docs / f"{stem}.pdf").read_bytes()
        assert pdf[:5] == b"%PDF-"
        assert b"%%EOF" in pdf[-2048:]
