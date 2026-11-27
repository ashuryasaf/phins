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
    # Drop the cached engine so a prior test's SQLITE_PATH is not reused.
    from database import reset_connection
    reset_connection()
    init_database(drop_existing=True)
    yield
    reset_connection()


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
    # Content-addressed on bill (and optional ledger_tx), not process-local
    # ALLOC-{n} — Agentic Security Review on U5.
    assert 'ae:ACC-J-DUAL:premium:BILL-J1:risk:debit' in keys
    assert 'ae:ACC-J-DUAL:premium:BILL-J1:savings:debit' in keys
    assert 'ae:ACC-J-DUAL:allocation:BILL-J1' in keys
    assert alloc.allocation_id.startswith('ALLOC-')
    assert len(alloc.allocation_id) > len('ALLOC-000001')

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
            idempotency_key='ae:ACC-J-DB:premium:B1:risk:debit',
        )
    assert eng.ledger_entries == []


def test_dual_mode_refuses_memory_on_idempotency_clash(monkeypatch):
    """Integrity clash must fail closed even when journal is dual (not db)."""
    monkeypatch.setenv('PHINS_ACCOUNTING_JOURNAL_MODE', 'dual')

    def _clash(**_kwargs):
        return {
            'ok': False,
            'id': None,
            'checksum': '',
            'reused': False,
            'withheld': True,
            'reason': 'idempotency_payload_mismatch',
            'mode': 'dual',
        }

    import services.erp.accounting_journal as aj

    monkeypatch.setattr(aj, 'append_journal_entry', _clash)
    monkeypatch.setattr(aj, 'journal_enabled', lambda environ=None: True)
    monkeypatch.setattr(aj, 'journal_required', lambda environ=None: False)

    eng = AccountingEngine('ACC-J-DUAL-CLASH', 'Clash Co')
    with pytest.raises(RuntimeError, match='idempotency_payload_mismatch'):
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
            idempotency_key='ae:ACC-J-DUAL-CLASH:premium:B1:risk:debit',
        )
    assert eng.ledger_entries == []


def test_dual_mode_still_allows_memory_on_journal_unavailable(monkeypatch):
    """Transient journal_unavailable in dual keeps the memory post."""
    monkeypatch.setenv('PHINS_ACCOUNTING_JOURNAL_MODE', 'dual')

    def _unavailable(**_kwargs):
        return {
            'ok': False,
            'id': None,
            'checksum': '',
            'reused': False,
            'withheld': True,
            'reason': 'journal_unavailable',
            'mode': 'dual',
        }

    import services.erp.accounting_journal as aj

    monkeypatch.setattr(aj, 'append_journal_entry', _unavailable)
    monkeypatch.setattr(aj, 'journal_enabled', lambda environ=None: True)
    monkeypatch.setattr(aj, 'journal_required', lambda environ=None: False)

    eng = AccountingEngine('ACC-J-DUAL-UNAV', 'Unav Co')
    entry = eng._create_ledger_entry(
        allocation_id='A1',
        policy_id='P1',
        customer_id='C1',
        entry_date=date.today(),
        entry_type=EntryType.RISK_PAYMENT,
        account_type=AccountType.RISK_FUND,
        debit_amount=Decimal('10.00'),
        description='x',
        reference_no='B1',
        idempotency_key='ae:ACC-J-DUAL-UNAV:premium:B1:risk:debit',
    )
    assert entry is not None
    assert len(eng.ledger_entries) == 1


def test_allocation_ids_are_content_addressed_not_sequential():
    """Allocation ids hash cash subject — never ALLOC-{n} or random UUID."""
    a = AccountingEngine('ACC-A', 'A')
    b = AccountingEngine('ACC-B', 'B')
    ids = set()
    for eng in (a, b):
        for i in range(5):
            alloc = eng.create_allocation(
                bill_id=f'B-{eng.engine_id}-{i}',
                policy_id='P1',
                customer_id='C1',
                total_premium=Decimal('10.00'),
                risk_percentage=Decimal('100'),
            )
            assert alloc.allocation_id not in ids
            ids.add(alloc.allocation_id)
            assert alloc.allocation_id != f'ALLOC-{len(ids):06d}'
    # Same engine + bill (+ notes) → same id (peer-safe).
    again = a.create_allocation(
        bill_id='B-ACC-A-0',
        policy_id='P1',
        customer_id='C1',
        total_premium=Decimal('10.00'),
        risk_percentage=Decimal('100'),
    )
    first = next(
        x for x in a.allocations.values()
        if x.bill_id == 'B-ACC-A-0'
    )
    assert again.allocation_id == first.allocation_id


