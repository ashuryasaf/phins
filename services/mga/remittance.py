"""Carrier remittance runs (ERP/MGA integrity U9).

A remittance run is created from a sealed bordereau (payable = carrier
risk cash). Settle authorizes through Money Gate ``remittance.settle``
(U4 refuse-if-books-red) then marks the run settled and mirrors a
platform-ledger event. Never reads analytical expense weights as cash.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Mapping, Optional

from services.mga import bordereaux as brd

logger = logging.getLogger(__name__)

STATUS_PAYABLE = 'payable'
STATUS_SETTLED = 'settled'
STATUS_CANCELLED = 'cancelled'
EVENT_CREATED = 'mga.remittance_created'
EVENT_REFRESHED = 'mga.remittance_refreshed'
EVENT_SETTLED = 'mga.remittance_settled'
OP_SETTLE = 'remittance.settle'

_LOCK = threading.RLock()
_RUNS: Dict[str, Dict[str, Any]] = {}

_CENT = Decimal('0.01')


class RemittanceError(Exception):
    """Raised when a remittance create/settle is refused."""

    def __init__(self, message: str, *, detail: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.detail = detail or {}

    def as_response(self) -> Dict[str, Any]:
        body = {'error': self.message}
        body.update(self.detail)
        return body


def reset_remittance_state() -> None:
    with _LOCK:
        _RUNS.clear()


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def _money(value: Any) -> Decimal:
    try:
        return Decimal(str(value or 0)).quantize(_CENT, rounding=ROUND_HALF_UP)
    except Exception:
        return Decimal('0.00')


def _canonical(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(',', ':'), default=str)


def _run_id(binder_id: str, period_id: str) -> str:
    """One remittance run identity per binder/period (never per rebuild)."""
    digest = hashlib.sha256(f'{binder_id}|{period_id}'.encode('utf-8')).hexdigest()[:12]
    return f'REM-{binder_id}-{period_id}-{digest}'


def _resolve_platform_ledger() -> Any:
    try:
        import sys
        portal = sys.modules.get('web_portal.server') or sys.modules.get('server')
        if portal is None:
            return None
        ledger = getattr(portal, 'platform_event_ledger', None)
        if ledger is None or not hasattr(ledger, 'append_event'):
            return None
        return ledger
    except Exception:
        return None


def _mirror(
    event_type: str,
    run: Mapping[str, Any],
    *,
    entry_suffix: Optional[str] = None,
) -> Dict[str, Any]:
    ledger = _resolve_platform_ledger()
    if ledger is None:
        return {'ok': True, 'skipped': True}
    suffix = entry_suffix or event_type.split('.')[-1]
    entry_id = str(run.get('id') or '') + ':' + suffix
    try:
        ledger.append_event(
            event_type=event_type,
            entity_type='remittance_run',
            entity_id=run.get('id'),
            actor=(
                run.get('settled_by')
                or run.get('updated_by')
                or run.get('created_by')
                or 'remittance'
            ),
            amount=float(_money(run.get('amount'))),
            payload={
                'run_id': run.get('id'),
                'binder_id': run.get('binder_id'),
                'period_id': run.get('period_id'),
                'bordereau_id': run.get('bordereau_id'),
                'bordereau_sha256': run.get('bordereau_sha256'),
                'status': run.get('status'),
                'amount': run.get('amount'),
                'currency': run.get('currency'),
            },
            entry_id=entry_id,
        )
        return {'ok': True, 'entry_id': entry_id}
    except Exception as exc:
        logger.exception('remittance ledger mirror failed event=%s run=%s', event_type, run.get('id'))
        return {'ok': False, 'reason': 'ledger_append_failed', 'error': str(exc)}


def settled_run_for(binder_id: str, period_id: str) -> Optional[Dict[str, Any]]:
    """Return the settled remittance for binder/period, if any."""
    rows = list_remittance_runs(
        binder_id=str(binder_id or ''),
        period_id=str(period_id or ''),
        status=STATUS_SETTLED,
    )
    return dict(rows[0]) if rows else None


def bordereau_snapshot_from_run(run: Mapping[str, Any]) -> Dict[str, Any]:
    """Read-only board view for a settled run (keeps remitted cash visible)."""
    snap = run.get('bordereau_snapshot')
    if isinstance(snap, Mapping) and snap.get('bordereau_sha256'):
        return dict(snap)
    return {
        'id': run.get('bordereau_id'),
        'schema': brd.SCHEMA,
        'binder_id': run.get('binder_id'),
        'period_id': run.get('period_id'),
        'bordereau_sha256': run.get('bordereau_sha256'),
        'carrier_payable': run.get('amount'),
        'premium_cash': run.get('premium_cash'),
        'claims_paid': run.get('claims_paid'),
        'commission': 0.0,
        'streams': run.get('streams') or {},
        'currency': run.get('currency') or 'USD',
        'lines': [],
        'policy_ids': [],
        'settled_snapshot': True,
        'ae5_ok': True,
    }


def create_remittance_run(
    *,
    bordereau: Mapping[str, Any],
    actor: str = 'accountant',
) -> Dict[str, Any]:
    """Create a payable remittance run from a sealed bordereau (idempotent)."""
    check = brd.verify_bordereau(bordereau)
    if not check.get('ok'):
        raise RemittanceError(
            'bordereau_not_intact',
            detail={'ae5': check},
        )
    binder_id = str(bordereau.get('binder_id') or brd.DEFAULT_BINDER_ID)
    period_id = str(bordereau.get('period_id') or '')
    bordereau_id = str(bordereau.get('id') or '')
    if not period_id or not bordereau_id:
        raise RemittanceError('bordereau_incomplete')
    amount = _money(bordereau.get('carrier_payable'))
    run_id = _run_id(binder_id, period_id)
    with _LOCK:
        existing = _RUNS.get(run_id)
        if existing is not None:
            if existing.get('status') == STATUS_SETTLED:
                return {'ok': True, 'already_settled': True, 'run': dict(existing)}
            if existing.get('status') == STATUS_CANCELLED:
                pass  # reopen a fresh payable below
            elif existing.get('status') == STATUS_PAYABLE:
                # Same sealed cash → idempotent. Changed cash → refresh the
                # single payable in place (never a second run for the period).
                if (
                    existing.get('bordereau_sha256') == bordereau.get('bordereau_sha256')
                    and float(_money(existing.get('amount'))) == float(amount)
                ):
                    return {'ok': True, 'already': True, 'run': dict(existing)}
                refreshed = dict(existing)
                prior_amount = refreshed.get('amount')
                prior_sha = refreshed.get('bordereau_sha256')
                refreshed['bordereau_id'] = bordereau_id
                refreshed['bordereau_sha256'] = bordereau.get('bordereau_sha256')
                refreshed['amount'] = float(amount)
                refreshed['premium_cash'] = bordereau.get('premium_cash')
                refreshed['claims_paid'] = bordereau.get('claims_paid')
                refreshed['streams'] = bordereau.get('streams') or {}
                refreshed['currency'] = str(bordereau.get('currency') or 'USD')
                refreshed['updated_at'] = _now_iso()
                refreshed['updated_by'] = actor
                sha = str(bordereau.get('bordereau_sha256') or '')[:12] or 'refresh'
                mirrored = _mirror(
                    EVENT_REFRESHED,
                    refreshed,
                    entry_suffix=f'refreshed:{sha}',
                )
                if not mirrored.get('ok'):
                    raise RemittanceError(
                        'ledger_append_failed',
                        detail={
                            'ledger': mirrored,
                            'prior_amount': prior_amount,
                            'prior_sha': prior_sha,
                        },
                    )
                _RUNS[run_id] = refreshed
                return {'ok': True, 'refreshed': True, 'run': dict(refreshed)}
            else:
                raise RemittanceError(
                    'remittance_not_payable',
                    detail={'status': existing.get('status')},
                )
        run = {
            'id': run_id,
            'status': STATUS_PAYABLE,
            'binder_id': binder_id,
            'period_id': period_id,
            'bordereau_id': bordereau_id,
            'bordereau_sha256': bordereau.get('bordereau_sha256'),
            'amount': float(amount),
            'currency': str(bordereau.get('currency') or 'USD'),
            'created_at': _now_iso(),
            'created_by': actor,
            'settled_at': None,
            'settled_by': None,
            'premium_cash': bordereau.get('premium_cash'),
            'claims_paid': bordereau.get('claims_paid'),
            'streams': bordereau.get('streams') or {},
        }
        mirrored = _mirror(EVENT_CREATED, run)
        if not mirrored.get('ok'):
            raise RemittanceError(
                'ledger_append_failed',
                detail={'ledger': mirrored},
            )
        _RUNS[run_id] = run
        return {'ok': True, 'run': dict(run)}


def get_remittance_run(run_id: str) -> Optional[Dict[str, Any]]:
    with _LOCK:
        row = _RUNS.get(str(run_id or '').strip())
        return dict(row) if row else None


def list_remittance_runs(
    *,
    binder_id: Optional[str] = None,
    period_id: Optional[str] = None,
    status: Optional[str] = None,
) -> List[Dict[str, Any]]:
    with _LOCK:
        rows = [dict(v) for v in _RUNS.values()]
    if binder_id:
        rows = [r for r in rows if r.get('binder_id') == binder_id]
    if period_id:
        rows = [r for r in rows if r.get('period_id') == period_id]
    if status:
        rows = [r for r in rows if r.get('status') == status]
    return sorted(rows, key=lambda r: str(r.get('id') or ''))


def settle_remittance_run(
    run_id: str,
    *,
    actor: str = 'accountant',
    role: str = 'accountant',
    books: Optional[Mapping[str, Any]] = None,
    break_glass: bool = False,
    break_glass_reason: str = '',
    platform_ledger: Any = None,
) -> Dict[str, Any]:
    """Settle a payable remittance after Money Gate authorization (U4 / AE5)."""
    from services.erp.money_gate import MoneyGateError, authorize_money_move

    with _LOCK:
        run = _RUNS.get(str(run_id or '').strip())
        if run is None:
            raise RemittanceError('remittance_not_found')
        if run.get('status') == STATUS_SETTLED:
            return {'ok': True, 'already_settled': True, 'run': dict(run)}
        if run.get('status') != STATUS_PAYABLE:
            raise RemittanceError(
                'remittance_not_payable',
                detail={'status': run.get('status')},
            )
        # Re-verify the bordereau seal before cash moves.
        bordereau = brd.get_bordereau(str(run.get('bordereau_id') or ''))
        if bordereau is None:
            raise RemittanceError('bordereau_missing')
        check = brd.verify_bordereau(bordereau)
        if not check.get('ok'):
            raise RemittanceError('bordereau_not_intact', detail={'ae5': check})

    try:
        authorize_kwargs: Dict[str, Any] = {
            'books': books,
            'break_glass': break_glass,
            'break_glass_reason': break_glass_reason,
            'actor': actor,
            'role': role,
        }
        if platform_ledger is not None:
            authorize_kwargs['platform_ledger'] = platform_ledger
        verdict = authorize_money_move(OP_SETTLE, **authorize_kwargs)
    except MoneyGateError as gate_exc:
        raise RemittanceError(
            'money_gate_refused',
            detail=gate_exc.as_response() if hasattr(gate_exc, 'as_response') else {
                'error': 'money_gate_refused',
                'failed_checks': list(getattr(gate_exc, 'failed_checks', []) or []),
            },
        ) from gate_exc

    with _LOCK:
        run = _RUNS.get(str(run_id or '').strip())
        if run is None:
            raise RemittanceError('remittance_not_found')
        if run.get('status') == STATUS_SETTLED:
            return {'ok': True, 'already_settled': True, 'run': dict(run)}
        # Re-load the intact seal and freeze it on the run so a later rebuild
        # cannot erase the remitted AE5 cash picture.
        bordereau = brd.get_bordereau(str(run.get('bordereau_id') or ''))
        if bordereau is None:
            raise RemittanceError('bordereau_missing')
        check = brd.verify_bordereau(bordereau)
        if not check.get('ok'):
            raise RemittanceError('bordereau_not_intact', detail={'ae5': check})
        run = dict(run)
        run['status'] = STATUS_SETTLED
        run['settled_at'] = _now_iso()
        run['settled_by'] = actor
        run['money_gate_digest'] = getattr(verdict, 'digest', '') or ''
        run['bordereau_snapshot'] = dict(bordereau)
        run['bordereau_sha256'] = bordereau.get('bordereau_sha256')
        run['amount'] = float(_money(bordereau.get('carrier_payable')))
        run['premium_cash'] = bordereau.get('premium_cash')
        run['claims_paid'] = bordereau.get('claims_paid')
        run['streams'] = bordereau.get('streams') or {}
        mirrored = _mirror(EVENT_SETTLED, run)
        if not mirrored.get('ok'):
            raise RemittanceError('ledger_append_failed', detail={'ledger': mirrored})
        _RUNS[run['id']] = run
        return {
            'ok': True,
            'run': dict(run),
            'money_gate': verdict.as_dict() if hasattr(verdict, 'as_dict') else {},
        }


def build_and_create(
    *,
    binder_id: str = brd.DEFAULT_BINDER_ID,
    period_id: str,
    policies: Optional[Mapping[str, Any]] = None,
    ledger_transactions: Optional[Any] = None,
    claims: Optional[Mapping[str, Any]] = None,
    billing: Optional[Mapping[str, Any]] = None,
    actor: str = 'accountant',
) -> Dict[str, Any]:
    """Build a sealed bordereau and open a payable remittance run."""
    settled = settled_run_for(binder_id, period_id)
    if settled is not None:
        board = brd.get_bordereau(str(settled.get('bordereau_id') or ''))
        if board is None:
            board = bordereau_snapshot_from_run(settled)
        return {
            'ok': True,
            'already_settled': True,
            'bordereau': board,
            'run': settled,
        }
    bordereau = brd.build_bordereau(
        binder_id=binder_id,
        period_id=period_id,
        policies=policies,
        ledger_transactions=ledger_transactions,
        claims=claims,
        billing=billing,
        actor=actor,
    )
    created = create_remittance_run(bordereau=bordereau, actor=actor)
    return {
        'ok': True,
        'bordereau': bordereau,
        'run': created.get('run'),
        'already': created.get('already'),
        'already_settled': created.get('already_settled'),
        'refreshed': created.get('refreshed'),
    }


__all__ = [
    'EVENT_CREATED',
    'EVENT_REFRESHED',
    'EVENT_SETTLED',
    'OP_SETTLE',
    'RemittanceError',
    'STATUS_CANCELLED',
    'STATUS_PAYABLE',
    'STATUS_SETTLED',
    'bordereau_snapshot_from_run',
    'build_and_create',
    'create_remittance_run',
    'get_remittance_run',
    'list_remittance_runs',
    'reset_remittance_state',
    'settle_remittance_run',
    'settled_run_for',
]
