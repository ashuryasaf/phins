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


def _tamper_db_rows(break_at_index=4, shift_from_index=5, shift_by=100):
    """Reproduce the production drift pattern directly in the DB layer:
    rewrite one row's hashes to bogus values and shift later sequence_nos."""
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
        bad_prev = "0" * 64
        bad_hash = "f" * 64
        target = rows[break_at_index]
        target.previous_hash = bad_prev
        target.entry_hash = bad_hash
        try:
            payload_obj = _json.loads(target.payload) if target.payload else {}
        except Exception:
            payload_obj = {}
        if isinstance(payload_obj, dict):
            payload_obj["previous_hash"] = bad_prev
            payload_obj["entry_hash"] = bad_hash
            target.payload = _json.dumps(payload_obj, sort_keys=True, default=str)

        for r in rows[shift_from_index:]:
            new_seq = r.sequence_no + shift_by
            r.sequence_no = new_seq
            try:
                payload_obj = _json.loads(r.payload) if r.payload else {}
            except Exception:
                payload_obj = {}
            if isinstance(payload_obj, dict):
                payload_obj["sequence_no"] = new_seq
                r.payload = _json.dumps(payload_obj, sort_keys=True, default=str)
        db.commit()


def test_persist_chain_to_db_reconciles_divergent_db_rows(sqlite_ledger, tmp_path):
    """After hydrate + ensure_hash_chain, persist_chain_to_db must write the
    repaired chain back to SQL so the NEXT restart hydrates a valid chain and
    the startup divergence warning does not recur."""
    from services.platform_event_ledger_service import reconcile_ledger_entries

    first_memory = {}
    first_service = _make_service(first_memory)
    _seed_sample_ledger(first_service, n_entries=10)
    _tamper_db_rows()

    restart_memory = {}
    restart_service = _make_service(restart_memory)
    assert restart_service.hydrate_from_db() == 10
    pre = reconcile_ledger_entries(restart_memory.values())
    assert not pre["chain_valid"]

    restart_service.ensure_hash_chain()
    backup_path = str(tmp_path / "chain_backup.json")
    summary = restart_service.persist_chain_to_db(backup_path=backup_path)

    assert summary["applied"], f"write-back refused: {summary['reason']}"
    assert summary["rows_updated"] >= 1
    assert summary["rows_inserted"] == 0
    assert summary["backup_path"] == backup_path
    assert Path(backup_path).exists()

    # Next "restart": a brand-new memory ledger hydrated from the reconciled
    # DB must validate cleanly with no repair pass at all.
    next_memory = {}
    next_service = _make_service(next_memory)
    assert next_service.hydrate_from_db() == 10
    post = reconcile_ledger_entries(next_memory.values())
    assert post["chain_valid"], (
        f"DB still divergent after write-back: "
        f"broken={len(post['broken_links'])}, gaps={len(post['sequence_gaps'])}"
    )
    for entry_id, entry in restart_memory.items():
        assert next_memory[entry_id]["entry_hash"] == entry["entry_hash"]
        assert next_memory[entry_id]["sequence_no"] == entry["sequence_no"]


def test_persist_chain_to_db_refuses_invalid_memory_chain(sqlite_ledger):
    """The write-back must never overwrite DB rows from a memory ledger that
    does not itself validate — a corrupted memory chain is not canonical."""
    from database.manager import DatabaseManager

    memory = {}
    service = _make_service(memory)
    seeded = _seed_sample_ledger(service, n_entries=5)
    db_hashes_before = {e["id"]: e["entry_hash"] for e in seeded}

    # Corrupt one in-memory entry so reconcile fails.
    memory[seeded[2]["id"]]["entry_hash"] = "deadbeef" * 8

    summary = service.persist_chain_to_db()
    assert not summary["applied"]
    assert "invalid" in summary["reason"]

    with DatabaseManager() as db:
        for entry_id, expected_hash in db_hashes_before.items():
            row = db.platform_ledger.get_by_id(entry_id)
            assert row is not None
            assert row.entry_hash == expected_hash, "DB row mutated despite refusal"


