"""Accountant dashboard forecast factors, risk-chart scale, and books outline.

The planning-case forecast (omitted factors) must match the historical
projection. Adjusted factors change only the scenario. Risk exposure is the
coverage already counted in the portfolio total, split by band.
"""

import os
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

import pytest
import requests

from services.financial_reporting_service import (
    FinancialReportingService,
    _risk_band,
)

STATIC = Path(__file__).resolve().parents[1] / "web_portal" / "static"
HTML = (STATIC / "accountant-dashboard.html").read_text(encoding="utf-8")
BASE_URL = os.environ.get("TEST_BASE_URL", "http://localhost:8000")


def _book():
    policies = {
        "POL-A": {
            "status": "active",
            "customer_id": "CUST-A",
            "coverage_amount": 100_000,
            "annual_premium": 1_200,
            "type": "life",
            "risk_score": "low",
        },
        "POL-B": {
            "status": "active",
            "customer_id": "CUST-B",
            "coverage_amount": 300_000,
            "annual_premium": 4_000,
            "type": "life",
            "risk_score": "high",
        },
        "POL-C": {
            "status": "lapsed",
            "customer_id": "CUST-A",
            "coverage_amount": 50_000,
            "annual_premium": 900,
            "type": "life",
            "risk_score": "very_high",
        },
    }
    return FinancialReportingService(policies, {}, {}, {}, {})


def _historical_projection(policies, years=2, growth=0.10, inflation=0.03, claim=0.02, lapse=0.03):
    active = [p for p in policies.values() if (p.get("status") or "").lower() == "active"]
    current_premiums = sum(p.get("annual_premium", 0) for p in active)
    current_policies = len(active)
    opening_coverage = sum(p.get("coverage_amount", 0) for p in active)
    avg_claim = (opening_coverage / max(current_policies, 1)) * 0.3
    count = float(current_policies)
    premiums = current_premiums
    cumulative_revenue = 0.0
    cumulative_claims = 0.0
    rows = []
    for year in range(1, years + 1):
        new_policies = count * growth
        count = (count + new_policies) * (1 - lapse)
        premiums = premiums * (1 + inflation) + new_policies * (premiums / max(current_policies, 1))
        expected = count * claim * avg_claim
        cumulative_revenue += premiums
        cumulative_claims += expected
        rows.append({
            "year": year,
            "active_policies": int(round(count)),
            "annual_premium_revenue": round(premiums, 2),
            "expected_claims": round(expected, 2),
            "cumulative_profit": round(cumulative_revenue - cumulative_claims, 2),
        })
    return rows


def test_default_forecast_matches_historical_planning_case():
    svc = _book()
    report = svc.generate_forecast_report(years=3)
    expected = _historical_projection(svc._policies, years=3)
    assert report["assumptions"]["applied"]["source"] == "default"
    assert report["assumptions"]["applied"]["lapse_rate"] == 0.03
    assert report["assumptions"]["new_policy_growth_rate"] == "10.0%"
    assert report["opening_book"]["active_policies"] == 2
    assert report["opening_book"]["annual_premium"] == 5200.0
    for row, historic in zip(report["projections"], expected):
        assert row["active_policies"] == historic["active_policies"]
        assert row["annual_premium_revenue"] == historic["annual_premium_revenue"]
        assert row["expected_claims"] == historic["expected_claims"]
        assert row["cumulative_profit"] == historic["cumulative_profit"]
        assert row["projected_date"] == (datetime.now() + timedelta(days=365 * row["year"])).strftime("%Y-%m-%d")
    assert report["summary"]["terminal_year"] == 3
    assert report["summary"]["year_25_policies"] == report["summary"]["terminal_policies"]
    assert report["summary"]["terminal_profit"] == expected[-1]["cumulative_profit"]


def test_adjustable_factors_change_only_the_scenario():
    svc = _book()
    base = svc.generate_forecast_report(years=2)
    stressed = svc.generate_forecast_report(
        years=2,
        growth_rate=0.20,
        inflation_rate=0.05,
        claim_rate=0.04,
        lapse_rate=0.10,
    )
    assert stressed["assumptions"]["applied"] == {
        "growth_rate": 0.20,
        "inflation_rate": 0.05,
        "claim_rate": 0.04,
        "lapse_rate": 0.10,
        "source": "request",
    }
    assert stressed["projections"][0]["annual_premium_revenue"] != base["projections"][0]["annual_premium_revenue"]
    assert stressed["projections"][0]["expected_claims"] != base["projections"][0]["expected_claims"]
    # Opening book is the live book, not a rewritten premium.
    assert stressed["opening_book"] == base["opening_book"]
    assert svc._policies["POL-A"]["annual_premium"] == 1_200


def test_forecast_rejects_factors_outside_bounds():
    svc = _book()
    with pytest.raises(ValueError, match="growth_rate"):
        svc.generate_forecast_report(growth_rate=0.9)
    with pytest.raises(ValueError, match="years"):
        svc.generate_forecast_report(years=80)
    with pytest.raises(ValueError, match="claim_rate"):
        svc.generate_forecast_report(claim_rate=float("nan"))


def test_customer_forecast_uses_that_book_and_does_not_invent_one():
    svc = _book()
    report = svc.generate_forecast_report(years=1, customer_id="CUST-A")
    assert report["opening_book"]["active_policies"] == 1
    assert report["opening_book"]["annual_premium"] == 1200.0
    assert report["customer_id"] == "CUST-A"
    # Lapsed POL-C is not pulled back into the opening book.
    assert report["assumptions"]["avg_claim_amount"] == round(100_000 * 0.3, 2)
    # A one-policy book survives the lapse step instead of collapsing to zero.
    assert report["projections"][0]["active_policies"] == 1
    assert report["projections"][0]["expected_claims"] > 0
    empty = svc.generate_forecast_report(years=5, customer_id="CUST-MISSING")
    assert empty["projections"] == []
    assert empty["empty_reason"] == "no_active_policies"
    assert empty["summary"]["terminal_profit"] == 0


