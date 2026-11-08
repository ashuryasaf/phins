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
    "reinsurer-ceo-assessment-nov2026",
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
        "reinsurer-ceo-assessment-nov2026",
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
    assert 'value="/phins-customer-150k-one-pager.html"' in html
    assert 'value="/phins-customer-150k-one-pager.he.html"' in html
    assert 'value="/investor-deck.html"' in html
    assert 'value="/investor-deck.he.html"' in html
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


def test_oct2026_diary_seed_and_designed_briefs():
    import importlib.util

    html = _html()
    assert 'var STORAGE_ID = "phins.il.meeting.diary.v10"' in html
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


# ---------------------------------------------------------------------------
# 7 Nov 2026 — global reinsurer Group CEO assessment (role exercise). The
# ceded line is the unified plan's own carrier view read from the reinsurer's
# side; every figure must regenerate from the model at default factors.
# ---------------------------------------------------------------------------

REINSURER_SECTION = "reinsurer-ceo-assessment-nov2026"
REINSURER_STEM = "reinsurer-group-ceo-assessment-nov2026-brief"


def _reinsurer_md() -> str:
    return (REPO / "web_portal" / "static" / "investor-docs" / f"{REINSURER_STEM}.md").read_text(
        encoding="utf-8"
    )


def test_reinsurer_ceo_assessment_addresses_the_unified_plan():
    html = _html()
    section = _oct_section(html, REINSURER_SECTION)
    assert "Group CEO" in section
    assert "7 November 2026" in section
    assert "no approach made" in section
    assert 'href="#unified-business-plan-card"' in section
    assert 'href="/business-plan.html"' in section
    assert 'href="/business-plan.html#part-deck"' in section
    assert 'href="/business-plan.html#part-appendices"' in section
    assert 'href="#techno-yes-section"' in section
    assert 'href="#partner-meetings-13jul"' in section
    assert f'/investor-docs/{REINSURER_STEM}.html"' in section
    assert f'/investor-docs/{REINSURER_STEM}.pdf"' in section
    assert "download" in section
    for needle in (
        "4,518", "24,000 / 94,080 / 230,554", "13,554,000 / 66,685,680 / 183,337,052",
        "54,216,000 / 266,742,720 / 733,348,206", "ILS 6,000,000 on ILS 24,000,000",
        "unified-2026.10-v1", "Data integrity notice",
    ):
        assert needle in section, needle
    # Every option stays open and no reinsurer term is set in the bar.
    for option in ("A. Quota-share capacity", "B. Lead reinsurer", "C. Strategic minority",
                   "D. Series A anchor", "E. Carrier introductions", "F. Data access only", "G. Pass"):
        assert option in section, option
    assert "Never a linked price" in section
    assert "No reinsurer limit, cap, ticket or price is set" in section
    # The one-standard card lists the assessment beside the October meetings.
    card = html[html.index('id="unified-business-plan-card"'):html.index('id="investor-deck-film"')]
    assert f'href="#{REINSURER_SECTION}"' in card
    md = _reinsurer_md()
    assert "No reinsurer has been approached" in md
    assert "This memo does not write the platform ledger." in md


