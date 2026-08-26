"""Regression: pitch in-page viewer must not hijack app/dashboard navigations.

Bug: VIEWABLE_EXT matched every ``*.html``, so clicking ← Admin (and
underwriting / billing / other dashboards) opened those pages inside the
pitch document viewer chrome (← Back to tab · Open ↗ · ×) instead of
navigating normally.
"""

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PITCH = REPO / "web_portal" / "static" / "pitch-dashboard.html"


def _html() -> str:
    return PITCH.read_text(encoding="utf-8")


def _extract_js_regex(name: str) -> re.Pattern:
    html = _html()
    # var NAME = /pattern/flags;
    m = re.search(
        rf"var\s+{re.escape(name)}\s*=\s*/(?P<body>(?:\\.|[^/])+)/(?P<flags>[a-z]*)\s*;",
        html,
    )
    assert m, f"could not find JS regex {name}"
    return re.compile(m.group("body"), re.I if "i" in m.group("flags") else 0)


def _classify(path: str):
    """Mirror classifyDocUrl path rules from pitch-dashboard.html."""
    viewable_ext = _extract_js_regex("VIEWABLE_EXT")
    downloadish_ext = _extract_js_regex("DOWNLOADISH_EXT")
    doc_path = _extract_js_regex("DOC_PATH_HINT")
    doc_page = _extract_js_regex("DOC_PAGE_HINT")
    app_nav = _extract_js_regex("APP_NAV_EXCLUDE")
    if path in ("/pitch-dashboard.html", "/"):
        return None
    if app_nav.search(path):
        return None
    downloadish = bool(downloadish_ext.search(path))
    viewable = bool(
        viewable_ext.search(path) or doc_path.search(path) or doc_page.search(path)
    )
    if not downloadish and not viewable:
        return None
    return "view" if viewable and not downloadish else "download"


def test_viewable_ext_does_not_match_html_apps():
    viewable_ext = _extract_js_regex("VIEWABLE_EXT")
    assert viewable_ext.search("/report.pdf")
    assert viewable_ext.search("/notes.md")
    assert not viewable_ext.search("/admin.html")
    assert not viewable_ext.search("/underwriter-dashboard.html")
    assert not viewable_ext.search("/billing.html")


def test_app_dashboards_are_not_intercepted():
    for path in (
        "/admin.html",
        "/admin-media.html",
        "/admin-agents.html",
        "/underwriter-dashboard.html",
        "/billing.html",
        "/accountant-dashboard.html",
        "/claims-adjuster-dashboard.html",
        "/actuary-dashboard.html",
        "/corporate-legal-dashboard.html",
        "/nda-dashboard.html",
        "/risk-dashboard.html",
        "/supplier-dashboard.html",
        "/agent-portal.html",
        "/unified-workbench.html",
        "/cyber-security.html",
        "/video-agents.html",
        "/nda.html",
    ):
        assert _classify(path) is None, f"{path} must navigate normally"


def test_investor_documents_still_open_in_viewer():
    for path, mode in (
        ("/investor-docs/israel-pitch-executive-summary.pdf", "view"),
        ("/investor-docs/fintl-vc-meeting-5aug-brief.md", "view"),
        ("/internal/phins-investor-business-plan.html", "view"),
        ("/internal/phins-investment-deck.html", "view"),
        ("/legal/term-sheet.html", "view"),
        ("/legal/nda.html", "view"),
        ("/unicorn-investor-deck.html", "view"),
        ("/seed-investor-deck.html", "view"),
        ("/capital-markets-pitch.html", "view"),
        ("/PHINS_Business_Plan_Executive.pdf", "view"),
    ):
        assert _classify(path) == mode, path


def test_pitch_header_has_no_admin_back_link():
    html = _html()
    # Header actions must not link to the admin portal with the old back label.
    header = html.split('<nav class="pitch-nav"', 1)[0]
    assert "← Admin" not in header
    assert 'href="/admin.html"' not in header


def test_viewer_chrome_has_no_back_to_tab():
    html = _html()
    viewer = html.split('id="pitch-doc-viewer"', 1)[1].split("</div>\n\n  <footer", 1)[0]
    assert "Back to tab" not in viewer
    assert 'id="pitch-doc-back"' not in html
    assert 'id="pitch-doc-fallback-back"' not in html
    assert 'id="pitch-doc-close"' in html
    assert "APP_NAV_EXCLUDE" in html
    assert "classifyDocUrl" in html
