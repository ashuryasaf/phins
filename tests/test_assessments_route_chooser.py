"""Assessments nav exposes a chooser for assessment routes (PR follow-up)."""

from __future__ import annotations

import os
import re
from pathlib import Path

import requests

BASE_URL = os.environ.get("TEST_BASE_URL", "http://127.0.0.1:8000")
STATIC = Path(__file__).resolve().parents[1] / "web_portal" / "static"

# Frozen chooser destinations — chrome/layout changes must not rewrite these.
ADMIN_ROUTE_HREFS = (
    "/unified-workbench.html",
    "/assessment-center.html",
    "/risk-dashboard.html",
    "/risk-reports-dashboard.html",
    "/risk-assessment-viewer.html",
)
CUSTOMER_ROUTE_HREFS = (
    "/unified-workbench.html",
    "/assessment-center.html",
    "/customer-ai-report.html",
    "/risk-reports-dashboard.html",
)


def test_assessments_nav_assets_exist():
    assert (STATIC / "assessments-nav.js").is_file()
    css = (STATIC / "phins-theme.css").read_text(encoding="utf-8")
    assert ".assessments-nav" in css
    assert "phins-gold" in css
    # Mobile drawer uses opaque navy tiles + a vertical gold wash so the
    # old 135deg blue hatch does not stripe through the stacked chips.
    assert "#mobile-nav.phins-nav" in css
    assert "no 135deg stripe bleed" in css
    assert "background: var(--phins-gold) !important;" in css
    assert "#mobile-nav .assessments-nav-toggle" in css
    # Drawer lives inside a backdrop-filter header; bottom:auto keeps
    # the ☰ open state from collapsing to a 0-height strip.
    assert "bottom: auto !important;" in css


def test_assessments_nav_mobile_drawer_keeps_chooser_in_flow():
    css = (STATIC / "phins-theme.css").read_text(encoding="utf-8")
    js = (STATIC / "assessments-nav.js").read_text(encoding="utf-8")

    # Absolute dropdowns are clipped by overflow-y:auto on iOS/Android.
    assert "position: static !important;" in css
    assert "-webkit-overflow-scrolling: touch;" in css
    assert "100svh" in css
    assert "env(safe-area-inset-bottom, 0px)" in css
    assert "white-space: normal !important;" in css
    assert "[data-assessments-nav]:not([data-assessments-ready])" in css
    assert "align-items: stretch !important;" in css
    assert "min-height: 44px" in css
    # Portrait + landscape (short viewport) both covered.
    assert "orientation: landscape" in css
    assert "max-height: 500px" in css
    assert "assessments-nav--drop-up" in css
    assert "assessments-nav--align-end" in css

    # Chooser reveals itself after open and survives rotation.
    assert "scrollIntoView" in js
    assert "ignoreDocClickUntil" in js
    assert "orientationchange" in js
    assert "placeMenu" in js
    assert "inDrawer" in js


def test_assessments_nav_route_integrity_is_unchanged():
    js = (STATIC / "assessments-nav.js").read_text(encoding="utf-8")
    admin_block = js.split("var ADMIN_ROUTES = [", 1)[1].split("];", 1)[0]
    customer_block = js.split("var CUSTOMER_ROUTES = [", 1)[1].split("];", 1)[0]
    admin_hrefs = tuple(re.findall(r"href:\s*'([^']+)'", admin_block))
    customer_hrefs = tuple(re.findall(r"href:\s*'([^']+)'", customer_block))
    assert admin_hrefs == ADMIN_ROUTE_HREFS
    assert customer_hrefs == CUSTOMER_ROUTE_HREFS
    # Chrome-only: no fetch / POST / localStorage writes from the chooser.
    assert "fetch(" not in js
    assert "XMLHttpRequest" not in js
    assert "localStorage.setItem" not in js
    assert "sessionStorage.setItem" not in js


def test_admin_and_customer_mount_assessments_chooser():
    admin = requests.get(f"{BASE_URL}/admin.html").text
    assert 'data-assessments-nav' in admin
    assert 'data-assessments-role="admin"' in admin
    assert 'data-assessments-nav data-assessments-role="admin">Assessments</span>' in admin
    assert 'assessments-nav.js' in admin
    assert 'phins-theme.css' in admin
    # No longer a single hard-wired Assessments <a> only destination
    assert 'href="/unified-workbench.html">📋 Assessments</a>' not in admin
    assert "orientation: landscape" in admin
    assert ".phins-nav .assessments-nav-menu" in admin
    assert "white-space: normal" in admin

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
        ("/risk-assessment-viewer.html", "Risk Assessment Report"),
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
