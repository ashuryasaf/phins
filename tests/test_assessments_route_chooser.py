"""Assessments nav exposes a chooser for assessment routes (PR follow-up)."""

from __future__ import annotations

import os
from pathlib import Path

import requests

BASE_URL = os.environ.get("TEST_BASE_URL", "http://127.0.0.1:8000")
STATIC = Path(__file__).resolve().parents[1] / "web_portal" / "static"


def test_assessments_nav_assets_exist():
    assert (STATIC / "assessments-nav.js").is_file()
    css = (STATIC / "phins-theme.css").read_text(encoding="utf-8")
    assert ".assessments-nav" in css
    assert "phins-gold" in css


def test_admin_and_customer_mount_assessments_chooser():
    admin = requests.get(f"{BASE_URL}/admin.html").text
    assert 'data-assessments-nav' in admin
    assert 'assessments-nav.js' in admin
    assert 'phins-theme.css' in admin
    # No longer a single hard-wired Assessments <a> only destination
    assert 'href="/unified-workbench.html">📋 Assessments</a>' not in admin

    customer = requests.get(f"{BASE_URL}/dashboard.html").text
    assert 'data-assessments-nav' in customer
    assert 'assessments-nav.js' in customer


def test_assessment_routes_are_full_pages_not_stubs():
    for path, must_include in [
        ("/assessment-center.html", "Pull Mislaka facts"),
        ("/risk-dashboard.html", "Risk Assessment"),
        ("/risk-reports-dashboard.html", "Mislaka"),
        ("/unified-workbench.html", "Run Unified Analysis"),
        ("/customer-ai-report.html", "AI Report"),
    ]:
        resp = requests.get(f"{BASE_URL}{path}")
        assert resp.status_code == 200, path
        body = resp.text
        assert "Redirecting to Assessments" not in body, path
        assert must_include in body, path


def test_workbench_and_reports_use_phins_logo_and_theme():
    for path in ("/unified-workbench.html", "/risk-reports-dashboard.html", "/risk-dashboard.html"):
        body = requests.get(f"{BASE_URL}{path}").text
        assert "phins-theme.css" in body
        assert "phins-logo.svg" in body
