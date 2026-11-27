"""Books Integrity Agent job (ERP/MGA integrity U4 / U6).

Computes the Money Gate critical-check digest from
``reconcile_financial_books`` + the unified cash-flow statement. Writes
nothing to the money books. When ``issue_certificate`` is set (or under the
daily U6 clock), a green verdict also seals ``finance.books_tied`` on the
platform ledger via ``services.erp.books_tied``.

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


def run_once(
    *,
    books: Optional[Dict[str, Any]] = None,
    operation: str = 'books_integrity',
    issue_certificate: bool = False,
    ledger: Any = None,
) -> Dict[str, Any]:
    """Evaluate critical checks; optionally seal today's books-tied cert."""
    from services.erp.money_gate import evaluate_money_gate

    verdict = evaluate_money_gate(books=books, operation=operation)
    result = verdict.as_dict()
    if issue_certificate:
        from services.erp.books_tied import issue_certificate as _issue

        if ledger is None:
            try:
                import sys
                portal = sys.modules.get('web_portal.server') or sys.modules.get('server')
                ledger = getattr(portal, 'platform_event_ledger', None) if portal else None
            except Exception:
                ledger = None
        result['certificate'] = _issue(ledger, verdict=verdict, actor='books_integrity')
    return result


def _handle(job: Dict[str, Any]) -> Dict[str, Any]:
    params = job.get('input_params') or {}
    return run_once(
        books=params.get('books'),
        operation=str(params.get('operation') or 'books_integrity'),
        issue_certificate=bool(params.get('issue_certificate')),
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
