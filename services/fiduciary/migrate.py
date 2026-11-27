"""One-shot journal-first migration of snapshot fiduciary keys → tables."""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime
from typing import Any, Callable, Dict, Mapping, Optional

from services.fiduciary.store import FIDUCIARY_SNAPSHOT_KEYS, fiduciary_mode

logger = logging.getLogger(__name__)

MIGRATION_EVENT = 'fiduciary.tables_migrated'
MIGRATION_ENTITY = 'fiduciary_store'
MIGRATION_ENTITY_ID = 'fiduciary-u2-v1'


def _fingerprint(snapshot: Mapping[str, Any]) -> str:
    subset = {k: snapshot.get(k) for k in FIDUCIARY_SNAPSHOT_KEYS}
    text = json.dumps(subset, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def _table_row_counts(db: Any) -> Dict[str, int]:
    return {
        'health_wallets': db.health_wallets.count_rows(),
        'wallet_withdrawals': db.wallet_withdrawals.count_rows(),
        'nft_ledger': db.nft_ledger.count_rows(),
        'investment_accounts': db.investment_accounts.count_rows(),
        'balance_sheet': db.balance_sheet.count_rows(),
    }


def _repo_for_key(db: Any, key: str) -> Any:
    return {
        'health_wallets': db.health_wallets,
        'wallet_withdrawals': db.wallet_withdrawals,
        'nft_ledger': db.nft_ledger,
        'investment_accounts': db.investment_accounts,
        'phins_balance_sheet': db.balance_sheet,
    }[key]


def _keys_needing_migrate(
    db: Any,
    snapshot: Mapping[str, Any],
    *,
    force: bool,
) -> Dict[str, Any]:
    """Return snapshot keys that still need rows (or every key when force).

    A half-finished migrate may leave *some* wallet ids in the table. The next
    boot must still insert the missing ids — never treat ``count_rows() > 0``
    as "this book is done".
    """
    pending: Dict[str, Any] = {}
    for key in FIDUCIARY_SNAPSHOT_KEYS:
        value = snapshot.get(key)
        if not value or not isinstance(value, dict):
            continue
        if force:
            pending[key] = value
            continue
        if key == 'phins_balance_sheet':
            if db.balance_sheet.count_rows() == 0:
                pending[key] = value
            continue
        missing = _repo_for_key(db, key).missing_ids(value)
        if missing:
            pending[key] = value
    return pending


def _write_key(
    db: Any,
    key: str,
    mapping: Dict[str, Any],
    *,
    force: bool,
) -> Dict[str, int]:
    from database.repositories.fiduciary_repository import BALANCE_SHEET_ID

    repo = _repo_for_key(db, key)
    customer_from = 'customer_id' if key in ('wallet_withdrawals', 'nft_ledger') else None
    if key == 'phins_balance_sheet':
        # Insert when empty (no token). Force overwrite presents the current
        # sealed digest as expected_checksum so CAS still applies.
        expected = None
        if force and db.balance_sheet.count_rows() > 0:
            expected = db.balance_sheet.load_checksums().get(BALANCE_SHEET_ID)
        ok = db.balance_sheet.upsert_phins(mapping, expected_checksum=expected)
        return {'written': 1 if ok else 0, 'withheld': 0 if ok else 1, 'errors': 0}
    if force:
        # Intentional replace: CAS against seals observed at migrate start.
        expected = repo.load_checksums()
        return repo.replace_mapping(
            mapping,
            customer_from=customer_from,
            expected_checksums=expected,
        )
    return repo.fill_missing_mapping(mapping, customer_from=customer_from)


def migrate_snapshot_to_fiduciary_tables(
    snapshot: Mapping[str, Any],
    *,
    append_event: Optional[Callable[..., Any]] = None,
    force: bool = False,
) -> Dict[str, Any]:
    """Copy fiduciary keys from a ledger snapshot into sealed tables.

    Writes a platform-ledger before/after event **before** any table upsert
    when ``append_event`` is supplied (fail closed on journal failure). Default
    path only inserts missing record ids (and empty balance-sheet); ``force``
    replaces intact rows. A half-written book resumes on the next boot.
    """
    mode = fiduciary_mode()
    result: Dict[str, Any] = {
        'migrated': False,
        'mode': mode,
        'reason': None,
        'fingerprint': None,
        'counts': {},
    }
    if mode == 'off':
        result['reason'] = 'fiduciary_mode_off'
        return result
    if not isinstance(snapshot, Mapping):
        result['reason'] = 'invalid_snapshot'
        return result

    present = {k: snapshot.get(k) for k in FIDUCIARY_SNAPSHOT_KEYS if snapshot.get(k)}
    if not present:
        result['reason'] = 'no_fiduciary_keys'
        return result

    fingerprint = _fingerprint(snapshot)
    result['fingerprint'] = fingerprint

    from database.manager import DatabaseManager

    db = DatabaseManager()
    journaled = False
    try:
        before = _table_row_counts(db)
        subset = _keys_needing_migrate(db, snapshot, force=force)
        if not subset:
            result['reason'] = 'tables_already_populated'
            return result

        journal_payload = {
            'schema': 'phins.fiduciary.migration.v1',
            'fingerprint': fingerprint,
            'before': before,
            'keys': sorted(subset.keys()),
            'force': force,
            'started_at': datetime.utcnow().isoformat(),
        }

        if append_event is not None:
            # Forensic journal first — refuse the migrate if the chain cannot
            # accept the before record (propagate; do not soft-return).
            append_event(
                event_type=MIGRATION_EVENT,
                entity_type=MIGRATION_ENTITY,
                entity_id=f'{MIGRATION_ENTITY_ID}-before-{fingerprint[:16]}',
                actor='system_fiduciary_migrate',
                status='started',
                payload=journal_payload,
            )
            journaled = True

        try:
            counts: Dict[str, Any] = {}
            for key, mapping in subset.items():
                label = 'balance_sheet' if key == 'phins_balance_sheet' else key
                counts[label] = _write_key(db, key, mapping, force=force)
        except Exception as exc:
            # Rows already committed stay; fill_missing resumes next boot.
            logger.error(
                "fiduciary migration copy failed: %s", type(exc).__name__
            )
            result['reason'] = f'error:{type(exc).__name__}'
            result['migrated'] = False
            result['keys'] = sorted(subset.keys())
            return result

        result['counts'] = counts
        result['keys'] = sorted(subset.keys())
        # fill_missing / replace_mapping swallow per-row failures into
        # errors/withheld — treat those as an incomplete migrate, not ok.
        row_failures = {
            label: block
            for label, block in counts.items()
            if isinstance(block, dict)
            and (
                int(block.get('errors') or 0) > 0
                or int(block.get('withheld') or 0) > 0
            )
        }
        if row_failures:
            logger.error("fiduciary migration row failures: %s", row_failures)
            result['reason'] = 'error:row_errors'
            result['migrated'] = False
            result['after'] = _table_row_counts(db)
            if append_event is not None:
                append_event(
                    event_type=MIGRATION_EVENT,
                    entity_type=MIGRATION_ENTITY,
                    entity_id=f'{MIGRATION_ENTITY_ID}-failed-{fingerprint[:16]}',
                    actor='system_fiduciary_migrate',
                    status='failed',
                    payload={
                        'schema': 'phins.fiduciary.migration.v1',
                        'fingerprint': fingerprint,
                        'before': before,
                        'after': result['after'],
                        'counts': counts,
                        'row_failures': row_failures,
                        'keys': sorted(subset.keys()),
                        'force': force,
                        'failed_at': datetime.utcnow().isoformat(),
                    },
                )
            return result

        after = _table_row_counts(db)
        result['after'] = after
        result['migrated'] = True
        result['reason'] = 'ok'

        if append_event is not None:
            append_event(
                event_type=MIGRATION_EVENT,
                entity_type=MIGRATION_ENTITY,
                entity_id=f'{MIGRATION_ENTITY_ID}-after-{fingerprint[:16]}',
                actor='system_fiduciary_migrate',
                status='completed',
                payload={
                    'schema': 'phins.fiduciary.migration.v1',
                    'fingerprint': fingerprint,
                    'before': before,
                    'after': after,
                    'counts': counts,
                    'keys': sorted(subset.keys()),
                    'force': force,
                    'completed_at': datetime.utcnow().isoformat(),
                },
            )
        return result
    except Exception as exc:
        # Journal failure (or unexpected setup error) must not look like a
        # soft skip — callers in db mode fail closed on this raise.
        if not journaled:
            logger.error(
                "fiduciary migration refused (journal/setup): %s",
                type(exc).__name__,
            )
            raise
        logger.error(
            "fiduciary migration failed after journal: %s", type(exc).__name__
        )
        result['reason'] = f'error:{type(exc).__name__}'
        result['migrated'] = False
        return result
    finally:
        try:
            db.close()
        except Exception:
            pass
