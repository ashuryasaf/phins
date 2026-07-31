"""Regression tests for GET /api/risk-assessment/report.

The production risk-assessment viewer showed a generic "Error Loading Report"
because the handler crashed (connection dropped, no HTTP response) on data
shapes that occur in real records:

- numeric fields stored as strings (HTML form submissions): disability_percentage,
  bmi, coverage_amount, age
- questionnaire_responses / medical_conditions / documents stored as JSON
  strings (the database round-trip shape)
- questionnaire values with odd types (boolean "smoke", non-numeric age)
- customers with a NULL email during email-based lookup
- applications with a NULL created_date during latest-application selection

Each test seeds portal state directly (in-memory mode under pytest) and
asserts the endpoint returns a well-formed JSON report instead of crashing.
"""

from __future__ import annotations

import json
import os

import requests

import web_portal.server as portal

BASE_URL = os.environ.get("TEST_BASE_URL", "http://127.0.0.1:8000")


def _admin_token() -> str:
    resp = requests.post(
        f"{BASE_URL}/api/login",
        json={"username": "admin", "password": "admin123"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["token"]


def _get_report(token: str, query: str) -> requests.Response:
    return requests.get(
        f"{BASE_URL}/api/risk-assessment/report{query}",
        headers={"Authorization": f"Bearer {token}"},
    )


def test_report_happy_path():
    token = _admin_token()
    portal.CUSTOMERS["CUST-RPT1"] = {
        "id": "CUST-RPT1", "name": "Norma Normal", "email": "norma@example.com",
        "age": 44, "gender": "female", "occupation": "Teacher",
    }
    portal.UNDERWRITING_APPLICATIONS["UW-RPT1"] = {
        "id": "UW-RPT1", "customer_id": "CUST-RPT1", "policy_type": "health",
        "coverage_amount": 100000, "age": 44, "smoking_status": "never",
        "bmi": 24.0, "disability_percentage": 0,
        "created_date": "2026-01-01T00:00:00", "status": "pending",
    }

    resp = _get_report(token, "?application_id=UW-RPT1")
    assert resp.status_code == 200, resp.text
    report = resp.json()
    assert report["application_id"] == "UW-RPT1"
    assert report["applicant"]["name"] == "Norma Normal"
    assert report["risk_scores"]["category"] in (
        "very_low", "low", "moderate", "elevated", "high", "very_high"
    )
    assert "recommendation" in report


def test_report_with_string_numeric_fields():
    """Regression: string-typed numerics crashed with TypeError (dropped connection)."""
    token = _admin_token()
    portal.CUSTOMERS["CUST-RPT2"] = {"id": "CUST-RPT2", "name": "Stringy Stan", "email": None}
    portal.UNDERWRITING_APPLICATIONS["UW-RPT2"] = {
        "id": "UW-RPT2", "customer_id": "CUST-RPT2", "policy_type": "life",
        "coverage_amount": "250000", "disability_percentage": "30",
        "bmi": "32.5", "age": "51", "smoking_status": "current",
        "created_date": "2026-01-02T00:00:00", "status": "pending",
    }

    resp = _get_report(token, "?application_id=UW-RPT2")
    assert resp.status_code == 200, resp.text
    report = resp.json()
    assert report["coverage_amount"] == 250000.0
    assert report["applicant"]["age"] == 51
    assert report["medical_assessment"]["disability_percentage"] == 30
    # bmi 32.5 -> Obese Class I
    assert report["medical_assessment"]["bmi_category"] == "Obese Class I"


def test_report_with_json_string_fields():
    """Regression: DB-shaped JSON strings crashed with AttributeError ('str'.get)."""
    token = _admin_token()
    portal.CUSTOMERS["CUST-RPT3"] = {
        "id": "CUST-RPT3", "name": "Jason Json", "email": "jason@example.com",
    }
    portal.UNDERWRITING_APPLICATIONS["UW-RPT3"] = {
        "id": "UW-RPT3", "customer_id": "CUST-RPT3", "policy_type": "health",
        "questionnaire_responses": json.dumps({"age": 44, "smoke": "no"}),
        "medical_conditions": json.dumps([
            {"condition": "Asthma", "severity": "mild", "risk_impact": "0.05",
             "loading_percentage": "5"},
        ]),
        "documents": json.dumps([{"type": "passport", "verified": True}]),
        "created_date": "2026-01-03T00:00:00", "status": "pending",
    }

    resp = _get_report(token, "?application_id=UW-RPT3")
    assert resp.status_code == 200, resp.text
    report = resp.json()
    assert report["applicant"]["age"] == 44
    conditions = report["medical_assessment"]["conditions"]
    assert any(c["condition"] == "Asthma" for c in conditions)
    assert report["documents"] and report["documents"][0]["type"] == "passport"
    assert report["medical_assessment"]["smoking_status"] == "never"


def test_report_with_malformed_questionnaire_values():
    """Regression: non-numeric age / boolean smoke crashed (ValueError/AttributeError)."""
    token = _admin_token()
    portal.CUSTOMERS["CUST-RPT4"] = {
        "id": "CUST-RPT4", "name": "Quinn Quest", "email": "quinn@example.com",
        "date_of_birth": "1980-05-05",
    }
    portal.UNDERWRITING_APPLICATIONS["UW-RPT4"] = {
        "id": "UW-RPT4", "customer_id": "CUST-RPT4", "policy_type": "health",
        "questionnaire_responses": {
            "age": "not-a-number", "smoke": True,
            "disability_percentage": "n/a", "height": "abc", "weight": "170",
        },
        "created_date": "2026-01-04T00:00:00", "status": "pending",
    }

    resp = _get_report(token, "?application_id=UW-RPT4")
    assert resp.status_code == 200, resp.text
    report = resp.json()
    # age falls back to DOB-derived value; unparseable values never become 0
    assert report["applicant"]["age"] and report["applicant"]["age"] > 40
    # boolean smoke=True maps to current smoker
    assert report["medical_assessment"]["smoking_status"] == "current"


def test_report_lookup_by_customer_with_null_created_date():
    """Regression: max() over apps with created_date=None crashed with TypeError."""
    token = _admin_token()
    portal.CUSTOMERS["CUST-RPT5"] = {
        "id": "CUST-RPT5", "name": "Nadia Nulldate", "email": "nadia@example.com",
    }
    portal.UNDERWRITING_APPLICATIONS["UW-RPT5A"] = {
        "id": "UW-RPT5A", "customer_id": "CUST-RPT5", "policy_type": "health",
        "created_date": None, "status": "pending",
    }
    portal.UNDERWRITING_APPLICATIONS["UW-RPT5B"] = {
        "id": "UW-RPT5B", "customer_id": "CUST-RPT5", "policy_type": "health",
        "created_date": "2026-01-05T00:00:00", "status": "pending",
    }

    resp = _get_report(token, "?customer_id=CUST-RPT5")
    assert resp.status_code == 200, resp.text
    assert resp.json()["application_id"] == "UW-RPT5B"


def test_report_lookup_by_email_with_null_email_customer_present():
    """Regression: a customer with email=None crashed the email scan (AttributeError)."""
    token = _admin_token()
    portal.CUSTOMERS["CUST-RPT6A"] = {"id": "CUST-RPT6A", "name": "No Email", "email": None}
    portal.CUSTOMERS["CUST-RPT6B"] = {
        "id": "CUST-RPT6B", "name": "Has Email", "email": "hasemail@example.com",
    }
    portal.UNDERWRITING_APPLICATIONS["UW-RPT6"] = {
        "id": "UW-RPT6", "customer_id": "CUST-RPT6B", "policy_type": "health",
        "created_date": "2026-01-06T00:00:00", "status": "pending",
    }

    resp = _get_report(token, "?email=hasemail@example.com")
    assert resp.status_code == 200, resp.text
    assert resp.json()["application_id"] == "UW-RPT6"


def test_report_internal_error_returns_500_json():
    """Regression: unhandled exceptions dropped the connection (no HTTP response),
    so the viewer could only show the generic "Error Loading Report" box.
    The handler must answer with a JSON 500 body instead."""
    token = _admin_token()
    portal.CUSTOMERS["CUST-RPT7"] = {
        "id": "CUST-RPT7", "name": "Crash Case", "email": "crash@example.com",
    }
    portal.UNDERWRITING_APPLICATIONS["UW-RPT7"] = {
        "id": "UW-RPT7", "customer_id": "CUST-RPT7", "policy_type": "health",
        # A set is not JSON-serializable, forcing a crash during response
        # serialization (stand-in for any unanticipated bad data shape).
        "documents": [{"type": "passport", "authenticity_score": {0.9}}],
        "created_date": "2026-01-07T00:00:00", "status": "pending",
    }

    resp = _get_report(token, "?application_id=UW-RPT7")
    assert resp.status_code == 500, resp.text
    body = resp.json()
    assert "error" in body
    assert "risk assessment report" in body["error"]


def test_report_not_found_returns_404_json():
    token = _admin_token()
    resp = _get_report(token, "?application_id=UW-DOES-NOT-EXIST")
    assert resp.status_code == 404
    assert "error" in resp.json()


def test_report_requires_privileged_role():
    resp = requests.get(f"{BASE_URL}/api/risk-assessment/report?application_id=X")
    assert resp.status_code == 403
    assert "error" in resp.json()
