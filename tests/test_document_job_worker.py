"""
Tests for the async document processing worker (Phase 1 of the multimodal
document intelligence pipeline).

Covers:
- Async upload gating via PHINS_DOC_ASYNC (queued vs inline processing)
- Worker drain: enqueue -> claim -> execute -> completed
- Idempotent enqueue (duplicate delivery returns the existing job)
- Retry with backoff and dead-letter after max attempts
- Dead-letter requeue (operator action)
- Completion hook firing after successful jobs
- Sync behaviour unchanged when the flag is off
"""

import base64
from datetime import datetime, timedelta

import pytest

from services.document_processing_service import (
    DocumentProcessingService,
    ProcessingJobType,
)
from services.document_job_worker import (
    DocumentJobWorker,
    get_document_job_worker,
    reset_document_job_worker,
)


def _b64(content: str = "policy premium coverage details") -> str:
    return base64.b64encode(content.encode("utf-8")).decode("ascii")


@pytest.fixture
def doc_service(tmp_path):
    return DocumentProcessingService(storage_root=str(tmp_path / "docs"))


@pytest.fixture
def worker(doc_service):
    w = DocumentJobWorker(doc_service=doc_service, poll_interval=0.05)
    yield w
    w.stop(timeout=1.0)


@pytest.fixture(autouse=True)
def _reset_singleton():
    reset_document_job_worker()
    yield
    reset_document_job_worker()


# ── Async upload gating ───────────────────────────────────────────────────────

def test_sync_upload_unchanged_when_flag_off(doc_service, monkeypatch):
    monkeypatch.delenv("PHINS_DOC_ASYNC", raising=False)
    result = doc_service.upload_document(
        file_name="notes.txt", file_data_b64=_b64(), mime_type="text/plain")
    assert result.status == "processed"
    record = doc_service.get_document(result.document_id)
    assert record["processing_status"] == "completed"
    assert "policy premium" in (record.get("extracted_text") or "")


def test_async_upload_queues_then_worker_completes(doc_service, monkeypatch):
    monkeypatch.setenv("PHINS_DOC_ASYNC", "1")
    # Bind the singleton worker to this test's service so the upload path
    # enqueues into a queue we control.
    worker = get_document_job_worker(doc_service=doc_service)

    result = doc_service.upload_document(
        file_name="notes.txt", file_data_b64=_b64(), mime_type="text/plain")
    assert result.status == "uploaded"
    assert result.metadata == {"queued": True}

    record = doc_service.get_document(result.document_id)
    assert record["processing_status"] == "queued"
    assert not record.get("extracted_text")

    stats = worker.process_once()
    assert stats["claimed"] == 1
    assert stats["completed"] == 1

    record = doc_service.get_document(result.document_id)
    assert record["status"] == "processed"
    assert record["processing_status"] == "completed"
    assert "policy premium" in (record.get("extracted_text") or "")


def test_async_upload_falls_back_to_sync_on_enqueue_failure(doc_service, monkeypatch):
    monkeypatch.setenv("PHINS_DOC_ASYNC", "1")

    def _boom(**_kwargs):
        raise RuntimeError("queue unavailable")

    worker = get_document_job_worker(doc_service=doc_service)
    monkeypatch.setattr(worker, "enqueue", _boom)

    result = doc_service.upload_document(
        file_name="notes.txt", file_data_b64=_b64(), mime_type="text/plain")
    # Falls back to inline processing — a document must never stay unprocessed.
    assert result.status == "processed"
    record = doc_service.get_document(result.document_id)
    assert record["processing_status"] == "completed"


# ── Idempotency ───────────────────────────────────────────────────────────────

def test_duplicate_enqueue_returns_existing_job(doc_service, worker):
    upload = doc_service.upload_document(
        file_name="a.txt", file_data_b64=_b64(), mime_type="text/plain",
        skip_processing=True)
    key = f"{upload.sha256}:{ProcessingJobType.DOCUMENT_ENRICHMENT.value}"

    first = worker.enqueue(document_id=upload.document_id,
                           job_type=ProcessingJobType.DOCUMENT_ENRICHMENT.value,
                           idempotency_key=key)
    second = worker.enqueue(document_id=upload.document_id,
                            job_type=ProcessingJobType.DOCUMENT_ENRICHMENT.value,
                            idempotency_key=key)
    assert first["id"] == second["id"]
    assert len(worker.list_jobs()) == 1


def test_completed_job_not_rerun_on_duplicate_delivery(doc_service, worker):
    upload = doc_service.upload_document(
        file_name="a.txt", file_data_b64=_b64(), mime_type="text/plain",
        skip_processing=True)
    key = f"{upload.sha256}:{ProcessingJobType.DOCUMENT_ENRICHMENT.value}"
    worker.enqueue(document_id=upload.document_id,
                   job_type=ProcessingJobType.DOCUMENT_ENRICHMENT.value,
                   idempotency_key=key)
    assert worker.process_once()["completed"] == 1

    # Duplicate delivery after completion: no new job, nothing to claim.
    duplicate = worker.enqueue(document_id=upload.document_id,
                               job_type=ProcessingJobType.DOCUMENT_ENRICHMENT.value,
                               idempotency_key=key)
    assert duplicate["status"] == "completed"
    assert worker.process_once()["claimed"] == 0
    assert len(worker.list_jobs()) == 1


# ── Retry / dead-letter ───────────────────────────────────────────────────────

