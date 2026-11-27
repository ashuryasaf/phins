"""Read/write bridge between in-memory fiduciary dicts and sealed tables."""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Iterable, Mapping, MutableMapping, Optional

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


def capture_fiduciary_baseline_from_memory(
    *,
    health_wallets: Mapping[str, Any],
    wallet_withdrawals: Mapping[str, Any],
    nft_ledger: Mapping[str, Any],
    investment_accounts: Mapping[str, Any],
    balance_sheet: Mapping[str, Any],
) -> Dict[str, int]:
    """Stamp CAS baselines from digests of the live books (tests / diagnostics)."""
    from database.repositories.fiduciary_repository import (
        BALANCE_SHEET_ID,
        canonical_payload,
    )

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

    def _from_mapping(label: str, mapping: Mapping[str, Any]) -> None:
        checksums: Dict[str, str] = {}
        for key, payload in (mapping or {}).items():
            if not key:
                continue
            _, digest = canonical_payload(payload)
            checksums[str(key)] = digest
        _set_baseline(label, checksums)
        counts[label] = len(checksums)

    _from_mapping('health_wallets', health_wallets)
    _from_mapping('wallet_withdrawals', wallet_withdrawals)
    _from_mapping('nft_ledger', nft_ledger)
    _from_mapping('investment_accounts', investment_accounts)
    if balance_sheet:
        _, digest = canonical_payload(dict(balance_sheet))
        _set_baseline('balance_sheet', {BALANCE_SHEET_ID: digest})
        counts['balance_sheet'] = 1
    else:
        _set_baseline('balance_sheet', {})
    return counts


def capture_fiduciary_baseline_from_db() -> Dict[str, int]:
    """Record sealed checksums without merging payloads into memory."""
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
    preserve_absent: bool = False,
) -> Dict[str, int]:
    """Load sealed tables into the live dicts.

    When ``prefer_db`` is True, an intact DB row replaces the in-memory value
    for that key. When False, DB only fills missing keys.

    ``preserve_absent`` (dual volume boot): never add sealed-only ids, so a
    file purge stays gone, but ids present in both still prefer the sealed
    payload on conflict. That is multi-writer safe without authorizing a
    lagging volume book to overwrite a newer peer seal.

    Baseline covers only ids left in memory (sealed digest when present,
    otherwise the live payload digest).
    """
    from database.repositories.fiduciary_repository import (
        BALANCE_SHEET_ID,
        canonical_payload,
    )

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

    def _merge(
        target: MutableMapping[str, Any],
        loaded: Dict[str, Any],
        label: str,
        sealed_cs: Dict[str, str],
    ) -> None:
        for key, payload in loaded.items():
            if key in target:
                if prefer_db:
                    target[key] = payload
                    counts[label] += 1
            elif not preserve_absent and (prefer_db or key not in target):
                target[key] = payload
                counts[label] += 1
        baseline: Dict[str, str] = {}
        for key, payload in target.items():
            record_id = str(key)
            if record_id in sealed_cs:
                baseline[record_id] = sealed_cs[record_id]
            else:
                _, digest = canonical_payload(payload)
                baseline[record_id] = digest
        _set_baseline(label, baseline)

    try:
        hw_cs = db.health_wallets.load_checksums()
        _merge(health_wallets, db.health_wallets.load_mapping(), 'health_wallets', hw_cs)

        ww_cs = db.wallet_withdrawals.load_checksums()
        _merge(
            wallet_withdrawals,
            db.wallet_withdrawals.load_mapping(),
            'wallet_withdrawals',
            ww_cs,
        )

        nft_cs = db.nft_ledger.load_checksums()
        _merge(nft_ledger, db.nft_ledger.load_mapping(), 'nft_ledger', nft_cs)

        inv_cs = db.investment_accounts.load_checksums()
        _merge(
            investment_accounts,
            db.investment_accounts.load_mapping(),
            'investment_accounts',
            inv_cs,
        )

        sheet = db.balance_sheet.get_phins()
        sheet_cs = db.balance_sheet.load_checksums()
        if sheet is not None and isinstance(sheet, dict):
            if balance_sheet:
                if prefer_db:
                    balance_sheet.clear()
                    balance_sheet.update(sheet)
                    counts['balance_sheet'] = 1
            elif not preserve_absent:
                balance_sheet.clear()
                balance_sheet.update(sheet)
                counts['balance_sheet'] = 1
        if balance_sheet:
            if BALANCE_SHEET_ID in sheet_cs:
                _set_baseline('balance_sheet', {BALANCE_SHEET_ID: sheet_cs[BALANCE_SHEET_ID]})
            else:
                _, digest = canonical_payload(dict(balance_sheet))
                _set_baseline('balance_sheet', {BALANCE_SHEET_ID: digest})
        else:
            _set_baseline('balance_sheet', {})
    except Exception as exc:
        logger.error("fiduciary hydrate failed: %s", type(exc).__name__)
        raise
    finally:
        try:
            db.close()
        except Exception:
            pass
    return counts


