"""Period Close Agent (ERP/MGA integrity U8).

Soft- or hard-closes a fiscal period and seals the four-fund trial-balance
pack. Idempotent hard close returns the existing pack. Register on the
agent job queue; admin ``POST /api/admin/cashflow/period-close`` can also
run inline.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from services.agent_job_queue import AgentJobQueue

JOB_TYPE = 'period_close'
SUBJECT_TYPE = 'fiscal_period'


def run_once(
    *,
    period_id: str,
    action: str = 'soft',
    actor: str = 'period_close_job',
    engine: Any = None,
    books: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Soft- or hard-close ``period_id`` and return the sealed pack."""
    from services.erp import period_close as pc

    action_norm = str(action or 'soft').strip().lower()
    if action_norm in ('hard', 'hard_close'):
        result = pc.hard_close(period_id, actor=actor, engine=engine, books=books)
    elif action_norm in ('soft', 'soft_close'):
        result = pc.soft_close(period_id, actor=actor, engine=engine, books=books)
    else:
        return {'ok': False, 'reason': f'unknown_action:{action_norm}'}
    result['status'] = pc.status_report(engine=engine)
    return result


def _accounting_engine() -> Any:
    """Engine the admin period-close route seals against.

    A standalone worker's singleton starts empty; hydrate from the journal
    the way the web process does at boot so the sealed trial balance is the
    books, not zeros.
    """
    try:
        from accounting_engine import get_accounting_engine
        engine = get_accounting_engine()
    except Exception:
        return None
    try:
        from services.erp.accounting_journal import hydrate_accounting_engine_from_journal
        hydrate_accounting_engine_from_journal(engine)
    except Exception:
        pass
    return engine


def _handle(job: Dict[str, Any]) -> Dict[str, Any]:
    params = job.get('input_params') or {}
    period_id = str(params.get('period_id') or '').strip()
    if not period_id:
        raise ValueError('period_id is required')
    return run_once(
        period_id=period_id,
        action=str(params.get('action') or 'soft'),
        actor=str(params.get('actor') or 'period_close_job'),
        engine=_accounting_engine(),
        books=params.get('books'),
    )


def enqueue(
    queue: AgentJobQueue,
    *,
    period_id: str,
    action: str = 'soft',
    submitted_by: str = 'system',
    idempotency_key: Optional[str] = None,
) -> Dict[str, Any]:
    action_norm = str(action or 'soft').strip().lower()
    key = idempotency_key or f'period-close:{period_id}:{action_norm}'
    return queue.enqueue(
        job_type=JOB_TYPE,
        subject_type=SUBJECT_TYPE,
        subject_id=str(period_id),
        submitted_by=submitted_by,
        priority=140,
        idempotency_key=key,
        input_params={'period_id': period_id, 'action': action_norm, 'once': True},
        max_attempts=2,
    )


def register(queue: AgentJobQueue) -> None:
    queue.register_handler(JOB_TYPE, _handle)