def test_forecast_reads_coverage_under_either_key():
    svc = FinancialReportingService(
        {
            "POL-D": {
                "status": "active",
                "customer_id": "CUST-D",
                "coverage": 200_000,
                "annual_premium": 2_000,
                "policy_type": "life",
            }
        },
        {},
        {},
        {},
        {},
    )
    report = svc.generate_forecast_report(years=1, customer_id="CUST-D")
    assert report["assumptions"]["avg_claim_amount"] == round(200_000 * 0.3, 2)
    assert report["projections"][0]["expected_claims"] > 0


def test_risk_exposure_is_the_coverage_already_in_the_total():
    svc = _book()
    report = svc.generate_portfolio_report()
    dist = report["risk_distribution"]
    exposure = report["risk_exposure"]
    assert dist == {"low": 1, "medium": 0, "high": 1, "very_high": 0}
    assert exposure["low"] == 100_000
    assert exposure["high"] == 300_000
    assert exposure["medium"] == 0
    assert exposure["very_high"] == 0
    assert sum(exposure.values()) == report["summary"]["total_coverage"]
    assert _risk_band("Very High") == "very_high"
    assert _risk_band(None) == "medium"
    assert _risk_band("unknown-score") == "very_high"


def test_dashboard_scales_risk_bars_and_keeps_factor_and_books_hooks():
    assert "count * 30" not in HTML
    assert "function renderScaledBars" in HTML
    assert "function renderRiskDistribution" in HTML
    assert "function renderBooksFlow" in HTML
    assert 'id="books-outline"' in HTML
    assert 'id="ol-economic"' in HTML
    assert 'id="ol-ledger"' in HTML
    assert 'id="forecast-growth"' in HTML
    assert 'id="forecast-inflation"' in HTML
    assert 'id="forecast-claim-rate"' in HTML
    assert 'id="forecast-lapse"' in HTML
    assert "function forecastRequestUrl" in HTML
    assert "customer_id" in HTML
    assert "growth_rate" in HTML
    assert "Pipeline books" in HTML
    assert "does not invent an SCR model" in HTML
    # The live forecast path is the one that sends factors. The old override
    # fetched years only and dropped the customer filter.
    assert HTML.count("async function loadForecast") == 1
    assert "/api/financial/forecast?years=${years}" not in HTML
    script = subprocess.check_output(
        [
            "node",
            "-e",
            r"""
const fs = require('fs');
const html = fs.readFileSync(process.argv[1], 'utf8');
const blocks = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m => m[1]);
const script = blocks.sort((a, b) => b.length - a.length)[0];
const start = script.indexOf('function renderScaledBars');
const end = script.indexOf('function ledgerTotal');
const fn = script.slice(start, end)
  .replace('function formatCurrency(amount)', '')
  + '\nfunction formatCurrency(amount){return "$"+Number(amount||0).toFixed(2);}\n';
eval(fn);
const chart = renderRiskDistribution(
  {low: 1, medium: 0, high: 3, very_high: 0},
  {low: 100, medium: 0, high: 300, very_high: 0}
);
const heights = [...chart.matchAll(/height:([^;%]+)%/g)].map(m => Number(m[1]));
if (Math.abs(heights[0] - (100/3)) > 0.01) process.exit(2);
if (heights[2] !== 100) process.exit(3);
if ((chart.match(/is-zero/g) || []).length < 2) process.exit(4);
if (!chart.includes('25.0% of policies')) process.exit(5);
if (!chart.includes('75.0% of policies')) process.exit(6);
if (!chart.includes('75.0% of coverage')) process.exit(7);
process.stdout.write('ok');
""",
            str(STATIC / "accountant-dashboard.html"),
        ],
        text=True,
    )
    assert script.strip() == "ok"


def test_forecast_route_honours_factors_and_rejects_bad_input():
    login = requests.post(
        f"{BASE_URL}/api/login",
        json={"username": "accountant", "password": "acct123"},
        timeout=15,
    )
    assert login.status_code == 200, login.text
    token = login.json().get("token") or login.json().get("session_token")
    headers = {"Authorization": f"Bearer {token}"}
    base = requests.get(f"{BASE_URL}/api/financial/forecast?years=2", headers=headers, timeout=20)
    assert base.status_code == 200, base.text
    base_body = base.json()
    assert base_body["assumptions"]["applied"]["source"] == "default"
    adjusted = requests.get(
        f"{BASE_URL}/api/financial/forecast?years=2&growth_rate=0.2&inflation_rate=0.05&claim_rate=0.04&lapse_rate=0.1",
        headers=headers,
        timeout=20,
    )
    assert adjusted.status_code == 200, adjusted.text
    body = adjusted.json()
    assert body["assumptions"]["applied"]["growth_rate"] == 0.2
    assert body["assumptions"]["applied"]["source"] == "request"
    opening = (body.get("opening_book") or {}).get("active_policies") or 0
    if opening and body.get("projections") and base_body.get("projections"):
        changed = (
            body["projections"][0]["annual_premium_revenue"] != base_body["projections"][0]["annual_premium_revenue"]
            or body["projections"][0]["expected_claims"] != base_body["projections"][0]["expected_claims"]
        )
        assert changed
    rejected = requests.get(
        f"{BASE_URL}/api/financial/forecast?years=2&growth_rate=2",
        headers=headers,
        timeout=20,
    )
    assert rejected.status_code == 400
    assert "error" in rejected.json()
