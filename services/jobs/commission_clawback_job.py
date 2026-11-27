"""Commission Clawback Agent clock (ERP/MGA integrity U7).

Scans policies and posts hash-chained ``agent.commission.clawed_back``
reversals for live commissions on lapsed / cancelled / expired / inactive
policies. Overdue bills alone do not auto-claw (admin posts those
explicitly). Idempotent on ``(policy_id, commission_id)``. When the agent
job queue is running, ``ensure_scan_clock`` keeps one recurring row;
``enqueue_once`` is the operator / API path. Correctness also holds when
an admin posts ``/api/admin/agents/commissions/clawback`` inline.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

from services.agent_job_queue import AgentJobQueue, RescheduleJob

JOB_TYPE = 'commission_clawback_scan'
SUBJECT_TYPE = 'commission_clawback'
SUBJECT_ID = 'global'
IDEMPOTENCY_KEY = 'commission-clawback-scan-clock'
DEFAULT_TICK_SECONDS = 3600.0


def tick_seconds() -> float:
    try:
        value = float(os.environ.get('PHINS_COMMISSION_CLAWBACK_TICK_SECONDS', DEFAULT_TICK_SECONDS))
    except (TypeError, ValueError):
        value = DEFAULT_TICK_SECONDS
    return max(60.0, min(value, 24 * 3600.0))


def _portal_stores() -> Dict[str, Any]:
    """Best-effort policy/bill dicts from the loaded portal module."""
    policies: Dict[str, Any] = {}
    bills: Dict[str, Any] = {}
    try:
        import sys
        portal = sys.modules.get('web_portal.server') or sys.modules.get('server')
        if portal is not None:
            policies = getattr(portal, 'POLICIES', None) or {}
            bills = getattr(portal, 'BILLING', None) or getattr(portal, 'BILLS', None) or {}
    except Exception:
        pass
    return {'policies': policies, 'bills': bills}


def run_once(
    *,
    policies: Optional[Dict[str, Any]] = None,
    bills: Optional[Dict[str, Any]] = None,
    actor: str = 'commission_clawback_job',
) -> Dict[str, Any]:
    """Scan and claw back commissions that should reverse (AE6)."""
    from services import agent_ecosystem_service as svc

    stores = _portal_stores()
    if policies is None:
        policies = stores.get('policies') or {}
    if bills is None:
        bills = stores.get('bills') or {}
    result = svc.clawback_for_policies(policies, bills, actor=actor)
    return {
        'clawed': result.get('clawed', 0),
        'already': result.get('already', 0),
        'skipped': result.get('skipped', 0),
        'items': result.get('items') or [],
        'skipped_items': result.get('skipped_items') or [],
        'coverage': result.get('coverage') or {},
        'ledger_intact': result.get('ledger_intact'),
    }


def _handle(job: Dict[str, Any]) -> Dict[str, Any]:
    params = job.get('input_params') or {}
    try:
        result = run_once(
            policies=params.get('policies'),
            bills=params.get('bills'),
            actor=str(params.get('actor') or 'commission_clawback_job'),
        )
    except Exception as exc:
        if params.get('once'):
            raise
        raise RescheduleJob(
            tick_seconds(),
            f"commission_clawback scan: error={exc}",
        ) from exc
    if params.get('once'):
        return result
    raise RescheduleJob(
        tick_seconds(),
        f"commission_clawback scan: clawed={result.get('clawed')} "
        f"gaps={(result.get('coverage') or {}).get('gap_count')}",
    )


def ensure_scan_clock(queue: AgentJobQueue, *, submitted_by: str = 'system') -> Dict[str, Any]:
    """Enqueue the recurring clawback scan exactly once (idempotent)."""
    return queue.enqueue(
        job_type=JOB_TYPE,
        subject_type=SUBJECT_TYPE,
        subject_id=SUBJECT_ID,
        submitted_by=submitted_by,
        priority=160,
        idempotency_key=IDEMPOTENCY_KEY,
        input_params={'once': False},
    )


def enqueue_once(
    queue: AgentJobQueue,
    *,
    submitted_by: str = 'system',
    idempotency_key: Optional[str] = None,
    policies: Optional[Dict[str, Any]] = None,
    bills: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return queue.enqueue(
        job_type=JOB_TYPE,
        subject_type=SUBJECT_TYPE,
        subject_id=SUBJECT_ID,
        submitted_by=submitted_by,
        priority=150,
        idempotency_key=idempotency_key,
        input_params={
            'once': True,
            'policies': policies,
            'bills': bills,
        },
        max_attempts=2,
    )


def register(queue: AgentJobQueue) -> None:
    queue.register_handler(JOB_TYPE, _handle)
