"""
Regression tests for ledger hydration after a fresh container start.

Without hydration the Railway boot path produces this integrity warning on
every restart where the JSON ledger persistence file is missing but the SQL
``platform_ledger_entries`` table already has rows from prior runs:

    ⚠️  [INTEGRITY] Startup validation: 1 issue(s) detected
       ✗ Ledger chain invalid: 1 broken links, 20 sequence gaps, 0 duplicates

Root cause: ``PlatformEventLedgerService.append_event()`` reads the latest
sequence number from memory ∪ DB. With memory empty and the DB holding
sequence_no=1..N, the next append gets sequence_no=N+1 — but the DB INSERT
is skipped because the row's ID already exists. Memory ends up with
sequence_no=N+1..2N for the same IDs that the DB stores at 1..N, breaking
the hash chain and the sequence numbering.

Fix: ``PlatformEventLedgerService.hydrate_from_db()`` loads existing DB
rows into memory before any new appends so the chain stays consistent.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest


@pytest.fixture()
def sqlite_ledger(monkeypatch):
    """Provision an isolated SQLite database with the platform_ledger schema."""
    from database import init_database, reset_connection

    sqlite_file = Path(tempfile.mkdtemp()) / "phins_ledger_hydrate.db"
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


def _seed_sample_ledger(service, n_entries=20):
    """Append the same fixed-id payloads the Railway boot script appends."""
    seeded = []
    for index in range(n_entries):
        entry_id = f"TX-DEMO-{index:03d}"
        seeded.append(
            service.append_event(
                event_type="policy_approved" if index < 5 else "billing_created",
                entity_type="transaction",
                entity_id=entry_id,
                customer_id="CUST-DEMO-001",
                actor="system",
                amount=100.0 + index,
                status="completed",
                source_system="test",
                payload={"id": entry_id, "demo_index": index},
                entry_id=entry_id,
                ledger_type="transaction",
            )
        )
    return seeded


def test_reseed_without_hydration_breaks_chain(sqlite_ledger):
    """Documents the bug: re-appending fixed-id entries against an empty memory
    ledger but populated DB produces sequence gaps and a broken first link."""
    from services.platform_event_ledger_service import reconcile_ledger_entries

    first_memory = {}
    first_service = _make_service(first_memory)
    _seed_sample_ledger(first_service, n_entries=20)

    first_summary = reconcile_ledger_entries(first_memory.values())
    assert first_summary["chain_valid"], (
        "first-run chain must be valid; got "
        f"broken={len(first_summary['broken_links'])}, "
        f"gaps={len(first_summary['sequence_gaps'])}"
    )

    restart_memory = {}
    restart_service = _make_service(restart_memory)
    _seed_sample_ledger(restart_service, n_entries=20)

    restart_summary = reconcile_ledger_entries(restart_memory.values())
    assert not restart_summary["chain_valid"]
    assert len(restart_summary["sequence_gaps"]) == 20
    assert len(restart_summary["broken_links"]) >= 1


def test_hydrate_from_db_restores_chain_after_restart(sqlite_ledger):
    """With hydrate_from_db() the memory ledger comes back from SQL with the
    same sequence numbers and hashes the previous run wrote, so re-running
    the sample seed loop is a no-op and the chain remains valid."""
    from services.platform_event_ledger_service import reconcile_ledger_entries

    first_memory = {}
    first_service = _make_service(first_memory)
    first_seeded = _seed_sample_ledger(first_service, n_entries=20)
    expected_hashes = {entry["id"]: entry["entry_hash"] for entry in first_seeded}
    expected_sequences = {entry["id"]: entry["sequence_no"] for entry in first_seeded}

    restart_memory = {}
    restart_service = _make_service(restart_memory)

    hydrated = restart_service.hydrate_from_db()
    assert hydrated == 20

    _seed_sample_ledger(restart_service, n_entries=20)

    summary = reconcile_ledger_entries(restart_memory.values())
    assert summary["chain_valid"], (
        "post-hydration chain must be valid; got "
        f"broken={len(summary['broken_links'])}, "
        f"gaps={len(summary['sequence_gaps'])}, "
        f"missing_hash={len(summary['missing_hash_ids'])}"
    )
    assert summary["total_entries"] == 20
    assert len(summary["sequence_gaps"]) == 0
    assert len(summary["broken_links"]) == 0

    for entry_id, expected_hash in expected_hashes.items():
        assert restart_memory[entry_id]["entry_hash"] == expected_hash, (
            f"Hydrated entry {entry_id} hash diverged from original"
        )
        assert restart_memory[entry_id]["sequence_no"] == expected_sequences[entry_id]


def test_hydrate_from_db_is_no_op_when_db_empty(sqlite_ledger):
    """Hydration must be a safe no-op on a completely fresh deployment."""
    from services.platform_event_ledger_service import reconcile_ledger_entries

    memory = {}
    service = _make_service(memory)

    assert service.hydrate_from_db() == 0
    assert memory == {}

    _seed_sample_ledger(service, n_entries=5)
    summary = reconcile_ledger_entries(memory.values())
    assert summary["chain_valid"]
    assert summary["total_entries"] == 5


def test_hydrate_from_db_preserves_existing_memory_entries(sqlite_ledger):
    """Already-loaded entries must take precedence over DB rows so a partial
    JSON persistence load is not silently overwritten."""
    first_memory = {}
    first_service = _make_service(first_memory)
    seeded = _seed_sample_ledger(first_service, n_entries=3)
    target_id = seeded[0]["id"]

    restart_memory = {target_id: {"id": target_id, "marker": "from-json-file"}}
    restart_service = _make_service(restart_memory)

    hydrated = restart_service.hydrate_from_db()
    assert hydrated == 2  # the other two; the pre-existing one was skipped
    assert restart_memory[target_id]["marker"] == "from-json-file"