def _refresh_baseline_after_flush(
    label: str,
    live: Mapping[str, Any],
    repo: Any,
    *,
    flushed: Mapping[str, Any],
    prior_expected: Mapping[str, str],
    written_ids: Iterable[str],
    withheld_ids: Iterable[str],
) -> int:
    """Align baseline (and mutable memory) with sealed outcomes.

    Compare digests against the ``flushed`` snapshot that was actually
    upserted — not the live maps, which a concurrent credit may have moved
    after ``replace_mapping(dict(mapping))`` ran unlocked.

    * Written / no-op ids: stamp baseline from the flushed digest; never
      clobber a live credit that raced ahead of the snapshot.
    * Withheld ids: adopt sealed into live memory only when live still equals
      the flushed snapshot. If live moved, stamp baseline from the sealed
      digest without adopting so the next flush can CAS-write the local
      credit over the peer.

    Baseline is rebuilt only for ids in ``flushed`` / live. Sealed ids this
    replica never held must not receive tokens. Returns adopt count.
    """
    from database.repositories.fiduciary_repository import canonical_payload

    try:
        sealed_cs = repo.load_checksums()
        sealed_payloads = repo.load_mapping()
    except Exception:
        return 0

    baseline: Dict[str, str] = {}
    adopted = 0
    mutable = isinstance(live, MutableMapping)
    written_set = {str(i) for i in written_ids}
    withheld_set = {str(i) for i in withheld_ids}

    for key, flushed_payload in (flushed or {}).items():
        record_id = str(key)
        _, flushed_digest = canonical_payload(flushed_payload)
        sealed_digest = sealed_cs.get(record_id)

        if record_id in written_set:
            # We sealed (or no-op'd) the flushed snapshot. Token = that digest.
            # Leave live alone — a post-snapshot credit must survive.
            baseline[record_id] = sealed_digest or flushed_digest
            continue

        if record_id not in withheld_set:
            # Error / skipped — keep a prior token only if still in live book.
            if record_id in prior_expected and record_id in (live or {}):
                baseline[record_id] = prior_expected[record_id]
            continue

        if sealed_digest is None:
            continue

        live_payload = (live or {}).get(record_id)
        live_digest = None
        if live_payload is not None:
            _, live_digest = canonical_payload(live_payload)

        if (
            mutable
            and live_digest == flushed_digest
            and record_id in sealed_payloads
        ):
            # Live still matches what we tried to write — peer win; adopt.
            live[record_id] = sealed_payloads[record_id]  # type: ignore[index]
            baseline[record_id] = sealed_digest
            adopted += 1
        else:
            # Live raced ahead (or missing): observe sealed for next CAS write
            # without wiping the local credit.
            baseline[record_id] = sealed_digest
    _set_baseline(label, baseline)
    return adopted


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
    hydrated/flushed, instead of reverting them. Withheld ids adopt sealed
    payloads into mutable mappings before the baseline advances.
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
        from database.repositories.fiduciary_repository import (
            BALANCE_SHEET_ID,
            canonical_payload,
        )

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
            expected = dict(_FIDUCIARY_BASELINE.get(label) or {})
            kwargs: Dict[str, Any] = {'expected_checksums': expected}
            if customer_from:
                kwargs['customer_from'] = customer_from
            flushed = dict(mapping)
            counts = repo.replace_mapping(flushed, **kwargs)
            adopted = _refresh_baseline_after_flush(
                label,
                mapping,
                repo,
                flushed=flushed,
                prior_expected=expected,
                written_ids=counts.get('written_ids') or [],
                withheld_ids=counts.get('withheld_ids') or [],
            )
            if adopted:
                counts['adopted'] = adopted
            result[label] = counts

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
            flushed_sheet = dict(balance_sheet)
            ok = db.balance_sheet.upsert_phins(
                flushed_sheet, expected_checksum=expected_sheet
            )
            prior: Dict[str, str] = {}
            try:
                sealed_cs = db.balance_sheet.load_checksums()
                sealed_payload = db.balance_sheet.get_phins()
            except Exception:
                sealed_cs = {}
                sealed_payload = None
            _, flushed_digest = canonical_payload(flushed_sheet)
            sealed_digest = sealed_cs.get(BALANCE_SHEET_ID)
            adopted = 0
            if ok:
                # Written / no-op: stamp flushed digest; do not clobber a live
                # race that mutated balance_sheet after the snapshot.
                prior[BALANCE_SHEET_ID] = sealed_digest or flushed_digest
            elif sealed_digest is not None:
                live_digest = None
                if balance_sheet:
                    _, live_digest = canonical_payload(dict(balance_sheet))
                if (
                    isinstance(balance_sheet, MutableMapping)
                    and live_digest == flushed_digest
                    and isinstance(sealed_payload, dict)
                ):
                    balance_sheet.clear()
                    balance_sheet.update(sealed_payload)
                    prior[BALANCE_SHEET_ID] = sealed_digest
                    adopted = 1
                else:
                    # Live raced ahead — observe sealed for the next CAS write.
                    prior[BALANCE_SHEET_ID] = sealed_digest
            _set_baseline('balance_sheet', prior)
            result['balance_sheet'] = {
                'written': 1 if ok else 0,
                'withheld': 0 if ok else 1,
            }
            if adopted:
                result['balance_sheet']['adopted'] = adopted
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
