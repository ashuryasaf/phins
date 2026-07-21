"""
Tests for the startup fast paths that keep boot time flat as data grows:

1. init_database() schema fingerprint marker — the full DDL sync (create_all
   + upgrade_schema, one reflection query per table) only runs when the
   declared models changed, were never synced, or PHINS_FORCE_SCHEMA_SYNC is
   set.
2. seed_default_users() / seed_dynamic_customers() batch existence checks —
   one SELECT for all accounts instead of one lookup per account, deferred
   password resolution (no misleading "No password configured" warnings for
   accounts that already exist).
3. Platform ledger hydration delta fast path — when the in-memory ledger
   already holds every DB row id, hydration performs the ids-only probe and
   never re-transfers full rows.
"""

from __future__ import annotations

import logging
import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


# ---------------------------------------------------------------------------
# 1. Schema fingerprint marker
# ---------------------------------------------------------------------------

@pytest.fixture()
def isolated_sqlite(monkeypatch, tmp_path):
    """Isolated SQLite DB with PHINS_TEST_MODE cleared.

    PHINS_TEST_MODE forces drop_existing=True for tempdir SQLite paths inside
    init_database(), which bypasses the marker fast path — so it must be
    cleared to test production boot behavior. The DB file still lives under
    pytest's tmp_path and env changes are restored by monkeypatch.
    """
    from database import reset_connection

    sqlite_file = tmp_path / "phins_schema_marker.db"
    monkeypatch.setenv("USE_SQLITE", "true")
    monkeypatch.setenv("SQLITE_PATH", str(sqlite_file))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("PHINS_TEST_MODE", raising=False)
    monkeypatch.delenv("PHINS_FORCE_SCHEMA_SYNC", raising=False)

    reset_connection()
    try:
        yield sqlite_file
    finally:
        reset_connection()


def _init_and_capture(caplog):
    from database import init_database

    caplog.clear()
    with caplog.at_level(logging.INFO, logger="database"):
        init_database()
    return caplog.text


def test_second_init_skips_ddl_sync(isolated_sqlite, caplog):
    first = _init_and_capture(caplog)
    assert "Creating database tables..." in first
    assert "skipping DDL sync" not in first

    second = _init_and_capture(caplog)
    assert "skipping DDL sync" in second
    assert "Creating database tables..." not in second


def test_marker_mismatch_reruns_full_sync(isolated_sqlite, caplog):
    from sqlalchemy import text
    from database import get_engine

    _init_and_capture(caplog)

    with get_engine().connect() as conn:
        conn.execute(text(
            "UPDATE schema_sync_state SET fingerprint = 'stale' WHERE id = 1"
        ))
        conn.commit()

    rerun = _init_and_capture(caplog)
    assert "Creating database tables..." in rerun
    assert "skipping DDL sync" not in rerun

    # And the marker is refreshed, so the next boot skips again.
    assert "skipping DDL sync" in _init_and_capture(caplog)


def test_force_schema_sync_env_bypasses_marker(isolated_sqlite, caplog, monkeypatch):
    _init_and_capture(caplog)
    monkeypatch.setenv("PHINS_FORCE_SCHEMA_SYNC", "true")
    forced = _init_and_capture(caplog)
    assert "Creating database tables..." in forced
    assert "skipping DDL sync" not in forced


def test_drop_existing_reruns_and_resets_marker(isolated_sqlite, caplog):
    from database import init_database

    _init_and_capture(caplog)

    caplog.clear()
    with caplog.at_level(logging.INFO, logger="database"):
        init_database(drop_existing=True)
    assert "Creating database tables..." in caplog.text

    # Marker was rewritten after the drop/create, next boot skips again.
    assert "skipping DDL sync" in _init_and_capture(caplog)


def test_failed_upgrade_does_not_persist_marker(isolated_sqlite, caplog, monkeypatch):
    """If upgrade_schema reports a failure, the marker must not be written so
    the next boot re-runs the DDL sync (transient failures get retried)."""
    import database as db

    monkeypatch.setattr(db, "upgrade_schema", lambda engine=None: False)

    first = _init_and_capture(caplog)
    assert "Creating database tables..." in first
    assert db._read_schema_marker(db.get_engine()) is None

    # Next boot must re-run the full sync rather than skip via a stale marker.
    rerun = _init_and_capture(caplog)
    assert "Creating database tables..." in rerun
    assert "skipping DDL sync" not in rerun


