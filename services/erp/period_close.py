"""Fiscal period close — open → soft → hard (ERP/MGA integrity U8 / AE4).

Hard-closed months refuse GL posts dated in that period (409). Soft close
seals a trial-balance pack but still allows posts; hard close is immutable
(compensating entries only in an open period). Close packs seal the
four-fund TB plus CoA fingerprint; they never rewrite books.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
from calendar import monthrange
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from services.erp import coa as coa_mod

logger = logging.getLogger(__name__)

STATUS_OPEN = 'open'
STATUS_SOFT = 'soft'
STATUS_HARD = 'hard'
PERIOD_STATUSES = (STATUS_OPEN, STATUS_SOFT, STATUS_HARD)

EVENT_SOFT = 'finance.period_soft_closed'
EVENT_HARD = 'finance.period_hard_closed'
EVENT_REOPEN = 'finance.period_reopened'

_LOCK = threading.RLock()
# period_id (YYYY-MM) -> period dict
_PERIODS: Dict[str, Dict[str, Any]] = {}
# period_id -> latest close pack dict
_PACKS: Dict[str, Dict[str, Any]] = {}


class PeriodClosedError(Exception):
    """Raised when a GL post targets a hard-closed fiscal period."""

    def __init__(
        self,
        message: str = 'period_hard_closed',
        *,
        period_id: str = '',
        entry_date: str = '',
        status: str = STATUS_HARD,
    ):
        super().__init__(message)
        self.message = message
        self.period_id = period_id
        self.entry_date = entry_date
        self.status = status

    def as_response(self) -> Dict[str, Any]:
        return {
            'error': self.message or 'period_hard_closed',
            'period_id': self.period_id,
            'entry_date': self.entry_date,
            'status': self.status,
        }


def reset_period_close_state() -> None:
    """Clear in-memory periods and packs (tests)."""
    with _LOCK:
        _PERIODS.clear()
        _PACKS.clear()


def _canonical(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(',', ':'), default=str)


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def period_id_for(year: int, month: int) -> str:
    return f'{int(year):04d}-{int(month):02d}'


def parse_period_id(period_id: str) -> Tuple[int, int]:
    raw = str(period_id or '').strip()
    parts = raw.split('-')
    if len(parts) != 2:
        raise ValueError(f'invalid period_id: {period_id!r}')
    year, month = int(parts[0]), int(parts[1])
    if month < 1 or month > 12:
        raise ValueError(f'invalid period month: {period_id!r}')
    return year, month


def period_bounds(year: int, month: int) -> Tuple[date, date]:
    last = monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last)


def _empty_period(year: int, month: int) -> Dict[str, Any]:
    start, end = period_bounds(year, month)
    pid = period_id_for(year, month)
    return {
        'id': pid,
        'year': year,
        'month': month,
        'start_date': start.isoformat(),
        'end_date': end.isoformat(),
        'status': STATUS_OPEN,
        'soft_closed_at': None,
        'soft_closed_by': None,
        'hard_closed_at': None,
        'hard_closed_by': None,
        'pack_id': None,
        'pack_checksum': None,
        'updated_at': _now_iso(),
    }


def ensure_period(year: int, month: int) -> Dict[str, Any]:
    """Return the fiscal period for ``year``/``month``, creating it open.

    A hard-close mirrored on the platform ledger is restored first so a
    restarted worker does not reopen a month that was already sealed.
    """
    pid = period_id_for(year, month)
    with _LOCK:
        existing = _PERIODS.get(pid)
        if existing is not None:
            return dict(existing)
    restored = _restore_hard_close_from_ledger(pid)
    if restored is not None:
        return restored
    with _LOCK:
        existing = _PERIODS.get(pid)
        if existing is not None:
            return dict(existing)
        row = _empty_period(year, month)
        _PERIODS[pid] = row
        return dict(row)


def get_period(period_id: str) -> Optional[Dict[str, Any]]:
    pid = str(period_id or '').strip()
    with _LOCK:
        row = _PERIODS.get(pid)
        if row is not None and row.get('status') == STATUS_HARD:
            return dict(row)
    # Peer restart / multi-worker: restore hard close from platform ledger.
    restored = _restore_hard_close_from_ledger(pid)
    if restored is not None:
        return dict(restored)
    with _LOCK:
        row = _PERIODS.get(pid)
        return dict(row) if row else None


def get_period_for_date(d: date) -> Dict[str, Any]:
    if not isinstance(d, date):
        raise TypeError('entry_date must be a date')
    pid = period_id_for(d.year, d.month)
    existing = get_period(pid)
    if existing is not None:
        return existing
    return ensure_period(d.year, d.month)


def list_periods() -> List[Dict[str, Any]]:
    with _LOCK:
        return [dict(p) for p in sorted(_PERIODS.values(), key=lambda r: r['id'])]


def assert_period_open_for_post(entry_date: Any) -> Dict[str, Any]:
    """Refuse posts into a hard-closed period (AE4).

    Soft-closed periods still accept posts. Missing / open periods are fine.
    """
    if isinstance(entry_date, datetime):
        d = entry_date.date()
    elif isinstance(entry_date, date):
        d = entry_date
    elif isinstance(entry_date, str) and entry_date.strip():
        d = date.fromisoformat(entry_date.strip()[:10])
    else:
        d = date.today()
    period = get_period_for_date(d)
    if period.get('status') == STATUS_HARD:
        raise PeriodClosedError(
            'period_hard_closed',
            period_id=period['id'],
            entry_date=d.isoformat(),
            status=STATUS_HARD,
        )
    return period


def _decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value or 0)).quantize(Decimal('0.01'))
    except Exception:
        return Decimal('0.00')


def trial_balance(
    period_id: str,
    *,
    engine: Any = None,
) -> Dict[str, Any]:
    """Four-fund trial balance for the period (read-only).

    When ``engine`` is supplied, sums ledger entries whose ``entry_date``
    falls in the period. Otherwise returns a zero TB sealed to the CoA.
    """
    year, month = parse_period_id(period_id)
    start, end = period_bounds(year, month)
    funds = {f: {'debit': Decimal('0.00'), 'credit': Decimal('0.00')} for f in coa_mod.FUNDS}

    if engine is not None:
        entries = list(getattr(engine, 'ledger_entries', None) or [])
        for entry in entries:
            ed = getattr(entry, 'entry_date', None)
            if isinstance(ed, datetime):
                ed = ed.date()
            if not isinstance(ed, date) or ed < start or ed > end:
                continue
            fund = coa_mod.map_account_type(getattr(entry, 'account_type', None))
            if fund not in funds:
                fund = coa_mod.FUND_OPERATING
            funds[fund]['debit'] += _decimal(getattr(entry, 'debit_amount', 0))
            funds[fund]['credit'] += _decimal(getattr(entry, 'credit_amount', 0))

    lines = []
    total_debit = Decimal('0.00')
    total_credit = Decimal('0.00')
    for fund in coa_mod.FUNDS:
        debit = funds[fund]['debit']
        credit = funds[fund]['credit']
        total_debit += debit
        total_credit += credit
        lines.append({
            'fund': fund,
            'debit': float(debit),
            'credit': float(credit),
            'net': float(debit - credit),
            'accounts': [a['code'] for a in coa_mod.list_accounts(fund=fund)],
        })
    balanced = abs(total_debit - total_credit) < Decimal('0.015')
    return {
        'period_id': period_id_for(year, month),
        'start_date': start.isoformat(),
        'end_date': end.isoformat(),
        'lines': lines,
        'total_debit': float(total_debit),
        'total_credit': float(total_credit),
        'balanced': balanced,
        'chart_fingerprint': coa_mod.chart_fingerprint(),
    }


def _seal_pack(pack: Dict[str, Any]) -> Dict[str, Any]:
    body = {
        'period_id': pack.get('period_id'),
        'action': pack.get('action'),
        'trial_balance': pack.get('trial_balance'),
        'chart_fingerprint': pack.get('chart_fingerprint'),
        'critical_checks_digest': pack.get('critical_checks_digest'),
        'actor': pack.get('actor'),
        'sealed_at': pack.get('sealed_at'),
    }
    checksum = hashlib.sha256(_canonical(body).encode('utf-8')).hexdigest()
    pack = dict(pack)
    pack['checksum'] = checksum
    pack['id'] = f"PCP-{pack['period_id']}-{pack['action']}-{checksum[:12]}"
    return pack


def verify_close_pack(pack: Dict[str, Any]) -> Dict[str, Any]:
    """Recompute the pack checksum; refuse a tampered seal."""
    if not isinstance(pack, dict):
        return {'ok': False, 'reason': 'pack_missing'}
    expected = _seal_pack({**pack, 'checksum': None, 'id': None}).get('checksum')
    got = str(pack.get('checksum') or '')
    if not got or got != expected:
        return {'ok': False, 'reason': 'checksum_mismatch', 'expected': expected, 'got': got}
    return {'ok': True, 'checksum': got, 'id': pack.get('id')}


def _critical_checks_digest(books: Optional[Dict[str, Any]] = None) -> str:
    try:
        from services.erp.money_gate import evaluate_money_gate
        verdict = evaluate_money_gate(books=books, operation='period_close')
        return str(getattr(verdict, 'digest', '') or '')
    except Exception:
        return hashlib.sha256(b'period-close-checks-unavailable').hexdigest()


def _resolve_platform_ledger() -> Any:
    import sys
    portal = sys.modules.get('web_portal.server') or sys.modules.get('server')
    if portal is None:
        return None
    ledger = getattr(portal, 'platform_event_ledger', None)
    if ledger is None or not hasattr(ledger, 'append_event'):
        return None
    return ledger


def _iter_platform_ledger_entries(ledger: Any) -> List[Dict[str, Any]]:
    store = getattr(ledger, 'transaction_ledger', None)
    if isinstance(store, dict):
        return [dict(v) for v in store.values() if isinstance(v, dict)]
    if hasattr(ledger, 'values') and callable(ledger.values):
        return [dict(v) for v in ledger.values() if isinstance(v, dict)]
    if isinstance(ledger, dict):
        return [dict(v) for v in ledger.values() if isinstance(v, dict)]
    return []


_PACK_LEDGER_KEYS = (
    'period_id',
    'pack_id',
    'checksum',
    'action',
    'trial_balance',
    'chart_fingerprint',
    'critical_checks_digest',
    'actor',
    'sealed_at',
    'prior_pack_id',
    'prior_pack_checksum',
)


def _pack_fields_from_entry(entry: Dict[str, Any]) -> Dict[str, Any]:
    """Pull close-pack fields from a nested ``payload`` or flattened ledger row.

    ``PlatformEventLedgerService.append_event`` merges the supplied payload
    onto the top level of the entry (same pattern as books_tied certs).
    """
    nested = entry.get('payload') if isinstance(entry.get('payload'), dict) else None
    if isinstance(nested, str) and nested.strip():
        try:
            parsed = json.loads(nested)
            nested = parsed if isinstance(parsed, dict) else None
        except Exception:
            nested = None
    source: Dict[str, Any]
    if nested and any(k in nested for k in ('pack_id', 'checksum', 'trial_balance', 'sealed_at')):
        source = dict(nested)
    else:
        source = dict(entry)
    out: Dict[str, Any] = {}
    for key in _PACK_LEDGER_KEYS:
        if key in source and source[key] is not None:
            out[key] = source[key]
    if 'period_id' not in out and entry.get('entity_id'):
        out['period_id'] = entry.get('entity_id')
    if 'actor' not in out and entry.get('actor'):
        out['actor'] = entry.get('actor')
    if 'pack_id' not in out and entry.get('entry_id'):
        # Prefer pack_id from payload; fall back only when id looks like a pack.
        eid = str(entry.get('entry_id') or '')
        if eid.startswith('PCP-'):
            out['pack_id'] = eid
    if 'sealed_at' not in out:
        stamp = entry.get('timestamp') or entry.get('recorded_at')
        if stamp:
            out['sealed_at'] = stamp
    return out


def _pack_from_ledger_fields(fields: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Rebuild a close pack that ``verify_close_pack`` can re-seal."""
    period_id = str(fields.get('period_id') or '')
    action = str(fields.get('action') or STATUS_HARD)
    if not period_id:
        return None
    pack = {
        'period_id': period_id,
        'action': action,
        'trial_balance': fields.get('trial_balance'),
        'chart_fingerprint': fields.get('chart_fingerprint'),
        'critical_checks_digest': fields.get('critical_checks_digest'),
        'actor': fields.get('actor') or 'period_close',
        'sealed_at': fields.get('sealed_at') or _now_iso(),
        'prior_pack_id': fields.get('prior_pack_id'),
        'prior_pack_checksum': fields.get('prior_pack_checksum'),
        'restored_from_ledger': True,
    }
    stored_checksum = str(fields.get('checksum') or '')
    stored_id = str(fields.get('pack_id') or '')
    # Prefer the stored seal when present and intact; otherwise recompute.
    if stored_checksum:
        pack['checksum'] = stored_checksum
        pack['id'] = stored_id or f"PCP-{period_id}-{action}-{stored_checksum[:12]}"
        if verify_close_pack(pack).get('ok'):
            return pack
    resealed = _seal_pack(pack)
    # If a stored checksum was present but mismatched, refuse rather than
    # invent a new seal over incomplete fields.
    if stored_checksum and resealed.get('checksum') != stored_checksum:
        logger.warning(
            'period_close restored pack checksum mismatch period=%s',
            period_id,
        )
        # Still restore HARD status; pack verify stays failed until resealed
        # fields are complete. Keep the stored ids for forensics.
        pack['checksum'] = stored_checksum
        pack['id'] = stored_id or resealed.get('id')
        pack['seal_intact'] = False
        return pack
    return resealed


