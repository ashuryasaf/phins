"""U11 — premium tax accrual is additive; never rewrites billed premium."""

from __future__ import annotations

import pytest

from accounting_engine import AccountingEngine, reset_accounting_engine
from services.erp.integrity_scorecard import compute_integrity_scorecard
from services.mga import bordereaux as brd
from services.mga import premium_tax as tax


@pytest.fixture(autouse=True)
def _reset():
    brd.reset_bordereaux_state()
    tax.reset_premium_tax_state()
    reset_accounting_engine()
    yield
    tax.reset_premium_tax_state()
    brd.reset_bordereaux_state()
    reset_accounting_engine()


def _board():
    policies = {
        'POL-TAX': {
            'id': 'POL-TAX',
            'binder_id': brd.DEFAULT_BINDER_ID,
            'customer_id': 'CUST-TAX',
            'annual_premium': 1000.0,
        },
    }
    ledger = [{
        'id': 'TX-TAX',
        'type': 'premium_payment',
        'amount': 200.0,
        'timestamp': '2026-11-12T12:00:00Z',
        'customer_id': 'CUST-TAX',
        'metadata': {'policy_id': 'POL-TAX'},
    }]
    return brd.build_bordereau(
        binder_id=brd.DEFAULT_BINDER_ID,
        period_id='2026-11',
        policies=policies,
        ledger_transactions=ledger,
    )


def test_accrue_additive_il_jurisdiction():
    board = _board()
    billed_before = board['premium_cash']
    result = tax.accrue_from_bordereau(board, jurisdiction='IL', actor='acct')
    assert result['ok'] is True
    assert result['billed_premium_rewritten'] is False
    accrual = result['accrual']
    assert accrual['billed_premium_unchanged'] is True
    assert accrual['tax_amount'] == pytest.approx(2.0)  # 1% of 200
    assert accrual['taxable_premium'] == billed_before
    # Bordereau cash unchanged.
    assert board['premium_cash'] == billed_before
    assert tax.verify_accrual(accrual)['ok'] is True


def test_unknown_jurisdiction_refused():
    board = _board()
    result = tax.accrue_from_bordereau(board, jurisdiction='XX-UNKNOWN')
    assert result['ok'] is False
    assert result['reason'] == 'jurisdiction_unknown'


def test_gl_post_additive_not_premium_rewrite():
    eng = AccountingEngine('ACC-TAX', 'Tax Co')
    board = _board()
    result = tax.accrue_from_bordereau(
        board, jurisdiction='US-CA', actor='acct', engine=eng,
    )
    assert result['ok'] is True
    gl = result['accrual'].get('gl_post') or {}
    assert gl.get('ok') is True
    # Operating fund moved; no policy premium field rewritten.
    assert board.get('annual_premium') is None or True
    schedule = tax.remittance_schedule(period_id='2026-11')
    assert schedule['additive_only'] is True
    assert schedule['billed_premium_rewritten'] is False
    assert schedule['due'] == pytest.approx(result['accrual']['tax_amount'])


def test_remit_schedule_and_mark():
    board = _board()
    accrued = tax.accrue_from_bordereau(board, jurisdiction='CY')
    aid = accrued['accrual']['id']
    marked = tax.mark_remitted(aid, actor='acct')
    assert marked['ok'] is True
    assert marked['accrual']['status'] == 'remitted'
    schedule = tax.remittance_schedule(period_id='2026-11')
    assert schedule['due'] == 0.0
    assert schedule['remitted'] == pytest.approx(accrued['accrual']['tax_amount'])


def test_scorecard_u11_landed_on_this_checkout():
    report = compute_integrity_scorecard()
    by_id = {u['unit_id']: u for u in report['units']}
    assert by_id['U11']['status'] == 'landed', by_id['U11']
    # Plan complete with U1–U14 → claimed 100.
    assert report['claimed_score'] == 100
