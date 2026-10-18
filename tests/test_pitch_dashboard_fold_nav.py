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
