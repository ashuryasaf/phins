"""U5 durable accounting journal — sealed idempotent GL posts."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from accounting_engine import (
    AccountType,
    AccountingEngine,
    EntryType,
    reset_accounting_engine,
)
from database import init_database
from services.erp import accounting_journal as journal


@pytest.fixture(autouse=True)
def _reset_engine():
    reset_accounting_engine()
    yield
    reset_accounting_engine()


@pytest.fixture
def sqlite_journal(monkeypatch, tmp_path):
    monkeypatch.setenv('USE_DATABASE', 'true')
    monkeypatch.setenv('USE_SQLITE', 'true')
    monkeypatch.setenv('SQLITE_PATH', str(tmp_path / 'accounting-u5.sqlite'))
    monkeypatch.setenv('PHINS_ACCOUNTING_JOURNAL_MODE', 'dual')
    monkeypatch.setenv('PHINS_TEST_MODE', 'true')
    init_database(drop_existing=True)
    yield


def test_mode_defaults_off_under_test_env(monkeypatch):
    monkeypatch.delenv('PHINS_ACCOUNTING_JOURNAL_MODE', raising=False)
    monkeypatch.setenv('USE_DATABASE', 'false')
    assert journal.accounting_journal_mode({'USE_DATABASE': 'false'}) == 'off'
    assert journal.accounting_journal_mode({'PHINS_ACCOUNTING_JOURNAL_MODE': 'db'}) == 'db'


def test_idempotency_key_stable():
    a = journal.make_idempotency_key(
        engine_id='PHI-AE-001', kind='claim', subject_id='CLM-1',
        account_type='Risk Fund', side='credit',
    )
    b = journal.make_idempotency_key(
        engine_id='PHI-AE-001', kind='claim', subject_id='CLM-1',
        account_type='Risk Fund', side='credit',
    )
    assert a == b
    assert a.startswith('ae:PHI-AE-001:claim:CLM-1:')


def test_post_allocation_still_works_with_journal_off(monkeypatch):
    monkeypatch.setenv('PHINS_ACCOUNTING_JOURNAL_MODE', 'off')
    eng = AccountingEngine('ACC-J-OFF', 'Test')
    alloc = eng.create_allocation(
        bill_id='B1', policy_id='P1', customer_id='C1',
        total_premium=Decimal('100.00'), risk_percentage=Decimal('60'),
    )
    ok, _msg = eng.post_allocation(alloc.allocation_id, 'tester')
    assert ok is True
    assert len(eng.ledger_entries) == 2


def test_append_and_hydrate_round_trip(sqlite_journal):
    """Dual-mode post seals rows; a fresh engine hydrates them back."""
    eng = AccountingEngine('ACC-J-DUAL', 'Dual Co')
    alloc = eng.create_allocation(
        bill_id='BILL-J1', policy_id='POL-J1', customer_id='CUST-J1',
        total_premium=Decimal('200.00'), risk_percentage=Decimal('70'),
    )
    ok, msg = eng.post_allocation(alloc.allocation_id, 'accountant')
    assert ok is True, msg
    assert len(eng.ledger_entries) == 2

    rows = journal.load_journal_entries(engine_id='ACC-J-DUAL')
    assert len(rows) >= 2
    keys = {r.get('idempotency_key') for r in rows}
    assert f'ae:ACC-J-DUAL:alloc:{alloc.allocation_id}:risk:debit' in keys
    assert f'ae:ACC-J-DUAL:alloc:{alloc.allocation_id}:savings:debit' in keys

    eng2 = AccountingEngine('ACC-J-DUAL', 'Dual Co')
    hydrated = journal.hydrate_accounting_engine_from_journal(eng2)
    assert hydrated['loaded'] >= 2
    assert len(eng2.ledger_entries) >= 2
    risk = sum(
        (e.debit_amount - e.credit_amount)
        for e in eng2.ledger_entries
        if e.account_type == AccountType.RISK_FUND
    )
    assert risk == Decimal('140.00')


def test_claim_payment_journal_idempotent(sqlite_journal):
    eng = AccountingEngine('ACC-J-CLM', 'Claim Co')
    ok1, _ = eng.post_claim_payment('CLM-J1', 'P1', 'C1', Decimal('25.00'))
    ok2, msg2 = eng.post_claim_payment('CLM-J1', 'P1', 'C1', Decimal('25.00'))
    assert ok1 is True and ok2 is True
    assert 'already recorded' in msg2
    claim_entries = [
        e for e in eng.ledger_entries
        if e.entry_type == EntryType.CLAIM_PAYMENT and e.reference_no == 'CLM-J1'
    ]
    assert len(claim_entries) == 1

    peer = AccountingEngine('ACC-J-CLM', 'Claim Co')
    journal.hydrate_accounting_engine_from_journal(peer)
    peer_claims = [
        e for e in peer.ledger_entries
        if e.entry_type == EntryType.CLAIM_PAYMENT and e.reference_no == 'CLM-J1'
    ]
    assert len(peer_claims) == 1


def test_db_mode_refuses_when_journal_unavailable(monkeypatch):
    monkeypatch.setenv('PHINS_ACCOUNTING_JOURNAL_MODE', 'db')

    def _boom(**_kwargs):
        return {
            'ok': False,
            'id': None,
            'checksum': '',
            'reused': False,
            'withheld': True,
            'reason': 'journal_unavailable',
            'mode': 'db',
        }

    import services.erp.accounting_journal as aj

    monkeypatch.setattr(aj, 'append_journal_entry', _boom)
    monkeypatch.setattr(aj, 'journal_enabled', lambda environ=None: True)
    monkeypatch.setattr(aj, 'journal_required', lambda environ=None: True)

    eng = AccountingEngine('ACC-J-DB', 'DB Co')
    with pytest.raises(RuntimeError, match='accounting journal refused'):
        eng._create_ledger_entry(
            allocation_id='A1',
            policy_id='P1',
            customer_id='C1',
            entry_date=date.today(),
            entry_type=EntryType.RISK_PAYMENT,
            account_type=AccountType.RISK_FUND,
            debit_amount=Decimal('10.00'),
            description='x',
            reference_no='B1',
            idempotency_key='ae:ACC-J-DB:alloc:A1:risk:debit',
        )
    assert eng.ledger_entries == []


def test_boot_hydrate_runs_before_ledger_reconstruct(monkeypatch):
    """hydrate_accounting_book_from_ledger must call journal hydrate first."""
    order = []

    class _Eng:
        engine_id = 'PHI-AE-001'
        ledger_entries = []
        entry_counter = 0

    monkeypatch.setattr(
        'accounting_engine.get_accounting_engine', lambda: _Eng(),
    )

    def _hydrate(engine):
        order.append('journal')
        return {'loaded': 1, 'skipped': 0, 'mode': 'dual'}

    def _reconstruct(**_kwargs):
        order.append('ledger')
        return {'posted_count': 0}

    monkeypatch.setattr(
        'services.erp.accounting_journal.hydrate_accounting_engine_from_journal',
        _hydrate,
    )
    monkeypatch.setattr(
        'services.financial_unification_service.reconstruct_accounting_book_from_ledger',
        _reconstruct,
    )

    from web_portal import server as portal

    result = portal.hydrate_accounting_book_from_ledger()
    assert order == ['journal', 'ledger']
    assert result.get('journal', {}).get('loaded') == 1
