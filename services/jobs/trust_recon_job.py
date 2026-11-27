"""Trust Recon Agent (ERP/MGA integrity U10).

Compares the trust trial balance to an optional bank import and emits
findings only. Never invents cash to close a deficit.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from services.agent_job_queue import AgentJobQueue

JOB_TYPE = 'trust_recon'
SUBJECT_TYPE = 'trust_binder'


def run_once(
    *,
    binder_id: str = 'PHINS-DEFAULT',
    bank_balance: Optional[Any] = None,
    actor: str = 'trust_recon_job',
) -> Dict[str, Any]:
    from services.mga import trust as trust_mod

    report = trust_mod.reconcile_trust(
        binder_id=binder_id,
        bank_balance=bank_balance,
    )
    report['actor'] = actor
    report['trial_balance'] = trust_mod.trial_balance(binder_id=binder_id)
    return report


def _handle(job: Dict[str, Any]) -> Dict[str, Any]:
    params = job.get('input_params') or {}
    return run_once(
        binder_id=str(params.get('binder_id') or 'PHINS-DEFAULT'),
        bank_balance=params.get('bank_balance'),
        actor=str(params.get('actor') or 'trust_recon_job'),
    )


def enqueue(
    queue: AgentJobQueue,
    *,
    binder_id: str = 'PHINS-DEFAULT',
    bank_balance: Optional[Any] = None,
    submitted_by: str = 'system',
    idempotency_key: Optional[str] = None,
) -> Dict[str, Any]:
    key = idempotency_key or f'trust-recon:{binder_id}'
    params: Dict[str, Any] = {'binder_id': binder_id, 'once': True}
    if bank_balance is not None:
        params['bank_balance'] = bank_balance
    return queue.enqueue(
        job_type=JOB_TYPE,
        subject_type=SUBJECT_TYPE,
        subject_id=str(binder_id),
        submitted_by=submitted_by,
        priority=150,
        idempotency_key=key,
        input_params=params,
        max_attempts=2,
    )


def register(queue: AgentJobQueue) -> None:
    queue.register_handler(JOB_TYPE, _handle)
