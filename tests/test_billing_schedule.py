"""B2: one due-date answer per billing frequency (PHINS_PLATFORM_ASSESSMENT D3)
and the controller split's re-export / segment / confidence_band contract."""

import os
import sys
from datetime import date, datetime

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from services.automation import billing_schedule as bs  # noqa: E402


@pytest.mark.parametrize("today, expected", [
    (date(2025, 12, 31), date(2026, 1, 1)),    # Q4 -> Q1 rolls the year
    (date(2026, 1, 1), date(2026, 4, 1)),      # Q1 start -> Q2, same year
    (date(2026, 3, 31), date(2026, 4, 1)),     # Q1 end
    (date(2026, 4, 1), date(2026, 7, 1)),
    (date(2026, 6, 30), date(2026, 7, 1)),
    (date(2026, 9, 30), date(2026, 10, 1)),
    (date(2026, 10, 1), date(2027, 1, 1)),     # first day of Q4 still rolls
    (date(2026, 11, 15), date(2027, 1, 1)),
    (date(2024, 2, 29), date(2024, 4, 1)),     # leap day
    (date(2024, 12, 31), date(2025, 1, 1)),    # leap-year Q4
    (date(2100, 12, 31), date(2101, 1, 1)),    # non-leap century boundary
])
def test_next_quarter_start(today, expected):
    assert bs.next_quarter_start(today) == expected
    assert bs.next_quarter_start(datetime.combine(today, datetime.min.time())) == expected
    assert bs.next_quarter_start(today).day == 1
    assert bs.next_quarter_start(today) > today


@pytest.mark.parametrize("today, quarter, start", [
    (date(2026, 1, 1), 1, date(2026, 1, 1)),
    (date(2026, 3, 31), 1, date(2026, 1, 1)),
    (date(2026, 5, 15), 2, date(2026, 4, 1)),
    (date(2026, 8, 2), 3, date(2026, 7, 1)),
    (date(2026, 12, 31), 4, date(2026, 10, 1)),
])
def test_quarter_of_and_current_start(today, quarter, start):
    assert bs.quarter_of(today) == quarter
    assert bs.current_quarter_start(today) == start


def test_invoice_due_date_per_frequency():
    dec31 = date(2025, 12, 31)
    assert bs.invoice_due_date('monthly', dec31) == date(2025, 12, 1)
    assert bs.invoice_due_date('quarterly', dec31) == date(2026, 1, 1)
    assert bs.invoice_due_date('annual', dec31) == date(2025, 1, 1)
    assert bs.invoice_due_date('QUARTERLY ', date(2024, 2, 29)) == date(2024, 4, 1)
    assert bs.invoice_due_date('weird', date(2024, 2, 29)) == date(2024, 1, 1)   # unknown -> annual
    assert bs.invoice_due_date('monthly') == date(date.today().year, date.today().month, 1)


def test_controller_invoice_uses_the_single_schedule_path(monkeypatch):
    import ai_automation_controller as mod

    class _Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2025, 12, 31, 13, 45, 12)

    monkeypatch.setattr(mod, 'datetime', _Frozen)
    controller = mod.AIAutomationController()
    quarterly = controller.auto_generate_invoice({'policy_id': 'POL-1', 'premium_amount': 100,
                                                  'billing_frequency': 'quarterly'})
    assert quarterly['due_date'].startswith('2026-01-01T13:45:12')
    monthly = controller.auto_generate_invoice({'policy_id': 'POL-1', 'premium_amount': 100,
                                                'billing_frequency': 'monthly'})
    assert monthly['due_date'].startswith('2025-12-01T')
    annual = controller.auto_generate_invoice({'policy_id': 'POL-1', 'premium_amount': 100,
                                               'billing_frequency': 'annual'})
    assert annual['due_date'].startswith('2025-01-01T')
    assert quarterly['status'] == 'pending' and quarterly['amount'] == 100


# ---------------------------------------------------------------------------
# Controller split contract
# ---------------------------------------------------------------------------

def test_root_module_still_exports_every_historical_name():
    import ai_automation_controller as mod
    for name in ('AIAutomationController', 'AutomationDecision', 'FraudRisk', 'AutomationMetrics',
                 'get_automation_controller', 'auto_quote', 'auto_underwrite', 'auto_process_claim',
                 'detect_fraud'):
        assert hasattr(mod, name), name
        assert name in mod.__all__
    from services.automation.types import AutomationDecision, FraudRisk
    assert mod.AutomationDecision is AutomationDecision and mod.FraudRisk is FraudRisk
    assert mod.AutomationDecision.AUTO_APPROVE.value == 'auto_approve'


