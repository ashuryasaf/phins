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


def test_ensure_hash_chain_repairs_divergent_hydrated_chain(sqlite_ledger):
    """When the DB itself already carries a divergent chain (e.g. accumulated
    drift from older deployments that wrote entries before hydrate_from_db
    existed), hydrate_from_db pulls the divergent rows in unchanged.

    The boot path then calls ensure_hash_chain() to repair the *in-memory*
    chain. After that call the integrity validator must report chain_valid=True
    and the entries must be contiguous 1..N with a recomputed hash sequence.
    """
    from services.platform_event_ledger_service import (
        compute_entry_hash,
        reconcile_ledger_entries,
    )

    # Simulate a divergent DB: seed an entry with a deliberately wrong
    # previous_hash / sequence_no so the chain looks broken when hydrated.
    first_memory = {}
    first_service = _make_service(first_memory)
    _seed_sample_ledger(first_service, n_entries=10)

    # Directly tamper with one entry's stored hash + sequence_no via the DB
    # layer to simulate the production drift pattern.
    from database.manager import DatabaseManager
    from database.models import PlatformLedgerEntry

    import json as _json

    with DatabaseManager() as db:
        session = db._ensure_session()
        rows = (
            session.query(PlatformLedgerEntry)
            .order_by(PlatformLedgerEntry.sequence_no.asc())
            .all()
        )
        # Break the chain at row 5: rewrite its previous_hash + entry_hash
        # to bogus values both in the indexed columns AND in the embedded
        # payload (the payload takes precedence during hydration so both
        # must be tampered to reproduce production drift). Then shift
        # sequence_no on later rows so contiguous numbering is lost.
        bad_prev = "0" * 64
        bad_hash = "f" * 64
        rows[4].previous_hash = bad_prev
        rows[4].entry_hash = bad_hash
        try:
            payload_obj = _json.loads(rows[4].payload) if rows[4].payload else {}
        except Exception:
            payload_obj = {}
        if isinstance(payload_obj, dict):
            payload_obj["previous_hash"] = bad_prev
            payload_obj["entry_hash"] = bad_hash
            rows[4].payload = _json.dumps(payload_obj, sort_keys=True, default=str)

        for r in rows[5:]:
            new_seq = r.sequence_no + 100
            r.sequence_no = new_seq
            try:
                payload_obj = _json.loads(r.payload) if r.payload else {}
            except Exception:
                payload_obj = {}
            if isinstance(payload_obj, dict):
                payload_obj["sequence_no"] = new_seq
                r.payload = _json.dumps(payload_obj, sort_keys=True, default=str)
        db.commit()

    restart_memory = {}
    restart_service = _make_service(restart_memory)

    hydrated = restart_service.hydrate_from_db()
    assert hydrated == 10

    pre = reconcile_ledger_entries(restart_memory.values())
    assert not pre["chain_valid"], (
        "fixture must yield a broken chain to exercise the repair path"
    )
    assert len(pre["broken_links"]) >= 1
    assert len(pre["sequence_gaps"]) >= 1

    summary = restart_service.ensure_hash_chain()
    assert summary["chain_valid"], (
        f"repair failed: broken={len(summary['broken_links'])}, "
        f"gaps={len(summary['sequence_gaps'])}"
    )
    assert summary["total_entries"] == 10
    assert summary["repaired_entries"] >= 1

    # Verify sequence numbers are contiguous 1..10 and previous_hash links match.
    sorted_entries = sorted(
        restart_memory.values(), key=lambda e: int(e["sequence_no"])
    )
    assert [e["sequence_no"] for e in sorted_entries] == list(range(1, 11))
    previous_hash = ""
    for entry in sorted_entries:
        assert entry["previous_hash"] == previous_hash
        expected = compute_entry_hash(entry, previous_hash)
        assert entry["entry_hash"] == expected
        previous_hash = entry["entry_hash"]


def test_ensure_hash_chain_is_idempotent_on_valid_chain(sqlite_ledger):
    """Running ensure_hash_chain() on an already-valid chain must not mutate
    any entry — important because the boot path now invokes it conditionally
    after hydration and we don't want spurious rewrites on healthy deploys."""
    from services.platform_event_ledger_service import reconcile_ledger_entries

    memory = {}
    service = _make_service(memory)
    seeded = _seed_sample_ledger(service, n_entries=6)
    expected_hashes = {e["id"]: e["entry_hash"] for e in seeded}
    expected_sequences = {e["id"]: e["sequence_no"] for e in seeded}

    summary = service.ensure_hash_chain()
    assert summary["chain_valid"]
    assert summary["repaired_entries"] == 0

    for entry_id, entry in memory.items():
        assert entry["entry_hash"] == expected_hashes[entry_id]
        assert entry["sequence_no"] == expected_sequences[entry_id]

    summary2 = reconcile_ledger_entries(memory.values())
    assert summary2["chain_valid"]
