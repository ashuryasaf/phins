"""
Tests for the shared underwriting risk scorer.

The scorer is the single source of truth used by BOTH the
``/api/risk-assessment/report`` endpoint and the underwriting decision
endpoints, so these tests pin its extraction semantics, scoring bands, and
HTTP parity (report score == decision-time score).
"""

from __future__ import annotations

import os

import requests

from services.underwriting_risk_scoring import (
    assess_application,
    extract_risk_inputs,
    score_risk_inputs,
)

BASE_URL = os.environ.get("TEST_BASE_URL", "http://localhost:8000")


class TestExtraction:
    def test_minimal_app_yields_unknowns(self):
        inputs = extract_risk_inputs({}, {})
        assert inputs["age"] is None
        assert inputs["bmi"] is None
        assert inputs["smoking_status"] is None
        assert inputs["medical_conditions"] == []

    def test_questionnaire_fallbacks(self):
        app = {"questionnaire": {"age": "42", "smoke": "yes",
                                 "height": 180, "weight": 120}}
        inputs = extract_risk_inputs(app, {})
        assert inputs["age"] == 42
        assert inputs["smoking_status"] == "current"
        assert inputs["bmi"] == 37.0
        # BMI >= 35 auto-adds an obesity condition
        assert any("Obesity" in c["condition"] for c in inputs["medical_conditions"])

    def test_json_string_conditions_parse(self):
        app = {"medical_conditions": '[{"condition": "Diabetes", "risk_impact": 0.18}]'}
        inputs = extract_risk_inputs(app, {})
        assert inputs["medical_conditions"][0]["condition"] == "Diabetes"
        assert inputs["medical_conditions"][0]["risk_impact"] == 0.18

    def test_disability_added_from_direct_field(self):
        app = {"disability_percentage": 60}
        inputs = extract_risk_inputs(app, {})
        cond = inputs["medical_conditions"][0]
        assert "Disability" in cond["condition"]
        assert cond["severity"] == "severe"
        assert cond["exclusion_recommended"] is True


class TestScoringBands:
    def test_clean_applicant_is_very_low_auto_approve(self):
        scores = score_risk_inputs(
            age=30, medical_conditions=[], smoking_status="never", claims_count=0,
        )
        assert scores["overall_risk"] <= 0.15
        assert scores["risk_category"] == "very_low"
        assert scores["recommendation_type"] == "auto_approve"

    def test_unknown_everything_scores_base_only(self):
        scores = score_risk_inputs(
            age=None, medical_conditions=[], smoking_status=None, claims_count=0,
        )
        assert scores["overall_risk"] == 0.10
        assert scores["recommendation_type"] == "auto_approve"

    def test_elderly_smoker_with_conditions_declines(self):
        conditions = [
            {"condition": "Heart Disease", "risk_impact": 0.25, "loading_percentage": 25,
             "severity": "severe", "exclusion_recommended": True},
        ]
        scores = score_risk_inputs(
            age=70, medical_conditions=conditions, smoking_status="current",
            claims_count=5,
        )
        assert scores["overall_risk"] > 0.70
        assert scores["risk_category"] == "very_high"
        assert scores["recommendation_type"] == "decline"

    def test_high_band_refers_to_senior_underwriter(self):
        conditions = [
            {"condition": "Hypertension", "risk_impact": 0.10, "loading_percentage": 15,
             "severity": "moderate"},
        ]
        scores = score_risk_inputs(
            age=60, medical_conditions=conditions, smoking_status="current",
            claims_count=0,
        )
        # 0.10 + 0.20 + 0.10 + 0.25 = 0.65 → high band
        assert scores["risk_category"] == "high"
        assert scores["recommendation_type"] == "refer_senior_uw"
        assert any("Senior underwriter" in c for c in scores["conditions_of_approval"])

    def test_score_capped_at_one(self):
        conditions = [{"condition": f"C{i}", "risk_impact": 0.5} for i in range(5)]
        scores = score_risk_inputs(
            age=80, medical_conditions=conditions, smoking_status="current",
            claims_count=99,
        )
        assert scores["overall_risk"] == 1.0

    def test_assess_application_never_raises(self):
        result = assess_application(None, None)
        assert "overall_risk" in result


class TestReportParity:
    """The HTTP report and the direct scorer must produce identical scores."""

    def _admin_headers(self):
        resp = requests.post(f"{BASE_URL}/api/login", json={
            "username": "admin", "password": "admin123",
        })
        assert resp.status_code == 200, resp.text
        return {"Authorization": f"Bearer {resp.json()['token']}"}

    def test_report_endpoint_matches_shared_scorer(self):
        import web_portal.server as portal

        headers = self._admin_headers()

        app_id = "UW-PARITY-001"
        cust_id = "CUST-PARITY-001"
        pol_id = "POL-PARITY-001"
        portal.CUSTOMERS[cust_id] = {"id": cust_id, "name": "Parity Test"}
        portal.POLICIES[pol_id] = {
            "id": pol_id, "customer_id": cust_id, "type": "life",
            "coverage_amount": 250000, "status": "pending_underwriting",
        }
        portal.UNDERWRITING_APPLICATIONS[app_id] = {
            "id": app_id, "customer_id": cust_id, "policy_id": pol_id,
            "status": "pending", "age": 58, "smoking_status": "current",
            "bmi": 36.0, "disability_percentage": 30,
            "medical_conditions": [
                {"condition": "Hypertension", "risk_impact": 0.15,
                 "loading_percentage": 15, "severity": "moderate"},
            ],
        }

        resp = requests.get(
            f"{BASE_URL}/api/risk-assessment/report",
            params={"application_id": app_id},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        report = resp.json()

        direct = assess_application(
            portal.UNDERWRITING_APPLICATIONS[app_id],
            portal.CUSTOMERS[cust_id],
            claims_count=0,
        )

        assert report["risk_scores"]["overall"] == round(direct["overall_risk"], 4)
        assert report["risk_scores"]["category"] == direct["risk_category"]
        assert report["recommendation"]["type"] == direct["recommendation_type"]
        assert report["recommendation"]["confidence"] == direct["confidence"]
        assert report["recommendation"]["premium_adjustment"] == round(
            direct["premium_adjustment"], 4
        )