def test_rules_are_pure_and_match_the_controller():
    from services.automation import underwriting_gate, fraud, quoting, claims_gate
    import ai_automation_controller as mod
    controller = mod.AIAutomationController()
    app = {'age': 40, 'smoker': True, 'pre_existing_conditions': False, 'health_score': 6,
           'employment_stable': True, 'recent_claims_count': 3, 'inconsistent_information': True}
    assert controller._assess_risk(app) == underwriting_gate.assess_risk(app) == pytest.approx(0.85)
    assert controller._detect_fraud(app) is fraud.application_fraud_risk(app) is mod.FraudRisk.CRITICAL
    claim = {'claimed_amount': 40000, 'type': 'medical', 'policy_coverage': 50000,
             'average_claim_for_type': 5000}
    assert controller._detect_claim_fraud(claim) is fraud.claim_fraud_risk(claim) is mod.FraudRisk.HIGH
    decision, details, fr = claims_gate.gate(claim)
    assert decision is mod.AutomationDecision.HUMAN_REVIEW and fr is mod.FraudRisk.HIGH
    assert details['requires_investigation'] is True
    quote = quoting.compute_quote({'age': 30, 'coverage_amount': 100000, 'health_score': 10})
    assert quote['annual_premium'] == 120.0 and quote['risk_factors']['health'] == 1.0


def test_confidence_band_and_margin():
    from services.automation.underwriting_gate import confidence_band
    assert confidence_band(0.9, 0.85, 0.15)['band'] == 'auto_approve'
    assert confidence_band(0.85, 0.85, 0.15)['band'] == 'auto_approve'
    assert confidence_band(0.1, 0.85, 0.15)['band'] == 'auto_reject'
    assert confidence_band(0.6, 0.85, 0.15)['band'] == 'review_upper'
    assert confidence_band(0.5, 0.85, 0.15)['band'] == 'review_lower'
    assert confidence_band(0.9, 0.85, 0.15, fraud_hold=True)['band'] == 'fraud_hold'
    band = confidence_band(0.8, 0.85, 0.15)
    assert band['margin'] == pytest.approx(0.05) and band['approve_threshold'] == 0.85


def test_auto_underwrite_returns_segment_and_confidence_band():
    import ai_automation_controller as mod
    controller = mod.AIAutomationController()
    decision, details = controller.auto_underwrite({
        'application_id': 'APP-B2', 'age': 30, 'occupation': 'Teacher', 'smoker': False,
        'pre_existing_conditions': False, 'health_score': 9, 'employment_stable': True})
    assert decision is mod.AutomationDecision.AUTO_APPROVE
    assert details['segment'] == '25_34|teacher'
    assert details['confidence_band'] == 'auto_approve'
    assert details['threshold_margin'] == pytest.approx(0.15)
    # The function-based wrapper (handler-facing) carries the same fields additively.
    legacy = mod.auto_underwrite({'age': 30, 'occupation': 'Teacher', 'smoker': False,
                                  'pre_existing_conditions': False, 'health_score': 9,
                                  'employment_stable': True})
    assert legacy['decision'] == 'AUTO_APPROVE' and legacy['risk_level'] == 'low'
    assert legacy['confidence_band'] == 'auto_approve' and legacy['segment'] == '25_34|teacher'
    # Fraud gate: forced review is labelled as such, not as a mid-band score.
    decision, details = controller.auto_underwrite({
        'age': 30, 'occupation': 'teacher', 'health_score': 9, 'employment_stable': True,
        'inconsistent_information': True})
    assert decision is mod.AutomationDecision.HUMAN_REVIEW
    assert details['confidence_band'] == 'fraud_hold' and details['requires_investigation'] is True
    assert controller.metrics.fraud_detected == 1 and controller.metrics.auto_approved == 1


def test_promoted_segment_changes_only_its_own_segment():
    import ai_automation_controller as mod
    from services.ai_threshold_config import get_threshold_config
    config = get_threshold_config()
    snapshot = config.export()
    try:
        controller = mod.AIAutomationController()
        base = {'age': 30, 'smoker': False, 'pre_existing_conditions': False, 'health_score': 5}
        # 0.5 + 0.2 (age) + 0.1 (non-smoker) + 0.15 (no conditions) = 0.95 -> auto_approve at 0.85
        assert controller.auto_underwrite({**base, 'occupation': 'nurse'})[0] is mod.AutomationDecision.AUTO_APPROVE
        assert controller.auto_underwrite({**base, 'occupation': 'pilot'})[0] is mod.AutomationDecision.AUTO_APPROVE
        config.promote('25_34|nurse', 0.97, 0.10)
        nurse_decision, nurse = controller.auto_underwrite({**base, 'occupation': 'nurse'})
        pilot_decision, pilot = controller.auto_underwrite({**base, 'occupation': 'pilot'})
        assert nurse_decision is mod.AutomationDecision.HUMAN_REVIEW
        assert nurse['confidence_band'] == 'review_upper' and nurse['threshold_margin'] == pytest.approx(0.02)
        assert pilot_decision is mod.AutomationDecision.AUTO_APPROVE
        assert pilot['confidence_band'] == 'auto_approve'
        # The decision-log row carries the band and the thresholds that produced it.
        from services.ai_decision_log import get_ai_decision_log
        rec = get_ai_decision_log().get(nurse['decision_id'])
        assert rec['output']['approve_threshold'] == 0.97 and rec['output']['confidence_band'] == 'review_upper'
    finally:
        config.import_(snapshot)