def _restore_hard_close_from_ledger(period_id: str) -> Optional[Dict[str, Any]]:
    """Rehydrate a hard-closed period from the platform ledger (peer / restart).

    Soft/reopen events do not clear a hard-close row — hard remains immutable.
    Missing ledger → no restore (period stays open until closed again).
    """
    pid = str(period_id or '').strip()
    if not pid:
        return None
    ledger = _resolve_platform_ledger()
    if ledger is None:
        return None
    latest: Optional[Dict[str, Any]] = None
    for entry in _iter_platform_ledger_entries(ledger):
        event_type = str(entry.get('event_type') or entry.get('type') or '')
        entity_id = str(entry.get('entity_id') or '')
        if event_type == EVENT_HARD and entity_id == pid:
            latest = entry
    if latest is None:
        return None
    try:
        year, month = parse_period_id(pid)
    except ValueError:
        return None
    fields = _pack_fields_from_entry(latest)
    fields.setdefault('period_id', pid)
    fields.setdefault('action', STATUS_HARD)
    pack = _pack_from_ledger_fields(fields)
    sealed_at = str(
        (pack or {}).get('sealed_at')
        or fields.get('sealed_at')
        or latest.get('timestamp')
        or latest.get('recorded_at')
        or _now_iso()
    )
    actor = str((pack or {}).get('actor') or fields.get('actor') or latest.get('actor') or 'period_close')
    pack_id = str((pack or {}).get('id') or fields.get('pack_id') or '') or None
    pack_checksum = str((pack or {}).get('checksum') or fields.get('checksum') or '') or None
    with _LOCK:
        period = _empty_period(year, month)
        period['status'] = STATUS_HARD
        period['hard_closed_at'] = sealed_at
        period['hard_closed_by'] = actor
        period['soft_closed_at'] = sealed_at
        period['soft_closed_by'] = actor
        period['pack_id'] = pack_id
        period['pack_checksum'] = pack_checksum
        period['updated_at'] = sealed_at
        _PERIODS[pid] = period
        if pack is not None:
            _PACKS[pid] = pack
        return dict(period)


