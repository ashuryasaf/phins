"""U9 / AE5 — sealed bordereaux + remittance settle via Money Gate."""

from __future__ import annotations

import pytest

from services.erp.integrity_scorecard import compute_integrity_scorecard
from services.jobs import bordereaux_job
from services.mga import bordereaux as brd
from services.mga import remittance as rem


@pytest.fixture(autouse=True)
def _reset():
    brd.reset_bordereaux_state()
    rem.reset_remittance_state()
    yield
    brd.reset_bordereaux_state()
    rem.reset_remittance_state()


def _green_books():
    return {
        'unified': {'integrity': {'ok': True, 'failed': []}},
        'reconcile': {'discrepancies': []},
    }


def _red_books():
    return {
        'unified': {
            'integrity': {
                'ok': False,
                'failed': ['claims_counted_once'],
            }
        },
        'reconcile': {'discrepancies': []},
    }


def _fixture_binder(*, binder_id: str = brd.DEFAULT_BINDER_ID, period_id: str = '2026-11'):
    """Two policies on binder B with $100 + $50 premium cash in period M."""
    policies = {
        'POL-U9-A': {
            'id': 'POL-U9-A',
            'binder_id': binder_id,
            'customer_id': 'CUST-U9',
            'kernel_pin': {
                'risk_premium_annual': 700.0,
                'savings_premium_annual': 200.0,
                'underwriting_fee_annual': 100.0,
                'annual_premium': 1000.0,
            },
            'annual_premium': 1000.0,
            'risk_premium_annual': 700.0,
            'savings_premium_annual': 200.0,
            'underwriting_fee_annual': 100.0,
        },
        'POL-U9-B': {
            'id': 'POL-U9-B',
            'binder_id': binder_id,
            'customer_id': 'CUST-U9',
            'annual_premium': 500.0,
            # No pin → whole premium is risk (writer rule).
        },
        'POL-OTHER': {
            'id': 'POL-OTHER',
            'binder_id': 'OTHER-BINDER',
            'customer_id': 'CUST-X',
            'annual_premium': 999.0,
        },
    }
    ledger = [
        {
            'id': 'TX-U9-1',
            'type': 'premium_payment',
            'amount': 100.0,
            'timestamp': '2026-11-10T12:00:00Z',
            'customer_id': 'CUST-U9',
            'metadata': {'policy_id': 'POL-U9-A'},
        },
        {
            'id': 'TX-U9-2',
            'type': 'bill_payment',
            'amount': 50.0,
            'timestamp': '2026-11-20T09:00:00Z',
            'customer_id': 'CUST-U9',
            'metadata': {'policy_id': 'POL-U9-B'},
        },
        {
            'id': 'TX-OTHER',
            'type': 'premium_payment',
            'amount': 999.0,
            'timestamp': '2026-11-15T00:00:00Z',
            'customer_id': 'CUST-X',
            'metadata': {'policy_id': 'POL-OTHER'},
        },
        {
            'id': 'TX-OUT',
            'type': 'premium_payment',
            'amount': 40.0,
            'timestamp': '2026-10-31T23:00:00Z',
            'customer_id': 'CUST-U9',
            'metadata': {'policy_id': 'POL-U9-A'},
        },
    ]
    claims = {
        'CLM-U9-1': {
            'id': 'CLM-U9-1',
            'policy_id': 'POL-U9-A',
            'status': 'paid',
            'amount_paid': 25.0,
            'paid_at': '2026-11-18',
        },
    }
    return policies, ledger, claims, period_id, binder_id


