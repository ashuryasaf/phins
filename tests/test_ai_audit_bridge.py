"""
Tests for AI audit durability + claims-bot audit parity
========================================================
Covers:
- ``services.ai_audit_bridge`` wiring of the AI decision log to a durable
  persister, and its best-effort (never-fatal) contract.
- Claims-bot audit logging no longer silently swallows failures and records a
  durable audit event, plus the new bounded report retention + ``list_reports``.
"""

import pytest

import services.ai_audit_bridge as bridge
from services.ai_decision_log import AIDecisionLog, get_ai_decision_log
from services.claims_bot_service import ClaimsBotService


# --------------------------------------------------------------------------
# ai_audit_bridge
# --------------------------------------------------------------------------

def test_wire_attaches_persister_and_is_idempotent(monkeypatch):
    captured = []
    monkeypatch.setattr(bridge, '_wired', False)
    monkeypatch.setattr(bridge, '_persist_decision_to_audit',
                        lambda rec: captured.append(rec))

    # Reset the singleton persister so the test is isolated.
    log = get_ai_decision_log()
    log.set_db_persister(None)

    assert bridge.wire_ai_decision_log() is True
    assert bridge.is_wired() is True
    # Idempotent: a second call is a no-op that still reports wired.
    assert bridge.wire_ai_decision_log() is True

    did = log.record(decision_type='quote', output={'decision': 'quote_generated'})
    assert did
    assert len(captured) == 1
    assert captured[0]['decision_id'] == did

    # Clean up shared singleton state for other tests.
    log.set_db_persister(None)


def test_record_ai_audit_never_raises_without_database(monkeypatch):
    # Simulate the database layer being unavailable: the call must be a safe
    # no-op returning False rather than raising into the AI path.
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == 'database.manager':
            raise ImportError("no database in this build")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, '__import__', fake_import)
    assert bridge.record_ai_audit('ai_decision', 'customer', 'CUST1', {'x': 1}) is False


