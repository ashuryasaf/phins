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
    """Return the fiscal period for ``year``/``month``, creating it open."""
    with _LOCK:
        pid = period_id_for(year, month)
        existing = _PERIODS.get(pid)
        if existing is not None:
            return dict(existing)
        row = _empty_period(year, month)
        _PERIODS[pid] = row
        return dict(row)


def get_period(period_id: str) -> Optional[Dict[str, Any]]:
    with _LOCK:
        row = _PERIODS.get(str(period_id or '').strip())
        return dict(row) if row else None


def get_period_for_date(d: date) -> Dict[str, Any]:
    if not isinstance(d, date):
        raise TypeError('entry_date must be a date')
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


def _mirror_pack_to_ledger(pack: Dict[str, Any], *, event_type: str) -> Dict[str, Any]:
    """Append a durable period-close event when a platform ledger is present.

    No ledger (unit tests / early boot) → skipped OK. A present ledger that
    refuses the append fails closed so the period state is not advanced.
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
                'pack_id': pack.get('id'),
                'checksum': pack.get('checksum'),
                'action': pack.get('action'),
                'trial_balance': pack.get('trial_balance'),
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
