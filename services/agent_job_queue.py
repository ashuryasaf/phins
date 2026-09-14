"""
Agent Job Queue
===============
Durable, agent-generic job queue that moves heavy agent work (document
enrichment, Underwriting/Claims Bot evaluations, risk reports, pension
imports, video generation) off the HTTP handler thread.

Generalized from ``services/document_job_worker.py`` (design:
docs/agent_operations_optimization_design.md §A3). The document worker is now
a thin binding on top of this module and keeps its public API.

Semantics (unchanged from the document worker, now per job type):

* **One table** — ``document_processing_jobs`` when a database is available;
  an in-memory list with identical semantics otherwise. Non-document jobs
  carry ``subject_type``/``subject_id`` (``claim``, ``application``,
  ``report``, ``pension_import``, ``video_job``); document jobs keep
  ``document_id`` and mirror it into the subject pair.
* **Handlers** — ``register_handler(job_type, fn)``; ``fn(job) -> result``
  receives the job view (a dict) and returns a JSON-serialisable result.
  A worker only claims job types it has a handler for, so a job nobody in
  the process can run stays ``pending`` (visible in ``queue_stats``) for a
  worker that can — it is never taken, failed and dead-lettered by mistake.
* **Idempotency** — duplicate ``idempotency_key`` enqueues return the
  existing job; a completed job with the same key is not re-run.
* **Retries** — transient failures back off along ``PHINS_DOC_RETRY_SCHEDULE``
  (default 30s, 2m, 10m); exhausted jobs land in ``dead_letter`` for operator
  action (requeue) instead of disappearing.
* **Crash recovery** — a claim stamps its expiry into ``next_retry_at``; a
  crashed worker's claim simply expires and the job is claimable again.
* **Concurrency** — ``PHINS_DOC_WORKER_CONCURRENCY`` threads always run;
  when ``PHINS_JOB_WORKER_MAX_CONCURRENCY`` is higher, extra threads are
  added while the pending backlog exceeds the running thread count and exit
  again after ``PHINS_JOB_WORKER_IDLE_POLLS`` consecutive empty polls.
* **Topology** — daemon threads inside the web process (``start()``) and the
  same loop one-shot (``process_once()``) from cron / ``entrypoint.sh worker``.

Environment:
    PHINS_DOC_WORKER_CONCURRENCY      baseline worker threads (default 2)
    PHINS_JOB_WORKER_MAX_CONCURRENCY  upper bound for burst threads (default = baseline)
    PHINS_JOB_WORKER_IDLE_POLLS       empty polls before a burst thread exits (default 5)
    PHINS_DOC_WORKER_POLL_INTERVAL    seconds between polls (default 2.0)
    PHINS_DOC_RETRY_SCHEDULE          comma seconds, e.g. "30,120,600"
    PHINS_DOC_CLAIM_TIMEOUT           claim expiry seconds (default 600)
"""

import json
import logging
import os
import threading
import time
import uuid
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

TERMINAL_STATUSES = ('completed', 'dead_letter')

DOCUMENT_SUBJECT = 'document'

JobHandler = Callable[[Dict[str, Any]], Any]
DeadLetterHook = Callable[[Dict[str, Any], str], None]

# Event names emitted through ``event_hook``. Document jobs keep the names the
# platform event ledger has recorded since the pipeline shipped; every other
# subject uses the generic JOB_* names.
_DOCUMENT_EVENTS = {
    'queued': 'DOCUMENT_QUEUED',
    'started': 'DOCUMENT_PROCESSING_STARTED',
    'completed': 'DOCUMENT_PARSED',
    'failed': 'PROCESSING_FAILED',
}
_GENERIC_EVENTS = {
    'queued': 'JOB_QUEUED',
    'started': 'JOB_STARTED',
    'completed': 'JOB_COMPLETED',
    'failed': 'JOB_FAILED',
}


def _retry_schedule() -> List[int]:
    raw = os.environ.get('PHINS_DOC_RETRY_SCHEDULE', '30,120,600')
    try:
        schedule = [max(1, int(p.strip())) for p in raw.split(',') if p.strip()]
    except ValueError:
        schedule = [30, 120, 600]
    return schedule or [30, 120, 600]


