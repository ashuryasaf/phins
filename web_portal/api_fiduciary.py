"""Thin fiduciary HTTP surface (ERP/MGA integrity U12 strangler).

Wallet / withdrawal / NFT-adjacent admin reads that must stay on the
fiduciary store. Wallet-withdrawal chat routes remain in
``api_wallet_withdrawal``; this module covers the durability probe and
fiduciary health snapshot used by the Durability Guard.
"""

from __future__ import annotations

import sys
from typing import Any, Dict, List, Optional, Tuple

Result = Optional[Tuple[int, Dict[str, Any]]]

API_PREFIXES = (
    '/api/admin/fiduciary/durability',
    '/api/admin/fiduciary/health',
)

FIDUCIARY_ROLES = ('admin', 'accountant')


def _portal():
    return sys.modules.get('web_portal.server') or sys.modules.get('server')


def _role(session: Optional[Dict[str, Any]]) -> str:
    return str((session or {}).get('role') or '').lower()


def _actor(session: Optional[Dict[str, Any]]) -> str:
    return str((session or {}).get('username') or 'admin')


def _staff(session: Optional[Dict[str, Any]]) -> Result:
    portal = _portal()
    require_role = getattr(portal, 'require_role', None)
    if require_role is None:
        if _role(session) not in FIDUCIARY_ROLES:
            return 403, {'error': 'Unauthorized'}
        return None
    if not require_role(session, list(FIDUCIARY_ROLES)):
        return 403, {'error': 'Unauthorized'}
    return None


def dispatch_get(path: str, session: Optional[Dict[str, Any]], qs: Dict[str, List[str]]) -> Result:
    path = path.rstrip('/')
    denied = _staff(session)
    if denied and path.startswith('/api/admin/fiduciary/'):
        return denied

    if path == '/api/admin/fiduciary/health':
        from services.jobs import durability_guard_job
        report = durability_guard_job.status_report()
        return 200, {'success': True, 'fiduciary': report}

    if path == '/api/admin/fiduciary/durability':
        from services.jobs import durability_guard_job
        # Read-only status; POST runs the probe.
        return 200, {
            'success': True,
            'durability': durability_guard_job.status_report(),
            'note': 'POST to run the probe (findings only; never rewrites customer money)',
        }

    return None


def dispatch_post(
    path: str,
    session: Optional[Dict[str, Any]],
    body: Dict[str, Any],
    client_ip: str = '',
) -> Result:
    path = path.rstrip('/')
    if path != '/api/admin/fiduciary/durability':
        return None
    denied = _staff(session)
    if denied:
        return denied
    from services.erp.unit_of_work import money_uow
    from services.jobs import durability_guard_job
    with money_uow(label='durability_guard'):
        report = durability_guard_job.run_once(actor=_actor(session))
    return 200, {'success': True, 'durability': report}


__all__ = ['API_PREFIXES', 'dispatch_get', 'dispatch_post']