def test_premium_keys_include_ledger_tx_when_present(sqlite_journal):
    eng = AccountingEngine('ACC-J-TX', 'Tx Co')
    alloc = eng.create_allocation(
        bill_id='BILL-TX1',
        policy_id='POL-TX1',
        customer_id='CUST-TX1',
        total_premium=Decimal('80.00'),
        risk_percentage=Decimal('100'),
        allocation_notes='ledger_tx=TX-99',
    )
    ok, msg = eng.post_allocation(alloc.allocation_id, 'accountant')
    assert ok is True, msg
    keys = {r.get('idempotency_key') for r in journal.load_journal_entries(engine_id='ACC-J-TX')}
    assert 'ae:ACC-J-TX:premium:BILL-TX1:TX-99:risk:debit' in keys
    assert 'ae:ACC-J-TX:allocation:BILL-TX1:TX-99' in keys


def test_post_allocation_rolls_back_posted_on_journal_refuse(monkeypatch):
    """POSTED must not stick when a journal integrity clash aborts the post."""
    from accounting_engine import AllocationStatus

    monkeypatch.setenv('PHINS_ACCOUNTING_JOURNAL_MODE', 'dual')
    calls = {'n': 0}

    def _clash(**_kwargs):
        calls['n'] += 1
        if calls['n'] == 1:
            # First ledger line seals; second clashes.
            return {
                'ok': True, 'id': 'JE-1', 'checksum': 'abc',
                'reused': False, 'withheld': False, 'mode': 'dual',
            }
        return {
            'ok': False, 'id': None, 'checksum': '',
            'reused': False, 'withheld': True,
            'reason': 'idempotency_payload_mismatch', 'mode': 'dual',
        }

    import services.erp.accounting_journal as aj

    monkeypatch.setattr(aj, 'append_journal_entry', _clash)
    monkeypatch.setattr(aj, 'journal_enabled', lambda environ=None: True)
    monkeypatch.setattr(aj, 'journal_required', lambda environ=None: False)

    eng = AccountingEngine('ACC-J-ROLLBACK', 'Rollback Co')
    alloc = eng.create_allocation(
        bill_id='BILL-RB', policy_id='P1', customer_id='C1',
        total_premium=Decimal('50.00'), risk_percentage=Decimal('100'),
    )
    ok, msg = eng.post_allocation(alloc.allocation_id, 'accountant')
    assert ok is False
    assert 'idempotency_payload_mismatch' in msg
    assert alloc.status == AllocationStatus.DRAFT
    assert alloc.posted_date is None
    assert eng.ledger_entries == []


def test_reverse_then_repost_uses_next_generation_keys(sqlite_journal):
    """After reverse, debit keys move to :g1 so resplit can rebook the cash."""
    from accounting_engine import AllocationStatus

    eng = AccountingEngine('ACC-J-REV', 'Rev Co')
    first = eng.create_allocation(
        bill_id='BILL-REV', policy_id='POL-REV', customer_id='CUST-REV',
        total_premium=Decimal('100.00'), risk_percentage=Decimal('100'),
        allocation_notes='ledger_tx=TX-REV',
    )
    assert eng.post_allocation(first.allocation_id, 'accountant')[0] is True
    assert eng.reverse_allocation(first.allocation_id, 'accountant', 'resplit')[0] is True
    assert first.status == AllocationStatus.REVERSED

    second = eng.create_allocation(
        bill_id='BILL-REV', policy_id='POL-REV', customer_id='CUST-REV',
        total_premium=Decimal('100.00'), risk_percentage=Decimal('60'),
        savings_percentage=Decimal('40'),
        allocation_notes='ledger_tx=TX-REV; resplit',
        risk_amount=Decimal('60.00'),
        savings_amount=Decimal('40.00'),
    )
    assert second.allocation_id != first.allocation_id
    ok, msg = eng.post_allocation(second.allocation_id, 'accountant')
    assert ok is True, msg
    assert second.status == AllocationStatus.POSTED

    keys = {r.get('idempotency_key') for r in journal.load_journal_entries(engine_id='ACC-J-REV')}
    assert 'ae:ACC-J-REV:premium:BILL-REV:TX-REV:risk:debit' in keys
    assert 'ae:ACC-J-REV:premium:BILL-REV:TX-REV:risk:credit:rev' in keys
    assert 'ae:ACC-J-REV:premium:BILL-REV:TX-REV:risk:debit:g1' in keys
    assert 'ae:ACC-J-REV:allocation:BILL-REV:TX-REV:g1' in keys
    assert eng._get_account_balance(AccountType.RISK_FUND) == Decimal('60.00')
    assert eng._get_account_balance(AccountType.SAVINGS_FUND) == Decimal('40.00')


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