def test_persist_decision_to_audit_swallows_persister_errors(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("db exploded")

    monkeypatch.setattr(bridge, 'record_ai_audit', boom)
    # Must not raise.
    bridge._persist_decision_to_audit({'decision_id': 'AIDEC-1', 'entity_type': 'customer',
                                       'entity_id': 'CUST1', 'human_override': None})


def test_decision_log_record_still_safe_with_real_bridge_persister(monkeypatch):
    # Even if the bridge persister fails, recording must not raise (decision
    # log contract) and the in-memory record must still be retrievable.
    log = AIDecisionLog()
    monkeypatch.setattr(bridge, 'record_ai_audit',
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    log.set_db_persister(bridge._persist_decision_to_audit)
    did = log.record(decision_type='underwrite', output={'decision': 'auto_approve'})
    assert log.get(did) is not None


# --------------------------------------------------------------------------
# claims-bot audit parity + retention
# --------------------------------------------------------------------------

class _RecordingAudit:
    def __init__(self):
        self.events = []

    def log(self, *args, **kwargs):
        self.events.append((args, kwargs))


class _ExplodingAudit:
    def log(self, *args, **kwargs):
        raise RuntimeError("audit backend down")


def _claim_fixture():
    customers = {'CUST1': {'id': 'CUST1', 'name': 'Test'}}
    policies = {'POL1': {'id': 'POL1', 'start_date': '2020-01-01', 'coverage_amount': 100000}}
    claims = {'CLM1': {'id': 'CLM1', 'customer_id': 'CUST1', 'policy_id': 'POL1',
                       'claimed_amount': 1000, 'filed_date': '2024-01-01', 'type': 'medical'}}
    return customers, policies, claims


def test_claims_bot_log_event_does_not_raise_when_audit_backend_fails(monkeypatch):
    monkeypatch.setattr(bridge, 'record_ai_audit', lambda *a, **k: False)
    customers, policies, claims = _claim_fixture()
    bot = ClaimsBotService(customers=customers, policies=policies, claims=claims,
                           audit_service=_ExplodingAudit())
    # Should complete without raising even though the audit backend throws.
    report = bot.generate_probability_report('CLM1')
    assert report is not None


def test_claims_bot_records_durable_audit_event(monkeypatch):
    calls = []
    monkeypatch.setattr(bridge, 'record_ai_audit',
                        lambda **kwargs: calls.append(kwargs) or True)
    customers, policies, claims = _claim_fixture()
    bot = ClaimsBotService(customers=customers, policies=policies, claims=claims)
    bot.generate_probability_report('CLM1')
    assert any(c.get('action') == 'claims_bot_probability_report_generated' for c in calls)


def test_claims_bot_list_reports_and_retention_cap(monkeypatch):
    monkeypatch.setattr(bridge, 'record_ai_audit', lambda *a, **k: False)
    customers, policies, claims = _claim_fixture()
    bot = ClaimsBotService(customers=customers, policies=policies, claims=claims)
    bot.MAX_RETAINED_REPORTS = 2
    for _ in range(4):
        bot.generate_probability_report('CLM1')
    assert len(bot.reports) <= 2
    listed = bot.list_reports('CLM1')
    assert listed and all(r['claim_id'] == 'CLM1' for r in listed)
    assert bot.list_reports('NOPE') == []


# --------------------------------------------------------------------------
# trading-engine audit parity
# --------------------------------------------------------------------------

def test_audit_bot_trade_records_event(monkeypatch):
    import services.ai_trading_engine as engine
    calls = []
    monkeypatch.setattr(bridge, 'record_ai_audit',
                        lambda **kwargs: calls.append(kwargs) or True)
    engine._audit_bot_trade({'bot_id': 'BOT1', 'symbol': 'AAPL', 'side': 'buy',
                             'qty': 10, 'order_result': {'id': 'ord1'}})
    assert len(calls) == 1
    assert calls[0]['action'] == 'ai_bot_trade_executed'
    assert calls[0]['entity_id'] == 'BOT1'
    assert calls[0]['success'] is True


def test_audit_bot_trade_marks_failed_order(monkeypatch):
    import services.ai_trading_engine as engine
    calls = []
    monkeypatch.setattr(bridge, 'record_ai_audit',
                        lambda **kwargs: calls.append(kwargs) or True)
    engine._audit_bot_trade({'bot_id': 'BOT1', 'order_result': {'error': 'rejected'}})
    assert calls[0]['success'] is False


def test_audit_bot_trade_never_raises(monkeypatch):
    import services.ai_trading_engine as engine
    monkeypatch.setattr(bridge, 'record_ai_audit',
                        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("x")))
    # Must not raise.
    engine._audit_bot_trade({'bot_id': 'BOT1'})


# --------------------------------------------------------------------------
# risk-report + video-agents audit parity
# --------------------------------------------------------------------------

def test_risk_report_audit_helper(monkeypatch):
    import services.ai_risk_reports_service as rr
    calls = []
    monkeypatch.setattr(bridge, 'record_ai_audit',
                        lambda **kwargs: calls.append(kwargs) or True)
    rr._risk_report_audit('risk_report_generated', 'RPT-1', {'language': 'hebrew'})
    assert calls[0]['action'] == 'risk_report_generated'
    assert calls[0]['entity_type'] == 'risk_report'
    assert calls[0]['entity_id'] == 'RPT-1'


def test_risk_report_audit_never_raises(monkeypatch):
    import services.ai_risk_reports_service as rr
    monkeypatch.setattr(bridge, 'record_ai_audit',
                        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("x")))
    rr._risk_report_audit('risk_report_generated', 'RPT-1', {})


def test_video_audit_helper(monkeypatch):
    import services.video_agents_service as va
    calls = []
    monkeypatch.setattr(bridge, 'record_ai_audit',
                        lambda **kwargs: calls.append(kwargs) or True)
    va._audit_video_event('video_job_submitted', 'JOB-1', {'provider': 'kling'})
    assert calls[0]['action'] == 'video_job_submitted'
    assert calls[0]['entity_type'] == 'video_job'
    assert calls[0]['entity_id'] == 'JOB-1'


def test_video_audit_never_raises(monkeypatch):
    import services.video_agents_service as va
    monkeypatch.setattr(bridge, 'record_ai_audit',
                        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("x")))
    va._audit_video_event('video_job_submitted', 'JOB-1', {})
