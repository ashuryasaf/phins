"""
Async Document Processing Worker
================================
Drains the ``document_processing_jobs`` queue so uploads return immediately
and heavy work (OCR, parsing, enrichment) happens in the background.

Design (see docs/multimodal_assessment_pipeline_plan.md, Phase 1):

* **Queue** — the existing ``document_processing_jobs`` table when a database
  is available; an in-memory list with identical semantics otherwise (test
  mode / in-memory deployments).
* **Idempotency** — every job carries an ``idempotency_key`` (content sha256 +
  job type). Duplicate enqueues return the existing job instead of creating a
  second one, so re-delivered events can never double-process a document.
* **Retries** — transient failures back off along ``PHINS_DOC_RETRY_SCHEDULE``
  (default 30s, 2m, 10m). Exhausted jobs land in ``dead_letter`` for operator
  action (requeue endpoint) instead of silently disappearing.
* **Crash recovery** — claiming a job stamps a claim expiry into
  ``next_retry_at``; a worker crash simply lets the claim expire and the job
  is picked up again.
* **Topology** — runs as daemon threads inside the web process by default
  (``start()``), and the same loop is callable one-shot (``process_once()``)
  from cron / ``entrypoint.sh worker`` for scale-out.

Environment:
    PHINS_DOC_ASYNC                 gate: enqueue instead of inline processing
    PHINS_DOC_WORKER_CONCURRENCY    worker threads (default 2)
    PHINS_DOC_WORKER_POLL_INTERVAL  seconds between polls (default 2.0)
    PHINS_DOC_RETRY_SCHEDULE        comma seconds, e.g. "30,120,600"
    PHINS_DOC_CLAIM_TIMEOUT         claim expiry seconds (default 600)
"""

import logging
import os
import threading
import time
import uuid
import json
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

TERMINAL_STATUSES = ('completed', 'dead_letter')


def _retry_schedule() -> List[int]:
    raw = os.environ.get('PHINS_DOC_RETRY_SCHEDULE', '30,120,600')
    try:
        schedule = [max(1, int(p.strip())) for p in raw.split(',') if p.strip()]
    except ValueError:
        schedule = [30, 120, 600]
    return schedule or [30, 120, 600]


