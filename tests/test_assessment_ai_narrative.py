"""
Tests for the additive Assessment AI narrative layer.

Covers:
- The narrative is OFF by default (existing analysis shapes unchanged).
- When requested, it is additive, advisory, low-confidence and needs review.
- It is deterministic and offline by default (no network, reproducible).
- It introduces NO new facts and stays anchored to existing evidence.
- Filters (adjustable reporting) narrow the underlying fact set.
"""

from __future__ import annotations

import pytest

from services.assessment_center_service import AssessmentCenterService
from services.assessment_ai_service import AssessmentAIService


@pytest.fixture
def center(tmp_path):
    return AssessmentCenterService(fact_store_dir=str(tmp_path / "facts"))


def _ingest(center, customer_id="CUST-1"):
    recs = [
        {
            "policy_number": "POL-1", "product_type": "1", "status": "1",
            "company_name": "מגדל", "affiliation_provider": "מגדל",
            "affiliation_product": "New Pension Fund", "accumulated_value": 12000,
            "start_date": "2020-05-01",
        },
        {
            "policy_number": "POL-2", "product_type": "7", "status": "2",
            "company_name": "כלל", "affiliation_provider": "כלל",
            "affiliation_product": "Managers Insurance", "accumulated_value": 0,
            "start_date": "2023-09-15",
        },
    ]
    return center.ingest_external_facts(
        customer_id=customer_id, source="mislaka",
        records=recs, fact_type="external_policy",
    )


class TestNarrativeOptIn:
    def test_off_by_default(self, center):
        _ingest(center)
        payload = center.run_analysis("CUST-1", "describe_data")
        assert "ai_narrative" not in payload

    def test_added_when_requested(self, center):
        _ingest(center)
        payload = center.run_analysis("CUST-1", "describe_data", options={"ai_narrative": True})
        nar = payload["ai_narrative"]
        assert nar["source"] == "assessment_ai"
        assert nar["advisory"] is True
        assert nar["needs_review"] is True
        assert nar["confidence"] <= 0.4
        assert nar["mode"] == "deterministic"


class TestNarrativeIntegrity:
    def test_deterministic_offline(self, center):
        _ingest(center)
        a = center.run_analysis("CUST-1", "cross_document", options={"ai_narrative": True})
        b = center.run_analysis("CUST-1", "cross_document", options={"ai_narrative": True})
        assert a["ai_narrative"]["summary_text"] == b["ai_narrative"]["summary_text"]
        assert a["ai_narrative"]["facts_digest"] == b["ai_narrative"]["facts_digest"]

    def test_evidence_is_anchored_to_real_documents_only(self, center):
        _ingest(center)
        payload = center.run_analysis("CUST-1", "describe_data", options={"ai_narrative": True})
        nar = payload["ai_narrative"]
        # Every highlight must reference a fact that exists in the description.
        described_labels = set()
        for section in payload["description"]["sections"]:
            described_labels.update((section.get("by_label") or {}).keys())
        for h in nar["highlights"]:
            assert h["label"] in described_labels

    def test_llm_disabled_without_config(self):
        svc = AssessmentAIService()
        # No env configured in the test environment.
        assert svc.is_llm_enabled() is False

    def test_audit_trail_records_invocation(self, center):
        _ingest(center)
        center.run_analysis("CUST-1", "describe_data", options={"ai_narrative": True})
        from services.assessment_ai_service import get_assessment_ai_service
        audit = get_assessment_ai_service().recent_audit()
        assert audit, "expected at least one audit record"
        assert audit[-1]["mode"] == "deterministic"


class TestAdjustableReportingFilters:
    def test_policy_number_filter_narrows_facts(self, center):
        _ingest(center)
        full = center.run_analysis("CUST-1", "describe_data")
        filtered = center.run_analysis(
            "CUST-1", "describe_data", options={"filters": {"policy_number": "POL-1"}}
        )
        assert filtered["description"]["fact_count"] < full["description"]["fact_count"]
        assert filtered["description"]["filters_applied"] == {"policy_number": "POL-1"}

    def test_provider_filter(self, center):
        _ingest(center)
        filtered = center.run_analysis(
            "CUST-1", "describe_data", options={"filters": {"provider": "כלל"}}
        )
        assert filtered["description"]["fact_count"] >= 1
