"""U2: sealed fiduciary tables round-trip wallets / BS and withhold bad checksums."""

from __future__ import annotations

import hashlib
import json
import os

import pytest

from database import init_database
from database.fiduciary_models import HealthWallet
from database.manager import DatabaseManager
from database.repositories.fiduciary_repository import BALANCE_SHEET_ID, canonical_payload
from services.fiduciary.migrate import migrate_snapshot_to_fiduciary_tables
from services.fiduciary.store import (
    FIDUCIARY_BOOKS_DB,
    FIDUCIARY_BOOKS_MARKER,
    FIDUCIARY_SNAPSHOT_KEYS,
    capture_fiduciary_baseline_from_memory,
    fiduciary_baseline,
    fiduciary_mode,
    flush_fiduciary_to_db,
    hydrate_fiduciary_from_db,
    omit_fiduciary_from_snapshot,
    reset_fiduciary_baseline,
)
from services import ledger_snapshot_store as lss


@pytest.fixture
def sqlite_db(monkeypatch, tmp_path):
    monkeypatch.setenv('USE_DATABASE', 'true')
    monkeypatch.setenv('USE_SQLITE', 'true')
    monkeypatch.setenv('SQLITE_PATH', str(tmp_path / 'fiduciary-u2.sqlite'))
    monkeypatch.setenv('PHINS_FIDUCIARY_MODE', 'dual')
    monkeypatch.delenv('PHINS_TEST_MODE', raising=False)
    # Force db_mode_enabled via env (portal may not be loaded with DB flags).
    monkeypatch.setenv('PHINS_TEST_MODE', 'true')  # keep soft boot; mode is explicit dual
    reset_fiduciary_baseline()
    init_database(drop_existing=True)
    yield
    reset_fiduciary_baseline()
    # Leave the temp sqlite for inspection if needed.


def test_fiduciary_mode_explicit_and_omit():
    assert fiduciary_mode({'PHINS_FIDUCIARY_MODE': 'db'}) == 'db'
    assert omit_fiduciary_from_snapshot({'PHINS_FIDUCIARY_MODE': 'db'}) is True
    assert omit_fiduciary_from_snapshot({'PHINS_FIDUCIARY_MODE': 'dual'}) is False
    assert fiduciary_mode({'PHINS_FIDUCIARY_MODE': 'off'}) == 'off'


def test_canonical_payload_is_stable():
    text_a, digest_a = canonical_payload({'b': 2, 'a': 1})
    text_b, digest_b = canonical_payload({'a': 1, 'b': 2})
    assert text_a == text_b
    assert digest_a == digest_b
    assert len(digest_a) == 64


def test_upsert_and_load_health_wallet(sqlite_db):
    db = DatabaseManager()
    payload = {'customer_id': 'CUST-U2-1', 'balance': 1250.5, 'transactions': []}
    assert db.health_wallets.upsert('CUST-U2-1', payload) is True
    loaded = db.health_wallets.get_payload('CUST-U2-1')
    assert loaded == payload
    db.close()


def test_checksum_mismatch_is_withheld_and_not_overwritten(sqlite_db):
    db = DatabaseManager()
    assert db.health_wallets.upsert('CUST-BAD', {'balance': 10}) is True
    row = db.health_wallets.session.get(HealthWallet, 'CUST-BAD')
    assert row is not None
    row.checksum = '0' * 64
    db.health_wallets.session.commit()

    assert db.health_wallets.get_payload('CUST-BAD') is None
    # Must not overwrite a broken seal.
    assert db.health_wallets.upsert('CUST-BAD', {'balance': 99}) is False
    still = db.health_wallets.session.get(HealthWallet, 'CUST-BAD')
    assert still.checksum == '0' * 64
    db.close()