def test_ae5_bordereau_ties_premium_cash_to_the_cent():
    policies, ledger, claims, period_id, binder_id = _fixture_binder()
    pack = brd.build_bordereau(
        binder_id=binder_id,
        period_id=period_id,
        policies=policies,
        ledger_transactions=ledger,
        claims=claims,
        actor='test',
    )
    assert pack['ae5_ok'] is True
    assert pack['premium_cash'] == 150.0
    assert pack['claims_paid'] == 25.0
    premium_lines = [r for r in pack['lines'] if r.get('kind') == 'premium']
    assert abs(sum(r['amount'] for r in premium_lines) - pack['premium_cash']) < 0.005
    check = brd.verify_bordereau(pack)
    assert check['ok'] is True
    # Carrier payable is risk cash only (KTD5 — never expense weights).
    assert pack['carrier_payable'] == pytest.approx(pack['streams']['risk'])
    assert 'POL-OTHER' not in pack['policy_ids']
    assert set(pack['policy_ids']) == {'POL-U9-A', 'POL-U9-B'}


def test_tampered_bordereau_fails_verify():
    policies, ledger, claims, period_id, binder_id = _fixture_binder()
    pack = brd.build_bordereau(
        binder_id=binder_id,
        period_id=period_id,
        policies=policies,
        ledger_transactions=ledger,
        claims=claims,
    )
    bad = dict(pack)
    bad['premium_cash'] = float(pack['premium_cash']) + 1.0
    assert brd.verify_bordereau(bad)['ok'] is False
    bad2 = dict(pack)
    bad2['bordereau_sha256'] = '0' * 64
    assert brd.verify_bordereau(bad2)['ok'] is False


def test_create_and_settle_remittance_green(monkeypatch):
    monkeypatch.setenv('PHINS_MONEY_GATE', '1')
    monkeypatch.setenv('PHINS_BOOKS_TIED_REQUIRE', '0')
    policies, ledger, claims, period_id, binder_id = _fixture_binder()
    built = rem.build_and_create(
        binder_id=binder_id,
        period_id=period_id,
        policies=policies,
        ledger_transactions=ledger,
        claims=claims,
        actor='accountant',
    )
    assert built['ok'] is True
    run = built['run']
    assert run['status'] == rem.STATUS_PAYABLE
    assert run['amount'] == pytest.approx(built['bordereau']['carrier_payable'])

    settled = rem.settle_remittance_run(
        run['id'],
        actor='accountant',
        role='accountant',
        books=_green_books(),
    )
    assert settled['ok'] is True
    assert settled['run']['status'] == rem.STATUS_SETTLED
    again = rem.settle_remittance_run(
        run['id'],
        actor='accountant',
        role='accountant',
        books=_green_books(),
    )
    assert again.get('already_settled') is True


def test_settle_refuses_when_books_red(monkeypatch):
    monkeypatch.setenv('PHINS_MONEY_GATE', '1')
    monkeypatch.setenv('PHINS_BOOKS_TIED_REQUIRE', '0')
    policies, ledger, claims, period_id, binder_id = _fixture_binder()
    built = rem.build_and_create(
        binder_id=binder_id,
        period_id=period_id,
        policies=policies,
        ledger_transactions=ledger,
        claims=claims,
    )
    with pytest.raises(rem.RemittanceError) as raised:
        rem.settle_remittance_run(
            built['run']['id'],
            actor='accountant',
            role='accountant',
            books=_red_books(),
        )
    assert raised.value.message == 'money_gate_refused'
    body = raised.value.as_response()
    assert 'claims_counted_once' in body.get('failed_checks', [])
    # Run stays payable.
    assert rem.get_remittance_run(built['run']['id'])['status'] == rem.STATUS_PAYABLE


def test_create_refuses_tampered_bordereau():
    policies, ledger, claims, period_id, binder_id = _fixture_binder()
    pack = brd.build_bordereau(
        binder_id=binder_id,
        period_id=period_id,
        policies=policies,
        ledger_transactions=ledger,
        claims=claims,
    )
    pack['bordereau_sha256'] = 'deadbeef'
    with pytest.raises(rem.RemittanceError) as raised:
        rem.create_remittance_run(bordereau=pack)
    assert raised.value.message == 'bordereau_not_intact'


