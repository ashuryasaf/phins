"""Thin finance HTTP surface (ERP/MGA integrity U12 strangler).

Cashflow integrity, period close, books-tied, scorecard, and kernel-pin
routes. Handlers call ``services.erp.*`` / cashflow services; money writes
use ``money_uow``.
"""

from __future__ import annotations

import sys
from typing import Any, Dict, List, Optional, Tuple

Result = Optional[Tuple[int, Dict[str, Any]]]

API_PREFIXES = (
    '/api/admin/cashflow/period-close',
    '/api/admin/cashflow/books-tied',
    '/api/admin/cashflow/integrity-scorecard',
    '/api/admin/cashflow/kernel-pins',
    '/api/admin/cashflow/restore-kernel-pins',
)

FINANCE_ROLES = ('admin', 'accountant', 'actuary')
KERNEL_PIN_ROLES = ('admin', 'accountant', 'actuary')


def _portal():
    return sys.modules.get('web_portal.server') or sys.modules.get('server')


def _role(session: Optional[Dict[str, Any]]) -> str:
    return str((session or {}).get('role') or '').lower()


def _actor(session: Optional[Dict[str, Any]]) -> str:
    return str((session or {}).get('username') or 'accountant')


def _staff(session: Optional[Dict[str, Any]], roles=FINANCE_ROLES) -> Result:
    portal = _portal()
    require_role = getattr(portal, 'require_role', None)
    if require_role is None:
        if _role(session) not in roles:
            return 403, {'error': 'Unauthorized'}
        return None
    if not require_role(session, list(roles)):
        return 403, {'error': 'Unauthorized'}
    return None


def _platform_ledger():
    portal = _portal()
    return getattr(portal, 'platform_event_ledger', None)


def _accounting_engine():
    try:
        from accounting_engine import get_accounting_engine
        return get_accounting_engine()
    except Exception:
        return None


def dispatch_get(path: str, session: Optional[Dict[str, Any]], qs: Dict[str, List[str]]) -> Result:
    path = path.rstrip('/')

    if path == '/api/admin/cashflow/period-close':
        denied = _staff(session)
        if denied:
            return denied
        from services.erp.period_close import status_report as period_close_status
        return 200, {
            'success': True,
            'period_close': period_close_status(engine=_accounting_engine()),
        }

    if path == '/api/admin/cashflow/books-tied':
        denied = _staff(session)
        if denied:
            return denied
        from services.erp.books_tied import status_report as books_tied_status
        return 200, {
            'success': True,
            'books_tied': books_tied_status(_platform_ledger()),
        }

    if path == '/api/admin/cashflow/integrity-scorecard':
        denied = _staff(session)
        if denied:
            return denied
        from services.erp.integrity_scorecard import compute_integrity_scorecard
        return 200, {'success': True, 'scorecard': compute_integrity_scorecard()}

    if path == '/api/admin/cashflow/kernel-pins':
        denied = _staff(session, KERNEL_PIN_ROLES)
        if denied:
            return denied
        portal = _portal()
        restore = getattr(portal, 'restore_kernel_pins', None)
        if restore is None:
            return 500, {'error': 'kernel pin preview unavailable'}
        preview = restore(_actor(session), apply=False)
        return 200, {'success': True, 'kernel_pins': preview}

    return None


def dispatch_post(
    path: str,
    session: Optional[Dict[str, Any]],
    body: Dict[str, Any],
    client_ip: str = '',
) -> Result:
    path = path.rstrip('/')

    if path == '/api/admin/cashflow/period-close':
        denied = _staff(session)
        if denied:
            return denied
        from services.erp.unit_of_work import money_uow
        from services.erp import period_close as pc
        period_id = str((body or {}).get('period_id') or '').strip()
        action = str((body or {}).get('action') or 'soft').strip().lower()
        actor = _actor(session)
        engine = _accounting_engine()
        if not period_id:
            today = __import__('datetime').date.today()
            period_id = pc.period_id_for(today.year, today.month)
        try:
            with money_uow(label='period_close'):
                if action in ('hard', 'hard_close'):
                    result = pc.hard_close(period_id, actor=actor, engine=engine)
                elif action in ('reopen', 'reopen_soft'):
                    result = pc.reopen_soft(period_id, actor=actor)
                else:
                    result = pc.soft_close(period_id, actor=actor, engine=engine)
                status = pc.status_report(engine=engine)
        except Exception as period_exc:
            if type(period_exc).__name__ == 'PeriodClosedError':
                return 409, getattr(period_exc, 'as_response', lambda: {'error': str(period_exc)})()
            return 500, {'error': 'period_close_failed', 'detail': str(period_exc)}
        if not result.get('ok'):
            return 409, {
                'error': result.get('reason') or 'period_close_refused',
                **{k: v for k, v in result.items() if k != 'ok'},
            }
        return 200, {'success': True, 'result': result, 'period_close': status}

    if path == '/api/admin/cashflow/books-tied':
        denied = _staff(session)
        if denied:
            return denied
        from services.erp.unit_of_work import money_uow
        from services.erp.books_tied import (
            issue_certificate as books_tied_issue,
            status_report as books_tied_status,
        )
        from services.erp.money_gate import evaluate_money_gate
        with money_uow(label='books_tied'):
            verdict = evaluate_money_gate(operation='books_tied.issue')
            issued = books_tied_issue(
                _platform_ledger(),
                verdict=verdict,
                actor=_actor(session),
            )
            status = books_tied_status(_platform_ledger())
        return 200, {
            'success': True,
            'certificate': issued,
            'books_tied': status,
        }

    if path == '/api/admin/cashflow/restore-kernel-pins':
        denied = _staff(session, KERNEL_PIN_ROLES)
        if denied:
            return denied
        from services.erp.unit_of_work import money_uow
        portal = _portal()
        restore = getattr(portal, 'restore_kernel_pins', None)
        if restore is None:
            return 500, {'error': 'kernel pin restore unavailable'}
        with money_uow(label='kernel_pins'):
            result = restore(_actor(session), apply=True)
        # Journal-first fail-closed: a non-durable restore must not look like success.
        if result.get('success') is False:
            return 503, {
                'error': result.get('error') or 'not_durable',
                'kernel_pins': result,
            }
        return 200, {'success': True, 'kernel_pins': result}

    return None


__all__ = ['API_PREFIXES', 'dispatch_get', 'dispatch_post']
