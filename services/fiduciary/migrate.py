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


# Snapshot key → (table label used in before/after counts, emptiness predicate).
_TABLE_FOR_KEY = {
    'health_wallets': 'health_wallets',
    'wallet_withdrawals': 'wallet_withdrawals',
    'nft_ledger': 'nft_ledger',
    'investment_accounts': 'investment_accounts',
    'phins_balance_sheet': 'balance_sheet',
}


def _table_row_counts(db: Any) -> Dict[str, int]:
    return {
        'health_wallets': db.health_wallets.count_rows(),
        'wallet_withdrawals': db.wallet_withdrawals.count_rows(),
        'nft_ledger': db.nft_ledger.count_rows(),
        'investment_accounts': db.investment_accounts.count_rows(),
        'balance_sheet': db.balance_sheet.count_rows(),
    }


def _keys_needing_migrate(
    snapshot: Mapping[str, Any],
    counts: Mapping[str, int],
    *,
    force: bool,
) -> Dict[str, Any]:
    """Return snapshot subset for empty tables (or every present key when force).

    A half-finished first boot leaves some tables populated and others empty.
    The next boot must still migrate the empty ones — never skip the whole
    migrate just because *any* fiduciary table already has rows.
    """
    pending: Dict[str, Any] = {}
    for key in FIDUCIARY_SNAPSHOT_KEYS:
        value = snapshot.get(key)
        if not value or not isinstance(value, dict):
            continue
        table = _TABLE_FOR_KEY[key]
        if force or counts.get(table, 0) == 0:
            pending[key] = value
    return pending


def migrate_snapshot_to_fiduciary_tables(
    snapshot: Mapping[str, Any],
    *,
    append_event: Optional[Callable[..., Any]] = None,
    force: bool = False,
) -> Dict[str, Any]:
    """Copy fiduciary keys from a ledger snapshot into sealed tables.

    Writes a platform-ledger before/after event **before** any table upsert
    when ``append_event`` is supplied (fail closed on journal failure). Only
    empty tables are filled unless ``force`` is True; populated tables are
    left alone so a partial migrate can finish on the next boot.
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
    try:
        before = _table_row_counts(db)
        subset = _keys_needing_migrate(snapshot, before, force=force)
        if not subset:
            result['reason'] = 'tables_already_populated'
            return result

        journal_payload = {
            'schema': 'phins.fiduciary.migration.v1',
            'fingerprint': fingerprint,
            'before': before,
            'keys': sorted(subset.keys()),
            'started_at': datetime.utcnow().isoformat(),
        }

        if append_event is not None:
            # Forensic journal first — refuse the migrate if the chain cannot
            # accept the before record.
            append_event(
                event_type=MIGRATION_EVENT,
                entity_type=MIGRATION_ENTITY,
                entity_id=f'{MIGRATION_ENTITY_ID}-before-{fingerprint[:16]}',
                actor='system_fiduciary_migrate',
                status='started',
                payload=journal_payload,
            )

        counts: Dict[str, Any] = {}
        if 'health_wallets' in subset:
            counts['health_wallets'] = db.health_wallets.replace_mapping(subset['health_wallets'])
        if 'wallet_withdrawals' in subset:
            counts['wallet_withdrawals'] = db.wallet_withdrawals.replace_mapping(
                subset['wallet_withdrawals'], customer_from='customer_id'
            )
        if 'nft_ledger' in subset:
            counts['nft_ledger'] = db.nft_ledger.replace_mapping(
                subset['nft_ledger'], customer_from='customer_id'
            )
        if 'investment_accounts' in subset:
            counts['investment_accounts'] = db.investment_accounts.replace_mapping(
                subset['investment_accounts']
            )
        if 'phins_balance_sheet' in subset:
            ok = db.balance_sheet.upsert_phins(subset['phins_balance_sheet'])
            counts['balance_sheet'] = {'written': 1 if ok else 0, 'withheld': 0 if ok else 1}

        after = _table_row_counts(db)
        result['counts'] = counts
        result['after'] = after
        result['keys'] = sorted(subset.keys())
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
                    'completed_at': datetime.utcnow().isoformat(),
                },
            )
        return result
    except Exception as exc:
        logger.error("fiduciary migration failed: %s", exc)
        result['reason'] = f'error:{type(exc).__name__}'
        result['migrated'] = False
        return result
    finally:
        try:
            db.close()
        except Exception:
            pass