def test_flush_hydrate_round_trip_ae2(sqlite_db, monkeypatch):
    """AE2 shape: clear memory, restore from sealed tables (no volume / no file)."""
    monkeypatch.setenv('PHINS_FIDUCIARY_MODE', 'dual')
    wallets = {
        'CUST-A': {'customer_id': 'CUST-A', 'balance': 100.0},
        'CUST-B': {'customer_id': 'CUST-B', 'balance': 250.25},
    }
    withdrawals = {
        'WD-1': {'id': 'WD-1', 'customer_id': 'CUST-A', 'amount': 40.0, 'status': 'pending'},
    }
    nfts = {'NFT-1': {'token_id': 'NFT-1', 'customer_id': 'CUST-A', 'kind': 'wallet_withdrawal_request'}}
    investments = {'CUST-A': {'customer_id': 'CUST-A', 'balance': 900.0, 'allocations': []}}
    sheet = {
        'claims_reserve': 3500000.0,
        'operating_reserve': 1234.56,
        'seed_claims_reserve': 3500000.0,
    }

    flushed = flush_fiduciary_to_db(
        health_wallets=wallets,
        wallet_withdrawals=withdrawals,
        nft_ledger=nfts,
        investment_accounts=investments,
        balance_sheet=sheet,
    )
    assert flushed.get('mode') == 'dual'
    assert flushed['health_wallets']['written'] == 2
    assert flushed['balance_sheet']['written'] == 1

    # Simulate redeploy: empty process memory, no snapshot file.
    restored_wallets: dict = {}
    restored_withdrawals: dict = {}
    restored_nfts: dict = {}
    restored_investments: dict = {}
    restored_sheet: dict = {}
    counts = hydrate_fiduciary_from_db(
        health_wallets=restored_wallets,
        wallet_withdrawals=restored_withdrawals,
        nft_ledger=restored_nfts,
        investment_accounts=restored_investments,
        balance_sheet=restored_sheet,
        prefer_db=True,
    )
    assert counts['health_wallets'] == 2
    assert restored_wallets['CUST-A']['balance'] == 100.0
    assert restored_wallets['CUST-B']['balance'] == 250.25
    assert restored_withdrawals['WD-1']['amount'] == 40.0
    assert restored_nfts['NFT-1']['kind'] == 'wallet_withdrawal_request'
    assert restored_investments['CUST-A']['balance'] == 900.0
    assert restored_sheet['claims_reserve'] == 3500000.0
    assert restored_sheet.get('seed_claims_reserve') == 3500000.0


def test_migrate_snapshot_journal_first(sqlite_db, monkeypatch):
    monkeypatch.setenv('PHINS_FIDUCIARY_MODE', 'dual')
    events = []

    def _append(**kwargs):
        events.append(kwargs)
        return {'id': kwargs.get('entity_id')}

    snapshot = {
        'saved_at': '2026-11-27T12:00:00',
        'version': '2.0',
        'health_wallets': {'CUST-M': {'customer_id': 'CUST-M', 'balance': 42}},
        'wallet_withdrawals': {},
        'nft_ledger': {},
        'investment_accounts': {},
        'phins_balance_sheet': {'claims_reserve': 1.0, 'operating_reserve': 2.0},
    }
    result = migrate_snapshot_to_fiduciary_tables(snapshot, append_event=_append)
    assert result['migrated'] is True
    assert result['reason'] == 'ok'
    assert len(events) == 2
    assert events[0]['status'] == 'started'
    assert events[1]['status'] == 'completed'
    assert events[0]['payload']['fingerprint'] == result['fingerprint']

    # Second pass is a no-op (tables populated).
    again = migrate_snapshot_to_fiduciary_tables(snapshot, append_event=_append)
    assert again['migrated'] is False
    assert again['reason'] == 'tables_already_populated'


def test_migrate_resumes_empty_tables_after_partial(sqlite_db, monkeypatch):
    """A half-finished migrate must still fill remaining empty tables."""
    monkeypatch.setenv('PHINS_FIDUCIARY_MODE', 'dual')
    events = []

    def _append(**kwargs):
        events.append(kwargs)
        return {'id': kwargs.get('entity_id')}

    # Simulate crash after only wallets landed.
    partial = {
        'health_wallets': {'CUST-P': {'customer_id': 'CUST-P', 'balance': 7}},
    }
    first = migrate_snapshot_to_fiduciary_tables(partial, append_event=_append)
    assert first['migrated'] is True
    assert first['keys'] == ['health_wallets']

    full = {
        'health_wallets': {'CUST-P': {'customer_id': 'CUST-P', 'balance': 7}},
        'phins_balance_sheet': {'claims_reserve': 99.0, 'operating_reserve': 1.0},
        'wallet_withdrawals': {
            'WD-P': {'id': 'WD-P', 'customer_id': 'CUST-P', 'amount': 3.0},
        },
    }
    second = migrate_snapshot_to_fiduciary_tables(full, append_event=_append)
    assert second['migrated'] is True
    assert second['reason'] == 'ok'
    assert 'health_wallets' not in second['keys']  # all wallet ids already present
    assert 'phins_balance_sheet' in second['keys']
    assert 'wallet_withdrawals' in second['keys']

    db = DatabaseManager()
    assert db.health_wallets.count_rows() == 1
    assert db.wallet_withdrawals.count_rows() == 1
    assert db.balance_sheet.get_phins()['claims_reserve'] == 99.0
    db.close()

    # Everything present → no-op.
    third = migrate_snapshot_to_fiduciary_tables(full, append_event=_append)
    assert third['migrated'] is False
    assert third['reason'] == 'tables_already_populated'


