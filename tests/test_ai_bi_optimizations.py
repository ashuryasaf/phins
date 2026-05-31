"""
Tests for the AI/BI optimization work
=====================================
Covers:
- BI-1 canonical KPI definitions
- BI-2 dashboard caching (freshness + invalidation on data change)
- AI-1 append-only decision log (record + override is additive)
- AI-2 segment thresholds (default == legacy behavior) + recommend-only calibration
- AI agent: controller logs every decision and behavior is preserved
"""

import pytest

from services import kpi_definitions as kpi
from services.bi_analytics_service import BIAnalyticsService
from services.ai_decision_log import AIDecisionLog
from services.ai_threshold_config import (
    ThresholdConfig, calibrate_thresholds, segment_key,
    DEFAULT_APPROVE_THRESHOLD, DEFAULT_REJECT_THRESHOLD,
)
from ai_automation_controller import AIAutomationController, AutomationDecision


# --------------------------------------------------------------------------
# BI-1 canonical KPIs
# --------------------------------------------------------------------------

def test_kpi_loss_ratio_and_zero_denominator():
    assert kpi.loss_ratio_pct(50, 100) == 50.0
    assert kpi.loss_ratio_pct(50, 0) == 0.0       # defensive: no premium base
    assert kpi.loss_ratio_pct(None, 100) == 0.0


def test_kpi_approval_rate_and_net_worth():
    assert kpi.approval_rate_pct(80, 100) == 80.0
    assert kpi.approval_rate_pct(1, 0) == 0.0
    assert kpi.net_worth(1000, 200) == 800.0


def test_kpi_mrr_arr():
    policies = {
        'P1': {'status': 'active', 'monthly_premium': 500},
        'P2': {'status': 'active', 'monthly_premium': 1000},
        'P3': {'status': 'inactive', 'monthly_premium': 300},
    }
    mrr = kpi.monthly_recurring_revenue(policies)
    assert mrr == 1500.0
    assert kpi.annual_recurring_revenue(mrr) == 18000.0


# --------------------------------------------------------------------------
# BI-2 caching
# --------------------------------------------------------------------------

def test_dashboard_cache_returns_same_object_until_data_changes():
    svc = BIAnalyticsService(cache_ttl_seconds=300)
    customers = {'C1': {'status': 'active'}}
    policies = {'P1': {'status': 'active', 'monthly_premium': 100, 'annual_premium': 1200, 'coverage_amount': 1000}}
    claims, billing, bs = {}, {}, {'total_assets': 10, 'total_liabilities': 1, 'claims_reserve': 5}

    first = svc.get_executive_dashboard(customers, policies, claims, billing, bs)
    second = svc.get_executive_dashboard(customers, policies, claims, billing, bs)
    # Cache hit returns the identical cached object (same generated_at).
    assert first is second

    # Mutating the data changes the fingerprint -> recompute -> different object.
    policies['P2'] = {'status': 'active', 'monthly_premium': 50, 'annual_premium': 600, 'coverage_amount': 500}
    third = svc.get_executive_dashboard(customers, policies, claims, billing, bs)
    assert third is not second
    assert third['summary']['active_policies'] == 2

    # Explicit invalidation forces recompute even with identical data.
    fourth = svc.get_executive_dashboard(customers, policies, claims, billing, bs)
    assert fourth is third
    svc.invalidate_cache()
    fifth = svc.get_executive_dashboard(customers, policies, claims, billing, bs)
    assert fifth is not fourth


# --------------------------------------------------------------------------
# AI-1 decision log
# --------------------------------------------------------------------------

def test_decision_log_is_append_only_and_override_is_additive():
    log = AIDecisionLog()
    did = log.record(
        decision_type='underwrite',
        output={'decision': 'auto_approve', 'risk_score': 0.9},
        inputs={'age': 30},
        model_version='rules-v1',
    )
    rec = log.get(did)
    assert rec['output']['decision'] == 'auto_approve'
    assert rec['human_override'] is None

    # Override fills the override fields but never rewrites the original output.
    assert log.record_override(did, 'reject', reason='manual', overridden_by='uw1') is True
    rec2 = log.get(did)
    assert rec2['output']['decision'] == 'auto_approve'   # original preserved
    assert rec2['human_override'] == 'reject'
    assert rec2['overridden_by'] == 'uw1'

    summary = log.summary()
    assert summary['total_decisions'] == 1
    assert summary['human_overrides'] == 1
    assert summary['override_rate'] == 100.0


def test_decision_log_record_never_raises_on_bad_persister():
    log = AIDecisionLog()
    log.set_db_persister(lambda rec: (_ for _ in ()).throw(RuntimeError("db down")))
    # Must not raise despite the persister blowing up.
    did = log.record(decision_type='quote', output={'decision': 'quote_generated'})
    assert log.get(did) is not None


# --------------------------------------------------------------------------
# AI-2 thresholds + calibration
# --------------------------------------------------------------------------

def test_segment_thresholds_default_to_legacy_constants():
    cfg = ThresholdConfig()
    approve, reject = cfg.get('35_44|office_worker')
    assert approve == DEFAULT_APPROVE_THRESHOLD
    assert reject == DEFAULT_REJECT_THRESHOLD


