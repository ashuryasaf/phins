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


class _FakeLedger:
    """Mirrors PlatformEventLedgerService.append_event flatten behaviour."""

    def __init__(self, *, fail: bool = False):
        self.fail = fail
        self.events = []
        self.transaction_ledger = {}

    def append_event(self, **kwargs):
        if self.fail:
            raise RuntimeError('ledger_down')
        entry_id = str(kwargs.get('entry_id') or f"evt-{len(self.events)}")
        payload = kwargs.pop('payload', None) or {}
        row = dict(payload) if isinstance(payload, dict) else {}
        row.update(kwargs)
        row['entry_id'] = entry_id
        row['type'] = kwargs.get('event_type') or row.get('type')
        row['event_type'] = kwargs.get('event_type') or row.get('event_type')
        self.events.append(row)
        self.transaction_ledger[entry_id] = row
        return row


def test_reopen_soft_mirrors_ledger_event(monkeypatch):
    ledger = _FakeLedger()
    monkeypatch.setattr(pc, '_resolve_platform_ledger', lambda: ledger)
    soft = pc.soft_close('2026-02', actor='acct')
    assert soft['ok'] is True
    assert any(e['event_type'] == pc.EVENT_SOFT for e in ledger.events)

    reopen = pc.reopen_soft('2026-02', actor='acct')
    assert reopen['ok'] is True
    assert reopen['period']['status'] == pc.STATUS_OPEN
    assert reopen['pack']['checksum']
    reopen_events = [e for e in ledger.events if e['event_type'] == pc.EVENT_REOPEN]
    assert len(reopen_events) == 1
    assert reopen_events[0]['entity_id'] == '2026-02'
    # FakeLedger flattens payload onto the row (like PlatformEventLedgerService).
    assert reopen_events[0]['prior_pack_checksum'] == soft['pack']['checksum']


def test_soft_close_fails_closed_when_ledger_append_fails(monkeypatch):
    ledger = _FakeLedger(fail=True)
    monkeypatch.setattr(pc, '_resolve_platform_ledger', lambda: ledger)
    result = pc.soft_close('2026-04', actor='acct')
    assert result['ok'] is False
    assert result['reason'] == 'ledger_append_failed'
    period = pc.get_period('2026-04')
    assert period is None or period.get('status') == pc.STATUS_OPEN


def test_hard_close_restored_from_ledger_after_memory_clear(monkeypatch):
    ledger = _FakeLedger()
    monkeypatch.setattr(pc, '_resolve_platform_ledger', lambda: ledger)
    hard = pc.hard_close('2025-09', actor='acct')
    assert hard['ok'] is True
    pack_id = hard['pack']['id']
    pack_checksum = hard['pack']['checksum']
    assert pc.verify_close_pack(hard['pack'])['ok'] is True
    # Simulate restart: clear process memory; ledger still has flattened event.
    pc.reset_period_close_state()
    restored = pc.ensure_period(2025, 9)
    assert restored['status'] == pc.STATUS_HARD
    assert restored['pack_id'] == pack_id
    assert restored['pack_checksum'] == pack_checksum
    restored_pack = pc.get_close_pack('2025-09')
    assert restored_pack is not None
    assert pc.verify_close_pack(restored_pack)['ok'] is True
    assert restored_pack['checksum'] == pack_checksum
    assert restored_pack.get('chart_fingerprint') == hard['pack']['chart_fingerprint']
    with pytest.raises(pc.PeriodClosedError):
        pc.assert_period_open_for_post(date(2025, 9, 15))


def test_hard_close_restored_from_db_when_memory_empty(monkeypatch):
    """Peer worker: durable platform_ledger row restores HARD without memory."""

    class _Row:
        def to_dict(self):
            return {
                'id': 'PCP-2025-07-hard-abc',
                'event_type': pc.EVENT_HARD,
                'entity_id': '2025-07',
                'actor': 'peer',
                'timestamp': '2025-07-31T12:00:00Z',
                'payload': {
                    'period_id': '2025-07',
                    'pack_id': 'PCP-2025-07-hard-abc',
                    'checksum': 'deadbeef',
                    'action': 'hard',
                    'trial_balance': {'balanced': True},
                    'chart_fingerprint': coa.chart_fingerprint(),
                    'critical_checks_digest': 'x',
                    'actor': 'peer',
                    'sealed_at': '2025-07-31T12:00:00Z',
                },
            }

    class _Db:
        platform_ledger = type('PL', (), {
            'get_by_entity_event': staticmethod(lambda *_a, **_k: [_Row()]),
        })()

    class _Ledger:
        transaction_ledger = {}

        def _database_enabled(self):
            return True

        def _get_db_manager_factory(self):
            class _CM:
                def __enter__(self):
                    return _Db()

                def __exit__(self, *a):
                    return False

            return _CM

    monkeypatch.setattr(pc, '_resolve_platform_ledger', lambda: _Ledger())
    restored = pc.ensure_period(2025, 7)
    assert restored['status'] == pc.STATUS_HARD
    assert restored['hard_closed_by'] == 'peer'
    with pytest.raises(pc.PeriodClosedError):
        pc.assert_period_open_for_post(date(2025, 7, 10))


def test_reverse_allocation_refuses_hard_closed_today():
    eng = AccountingEngine('ACC-U8-REV', 'Reverse Gate Co')
    alloc = eng.create_allocation(
        bill_id='BILL-U8-REV', policy_id='POL-U8-REV', customer_id='CUST-U8-REV',
        total_premium=Decimal('50.00'), risk_percentage=Decimal('80'),
    )
    ok, _ = eng.post_allocation(alloc.allocation_id, 'accountant')
    assert ok is True
    today = date.today()
    hard = pc.hard_close(pc.period_id_for(today.year, today.month), actor='acct', engine=eng)
    assert hard['ok'] is True
    ok2, msg = eng.reverse_allocation(alloc.allocation_id, 'accountant', reason='should refuse')
    assert ok2 is False
    assert 'period_hard_closed' in msg


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
    # P3 complete on this tip (U1–U14) — claimed 100.
    assert report['claimed_score'] == 100
    assert float(report['progress_score']) >= 100.0


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
