"""Bordereaux Agent (ERP/MGA integrity U9).

Builds a sealed binder/period bordereau and optionally opens a payable
remittance run. Register on the agent job queue; admin APIs can also run
inline. Never invents cash or reads analytical expense weights.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from services.agent_job_queue import AgentJobQueue

JOB_TYPE = 'bordereaux_build'
SUBJECT_TYPE = 'bordereau'


def _portal_stores() -> Dict[str, Any]:
    policies: Dict[str, Any] = {}
    claims: Dict[str, Any] = {}
    billing: Dict[str, Any] = {}
    ledger: list = []
    try:
        import sys
        portal = sys.modules.get('web_portal.server') or sys.modules.get('server')
        if portal is not None:
            policies = getattr(portal, 'POLICIES', None) or {}
            claims = getattr(portal, 'CLAIMS', None) or {}
            billing = getattr(portal, 'BILLING', None) or getattr(portal, 'BILLS', None) or {}
            tx = getattr(portal, 'TRANSACTION_LEDGER', None)
            if isinstance(tx, dict):
                ledger = list(tx.values())
            elif isinstance(tx, list):
                ledger = list(tx)
    except Exception:
        pass
    return {
        'policies': policies,
        'claims': claims,
        'billing': billing,
        'ledger_transactions': ledger,
    }


def run_once(
    *,
    binder_id: str = 'PHINS-DEFAULT',
    period_id: str,
    create_remittance: bool = True,
    actor: str = 'bordereaux_job',
    policies: Optional[Dict[str, Any]] = None,
    claims: Optional[Dict[str, Any]] = None,
    billing: Optional[Dict[str, Any]] = None,
    ledger_transactions: Optional[Any] = None,
) -> Dict[str, Any]:
    """Build (and optionally open a remittance run for) a binder/period bordereau."""
    from services.mga import bordereaux as brd
    from services.mga import remittance as rem

    stores = _portal_stores()
    if policies is None:
        policies = stores['policies']
    if claims is None:
        claims = stores['claims']
    if billing is None:
        billing = stores['billing']
    if ledger_transactions is None:
        ledger_transactions = stores['ledger_transactions']

    if create_remittance:
        return rem.build_and_create(
            binder_id=binder_id,
            period_id=period_id,
            policies=policies,
            ledger_transactions=ledger_transactions,
            claims=claims,
            billing=billing,
            actor=actor,
        )
    bordereau = brd.build_bordereau(
        binder_id=binder_id,
        period_id=period_id,
        policies=policies,
        ledger_transactions=ledger_transactions,
        claims=claims,
        billing=billing,
        actor=actor,
    )
    return {'ok': True, 'bordereau': bordereau, 'run': None}


def _handle(job: Dict[str, Any]) -> Dict[str, Any]:
    params = job.get('input_params') or {}
    period_id = str(params.get('period_id') or '').strip()
    if not period_id:
        raise ValueError('period_id is required')
    return run_once(
        binder_id=str(params.get('binder_id') or 'PHINS-DEFAULT'),
        period_id=period_id,
        create_remittance=bool(params.get('create_remittance', True)),
        actor=str(params.get('actor') or 'bordereaux_job'),
    )


def enqueue(
    queue: AgentJobQueue,
    *,
    binder_id: str = 'PHINS-DEFAULT',
    period_id: str,
    create_remittance: bool = True,
    submitted_by: str = 'system',
    idempotency_key: Optional[str] = None,
) -> Dict[str, Any]:
    key = idempotency_key or f'bordereaux:{binder_id}:{period_id}'
    return queue.enqueue(
        job_type=JOB_TYPE,
        subject_type=SUBJECT_TYPE,
        subject_id=f'{binder_id}:{period_id}',
        submitted_by=submitted_by,
        priority=145,
        idempotency_key=key,
        input_params={
            'binder_id': binder_id,
            'period_id': period_id,
            'create_remittance': bool(create_remittance),
            'once': True,
        },
        max_attempts=2,
    )


def register(queue: AgentJobQueue) -> None:
    queue.register_handler(JOB_TYPE, _handle)
