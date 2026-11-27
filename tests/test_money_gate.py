"""U4 Money Gate Agent — critical-check digest refuses money moves (AE3)."""

from __future__ import annotations

import pytest

from services.erp.money_gate import (
    GATE_REFUSED_ERROR,
    MoneyGateError,
    authorize_money_move,
    critical_failures,
    digest_for,
    evaluate_from_reports,
    http_refuse,
    money_gate_enforced,
)
from services.jobs import books_integrity_job
from web_portal import api_wallet_withdrawal as wallet_api
from web_portal import api_agent_ecosystem as agent_api


def _red_books():
    return {
        'unified': {
            'integrity': {
                'ok': False,
                'failed': ['claims_counted_once', 'marketplace_orders_tie'],
            }
        },
        'reconcile': {'discrepancies': []},
    }


def _green_books():
    return {
        'unified': {'integrity': {'ok': True, 'failed': []}},
        'reconcile': {'discrepancies': []},
    }


def test_critical_failures_filters_non_critical_unified_checks():
    failed = critical_failures(
        unified_failed=['claims_counted_once', 'marketplace_orders_tie'],
        reconcile_discrepancies=[
            {'check': 'paid_claims_missing_customer_ledger'},
            {'check': 'kernel_vs_stored_annual_premium'},
        ],
    )
    assert failed == ['claims_counted_once', 'paid_claims_missing_customer_ledger']


def test_evaluate_claims_counted_once_red(monkeypatch):
    monkeypatch.setenv('PHINS_MONEY_GATE', '1')
    verdict = evaluate_from_reports(
        unified_report=_red_books()['unified'],
        reconcile_report=_red_books()['reconcile'],
        operation='wallet_withdrawal.release',
    )
    assert verdict.ok is False
    assert verdict.failed_checks == ['claims_counted_once']
    assert verdict.digest == digest_for(['claims_counted_once'], ok=False)
    assert verdict.enforced is True


def test_authorize_refuses_when_enforced(monkeypatch):
    monkeypatch.setenv('PHINS_MONEY_GATE', '1')
    with pytest.raises(MoneyGateError) as raised:
        authorize_money_move(
            'wallet_withdrawal.release',
            books=_red_books(),
            actor='accountant',
            role='accountant',
        )
    body = http_refuse(raised.value)
    assert body['error'] == GATE_REFUSED_ERROR
    assert body['failed_checks'] == ['claims_counted_once']
    assert 'digest' in body


def test_authorize_allows_when_enforcement_off(monkeypatch):
    monkeypatch.setenv('PHINS_MONEY_GATE', '0')
    assert money_gate_enforced() is False
    verdict = authorize_money_move(
        'wallet_withdrawal.release',
        books=_red_books(),
        actor='accountant',
        role='accountant',
    )
    assert verdict.ok is False
    assert verdict.enforced is False


def test_authorize_green_path(monkeypatch):
    monkeypatch.setenv('PHINS_MONEY_GATE', '1')
    verdict = authorize_money_move(
        'claim_payout',
        books=_green_books(),
        actor='claims_adjuster',
        role='claims_adjuster',
    )
    assert verdict.ok is True
    assert verdict.failed_checks == []


def test_break_glass_requires_admin_reason_and_journal(monkeypatch):
    monkeypatch.setenv('PHINS_MONEY_GATE', '1')
    events = []

    class _Ledger:
        def append_event(self, **kwargs):
            events.append(kwargs)
            return kwargs

    with pytest.raises(MoneyGateError) as no_admin:
        authorize_money_move(
            'agent_commission.settle',
            books=_red_books(),
            break_glass=True,
            break_glass_reason='force payout for carrier deadline',
            actor='accountant',
            role='accountant',
            platform_ledger=_Ledger(),
        )
    assert 'admin' in str(no_admin.value)

    with pytest.raises(MoneyGateError) as short_reason:
        authorize_money_move(
            'agent_commission.settle',
            books=_red_books(),
            break_glass=True,
            break_glass_reason='short',
            actor='admin',
            role='admin',
            platform_ledger=_Ledger(),
        )
    assert 'reason' in str(short_reason.value)

    verdict = authorize_money_move(
        'agent_commission.settle',
        books=_red_books(),
        break_glass=True,
        break_glass_reason='force payout for carrier deadline',
        actor='admin',
        role='admin',
        platform_ledger=_Ledger(),
    )
    assert verdict.ok is True
    assert verdict.break_glass is True
    assert verdict.failed_checks == ['claims_counted_once']
    assert len(events) == 1
    assert events[0]['event_type'] == 'finance.money_gate_break_glass'


def test_break_glass_fails_closed_without_journal(monkeypatch):
    monkeypatch.setenv('PHINS_MONEY_GATE', '1')
    with pytest.raises(MoneyGateError) as raised:
        authorize_money_move(
            'claim_payout',
            books=_red_books(),
            break_glass=True,
            break_glass_reason='enough characters here',
            actor='admin',
            role='admin',
            platform_ledger=None,
        )
    assert 'journal' in str(raised.value)


def test_books_integrity_job_run_once(monkeypatch):
    monkeypatch.setenv('PHINS_MONEY_GATE', '1')
    result = books_integrity_job.run_once(books=_red_books())
    assert result['ok'] is False
    assert result['failed_checks'] == ['claims_counted_once']


def test_withdrawal_release_api_returns_409_on_red(monkeypatch):
    """AE3: red claims_counted_once → release 409; cash helper never runs."""
    monkeypatch.setenv('PHINS_MONEY_GATE', '1')
    released = {'called': False}

    def _boom(*_a, **_k):
        released['called'] = True
        raise AssertionError('release must not run when gate refuses')

    monkeypatch.setattr(wallet_api.withdrawals, 'release', _boom)

    from services.erp import money_gate as mg

    def _refuse(operation, **_kwargs):
        verdict = mg.evaluate_from_reports(
            unified_report=_red_books()['unified'],
            reconcile_report=_red_books()['reconcile'],
            operation=operation,
        )
        raise mg.MoneyGateError(verdict)

    monkeypatch.setattr(mg, 'authorize_money_move', _refuse)

    status, body = wallet_api.dispatch_post(
        '/api/admin/wallet-withdrawals/WD-TEST/release',
        {'role': 'admin', 'username': 'admin'},
        {'reference': 'x'},
    )
    assert status == 409
    assert body['error'] == GATE_REFUSED_ERROR
    assert body['failed_checks'] == ['claims_counted_once']
    assert released['called'] is False


def test_agent_settle_api_returns_409_on_red(monkeypatch):
    """AE3: red claims_counted_once → commission settle 409; settle never runs."""
    monkeypatch.setenv('PHINS_MONEY_GATE', '1')
    settled = {'called': False}

    def _boom(*_a, **_k):
        settled['called'] = True
        return False, 'should not settle'

    monkeypatch.setattr(agent_api.svc, 'settle_payout', _boom)

    from services.erp import money_gate as mg

    def _refuse(operation, **_kwargs):
        verdict = mg.evaluate_from_reports(
            unified_report=_red_books()['unified'],
            reconcile_report=_red_books()['reconcile'],
            operation=operation,
        )
        raise mg.MoneyGateError(verdict)

    monkeypatch.setattr(mg, 'authorize_money_move', _refuse)

    status, body = agent_api.handle_post(
        '/api/admin/agents/payouts/settle',
        {},
        {'role': 'admin', 'username': 'admin'},
        {'payout_id': 'APAY-TEST'},
        {'platform_ledger': None},
    )
    assert status == 409
    assert body['failed_checks'] == ['claims_counted_once']
    assert settled['called'] is False
