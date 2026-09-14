"""
Async Document Processing Worker
================================
Document binding over the agent-generic ``services.agent_job_queue``.

Since A3 (docs/agent_operations_optimization_design.md) one queue per process
drains ``document_processing_jobs`` for every agent. This module keeps the
document worker's public API — ``DocumentJobWorker``,
``get_document_job_worker()``, ``reset_document_job_worker()`` — so the
upload path, admin routes, ``entrypoint.sh worker`` and existing tests are
unchanged, and binds the document-specific parts onto the shared queue:

* one handler per ``ProcessingJobType`` that calls
  ``DocumentProcessingService.execute_job(document_id, job_type)``;
* a dead-letter hook that flags the parent document ``processing_status``
  as ``failed`` so the UI can surface it.

Queue semantics (idempotency, retry schedule, dead-letter, crash recovery,
concurrency, environment variables) are documented in ``agent_job_queue``.
"""

import logging
from typing import Any, Dict, Optional

from services.agent_job_queue import (  # noqa: F401  (re-exported)
    AgentJobQueue,
    DOCUMENT_SUBJECT,
    TERMINAL_STATUSES,
    get_job_queue,
    reset_job_queue,
)

logger = logging.getLogger(__name__)


def _document_job_types():
    from services.document_processing_service import ProcessingJobType
    return [member.value for member in ProcessingJobType]


class _DocumentBinding:
    """Document handlers for a queue; resolves the service lazily at call time
    so a service bound (or monkeypatched) after construction is honoured."""

    def __init__(self, queue: AgentJobQueue, doc_service=None):
        self.queue = queue
        self.doc_service_override = doc_service

    @property
    def doc_service(self):
        if self.doc_service_override is None:
            from services.document_processing_service import get_document_service
            self.doc_service_override = get_document_service(db_manager=self.queue.db_manager)
        return self.doc_service_override

    def handle(self, job: Dict[str, Any]) -> Any:
        document_id = job.get('document_id') or job.get('subject_id')
        return self.doc_service.execute_job(document_id, job['job_type'])

    def dead_letter(self, job: Dict[str, Any], _error: str) -> None:
        document_id = job.get('document_id') or job.get('subject_id')
        try:
            self.doc_service._update_record(document_id, {'processing_status': 'failed'})
        except Exception as exc:
            logger.error(f"Could not flag document {document_id} as failed: {exc}")


def bind_document_handlers(queue: AgentJobQueue, doc_service=None) -> _DocumentBinding:
    """Register the document job types and dead-letter hook on ``queue``.

    Idempotent: a queue that already has a binding keeps it (and adopts
    ``doc_service`` if it had none yet).
    """
    binding = getattr(queue, '_document_binding', None)
    if binding is None:
        binding = _DocumentBinding(queue, doc_service)
        for job_type in _document_job_types():
            queue.register_handler(job_type, binding.handle)
        queue.register_dead_letter_hook(DOCUMENT_SUBJECT, binding.dead_letter)
        queue._document_binding = binding  # type: ignore[attr-defined]
    elif doc_service is not None and binding.doc_service_override is None:
        binding.doc_service_override = doc_service
    return binding


class DocumentJobWorker(AgentJobQueue):
    """The agent job queue with document handlers bound at construction."""

    def __init__(
        self,
        doc_service=None,
        db_manager=None,
        concurrency: Optional[int] = None,
        poll_interval: Optional[float] = None,
        max_concurrency: Optional[int] = None,
    ):
        super().__init__(db_manager=db_manager, concurrency=concurrency,
                         poll_interval=poll_interval, max_concurrency=max_concurrency)
        bind_document_handlers(self, doc_service)

    @property
    def doc_service(self):
        return self._document_binding.doc_service  # type: ignore[attr-defined]


# ── Module-level singleton (shared with agent_job_queue) ──────────────────────

def get_document_job_worker(doc_service=None, db_manager=None) -> AgentJobQueue:
    """Return the process-wide queue with document handlers bound.

    ``get_job_queue()`` already creates a ``DocumentJobWorker``; this binds a
    caller-supplied service onto it (first binding wins) and, should a bare
    queue have been installed, adds the document handlers to it rather than
    creating a second, competing queue.
    """
    queue = get_job_queue(db_manager=db_manager)
    bind_document_handlers(queue, doc_service)
    return queue


def reset_document_job_worker() -> None:
    """Stop and drop the shared singleton (mainly for tests)."""
    reset_job_queue()
