"""Durable accounting journal bridge (ERP/MGA integrity U5).

Every ``AccountingEngine`` ledger post can append a sealed journal row
(idempotent key). Boot hydrates the in-memory engine from intact journal
rows; ``hydrate_accounting_book_from_ledger`` remains the reconciler that
fills gaps from platform ledger cash.

Modes (``PHINS_ACCOUNTING_JOURNAL_MODE``):
* ``off`` — memory only (tests / no database).
* ``dual`` — journal written on every post; boot hydrates journal then
  ledger reconstruct (default when the DB is up).
* ``db`` — journal is required; a failed durable write refuses the post.
"""

from __future__ import annotations

import logging
import os
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Mapping, Optional

from services.hydrated_store import db_mode_enabled

logger = logging.getLogger(__name__)

_MODE_ENV = 'PHINS_ACCOUNTING_JOURNAL_MODE'


def accounting_journal_mode(environ: Optional[Mapping[str, str]] = None) -> str:
    """Return ``off``, ``dual``, or ``db``."""
    env = environ if environ is not None else os.environ
    raw = str(env.get(_MODE_ENV) or '').strip().lower()
    if raw in ('off', 'dual', 'db', 'database', 'authoritative'):
        if raw in ('database', 'authoritative'):
            return 'db'
        return raw
    return 'dual' if db_mode_enabled() else 'off'


def journal_required(environ: Optional[Mapping[str, str]] = None) -> bool:
    """True when a failed journal write must refuse the in-memory post."""
    return accounting_journal_mode(environ) == 'db'


def journal_enabled(environ: Optional[Mapping[str, str]] = None) -> bool:
    return accounting_journal_mode(environ) != 'off'


def make_idempotency_key(
    *,
    engine_id: str,
    kind: str,
    subject_id: str,
    account_type: str = '',
    side: str = '',
) -> str:
    """Stable idempotency key for an accounting journal post."""
    parts = [
        'ae',
        str(engine_id or 'PHI-AE-001').strip() or 'PHI-AE-001',
        str(kind or 'entry').strip() or 'entry',
        str(subject_id or '').strip() or 'unknown',
    ]
    if account_type:
        parts.append(str(account_type).strip())
    if side:
        parts.append(str(side).strip())
    return ':'.join(parts)[:200]


def _db_manager():
    from database.manager import DatabaseManager
    return DatabaseManager()


