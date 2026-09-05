"""Accountant dashboard is an IFRS / Solvency / kernel control surface."""

import os
from pathlib import Path

import requests

STATIC = Path(__file__).resolve().parents[1] / "web_portal" / "static"
HTML = (STATIC / "accountant-dashboard.html").read_text(encoding="utf-8")
BASE_URL = os.environ.get("TEST_BASE_URL", "http://localhost:8000")


def test_accountant_uses_phins_chrome_and_identity_copy():
    assert 'href="/phins-theme.css"' in HTML
    assert "/phins-logo.svg" in HTML
    assert "Space Grotesk" in HTML
    assert "Financial Control" in HTML
    assert "Premium identity" in HTML
    assert "Cash identity" in HTML
    assert "IFRS 17" in HTML
    assert "Solvency" in HTML


def test_accountant_drops_cross_role_dashboard_tab():
    assert 'data-tab="control"' in HTML
    assert 'data-tab="balancesheet"' in HTML
    assert 'data-tab="solvency"' in HTML
    assert 'data-tab="integrity"' in HTML
    assert 'onclick="showTab(\'dashboards\')"' not in HTML
    assert 'data-tab="dashboards"' not in HTML
    assert "hidden-legacy" in HTML


def test_accountant_keeps_pipeline_hooks():
    for marker in (
        "/api/financial/dashboard-summary",
        "/api/financial/portfolio-report",
        "/api/financial/customer-projection",
        "/api/financial/forecast",
        "/api/financial/data-integrity",
        "/api/finance/reconcile",
        "/api/admin/balance-sheet",
        "function loadQuickStats",
        "function loadBooksReconcile",
        "function loadIntegrityReport",
        "function loadBalanceSheet",
        "function calculateProjection",
        "function loadForecast",
        "function loadPortfolioReport",
        "function loadControlTower",
        'id="total-revenue"',
        'id="total-collected"',
        'id="outstanding-ar"',
        'id="claims-liability"',
        'id="loss-ratio"',
        'id="solvency-ratio"',
        'id="bs-claims-reserve"',
        'id="bs-premium-income"',
        'id="integrity-results"',
        'id="ctl-ledger-premium"',
        'id="ctl-economic-reserve"',
        'id="sv-economic-tp"',
        'id="proj-coverage"',
        'id="forecast-years"',
        'id="portfolio-results"',
    ):
        assert marker in HTML, marker


def test_accountant_does_not_invent_scr_model():
    assert "does not invent an SCR model" in HTML
    assert "seed_claims_reserve" in HTML
    assert "economic claims reserve" in HTML.lower() or "Economic claims reserve" in HTML


def test_accountant_control_tower_pipelines_respond():
    """The rebuilt surface still reads the same finance pipelines."""
    login = requests.post(
        f"{BASE_URL}/api/login",
        json={"username": "accountant", "password": "acct123"},
        timeout=15,
    )
    assert login.status_code == 200, login.text
    token = login.json().get("token") or login.json().get("session_token")
    assert token
    headers = {"Authorization": f"Bearer {token}"}

    page = requests.get(f"{BASE_URL}/accountant-dashboard.html", timeout=15)
    assert page.status_code == 200
    assert "Financial Control" in page.text
    assert 'id="control-tab"' in page.text

    for path in (
        "/api/financial/dashboard-summary?type=accountant",
        "/api/financial/portfolio-report",
        "/api/finance/reconcile",
        "/api/admin/balance-sheet",
        "/api/financial/data-integrity",
    ):
        resp = requests.get(f"{BASE_URL}{path}", headers=headers, timeout=20)
        assert resp.status_code == 200, path
        body = resp.json()
        assert "error" not in body or body.get("success") is True, path
