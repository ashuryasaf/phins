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

_MODE_ENV = 'PHINS_FIDUCIARY_MODE'


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


def _db_manager():
    from database.manager import DatabaseManager
    return DatabaseManager()


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
        _merge(health_wallets, db.health_wallets.load_mapping(), 'health_wallets')
        _merge(wallet_withdrawals, db.wallet_withdrawals.load_mapping(), 'wallet_withdrawals')
        _merge(nft_ledger, db.nft_ledger.load_mapping(), 'nft_ledger')
        _merge(investment_accounts, db.investment_accounts.load_mapping(), 'investment_accounts')
        sheet = db.balance_sheet.get_phins()
        if sheet is not None and isinstance(sheet, dict):
            if prefer_db or not balance_sheet:
                balance_sheet.clear()
                balance_sheet.update(sheet)
                counts['balance_sheet'] = 1
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
    """Dual/db write path: seal every live fiduciary dict into its table."""
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
        result['health_wallets'] = db.health_wallets.replace_mapping(dict(health_wallets))
        result['wallet_withdrawals'] = db.wallet_withdrawals.replace_mapping(
            dict(wallet_withdrawals), customer_from='customer_id'
        )
        result['nft_ledger'] = db.nft_ledger.replace_mapping(
            dict(nft_ledger), customer_from='customer_id'
        )
        result['investment_accounts'] = db.investment_accounts.replace_mapping(
            dict(investment_accounts)
        )
        if balance_sheet:
            ok = db.balance_sheet.upsert_phins(dict(balance_sheet))
            result['balance_sheet'] = {'written': 1 if ok else 0, 'withheld': 0 if ok else 1}
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