def append_journal_entry(
    *,
    idempotency_key: str,
    payload: Dict[str, Any],
    engine_id: str = '',
    allocation_id: str = '',
    policy_id: str = '',
    customer_id: str = '',
    entry_type: str = '',
    account_type: str = '',
    entry_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Persist one sealed journal row when the journal mode is on."""
    batch = append_journal_entries([{
        'idempotency_key': idempotency_key,
        'payload': payload,
        'engine_id': engine_id,
        'allocation_id': allocation_id,
        'policy_id': policy_id,
        'customer_id': customer_id,
        'entry_type': entry_type,
        'account_type': account_type,
        'entry_id': entry_id,
    }])
    if batch.get('ok') and batch.get('results'):
        result = dict(batch['results'][0])
        result['mode'] = batch.get('mode')
        return result
    return {
        'ok': False,
        'id': None,
        'checksum': '',
        'reused': False,
        'withheld': True,
        'reason': batch.get('reason') or 'withheld',
        'mode': batch.get('mode') or accounting_journal_mode(),
    }


def _anchor_sqlite_transaction(session) -> None:
    """Open a real SQLite transaction before the first SAVEPOINT.

    sqlite3 legacy transaction control does not start a transaction for
    SAVEPOINT alone. Releasing that savepoint then commits the row on its
    own, so a later refusal in the same batch cannot roll earlier rows
    back (Bugbot Autofix / U5 batch seals).
    """
    conn = session.connection()
    if getattr(conn.dialect, 'name', '') != 'sqlite':
        return
    raw = getattr(getattr(conn, 'connection', None), 'driver_connection', None)
    if raw is not None and getattr(raw, 'in_transaction', False):
        return
    conn.exec_driver_sql('BEGIN')


def append_journal_entries(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Persist many sealed rows in one transaction (all-or-nothing).

    Used by ``post_allocation`` and ``reverse_allocation`` so a mid-loop
    clash cannot leave a one-sided line sealed.
    """
    mode = accounting_journal_mode()
    if mode == 'off':
        return {
            'ok': True,
            'results': [
                {
                    'ok': True,
                    'id': None,
                    'checksum': '',
                    'reused': False,
                    'withheld': False,
                }
                for _ in (items or [])
            ],
            'mode': mode,
        }
    if not items:
        return {'ok': True, 'results': [], 'mode': mode}
    try:
        db = _db_manager()
        results: List[Dict[str, Any]] = []
        with db.session_scope():
            _anchor_sqlite_transaction(db.session)
            for item in items:
                result = db.accounting_journal.append(
                    idempotency_key=str(item.get('idempotency_key') or ''),
                    payload=dict(item.get('payload') or {}),
                    engine_id=str(item.get('engine_id') or ''),
                    allocation_id=str(item.get('allocation_id') or ''),
                    policy_id=str(item.get('policy_id') or ''),
                    customer_id=str(item.get('customer_id') or ''),
                    entry_type=str(item.get('entry_type') or ''),
                    account_type=str(item.get('account_type') or ''),
                    entry_id=item.get('entry_id'),
                )
                if not result.get('ok'):
                    # Abort the whole transaction — no partial reverse/post seals.
                    raise RuntimeError(str(result.get('reason') or 'withheld'))
                results.append(result)
        return {'ok': True, 'results': results, 'mode': mode}
    except RuntimeError as exc:
        return {
            'ok': False,
            'results': [],
            'reused': False,
            'withheld': True,
            'reason': str(exc) or 'withheld',
            'mode': mode,
        }
    except Exception as exc:
        logger.error("accounting journal batch append failed: %s", type(exc).__name__)
        return {
            'ok': False,
            'results': [],
            'reused': False,
            'withheld': True,
            'reason': 'journal_unavailable',
            'mode': mode,
        }


def load_journal_entries(*, engine_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """Load intact journal payloads (empty when mode is off or DB unavailable)."""
    if not journal_enabled():
        return []
    try:
        db = _db_manager()
        with db.session_scope():
            return db.accounting_journal.load_intact(engine_id=engine_id)
    except Exception as exc:
        logger.error("accounting journal load failed: %s", type(exc).__name__)
        return []


def clear_journal_for_tests() -> int:
    """Wipe journal rows under ``PHINS_TEST_MODE`` so suites do not share seals.

    Production never calls this. Financial CI shares one Postgres; without a
    clear, two tests that reuse ``BILL-FS``/``CLM-1`` with different splits
    collide on content-addressed keys after ``reset_accounting_engine``.
    """
    if str(os.environ.get('PHINS_TEST_MODE') or '').strip().lower() not in (
        '1', 'true', 'yes', 'on',
    ):
        return 0
    if not journal_enabled():
        return 0
    try:
        from database.accounting_models import AccountingJournalEntry

        db = _db_manager()
        with db.session_scope():
            deleted = (
                db.accounting_journal.session.query(AccountingJournalEntry).delete()
            )
            return int(deleted or 0)
    except Exception as exc:
        logger.warning("accounting journal test clear failed: %s", type(exc).__name__)
        return 0


def _parse_entry_date(raw: Any) -> date:
    if isinstance(raw, date) and not isinstance(raw, datetime):
        return raw
    text = str(raw or '').strip()
    if not text:
        return date.today()
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return date.today()


def hydrate_accounting_engine_from_journal(engine: Any) -> Dict[str, Any]:
    """Fill an ``AccountingEngine`` from sealed journal rows (boot path).

    Does not clear existing entries: skips subjects already present so a
    second call stays idempotent. ``hydrate_accounting_book_from_ledger``
    remains the reconciler that posts missing ledger-cash rows afterward.
    """
    if engine is None:
        return {'loaded': 0, 'skipped': 0, 'mode': accounting_journal_mode()}
    mode = accounting_journal_mode()
    if mode == 'off':
        return {'loaded': 0, 'skipped': 0, 'mode': mode}

    from accounting_engine import (
        AccountType,
        AccountingEntry,
        AllocationStatus,
        EntryType,
        InvestmentRoute,
        PremiumAllocation,
    )

    rows = load_journal_entries(engine_id=getattr(engine, 'engine_id', None) or None)
    # Also accept rows without engine filter when engine_id column was null.
    if not rows:
        rows = load_journal_entries()

    existing_keys = set()
    for entry in getattr(engine, 'ledger_entries', []) or []:
        existing_keys.add(
            (
                str(getattr(entry, 'allocation_id', '') or ''),
                str(getattr(getattr(entry, 'entry_type', None), 'value', getattr(entry, 'entry_type', '')) or ''),
                str(getattr(getattr(entry, 'account_type', None), 'value', getattr(entry, 'account_type', '')) or ''),
                str(getattr(entry, 'reference_no', '') or ''),
                str(getattr(entry, 'debit_amount', '') or ''),
                str(getattr(entry, 'credit_amount', '') or ''),
            )
        )

    loaded = 0
    skipped = 0
    allocations_loaded = 0
    max_no = int(getattr(engine, 'entry_counter', 0) or 0)
    for row in rows:
        if str(row.get('record_type') or '') == 'allocation':
            alloc_id = str(row.get('allocation_id') or '')
            if not alloc_id:
                skipped += 1
                continue
            existing = (getattr(engine, 'allocations', {}) or {}).get(alloc_id)
            # Prefer a later reversed seal over a posted header.
            if existing is not None and getattr(existing, 'status', None) == AllocationStatus.REVERSED:
                skipped += 1
                continue
            try:
                route = InvestmentRoute(str(row.get('investment_route') or InvestmentRoute.BASIC_SAVINGS.value))
                status = AllocationStatus(str(row.get('status') or AllocationStatus.POSTED.value))
                alloc = PremiumAllocation(
                    allocation_id=alloc_id,
                    bill_id=str(row.get('bill_id') or ''),
                    policy_id=str(row.get('policy_id') or ''),
                    customer_id=str(row.get('customer_id') or ''),
                    allocation_date=_parse_entry_date(row.get('allocation_date')),
                    total_premium=Decimal(str(row.get('total_premium') or 0)),
                    risk_percentage=Decimal(str(row.get('risk_percentage') or 0)),
                    savings_percentage=Decimal(str(row.get('savings_percentage') or 0)),
                    investment_route=route,
                    preserve_savings_percentage=True,
                    risk_amount_exact=Decimal(str(row.get('risk_premium') or 0)),
                    savings_amount_exact=Decimal(str(row.get('savings_premium') or 0)),
                    notes=(
                        str(row.get('notes') or '')
                        or (
                            f"ledger_tx={row.get('ledger_tx')}"
                            if row.get('ledger_tx') else ''
                        )
                    ),
                )
                alloc.status = status
                if row.get('posted_date'):
                    alloc.posted_date = _parse_entry_date(row.get('posted_date'))
                alloc.posted_by = str(row.get('posted_by') or '')
                engine.allocations[alloc_id] = alloc
                allocations_loaded += 1
                loaded += 1
            except Exception:
                skipped += 1
            continue
        try:
            entry_type = EntryType(str(row.get('entry_type') or ''))
            account_type = AccountType(str(row.get('account_type') or ''))
        except ValueError:
            skipped += 1
            continue
        debit = Decimal(str(row.get('debit_amount') or 0)).quantize(
            Decimal('0.01'), rounding=ROUND_HALF_UP
        )
        credit = Decimal(str(row.get('credit_amount') or 0)).quantize(
            Decimal('0.01'), rounding=ROUND_HALF_UP
        )
        key = (
            str(row.get('allocation_id') or ''),
            entry_type.value,
            account_type.value,
            str(row.get('reference_no') or ''),
            str(debit),
            str(credit),
        )
        if key in existing_keys:
            skipped += 1
            continue
        entry_no = int(row.get('entry_no') or 0) or (max_no + 1)
        max_no = max(max_no, entry_no)
        balance = Decimal(str(row.get('balance') or 0)).quantize(
            Decimal('0.01'), rounding=ROUND_HALF_UP
        )
        entry = AccountingEntry(
            entry_no=entry_no,
            allocation_id=str(row.get('allocation_id') or ''),
            policy_id=str(row.get('policy_id') or ''),
            customer_id=str(row.get('customer_id') or ''),
            entry_date=_parse_entry_date(row.get('entry_date')),
            entry_type=entry_type,
            account_type=account_type,
            debit_amount=debit,
            credit_amount=credit,
            balance=balance,
            description=str(row.get('description') or ''),
            reference_no=str(row.get('reference_no') or ''),
            currency_code=str(row.get('currency_code') or 'USD'),
            posted=bool(row.get('posted', True)),
            posted_by=str(row.get('posted_by') or ''),
        )
        engine.ledger_entries.append(entry)
        existing_keys.add(key)
        loaded += 1
    engine.entry_counter = max(int(getattr(engine, 'entry_counter', 0) or 0), max_no)
    return {
        'loaded': loaded,
        'skipped': skipped,
        'allocations_loaded': allocations_loaded,
        'mode': mode,
        'rows': len(rows),
    }


__all__ = [
    'accounting_journal_mode',
    'journal_enabled',
    'journal_required',
    'make_idempotency_key',
    'append_journal_entry',
    'append_journal_entries',
    'load_journal_entries',
    'clear_journal_for_tests',
    'hydrate_accounting_engine_from_journal',
]