def _mirror_pack_to_ledger(pack: Dict[str, Any], *, event_type: str) -> Dict[str, Any]:
    """Append a durable period-close event when a platform ledger is present.

    No ledger (unit tests / early boot) → skipped OK. A present ledger that
    refuses the append fails closed so the period state is not advanced.
    Payload carries every field ``_seal_pack`` hashes so a restart can
    rebuild a verifiable pack (``append_event`` flattens these onto the row).
    """
    ledger = _resolve_platform_ledger()
    if ledger is None:
        return {'ok': True, 'skipped': True, 'reason': 'ledger_unavailable'}
    entry_id = str(pack.get('id') or f"PCP-{pack.get('period_id')}-{event_type}")
    try:
        ledger.append_event(
            event_type=event_type,
            entity_type='fiscal_period',
            entity_id=pack.get('period_id'),
            actor=pack.get('actor') or 'period_close',
            amount=0.0,
            payload={
                'period_id': pack.get('period_id'),
                'pack_id': pack.get('id'),
                'checksum': pack.get('checksum'),
                'action': pack.get('action'),
                'trial_balance': pack.get('trial_balance'),
                'chart_fingerprint': pack.get('chart_fingerprint'),
                'critical_checks_digest': pack.get('critical_checks_digest'),
                'actor': pack.get('actor') or 'period_close',
                'sealed_at': pack.get('sealed_at'),
                'prior_pack_id': pack.get('prior_pack_id'),
                'prior_pack_checksum': pack.get('prior_pack_checksum'),
            },
            entry_id=entry_id,
        )
        return {'ok': True, 'entry_id': entry_id}
    except Exception as exc:
        logger.exception(
            'period_close ledger mirror failed event_type=%s period=%s',
            event_type,
            pack.get('period_id'),
        )
        return {
            'ok': False,
            'reason': 'ledger_append_failed',
            'error': str(exc) or type(exc).__name__,
        }


