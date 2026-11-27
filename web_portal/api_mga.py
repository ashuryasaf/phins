"""Thin MGA HTTP surface (ERP/MGA integrity U12 strangler).

Routes under ``/api/admin/cashflow/{remittance,trust,premium-tax}`` and
related MGA reads. Handlers stay thin: session + role check, then call
``services.mga.*``. Money writes go through ``money_uow``.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

Result = Optional[Tuple[int, Dict[str, Any]]]

API_PREFIXES = (
    '/api/admin/cashflow/remittance',
    '/api/admin/cashflow/trust',
    '/api/admin/cashflow/premium-tax',
    '/api/admin/cashflow/cession',
)

MGA_ROLES = ('admin', 'accountant', 'actuary')


def _portal():
    return sys.modules.get('web_portal.server') or sys.modules.get('server')


def _role(session: Optional[Dict[str, Any]]) -> str:
    return str((session or {}).get('role') or '').lower()


def _actor(session: Optional[Dict[str, Any]]) -> str:
    return str((session or {}).get('username') or 'accountant')


def _staff(session: Optional[Dict[str, Any]]) -> Result:
    portal = _portal()
    require_role = getattr(portal, 'require_role', None)
    if require_role is None:
        if _role(session) not in MGA_ROLES:
            return 403, {'error': 'Unauthorized'}
        return None
    if not require_role(session, list(MGA_ROLES)):
        return 403, {'error': 'Unauthorized'}
    return None


def _qs_first(qs: Dict[str, List[str]], key: str, default: str = '') -> str:
    return str((qs.get(key) or [default])[0] or default)


def dispatch_get(path: str, session: Optional[Dict[str, Any]], qs: Dict[str, List[str]]) -> Result:
    path = path.rstrip('/')
    if not path.startswith('/api/admin/cashflow/'):
        return None
    denied = _staff(session)
    if denied:
        return denied

    if path == '/api/admin/cashflow/remittance':
        from services.mga import remittance as rem
        from services.mga import bordereaux as brd
        period_id = _qs_first(qs, 'period_id').strip()
        if not period_id:
            period_id = datetime.now(timezone.utc).strftime('%Y-%m')
        binder_id = _qs_first(qs, 'binder_id', brd.DEFAULT_BINDER_ID) or brd.DEFAULT_BINDER_ID
        status = {
            'binder_id': binder_id,
            'period_id': period_id,
            'bordereaux': brd.list_bordereaux(binder_id=binder_id, period_id=period_id),
            'runs': rem.list_remittance_runs(binder_id=binder_id, period_id=period_id),
            'default_binder_id': brd.DEFAULT_BINDER_ID,
        }
        return 200, {'success': True, 'remittance': status}

    if path == '/api/admin/cashflow/trust':
        from services.mga import trust as trust_mod
        from services.mga import cession as cession_mod
        from services.mga import bordereaux as brd
        from services.jobs import trust_recon_job
        binder_id = _qs_first(qs, 'binder_id', brd.DEFAULT_BINDER_ID) or brd.DEFAULT_BINDER_ID
        bank_raw = _qs_first(qs, 'bank_balance', '')
        bank_balance = None
        if bank_raw not in ('', None):
            try:
                bank_balance = float(bank_raw)
            except (TypeError, ValueError):
                bank_balance = None
        status = trust_recon_job.run_once(
            binder_id=binder_id,
            bank_balance=bank_balance,
            actor=_actor(session),
        )
        status['cession'] = cession_mod.cession_totals(binder_id=binder_id)
        status['treaties'] = cession_mod.list_treaties()
        return 200, {'success': True, 'trust': status}

    if path == '/api/admin/cashflow/premium-tax':
        from services.mga import premium_tax as tax_mod
        from services.mga import bordereaux as brd
        binder_id = _qs_first(qs, 'binder_id', brd.DEFAULT_BINDER_ID) or brd.DEFAULT_BINDER_ID
        period_id = _qs_first(qs, 'period_id', '').strip() or None
        status = {
            'jurisdictions': tax_mod.list_jurisdictions(),
            'schedule': tax_mod.remittance_schedule(
                binder_id=binder_id, period_id=period_id,
            ),
            'accruals': tax_mod.list_accruals(
                binder_id=binder_id, period_id=period_id,
            ),
        }
        return 200, {'success': True, 'premium_tax': status}

    if path == '/api/admin/cashflow/cession':
        from services.mga import cession as cession_mod
        from services.mga import bordereaux as brd
        binder_id = _qs_first(qs, 'binder_id', brd.DEFAULT_BINDER_ID) or brd.DEFAULT_BINDER_ID
        period_id = _qs_first(qs, 'period_id', '').strip() or None
        expense_raw = _qs_first(qs, 'expense_loading', '0')
        try:
            expense_loading = float(expense_raw or 0)
        except (TypeError, ValueError):
            expense_loading = 0.0
        return 200, {
            'success': True,
            'cession': {
                'totals': cession_mod.cession_totals(
                    binder_id=binder_id, period_id=period_id,
                ),
                'entries': cession_mod.list_entries(
                    binder_id=binder_id, period_id=period_id,
                ),
                'divergence': cession_mod.analytical_divergence_report(
                    expense_loading=expense_loading,
                    binder_id=binder_id,
                    period_id=period_id,
                ),
            },
        }

    return None


def dispatch_post(
    path: str,
    session: Optional[Dict[str, Any]],
    body: Dict[str, Any],
    client_ip: str = '',
) -> Result:
    path = path.rstrip('/')
    if path != '/api/admin/cashflow/remittance':
        return None
    denied = _staff(session)
    if denied:
        return denied

    from services.erp.unit_of_work import money_uow
    from services.mga import remittance as rem
    from services.mga import bordereaux as brd
    from services.mga.remittance import RemittanceError
    from services.jobs import bordereaux_job

    action = str((body or {}).get('action') or 'build').strip().lower()
    binder_id = str((body or {}).get('binder_id') or brd.DEFAULT_BINDER_ID).strip() or brd.DEFAULT_BINDER_ID
    period_id = str((body or {}).get('period_id') or '').strip()
    if not period_id:
        period_id = datetime.now(timezone.utc).strftime('%Y-%m')

    try:
        with money_uow(label='remittance'):
            if action in ('settle', 'settle_run'):
                run_id = str((body or {}).get('run_id') or '').strip()
                if not run_id:
                    return 400, {'error': 'run_id required'}
                result = rem.settle_remittance_run(
                    run_id,
                    actor=_actor(session),
                    role=_role(session),
                    break_glass=bool((body or {}).get('break_glass')),
                    break_glass_reason=str((body or {}).get('break_glass_reason') or ''),
                )
            else:
                result = bordereaux_job.run_once(
                    binder_id=binder_id,
                    period_id=period_id,
                    create_remittance=True,
                    actor=_actor(session),
                )
            status = {
                'binder_id': binder_id,
                'period_id': period_id,
                'bordereaux': brd.list_bordereaux(binder_id=binder_id, period_id=period_id),
                'runs': rem.list_remittance_runs(binder_id=binder_id, period_id=period_id),
            }
        if not result.get('ok'):
            return 409, {
                'error': result.get('reason') or 'remittance_refused',
                **{k: v for k, v in result.items() if k != 'ok'},
            }
        return 200, {'success': True, 'result': result, 'remittance': status}
    except RemittanceError as exc:
        return 409, getattr(exc, 'as_response', lambda: {'error': str(exc)})()
    except Exception as exc:
        return 500, {'error': 'remittance action failed', 'detail': str(exc)}


__all__ = ['API_PREFIXES', 'dispatch_get', 'dispatch_post']