def test_schema_still_usable_after_marker_skip(isolated_sqlite, caplog):
    """A boot that skipped the DDL sync must still see a fully working schema."""
    from database import get_db_session, reset_connection
    from database.repositories import UserRepository

    _init_and_capture(caplog)
    assert "skipping DDL sync" in _init_and_capture(caplog)

    session = get_db_session()
    try:
        repo = UserRepository(session)
        assert repo.get_by_username("nonexistent-user") is None
        created = repo.create(
            username="marker-check-user",
            password_hash="x",
            password_salt="y",
            role="customer",
            name="Marker Check",
            email="marker@check.local",
            active=True,
        )
        assert created is not None
    finally:
        session.close()
        reset_connection()


# ---------------------------------------------------------------------------
# 2. Batched seed existence checks + deferred password resolution
# ---------------------------------------------------------------------------

def test_seed_default_users_idempotent_and_quiet_on_rerun(isolated_sqlite, caplog):
    from database import get_db_session
    from database.repositories import UserRepository
    from database.seeds import seed_default_users

    _init_and_capture(caplog)

    seed_default_users()

    session = get_db_session()
    try:
        repo = UserRepository(session)
        admin = repo.get_by_username("admin")
        assert admin is not None and admin.role == "admin"
        first_count = repo.count()
    finally:
        session.close()

    # Re-run: no new users, no "No password configured" warnings for accounts
    # that already exist (passwords resolve only at creation time).
    caplog.clear()
    with caplog.at_level(logging.DEBUG, logger="database.seeds"):
        seed_default_users()
    assert "No password configured" not in caplog.text

    session = get_db_session()
    try:
        repo = UserRepository(session)
        assert repo.count() == first_count
    finally:
        session.close()


def test_seed_default_users_still_repairs_changed_role(isolated_sqlite, caplog):
    from database import get_db_session
    from database.seeds import seed_default_users
    from database.repositories import UserRepository

    _init_and_capture(caplog)
    seed_default_users()

    session = get_db_session()
    try:
        repo = UserRepository(session)
        admin = repo.get_by_username("admin")
        admin.role = "customer"
        session.commit()
    finally:
        session.close()

    seed_default_users()

    session = get_db_session()
    try:
        repo = UserRepository(session)
        assert repo.get_by_username("admin").role == "admin"
    finally:
        session.close()


def test_get_by_usernames_batch_lookup(isolated_sqlite, caplog):
    from database import get_db_session
    from database.repositories import UserRepository
    from database.seeds import seed_default_users

    _init_and_capture(caplog)
    seed_default_users()

    session = get_db_session()
    try:
        repo = UserRepository(session)
        found = repo.get_by_usernames(["admin", "actuary", "no-such-user"])
        assert {user.username for user in found} == {"admin", "actuary"}
        assert repo.get_by_usernames([]) == []
    finally:
        session.close()


def test_seed_dynamic_customers_batch_skip(isolated_sqlite, caplog, monkeypatch, tmp_path):
    import json

    import database.seeds as seeds
    from database import get_db_session
    from database.repositories import UserRepository

    _init_and_capture(caplog)

    dynamic_file = tmp_path / "dynamic_customers.json"
    dynamic_file.write_text(json.dumps([
        {"username": "dyn1@example.com", "email": "dyn1@example.com",
         "name": "Dyn One", "password": "pw-one-123"},
        {"username": "dyn2@example.com", "email": "dyn2@example.com",
         "name": "Dyn Two", "password": "pw-two-123"},
    ]))
    monkeypatch.setattr(seeds, "DYNAMIC_CUSTOMERS_FILE", str(dynamic_file))

    session = get_db_session()
    try:
        repo = UserRepository(session)
        seeds.seed_dynamic_customers(session, repo)
        assert repo.get_by_username("dyn1@example.com") is not None
        assert repo.get_by_username("dyn2@example.com") is not None
        count_after_first = repo.count()

        seeds.seed_dynamic_customers(session, repo)
        assert repo.count() == count_after_first
    finally:
        session.close()


# ---------------------------------------------------------------------------
# 3. Ledger hydration delta fast path
# ---------------------------------------------------------------------------

