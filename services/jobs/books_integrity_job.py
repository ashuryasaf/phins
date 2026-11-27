"""Books Integrity Agent job (ERP/MGA integrity U4).

Computes the Money Gate critical-check digest from
``reconcile_financial_books`` + the unified cash-flow statement. Writes
nothing to the money books — the result is the job payload (and optional
agent_artifact later in U6 for the daily ``finance.books_tied`` cert).

Under ``PHINS_AGENT_ASYNC`` callers can enqueue; otherwise ``run_once`` is
the synchronous evaluate path the Money Gate itself uses via
``evaluate_money_gate``.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from services.agent_job_queue import AgentJobQueue

JOB_TYPE = 'books_integrity_evaluate'
SUBJECT_TYPE = 'books_integrity'
SUBJECT_ID = 'global'


def run_once(*, books: Optional[Dict[str, Any]] = None, operation: str = 'books_integrity') -> Dict[str, Any]:
    """Evaluate critical checks; return the Money Gate verdict dict."""
    from services.erp.money_gate import evaluate_money_gate

    verdict = evaluate_money_gate(books=books, operation=operation)
    return verdict.as_dict()


def _handle(job: Dict[str, Any]) -> Dict[str, Any]:
    params = job.get('input_params') or {}
    return run_once(
        books=params.get('books'),
        operation=str(params.get('operation') or 'books_integrity'),
    )


def enqueue(
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
        priority=120,
        idempotency_key=idempotency_key,
        input_params={'books': books, 'operation': 'books_integrity'},
        max_attempts=2,
    )


def register(queue: AgentJobQueue) -> None:
    queue.register_handler(JOB_TYPE, _handle)