def test_peer_process_smoke_shares_journal(sqlite_journal, tmp_path):
    """Plan U5 verify: process A posts; process B boots from the same SQLite journal."""
    import json
    import os
    import subprocess
    import sys

    from database import reset_connection

    eng = AccountingEngine('ACC-J-PEER', 'Peer Co')
    alloc = eng.create_allocation(
        bill_id='BILL-PEER', policy_id='POL-PEER', customer_id='CUST-PEER',
        total_premium=Decimal('100.00'), risk_percentage=Decimal('100'),
    )
    assert eng.post_allocation(alloc.allocation_id, 'accountant')[0] is True
    assert eng._get_account_balance(AccountType.RISK_FUND) == Decimal('100.00')
    reset_connection()

    sqlite_path = os.environ.get('SQLITE_PATH') or str(tmp_path / 'accounting-u5.sqlite')
    # Do not call init_database in the child: under PHINS_TEST_MODE + a
    # tempfile SQLITE_PATH it auto-drops tables and would wipe the journal.
    child = (
        'import json, os\n'
        f'os.environ["USE_DATABASE"] = "true"\n'
        f'os.environ["USE_SQLITE"] = "true"\n'
        f'os.environ["SQLITE_PATH"] = {sqlite_path!r}\n'
        'os.environ["PHINS_ACCOUNTING_JOURNAL_MODE"] = "dual"\n'
        'os.environ["PHINS_TEST_MODE"] = "true"\n'
        'from database import reset_connection\n'
        'reset_connection()\n'
        'from accounting_engine import AccountType, AccountingEngine\n'
        'from services.erp.accounting_journal import hydrate_accounting_engine_from_journal\n'
        'peer = AccountingEngine("ACC-J-PEER", "Peer Co")\n'
        'hydrated = hydrate_accounting_engine_from_journal(peer)\n'
        'risk = float(peer._get_account_balance(AccountType.RISK_FUND))\n'
        'print(json.dumps({"loaded": hydrated.get("loaded"), "risk": risk, '
        '"entries": len(peer.ledger_entries)}))\n'
    )
    env = os.environ.copy()
    env.update({
        'USE_DATABASE': 'true',
        'USE_SQLITE': 'true',
        'SQLITE_PATH': sqlite_path,
        'PHINS_ACCOUNTING_JOURNAL_MODE': 'dual',
        'PHINS_TEST_MODE': 'true',
        'PYTHONPATH': '/agent/repos/phins',
    })
    proc = subprocess.run(
        [sys.executable, '-c', child],
        cwd='/agent/repos/phins',
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip().startswith('{')]
    assert lines, proc.stdout
    report = json.loads(lines[-1])
    assert report['loaded'] >= 1
    assert report['risk'] == 100.0
    assert report['entries'] >= 1


def test_reconstruct_after_journal_hydrate_stays_idempotent(sqlite_journal, monkeypatch):
    """After journal hydrate, ledger reconstruct must not double-post the same cash."""
    from accounting_engine import get_accounting_engine, reset_accounting_engine
    from services.financial_unification_service import (
        accounting_book_totals,
        post_premium_to_accounting_book,
        reconstruct_accounting_book_from_ledger,
    )

    reset_accounting_engine()
    monkeypatch.setenv('PHINS_ACCOUNTING_JOURNAL_MODE', 'dual')

    posted = post_premium_to_accounting_book(
        bill_id='BILL-REC-1',
        policy_id='POL-REC-1',
        customer_id='CUST-REC-1',
        amount=50.0,
        risk_percentage=100,
        savings_percentage=0,
        risk_amount=50.0,
        savings_amount=0.0,
        source_tx_id='TX-REC-1',
        posted_by='test',
    )
    assert posted.get('posted') is True

    # Peer boot: empty shared engine ← journal (entries + allocation headers).
    reset_accounting_engine()
    peer = get_accounting_engine()
    hydrated = journal.hydrate_accounting_engine_from_journal(peer)
    assert hydrated['loaded'] >= 1
    assert int(hydrated.get('allocations_loaded') or 0) >= 1

    policies = {
        'POL-REC-1': {
            'id': 'POL-REC-1',
            'customer_id': 'CUST-REC-1',
            'annual_premium': 50.0,
            'risk_premium_annual': 50.0,
            'savings_premium_annual': 0.0,
            'pricing_source': 'pricing_kernel',
        }
    }
    txs = {
        'TX-REC-1': {
            'id': 'TX-REC-1',
            'type': 'premium_payment',
            'amount': 50.0,
            'customer_id': 'CUST-REC-1',
            'metadata': {'bill_id': 'BILL-REC-1', 'policy_id': 'POL-REC-1'},
        }
    }
    first = reconstruct_accounting_book_from_ledger(
        policies=policies, claims={}, billing={}, transactions=txs, actor='boot',
    )
    second = reconstruct_accounting_book_from_ledger(
        policies=policies, claims={}, billing={}, transactions=txs, actor='boot',
    )
    # Journal already carried the post — reconstruct must not invent a second.
    assert int(first.get('posted_count') or 0) == 0
    assert int(second.get('posted_count') or 0) == 0
    assert accounting_book_totals()['premium_posted'] == 50.0
