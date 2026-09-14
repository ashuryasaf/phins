"""
Agent job adapters for the generalized job queue (A3).

One module per migrated agent, each exposing the job type, an
``enqueue_<x>()`` helper that builds the job row, and the handler that the
queue dispatches to. The handler computes exactly what the synchronous route
computed (golden parity), so a caller receives the same payload whether it
arrived inline (200) or via ``GET /api/jobs/{id}`` after a 202.

``register_all(queue, context)`` binds every adapter onto a queue. The two
bots operate on the portal's in-memory stores, which only the web process
holds, so their handlers are registered only when a ``JobContext`` is
supplied; a standalone worker without one simply never claims those types
(see ``AgentJobQueue._claim_due``).
"""

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional

from services.agent_job_queue import AgentJobQueue

from . import claims_bot_job, pension_import_job, risk_report_job, underwriting_bot_job, video_job

POLL_URL_PREFIX = '/api/jobs/'


@dataclass
class JobContext:
    """Portal stores and helpers the bot handlers need at run time.

    Holds references (not copies) to the live dicts so a handler sees the
    same state as a request thread would.
    """
    customers: Dict[str, Any] = field(default_factory=dict)
    policies: Dict[str, Any] = field(default_factory=dict)
    underwriting_apps: Dict[str, Any] = field(default_factory=dict)
    claims: Dict[str, Any] = field(default_factory=dict)
    audit: Any = None
    sanitize_claim_report: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None


def register_all(queue: AgentJobQueue, context: Optional[JobContext] = None) -> AgentJobQueue:
    """Bind every agent adapter onto ``queue`` (idempotent)."""
    risk_report_job.register(queue)
    pension_import_job.register(queue)
    video_job.register(queue)
    if context is not None:
        underwriting_bot_job.register(queue, context)
        claims_bot_job.register(queue, context)
    return queue


def queued_response(job: Dict[str, Any]) -> Dict[str, Any]:
    """The 202 body every migrated route returns under PHINS_AGENT_ASYNC.

    ``status`` is ``queued`` for a fresh job; an idempotent re-submit that hit
    an existing job reports that job's real status so the client can go
    straight to the result.
    """
    status = job.get('status') or 'pending'
    return {
        'job_id': job['id'],
        'status': 'queued' if status == 'pending' else status,
        'poll_url': f"{POLL_URL_PREFIX}{job['id']}",
    }


# Fields never served over HTTP: inputs can hold uploaded file bytes or a PII
# vault blob, and the worker id is an internal process handle.
_PRIVATE_JOB_FIELDS = ('input_params', 'worker_id')


def public_job_view(job: Dict[str, Any]) -> Dict[str, Any]:
    """Job row as returned by ``GET /api/jobs/{id}`` and admin listings."""
    view = {k: v for k, v in job.items() if k not in _PRIVATE_JOB_FIELDS}
    view['poll_url'] = f"{POLL_URL_PREFIX}{job['id']}"
    return view


__all__ = [
    'JobContext',
    'POLL_URL_PREFIX',
    'claims_bot_job',
    'pension_import_job',
    'public_job_view',
    'queued_response',
    'register_all',
    'risk_report_job',
    'underwriting_bot_job',
    'video_job',
]
