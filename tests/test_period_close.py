"""U8 / AE4 — fiscal period open → soft → hard; refuse posts in hard-closed month."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from accounting_engine import (
    AccountType,
    AccountingEngine,
    EntryType,
    reset_accounting_engine,
)
from services.erp import coa, period_close as pc
from services.erp.integrity_scorecard import compute_integrity_scorecard
from services.jobs import period_close_job


@pytest.fixture(autouse=True)
def _reset():
    reset_accounting_engine()
    pc.reset_period_close_state()
    yield
    pc.reset_period_close_state()
    reset_accounting_engine()


def test_ensure_period_opens_month():
    period = pc.ensure_period(2026, 11)
    assert period['id'] == '2026-11'
    assert period['status'] == pc.STATUS_OPEN
    assert period['start_date'] == '2026-11-01'
    assert period['end_date'] == '2026-11-30'


def test_ae4_soft_then_hard_then_refuse_post():
    """Soft-close M → hard-close → premium post dated in M refused; M+1 succeeds."""
    eng = AccountingEngine('ACC-U8', 'Period Close Co')
    # Post into November while open.
    nov = date(2026, 11, 15)
    alloc = eng.create_allocation(
        bill_id='BILL-U8-1', policy_id='POL-U8', customer_id='CUST-U8',
        total_premium=Decimal('100.00'), risk_percentage=Decimal('70'),
    )
    # Force entry dates via _create_ledger_entry path using claim helper mid-month.
    ok, _ = eng.post_allocation(alloc.allocation_id, 'accountant')
    assert ok is True

    soft = pc.soft_close('2026-11', actor='accountant', engine=eng)
    assert soft['ok'] is True
    assert soft['period']['status'] == pc.STATUS_SOFT
    assert soft['pack']['checksum']
    assert pc.verify_close_pack(soft['pack'])['ok'] is True

    # Soft still allows posts.
    pc.assert_period_open_for_post(nov)

    hard = pc.hard_close('2026-11', actor='accountant', engine=eng)
    assert hard['ok'] is True
    assert hard['period']['status'] == pc.STATUS_HARD
    assert pc.verify_close_pack(hard['pack'])['ok'] is True

    with pytest.raises(pc.PeriodClosedError) as raised:
        pc.assert_period_open_for_post(nov)
    assert raised.value.period_id == '2026-11'
    assert raised.value.as_response()['error'] == 'period_hard_closed'

    # Post allocation uses today — freeze by hard-closing today's month too
    # when tests run in Nov 2026; otherwise post for a dedicated closed day
    # through _create_ledger_entry.
    with pytest.raises(pc.PeriodClosedError):
        eng._create_ledger_entry(
            allocation_id=alloc.allocation_id,
            policy_id='POL-U8',
            customer_id='CUST-U8',
            entry_date=nov,
            entry_type=EntryType.RISK_PAYMENT,
            account_type=AccountType.RISK_FUND,
            debit_amount=Decimal('1.00'),
            description='should refuse',
            reference_no='BILL-U8-refuse',
        )

    # Open December succeeds.
    dec = date(2026, 12, 1)
    pc.assert_period_open_for_post(dec)
    entry = eng._create_ledger_entry(
        allocation_id=alloc.allocation_id,
        policy_id='POL-U8',
        customer_id='CUST-U8',
        entry_date=dec,
        entry_type=EntryType.RISK_PAYMENT,
        account_type=AccountType.RISK_FUND,
        debit_amount=Decimal('1.00'),
        description='open month ok',
        reference_no='BILL-U8-dec',
    )
    assert entry.entry_date == dec


def test_hard_close_idempotent_and_immutable():
    pc.ensure_period(2025, 1)
    first = pc.hard_close('2025-01', actor='a')
    second = pc.hard_close('2025-01', actor='b')
    assert first['ok'] and second.get('already_hard_closed') is True
    assert second['pack']['checksum'] == first['pack']['checksum']
    reopen = pc.reopen_soft('2025-01', actor='a')
    assert reopen['ok'] is False
    assert reopen['reason'] == 'hard_closed_immutable'


def test_tampered_pack_fails_verify():
    result = pc.soft_close('2024-06', actor='acct')
    pack = dict(result['pack'])
    pack['checksum'] = '0' * 64
    assert pc.verify_close_pack(pack)['ok'] is False


def test_trial_balance_includes_coa_fingerprint():
    tb = pc.trial_balance('2026-03')
    assert tb['chart_fingerprint'] == coa.chart_fingerprint()
    assert len(tb['lines']) == 4
    assert tb['balanced'] is True


def test_period_close_job_soft():
    result = period_close_job.run_once(period_id='2026-08', action='soft', actor='job')
    assert result['ok'] is True
    assert result['period']['status'] == pc.STATUS_SOFT


def test_scorecard_u8_landed_on_this_checkout():
    report = compute_integrity_scorecard()
    by_id = {u['unit_id']: u for u in report['units']}
    assert by_id['U8']['status'] == 'landed', by_id['U8']
    # P2 still incomplete without U9–U11 — claimed stays 82.
    assert report['claimed_score'] == 82
    assert float(report['progress_score']) > 82.0


def test_scorecard_u8_requires_both_files(tmp_path: Path):
    erp = tmp_path / 'services' / 'erp'
    erp.mkdir(parents=True)
    (erp / 'coa.py').write_text('# stub\n', encoding='utf-8')
    report = compute_integrity_scorecard(repo_root=str(tmp_path))
    by_id = {u['unit_id']: u for u in report['units']}
    assert by_id['U8']['status'] == 'missing'
    (erp / 'period_close.py').write_text('# stub\n', encoding='utf-8')
    report2 = compute_integrity_scorecard(repo_root=str(tmp_path))
    by_id2 = {u['unit_id']: u for u in report2['units']}
    assert by_id2['U8']['status'] == 'landed'