def test_migrate_fills_missing_ids_inside_half_written_table(sqlite_db, monkeypatch):
    """count_rows()>0 must not skip remaining wallet ids in the same table."""
    monkeypatch.setenv('PHINS_FIDUCIARY_MODE', 'dual')
    events = []

    def _append(**kwargs):
        events.append(kwargs)
        return {'id': kwargs.get('entity_id')}

    first = migrate_snapshot_to_fiduciary_tables(
        {'health_wallets': {'CUST-A': {'customer_id': 'CUST-A', 'balance': 1}}},
        append_event=_append,
    )
    assert first['migrated'] is True

    second = migrate_snapshot_to_fiduciary_tables(
        {
            'health_wallets': {
                'CUST-A': {'customer_id': 'CUST-A', 'balance': 1},
                'CUST-B': {'customer_id': 'CUST-B', 'balance': 2},
            },
        },
        append_event=_append,
    )
    assert second['migrated'] is True
    assert 'health_wallets' in second['keys']
    assert second['counts']['health_wallets']['written'] == 1
    assert second['counts']['health_wallets']['skipped'] == 1

    db = DatabaseManager()
    assert db.health_wallets.count_rows() == 2
    assert db.health_wallets.get_payload('CUST-B')['balance'] == 2
    # Existing intact row is not rewritten by fill-missing.
    assert db.health_wallets.get_payload('CUST-A')['balance'] == 1
    db.close()


def test_migrate_journal_failure_propagates(sqlite_db, monkeypatch):
    """Journal refusal must raise — no table writes without a before-record."""
    monkeypatch.setenv('PHINS_FIDUCIARY_MODE', 'dual')

    def _boom(**kwargs):
        raise RuntimeError('ledger_sealed')

    with pytest.raises(RuntimeError, match='ledger_sealed'):
        migrate_snapshot_to_fiduciary_tables(
            {'health_wallets': {'CUST-J': {'customer_id': 'CUST-J', 'balance': 1}}},
            append_event=_boom,
        )
    db = DatabaseManager()
    assert db.health_wallets.count_rows() == 0
    db.close()


def test_migrate_row_errors_are_not_reported_ok(sqlite_db, monkeypatch):
    """Per-row write failures must not yield migrated=True / completed."""
    monkeypatch.setenv('PHINS_FIDUCIARY_MODE', 'dual')
    events = []

    def _append(**kwargs):
        events.append(kwargs)
        return {'id': kwargs.get('entity_id')}

    db = DatabaseManager()
    assert db.health_wallets.upsert('CUST-BAD', {'balance': 1}) is True
    row = db.health_wallets.session.get(HealthWallet, 'CUST-BAD')
    row.checksum = '0' * 64
    db.health_wallets.session.commit()
    db.close()

    # force=True uses replace_mapping, which withholds the broken seal.
    result = migrate_snapshot_to_fiduciary_tables(
        {
            'health_wallets': {
                'CUST-BAD': {'customer_id': 'CUST-BAD', 'balance': 99},
                'CUST-OK': {'customer_id': 'CUST-OK', 'balance': 2},
            },
        },
        append_event=_append,
        force=True,
    )
    assert result['migrated'] is False
    assert result['reason'] == 'error:row_errors'
    assert result['counts']['health_wallets']['withheld'] >= 1
    assert events[-1]['status'] == 'failed'

    db = DatabaseManager()
    # Intact new id may still have been written before withheld was tallied.
    assert db.health_wallets.get_payload('CUST-BAD') is None
    db.close()


def test_flush_error_is_surfaced(sqlite_db, monkeypatch):
    """db mode callers must see flush failure; dual still returns the error key."""
    monkeypatch.setenv('PHINS_FIDUCIARY_MODE', 'db')

    class _Boom:
        def count_rows(self):
            return 0

        def replace_mapping(self, *a, **k):
            raise RuntimeError('boom')

        def upsert_phins(self, *a, **k):
            raise RuntimeError('boom')

    class _FakeDB:
        health_wallets = _Boom()
        wallet_withdrawals = _Boom()
        nft_ledger = _Boom()
        investment_accounts = _Boom()
        balance_sheet = _Boom()

        def close(self):
            pass

    monkeypatch.setattr(
        'services.fiduciary.store._db_manager',
        lambda: _FakeDB(),
    )
    result = flush_fiduciary_to_db(
        health_wallets={'C': {'balance': 1}},
        wallet_withdrawals={},
        nft_ledger={},
        investment_accounts={},
        balance_sheet={'claims_reserve': 1},
    )
    assert result.get('mode') == 'db'
    assert result.get('error') == 'RuntimeError'


def test_hydrate_propagates_db_open_failure(monkeypatch):
    """Hydrate must not soft-return empty counts when the DB cannot open."""
    monkeypatch.setenv('PHINS_FIDUCIARY_MODE', 'db')
    monkeypatch.setattr(
        'services.fiduciary.store._db_manager',
        lambda: (_ for _ in ()).throw(RuntimeError('db_down')),
    )
    with pytest.raises(RuntimeError, match='db_down'):
        hydrate_fiduciary_from_db(
            health_wallets={},
            wallet_withdrawals={},
            nft_ledger={},
            investment_accounts={},
            balance_sheet={},
            prefer_db=True,
        )


