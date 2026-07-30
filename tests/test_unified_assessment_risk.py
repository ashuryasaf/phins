"""Platform-context risk scoring and unified assessment integrity tests."""

from __future__ import annotations

import base64

import pytest

from services.assessment_center_service import AssessmentCenterService
from services.document_processing_service import (
    DocumentProcessingService,
    reset_document_service,
)


@pytest.fixture
def tmp_storage(tmp_path):
    return tmp_path


@pytest.fixture
def doc_service(tmp_storage):
    reset_document_service()
    return DocumentProcessingService(storage_root=str(tmp_storage / "docs"))


@pytest.fixture
def center(tmp_storage, doc_service):
    return AssessmentCenterService(
        document_service=doc_service,
        fact_store_dir=str(tmp_storage / "facts"),
    )


def _b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


class TestPlatformContextRisk:
    def test_pending_claim_increases_score_with_evidence(self, center, doc_service):
        customer_id = "CUST-PLATFORM-RISK"
        text = "Diagnosis: diabetes. Medication: metformin."
        upload = doc_service.upload_document(
            file_name="med.txt",
            file_data_b64=_b64(text),
            mime_type="text/plain",
            customer_id=customer_id,
        )
        center.assess_document(upload.document_id, customer_id=customer_id)

        facts_only = center.compute_risk_indicators(customer_id)
        assert facts_only["scale"] == "0-1"
        assert facts_only["platform_signals_applied"] is False
        assert "fact_store" in facts_only["sources"]
        assert not any(c.get("factor") == "pending_claim" for c in facts_only["contributors"])

        platform_context = {
            "policies": [],
            "claims": [
                {
                    "id": "CLM-PENDING-1",
                    "customer_id": customer_id,
                    "status": "pending",
                    "amount": 1200,
                }
            ],
            "underwriting": [],
            "billing": [],
        }
        with_platform = center.compute_risk_indicators(
            customer_id, platform_context=platform_context,
        )

        assert with_platform["risk_score"] > facts_only["risk_score"]
        assert with_platform["platform_signals_applied"] is True
        assert "claims" in with_platform["sources"]
        pending = [
            c for c in with_platform["contributors"] if c.get("factor") == "pending_claim"
        ]
        assert pending, "pending claim must appear in contributors"
        assert pending[0]["value"] == "CLM-PENDING-1"
        assert pending[0]["weight"] == 0.08
        assert pending[0].get("source") == "claims"

        # Integrity: no fabricated authenticity / invented score fields.
        assert with_platform["risk_score"] <= 1.0
        assert "authenticity_score" not in with_platform
        assert "fabricated" not in str(with_platform).lower()

        unified = center.build_unified_assessment(
            customer_id, platform_context=platform_context,
        )
        assert unified["customer_id"] == customer_id
        assert unified["risk"]["platform_signals_applied"] is True
        assert unified["integrity"]["fact_count"] == unified["profile"]["fact_count"]
        assert unified["integrity"]["documents_with_facts"] >= 1
        assert unified["integrity"]["platform_signals_applied"] is True
        assert "authenticity_score" not in unified
        assert "authenticity_score" not in unified["profile"]

    def test_uw_high_risk_fields_use_only_present_keys(self, center, doc_service):
        customer_id = "CUST-UW-FIELDS"
        text = "Diagnosis: hypertension."
        upload = doc_service.upload_document(
            file_name="uw.txt",
            file_data_b64=_b64(text),
            mime_type="text/plain",
            customer_id=customer_id,
        )
        center.assess_document(upload.document_id, customer_id=customer_id)
        base = center.compute_risk_indicators(customer_id)

        # App without smoking/bmi keys must not invent those contributors.
        ctx_sparse = {
            "underwriting": [
                {"id": "UW-1", "customer_id": customer_id, "status": "approved"}
            ],
        }
        sparse = center.compute_risk_indicators(customer_id, platform_context=ctx_sparse)
        assert not any(
            c.get("factor") in ("uw_smoking", "uw_bmi", "uw_disability_percentage")
            for c in sparse["contributors"]
        )

        ctx_rich = {
            "underwriting": [
                {
                    "id": "UW-2",
                    "customer_id": customer_id,
                    "status": "declined",
                    "disability_percentage": 60,
                    "smoking_status": "smoker",
                    "bmi": 37.5,
                }
            ],
        }
        rich = center.compute_risk_indicators(customer_id, platform_context=ctx_rich)
        factors = {c["factor"] for c in rich["contributors"]}
        assert "uw_rejected" in factors
        assert "uw_disability_percentage" in factors
        assert "uw_smoking" in factors
        assert "uw_bmi" in factors
        assert rich["risk_score"] > base["risk_score"]
        assert rich["risk_score"] <= 1.0
