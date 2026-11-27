"""Daily books-tied certificate clock (ERP/MGA integrity U6).

Evaluates Money Gate critical checks and, when green, appends today's sealed
``finance.books_tied`` ledger event. On success (or already issued),
reschedules toward the next UTC midnight (+5 minutes). On failure (red
books, missing ledger, exception), retries sooner the same day so payouts
are not stranded until tomorrow. ``ensure_daily_clock`` is idempotent.

When the agent job queue is not running (``PHINS_AGENT_ASYNC`` / doc async
default off), ``start_inprocess_daily_clock`` still issues at boot and arms a
daemon ``threading.Timer`` so production freshness stays green without those
flags.
"""

from __future__ import annotations

import os
import threading
from typing import Any, Dict, Optional

from services.agent_job_queue import AgentJobQueue, RescheduleJob

JOB_TYPE = 'books_tied_daily'
SUBJECT_TYPE = 'books_tied'
SUBJECT_ID = 'global'
IDEMPOTENCY_KEY = 'books-tied-daily-clock'
# Failed seals retry the same UTC day. Five minutes matches the post-midnight
# clock offset (Bugbot Autofix) and stays overridable via env.
ISSUE_RETRY_SECONDS = 300.0
DEFAULT_RETRY_SECONDS = ISSUE_RETRY_SECONDS

_INPROCESS_LOCK = threading.Lock()
_INPROCESS_STARTED = False
_INPROCESS_TIMER: Optional[threading.Timer] = None


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


def retry_seconds() -> float:
    try:
        value = float(os.environ.get('PHINS_BOOKS_TIED_RETRY_SECONDS', DEFAULT_RETRY_SECONDS))
    except (TypeError, ValueError):
        value = DEFAULT_RETRY_SECONDS
    return max(60.0, min(value, 12 * 3600.0))


def next_delay(run_result: Optional[Dict[str, Any]] = None) -> float:
    """Next wake: midnight+5m after a good seal, else a same-day retry."""
    from services.erp.books_tied import seconds_until_next_utc_midnight

    cert = None
    if isinstance(run_result, dict):
        cert = run_result.get('certificate')
        if not isinstance(cert, dict) and 'issued' in run_result:
            cert = run_result
    reason = str((cert or {}).get('reason') or '')
    issued = bool((cert or {}).get('issued'))
    if issued or reason == 'already_issued':
        return seconds_until_next_utc_midnight()
    # books_red / ledger_unavailable / tampered / boot_error → retry sooner
    return min(retry_seconds(), seconds_until_next_utc_midnight())


def _handle(job: Dict[str, Any]) -> Dict[str, Any]:
    params = job.get('input_params') or {}
    try:
        result = run_once(
            books=params.get('books'),
            actor=str(params.get('actor') or 'books_tied_job'),
        )
    except Exception as exc:
        if params.get('once'):
            raise
        raise RescheduleJob(
            ISSUE_RETRY_SECONDS,
            f"books_tied daily: error={exc}",
        ) from exc
    if params.get('once'):
        return result
    delay = next_delay(result)
    issued = bool((result.get('certificate') or {}).get('issued'))
    raise RescheduleJob(
        delay,
        f"books_tied daily: issued={issued} reason={(result.get('certificate') or {}).get('reason')} delay={delay:.0f}s",
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


def _inprocess_tick() -> None:
    """Daemon timer body: issue today's cert, then re-arm (retry or next day)."""
    global _INPROCESS_TIMER
    run_result: Optional[Dict[str, Any]] = None
    try:
        run_result = run_once(actor='books_tied_inprocess')
    except Exception as exc:
        run_result = {'certificate': {'issued': False, 'reason': f'tick_error:{exc}'}}
    try:
        delay = next_delay(run_result)
    except Exception:
        delay = retry_seconds()
    timer = threading.Timer(delay, _inprocess_tick)
    timer.daemon = True
    with _INPROCESS_LOCK:
        _INPROCESS_TIMER = timer
        timer.start()


def start_inprocess_daily_clock(*, issue_now: bool = True) -> Dict[str, Any]:
    """Issue (optional) and arm a process-local daily timer (idempotent).

    Used on the default ``serve`` path so ``PHINS_BOOKS_TIED_REQUIRE`` can
    stay on without needing ``PHINS_AGENT_ASYNC``. Best-effort and never
    raises into the caller.
    """
    global _INPROCESS_STARTED
    result: Dict[str, Any] = {'started': False, 'certificate': None}
    with _INPROCESS_LOCK:
        already = _INPROCESS_STARTED
        if not already:
            _INPROCESS_STARTED = True
    if issue_now:
        try:
            result['certificate'] = run_once(actor='books_tied_boot')
        except Exception as exc:
            result['certificate'] = {
                'issued': False,
                'reason': f'boot_error:{exc}',
            }
    if already:
        result['started'] = True
        result['reason'] = 'already_started'
        return result
    try:
        delay = next_delay(result.get('certificate'))
        timer = threading.Timer(delay, _inprocess_tick)
        timer.daemon = True
        with _INPROCESS_LOCK:
            global _INPROCESS_TIMER
            _INPROCESS_TIMER = timer
            timer.start()
        result['started'] = True
        result['next_tick_seconds'] = delay
        result['reason'] = 'armed'
    except Exception as exc:
        result['started'] = False
        result['reason'] = f'timer_error:{exc}'
    return result