def test_threshold_promotion_validates_ordering():
    cfg = ThresholdConfig()
    cfg.promote('35_44|office_worker', approve=0.8, reject=0.2)
    assert cfg.get('35_44|office_worker') == (0.8, 0.2)
    with pytest.raises(ValueError):
        cfg.promote('x', approve=0.2, reject=0.5)  # reject must be below approve


def test_calibration_is_recommend_only_with_insufficient_data():
    decisions = [{
        'decision_type': 'underwrite',
        'segment': '25_34|office_worker',
        'output': {'decision': 'auto_approve'},
        'human_override': 'reject',
    }]
    result = calibrate_thresholds(decisions, min_samples_per_segment=20)
    rec = result['recommendations']['25_34|office_worker']
    assert rec['status'] == 'insufficient_data'
    assert rec['recommended_approve'] == DEFAULT_APPROVE_THRESHOLD


def test_segment_key_shape():
    assert segment_key({'age': 30, 'occupation': 'Office_Worker'}) == '25_34|office_worker'


# --------------------------------------------------------------------------
# AI agent: behavior preserved + decisions logged
# --------------------------------------------------------------------------

def test_controller_logs_decisions_and_preserves_behavior():
    c = AIAutomationController()  # fresh instance shares singleton decision log
    if c._decision_log:
        c._decision_log.clear()

    decision, details = c.auto_underwrite({
        'age': 30, 'smoker': False, 'pre_existing_conditions': False,
        'health_score': 8, 'employment_stable': True,
    })
    # High-quality applicant still auto-approves (unchanged behavior).
    assert decision == AutomationDecision.AUTO_APPROVE
    assert 'risk_score' in details
    assert 'decision_id' in details
    assert details['segment'] == '25_34|unknown'

    claim_decision, _ = c.auto_process_claim({
        'claimed_amount': 750, 'type': 'medical', 'policy_coverage': 100000,
    })
    assert claim_decision == AutomationDecision.AUTO_APPROVE  # low-value medical

    summary = c.get_decision_log_summary()
    assert summary['available'] is True
    assert summary['total_decisions'] >= 2


def test_decision_log_scrubs_pii_from_inputs():
    """Raw PII must never reach the append-only decision log."""
    c = AIAutomationController()
    if c._decision_log:
        c._decision_log.clear()

    c.auto_underwrite({
        # PII that must be dropped:
        'name': 'Jane Doe', 'email': 'jane@example.com', 'phone': '+972-50-0000000',
        'national_id': '123456789', 'address': '1 Herzl St, Tel Aviv',
        'medical_notes': 'sensitive free text',
        # Non-PII features that may be logged:
        'age': 40, 'occupation': 'construction', 'smoker': True,
        'pre_existing_conditions': False, 'health_score': 6, 'employment_stable': True,
    })
    rec = c._decision_log.recent(1)[0]
    logged = rec['inputs']
    for pii in ('name', 'email', 'phone', 'national_id', 'address', 'medical_notes'):
        assert pii not in logged, f"PII field {pii} leaked into decision log"
    assert logged.get('age') == 40
    assert logged.get('occupation') == 'construction'


def test_decision_log_deepcopy_detaches_snapshot():
    log = AIDecisionLog()
    payload = {'nested': {'amount': 100}, 'items': [1, 2]}
    did = log.record(decision_type='claim', output={'decision': 'x'}, inputs=payload)
    # Mutate the caller's payload after recording.
    payload['nested']['amount'] = 999
    payload['items'].append(3)
    snap = log.get(did)['inputs']
    assert snap['nested']['amount'] == 100   # snapshot detached
    assert snap['items'] == [1, 2]


def test_model_registry_refuses_unsigned_artifact(tmp_path, monkeypatch):
    from services.ai_model_registry import ModelRegistry, MODEL_HMAC_KEY_ENV
    artifact = tmp_path / 'underwriting-v1.joblib'
    artifact.write_bytes(b'not-a-real-model')

    reg = ModelRegistry(model_dir=str(tmp_path))

    # No key configured -> refuse to load (returns None, falls back to rules).
    monkeypatch.delenv(MODEL_HMAC_KEY_ENV, raising=False)
    assert reg.get_model('underwriting') is None

    # Key set but no/!invalid signature -> still refuse.
    reg.reload()
    monkeypatch.setenv(MODEL_HMAC_KEY_ENV, 'test-secret')
    assert reg.get_model('underwriting') is None  # no .sig file present
    assert ModelRegistry._signature_valid(str(artifact), b'not-a-real-model') is False


def test_model_registry_signature_gate_accepts_valid_hmac(tmp_path, monkeypatch):
    import hashlib
    import hmac as _hmac
    from services.ai_model_registry import ModelRegistry, MODEL_HMAC_KEY_ENV

    data = b'model-bytes'
    artifact = tmp_path / 'underwriting-v1.joblib'
    artifact.write_bytes(data)
    key = 'top-secret-key'
    sig = _hmac.new(key.encode(), data, hashlib.sha256).hexdigest()
    (tmp_path / 'underwriting-v1.joblib.sig').write_text(sig)

    monkeypatch.setenv(MODEL_HMAC_KEY_ENV, key)
    # The HMAC gate itself accepts the valid signature...
    assert ModelRegistry._signature_valid(str(artifact), data) is True
    # ...and a wrong key is rejected.
    monkeypatch.setenv(MODEL_HMAC_KEY_ENV, 'wrong-key')
    assert ModelRegistry._signature_valid(str(artifact), data) is False


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