def agent_async_enabled() -> bool:
    """True when migrated agent routes should enqueue and answer 202.

    Controlled by ``PHINS_AGENT_ASYNC``; defaults to off (mirrors
    ``PHINS_DOC_ASYNC``) so every existing synchronous response is unchanged
    until an operator opts in.
    """
    return str(os.environ.get('PHINS_AGENT_ASYNC', '')).strip().lower() in ('1', 'true', 'yes', 'y', 'on')


def _env_int(name: str, default: int, minimum: int = 0) -> int:
    try:
        return max(minimum, int(os.environ.get(name, str(default))))
    except (TypeError, ValueError):
        return default


class AgentJobQueue:
    """Claims and executes jobs by registered ``job_type`` with retry + DLQ."""

    def __init__(
        self,
        db_manager=None,
        concurrency: Optional[int] = None,
        poll_interval: Optional[float] = None,
        max_concurrency: Optional[int] = None,
    ):
        self.db_manager = db_manager
        self.concurrency = concurrency or _env_int('PHINS_DOC_WORKER_CONCURRENCY', 2, minimum=1)
        self.max_concurrency = max(
            self.concurrency,
            max_concurrency or _env_int('PHINS_JOB_WORKER_MAX_CONCURRENCY', self.concurrency, minimum=1),
        )
        self.idle_polls_before_exit = _env_int('PHINS_JOB_WORKER_IDLE_POLLS', 5, minimum=1)
        self.poll_interval = poll_interval if poll_interval is not None else float(
            os.environ.get('PHINS_DOC_WORKER_POLL_INTERVAL', '2.0'))
        self.claim_timeout = _env_int('PHINS_DOC_CLAIM_TIMEOUT', 600, minimum=1)
        self.retry_schedule = _retry_schedule()
        self.worker_id = f"worker-{os.getpid()}-{uuid.uuid4().hex[:6]}"
        # Structured-event hook, wired by the server to the platform event
        # ledger. Signature: hook(event_type, subject_id, payload); payload
        # always carries job_id, job_type and subject_type.
        self.event_hook: Optional[Callable[[str, str, Dict[str, Any]], None]] = None
        # Post-completion hook. Signature: hook(subject_id, job_type, result).
        self.completion_hook: Optional[Callable[[str, str, Dict[str, Any]], None]] = None

        self._handlers: Dict[str, JobHandler] = {}
        self._dead_letter_hooks: Dict[str, DeadLetterHook] = {}
        self._lock = threading.RLock()
        self._inmemory_jobs: List[Dict[str, Any]] = []
        self._threads: List[threading.Thread] = []
        self._stop_event = threading.Event()
        self._thread_seq = 0

    # ── Handler registry ──────────────────────────────────────────────────

    def register_handler(self, job_type: str, handler: JobHandler) -> None:
        """Bind ``handler(job) -> result`` to ``job_type`` (replaces any prior)."""
        if not job_type or not callable(handler):
            raise ValueError('job_type and a callable handler are required')
        with self._lock:
            self._handlers[str(job_type)] = handler

    def unregister_handler(self, job_type: str) -> None:
        with self._lock:
            self._handlers.pop(str(job_type), None)

    def handlers(self) -> List[str]:
        with self._lock:
            return sorted(self._handlers)

    def register_dead_letter_hook(self, subject_type: str, hook: DeadLetterHook) -> None:
        """Called once, with ``(job, error)``, when a job of ``subject_type``
        exhausts its attempts — e.g. to flag the parent record as failed."""
        with self._lock:
            self._dead_letter_hooks[str(subject_type)] = hook

    def _use_db(self) -> bool:
        return self.db_manager is not None

    # ── Enqueue ───────────────────────────────────────────────────────────

    def enqueue(
        self,
        *,
        job_type: str,
        document_id: Optional[str] = None,
        subject_type: Optional[str] = None,
        subject_id: Optional[str] = None,
        submitted_by: Optional[str] = None,
        priority: int = 100,
        idempotency_key: Optional[str] = None,
        input_params: Optional[Dict[str, Any]] = None,
        max_attempts: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Queue a job. Duplicate idempotency keys return the existing job.

        A completed job with the same key is NOT re-run (duplicate delivery
        safety); operators can force a re-run by enqueueing without a key.
        Document jobs pass ``document_id``; every other agent passes
        ``subject_type`` + ``subject_id``.
        """
        if not job_type:
            raise ValueError('job_type is required')
        if document_id:
            subject_type = subject_type or DOCUMENT_SUBJECT
            subject_id = subject_id or document_id
        if not subject_id or not subject_type:
            raise ValueError('document_id or subject_type/subject_id is required')
        resolved_max = max_attempts or (len(self.retry_schedule) + 1)

        if idempotency_key:
            existing = self._find_by_idempotency_key(idempotency_key)
            if existing is not None:
                return existing

        job = {
            'id': f"JOB-{uuid.uuid4().hex[:12].upper()}",
            'document_id': document_id,
            'subject_type': subject_type,
            'subject_id': subject_id,
            'submitted_by': submitted_by,
            'job_type': job_type,
            'status': 'pending',
            'attempts': 0,
            'max_attempts': resolved_max,
            'next_retry_at': None,
            'priority': priority,
            'idempotency_key': idempotency_key,
            'worker_id': None,
            'input_params': json.dumps(input_params, default=str) if input_params else None,
            'result': None,
            'error_message': None,
            'processing_time_ms': None,
            'created_date': datetime.utcnow(),
            'completed_date': None,
        }

        if self._use_db():
            try:
                created = self.db_manager.processing_jobs.create(**job)
                if created is not None:
                    view = created.to_dict()
                    self._emit('queued', view, {})
                    return view
            except Exception as exc:
                logger.error(f"DB enqueue failed, using in-memory queue: {exc}")

        with self._lock:
            self._inmemory_jobs.append(job)
        view = self._job_view(job)
        self._emit('queued', view, {})
        return view

    def _find_by_idempotency_key(self, key: str) -> Optional[Dict[str, Any]]:
        if self._use_db():
            try:
                existing = self.db_manager.processing_jobs.get_by_idempotency_key(key)
                if existing is not None:
                    return existing.to_dict()
            except Exception as exc:
                logger.error(f"Idempotency lookup failed: {exc}")
        with self._lock:
            for job in self._inmemory_jobs:
                if job.get('idempotency_key') == key:
                    return self._job_view(job)
        return None

    # ── Execution ─────────────────────────────────────────────────────────

    def process_once(self, limit: int = 10) -> Dict[str, Any]:
        """Claim and run up to ``limit`` due jobs. Returns run statistics."""
        stats = {'claimed': 0, 'completed': 0, 'failed': 0, 'dead_letter': 0}
        for claimed in self._claim_due(limit):
            stats['claimed'] += 1
            outcome = self._execute(claimed)
            stats[outcome] += 1
        return stats

    def _claim_due(self, limit: int) -> List[Dict[str, Any]]:
        # Only claim what this process can execute: a worker lacking the
        # handler must leave the job pending for one that has it, never take
        # it, fail it and burn its retries.
        job_types = self.handlers()
        if not job_types:
            return []
        if self._use_db():
            try:
                rows = self.db_manager.processing_jobs.claim_due_jobs(
                    worker_id=self.worker_id, limit=limit,
                    claim_timeout_seconds=self.claim_timeout,
                    job_types=job_types,
                )
                return [row.to_dict() for row in rows]
            except Exception as exc:
                logger.error(f"DB claim failed: {exc}")
                return []

        now = datetime.utcnow()
        claimed: List[Dict[str, Any]] = []
        with self._lock:
            due = [
                j for j in self._inmemory_jobs
                if j['job_type'] in job_types and (
                    j['status'] == 'pending'
                    or (j['status'] in ('failed', 'claimed')
                        and j.get('next_retry_at') is not None
                        and j['next_retry_at'] <= now))
            ]
            due.sort(key=lambda j: (j.get('priority', 100), j['created_date']))
            for job in due[:limit]:
                job['status'] = 'claimed'
                job['worker_id'] = self.worker_id
                job['next_retry_at'] = now + timedelta(seconds=self.claim_timeout)
                claimed.append(self._job_view(job))
        return claimed

    def _resolve_handler(self, job_type: str) -> JobHandler:
        with self._lock:
            handler = self._handlers.get(job_type)
        if handler is None:
            raise LookupError(f"no handler registered for job_type '{job_type}'")
        return handler

    def _execute(self, job: Dict[str, Any]) -> str:
        """Run one claimed job; returns 'completed' | 'failed' | 'dead_letter'."""
        job_id = job['id']
        job_type = job['job_type']
        attempts = int(job.get('attempts') or 0) + 1
        max_attempts = int(job.get('max_attempts') or (len(self.retry_schedule) + 1))
        start = time.time()

        self._emit('started', job, {'attempt': attempts})
        try:
            handler = self._resolve_handler(job_type)
            result = handler(job)
            elapsed_ms = int((time.time() - start) * 1000)
            self._update_job(job_id, {
                'status': 'completed',
                'attempts': attempts,
                'result': json.dumps(result, default=str) if result else None,
                'error_message': None,
                'processing_time_ms': elapsed_ms,
                'next_retry_at': None,
                'completed_date': datetime.utcnow(),
            })
            self._emit('completed', job, {'processing_time_ms': elapsed_ms})
            if self.completion_hook:
                try:
                    self.completion_hook(job.get('subject_id'), job_type, result or {})
                except Exception as hook_exc:
                    logger.error(f"Completion hook failed for {job_id}: {hook_exc}")
            return 'completed'
        except Exception as exc:
            elapsed_ms = int((time.time() - start) * 1000)
            error_text = str(exc)[:2000]
            if attempts >= max_attempts:
                self._update_job(job_id, {
                    'status': 'dead_letter',
                    'attempts': attempts,
                    'error_message': error_text,
                    'processing_time_ms': elapsed_ms,
                    'next_retry_at': None,
                    'completed_date': datetime.utcnow(),
                })
                self._run_dead_letter_hook(job, error_text)
                self._emit('failed', job, {'error': error_text, 'final': True})
                logger.error(f"Job {job_id} dead-lettered after {attempts} attempts: {error_text}")
                return 'dead_letter'
            delay = self.retry_schedule[min(attempts - 1, len(self.retry_schedule) - 1)]
            self._update_job(job_id, {
                'status': 'failed',
                'attempts': attempts,
                'error_message': error_text,
                'processing_time_ms': elapsed_ms,
                'next_retry_at': datetime.utcnow() + timedelta(seconds=delay),
            })
            self._emit('failed', job, {'error': error_text, 'retry_in_seconds': delay})
            logger.warning(f"Job {job_id} attempt {attempts} failed, retry in {delay}s: {error_text}")
            return 'failed'

    def _run_dead_letter_hook(self, job: Dict[str, Any], error_text: str) -> None:
        with self._lock:
            hook = self._dead_letter_hooks.get(str(job.get('subject_type') or ''))
        if hook is None:
            return
        try:
            hook(job, error_text)
        except Exception as exc:
            logger.error(f"Dead-letter hook failed for {job.get('id')}: {exc}")

    def _update_job(self, job_id: str, updates: Dict[str, Any]) -> None:
        if self._use_db():
            try:
                if self.db_manager.processing_jobs.update(job_id, **updates) is not None:
                    return
            except Exception as exc:
                logger.error(f"DB job update failed for {job_id}: {exc}")
        with self._lock:
            for job in self._inmemory_jobs:
                if job['id'] == job_id:
                    job.update(updates)
                    return

    # ── Introspection / operator API ──────────────────────────────────────

    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        if not job_id:
            return None
        if self._use_db():
            try:
                row = self.db_manager.processing_jobs.get_by_id(job_id)
                if row is not None:
                    return row.to_dict()
            except Exception as exc:
                logger.error(f"Get job failed for {job_id}: {exc}")
        with self._lock:
            for job in self._inmemory_jobs:
                if job['id'] == job_id:
                    return self._job_view(job)
        return None

    def queue_stats(self) -> Dict[str, int]:
        if self._use_db():
            try:
                return self.db_manager.processing_jobs.count_by_status()
            except Exception as exc:
                logger.error(f"Queue stats failed: {exc}")
        with self._lock:
            stats: Dict[str, int] = {}
            for job in self._inmemory_jobs:
                stats[job['status']] = stats.get(job['status'], 0) + 1
            return stats

    def list_jobs(self, status: Optional[str] = None,
                  document_id: Optional[str] = None,
                  limit: int = 50,
                  subject_type: Optional[str] = None,
                  subject_id: Optional[str] = None,
                  job_type: Optional[str] = None,
                  submitted_by: Optional[str] = None) -> List[Dict[str, Any]]:
        if self._use_db():
            try:
                repo = self.db_manager.processing_jobs
                if document_id:
                    rows = repo.get_by_document(document_id)
                elif subject_id or subject_type or job_type or submitted_by:
                    rows = repo.find_jobs(
                        status=status, subject_type=subject_type, subject_id=subject_id,
                        job_type=job_type, submitted_by=submitted_by, limit=limit,
                    )
                    status = None
                elif status:
                    rows = repo.filter_by(status=status)
                else:
                    rows = repo.get_all(limit=limit)
                views = [r.to_dict() for r in rows]
                if status:
                    views = [v for v in views if v.get('status') == status]
                return views[:limit]
            except Exception as exc:
                logger.error(f"List jobs failed: {exc}")
        with self._lock:
            jobs = list(self._inmemory_jobs)
        if status:
            jobs = [j for j in jobs if j['status'] == status]
        if document_id:
            jobs = [j for j in jobs if j['document_id'] == document_id]
        if subject_type:
            jobs = [j for j in jobs if j.get('subject_type') == subject_type]
        if subject_id:
            jobs = [j for j in jobs if j.get('subject_id') == subject_id]
        if job_type:
            jobs = [j for j in jobs if j.get('job_type') == job_type]
        if submitted_by:
            jobs = [j for j in jobs if j.get('submitted_by') == submitted_by]
        jobs.sort(key=lambda j: j['created_date'], reverse=True)
        return [self._job_view(j) for j in jobs[:limit]]

    def requeue_dead_letter(self, job_id: str) -> bool:
        if self._use_db():
            try:
                return self.db_manager.processing_jobs.requeue_dead_letter(job_id)
            except Exception as exc:
                logger.error(f"Requeue failed for {job_id}: {exc}")
                return False
        with self._lock:
            for job in self._inmemory_jobs:
                if job['id'] == job_id and job['status'] == 'dead_letter':
                    job.update({
                        'status': 'pending', 'attempts': 0,
                        'next_retry_at': None, 'error_message': None,
                        'worker_id': None,
                    })
                    return True
        return False

    # ── Background loop ───────────────────────────────────────────────────

    def start(self) -> None:
        """Spawn the baseline daemon worker threads (idempotent)."""
        with self._lock:
            if self._alive_threads():
                return
            self._stop_event.clear()
            self._threads = []
            for _ in range(max(1, self.concurrency)):
                self._spawn_thread(burst=False)
        logger.info(f"Agent job queue started ({len(self._threads)} threads, "
                    f"max {self.max_concurrency}, poll {self.poll_interval}s, "
                    f"retries {self.retry_schedule})")

    def stop(self, timeout: float = 5.0) -> None:
        self._stop_event.set()
        for thread in list(self._threads):
            thread.join(timeout=timeout)
        self._threads = []

    def active_threads(self) -> int:
        with self._lock:
            return len(self._alive_threads())

    def _alive_threads(self) -> List[threading.Thread]:
        self._threads = [t for t in self._threads if t.is_alive()]
        return self._threads

    def _spawn_thread(self, burst: bool) -> threading.Thread:
        self._thread_seq += 1
        thread = threading.Thread(
            target=self._loop,
            kwargs={'burst': burst},
            name=f"job-worker-{self._thread_seq}{'-burst' if burst else ''}",
            daemon=True,
        )
        thread.start()
        self._threads.append(thread)
        return thread

    def _maybe_scale_up(self, pending: int) -> int:
        """Add burst threads while the backlog exceeds the running thread count.

        Returns the number of threads spawned. Bounded by ``max_concurrency``
        and only ever adds one thread per call so a single poll cannot spike
        the pool.
        """
        with self._lock:
            alive = len(self._alive_threads())
            if self._stop_event.is_set() or alive >= self.max_concurrency or pending <= alive:
                return 0
            self._spawn_thread(burst=True)
            return 1

    def _loop(self, burst: bool = False) -> None:
        idle_polls = 0
        while not self._stop_event.is_set():
            try:
                stats = self.process_once()
                if stats['claimed']:
                    idle_polls = 0
                    if self.max_concurrency > self.concurrency:
                        pending = self.queue_stats().get('pending', 0)
                        self._maybe_scale_up(pending)
                    continue
                idle_polls += 1
                if burst and idle_polls >= self.idle_polls_before_exit:
                    return
                self._stop_event.wait(self.poll_interval)
            except Exception as exc:
                logger.error(f"Worker loop error: {exc}")
                self._stop_event.wait(self.poll_interval)

    # ── Helpers ───────────────────────────────────────────────────────────

    @staticmethod
    def _job_view(job: Dict[str, Any]) -> Dict[str, Any]:
        """Serialisable view of an in-memory job, shaped like ``Model.to_dict``."""
        view = dict(job)
        for key in ('created_date', 'completed_date', 'next_retry_at'):
            value = view.get(key)
            if isinstance(value, datetime):
                view[key] = value.isoformat()
        for key in ('input_params', 'result'):
            value = view.get(key)
            if isinstance(value, str):
                try:
                    view[key] = json.loads(value)
                except ValueError:
                    pass
        return view

    def _emit(self, kind: str, job: Dict[str, Any], extra: Dict[str, Any]) -> None:
        if not self.event_hook:
            return
        subject_type = str(job.get('subject_type') or DOCUMENT_SUBJECT)
        names = _DOCUMENT_EVENTS if subject_type == DOCUMENT_SUBJECT else _GENERIC_EVENTS
        payload = {
            'job_id': job.get('id'),
            'job_type': job.get('job_type'),
            'subject_type': subject_type,
        }
        payload.update(extra)
        try:
            self.event_hook(names[kind], job.get('subject_id'), payload)
        except Exception as exc:
            logger.debug(f"Event hook failed for {kind}: {exc}")


# ── Module-level singleton ────────────────────────────────────────────────────

_default_queue: Optional[AgentJobQueue] = None
_singleton_lock = threading.Lock()


def _create_default_queue(db_manager=None) -> AgentJobQueue:
    # The shared queue always handles document jobs, whichever module asks
    # for it first; the document binding lives in document_job_worker.
    try:
        from services.document_job_worker import DocumentJobWorker
        return DocumentJobWorker(db_manager=db_manager)
    except Exception as exc:  # pragma: no cover - defensive
        logger.error(f"Document binding unavailable, bare queue: {exc}")
        return AgentJobQueue(db_manager=db_manager)


def get_job_queue(db_manager=None) -> AgentJobQueue:
    """Return or create the process-wide queue singleton.

    One queue per process drains the shared table for every agent.
    """
    global _default_queue
    with _singleton_lock:
        if _default_queue is None:
            _default_queue = _create_default_queue(db_manager)
        elif db_manager is not None and _default_queue.db_manager is None:
            _default_queue.db_manager = db_manager
        return _default_queue


def set_job_queue(queue: Optional[AgentJobQueue]) -> None:
    """Install ``queue`` as the singleton (tests; document worker binding)."""
    global _default_queue
    with _singleton_lock:
        _default_queue = queue


def reset_job_queue() -> None:
    """Stop and drop the singleton (mainly for tests)."""
    global _default_queue
    with _singleton_lock:
        queue = _default_queue
        _default_queue = None
    if queue is not None:
        try:
            queue.stop(timeout=1.0)
        except Exception:
            pass
