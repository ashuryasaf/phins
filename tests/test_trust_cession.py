"""U10 — trust ledger + RI cession cash book (KTD5)."""

from __future__ import annotations

import pytest

from services.erp.integrity_scorecard import compute_integrity_scorecard
from services.jobs import trust_recon_job
from services.mga import bordereaux as brd
from services.mga import cession as ces
from services.mga import remittance as rem
from services.mga import trust as trust_mod


@pytest.fixture(autouse=True)
def _reset():
    brd.reset_bordereaux_state()
    rem.reset_remittance_state()
    trust_mod.reset_trust_state()
    ces.reset_cession_state()
    yield
    trust_mod.reset_trust_state()
    ces.reset_cession_state()
    rem.reset_remittance_state()
    brd.reset_bordereaux_state()


def _green_books():
    return {
        'unified': {'integrity': {'ok': True, 'failed': []}},
        'reconcile': {'discrepancies': []},
    }


def _fixture():
    policies = {
        'POL-T1': {
            'id': 'POL-T1',
            'binder_id': brd.DEFAULT_BINDER_ID,
            'customer_id': 'CUST-T',
            'annual_premium': 1000.0,
        },
    }
    ledger = [{
        'id': 'TX-T1',
        'type': 'premium_payment',
        'amount': 100.0,
        'timestamp': '2026-11-10T12:00:00Z',
        'customer_id': 'CUST-T',
        'metadata': {'policy_id': 'POL-T1'},
    }]
    return policies, ledger, '2026-11', brd.DEFAULT_BINDER_ID


def test_trust_hold_and_release_on_remittance(monkeypatch):
    monkeypatch.setenv('PHINS_MONEY_GATE', '1')
    monkeypatch.setenv('PHINS_BOOKS_TIED_REQUIRE', '0')
    policies, ledger, period_id, binder_id = _fixture()
    built = rem.build_and_create(
        binder_id=binder_id,
        period_id=period_id,
        policies=policies,
        ledger_transactions=ledger,
    )
    tb = trust_mod.trust_balance(binder_id=binder_id)
    assert tb['premium_held'] == pytest.approx(built['run']['amount'])
    assert tb['balance'] == pytest.approx(built['run']['amount'])

    rem.settle_remittance_run(
        built['run']['id'],
        actor='accountant',
        role='accountant',
        books=_green_books(),
    )
    tb2 = trust_mod.trust_balance(binder_id=binder_id)
    assert tb2['remittance_released'] == pytest.approx(built['run']['amount'])
    assert abs(tb2['balance']) < 0.005


def test_trust_recon_flags_deficit_never_fills():
    trust_mod.record_movement(
        binder_id=brd.DEFAULT_BINDER_ID,
        period_id='2026-11',
        kind=trust_mod.KIND_PREMIUM_HELD,
        amount=100.0,
        signed=+1,
        ref_id='manual',
    )
    report = trust_mod.reconcile_trust(
        binder_id=brd.DEFAULT_BINDER_ID,
        bank_balance=40.0,
    )
    assert report['ok'] is False
    codes = [f['code'] for f in report['findings']]
    assert 'trust_deficit' in codes
    deficit_finding = next(f for f in report['findings'] if f['code'] == 'trust_deficit')
    assert deficit_finding['auto_fill'] is False
    # No balancing movement invented.
    assert len(trust_mod.list_movements(binder_id=brd.DEFAULT_BINDER_ID)) == 1
    assert report['auto_fill_forbidden'] is True


def test_trust_recon_job_run_once():
    trust_mod.record_movement(
        binder_id=brd.DEFAULT_BINDER_ID,
        period_id='2026-11',
        kind=trust_mod.KIND_PREMIUM_HELD,
        amount=50.0,
        signed=+1,
        ref_id='job',
    )
    report = trust_recon_job.run_once(
        binder_id=brd.DEFAULT_BINDER_ID,
        bank_balance=50.0,
    )
    assert report['ok'] is True
    assert report['trial_balance']['ok'] is True


def test_cession_cash_diverges_from_expense_weights(monkeypatch):
    monkeypatch.setenv('PHINS_MONEY_GATE', '1')
    monkeypatch.setenv('PHINS_BOOKS_TIED_REQUIRE', '0')
    policies, ledger, period_id, binder_id = _fixture()
    ces.register_treaty(quota_share=0.25, ceding_commission=0.10)
    built = rem.build_and_create(
        binder_id=binder_id,
        period_id=period_id,
        policies=policies,
        ledger_transactions=ledger,
    )
    rem.settle_remittance_run(
        built['run']['id'],
        actor='accountant',
        role='accountant',
        books=_green_books(),
    )
    totals = ces.cession_totals(binder_id=binder_id, period_id=period_id)
    assert totals['ceded_premium'] == pytest.approx(built['run']['amount'] * 0.25)
    # Analytical weights on a large expense loading must not equal cash cession.
    div = ces.analytical_divergence_report(
        expense_loading=1000.0,
        binder_id=binder_id,
        period_id=period_id,
    )
    assert div['labelled_non_cash'] is True
    assert div['analytical_source'] == '_EXPENSE_WEIGHTS'
    # 18% of 1000 = 180 analytical RI; cash cession is 25% of ~100.
    assert div['cash_equals_analytical'] is False
    assert div['divergence_abs'] > 0


def test_scorecard_u10_landed_on_this_checkout():
    report = compute_integrity_scorecard()
    by_id = {u['unit_id']: u for u in report['units']}
    assert by_id['U10']['status'] == 'landed', by_id['U10']