@pytest.fixture()
def sqlite_ledger(monkeypatch):
    """Isolated SQLite DB (same shape as tests/test_platform_ledger_hydration.py)."""
    from database import init_database, reset_connection

    sqlite_file = Path(tempfile.mkdtemp()) / "phins_ledger_fastpath.db"
    monkeypatch.setenv("USE_SQLITE", "true")
    monkeypatch.setenv("SQLITE_PATH", str(sqlite_file))
    monkeypatch.delenv("DATABASE_URL", raising=False)

    reset_connection()
    init_database()
    try:
        yield sqlite_file
    finally:
        reset_connection()
        try:
            sqlite_file.unlink()
        except FileNotFoundError:
            pass


def _make_service(transaction_ledger):
    from database.manager import DatabaseManager
    from services.platform_event_ledger_service import PlatformEventLedgerService

    return PlatformEventLedgerService(
        transaction_ledger=transaction_ledger,
        use_database=True,
        db_manager_factory=DatabaseManager,
    )


def _seed_entries(service, n_entries):
    seeded = []
    for index in range(n_entries):
        entry_id = f"TX-FASTPATH-{index:03d}"
        seeded.append(service.append_event(
            event_type="billing_created",
            entity_type="transaction",
            entity_id=entry_id,
            customer_id="CUST-FASTPATH-001",
            amount=10.0 + index,
            payload={"id": entry_id},
            entry_id=entry_id,
        ))
    return seeded


def test_hydrate_skips_full_row_fetch_when_memory_has_all_ids(sqlite_ledger, monkeypatch):
    """When memory already contains every DB id (JSON snapshot restored the
    ledger), hydration must stop after the ids-only probe — no full-row scan."""
    from database.repositories.platform_ledger_repository import PlatformLedgerRepository

    memory = {}
    service = _make_service(memory)
    _seed_entries(service, 10)

    def _fail_full_scan(self, limit=None):
        raise AssertionError("full-row scan must not run when ids all match")

    def _fail_get_by_ids(self, entry_ids):
        raise AssertionError(f"row fetch must not run for {entry_ids}")

    monkeypatch.setattr(PlatformLedgerRepository, "get_all_by_sequence", _fail_full_scan)
    monkeypatch.setattr(PlatformLedgerRepository, "get_by_ids", _fail_get_by_ids)

    # Memory already holds all 10 entries appended above.
    assert service.hydrate_from_db() == 0


def test_hydrate_fetches_only_missing_rows(sqlite_ledger, monkeypatch):
    """Only rows absent from memory are fetched, and the hydrated entries keep
    their original sequence numbers and hashes."""
    from database.repositories.platform_ledger_repository import PlatformLedgerRepository

    first_memory = {}
    first_service = _make_service(first_memory)
    seeded = _seed_entries(first_service, 6)

    # Restart where the JSON snapshot restored only the first 4 entries.
    restart_memory = {e["id"]: dict(e) for e in seeded[:4]}
    restart_service = _make_service(restart_memory)

    fetched_ids = []
    original_get_by_ids = PlatformLedgerRepository.get_by_ids

    def _spy_get_by_ids(self, entry_ids):
        fetched_ids.extend(entry_ids)
        return original_get_by_ids(self, entry_ids)

    monkeypatch.setattr(PlatformLedgerRepository, "get_by_ids", _spy_get_by_ids)

    assert restart_service.hydrate_from_db() == 2
    assert sorted(fetched_ids) == [seeded[4]["id"], seeded[5]["id"]]
    for entry in seeded:
        assert restart_memory[entry["id"]]["entry_hash"] == entry["entry_hash"]
        assert restart_memory[entry["id"]]["sequence_no"] == entry["sequence_no"]


def test_hydrate_falls_back_to_full_scan_when_probe_unavailable(sqlite_ledger, monkeypatch):
    """If the ids-only probe fails, hydration must fall back to the full scan
    rather than skipping hydration (chain integrity depends on it)."""
    from database.repositories.platform_ledger_repository import PlatformLedgerRepository

    first_memory = {}
    first_service = _make_service(first_memory)
    seeded = _seed_entries(first_service, 5)

    def _broken_probe(self):
        raise RuntimeError("probe unavailable")

    monkeypatch.setattr(PlatformLedgerRepository, "get_all_ids_by_sequence", _broken_probe)

    restart_memory = {}
    restart_service = _make_service(restart_memory)
    assert restart_service.hydrate_from_db() == 5
    for entry in seeded:
        assert restart_memory[entry["id"]]["entry_hash"] == entry["entry_hash"]