def test_reinsurer_ceo_assessment_ceded_line_matches_the_model():
    from services.business_plan_document import fmt
    from services.business_plan_model import compute_plan

    plan = compute_plan()
    assert plan["canonical"] is True
    assert plan["integrity"]["all_hold"] is True
    assert plan["content_hash"].startswith("9128223e1c222388")
    fx = plan["presentation"]["fx_usd_ils"]
    f = plan["inputs"]
    assert (f["cession_rate"], f["expected_loss_ratio"], f["ceding_commission"]) == (0.18, 0.62, 0.25)

    md = _reinsurer_md()
    section = _oct_section(_html(), REINSURER_SECTION)
    totals = {"risk_gwp": 0.0, "ceded_premium": 0.0, "ceded_claims": 0.0,
              "ceding_commission": 0.0, "result": 0.0}
    for row in plan["carrier_view"]["rows"]:
        result = row["ceded_premium"] - row["ceded_claims"] - row["ceding_commission"]
        # Identities the memo relies on.
        assert abs(row["ceded_premium"] + row["retained_premium"] - row["risk_gwp"]) < 0.5
        assert abs(result / row["ceded_premium"] - (1.0 - 0.62 - 0.25)) < 1e-9
        assert abs(row["carrier_margin"] - 0.0566) < 5e-5
        cells = [fmt(row["risk_gwp"], "ilsm"), fmt(row["ceded_premium"], "ilsm"),
                 fmt(row["ceded_claims"], "ilsm"), fmt(row["ceding_commission"], "ilsm"),
                 fmt(result, "ilsm"), fmt(result, "usdm", fx)]
        line = f"| {row['year']} | " + " | ".join(cells) + " |"
        assert line in md, line
        for cell in cells:
            assert cell in section, (row["year"], cell)
        for key in ("risk_gwp", "ceded_premium", "ceded_claims", "ceding_commission"):
            totals[key] += row[key]
        totals["result"] += result
    five = [fmt(totals["risk_gwp"], "ilsm"), fmt(totals["ceded_premium"], "ilsm"),
            fmt(totals["ceded_claims"], "ilsm"), fmt(totals["ceding_commission"], "ilsm"),
            fmt(totals["result"], "ilsm"), fmt(totals["result"], "usdm", fx)]
    assert "| Five years | " + " | ".join(five) + " |" in md
    for cell in five:
        assert cell in section, cell
    assert fmt(totals["ceded_premium"], "usdm", fx) in md  # $207.9M five-year ceded premium
    # Group envelope is group GWP × the default cession, labelled as arithmetic.
    envelope = " / ".join(fmt(r["risk_gwp"] * f["cession_rate"], "ilsm") for r in plan["group"]["rows"])
    assert envelope in md and envelope in section
    assert fmt(plan["group"]["rows"][-1]["risk_gwp"] * f["cession_rate"], "usdm", fx) in md
    assert "not a model row" in md and "not a model row" in section
    # Exact 2027 arithmetic quoted in the data-integrity paragraphs.
    r27 = plan["carrier_view"]["rows"][0]
    assert r27["ceded_premium"] == 9_758_880.0
    assert r27["ceding_commission"] == 2_439_720.0
    assert abs(r27["ceded_claims"] - 6_050_505.60) < 1e-6
    assert abs(r27["ceded_premium"] - r27["ceded_claims"] - r27["ceding_commission"] - 1_268_654.40) < 1e-6
    for needle in ("ILS 9,758,880", "ILS 2,439,720", "ILS 6,050,505.60", "ILS 1,268,654.40"):
        assert needle in md and needle in section, needle
    assert abs(plan["carrier_view"]["rows"][2]["ceded_premium"] - 132_002_677.08) < 1e-6
    assert "ILS 132,002,677.08" in md
    # Round, burn and appraisal figures restated from the same plan.
    funding, appraisal = plan["funding"], plan["appraisal"]
    assert (funding["seed"], funding["pre_money"], funding["post_money"]) == (6e6, 24e6, 30e6)
    assert funding["series_a_indicative"] == 18_000_000.0
    assert fmt(funding["burn_2027"], "ilsm") in md
    assert fmt(funding["peak_cumulative_need"], "ilsm") in md
    assert fmt(appraisal["central_pre_money"], "ilsm") in md
    assert f"{round(appraisal['ask_to_appraisal'] * 100)}% of it" in md
    assert fmt(funding["runway_months_on_seed"], "text").startswith("3.82")
    assert "3.8 months" in md
    g31 = plan["group"]["rows"][-1]
    assert fmt(g31["phins_revenue"], "ilsm") in md and fmt(g31["phins_revenue"], "usdm", fx) in md
    assert fmt(g31["risk_gwp"], "ilsm") in md and fmt(g31["risk_gwp"], "usdm", fx) in md
    assert fmt(g31["ebitda_margin"], "pct") + " EBITDA margin" in md
    il29 = plan["anchor_book"]["rows"][2]
    assert fmt(il29["savings_flow"], "ilsm") in md and fmt(g31["savings_flow"], "ilsm") in md


def test_reinsurer_ceo_assessment_designed_brief_and_pdf():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "generate_investor_pdfs", REPO / "scripts" / "generate_investor_pdfs.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    docs = REPO / "web_portal" / "static" / "investor-docs"
    md_name = f"investor-docs/{REINSURER_STEM}.md"
    assert md_name in {src for src, _pdf, _title in mod.DOCUMENTS}
    assert md_name in mod.DESIGNED_BRIEFS
    html_doc = (docs / f"{REINSURER_STEM}.html").read_text(encoding="utf-8")
    assert "linear-gradient(135deg, #060d1f 0%, #0e2f63 46%, #123f82 100%)" in html_doc
    assert "Space Grotesk" in html_doc
    assert 'class="phins-doc-logo"' in html_doc
    assert 'href="/business-plan.html"' in html_doc
    assert "Reinsurer assessment · 7 November 2026" in html_doc
    # The designed edition carries the same ceded table as the markdown source.
    for cell in ("₪764.9M", "₪474.2M", "₪191.2M", "₪99.4M", "$27.0M"):
        assert cell in html_doc, cell
    pdf = (docs / f"{REINSURER_STEM}.pdf").read_bytes()
    assert pdf[:5] == b"%PDF-"
    assert b"%%EOF" in pdf[-2048:]
