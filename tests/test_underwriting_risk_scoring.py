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

    def test_chat_questionnaire_dob_tobacco_and_conditions(self):
        """Chat senior-referral rows store dob/tobacco/conditions_list, not age/smoke."""
        app = {
            "source": "chat_adl_referral",
            "policy_type": "life",
            "adl_level": 8,
            "questionnaire_responses": {
                "dob": "1975-06-01",
                "tobacco": "yes",
                "height": 175,
                "weight": 95,
                "medical_conditions": "yes",
                "conditions_list": "type 2 diabetes, high blood pressure",
                "daily_function": "significant",
                "family_history": ["none"],
                "hazardous": "no",
            },
        }
        inputs = extract_risk_inputs(app, {})
        assert inputs["age"] is not None and inputs["age"] >= 45
        assert inputs["smoking_status"] == "current"
        assert inputs["bmi"] is not None and inputs["bmi"] >= 30
        assert inputs["adl_level"] == 8
        names = " ".join(c["condition"] for c in inputs["medical_conditions"]).lower()
        assert "diabetes" in names
        assert "adl" in names

    def test_chat_referral_report_does_not_collapse_to_base_score(self):
        """Empty-file 10%/very_low must never replace a stored high chat assessment."""
        app = {
            "id": "UW-CHATREF-INTEGRITY",
            "source": "chat_adl_referral",
            "policy_type": "life",
            "risk_assessment": "high",
            "recommendation_type": "refer_senior_uw",
            "adl_level": 8,
            "questionnaire_responses": {
                "dob": "1975-01-15",
                "tobacco": "yes",
                "height": 175,
                "weight": 95,
                "medical_conditions": "yes",
                "conditions_list": "type 2 diabetes, high blood pressure",
                "daily_function": "significant",
            },
            "data_sources": {
                "channel": "chat",
                "chat_assessment": {
                    "risk_category": "high",
                    "overall_risk": 0.62,
                    "confidence": 0.7,
                    "recommendation_type": "refer_senior_uw",
                    "age": 51,
                    "bmi": 31.0,
                },
                "quote_summary": {
                    "product_id": "phins_unified",
                    "adl_declined": True,
                    "eligible": False,
                },
            },
        }
        result = assess_application(app, {})
        assert result["inputs"]["age"] == 51
        assert result["risk_category"] == "high"
        assert float(result["overall_risk"]) >= 0.5
        assert result["recommendation_type"] == "refer_senior_uw"
        assert result["overall_risk"] != 0.10

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

    def test_chat_referral_risk_report_uses_real_inputs_not_base_score(self):
        import web_portal.server as portal

        headers = self._admin_headers()
        app_id = "UW-CHATREF-REPORT-001"
        cust_id = "CUST-CHATREF-REPORT-001"
        portal.CUSTOMERS[cust_id] = {
            "id": cust_id, "name": "High Risk Chat", "email": "high.risk@example.com",
            "dob": "1975-01-15", "phone": "+1-555-0199",
        }
        portal.UNDERWRITING_APPLICATIONS[app_id] = {
            "id": app_id,
            "customer_id": cust_id,
            "customer_name": "High Risk Chat",
            "customer_email": "high.risk@example.com",
            "customer_phone": "+1-555-0199",
            "status": "pending",
            "source": "chat_adl_referral",
            "policy_type": "life",  # legacy wrong label — report must remap
            "policy_id": None,
            "coverage_amount": 500000,
            "risk_assessment": "high",
            "risk_score": "high",
            "recommendation_type": "refer_senior_uw",
            "adl_level": 8,
            "age": 51,
            "bmi": 31.0,
            "height_cm": 175,
            "weight_kg": 95,
            "smoking_status": "current",
            "gender": "male",
            "occupation": "Teacher",
            "questionnaire_responses": {
                "dob": "1975-01-15",
                "tobacco": "yes",
                "height": 175,
                "weight": 95,
                "medical_conditions": "yes",
                "conditions_list": "type 2 diabetes, high blood pressure",
                "daily_function": "significant",
            },
            "medical_conditions": [
                {"condition": "type 2 diabetes", "risk_impact": 0.15,
                 "loading_percentage": 15, "severity": "moderate"},
                {"condition": "high blood pressure", "risk_impact": 0.12,
                 "loading_percentage": 12, "severity": "moderate"},
            ],
            "data_sources": {
                "channel": "chat",
                "chat_assessment": {
                    "risk_category": "high",
                    "overall_risk": 0.62,
                    "confidence": 0.7,
                    "recommendation_type": "refer_senior_uw",
                    "age": 51,
                    "bmi": 31.0,
                },
                "quote_summary": {
                    "product_id": "phins_unified",
                    "adl_declined": True,
                    "eligible": False,
                    "tables_version": "mort_v1",
                    "config_version": "cfg_v1",
                },
            },
        }

        resp = requests.get(
            f"{BASE_URL}/api/risk-assessment/report",
            params={"application_id": app_id},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        report = resp.json()

        assert report["applicant"]["age"] == 51
        assert report["policy_type"] == "phins_unified"
        assert report["risk_scores"]["category"] == "high"
        assert float(report["risk_scores"]["overall"]) >= 0.5
        assert float(report["risk_scores"]["overall"]) != 0.10
        assert report["recommendation"]["type"] == "refer_senior_uw"
        assert report["medical_assessment"]["adl_level"] == 8
        assert report["medical_assessment"]["smoking_status"] == "current"
        assert len(report["medical_assessment"]["conditions"]) >= 1
