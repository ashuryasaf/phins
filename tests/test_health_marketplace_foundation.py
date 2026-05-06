"""
Tests for the health-marketplace foundation (Phase 1+ of
docs/health_marketplace_architecture.md).

Covers:
- new ORM models load and persist via repositories
- DatabaseManager exposes the marketplace repository properties
- WalletLedgerService runs the hold -> capture / release / refund lifecycle
  and keeps cached balances aligned with the append-only ledger
- MarketplaceAccountingService produces deterministic financials and posts
  balanced journal entries
- SupplierSettlementService builds runs, computes the canonical payout
  formula, and exposes aging buckets
- MarketplaceEventService writes canonical outbox events
- PlatformIntegrityService.validate_marketplace_foundation surfaces wallet,
  settlement, markup, payer, and refund lineage findings

These tests are isolated per session: each one builds its own SQLite database
file under /tmp and resets the singleton cache so cross-test bleed is avoided.
"""

from __future__ import annotations

import os
import sys
import tempfile
import uuid
import pytest

# Ensure repo root is importable.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture
def isolated_db(monkeypatch):
    """Build a fresh sqlite DB and patch the marketplace services to use it."""
    db_path = os.path.join(tempfile.gettempdir(), f"phins_marketplace_{uuid.uuid4().hex}.db")
    monkeypatch.setenv('USE_SQLITE', '1')
    monkeypatch.setenv('SQLITE_PATH', db_path)
    monkeypatch.setenv('PHINS_TEST_MODE', 'true')

    # Reset global engine so the new SQLITE_PATH is honored.
    import database
    database.reset_connection()
    from database import init_database
    init_database(drop_existing=True)

    # Reset service singletons so they reuse the new DB.
    import services.wallet_ledger_service as wls
    import services.marketplace_accounting_service as mas
    import services.supplier_settlement_service as sss
    import services.marketplace_event_service as mes
    wls._wallet_ledger_service = None
    mas._marketplace_accounting_service = None
    sss._supplier_settlement_service = None
    mes._marketplace_event_service = None

    yield db_path

    try:
        os.remove(db_path)
    except OSError:
        pass
    database.reset_connection()


def test_marketplace_repositories_persist(isolated_db):
    from database.manager import DatabaseManager

    with DatabaseManager() as db:
        wallet = db.wallet_accounts.create(
            id='WAL-1', customer_id='CUST-1', wallet_type='health', currency='USD',
            available_balance=100.0, posted_balance=100.0,
        )
        assert wallet is not None and wallet.id == 'WAL-1'

        hold = db.wallet_holds.create(
            id='HOLD-1', wallet_account_id='WAL-1', customer_id='CUST-1',
            amount=20.0, status='held', idempotency_key='idem-1',
        )
        assert hold is not None
        assert db.wallet_holds.get_by_idempotency('idem-1') is not None

        ledger = db.wallet_ledger.create(
            id='LE-1', wallet_account_id='WAL-1', customer_id='CUST-1',
            entry_group_id='G-1', entry_type='deposit', direction='credit', amount=100.0,
        )
        assert ledger is not None
        assert abs(db.wallet_ledger.derive_balance('WAL-1') - 100.0) < 1e-6

        intent = db.payment_intents.create(
            id='PI-1', customer_id='CUST-1', total_amount=20.0,
            funding_strategy='wallet', idempotency_key='pi-idem',
        )
        assert intent is not None
        assert db.payment_intents.get_by_idempotency('pi-idem') is not None

        run = db.supplier_settlement_runs.create(
            id='SR-1', supplier_id='SUP-1', status='pending', gross_amount=0.0,
        )
        assert run is not None

        receivable = db.payer_receivables.create(
            id='PR-1', payer_id='PAY-1', expected_amount=50.0, open_amount=50.0,
        )
        assert receivable is not None
        assert any(r.id == 'PR-1' for r in db.payer_receivables.get_open())


def test_wallet_ledger_service_lifecycle(isolated_db):
    from services.wallet_ledger_service import get_wallet_ledger_service

    svc = get_wallet_ledger_service()

    deposit = svc.deposit('CUST-A', 250.0)
    assert deposit.success
    assert deposit.wallet['available_balance'] == 250.0
    assert deposit.wallet['posted_balance'] == 250.0

    hold_result = svc.create_hold('CUST-A', 80.0, order_id='ORD-1', idempotency_key='create-1')
    assert hold_result.success
    assert hold_result.wallet['available_balance'] == 170.0
    assert hold_result.wallet['held_balance'] == 80.0

    # Idempotent re-call must not double-debit.
    hold_again = svc.create_hold('CUST-A', 80.0, order_id='ORD-1', idempotency_key='create-1')
    assert hold_again.success
    assert hold_again.wallet['available_balance'] == 170.0

    capture = svc.capture_hold(hold_result.hold['id'])
    assert capture.success
    assert capture.wallet['held_balance'] == 0.0
    assert capture.wallet['available_balance'] == 170.0
    assert capture.wallet['posted_balance'] == 170.0

    # New hold and release flow.
    hold2 = svc.create_hold('CUST-A', 30.0, order_id='ORD-2', idempotency_key='create-2')
    assert hold2.success
    release = svc.release_hold(hold2.hold['id'], reason='customer_cancel')
    assert release.success
    assert release.wallet['held_balance'] == 0.0
    assert release.wallet['available_balance'] == 170.0

    # Refund credits wallet back.
    refund = svc.refund('CUST-A', 25.0, order_id='ORD-1')
    assert refund.success
    assert refund.wallet['available_balance'] == 195.0

    # Recompute reconciles cache to ledger.
    recomputed = svc.recompute_balances('CUST-A')
    assert recomputed['posted_balance'] == 195.0
    assert recomputed['available_balance'] == 195.0
    assert recomputed['held_balance'] == 0.0


