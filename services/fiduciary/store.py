"""Read/write bridge between in-memory fiduciary dicts and sealed tables."""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Mapping, MutableMapping, Optional

from services.hydrated_store import db_mode_enabled

logger = logging.getLogger(__name__)

# Snapshot file / agent_artifacts keys that U2 moves into fiduciary tables.
FIDUCIARY_SNAPSHOT_KEYS = (
    'health_wallets',
    'wallet_withdrawals',
    'nft_ledger',
    'investment_accounts',
    'phins_balance_sheet',
)

# Stamped on the JSON ledger file when fiduciary books are empty placeholders
# (db-authoritative mode). Dual boot uses this to hydrate sealed tables
# instead of treating those empties as a file-SoR purge.
FIDUCIARY_BOOKS_MARKER = 'fiduciary_books'
FIDUCIARY_BOOKS_DB = 'db'

_MODE_ENV = 'PHINS_FIDUCIARY_MODE'

# Process-local CAS baselines: sealed checksum last observed per book/id.
# Hydrate and successful flush refresh these; a flush passes them as
# expected_checksum so peer updates are withheld rather than reverted.
_FIDUCIARY_BASELINE: Dict[str, Dict[str, str]] = {
    'health_wallets': {},
    'wallet_withdrawals': {},
    'nft_ledger': {},
    'investment_accounts': {},
    'balance_sheet': {},
}


class FiduciaryBootError(RuntimeError):
    """Fatal fiduciary migrate/hydrate failure in ``db`` mode (abort boot)."""


def fiduciary_mode(environ: Optional[Mapping[str, str]] = None) -> str:
    """Return ``off``, ``dual``, or ``db``.

    * ``off`` — memory + JSON snapshot only (tests / no database).
    * ``dual`` — DB tables are written on every save; boot inserts missing
      snapshot ids into sealed tables then fills memory gaps (default when
      the DB is up). Prefer-DB hydrate only when no snapshot was applied
      (AE2 volume-less restore).
    * ``db`` — DB is authoritative; snapshot omits fiduciary keys; hydrate
      prefers sealed rows; a failed flush fails the ledger save.
    """
    env = environ if environ is not None else os.environ
    raw = str(env.get(_MODE_ENV) or '').strip().lower()
    if raw in ('off', 'dual', 'db', 'database', 'authoritative'):
        if raw in ('database', 'authoritative'):
            return 'db'
        return raw
    return 'dual' if db_mode_enabled() else 'off'


def omit_fiduciary_from_snapshot(environ: Optional[Mapping[str, str]] = None) -> bool:
    """True when the ledger snapshot must drop fiduciary keys."""
    return fiduciary_mode(environ) == 'db'


def reset_fiduciary_baseline() -> None:
    """Clear CAS baselines (tests / process isolation)."""
    for book in _FIDUCIARY_BASELINE:
        _FIDUCIARY_BASELINE[book] = {}


def fiduciary_baseline(book: str) -> Dict[str, str]:
    """Copy of the process CAS baseline for ``book`` (tests / diagnostics)."""
    return dict(_FIDUCIARY_BASELINE.get(book) or {})


def _db_manager():
    from database.manager import DatabaseManager
    return DatabaseManager()


def _set_baseline(book: str, checksums: Mapping[str, str]) -> None:
    _FIDUCIARY_BASELINE[book] = {str(k): str(v) for k, v in checksums.items()}


def capture_fiduciary_baseline_from_db() -> Dict[str, int]:
    """Record sealed checksums without merging payloads into memory.

    Call on dual file-SoR boot paths that skip hydrate so a later mutation
    flush still CAS-withholds peer updates.
    """
    mode = fiduciary_mode()
    if mode == 'off':
        return {'mode': 0}
    counts = {
        'health_wallets': 0,
        'wallet_withdrawals': 0,
        'nft_ledger': 0,
        'investment_accounts': 0,
        'balance_sheet': 0,
    }
    try:
        db = _db_manager()
    except Exception as exc:
        logger.error(
            "fiduciary baseline capture: cannot open DB: %s", type(exc).__name__
        )
        raise
    try:
        for label, repo in (
            ('health_wallets', db.health_wallets),
            ('wallet_withdrawals', db.wallet_withdrawals),
            ('nft_ledger', db.nft_ledger),
            ('investment_accounts', db.investment_accounts),
        ):
            checksums = repo.load_checksums()
            _set_baseline(label, checksums)
            counts[label] = len(checksums)
        sheet_cs = db.balance_sheet.load_checksums()
        _set_baseline('balance_sheet', sheet_cs)
        counts['balance_sheet'] = len(sheet_cs)
    except Exception as exc:
        logger.error(
            "fiduciary baseline capture failed: %s", type(exc).__name__
        )
        raise
    finally:
        try:
            db.close()
        except Exception:
            pass
    return counts