def test_should_flush_fiduciary_skips_clean_periodic_ticks():
    """Idle periodic / shutdown saves must not republish process-local books."""
    from web_portal.server import _should_flush_fiduciary

    assert _should_flush_fiduciary(periodic=True, wrote_file=False, force_db=False) is False
    assert _should_flush_fiduciary(periodic=True, wrote_file=True, force_db=False) is True
    assert _should_flush_fiduciary(periodic=False, wrote_file=False, force_db=False) is True
    # force_db alone (idle SIGTERM) must not flush stale hydrated books.
    assert _should_flush_fiduciary(periodic=True, wrote_file=False, force_db=True) is False
    assert _should_flush_fiduciary(periodic=False, wrote_file=False, force_db=True) is False
    assert _should_flush_fiduciary(periodic=False, wrote_file=True, force_db=True) is True


def test_graceful_shutdown_skips_flush_when_clean(monkeypatch):
    """Idle SIGTERM must not invent dirtiness or flush fiduciary books."""
    import web_portal.server as portal

    monkeypatch.setattr(portal, '_persistence_dirty', False)
    called = {'n': 0}

    def _save(*_a, **_k):
        called['n'] += 1
        return True

    monkeypatch.setattr(portal, 'save_ledger_data', _save)
    with pytest.raises(SystemExit):
        portal._graceful_shutdown(15, None)
    assert called['n'] == 0


def test_dual_db_snapshot_copy_prefers_sealed_over_stale_keys(sqlite_db, monkeypatch):
    """Throttled agent_artifacts copy must not skip sealed hydrate in dual."""
    import web_portal.server as portal

    monkeypatch.setenv('PHINS_FIDUCIARY_MODE', 'dual')
    monkeypatch.setenv('USE_DATABASE', 'true')
    assert flush_fiduciary_to_db(
        health_wallets={
            'CUST-NEWER': {'customer_id': 'CUST-NEWER', 'balance': 99},
        },
        wallet_withdrawals={},
        nft_ledger={},
        investment_accounts={},
        balance_sheet={},
    )['health_wallets']['written'] == 1

    portal.HEALTH_WALLETS.clear()
    portal.HEALTH_WALLETS['CUST-NEWER'] = {
        'customer_id': 'CUST-NEWER',
        'balance': 1,  # stale throttled snapshot
    }
    portal.WALLET_WITHDRAWALS.clear()
    portal.NFT_LEDGER.clear()
    portal.INVESTMENT_ACCOUNTS.clear()

    portal._hydrate_and_migrate_fiduciary(
        {
            'health_wallets': {
                'CUST-NEWER': {'customer_id': 'CUST-NEWER', 'balance': 1},
            },
            'wallet_withdrawals': {},
            'nft_ledger': {},
            'investment_accounts': {},
            'phins_balance_sheet': {},
        },
        prefer_sealed=True,
    )
    assert portal.HEALTH_WALLETS['CUST-NEWER']['balance'] == 99


def test_flush_skips_empty_book_without_blocking_others(sqlite_db, monkeypatch):
    """Empty NFT book must not abort wallet flush or wipe sealed wallets."""
    monkeypatch.setenv('PHINS_FIDUCIARY_MODE', 'dual')
    assert flush_fiduciary_to_db(
        health_wallets={'CUST-E': {'customer_id': 'CUST-E', 'balance': 5}},
        wallet_withdrawals={},
        nft_ledger={'NFT-E': {'token_id': 'NFT-E', 'customer_id': 'CUST-E'}},
        investment_accounts={},
        balance_sheet={},
    )['nft_ledger']['written'] == 1
    result = flush_fiduciary_to_db(
        health_wallets={'CUST-E': {'customer_id': 'CUST-E', 'balance': 9}},
        wallet_withdrawals={},
        nft_ledger={},  # purged in memory; sealed row remains
        investment_accounts={},
        balance_sheet={},
    )
    assert result.get('error') is None
    assert result['nft_ledger'].get('skipped') == 'refuse_empty_overwrite'
    assert result['health_wallets']['written'] == 1
    db = DatabaseManager()
    assert db.health_wallets.get_payload('CUST-E')['balance'] == 9
    assert db.nft_ledger.get_payload('NFT-E')['token_id'] == 'NFT-E'
    db.close()


def test_snapshot_payload_omits_fiduciary_keys_in_db_mode(monkeypatch):
    monkeypatch.setenv('PHINS_FIDUCIARY_MODE', 'db')
    snap = {
        'saved_at': '2026-11-27T12:00:00',
        'version': '2.0',
        'health_wallets': {'CUST-1': {'balance': 1}},
        'phins_balance_sheet': {'claims_reserve': 1},
        'transaction_ledger': {'TX-1': {}},
        'policies': {},
    }
    payload = lss.build_payload(snap)
    for key in FIDUCIARY_SNAPSHOT_KEYS:
        assert key not in payload['data']
    assert 'health_wallets' in payload['omitted']
    assert 'phins_balance_sheet' in payload['omitted']