def test_persist_chain_to_db_inserts_memory_only_entries(sqlite_ledger):
    """Memory entries whose DB insert was lost (e.g. transient persistence
    failure) must be re-inserted so the persisted chain has no holes."""
    from database.manager import DatabaseManager
    from services.platform_event_ledger_service import reconcile_ledger_entries

    memory = {}
    service = _make_service(memory)
    seeded = _seed_sample_ledger(service, n_entries=3)
    missing_id = seeded[1]["id"]

    with DatabaseManager() as db:
        assert db.platform_ledger.delete(missing_id)

    summary = service.persist_chain_to_db()
    assert summary["applied"]
    assert summary["rows_inserted"] == 1
    assert summary["rows_updated"] == 0

    next_memory = {}
    next_service = _make_service(next_memory)
    assert next_service.hydrate_from_db() == 3
    post = reconcile_ledger_entries(next_memory.values())
    assert post["chain_valid"]
    assert next_memory[missing_id]["entry_hash"] == memory[missing_id]["entry_hash"]


def test_persist_chain_to_db_noop_when_already_consistent(sqlite_ledger, tmp_path):
    """On healthy deploys the write-back must not touch rows or emit backups —
    the boot path calls it on every start once auto-repair is enabled."""
    memory = {}
    service = _make_service(memory)
    _seed_sample_ledger(service, n_entries=4)

    backup_path = str(tmp_path / "should_not_exist.json")
    summary = service.persist_chain_to_db(backup_path=backup_path)

    assert not summary["applied"]
    assert summary["reason"] == "db chain already consistent"
    assert summary["rows_unchanged"] == 4
    assert not Path(backup_path).exists()


def test_ensure_hash_chain_repaired_count_is_accurate(sqlite_ledger):
    """repaired_entries must equal the number of entries whose chain fields
    actually changed (previously the comparison ran after mutation, leaving
    dead conditions and an under-counted startup log line)."""
    memory = {}
    service = _make_service(memory)
    _seed_sample_ledger(service, n_entries=10)
    _tamper_db_rows(break_at_index=5, shift_from_index=5, shift_by=100)

    restart_memory = {}
    restart_service = _make_service(restart_memory)
    assert restart_service.hydrate_from_db() == 10

    summary = restart_service.ensure_hash_chain()
    assert summary["chain_valid"]
    # Rows 1-5 were untouched and head the chain, so exactly the 5 shifted
    # rows need re-sequencing/re-hashing.
    assert summary["repaired_entries"] == 5


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


# ---------------------------------------------------------------------------
# Chain-repair auditability (F4)
# ---------------------------------------------------------------------------
# The boot path may rewrite sequence_no/previous_hash/entry_hash on existing
# platform_ledger_entries rows to heal divergence. Rewriting audit rows is only
# acceptable while the pre-repair state stays recoverable and the result is
# verified, so these tests pin the fail-closed journal and the post-write check.


def test_repair_refuses_without_a_backup_path(sqlite_ledger):
    """No forensic journal → no rewrite. The divergence is left for an operator."""
    from database.manager import DatabaseManager

    first_memory = {}
    _seed_sample_ledger(_make_service(first_memory), n_entries=6)
    _tamper_db_rows()

    with DatabaseManager() as db:
        before = {
            row.id: (row.sequence_no, row.previous_hash, row.entry_hash)
            for row in db.platform_ledger.get_all_by_sequence(limit=1000)
        }

    memory = {}
    service = _make_service(memory)
    assert service.hydrate_from_db() == 6
    service.ensure_hash_chain()

    summary = service.persist_chain_to_db()  # no backup_path
    assert summary["applied"] is False
    assert "forensic journal" in summary["reason"]

    with DatabaseManager() as db:
        for entry_id, expected in before.items():
            row = db.platform_ledger.get_by_id(entry_id)
            assert (row.sequence_no, row.previous_hash, row.entry_hash) == expected, (
                "audit row mutated without a journal"
            )


def test_repair_refuses_when_the_journal_cannot_be_written(sqlite_ledger, tmp_path):
    """An unwritable journal destination must abort the repair, not proceed."""
    from database.manager import DatabaseManager

    _seed_sample_ledger(_make_service({}), n_entries=6)
    _tamper_db_rows()

    with DatabaseManager() as db:
        before = {
            row.id: (row.sequence_no, row.entry_hash)
            for row in db.platform_ledger.get_all_by_sequence(limit=1000)
        }

    memory = {}
    service = _make_service(memory)
    service.hydrate_from_db()
    service.ensure_hash_chain()

    # A path whose parent is a regular file can never be created.
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("x", encoding="utf-8")
    summary = service.persist_chain_to_db(backup_path=str(blocker / "journal.json"))

    assert summary["applied"] is False
    assert "journal write failed" in summary["reason"]

    with DatabaseManager() as db:
        for entry_id, expected in before.items():
            row = db.platform_ledger.get_by_id(entry_id)
            assert (row.sequence_no, row.entry_hash) == expected, (
                "audit row mutated despite journal failure"
            )


