"""Daily books-tied certificate clock (ERP/MGA integrity U6).

Evaluates Money Gate critical checks and, when green, appends today's sealed
``finance.books_tied`` ledger event. Reschedules itself toward the next UTC
midnight (plus five minutes) so the certificate renews once per day without
consuming retry attempts. ``ensure_daily_clock`` is idempotent.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from services.agent_job_queue import AgentJobQueue, RescheduleJob

JOB_TYPE = 'books_tied_daily'
SUBJECT_TYPE = 'books_tied'
SUBJECT_ID = 'global'
IDEMPOTENCY_KEY = 'books-tied-daily-clock'


def run_once(
    *,
    books: Optional[Dict[str, Any]] = None,
    ledger: Any = None,
    actor: str = 'books_tied_job',
) -> Dict[str, Any]:
    """Evaluate books and issue today's certificate when green."""
    from services.erp.books_tied import issue_certificate, status_report
    from services.erp.money_gate import evaluate_money_gate

    if ledger is None:
        ledger = _portal_ledger()
    verdict = evaluate_money_gate(books=books, operation='books_tied.daily')
    issued = issue_certificate(
        ledger,
        verdict=verdict,
        actor=actor,
    )
    return {
        'verdict': verdict.as_dict(),
        'certificate': issued,
        'status': status_report(ledger),
    }


def _portal_ledger() -> Any:
    try:
        import sys
        portal = sys.modules.get('web_portal.server') or sys.modules.get('server')
        if portal is None:
            return None
        return getattr(portal, 'platform_event_ledger', None)
    except Exception:
        return None


def _handle(job: Dict[str, Any]) -> Dict[str, Any]:
    from services.erp.books_tied import seconds_until_next_utc_midnight

    params = job.get('input_params') or {}
    result = run_once(books=params.get('books'), actor=str(params.get('actor') or 'books_tied_job'))
    if params.get('once'):
        return result
    delay = seconds_until_next_utc_midnight()
    issued = bool((result.get('certificate') or {}).get('issued'))
    raise RescheduleJob(
        delay,
        f"books_tied daily: issued={issued} reason={(result.get('certificate') or {}).get('reason')}",
    )


def ensure_daily_clock(queue: AgentJobQueue, *, submitted_by: str = 'system') -> Dict[str, Any]:
    """Enqueue the recurring daily clock exactly once (idempotent)."""
    return queue.enqueue(
        job_type=JOB_TYPE,
        subject_type=SUBJECT_TYPE,
        subject_id=SUBJECT_ID,
        submitted_by=submitted_by,
        priority=130,
        idempotency_key=IDEMPOTENCY_KEY,
        input_params={'once': False},
    )


def enqueue_once(
    queue: AgentJobQueue,
    *,
    submitted_by: str = 'system',
    idempotency_key: Optional[str] = None,
    books: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return queue.enqueue(
        job_type=JOB_TYPE,
        subject_type=SUBJECT_TYPE,
        subject_id=SUBJECT_ID,
        submitted_by=submitted_by,
        priority=140,
        idempotency_key=idempotency_key,
        input_params={'once': True, 'books': books},
        max_attempts=2,
    )


def register(queue: AgentJobQueue) -> None:
    queue.register_handler(JOB_TYPE, _handle)