def test_dual_empty_placeholders_still_hydrate(sqlite_db, monkeypatch):
    """db-mode file stamps fiduciary_books=db; dual rollback hydrates sealed rows."""
    import web_portal.server as portal

    monkeypatch.setenv('PHINS_FIDUCIARY_MODE', 'dual')
    monkeypatch.setenv('USE_DATABASE', 'true')
    assert flush_fiduciary_to_db(
        health_wallets={
            'CUST-EMPTY-PLACEHOLDER': {
                'customer_id': 'CUST-EMPTY-PLACEHOLDER',
                'balance': 42,
            }
        },
        wallet_withdrawals={},
        nft_ledger={},
        investment_accounts={},
        balance_sheet={},
    )['health_wallets']['written'] == 1

    portal.HEALTH_WALLETS.clear()
    portal.WALLET_WITHDRAWALS.clear()
    portal.NFT_LEDGER.clear()
    portal.INVESTMENT_ACCOUNTS.clear()
    assert not portal.HEALTH_WALLETS

    portal._hydrate_and_migrate_fiduciary(
        {
            FIDUCIARY_BOOKS_MARKER: FIDUCIARY_BOOKS_DB,
            'health_wallets': {},
            'wallet_withdrawals': {},
            'nft_ledger': {},
            'investment_accounts': {},
            'phins_balance_sheet': {},
        }
    )
    assert portal.HEALTH_WALLETS['CUST-EMPTY-PLACEHOLDER']['balance'] == 42


def test_dual_nonempty_books_skip_gap_fill(sqlite_db, monkeypatch):
    """Live dual file SoR must not resurrect purged ids via hydrate gap-fill."""
    import web_portal.server as portal

    monkeypatch.setenv('PHINS_FIDUCIARY_MODE', 'dual')
    monkeypatch.setenv('USE_DATABASE', 'true')
    assert flush_fiduciary_to_db(
        health_wallets={
            'CUST-KEEP': {'customer_id': 'CUST-KEEP', 'balance': 1},
            'CUST-PURGED': {'customer_id': 'CUST-PURGED', 'balance': 9},
        },
        wallet_withdrawals={},
        nft_ledger={},
        investment_accounts={},
        balance_sheet={},
    )['health_wallets']['written'] == 2

    portal.HEALTH_WALLETS.clear()
    portal.HEALTH_WALLETS['CUST-KEEP'] = {'customer_id': 'CUST-KEEP', 'balance': 1}
    portal.WALLET_WITHDRAWALS.clear()
    portal.NFT_LEDGER.clear()
    portal.INVESTMENT_ACCOUNTS.clear()

    called = {'n': 0}

    def _mark(*_a, **_k):
        called['n'] += 1
        return {'health_wallets': 0, 'withheld': 0}

    monkeypatch.setattr(
        'services.fiduciary.hydrate_fiduciary_from_db',
        _mark,
    )
    portal._hydrate_and_migrate_fiduciary(
        {
            'health_wallets': {'CUST-KEEP': {'customer_id': 'CUST-KEEP', 'balance': 1}},
            'wallet_withdrawals': {},
            'nft_ledger': {},
            'investment_accounts': {},
            'phins_balance_sheet': {},
        }
    )
    assert called['n'] == 0
    assert 'CUST-PURGED' not in portal.HEALTH_WALLETS


def test_dual_full_purge_empty_books_skip_gap_fill(sqlite_db, monkeypatch):
    """Dual file with empty fiduciary keys (no db marker) must not resurrect."""
    import web_portal.server as portal

    monkeypatch.setenv('PHINS_FIDUCIARY_MODE', 'dual')
    monkeypatch.setenv('USE_DATABASE', 'true')
    assert flush_fiduciary_to_db(
        health_wallets={
            'CUST-PURGED-ALL': {'customer_id': 'CUST-PURGED-ALL', 'balance': 7},
        },
        wallet_withdrawals={},
        nft_ledger={},
        investment_accounts={},
        balance_sheet={'claims_reserve': 1},
    )['health_wallets']['written'] == 1

    portal.HEALTH_WALLETS.clear()
    portal.WALLET_WITHDRAWALS.clear()
    portal.NFT_LEDGER.clear()
    portal.INVESTMENT_ACCOUNTS.clear()
    portal.PHINS_BALANCE_SHEET.clear()
    portal.PHINS_BALANCE_SHEET['claims_reserve'] = 1

    called = {'n': 0}

    def _mark(*_a, **_k):
        called['n'] += 1
        return {'health_wallets': 0, 'withheld': 0}

    monkeypatch.setattr(
        'services.fiduciary.hydrate_fiduciary_from_db',
        _mark,
    )
    portal._hydrate_and_migrate_fiduciary(
        {
            'health_wallets': {},
            'wallet_withdrawals': {},
            'nft_ledger': {},
            'investment_accounts': {},
            'phins_balance_sheet': {'claims_reserve': 1},
        }
    )
    assert called['n'] == 0
    assert 'CUST-PURGED-ALL' not in portal.HEALTH_WALLETS