def test_bordereaux_job_run_once():
    policies, ledger, claims, period_id, binder_id = _fixture_binder()
    result = bordereaux_job.run_once(
        binder_id=binder_id,
        period_id=period_id,
        create_remittance=True,
        actor='job',
        policies=policies,
        ledger_transactions=ledger,
        claims=claims,
    )
    assert result['ok'] is True
    assert result['bordereau']['ae5_ok'] is True
    assert result['run']['status'] == rem.STATUS_PAYABLE


def test_expense_weights_never_drive_payable():
    """KTD5: carrier payable is kernel risk cash, not analytical weights."""
    policies, ledger, claims, period_id, binder_id = _fixture_binder()
    pack = brd.build_bordereau(
        binder_id=binder_id,
        period_id=period_id,
        policies=policies,
        ledger_transactions=ledger,
        claims=claims,
    )
    assert pack['carrier_payable'] == pytest.approx(pack['streams']['risk'])
    # A 30% "carrier share" analytical carve of premium must not equal payable.
    assert pack['carrier_payable'] != pytest.approx(pack['premium_cash'] * 0.30)
    assert pack['carrier_payable'] <= pack['premium_cash'] + 1e-9


def test_rebuild_does_not_duplicate_payable():
    """Same binder/period rebuild keeps one remittance run (Bugbot high)."""
    policies, ledger, claims, period_id, binder_id = _fixture_binder()
    first = rem.build_and_create(
        binder_id=binder_id,
        period_id=period_id,
        policies=policies,
        ledger_transactions=ledger,
        claims=claims,
        actor='a',
    )
    second = rem.build_and_create(
        binder_id=binder_id,
        period_id=period_id,
        policies=policies,
        ledger_transactions=ledger,
        claims=claims,
        actor='b',
    )
    assert first['run']['id'] == second['run']['id']
    assert second.get('already') is True or second['run']['id'] == first['run']['id']
    assert len(rem.list_remittance_runs(binder_id=binder_id, period_id=period_id)) == 1
    assert first['bordereau']['bordereau_sha256'] == second['bordereau']['bordereau_sha256']


def test_undated_claims_are_withheld_from_every_period():
    policies, ledger, _claims, _period, binder_id = _fixture_binder()
    undated = {
        'CLM-UNDATED': {
            'id': 'CLM-UNDATED',
            'policy_id': 'POL-U9-A',
            'status': 'paid',
            'amount_paid': 99.0,
            # no paid_at / closed_at / updated_at / created_at
        },
    }
    nov = brd.build_bordereau(
        binder_id=binder_id,
        period_id='2026-11',
        policies=policies,
        ledger_transactions=ledger,
        claims=undated,
    )
    dec = brd.build_bordereau(
        binder_id=binder_id,
        period_id='2026-12',
        policies=policies,
        ledger_transactions=[],
        claims=undated,
    )
    assert nov['claims_paid'] == 0.0
    assert dec['claims_paid'] == 0.0
    assert not any(r.get('claim_id') == 'CLM-UNDATED' for r in nov['lines'])
    assert not any(r.get('claim_id') == 'CLM-UNDATED' for r in dec['lines'])


def test_settled_run_blocks_second_payable():
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setenv('PHINS_MONEY_GATE', '1')
    monkeypatch.setenv('PHINS_BOOKS_TIED_REQUIRE', '0')
    try:
        policies, ledger, claims, period_id, binder_id = _fixture_binder()
        built = rem.build_and_create(
            binder_id=binder_id,
            period_id=period_id,
            policies=policies,
            ledger_transactions=ledger,
            claims=claims,
        )
        rem.settle_remittance_run(
            built['run']['id'],
            actor='accountant',
            role='accountant',
            books=_green_books(),
        )
        again = rem.build_and_create(
            binder_id=binder_id,
            period_id=period_id,
            policies=policies,
            ledger_transactions=ledger,
            claims=claims,
        )
        assert again.get('already_settled') is True or again['run']['status'] == rem.STATUS_SETTLED
        assert len(rem.list_remittance_runs(binder_id=binder_id, period_id=period_id)) == 1
    finally:
        monkeypatch.undo()