def soft_close(
    period_id: str,
    *,
    actor: str = 'accountant',
    engine: Any = None,
    books: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Seal a soft-close pack; posts into the period remain allowed."""
    with _LOCK:
        year, month = parse_period_id(period_id)
        period = ensure_period(year, month)
        if period.get('status') == STATUS_HARD:
            return {
                'ok': False,
                'reason': 'already_hard_closed',
                'period': period,
            }
        tb = trial_balance(period['id'], engine=engine)
        sealed_at = _now_iso()
        pack = _seal_pack({
            'period_id': period['id'],
            'action': STATUS_SOFT,
            'trial_balance': tb,
            'chart_fingerprint': coa_mod.chart_fingerprint(),
            'critical_checks_digest': _critical_checks_digest(books),
            'actor': actor,
            'sealed_at': sealed_at,
        })
        mirrored = _mirror_pack_to_ledger(pack, event_type=EVENT_SOFT)
        if not mirrored.get('ok'):
            return {
                'ok': False,
                'reason': mirrored.get('reason') or 'ledger_append_failed',
                'period': dict(period),
                'pack': pack,
                'ledger': mirrored,
            }
        period['status'] = STATUS_SOFT
        period['soft_closed_at'] = sealed_at
        period['soft_closed_by'] = actor
        period['pack_id'] = pack['id']
        period['pack_checksum'] = pack['checksum']
        period['updated_at'] = sealed_at
        _PERIODS[period['id']] = period
        _PACKS[period['id']] = pack
        return {'ok': True, 'period': dict(period), 'pack': pack}


def hard_close(
    period_id: str,
    *,
    actor: str = 'accountant',
    engine: Any = None,
    books: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Seal an immutable hard-close pack; further posts in-period are refused."""
    with _LOCK:
        year, month = parse_period_id(period_id)
        period = ensure_period(year, month)
        if period.get('status') == STATUS_HARD:
            existing = _PACKS.get(period['id'])
            return {
                'ok': True,
                'already_hard_closed': True,
                'period': dict(period),
                'pack': dict(existing) if existing else None,
            }
        # Soft-close first when still open so the pack chain is complete.
        if period.get('status') == STATUS_OPEN:
            soft = soft_close(period['id'], actor=actor, engine=engine, books=books)
            if not soft.get('ok'):
                return soft
            period = soft['period']
        tb = trial_balance(period['id'], engine=engine)
        sealed_at = _now_iso()
        pack = _seal_pack({
            'period_id': period['id'],
            'action': STATUS_HARD,
            'trial_balance': tb,
            'chart_fingerprint': coa_mod.chart_fingerprint(),
            'critical_checks_digest': _critical_checks_digest(books),
            'actor': actor,
            'sealed_at': sealed_at,
            'prior_pack_id': period.get('pack_id'),
            'prior_pack_checksum': period.get('pack_checksum'),
        })
        mirrored = _mirror_pack_to_ledger(pack, event_type=EVENT_HARD)
        if not mirrored.get('ok'):
            return {
                'ok': False,
                'reason': mirrored.get('reason') or 'ledger_append_failed',
                'period': dict(period),
                'pack': pack,
                'ledger': mirrored,
            }
        period['status'] = STATUS_HARD
        period['hard_closed_at'] = sealed_at
        period['hard_closed_by'] = actor
        period['pack_id'] = pack['id']
        period['pack_checksum'] = pack['checksum']
        period['updated_at'] = sealed_at
        _PERIODS[period['id']] = period
        _PACKS[period['id']] = pack
        return {'ok': True, 'period': dict(period), 'pack': pack}


def reopen_soft(period_id: str, *, actor: str = 'accountant') -> Dict[str, Any]:
    """Return a soft-closed period to open. Hard-closed periods refuse.

    Soft → open is mirrored as ``finance.period_reopened`` when a platform
    ledger is present (fail closed on append failure).
    """
    with _LOCK:
        period = get_period(period_id) or ensure_period(*parse_period_id(period_id))
        if period.get('status') == STATUS_HARD:
            return {'ok': False, 'reason': 'hard_closed_immutable', 'period': period}
        if period.get('status') != STATUS_SOFT:
            return {'ok': True, 'already_open': True, 'period': dict(period)}
        prior_pack = _PACKS.get(period['id']) or {}
        reopened_at = _now_iso()
        reopen_pack = _seal_pack({
            'period_id': period['id'],
            'action': 'reopen',
            'trial_balance': prior_pack.get('trial_balance') or trial_balance(period['id']),
            'chart_fingerprint': coa_mod.chart_fingerprint(),
            'critical_checks_digest': prior_pack.get('critical_checks_digest') or '',
            'actor': actor,
            'sealed_at': reopened_at,
            'prior_pack_id': period.get('pack_id') or prior_pack.get('id'),
            'prior_pack_checksum': period.get('pack_checksum') or prior_pack.get('checksum'),
        })
        mirrored = _mirror_pack_to_ledger(reopen_pack, event_type=EVENT_REOPEN)
        if not mirrored.get('ok'):
            return {
                'ok': False,
                'reason': mirrored.get('reason') or 'ledger_append_failed',
                'period': dict(period),
                'pack': reopen_pack,
                'ledger': mirrored,
            }
        period['status'] = STATUS_OPEN
        period['soft_closed_at'] = None
        period['soft_closed_by'] = None
        period['updated_at'] = reopened_at
        period['reopened_at'] = reopened_at
        period['reopened_by'] = actor
        period['reopen_pack_id'] = reopen_pack['id']
        period['reopen_pack_checksum'] = reopen_pack['checksum']
        _PERIODS[period['id']] = period
        return {'ok': True, 'period': dict(period), 'pack': reopen_pack}


def get_close_pack(period_id: str) -> Optional[Dict[str, Any]]:
    with _LOCK:
        pack = _PACKS.get(str(period_id or '').strip())
        return dict(pack) if pack else None


def status_report(*, engine: Any = None) -> Dict[str, Any]:
    """Accountant badge: current month period + CoA fingerprint."""
    today = date.today()
    current = ensure_period(today.year, today.month)
    pack = get_close_pack(current['id'])
    pack_ok = None
    if pack:
        pack_ok = verify_close_pack(pack).get('ok')
    return {
        'schema': 'phins.erp_period_close.v1',
        'current_period': current,
        'periods': list_periods(),
        'pack': pack,
        'pack_intact': pack_ok,
        'coa': coa_mod.status_report(),
        'trial_balance': trial_balance(current['id'], engine=engine),
    }


__all__ = [
    'EVENT_HARD',
    'EVENT_REOPEN',
    'EVENT_SOFT',
    'PERIOD_STATUSES',
    'PeriodClosedError',
    'STATUS_HARD',
    'STATUS_OPEN',
    'STATUS_SOFT',
    'assert_period_open_for_post',
    'ensure_period',
    'get_close_pack',
    'get_period',
    'get_period_for_date',
    'hard_close',
    'list_periods',
    'parse_period_id',
    'period_bounds',
    'period_id_for',
    'reopen_soft',
    'reset_period_close_state',
    'soft_close',
    'status_report',
    'trial_balance',
    'verify_close_pack',
]
