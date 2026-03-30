from __future__ import annotations

import pytest

from services.advanced_ai_assessment_service import AdvancedAIAssessmentService


def test_document_uses_adjusted_risk_for_recommendation_and_bi_insights():
    service = AdvancedAIAssessmentService()

    assessment = service.assess_document(
        {
            "name": "medical-summary.txt",
            "document_type": "medical",
            "entity_type": "underwriting",
            "note": "Applicant has diabetes.",
        },
        affiliated_context={
            "application": {
                "coverage_amount": 500000,
                "questionnaire_responses": {"smoker": "yes"},
            },
            "customer": {"email": "applicant@example.com"},
            "related_documents": [],
        },
    )

    assert assessment["risk_score"] > 0.65
    assert assessment["risk_level"] == "high"
    assert assessment["recommendation"] == "refer_manual_review"
    assert assessment["bi_insights"]["portfolio_signal"]["risk_level"] == "high"
    assert assessment["bi_insights"]["portfolio_signal"]["risk_score"] == pytest.approx(0.68)


def test_policy_application_uses_adjusted_risk_for_recommendation_and_bi_insights():
    service = AdvancedAIAssessmentService()

    assessment = service.assess_policy_application(
        {
            "age": 60,
            "coverage_amount": 500000,
            "medical_exam_required": True,
        },
        customer={"email": "applicant@example.com"},
        documents=[
            {
                "name": "billing-receipt.txt",
                "document_type": "receipt",
                "entity_type": "policy",
                "note": "Past due invoice total $60000.",
            }
        ],
    )

    assert assessment["risk_score"] > 0.65
    assert assessment["risk_level"] == "high"
    assert assessment["recommendation"] == "refer_manual_review"
    assert assessment["bi_insights"]["pricing_signal"]["recommended_review_band"] == "high"
    assert assessment["document_assessments"][0]["risk_level"] == "medium"


def test_claim_uses_adjusted_risk_for_recommendation_and_bi_insights():
    service = AdvancedAIAssessmentService()

    assessment = service.assess_claim(
        {
            "description": "Hospital treatment needed after injury.",
        },
        customer={"email": "claimant@example.com"},
        documents=[
            {
                "name": "billing-receipt.txt",
                "document_type": "receipt",
                "entity_type": "general",
                "note": "Past due invoice total $60000.",
            }
        ],
    )

    assert assessment["risk_score"] > 0.65
    assert assessment["risk_level"] == "high"
    assert assessment["recommendation"] == "manual_investigation"
    assert assessment["bi_insights"]["claims_impact"]["review_band"] == "high"
    assert assessment["document_assessments"][0]["risk_level"] == "medium"


def test_claim_skips_zero_triggered_documents_finding():
    service = AdvancedAIAssessmentService()

    assessment = service.assess_claim(
        {"description": ""},
        documents=[
            {
                "name": "identity-card.txt",
                "document_type": "id",
                "entity_type": "claim",
                "note": "Government identity card.",
            }
        ],
    )

    assert "0 attached file(s) triggered elevated review logic." not in assessment["findings"]
    assert assessment["findings"] == [
        "Claim intake data supports standard adjudication with normal review depth."
    ]


def test_dataset_missing_rate_uses_sampled_row_denominator():
    service = AdvancedAIAssessmentService()
    rows = [{"policy_id": None, "risk_score": None, "premium": None} for _ in range(4000)]

    assessment = service.assess_uploaded_dataset(
        document_name="portfolio.csv",
        parsed_data={
            "columns": ["policy_id", "risk_score", "premium"],
            "rows": rows,
        },
    )

    assert "DATASET_HIGH_MISSING_RATE" in assessment["flags"]
    assert assessment["bi_insights"]["dataset_quality"]["missing_rate"] == pytest.approx(1.0)