def test_dual_hydrate_failure_without_file_sor_aborts(monkeypatch):
    """AE2 / missing file must not soft-continue into $0 wallet seeding."""
    import web_portal.server as portal
    from services.fiduciary import FiduciaryBootError

    monkeypatch.setenv('PHINS_FIDUCIARY_MODE', 'dual')
    monkeypatch.setenv('USE_DATABASE', 'true')

    def _boom(*_a, **_k):
        raise RuntimeError('db_down')

    monkeypatch.setattr(
        'services.fiduciary.hydrate_fiduciary_from_db',
        _boom,
    )
    with pytest.raises(FiduciaryBootError, match='RuntimeError'):
        portal._hydrate_and_migrate_fiduciary(None)


def test_dual_hydrate_failure_with_file_snapshot_soft_continues(monkeypatch):
    """Dual with a non-placeholder snapshot may soft-continue on hydrate error."""
    import web_portal.server as portal

    monkeypatch.setenv('PHINS_FIDUCIARY_MODE', 'dual')
    monkeypatch.setenv('USE_DATABASE', 'true')

    def _boom(*_a, **_k):
        raise RuntimeError('db_down')

    monkeypatch.setattr(
        'services.fiduciary.hydrate_fiduciary_from_db',
        _boom,
    )
    # Fiduciary keys omitted (other snapshot content only) → hydrate runs,
    # dual soft-continues because a file snapshot was applied.
    portal._hydrate_and_migrate_fiduciary({'transaction_ledger': {}})


def test_replace_mapping_does_not_delete_absent_or_withheld(sqlite_db, monkeypatch):
    """Upsert-only flush must keep absent ids and broken seals for forensics."""
    from database.fiduciary_models import HealthWallet

    monkeypatch.setenv('PHINS_FIDUCIARY_MODE', 'dual')
    assert flush_fiduciary_to_db(
        health_wallets={
            'CUST-KEEP': {'customer_id': 'CUST-KEEP', 'balance': 1},
            'CUST-GONE': {'customer_id': 'CUST-GONE', 'balance': 9},
        },
        wallet_withdrawals={},
        nft_ledger={},
        investment_accounts={},
        balance_sheet={},
    )['health_wallets']['written'] == 2
    db = DatabaseManager()
    row = db.health_wallets.session.get(HealthWallet, 'CUST-GONE')
    assert row is not None
    row.checksum = '0' * 64
    db.health_wallets.session.commit()
    db.close()

    result = flush_fiduciary_to_db(
        health_wallets={
            'CUST-KEEP': {'customer_id': 'CUST-KEEP', 'balance': 2},
        },
        wallet_withdrawals={},
        nft_ledger={},
        investment_accounts={},
        balance_sheet={},
    )
    assert 'deleted' not in result['health_wallets']
    db = DatabaseManager()
    assert db.health_wallets.get_payload('CUST-KEEP')['balance'] == 2
    # Broken seal still present and still withheld.
    assert db.health_wallets.get_payload('CUST-GONE') is None
    still = db.health_wallets.session.get(HealthWallet, 'CUST-GONE')
    assert still is not None
    assert still.checksum == '0' * 64
    db.close()


def test_upsert_cas_refuses_stale_expected_checksum(sqlite_db):
    """expected_checksum must match the sealed digest or the write is withheld."""
    db = DatabaseManager()
    original = {'customer_id': 'CUST-CAS', 'balance': 10}
    assert db.health_wallets.upsert('CUST-CAS', original) is True
    _, digest = canonical_payload(original)
    peer = {'customer_id': 'CUST-CAS', 'balance': 77}
    assert db.health_wallets.upsert(
        'CUST-CAS', peer, expected_checksum=digest
    ) is True
    _, peer_digest = canonical_payload(peer)
    # Stale CAS (pre-peer digest) must not revert the peer write.
    assert (
        db.health_wallets.upsert(
            'CUST-CAS',
            {'customer_id': 'CUST-CAS', 'balance': 10},
            expected_checksum=digest,
        )
        is False
    )
    assert db.health_wallets.get_payload('CUST-CAS')['balance'] == 77
    assert peer_digest == db.health_wallets.load_checksums()['CUST-CAS']
    db.close()


def test_upsert_missing_expected_checksum_withholds_overwrite(sqlite_db):
    """Existing sealed rows cannot be overwritten without a CAS token."""
    db = DatabaseManager()
    original = {'customer_id': 'CUST-NOCAS', 'balance': 5}
    assert db.health_wallets.upsert('CUST-NOCAS', original) is True
    assert (
        db.health_wallets.upsert(
            'CUST-NOCAS', {'customer_id': 'CUST-NOCAS', 'balance': 99}
        )
        is False
    )
    assert db.health_wallets.get_payload('CUST-NOCAS') == original
    # Idempotent no-op still allowed without a token.
    assert db.health_wallets.upsert('CUST-NOCAS', original) is True
    db.close()