def _drain_with_forced_retry(worker):
    """Process, then force each failed job's retry time into the past."""
    stats = worker.process_once()
    for job in worker.list_jobs(status="failed"):
        worker._update_job(job["id"], {
            "next_retry_at": datetime.utcnow() - timedelta(seconds=1)})
    return stats


def test_transient_failure_retries_then_succeeds(doc_service, worker, monkeypatch):
    upload = doc_service.upload_document(
        file_name="a.txt", file_data_b64=_b64(), mime_type="text/plain",
        skip_processing=True)
    worker.enqueue(document_id=upload.document_id,
                   job_type=ProcessingJobType.DOCUMENT_ENRICHMENT.value)

    original = doc_service.execute_job
    calls = {"n": 0}

    def _flaky(document_id, job_type):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("transient provider error")
        return original(document_id, job_type)

    monkeypatch.setattr(doc_service, "execute_job", _flaky)

    stats = _drain_with_forced_retry(worker)
    assert stats["failed"] == 1
    job = worker.list_jobs()[0]
    assert job["status"] == "failed"
    assert job["attempts"] == 1
    assert job["error_message"] == "transient provider error"

    stats = worker.process_once()
    assert stats["completed"] == 1
    assert worker.list_jobs()[0]["status"] == "completed"


def test_exhausted_retries_dead_letter_and_flag_document(doc_service, worker, monkeypatch):
    upload = doc_service.upload_document(
        file_name="a.txt", file_data_b64=_b64(), mime_type="text/plain",
        skip_processing=True)
    worker.enqueue(document_id=upload.document_id,
                   job_type=ProcessingJobType.DOCUMENT_ENRICHMENT.value,
                   max_attempts=3)

    monkeypatch.setattr(doc_service, "execute_job",
                        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("permanent")))

    outcomes = []
    for _ in range(3):
        stats = _drain_with_forced_retry(worker)
        outcomes.append(stats)
    assert outcomes[0]["failed"] == 1
    assert outcomes[1]["failed"] == 1
    assert outcomes[2]["dead_letter"] == 1

    job = worker.list_jobs()[0]
    assert job["status"] == "dead_letter"
    assert job["attempts"] == 3

    record = doc_service.get_document(upload.document_id)
    assert record["processing_status"] == "failed"

    # Nothing left to claim — dead-letter jobs need operator action.
    assert worker.process_once()["claimed"] == 0


def test_requeue_dead_letter(doc_service, worker, monkeypatch):
    upload = doc_service.upload_document(
        file_name="a.txt", file_data_b64=_b64(), mime_type="text/plain",
        skip_processing=True)
    worker.enqueue(document_id=upload.document_id,
                   job_type=ProcessingJobType.DOCUMENT_ENRICHMENT.value,
                   max_attempts=1)
    monkeypatch.setattr(doc_service, "execute_job",
                        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("boom")))
    worker.process_once()
    job = worker.list_jobs()[0]
    assert job["status"] == "dead_letter"

    assert worker.requeue_dead_letter(job["id"]) is True
    monkeypatch.undo()
    stats = worker.process_once()
    assert stats["completed"] == 1


# ── Hooks and stats ───────────────────────────────────────────────────────────

def test_completion_hook_and_events_fire(doc_service, worker):
    events = []
    completions = []
    worker.event_hook = lambda et, doc_id, payload: events.append(et)
    worker.completion_hook = lambda doc_id, jt, result: completions.append((doc_id, jt))

    upload = doc_service.upload_document(
        file_name="a.txt", file_data_b64=_b64(), mime_type="text/plain",
        skip_processing=True)
    worker.enqueue(document_id=upload.document_id,
                   job_type=ProcessingJobType.DOCUMENT_ENRICHMENT.value)
    worker.process_once()

    assert "DOCUMENT_QUEUED" in events
    assert "DOCUMENT_PROCESSING_STARTED" in events
    assert "DOCUMENT_PARSED" in events
    assert completions == [(upload.document_id,
                            ProcessingJobType.DOCUMENT_ENRICHMENT.value)]


def test_queue_stats(doc_service, worker):
    upload = doc_service.upload_document(
        file_name="a.txt", file_data_b64=_b64(), mime_type="text/plain",
        skip_processing=True)
    worker.enqueue(document_id=upload.document_id,
                   job_type=ProcessingJobType.DOCUMENT_ENRICHMENT.value)
    assert worker.queue_stats() == {"pending": 1}
    worker.process_once()
    assert worker.queue_stats() == {"completed": 1}


def test_crash_recovery_reclaims_expired_claims(doc_service, worker):
    """A job claimed by a crashed worker is claimable once its claim expires."""
    upload = doc_service.upload_document(
        file_name="a.txt", file_data_b64=_b64(), mime_type="text/plain",
        skip_processing=True)
    worker.enqueue(document_id=upload.document_id,
                   job_type=ProcessingJobType.DOCUMENT_ENRICHMENT.value)

    # Simulate a crash: claim without executing.
    claimed = worker._claim_due(limit=10)
    assert len(claimed) == 1
    assert worker.queue_stats() == {"claimed": 1}

    # Claim not yet expired: nothing due.
    assert worker._claim_due(limit=10) == []

    # Expire the claim, then the job is claimable again and completes.
    worker._update_job(claimed[0]["id"], {
        "next_retry_at": datetime.utcnow() - timedelta(seconds=1)})
    stats = worker.process_once()
    assert stats["completed"] == 1
