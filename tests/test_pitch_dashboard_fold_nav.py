"""Static integrity for pitch-dashboard foldable tabs + document viewer.

Covers per-tab Back-to-header controls and the in-page document viewer
(close via × — no Back-to-tab chrome).
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
    "fintl-vc-meetings-aug",
    "grove-vc-meeting-19aug",
    "exec-summary-section",
    "scenario-assessment-section",
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
        "scenario-assessment-section",
    ):
        assert f'"{section_id}"' in html


def test_pitch_document_viewer_return_controls():
    """Opened/downloaded docs expose × (not Back to tab) to close the viewer."""
    html = _html()
    assert 'id="pitch-doc-viewer"' in html
    assert 'id="pitch-doc-close"' in html
    assert "wireDocViewer" in html
    assert "findSourceSectionId" in html
    assert "returnSectionId" in html
    # Unintended "Back to tab" chrome must not ship in the viewer header/fallback.
    assert "Back to tab" not in html
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