def test_flush_cas_withholds_peer_wallet_update(sqlite_db, monkeypatch):
    """Multi-writer: process baseline must not overwrite a peer's sealed row."""
    monkeypatch.setenv('PHINS_FIDUCIARY_MODE', 'dual')
    wallets = {'CUST-MW': {'customer_id': 'CUST-MW', 'balance': 100.0}}
    assert flush_fiduciary_to_db(
        health_wallets=wallets,
        wallet_withdrawals={},
        nft_ledger={},
        investment_accounts={},
        balance_sheet={},
    )['health_wallets']['written'] == 1
    # Establish this process's CAS baseline from sealed tables.
    memory: dict = {}
    hydrate_fiduciary_from_db(
        health_wallets=memory,
        wallet_withdrawals={},
        nft_ledger={},
        investment_accounts={},
        balance_sheet={},
        prefer_db=True,
    )
    assert memory['CUST-MW']['balance'] == 100.0
    assert 'CUST-MW' in fiduciary_baseline('health_wallets')
    prior = fiduciary_baseline('health_wallets')['CUST-MW']

    # Peer writer updates sealed with a matching CAS token.
    db = DatabaseManager()
    assert db.health_wallets.upsert(
        'CUST-MW',
        {'customer_id': 'CUST-MW', 'balance': 999.0},
        expected_checksum=prior,
    ) is True
    db.close()

    # Stale process memory flushes → CAS withhold; peer value survives and
    # is adopted into the live map so the next save cannot revert it.
    stale = {'CUST-MW': {'customer_id': 'CUST-MW', 'balance': 100.0}}
    result = flush_fiduciary_to_db(
        health_wallets=stale,
        wallet_withdrawals={},
        nft_ledger={},
        investment_accounts={},
        balance_sheet={},
    )
    assert result['health_wallets']['withheld'] >= 1
    assert result['health_wallets']['written'] == 0
    assert result['health_wallets'].get('adopted', 0) >= 1
    assert stale['CUST-MW']['balance'] == 999.0
    db = DatabaseManager()
    assert db.health_wallets.get_payload('CUST-MW')['balance'] == 999.0
    db.close()

    # A follow-up flush of the (now adopted) book must not rewrite peer data.
    follow = flush_fiduciary_to_db(
        health_wallets=stale,
        wallet_withdrawals={},
        nft_ledger={},
        investment_accounts={},
        balance_sheet={},
    )
    assert follow['health_wallets']['withheld'] == 0
    db = DatabaseManager()
    assert db.health_wallets.get_payload('CUST-MW')['balance'] == 999.0
    db.close()


def test_flush_without_baseline_cannot_overwrite_sealed(sqlite_db, monkeypatch):
    """Empty process baseline must not blind-overwrite existing seals."""
    monkeypatch.setenv('PHINS_FIDUCIARY_MODE', 'dual')
    assert flush_fiduciary_to_db(
        health_wallets={'CUST-BL': {'customer_id': 'CUST-BL', 'balance': 1.0}},
        wallet_withdrawals={},
        nft_ledger={},
        investment_accounts={},
        balance_sheet={},
    )['health_wallets']['written'] == 1
    reset_fiduciary_baseline()
    result = flush_fiduciary_to_db(
        health_wallets={'CUST-BL': {'customer_id': 'CUST-BL', 'balance': 50.0}},
        wallet_withdrawals={},
        nft_ledger={},
        investment_accounts={},
        balance_sheet={},
    )
    assert result['health_wallets']['withheld'] >= 1
    assert result['health_wallets']['written'] == 0
    db = DatabaseManager()
    assert db.health_wallets.get_payload('CUST-BL')['balance'] == 1.0
    db.close()


def test_flush_cas_allows_write_when_baseline_matches(sqlite_db, monkeypatch):
    """Matching baseline still lets this process seal its own mutation."""
    monkeypatch.setenv('PHINS_FIDUCIARY_MODE', 'dual')
    assert flush_fiduciary_to_db(
        health_wallets={'CUST-OK': {'customer_id': 'CUST-OK', 'balance': 1.0}},
        wallet_withdrawals={},
        nft_ledger={},
        investment_accounts={},
        balance_sheet={},
    )['health_wallets']['written'] == 1
    memory: dict = {}
    hydrate_fiduciary_from_db(
        health_wallets=memory,
        wallet_withdrawals={},
        nft_ledger={},
        investment_accounts={},
        balance_sheet={},
        prefer_db=True,
    )
    memory['CUST-OK'] = {'customer_id': 'CUST-OK', 'balance': 42.0}
    result = flush_fiduciary_to_db(
        health_wallets=memory,
        wallet_withdrawals={},
        nft_ledger={},
        investment_accounts={},
        balance_sheet={},
    )
    assert result['health_wallets']['written'] == 1
    assert result['health_wallets']['withheld'] == 0
    db = DatabaseManager()
    assert db.health_wallets.get_payload('CUST-OK')['balance'] == 42.0
    db.close()


