"""Parameterized pitch/NDA jurisdiction templates replace 52 duplicates."""

from __future__ import annotations

import json
import os
from pathlib import Path

import requests

BASE_URL = os.environ.get("TEST_BASE_URL", "http://127.0.0.1:8000")
STATIC = Path(__file__).resolve().parents[1] / "web_portal" / "static"


def test_jurisdictions_catalog_has_expected_shape():
    data = json.loads((STATIC / "jurisdictions.json").read_text(encoding="utf-8"))
    rows = data["jurisdictions"]
    assert len(rows) >= 20
    ids = {r["id"] for r in rows}
    assert "usa" in ids and "israel" in ids and "germany" in ids
    for row in rows:
        assert row["flag"] and row["country"] and row["authority"]
        assert row["currency"] and row["governing_law"]


def test_country_duplicate_pitch_and_nda_files_removed():
    pitches = list(STATIC.glob("*-capital-markets-pitch.html"))
    ndas = [p for p in STATIC.glob("nda-*.html") if p.name != "nda-dashboard.html"]
    assert pitches == [], f"unexpected pitch duplicates: {[p.name for p in pitches]}"
    assert ndas == [], f"unexpected nda duplicates: {[p.name for p in ndas]}"
    assert (STATIC / "capital-markets-pitch.html").is_file()
    assert (STATIC / "nda.html").is_file()


def test_parameterized_pitch_and_nda_served_with_jurisdiction_query():
    pitch = requests.get(f"{BASE_URL}/capital-markets-pitch.html?jurisdiction=germany")
    assert pitch.status_code == 200
    assert "jurisdictions.json" in pitch.text
    assert "{{AUTHORITY}}" in pitch.text or "BaFin" in pitch.text

    nda = requests.get(f"{BASE_URL}/nda.html?jurisdiction=israel")
    assert nda.status_code == 200
    assert "jurisdictions.json" in nda.text


def test_admin_and_customer_nav_use_assessments_chooser():
    admin = requests.get(f"{BASE_URL}/admin.html").text
    # Chooser host — not three separate top-level Assessment Center / Assessment / AI Reports links
    assert 'data-assessments-nav' in admin
    assert 'href="/assessment-center.html">🧠 Assessment Center</a>' not in admin
    assert 'href="/risk-dashboard.html">🎯 Assessment</a>' not in admin
    assert 'href="/risk-reports-dashboard.html">📊 AI Reports</a>' not in admin

    customer = requests.get(f"{BASE_URL}/dashboard.html").text
    assert 'data-assessments-nav' in customer
    assert 'href="/customer-ai-report.html">🤖 AI Report</a>' not in customer
