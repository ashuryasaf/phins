"""
Delivery Bidding SLA clock (B11): one recurring queue job that closes elapsed
bidding windows (``DeliveryBiddingService.expire_bidding_windows``).

The job reschedules itself with ``RescheduleJob`` — the same row ticks every
``PHINS_DELIVERY_SLA_TICK_SECONDS`` (default 60 s) without consuming retry
attempts, and survives a restart because the pending row is durable in DB
mode. ``ensure_sla_clock`` is idempotent (fixed idempotency key), so any
number of web/worker processes calling it at startup share one clock.

Expiry is also applied lazily on every bid/read of an overdue request, so
correctness never depends on this job running; it only bounds how long a
closed window can go unnoticed (and its outbox event unemitted) when nobody
touches the request.
"""

import os
from typing import Any, Dict, Optional

from services.agent_job_queue import AgentJobQueue, RescheduleJob

JOB_TYPE = 'delivery_bidding_sla_tick'
SUBJECT_TYPE = 'delivery_sla_clock'
SUBJECT_ID = 'global'
IDEMPOTENCY_KEY = 'delivery-bidding-sla-clock'
DEFAULT_TICK_SECONDS = 60.0


def tick_seconds() -> float:
    try:
        value = float(os.environ.get('PHINS_DELIVERY_SLA_TICK_SECONDS', DEFAULT_TICK_SECONDS))
    except (TypeError, ValueError):
        value = DEFAULT_TICK_SECONDS
    return max(1.0, value)


def run_tick() -> Dict[str, Any]:
    from services.delivery_bidding_service import get_delivery_bidding_service
    return get_delivery_bidding_service().expire_bidding_windows()


def _handle(job: Dict[str, Any]) -> Dict[str, Any]:
    params = job.get('input_params') or {}
    result = run_tick()
    if params.get('once'):
        return result
    # Recurring: same row, next tick. The sweep result is not persisted per
    # tick (it would be a new row per minute); transitions are recorded on the
    # requests, the tracking log and the outbox.
    raise RescheduleJob(tick_seconds(), f"sla tick: closed={result['closed']} cancelled={result['cancelled']}")


def ensure_sla_clock(queue: AgentJobQueue, *, submitted_by: str = 'system') -> Dict[str, Any]:
    """Enqueue the recurring clock exactly once per queue (idempotent)."""
    return queue.enqueue(
        job_type=JOB_TYPE,
        subject_type=SUBJECT_TYPE,
        subject_id=SUBJECT_ID,
        submitted_by=submitted_by,
        priority=200,
        idempotency_key=IDEMPOTENCY_KEY,
        input_params={'once': False},
    )


def enqueue_once(queue: AgentJobQueue, *, submitted_by: str = 'system',
                 idempotency_key: Optional[str] = None) -> Dict[str, Any]:
    """A single sweep (operator request); completes with the sweep summary."""
    return queue.enqueue(
        job_type=JOB_TYPE,
        subject_type=SUBJECT_TYPE,
        subject_id=SUBJECT_ID,
        submitted_by=submitted_by,
        priority=150,
        idempotency_key=idempotency_key,
        input_params={'once': True},
        max_attempts=1,
    )


def register(queue: AgentJobQueue) -> None:
    queue.register_handler(JOB_TYPE, _handle)