def hydrate_fiduciary_from_db(
    *,
    health_wallets: MutableMapping[str, Any],
    wallet_withdrawals: MutableMapping[str, Any],
    nft_ledger: MutableMapping[str, Any],
    investment_accounts: MutableMapping[str, Any],
    balance_sheet: MutableMapping[str, Any],
    prefer_db: bool = True,
) -> Dict[str, int]:
    """Load sealed tables into the live dicts.

    When ``prefer_db`` is True (dual/db), an intact DB row replaces the
    in-memory value for that key. When False, DB only fills missing keys.
    Always refreshes the process CAS baseline from intact sealed checksums.
    """
    mode = fiduciary_mode()
    if mode == 'off':
        return {'mode': 0}
    counts = {
        'health_wallets': 0,
        'wallet_withdrawals': 0,
        'nft_ledger': 0,
        'investment_accounts': 0,
        'balance_sheet': 0,
        'withheld': 0,
    }
    try:
        db = _db_manager()
    except Exception as exc:
        logger.error("fiduciary hydrate: cannot open DB: %s", type(exc).__name__)
        # Propagate so db-mode boot can abort; dual callers catch and soft-log.
        raise

    def _merge(target: MutableMapping[str, Any], loaded: Dict[str, Any], label: str) -> None:
        for key, payload in loaded.items():
            if prefer_db or key not in target:
                target[key] = payload
                counts[label] += 1

    try:
        hw = db.health_wallets.load_mapping()
        _merge(health_wallets, hw, 'health_wallets')
        _set_baseline('health_wallets', db.health_wallets.load_checksums())

        ww = db.wallet_withdrawals.load_mapping()
        _merge(wallet_withdrawals, ww, 'wallet_withdrawals')
        _set_baseline('wallet_withdrawals', db.wallet_withdrawals.load_checksums())

        nft = db.nft_ledger.load_mapping()
        _merge(nft_ledger, nft, 'nft_ledger')
        _set_baseline('nft_ledger', db.nft_ledger.load_checksums())

        inv = db.investment_accounts.load_mapping()
        _merge(investment_accounts, inv, 'investment_accounts')
        _set_baseline('investment_accounts', db.investment_accounts.load_checksums())

        sheet = db.balance_sheet.get_phins()
        if sheet is not None and isinstance(sheet, dict):
            if prefer_db or not balance_sheet:
                balance_sheet.clear()
                balance_sheet.update(sheet)
                counts['balance_sheet'] = 1
        _set_baseline('balance_sheet', db.balance_sheet.load_checksums())
    except Exception as exc:
        logger.error("fiduciary hydrate failed: %s", type(exc).__name__)
        raise
    finally:
        try:
            db.close()
        except Exception:
            pass
    return counts


def flush_fiduciary_to_db(
    *,
    health_wallets: Mapping[str, Any],
    wallet_withdrawals: Mapping[str, Any],
    nft_ledger: Mapping[str, Any],
    investment_accounts: Mapping[str, Any],
    balance_sheet: Mapping[str, Any],
) -> Dict[str, Any]:
    """Dual/db write path: seal every live fiduciary dict into its table.

    Passes the process CAS baseline as ``expected_checksum`` so a multi-writer
    flush withholds ids another process updated since this one last
    hydrated/flushed, instead of reverting them.
    """
    mode = fiduciary_mode()
    if mode == 'off':
        return {'mode': 'off'}
    try:
        db = _db_manager()
    except Exception as exc:
        logger.error("fiduciary flush: cannot open DB: %s", type(exc).__name__)
        return {'mode': mode, 'error': type(exc).__name__}

    result: Dict[str, Any] = {'mode': mode}
    try:
        from database.repositories.fiduciary_repository import BALANCE_SHEET_ID

        # Per-book: skip empty process dicts over non-empty sealed tables
        # without aborting the rest of the flush (one purged NFT book must
        # not block wallet dual-writes).
        def _write_or_skip(
            label: str,
            mapping: Mapping[str, Any],
            repo: Any,
            *,
            customer_from: Optional[str] = None,
        ) -> None:
            if not mapping and repo.count_rows() > 0:
                logger.error(
                    "fiduciary flush skipped empty overwrite of %s (%s sealed rows)",
                    label,
                    repo.count_rows(),
                )
                result[label] = {
                    'written': 0,
                    'withheld': 0,
                    'errors': 0,
                    'skipped': 'refuse_empty_overwrite',
                }
                return
            expected = _FIDUCIARY_BASELINE.get(label) or {}
            kwargs: Dict[str, Any] = {'expected_checksums': expected}
            if customer_from:
                kwargs['customer_from'] = customer_from
            counts = repo.replace_mapping(dict(mapping), **kwargs)
            result[label] = counts
            # Sealed table is source of truth for the next CAS baseline
            # (our writes and peer wins both land here).
            try:
                _set_baseline(label, repo.load_checksums())
            except Exception:
                pass

        _write_or_skip('health_wallets', health_wallets, db.health_wallets)
        _write_or_skip(
            'wallet_withdrawals',
            wallet_withdrawals,
            db.wallet_withdrawals,
            customer_from='customer_id',
        )
        _write_or_skip(
            'nft_ledger', nft_ledger, db.nft_ledger, customer_from='customer_id'
        )
        _write_or_skip('investment_accounts', investment_accounts, db.investment_accounts)
        if balance_sheet:
            expected_sheet = (_FIDUCIARY_BASELINE.get('balance_sheet') or {}).get(
                BALANCE_SHEET_ID
            )
            ok = db.balance_sheet.upsert_phins(
                dict(balance_sheet), expected_checksum=expected_sheet
            )
            result['balance_sheet'] = {
                'written': 1 if ok else 0,
                'withheld': 0 if ok else 1,
            }
            try:
                _set_baseline('balance_sheet', db.balance_sheet.load_checksums())
            except Exception:
                pass
        else:
            result['balance_sheet'] = {'written': 0, 'withheld': 0}
    except Exception as exc:
        logger.error("fiduciary flush failed: %s", type(exc).__name__)
        result['error'] = type(exc).__name__
    finally:
        try:
            db.close()
        except Exception:
            pass
    return result
