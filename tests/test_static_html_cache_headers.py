"""Static HTML dashboards must revalidate on every navigation.

They are served without ETag/Last-Modified, so without an explicit
Cache-Control browsers apply heuristic caching and can keep showing the
pre-deploy page (seen on admin.html after a release). Non-HTML assets keep
their existing policy.
"""

import os
from urllib.request import Request, urlopen


def _head(path: str):
    base = os.environ.get("TEST_BASE_URL", "http://127.0.0.1:8000")
    with urlopen(Request(f"{base}{path}"), timeout=10) as resp:
        return resp.status, resp.headers


def test_html_dashboards_send_no_cache():
    for path in ("/admin.html", "/index.html", "/accountant-dashboard.html"):
        status, headers = _head(path)
        assert status == 200, path
        assert headers.get("Content-Type", "").startswith("text/html"), path
        assert headers.get("Cache-Control") == "no-cache", (path, headers.get("Cache-Control"))


def test_actuary_dashboard_keeps_stricter_no_store():
    status, headers = _head("/actuary-dashboard.html")
    assert status == 200
    assert "no-store" in (headers.get("Cache-Control") or "")


def test_non_html_assets_keep_their_policy():
    status, headers = _head("/phins-logo.svg")
    assert status == 200
    assert headers.get("Content-Type", "").startswith("image/svg+xml")
    assert headers.get("Cache-Control") != "no-cache"