def test_rebuild_after_settle_keeps_remitted_cash(monkeypatch):
    """Post-settle rebuild must not replace the remitted AE5 seal (Bugbot high)."""
    monkeypatch.setenv('PHINS_MONEY_GATE', '1')
    monkeypatch.setenv('PHINS_BOOKS_TIED_REQUIRE', '0')
    policies, ledger, claims, period_id, binder_id = _fixture_binder()
    built = rem.build_and_create(
        binder_id=binder_id,
        period_id=period_id,
        policies=policies,
        ledger_transactions=ledger,
        claims=claims,
    )
    remitted = float(built['bordereau']['carrier_payable'])
    remitted_sha = built['bordereau']['bordereau_sha256']
    rem.settle_remittance_run(
        built['run']['id'],
        actor='accountant',
        role='accountant',
        books=_green_books(),
    )
    # Extra premium after settle.
    more_ledger = list(ledger) + [{
        'id': 'TX-U9-LATE',
        'type': 'premium_payment',
        'amount': 200.0,
        'timestamp': '2026-11-28T12:00:00Z',
        'customer_id': 'CUST-U9',
        'metadata': {'policy_id': 'POL-U9-B'},
    }]
    again = rem.build_and_create(
        binder_id=binder_id,
        period_id=period_id,
        policies=policies,
        ledger_transactions=more_ledger,
        claims=claims,
    )
    assert again.get('already_settled') is True
    assert again['run']['status'] == rem.STATUS_SETTLED
    assert float(again['run']['amount']) == remitted
    assert again['bordereau']['bordereau_sha256'] == remitted_sha
    assert float(again['bordereau']['carrier_payable']) == remitted
    board = brd.build_bordereau(
        binder_id=binder_id,
        period_id=period_id,
        policies=policies,
        ledger_transactions=more_ledger,
        claims=claims,
    )
    assert board['bordereau_sha256'] == remitted_sha
    assert float(board['carrier_payable']) == remitted


def test_payable_refresh_mirrors_ledger_event(monkeypatch):
    events = []

    class _Ledger:
        def append_event(self, **kwargs):
            events.append(kwargs)
            return {'ok': True}

    monkeypatch.setattr(rem, '_resolve_platform_ledger', lambda: _Ledger())
    policies, ledger, claims, period_id, binder_id = _fixture_binder()
    first = rem.build_and_create(
        binder_id=binder_id,
        period_id=period_id,
        policies=policies,
        ledger_transactions=ledger,
        claims=claims,
        actor='a',
    )
    richer = list(ledger) + [{
        'id': 'TX-U9-MORE',
        'type': 'premium_payment',
        'amount': 25.0,
        'timestamp': '2026-11-25T12:00:00Z',
        'customer_id': 'CUST-U9',
        'metadata': {'policy_id': 'POL-U9-A'},
    }]
    second = rem.build_and_create(
        binder_id=binder_id,
        period_id=period_id,
        policies=policies,
        ledger_transactions=richer,
        claims=claims,
        actor='b',
    )
    assert second.get('refreshed') is True
    assert second['run']['id'] == first['run']['id']
    assert float(second['run']['amount']) > float(first['run']['amount'])
    types = [e.get('event_type') for e in events]
    assert rem.EVENT_CREATED in types
    assert rem.EVENT_REFRESHED in types
    refreshed = [e for e in events if e.get('event_type') == rem.EVENT_REFRESHED]
    assert refreshed[0]['entry_id'].startswith(second['run']['id'] + ':refreshed:')


def test_scorecard_u9_landed_on_this_checkout():
    report = compute_integrity_scorecard()
    by_id = {u['unit_id']: u for u in report['units']}
    assert by_id['U9']['status'] == 'landed', by_id['U9']
    # P2 still incomplete without U10–U11 — claimed stays 82; progress rises.
    assert report['claimed_score'] == 82
    assert float(report['progress_score']) > 82.0