class DocumentJobWorker:
    """Claims and executes document processing jobs with retry + DLQ."""

    def __init__(
        self,
        doc_service=None,
        db_manager=None,
        concurrency: Optional[int] = None,
        poll_interval: Optional[float] = None,
    ):
        self._doc_service = doc_service
        self.db_manager = db_manager
        self.concurrency = concurrency or int(os.environ.get('PHINS_DOC_WORKER_CONCURRENCY', '2'))
        self.poll_interval = poll_interval if poll_interval is not None else float(
            os.environ.get('PHINS_DOC_WORKER_POLL_INTERVAL', '2.0'))
        self.claim_timeout = int(os.environ.get('PHINS_DOC_CLAIM_TIMEOUT', '600'))
        self.retry_schedule = _retry_schedule()
        self.worker_id = f"worker-{os.getpid()}-{uuid.uuid4().hex[:6]}"
        # Optional structured-event hook, wired by the server to the platform
        # event ledger. Signature: hook(event_type, document_id, payload).
        self.event_hook: Optional[Callable[[str, str, Dict[str, Any]], None]] = None
        # Post-completion hook (e.g. assessment-center fact mining after async
        # enrichment). Signature: hook(document_id, job_type, result).
        self.completion_hook: Optional[Callable[[str, str, Dict[str, Any]], None]] = None

        self._lock = threading.RLock()
        self._inmemory_jobs: List[Dict[str, Any]] = []
        self._threads: List[threading.Thread] = []
        self._stop_event = threading.Event()

    # ── Document service binding ──────────────────────────────────────────

    @property
    def doc_service(self):
        if self._doc_service is None:
            from services.document_processing_service import get_document_service
            self._doc_service = get_document_service(db_manager=self.db_manager)
        return self._doc_service

    def _use_db(self) -> bool:
        return self.db_manager is not None

    # ── Enqueue ───────────────────────────────────────────────────────────

    def enqueue(
        self,
        *,
        document_id: str,
        job_type: str,
        priority: int = 100,
        idempotency_key: Optional[str] = None,
        input_params: Optional[Dict[str, Any]] = None,
        max_attempts: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Queue a job. Duplicate idempotency keys return the existing job.

        A completed job with the same key is NOT re-run (duplicate delivery
        safety); operators can force a re-run by enqueueing without a key.
        """
        if not document_id or not job_type:
            raise ValueError('document_id and job_type are required')
        resolved_max = max_attempts or (len(self.retry_schedule))

        if idempotency_key:
            existing = self._find_by_idempotency_key(idempotency_key)
            if existing is not None:
                return existing

        job = {
            'id': f"JOB-{uuid.uuid4().hex[:12].upper()}",
            'document_id': document_id,
            'job_type': job_type,
            'status': 'pending',
            'attempts': 0,
            'max_attempts': resolved_max,
            'next_retry_at': None,
            'priority': priority,
            'idempotency_key': idempotency_key,
            'worker_id': None,
            'input_params': json.dumps(input_params) if input_params else None,
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
                    self._emit('DOCUMENT_QUEUED', document_id,
                               {'job_id': job['id'], 'job_type': job_type})
                    return created.to_dict()
            except Exception as exc:
                logger.error(f"DB enqueue failed, using in-memory queue: {exc}")

        with self._lock:
            self._inmemory_jobs.append(job)
        self._emit('DOCUMENT_QUEUED', document_id,
                   {'job_id': job['id'], 'job_type': job_type})
        return self._job_view(job)

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
        if self._use_db():
            try:
                rows = self.db_manager.processing_jobs.claim_due_jobs(
                    worker_id=self.worker_id, limit=limit,
                    claim_timeout_seconds=self.claim_timeout,
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
                if j['status'] == 'pending'
                or (j['status'] in ('failed', 'claimed')
                    and j.get('next_retry_at') is not None
                    and j['next_retry_at'] <= now)
            ]
            due.sort(key=lambda j: (j.get('priority', 100), j['created_date']))
            for job in due[:limit]:
                job['status'] = 'claimed'
                job['worker_id'] = self.worker_id
                job['next_retry_at'] = now + timedelta(seconds=self.claim_timeout)
                claimed.append(self._job_view(job))
        return claimed

    def _execute(self, job: Dict[str, Any]) -> str:
        """Run one claimed job; returns 'completed' | 'failed' | 'dead_letter'."""
        job_id = job['id']
        document_id = job['document_id']
        job_type = job['job_type']
        attempts = int(job.get('attempts') or 0) + 1
        max_attempts = int(job.get('max_attempts') or len(self.retry_schedule))
        start = time.time()

        self._emit('DOCUMENT_PROCESSING_STARTED', document_id,
                   {'job_id': job_id, 'job_type': job_type, 'attempt': attempts})
        try:
            result = self.doc_service.execute_job(document_id, job_type)
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
            self._emit('DOCUMENT_PARSED', document_id,
                       {'job_id': job_id, 'job_type': job_type,
                        'processing_time_ms': elapsed_ms})
            if self.completion_hook:
                try:
                    self.completion_hook(document_id, job_type, result or {})
                except Exception as hook_exc:
                    logger.error(f"Completion hook failed for {document_id}: {hook_exc}")
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
                self._set_document_failed(document_id)
                self._emit('PROCESSING_FAILED', document_id,
                           {'job_id': job_id, 'job_type': job_type,
                            'error': error_text, 'final': True})
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
            self._emit('PROCESSING_FAILED', document_id,
                       {'job_id': job_id, 'job_type': job_type,
                        'error': error_text, 'retry_in_seconds': delay})
            logger.warning(f"Job {job_id} attempt {attempts} failed, retry in {delay}s: {error_text}")
            return 'failed'

    def _set_document_failed(self, document_id: str) -> None:
        """Mark the parent document so the UI can surface the failure."""
        try:
            self.doc_service._update_record(document_id, {
                'processing_status': 'failed',
            })
        except Exception as exc:
            logger.error(f"Could not flag document {document_id} as failed: {exc}")

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
                  limit: int = 50) -> List[Dict[str, Any]]:
        if self._use_db():
            try:
                repo = self.db_manager.processing_jobs
                if document_id:
                    rows = repo.get_by_document(document_id)
                elif status:
                    rows = repo.filter_by(status=status)
                else:
                    rows = repo.get_all(limit=limit)
                return [r.to_dict() for r in rows[:limit]]
            except Exception as exc:
                logger.error(f"List jobs failed: {exc}")
        with self._lock:
            jobs = list(self._inmemory_jobs)
        if status:
            jobs = [j for j in jobs if j['status'] == status]
        if document_id:
            jobs = [j for j in jobs if j['document_id'] == document_id]
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
        """Spawn daemon worker threads (idempotent)."""
        with self._lock:
            alive = [t for t in self._threads if t.is_alive()]
            if alive:
                return
            self._stop_event.clear()
            self._threads = []
            for index in range(max(1, self.concurrency)):
                thread = threading.Thread(
                    target=self._loop,
                    name=f"doc-worker-{index}",
                    daemon=True,
                )
                thread.start()
                self._threads.append(thread)
        logger.info(f"Document job worker started ({len(self._threads)} threads, "
                    f"poll {self.poll_interval}s, retries {self.retry_schedule})")

    def stop(self, timeout: float = 5.0) -> None:
        self._stop_event.set()
        for thread in self._threads:
            thread.join(timeout=timeout)
        self._threads = []

    def _loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                stats = self.process_once()
                if not stats['claimed']:
                    self._stop_event.wait(self.poll_interval)
            except Exception as exc:
                logger.error(f"Worker loop error: {exc}")
                self._stop_event.wait(self.poll_interval)

    # ── Helpers ───────────────────────────────────────────────────────────

    @staticmethod
    def _job_view(job: Dict[str, Any]) -> Dict[str, Any]:
        view = dict(job)
        for key in ('created_date', 'completed_date', 'next_retry_at'):
            value = view.get(key)
            if isinstance(value, datetime):
                view[key] = value.isoformat()
        return view

    def _emit(self, event_type: str, document_id: str, payload: Dict[str, Any]) -> None:
        if not self.event_hook:
            return
        try:
            self.event_hook(event_type, document_id, payload)
        except Exception as exc:
            logger.debug(f"Event hook failed for {event_type}: {exc}")


# ── Module-level singleton ────────────────────────────────────────────────────

_default_worker: Optional[DocumentJobWorker] = None


def get_document_job_worker(doc_service=None, db_manager=None) -> DocumentJobWorker:
    """Return or create the module-level worker singleton."""
    global _default_worker
    if _default_worker is None:
        _default_worker = DocumentJobWorker(doc_service=doc_service, db_manager=db_manager)
    else:
        if doc_service is not None and _default_worker._doc_service is None:
            _default_worker._doc_service = doc_service
        if db_manager is not None and _default_worker.db_manager is None:
            _default_worker.db_manager = db_manager
    return _default_worker


def reset_document_job_worker() -> None:
    """Stop and drop the singleton (mainly for tests)."""
    global _default_worker
    if _default_worker is not None:
        try:
            _default_worker.stop(timeout=1.0)
        except Exception:
            pass
    _default_worker = None
