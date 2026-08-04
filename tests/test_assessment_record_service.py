"""
Unit tests for the assessment record service (score → decision loop closure).

Covers: append-only recording, tamper-evident checksums, decision attachment
with engine/human alignment labeling, pagination shape, and summary
aggregates.
"""

from __future__ import annotations

import pytest

from services.assessment_record_service import (
    AssessmentRecordService,
    compute_alignment,
)


@pytest.fixture()
def svc():
    return AssessmentRecordService()


def _record(svc, **overrides):
    kwargs = dict(
        subject_type="underwriting_application",
        subject_id="UW-TEST-001",
        assessment_type="underwriting_risk",
        customer_id="CUST-T1",
        score=0.12,
        level="very_low",
        recommendation="auto_approve",
        details={"components": {"age_risk": 0.02}},
        engine="underwriting_risk_scoring",
        engine_version="uw-rules-2.0.0",
    )
    kwargs.update(overrides)
    return svc.record_assessment(**kwargs)


class TestRecording:
    def test_record_has_id_checksum_and_fields(self, svc):
        rec = _record(svc)
        assert rec["record_id"].startswith("ASMT-")
        assert rec["payload_sha256"]
        assert rec["score"] == 0.12
        assert rec["level"] == "very_low"
        assert rec["decision"] is None
        assert svc.verify_record(rec["record_id"]) is True

    def test_record_with_immediate_decision_labels_alignment(self, svc):
        rec = _record(svc, decided_by="admin", decision="approved")
        assert rec["decision"] == "approved"
        assert rec["decision_aligned"] is True

    def test_record_never_raises_on_bad_score(self, svc):
        rec = _record(svc, score="not-a-number")
        assert rec["record_id"].startswith("ASMT-")
        assert rec["score"] is None


class TestDecisionAttachment:
    def test_attach_decision_aligned(self, svc):
        rec = _record(svc, recommendation="auto_approve")
        updated = svc.attach_decision(
            rec["record_id"], decided_by="underwriter1", decision="approved"
        )
        assert updated["decision"] == "approved"
        assert updated["decision_aligned"] is True
        assert updated["decided_by"] == "underwriter1"

    def test_attach_decision_misaligned(self, svc):
        rec = _record(svc, recommendation="decline")
        updated = svc.attach_decision(
            rec["record_id"], decided_by="underwriter1", decision="approved"
        )
        assert updated["decision_aligned"] is False

    def test_attach_decision_unknown_record(self, svc):
        assert svc.attach_decision(
            "ASMT-NOPE", decided_by="x", decision="approved"
        ) is None

    def test_engine_output_not_rewritten_by_decision(self, svc):
        rec = _record(svc)
        checksum_before = rec["payload_sha256"]
        svc.attach_decision(rec["record_id"], decided_by="x", decision="rejected")
        after = svc.get_record(rec["record_id"])
        assert after["payload_sha256"] == checksum_before
        assert after["score"] == rec["score"]
        assert svc.verify_record(rec["record_id"]) is True


class TestIntegrity:
    def test_tampered_record_fails_verification(self, svc):
        rec = _record(svc)
        # Simulate on-disk/in-memory tampering with the engine output.
        with svc._lock:
            svc._records[svc._index[rec["record_id"]]]["score"] = 0.99
        assert svc.verify_record(rec["record_id"]) is False

    def test_verify_unknown_record_returns_none(self, svc):
        assert svc.verify_record("ASMT-UNKNOWN") is None


class TestAlignmentMapping:
    @pytest.mark.parametrize("rec,dec,expected", [
        ("auto_approve", "approved", True),
        ("auto_approve", "auto_approved", True),
        ("approve_standard", "approved", True),
        ("approve_with_loading", "approved", True),
        ("approve_with_exclusions", "paid", True),
        ("approve_full", "approved", True),
        ("approve_partial", "approved", True),
        ("decline", "rejected", True),
        ("deny_fraud_suspected", "rejected", True),
        ("deny_hidden_condition", "rejected", True),
        ("refer_senior_uw", "referred", True),
        ("refer_investigation", "rejected", True),
        ("refer_medical_review", "referred", True),
        ("auto_approve", "rejected", False),
        ("decline", "approved", False),
        ("deny_fraud_suspected", "paid", False),
        ("", "approved", None),
        ("auto_approve", "", None),
        ("unheard_of_label", "approved", None),
    ])
    def test_alignment(self, rec, dec, expected):
        assert compute_alignment(rec, dec) is expected

    def test_claims_bot_labels_present(self):
        # Underwriting recommendation labels used by the shared scorer.
        for label in ("approve_standard", "approve_with_loading",
                      "approve_with_exclusions", "refer_senior_uw"):
            assert compute_alignment(label, "approved") is not None or \
                compute_alignment(label, "referred") is not None


class TestListingAndSummary:
    def test_pagination_shape(self, svc):
        for i in range(7):
            _record(svc, subject_id=f"UW-{i}")
        page = svc.list_records(page=1, page_size=5)
        assert set(page.keys()) == {"items", "page", "page_size", "total"}
        assert page["total"] == 7
        assert len(page["items"]) == 5
        page2 = svc.list_records(page=2, page_size=5)
        assert len(page2["items"]) == 2

    def test_filters(self, svc):
        _record(svc, customer_id="CUST-A", subject_id="UW-A")
        _record(svc, customer_id="CUST-B", subject_id="CLM-B",
                subject_type="claim", assessment_type="claims_fraud")
        only_a = svc.list_records(customer_id="CUST-A")
        assert only_a["total"] == 1
        assert only_a["items"][0]["customer_id"] == "CUST-A"
        only_claims = svc.list_records(assessment_type="claims_fraud")
        assert only_claims["total"] == 1
        assert only_claims["items"][0]["subject_type"] == "claim"

    def test_latest_for_subject(self, svc):
        first = _record(svc, subject_id="UW-X", score=0.1)
        second = _record(svc, subject_id="UW-X", score=0.2)
        assert first["record_id"] != second["record_id"]
        latest = svc.latest_for_subject("underwriting_application", "UW-X")
        assert latest["record_id"] == second["record_id"]

    def test_summary_agreement_rate(self, svc):
        r1 = _record(svc, recommendation="auto_approve")
        r2 = _record(svc, recommendation="decline")
        svc.attach_decision(r1["record_id"], decided_by="u", decision="approved")
        svc.attach_decision(r2["record_id"], decided_by="u", decision="approved")
        summary = svc.summary()
        assert summary["total_assessments"] == 2
        assert summary["with_decision"] == 2
        assert summary["aligned_decisions"] == 1
        assert summary["misaligned_decisions"] == 1
        assert summary["agreement_rate"] == 50.0
