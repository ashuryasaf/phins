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
    FIDUCIARY_SNAPSHOT_KEYS,
    fiduciary_mode,
    flush_fiduciary_to_db,
    hydrate_fiduciary_from_db,
    omit_fiduciary_from_snapshot,
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
    init_database(drop_existing=True)
    yield
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
