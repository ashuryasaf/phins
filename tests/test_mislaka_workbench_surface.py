"""Mislaka assessment UI must remain reachable after Assessments unification."""

from __future__ import annotations

import os
from pathlib import Path

import requests

BASE_URL = os.environ.get("TEST_BASE_URL", "http://127.0.0.1:8000")


def test_unified_workbench_exposes_mislaka_link_controls():
    resp = requests.get(f"{BASE_URL}/unified-workbench.html")
    assert resp.status_code == 200
    body = resp.text
    assert "Pull Mislaka report" in body
    assert 'id="mislaka-report"' in body
    assert "linkMislaka" in body
    assert "/api/assessment-center/mislaka/link" in body
    assert 'id="mislaka-id"' in body


def test_unified_workbench_reveals_the_report_on_in_page_hash_change():
    # The Assessments chooser links to this same page with #mislaka-report, and
    # a same-document hash change never re-runs the init handler.
    resp = requests.get(f"{BASE_URL}/unified-workbench.html")
    assert resp.status_code == 200
    body = resp.text
    assert "function revealMislakaReport()" in body
    assert "addEventListener('hashchange', revealMislakaReport)" in body


def test_mislaka_reports_library_is_not_a_redirect_stub():
    resp = requests.get(f"{BASE_URL}/risk-reports-dashboard.html")
    assert resp.status_code == 200
    body = resp.text
    # Must be the full Swiftness / Mislaka library, not the redirect stub.
    assert "Redirecting to Assessments" not in body
    assert "mislaka" in body.lower()
    assert "/risk-report-studio.js" in body
    studio = Path(__file__).resolve().parents[1] / "web_portal" / "static" / "risk-report-studio.js"
    assert studio.stat().st_size > 50_000
