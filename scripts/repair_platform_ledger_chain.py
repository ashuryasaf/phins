#!/usr/bin/env python3
"""
Operator-run repair tool for the platform event ledger hash chain.

Use this when the production deployment logs report something like::

    ⚠️  [INTEGRITY] Startup validation: 1 issue(s) detected
       ✗ Ledger chain invalid: 361 broken links, 1168 sequence gaps, 0 duplicates

The web_portal boot path already repairs the *in-memory* chain after
``hydrate_from_db()``, so the running server is unaffected. But the rows in
``platform_ledger_entries`` still carry the divergent ``previous_hash`` /
``entry_hash`` / ``sequence_no`` values that were written during older
deployments. This script reconciles the DB rows to match the canonical
recomputed chain so a future BI/actuarial run that queries the DB
directly sees a fully consistent history.

Safety:
  * Dry-run by default — pass ``--apply`` to actually mutate rows.
  * Writes a JSON snapshot of every row before mutating (``--backup
    PATH``) so the previous state can be restored manually if needed.
  * Operates row-by-row inside a single SQLAlchemy session; on failure
    the session is rolled back and the DB is left untouched.

Usage::

    python scripts/repair_platform_ledger_chain.py                    # dry run
    python scripts/repair_platform_ledger_chain.py --apply
    python scripts/repair_platform_ledger_chain.py --apply --backup ledger_backup.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from typing import Any, Dict, List

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)


def _row_to_entry_dict(row: Any) -> Dict[str, Any]:
    """Convert a ``PlatformLedgerEntry`` row back into the entry shape that
    was originally hashed at write time.

    At write time the service stores the entire entry as the ``payload``
    column (see ``PlatformEventLedgerService._persist_entry``). Reconstructing
    the entry by reading column-by-column would produce a nested
    ``{... , payload: {full_entry}}`` structure that was never part of the
    canonical payload — so its recomputed hash would never match the one
    written to ``entry_hash``. To stay byte-identical with the original
    hash inputs we:

      1. Prefer the parsed ``payload`` blob as the entry body.
      2. Fall back to the indexed columns only for fields that the payload
         doesn't already provide (e.g. older entries written without a
         self-referential ``id`` inside payload).
    """
    raw_dict: Dict[str, Any] = {}
    if hasattr(row, "to_dict"):
        try:
            raw_dict = dict(row.to_dict())
        except Exception:
            raw_dict = {}
    if not raw_dict:
        raw_dict = {
            col.name: getattr(row, col.name, None)
            for col in row.__table__.columns  # type: ignore[attr-defined]
        }

    entry_id = raw_dict.get("id") or getattr(row, "id", None)
    payload = raw_dict.get("payload")
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except Exception:
            payload = None

    if isinstance(payload, dict) and payload.get("id") == entry_id:
        merged: Dict[str, Any] = dict(payload)
    else:
        merged = {}

    for column in (
        "id",
        "sequence_no",
        "ledger_type",
        "event_type",
        "entity_type",
        "entity_id",
        "customer_id",
        "actor",
        "amount",
        "currency",
        "status",
        "source_system",
        "previous_hash",
        "entry_hash",
        "timestamp",
    ):
        value = raw_dict.get(column)
        if value is not None and merged.get(column) in (None, ""):
            merged[column] = value

    return merged


def _serialize_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (dict, list, str, int, float, bool)) or value is None:
        return value
    return str(value)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Persist the recomputed chain back to platform_ledger_entries. "
        "Without this flag the script only prints the divergence summary.",
    )
    parser.add_argument(
        "--backup",
        default=None,
        help="Write a JSON snapshot of every row to PATH before mutating. "
        "Recommended when --apply is set.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=100000,
        help="Maximum number of rows to load (default: 100000)",
    )
    args = parser.parse_args()

    from database.manager import DatabaseManager
    from database.models import PlatformLedgerEntry
    from services.platform_event_ledger_service import (
        compute_entry_hash,
        normalize_ledger_entry,
        reconcile_ledger_entries,
        sort_ledger_entries,
        LEDGER_VERSION,
    )

    with DatabaseManager() as db:
        rows: List[PlatformLedgerEntry] = (
            db.platform_ledger.get_all_by_sequence(limit=args.limit)
        )
        if not rows:
            print("No platform_ledger_entries rows found — nothing to do.")
            return 0

        row_dicts = [_row_to_entry_dict(r) for r in rows]
        pre = reconcile_ledger_entries(row_dicts)
        print(
            f"Loaded {len(rows)} ledger rows. "
            f"chain_valid={pre['chain_valid']}, "
            f"broken_links={len(pre['broken_links'])}, "
            f"sequence_gaps={len(pre['sequence_gaps'])}, "
            f"duplicates={len(pre['duplicate_ids'])}, "
            f"missing_hash={len(pre['missing_hash_ids'])}"
        )

        if pre["chain_valid"]:
            print("Chain is already valid — nothing to repair.")
            return 0

        if args.backup:
            snapshot = [
                {
                    col.name: _serialize_value(getattr(r, col.name, None))
                    for col in PlatformLedgerEntry.__table__.columns
                }
                for r in rows
            ]
            with open(args.backup, "w", encoding="utf-8") as fh:
                json.dump(snapshot, fh, indent=2, default=str)
            print(f"Backup written: {args.backup} ({len(snapshot)} rows)")

        sorted_entries = sort_ledger_entries(row_dicts)
        previous_hash = ""
        repaired: List[Dict[str, Any]] = []
        for sequence_no, entry in enumerate(sorted_entries, start=1):
            normalized = normalize_ledger_entry(entry)
            original_sequence_no = normalized.get("sequence_no")
            original_entry_hash = normalized.get("entry_hash")
            normalized["sequence_no"] = sequence_no
            normalized["previous_hash"] = previous_hash
            normalized["ledger_version"] = LEDGER_VERSION
            new_hash = compute_entry_hash(normalized, previous_hash)
            normalized["entry_hash"] = new_hash
            normalized["original_sequence_no"] = original_sequence_no
            normalized["original_entry_hash"] = original_entry_hash
            repaired.append(normalized)
            previous_hash = new_hash

        post = reconcile_ledger_entries([
            {k: v for k, v in entry.items() if not k.startswith("original_")}
            for entry in repaired
        ])
        if not post["chain_valid"]:
            print(
                "ERROR: recomputed chain still reports "
                f"{len(post['broken_links'])} broken links — refusing to apply."
            )
            return 2

        print(
            f"Recomputed chain would re-sequence "
            f"{sum(1 for r in repaired if r['sequence_no'] != r.get('original_sequence_no', r['sequence_no']))} "
            f"rows and update {sum(1 for r in repaired if r['entry_hash'] != r.get('original_entry_hash'))} hashes."
        )

        if not args.apply:
            print("Dry run complete. Pass --apply to persist changes.")
            return 0

        id_to_row = {r.id: r for r in rows}
        for entry in repaired:
            row = id_to_row.get(entry["id"])
            if row is None:
                continue
            row.sequence_no = entry["sequence_no"]
            row.previous_hash = entry["previous_hash"]
            row.entry_hash = entry["entry_hash"]
            # Refresh the payload column so it matches the new chain state.
            persist = {k: v for k, v in entry.items() if not k.startswith("original_")}
            row.payload = json.dumps(persist, sort_keys=True, default=str)

        try:
            db.commit()
        except Exception as exc:
            db.rollback()
            print(f"ERROR: commit failed, rolled back: {exc}")
            return 3

    print(f"Repair complete: {len(repaired)} rows updated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
