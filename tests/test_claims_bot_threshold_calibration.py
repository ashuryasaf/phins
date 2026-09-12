"""
Claims-bot authenticity cut-offs tested against reviewer decisions (item K).

The Monte Carlo evaluation can only show the *mix* the 0.85 / 0.70 / 0.45
cut-offs produce, not their accuracy. Assessment records carry the
authenticity score at decision time and the reviewer's final decision, which
is the labelled set this report reads. It is recommend-only and refuses to
propose anything below the minimum labelled sample.
"""

from __future__ import annotations

import os

import pytest
import requests

from services.assessment_record_service import AssessmentRecordService
from services.claims_bot_service import (
    CALIBRATION_MIN_LABELLED,
    LIVE_AUTHENTICITY_THRESHOLDS,
    calibrate_claims_thresholds,
)

BASE_URL = os.environ.get("TEST_BASE_URL", "http://127.0.0.1:8000")


def _record(auth: float, decision: str, recommendation: str = "approve_full", aligned=None):
    return {
        "assessment_type": "claims_fraud",
        "recommendation": recommendation,
        "details": {"authenticity_probability": auth},
        "decision": decision,
        "decision_aligned": aligned,
    }


def test_live_thresholds_match_make_recommendation_constants():
    assert LIVE_AUTHENTICITY_THRESHOLDS == {"approve_full": 0.85, "approve_partial": 0.70, "deny": 0.45}
    assert CALIBRATION_MIN_LABELLED == 30


def test_insufficient_data_reports_live_performance_but_proposes_nothing():
    records = [_record(0.9, "approved"), _record(0.3, "rejected"), _record(0.8, "referred"),
               {"assessment_type": "underwriting_risk", "decision": "approved", "details": {}},
               {"assessment_type": "claims_fraud", "decision": "approved", "details": {}}]
    out = calibrate_claims_thresholds(records)
    assert out["read_only"] is True
    assert out["labelled_decisions"] == 2
    assert out["referred_decisions_unlabelled"] == 1
    assert out["decisions_without_authenticity_score"] == 1
    assert out["insufficient_data"] is True
    assert out["live_performance"]["agreement_rate"] == 1.0
    assert "proposed_thresholds" not in out and "best_grid_point" not in out
    assert out["adjust_via"].startswith("constants in services/claims_bot_service.py")

    empty = calibrate_claims_thresholds([])
    assert empty["labelled_decisions"] == 0 and empty["live_performance"] is None


def test_agreeing_reviewers_leave_live_thresholds_in_place():
    # Reviewers agree with the authenticity spine everywhere: no proposal.
    records = [_record(0.9, "paid", aligned=True) for _ in range(20)] + \
              [_record(0.75, "approved", aligned=True) for _ in range(10)] + \
              [_record(0.2, "rejected", "deny_fraud_suspected", aligned=True) for _ in range(10)]
    out = calibrate_claims_thresholds(records)
    assert out["insufficient_data"] is False
    assert out["live_performance"]["disagreement_cost"] == 0
    assert out["live_performance"]["agreement_rate"] == 1.0
    assert out["recorded_recommendation_agreement_rate"] == 1.0
    assert out["proposed_thresholds"] is None
    assert out["sweep_size"] > 0


def test_systematic_reviewer_rejections_in_the_partial_band_propose_a_higher_cutoff():
    # Reviewers reject everything scored 0.70–0.79 that the bot would approve.
    records = [_record(0.9, "approved") for _ in range(20)] + \
              [_record(0.72, "rejected", "approve_partial", aligned=False) for _ in range(15)] + \
              [_record(0.2, "rejected", "deny_fraud_suspected") for _ in range(10)]
    out = calibrate_claims_thresholds(records)
    live = out["live_performance"]
    assert live["recommended_approve_reviewer_rejected"] == 15
    proposed = out["proposed_thresholds"]
    assert proposed is not None
    assert proposed["approve_partial"] >= 0.75  # lifts the partial band above the rejected scores
    assert out["best_grid_point"]["disagreement_cost"] < live["disagreement_cost"]
    assert "recommend-only" in out["proposal_basis"]
    # Nothing in the live constants moved.
    assert LIVE_AUTHENTICITY_THRESHOLDS["approve_partial"] == 0.70


def test_reads_real_assessment_records_shape():
    svc = AssessmentRecordService()
    for i in range(3):
        svc.record_assessment(subject_type="claim", subject_id=f"CLM-{i}", assessment_type="claims_fraud",
                              customer_id="C1", score=0.1, level="low", recommendation="approve_full",
                              details={"authenticity_probability": 0.9}, engine="claims_bot",
                              engine_version="claims-rules-1.0", decided_by="adjuster", decision="approved")
    items = svc.list_records(assessment_type="claims_fraud")["items"]
    out = calibrate_claims_thresholds(items)
    assert out["labelled_decisions"] == 3
    assert out["recorded_recommendation_agreement_rate"] == 1.0
    assert out["insufficient_data"] is True


class TestRoute:
    def test_requires_privileged_role(self):
        resp = requests.get(f"{BASE_URL}/api/claims/bot-threshold-calibration")
        assert resp.status_code == 403
        assert set(resp.json()) == {"error"}

    def test_admin_gets_read_only_report(self):
        login = requests.post(f"{BASE_URL}/api/login", json={"username": "admin", "password": "admin123"})
        assert login.status_code == 200, login.text
        headers = {"Authorization": f"Bearer {login.json()['token']}"}
        resp = requests.get(f"{BASE_URL}/api/claims/bot-threshold-calibration", headers=headers, timeout=30)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["success"] is True
        cal = body["calibration"]
        assert cal["read_only"] is True
        assert cal["live_thresholds"] == LIVE_AUTHENTICITY_THRESHOLDS
        assert {"labelled_decisions", "insufficient_data", "min_labelled", "adjust_via"} <= set(cal)