def test_dual_file_sor_memory_baseline_cannot_overwrite_newer_seal(
    sqlite_db, monkeypatch
):
    """Dual volume boot: baseline from file digests, not sealed checksums."""
    monkeypatch.setenv('PHINS_FIDUCIARY_MODE', 'dual')
    # Peer sealed a newer wallet first.
    assert flush_fiduciary_to_db(
        health_wallets={'CUST-FS': {'customer_id': 'CUST-FS', 'balance': 999.0}},
        wallet_withdrawals={},
        nft_ledger={},
        investment_accounts={},
        balance_sheet={},
    )['health_wallets']['written'] == 1
    reset_fiduciary_baseline()
    # This process boots from an older volume file (hydrate skipped).
    file_book = {'CUST-FS': {'customer_id': 'CUST-FS', 'balance': 1.0}}
    capture_fiduciary_baseline_from_memory(
        health_wallets=file_book,
        wallet_withdrawals={},
        nft_ledger={},
        investment_accounts={},
        balance_sheet={},
    )
    _, file_digest = canonical_payload(file_book['CUST-FS'])
    assert fiduciary_baseline('health_wallets')['CUST-FS'] == file_digest
    result = flush_fiduciary_to_db(
        health_wallets=file_book,
        wallet_withdrawals={},
        nft_ledger={},
        investment_accounts={},
        balance_sheet={},
    )
    assert result['health_wallets']['withheld'] >= 1
    assert result['health_wallets']['written'] == 0
    assert file_book['CUST-FS']['balance'] == 999.0
    db = DatabaseManager()
    assert db.health_wallets.get_payload('CUST-FS')['balance'] == 999.0
    db.close()


def test_upsert_atomic_cas_update_requires_matching_checksum(sqlite_db):
    """Conditional UPDATE withholds when the sealed checksum already moved."""
    db = DatabaseManager()
    original = {'customer_id': 'CUST-ATM', 'balance': 3}
    assert db.health_wallets.upsert('CUST-ATM', original) is True
    _, digest = canonical_payload(original)
    peer = {'customer_id': 'CUST-ATM', 'balance': 8}
    assert db.health_wallets.upsert(
        'CUST-ATM', peer, expected_checksum=digest
    ) is True
    assert (
        db.health_wallets.upsert(
            'CUST-ATM',
            {'customer_id': 'CUST-ATM', 'balance': 3},
            expected_checksum=digest,
        )
        is False
    )
    assert db.health_wallets.get_payload('CUST-ATM')['balance'] == 8
    db.close()


def test_flush_baseline_excludes_unheld_sealed_ids(sqlite_db, monkeypatch):
    """Post-flush baseline must not authorize overwriting peers we never held."""
    monkeypatch.setenv('PHINS_FIDUCIARY_MODE', 'dual')
    assert flush_fiduciary_to_db(
        health_wallets={
            'CUST-PEER': {'customer_id': 'CUST-PEER', 'balance': 999.0},
            'CUST-LOCAL': {'customer_id': 'CUST-LOCAL', 'balance': 5.0},
        },
        wallet_withdrawals={},
        nft_ledger={},
        investment_accounts={},
        balance_sheet={},
    )['health_wallets']['written'] == 2
    reset_fiduciary_baseline()
    # Replica only holds LOCAL (skipped gap-fill hydrate).
    local = {'CUST-LOCAL': {'customer_id': 'CUST-LOCAL', 'balance': 5.0}}
    capture_fiduciary_baseline_from_memory(
        health_wallets=local,
        wallet_withdrawals={},
        nft_ledger={},
        investment_accounts={},
        balance_sheet={},
    )
    flush_fiduciary_to_db(
        health_wallets=local,
        wallet_withdrawals={},
        nft_ledger={},
        investment_accounts={},
        balance_sheet={},
    )
    assert 'CUST-PEER' not in fiduciary_baseline('health_wallets')
    # Lazy get-or-create of a foreign id must not CAS-replace the peer seal.
    local['CUST-PEER'] = {'customer_id': 'CUST-PEER', 'balance': 0.0}
    result = flush_fiduciary_to_db(
        health_wallets=local,
        wallet_withdrawals={},
        nft_ledger={},
        investment_accounts={},
        balance_sheet={},
    )
    assert result['health_wallets']['withheld'] >= 1
    db = DatabaseManager()
    assert db.health_wallets.get_payload('CUST-PEER')['balance'] == 999.0
    db.close()


