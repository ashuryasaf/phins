"""Assert unintended ← Back to tab / ← Admin header chrome is gone.

These controls were never meant to ship in dashboard headers. Plain nav
labels like \"Admin\" (without the ← Back prefix) on role dashboards are
out of scope for this guard.
"""

from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
STATIC = REPO / "web_portal" / "static"

HEADER_SURFACES = [
    STATIC / "pitch-dashboard.html",
    STATIC / "video-agents.html",
    STATIC / "nda-dashboard.html",
    STATIC / "corporate-legal-dashboard.html",
    STATIC / "cyber-security.html",
    STATIC / "admin-media.html",
    STATIC / "admin-agents.html",
    STATIC / "legal" / "legal-docs.js",
]

FORBIDDEN = (
    "← Back to tab",
    "Back to tab",
    "← Admin",
    "← Back to Admin",
    "← Back to admin",
)


def test_forbidden_header_back_chrome_removed():
    for path in HEADER_SURFACES:
        text = path.read_text(encoding="utf-8")
        for needle in FORBIDDEN:
            assert needle not in text, f"{path.name} still contains {needle!r}"


def test_pitch_viewer_close_remains():
    html = (STATIC / "pitch-dashboard.html").read_text(encoding="utf-8")
    assert 'id="pitch-doc-close"' in html
    assert 'id="pitch-doc-viewer"' in html