def test_marketplace_accounting_balanced_postings(isolated_db):
    from services.marketplace_accounting_service import get_marketplace_accounting_service

    svc = get_marketplace_accounting_service()

    fin = svc.calculate_order_financials(
        gross_sales_amount=120.0, supplier_cost_amount=100.0,
        delivery_fee_amount=5.0, holdback_rate=0.10,
    )
    assert fin.markup_amount == 20.0
    assert abs(fin.markup_percent - 20.0) < 1e-6
    assert fin.holdback_amount == 10.0
    assert fin.net_supplier_payout == 85.0  # 100 - 10 holdback - 5 delivery

    capture = svc.post_capture_entries('ORD-CAP-1', fin)
    assert capture.success
    debits = sum(e['amount'] for e in capture.journal_entries if e['direction'] == 'debit')
    credits = sum(e['amount'] for e in capture.journal_entries if e['direction'] == 'credit')
    assert abs(debits - credits) < 1e-6

    summary = svc.get_marketplace_finance_summary()
    assert 'kpis' in summary
    assert summary['kpis']['gross_marketplace_revenue'] == 20.0

    refund = svc.post_refund_entries('ORD-CAP-1', amount=12.0, markup_share=2.0,
                                     supplier_share=10.0, currency='USD')
    assert refund.success
    debits_r = sum(e['amount'] for e in refund.journal_entries if e['direction'] == 'debit')
    credits_r = sum(e['amount'] for e in refund.journal_entries if e['direction'] == 'credit')
    assert abs(debits_r - credits_r) < 1e-6


def test_supplier_settlement_run_and_aging(isolated_db):
    from services.supplier_settlement_service import get_supplier_settlement_service

    svc = get_supplier_settlement_service()
    result = svc.build_settlement_run(
        supplier_id='SUP-A',
        order_payloads=[
            {'order_id': 'ORD-1', 'gross_sales_amount': 120.0,
             'supplier_cost_amount': 100.0, 'holdback_rate': 0.10},
            {'order_id': 'ORD-2', 'gross_sales_amount': 60.0,
             'supplier_cost_amount': 50.0, 'penalty_amount': 5.0},
        ],
    )
    assert result['success']
    assert len(result['items']) == 2
    run = result['run']
    assert run['gross_amount'] == 180.0
    # ORD-1 net = 100 - 10 holdback = 90
    # ORD-2 net = 50 - 5 penalty = 45
    assert abs(run['net_amount'] - 135.0) < 1e-6

    exec_result = svc.execute_settlement_run(run['id'], external_payout_reference='PAYOUT-XYZ',
                                             executed_by='admin@phins')
    assert exec_result['success']
    assert exec_result['run']['status'] == 'executed'
    assert exec_result['run']['external_payout_reference'] == 'PAYOUT-XYZ'

    aging = svc.get_aging_snapshot()
    assert 'buckets' in aging


def test_marketplace_event_outbox(isolated_db):
    from services.marketplace_event_service import get_marketplace_event_service, CANONICAL_EVENT_TYPES

    svc = get_marketplace_event_service()
    event = svc.publish_order_created('ORD-EV-1', {'customer_id': 'CUST-X', 'total_amount': 50})
    assert event is not None
    assert event['event_type'] in CANONICAL_EVENT_TYPES
    assert event['status'] == 'pending'

    pending = svc.list_pending(limit=10)
    assert any(e['id'] == event['id'] for e in pending)

    assert svc.mark_published(event['id']) is True
    pending_after = svc.list_pending(limit=10)
    assert all(e['id'] != event['id'] for e in pending_after)


def test_platform_integrity_marketplace_validators(isolated_db):
    from services.wallet_ledger_service import get_wallet_ledger_service
    from services.marketplace_accounting_service import get_marketplace_accounting_service
    from services.platform_integrity_service import get_platform_integrity_service
    from database.manager import DatabaseManager

    wallet_svc = get_wallet_ledger_service()
    accounting_svc = get_marketplace_accounting_service()

    # Healthy wallet flow.
    wallet_svc.deposit('CUST-INTEG', 200.0)
    hold = wallet_svc.create_hold('CUST-INTEG', 50.0, order_id='ORD-INT-1', idempotency_key='inv-1')
    wallet_svc.capture_hold(hold.hold['id'])

    fin = accounting_svc.calculate_order_financials(120.0, 100.0)
    accounting_svc.post_capture_entries('ORD-INT-1', fin)

    # Add an orphaned refund to exercise lineage validator.
    with DatabaseManager() as db:
        db.refunds.create(id='REF-BAD', order_id='', funding_source='wallet', amount=10.0)

    integrity = get_platform_integrity_service()
    integrity.errors = []
    integrity.warnings = []
    report = integrity.validate_marketplace_foundation()

    assert 'wallet_holds' in report
    assert 'settlement_aging' in report
    assert 'markup_recognition' in report
    assert 'payer_receivable_aging' in report
    assert 'refund_lineage' in report
    assert report['refund_lineage']['status'] == 'FAIL'
    assert any('REF-BAD' in (o.get('refund_id') or '') for o in report['refund_lineage']['orphaned_refunds'])