def test_repair_may_proceed_without_journal_when_explicitly_allowed(sqlite_ledger):
    """The fail-closed default is overridable for deliberate operator use."""
    _seed_sample_ledger(_make_service({}), n_entries=5)
    _tamper_db_rows()

    memory = {}
    service = _make_service(memory)
    service.hydrate_from_db()
    service.ensure_hash_chain()

    summary = service.persist_chain_to_db(require_backup=False)
    assert summary["applied"] is True
    assert summary["rows_updated"] >= 1


def test_repair_journal_records_before_and_after(sqlite_ledger, tmp_path):
    """The journal must make the pre-repair chain reconstructible."""
    import json

    _seed_sample_ledger(_make_service({}), n_entries=8)
    _tamper_db_rows()

    memory = {}
    service = _make_service(memory)
    service.hydrate_from_db()
    service.ensure_hash_chain()

    journal_path = tmp_path / "nested" / "journal.json"  # parent auto-created
    summary = service.persist_chain_to_db(backup_path=str(journal_path))
    assert summary["applied"] is True
    assert journal_path.exists()

    journal = json.loads(journal_path.read_text(encoding="utf-8"))
    assert journal["schema"] == "phins.ledger.chain_repair.v2"
    assert journal["rows"], "journal recorded no changed rows"
    for row in journal["rows"]:
        assert {"id", "sequence_no", "previous_hash", "entry_hash", "replaced_by"} <= set(row)
        # The recorded original must differ from what replaced it, otherwise the
        # row should not have been in the update set at all.
        assert (
            row["sequence_no"],
            row["previous_hash"],
            row["entry_hash"],
        ) != (
            row["replaced_by"]["sequence_no"],
            row["replaced_by"]["previous_hash"],
            row["replaced_by"]["entry_hash"],
        )
    # The post-repair values in the journal match what is now in memory/DB.
    for row in journal["rows"]:
        assert memory[row["id"]]["entry_hash"] == row["replaced_by"]["entry_hash"]

    # No temp file is left behind by the atomic write.
    assert not (journal_path.parent / (journal_path.name + ".tmp")).exists()


def test_repair_reports_verification_success(sqlite_ledger, tmp_path):
    """A successful repair must be positively verified, not just committed."""
    _seed_sample_ledger(_make_service({}), n_entries=7)
    _tamper_db_rows()

    memory = {}
    service = _make_service(memory)
    service.hydrate_from_db()
    service.ensure_hash_chain()

    summary = service.persist_chain_to_db(backup_path=str(tmp_path / "j.json"))
    assert summary["applied"] is True
    assert summary["verified"] is True
    assert not summary.get("verification_mismatches")
    assert not summary.get("verification_missing")


def test_verification_detects_a_divergent_row(sqlite_ledger, tmp_path):
    """The verifier itself must catch a row that does not match memory."""
    from database.manager import DatabaseManager

    seeded = _seed_sample_ledger(_make_service({}), n_entries=4)

    memory = {}
    service = _make_service(memory)
    service.hydrate_from_db()

    with DatabaseManager() as db:
        row = db.platform_ledger.get_by_id(seeded[1]["id"])
        row.entry_hash = "b" * 64
        db.commit()
        result = service._verify_db_chain_matches_memory(db)

    assert result["verified"] is False
    assert seeded[1]["id"] in result["mismatches"]


def test_verification_detects_a_missing_row(sqlite_ledger):
    """A memory entry absent from SQL must fail verification."""
    from database.manager import DatabaseManager

    seeded = _seed_sample_ledger(_make_service({}), n_entries=4)

    memory = {}
    service = _make_service(memory)
    service.hydrate_from_db()

    with DatabaseManager() as db:
        assert db.platform_ledger.delete(seeded[2]["id"])
        db.commit()
        result = service._verify_db_chain_matches_memory(db)

    assert result["verified"] is False
    assert seeded[2]["id"] in result["missing"]
