"""
Tests for the agent-generic job queue (A3 of
docs/agent_operations_optimization_design.md).

Covers:
- Handler registry dispatch by job_type; unregistered types dead-letter
- Non-document subjects (nullable document_id) in memory and in SQLite
- Per-type idempotency keys
- Retry schedule / dead-letter per type; dead-letter hook scoped by subject
- Claim expiry recovery
- Event names: legacy DOCUMENT_* for documents, JOB_* for everything else
- Concurrency scales up on backlog and burst threads exit when idle
- One shared singleton for ``get_job_queue`` and ``get_document_job_worker``
- Schema migration: document_id NOT NULL -> nullable (SQLite rebuild)
"""

import os
import threading
import time
from datetime import datetime, timedelta

import pytest

from services.agent_job_queue import (
    AgentJobQueue,
    get_job_queue,
    reset_job_queue,
    set_job_queue,
)
from services.document_job_worker import (
    DocumentJobWorker,
    get_document_job_worker,
    reset_document_job_worker,
)


@pytest.fixture
def queue():
    q = AgentJobQueue(poll_interval=0.01)
    yield q
    q.stop(timeout=1.0)


@pytest.fixture(autouse=True)
def _reset_singletons():
    reset_job_queue()
    yield
    reset_job_queue()


def _force_due(queue):
    for job in queue.list_jobs(status="failed"):
        queue._update_job(job["id"], {
            "next_retry_at": datetime.utcnow() - timedelta(seconds=1)})


# ── Registry / dispatch ───────────────────────────────────────────────────────

def test_dispatch_by_job_type_with_subject(queue):
    seen = []
    queue.register_handler("claims_bot", lambda job: seen.append(job) or {"score": 0.9})

    job = queue.enqueue(job_type="claims_bot", subject_type="claim", subject_id="CLM-1",
                        submitted_by="adjuster", input_params={"claim_id": "CLM-1"})
    assert job["document_id"] is None
    assert job["subject_type"] == "claim"
    assert job["subject_id"] == "CLM-1"
    assert job["submitted_by"] == "adjuster"
    assert job["status"] == "pending"

    stats = queue.process_once()
    assert stats == {"claimed": 1, "completed": 1, "failed": 0, "dead_letter": 0}
    assert seen[0]["input_params"] == {"claim_id": "CLM-1"}

    done = queue.get_job(job["id"])
    assert done["status"] == "completed"
    assert done["result"] == {"score": 0.9}
    assert done["attempts"] == 1


def test_document_id_mirrors_into_subject(queue):
    queue.register_handler("document_enrichment", lambda job: {"ok": True})
    job = queue.enqueue(job_type="document_enrichment", document_id="DOC-1")
    assert job["subject_type"] == "document"
    assert job["subject_id"] == "DOC-1"
    assert job["document_id"] == "DOC-1"


def test_enqueue_requires_a_subject(queue):
    with pytest.raises(ValueError):
        queue.enqueue(job_type="claims_bot")
    with pytest.raises(ValueError):
        queue.enqueue(job_type="", subject_type="claim", subject_id="CLM-1")
    with pytest.raises(ValueError):
        queue.register_handler("x", "not-callable")


def test_unhandled_job_type_is_left_pending_for_a_capable_worker(queue):
    """A worker without the handler must not claim (and burn retries on) a
    job another worker can run; the job stays pending and visible."""
    queue.register_handler("known", lambda job: 1)
    job = queue.enqueue(job_type="mystery", subject_type="report", subject_id="R-1",
                        max_attempts=2)
    queue.enqueue(job_type="known", subject_type="report", subject_id="R-2")
    stats = queue.process_once()
    assert stats == {"claimed": 1, "completed": 1, "failed": 0, "dead_letter": 0}
    assert queue.get_job(job["id"])["status"] == "pending"
    assert queue.queue_stats() == {"pending": 1, "completed": 1}

    # A worker that gains the handler picks it up unchanged.
    queue.register_handler("mystery", lambda job: {"solved": True})
    assert queue.process_once()["completed"] == 1
    assert queue.get_job(job["id"])["result"] == {"solved": True}


def test_handler_removed_between_claim_and_run_fails_not_lost(queue):
    queue.register_handler("t", lambda job: 1)
    job = queue.enqueue(job_type="t", subject_type="x", subject_id="1", max_attempts=1)
    claimed = queue._claim_due(limit=1)
    queue.unregister_handler("t")
    assert queue._execute(claimed[0]) == "dead_letter"
    assert "no handler registered" in queue.get_job(job["id"])["error_message"]


def test_queue_with_no_handlers_claims_nothing(queue):
    queue.enqueue(job_type="t", subject_type="x", subject_id="1")
    assert queue.process_once()["claimed"] == 0
    assert queue.queue_stats() == {"pending": 1}


def test_handlers_are_per_type_and_replaceable(queue):
    queue.register_handler("a", lambda job: "first")
    queue.register_handler("b", lambda job: "b")
    assert queue.handlers() == ["a", "b"]
    queue.register_handler("a", lambda job: "second")
    job = queue.enqueue(job_type="a", subject_type="x", subject_id="1")
    queue.process_once()
    assert queue.get_job(job["id"])["result"] == "second"
    queue.unregister_handler("b")
    assert queue.handlers() == ["a"]


# ── Idempotency ───────────────────────────────────────────────────────────────

def test_idempotency_key_is_per_type(queue):
    queue.register_handler("underwriting_bot", lambda job: {"decision": "approve"})
    queue.register_handler("risk_report", lambda job: {"report": 1})

    first = queue.enqueue(job_type="underwriting_bot", subject_type="application",
                          subject_id="APP-1", idempotency_key="sha:underwriting_bot")
    dup = queue.enqueue(job_type="underwriting_bot", subject_type="application",
                        subject_id="APP-1", idempotency_key="sha:underwriting_bot")
    other = queue.enqueue(job_type="risk_report", subject_type="report",
                          subject_id="APP-1", idempotency_key="sha:risk_report")
    assert first["id"] == dup["id"]
    assert other["id"] != first["id"]
    assert len(queue.list_jobs()) == 2

    queue.process_once()
    replay = queue.enqueue(job_type="underwriting_bot", subject_type="application",
                           subject_id="APP-1", idempotency_key="sha:underwriting_bot")
    assert replay["status"] == "completed"
    assert queue.process_once()["claimed"] == 0


# ── Retry / dead-letter ───────────────────────────────────────────────────────

def test_retry_then_success_and_dead_letter_hook_scoped_by_subject(queue):
    calls = {"n": 0}

    def _flaky(job):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("transient")
        return {"ok": True}

    queue.register_handler("flaky", _flaky)
    queue.register_handler("doomed", lambda job: (_ for _ in ()).throw(RuntimeError("permanent")))
    dead = []
    queue.register_dead_letter_hook("report", lambda job, err: dead.append((job["id"], err)))

    flaky = queue.enqueue(job_type="flaky", subject_type="report", subject_id="R-1")
    doomed_report = queue.enqueue(job_type="doomed", subject_type="report", subject_id="R-2",
                                  max_attempts=1)
    doomed_claim = queue.enqueue(job_type="doomed", subject_type="claim", subject_id="C-1",
                                 max_attempts=1)

    stats = queue.process_once()
    assert stats["failed"] == 1
    assert stats["dead_letter"] == 2
    assert queue.get_job(flaky["id"])["status"] == "failed"
    assert queue.get_job(flaky["id"])["error_message"] == "transient"

    # The hook fires for the report subject only, exactly once, with the error.
    assert dead == [(doomed_report["id"], "permanent")]
    assert queue.get_job(doomed_claim["id"])["status"] == "dead_letter"

    _force_due(queue)
    assert queue.process_once()["completed"] == 1
    assert queue.get_job(flaky["id"])["status"] == "completed"

    # Operator requeue restores a dead-letter job.
    assert queue.requeue_dead_letter(doomed_claim["id"]) is True
    assert queue.get_job(doomed_claim["id"])["status"] == "pending"
    assert queue.requeue_dead_letter("JOB-NOPE") is False


def test_claim_expiry_recovers_crashed_worker(queue):
    queue.register_handler("t", lambda job: {"ok": 1})
    queue.enqueue(job_type="t", subject_type="report", subject_id="R-1")
    claimed = queue._claim_due(limit=10)
    assert len(claimed) == 1
    assert queue._claim_due(limit=10) == []
    queue._update_job(claimed[0]["id"], {
        "next_retry_at": datetime.utcnow() - timedelta(seconds=1)})
    assert queue.process_once()["completed"] == 1


def test_priority_orders_claims(queue):
    order = []
    queue.register_handler("t", lambda job: order.append(job["subject_id"]))
    queue.enqueue(job_type="t", subject_type="x", subject_id="low", priority=200)
    queue.enqueue(job_type="t", subject_type="x", subject_id="high", priority=10)
    queue.enqueue(job_type="t", subject_type="x", subject_id="mid", priority=100)
    queue.process_once()
    assert order == ["high", "mid", "low"]


# ── Events / hooks ────────────────────────────────────────────────────────────

def test_event_names_legacy_for_documents_generic_otherwise(queue):
    events = []
    queue.event_hook = lambda et, subject_id, payload: events.append((et, subject_id, payload["subject_type"]))
    completions = []
    queue.completion_hook = lambda subject_id, jt, result: completions.append((subject_id, jt, result))
    queue.register_handler("document_enrichment", lambda job: {"text": "x"})
    queue.register_handler("claims_bot", lambda job: {"score": 1})

    queue.enqueue(job_type="document_enrichment", document_id="DOC-1")
    queue.enqueue(job_type="claims_bot", subject_type="claim", subject_id="CLM-1")
    queue.process_once()

    doc_events = [e for e in events if e[1] == "DOC-1"]
    claim_events = [e for e in events if e[1] == "CLM-1"]
    assert [e[0] for e in doc_events] == ["DOCUMENT_QUEUED", "DOCUMENT_PROCESSING_STARTED", "DOCUMENT_PARSED"]
    assert [e[0] for e in claim_events] == ["JOB_QUEUED", "JOB_STARTED", "JOB_COMPLETED"]
    assert {e[2] for e in doc_events} == {"document"}
    assert {e[2] for e in claim_events} == {"claim"}
    assert completions == [("DOC-1", "document_enrichment", {"text": "x"}),
                           ("CLM-1", "claims_bot", {"score": 1})]


def test_failed_event_for_generic_subject(queue):
    events = []
    queue.event_hook = lambda et, sid, payload: events.append((et, payload))
    queue.register_handler("boom", lambda job: (_ for _ in ()).throw(RuntimeError("x")))
    queue.enqueue(job_type="boom", subject_type="claim", subject_id="C", max_attempts=1)
    queue.process_once()
    failed = [p for et, p in events if et == "JOB_FAILED"]
    assert failed and failed[0]["final"] is True and failed[0]["error"] == "x"


# ── Listing ───────────────────────────────────────────────────────────────────

def test_list_jobs_filters(queue):
    queue.register_handler("t", lambda job: 1)
    queue.enqueue(job_type="t", subject_type="claim", subject_id="C-1", submitted_by="alice")
    queue.enqueue(job_type="t", subject_type="report", subject_id="R-1", submitted_by="bob")
    queue.enqueue(job_type="u", subject_type="report", subject_id="R-2", submitted_by="bob")
    assert {j["subject_id"] for j in queue.list_jobs(subject_type="report")} == {"R-1", "R-2"}
    assert [j["subject_id"] for j in queue.list_jobs(subject_id="C-1")] == ["C-1"]
    assert {j["subject_id"] for j in queue.list_jobs(submitted_by="bob")} == {"R-1", "R-2"}
    assert [j["subject_id"] for j in queue.list_jobs(job_type="u")] == ["R-2"]
    assert queue.queue_stats() == {"pending": 3}
    assert queue.get_job("JOB-MISSING") is None


# ── Concurrency scaling ───────────────────────────────────────────────────────

def test_scales_up_on_backlog_and_burst_threads_exit_when_idle():
    q = AgentJobQueue(concurrency=1, max_concurrency=3, poll_interval=0.01)
    q.idle_polls_before_exit = 2
    gate = threading.Event()
    q.register_handler("slow", lambda job: gate.wait(2.0))
    try:
        for i in range(6):
            q.enqueue(job_type="slow", subject_type="x", subject_id=str(i))
        q.start()
        assert q.active_threads() == 1
        # Backlog above the running thread count adds burst threads, one per
        # call, never beyond max_concurrency.
        assert q._maybe_scale_up(pending=5) == 1
        assert q._maybe_scale_up(pending=5) == 1
        assert q._maybe_scale_up(pending=5) == 0
        assert q.active_threads() == 3
        # No scale-up when the backlog fits the running threads.
        assert q._maybe_scale_up(pending=3) == 0

        gate.set()
        deadline = time.time() + 5.0
        while time.time() < deadline and q.queue_stats().get("completed") != 6:
            time.sleep(0.02)
        assert q.queue_stats() == {"completed": 6}
        # Burst threads exit after idle polls; the baseline thread stays.
        deadline = time.time() + 5.0
        while time.time() < deadline and q.active_threads() > 1:
            time.sleep(0.02)
        assert q.active_threads() == 1
    finally:
        gate.set()
        q.stop(timeout=2.0)


def test_max_concurrency_never_below_baseline(monkeypatch):
    monkeypatch.setenv("PHINS_DOC_WORKER_CONCURRENCY", "4")
    monkeypatch.setenv("PHINS_JOB_WORKER_MAX_CONCURRENCY", "2")
    q = AgentJobQueue(poll_interval=0.01)
    assert q.concurrency == 4
    assert q.max_concurrency == 4
    monkeypatch.setenv("PHINS_JOB_WORKER_MAX_CONCURRENCY", "8")
    assert AgentJobQueue(poll_interval=0.01).max_concurrency == 8


def test_background_loop_drains_generic_jobs():
    q = AgentJobQueue(concurrency=1, poll_interval=0.01)
    q.register_handler("t", lambda job: {"n": job["subject_id"]})
    try:
        for i in range(3):
            q.enqueue(job_type="t", subject_type="x", subject_id=str(i))
        q.start()
        q.start()  # idempotent
        deadline = time.time() + 5.0
        while time.time() < deadline and q.queue_stats().get("completed") != 3:
            time.sleep(0.02)
        assert q.queue_stats() == {"completed": 3}
    finally:
        q.stop(timeout=2.0)


# ── Singleton sharing ─────────────────────────────────────────────────────────

def test_one_shared_queue_for_documents_and_agents():
    shared = get_job_queue()
    assert isinstance(shared, DocumentJobWorker)
    assert get_document_job_worker() is shared
    # Document job types are already bound on the shared instance.
    from services.document_processing_service import ProcessingJobType
    assert ProcessingJobType.DOCUMENT_ENRICHMENT.value in shared.handlers()
    # An agent registering its handler shares the same drain loop.
    shared.register_handler("claims_bot", lambda job: 1)
    assert "claims_bot" in get_document_job_worker().handlers()
    reset_document_job_worker()
    assert get_job_queue() is not shared


def test_bare_queue_installed_first_gets_document_handlers_bound():
    bare = AgentJobQueue(poll_interval=0.01)
    set_job_queue(bare)
    worker = get_document_job_worker()
    assert worker is bare
    from services.document_processing_service import ProcessingJobType
    assert ProcessingJobType.DOCUMENT_ENRICHMENT.value in bare.handlers()
    bare.stop(timeout=1.0)


def test_document_service_bound_after_creation_is_used(tmp_path):
    from services.document_processing_service import DocumentProcessingService
    svc = DocumentProcessingService(storage_root=str(tmp_path / "docs"))
    worker = get_document_job_worker()
    assert get_document_job_worker(doc_service=svc).doc_service is svc
    # First binding wins.
    other = DocumentProcessingService(storage_root=str(tmp_path / "other"))
    assert get_document_job_worker(doc_service=other).doc_service is svc
    assert worker.doc_service is svc


# ── Database-backed path ──────────────────────────────────────────────────────

def _sqlite_db_manager():
    from database import init_database
    from database.manager import DatabaseManager
    init_database()
    return DatabaseManager()


def test_sqlite_persists_non_document_jobs_with_null_document_id():
    from database.models import DocumentProcessingJob

    db = _sqlite_db_manager()
    marker = f"CLM-Q-{os.getpid()}"
    try:
        q = AgentJobQueue(db_manager=db, poll_interval=0.01)
        q.register_handler("claims_bot", lambda job: {"claim": job["subject_id"], "score": 0.42})
        job = q.enqueue(job_type="claims_bot", subject_type="claim", subject_id=marker,
                        submitted_by="adjuster", idempotency_key=f"{marker}:claims_bot",
                        input_params={"claim_id": marker})
        assert job["document_id"] is None
        assert job["subject_id"] == marker

        # Duplicate delivery through the DB unique key returns the same row.
        assert q.enqueue(job_type="claims_bot", subject_type="claim", subject_id=marker,
                         idempotency_key=f"{marker}:claims_bot")["id"] == job["id"]

        # A second worker on the same table without this handler leaves it alone.
        other = AgentJobQueue(db_manager=db, poll_interval=0.01)
        other.register_handler("something_else", lambda job: 1)
        assert other.process_once()["claimed"] == 0
        assert q.get_job(job["id"])["status"] == "pending"

        stats = q.process_once()
        assert stats["completed"] == 1
        row = q.get_job(job["id"])
        assert row["status"] == "completed"
        assert row["result"] == {"claim": marker, "score": 0.42}
        assert row["input_params"] == {"claim_id": marker}
        assert row["submitted_by"] == "adjuster"

        listed = q.list_jobs(subject_type="claim", subject_id=marker)
        assert [r["id"] for r in listed] == [job["id"]]
        assert q.list_jobs(submitted_by="adjuster", status="completed")[0]["id"] == job["id"]
        assert q.list_jobs(submitted_by="adjuster", status="pending") == []
        assert q.queue_stats().get("completed", 0) >= 1
    finally:
        try:
            session = db._ensure_session()
            session.query(DocumentProcessingJob).filter(
                DocumentProcessingJob.subject_id == marker).delete(synchronize_session=False)
            session.commit()
        finally:
            db.close()


# ── Schema migration ──────────────────────────────────────────────────────────

_LEGACY_JOBS_DDL = (
    "CREATE TABLE document_processing_jobs ("
    " id VARCHAR(120) PRIMARY KEY,"
    " document_id VARCHAR(120) NOT NULL REFERENCES documents(id) ON DELETE CASCADE,"
    " job_type VARCHAR(50) NOT NULL, status VARCHAR(30) NOT NULL,"
    " input_params TEXT, result TEXT, error_message TEXT, processing_time_ms INTEGER,"
    " attempts INTEGER NOT NULL DEFAULT 0, max_attempts INTEGER NOT NULL DEFAULT 3,"
    " next_retry_at DATETIME, priority INTEGER NOT NULL DEFAULT 100,"
    " idempotency_key VARCHAR(200), worker_id VARCHAR(100),"
    " created_date DATETIME, completed_date DATETIME)"
)


def _legacy_engine(tmp_path, extra_column_sql: str = ""):
    from sqlalchemy import create_engine, text
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    ddl = _LEGACY_JOBS_DDL
    if extra_column_sql:
        ddl = ddl[:-1] + f", {extra_column_sql})"
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE documents (id VARCHAR(120) PRIMARY KEY)"))
        conn.execute(text("INSERT INTO documents VALUES ('DOC-L1')"))
        conn.execute(text(ddl))
        conn.execute(text(
            "CREATE UNIQUE INDEX ix_document_processing_jobs_idempotency_key"
            " ON document_processing_jobs (idempotency_key)"))
        conn.execute(text(
            "INSERT INTO document_processing_jobs"
            " (id, document_id, job_type, status, result, idempotency_key, created_date)"
            " VALUES ('JOB-L1', 'DOC-L1', 'document_enrichment', 'completed',"
            " '{\"pages\": 3}', 'sha-l1:document_enrichment', '2026-01-01 00:00:00')"))
        conn.execute(text(
            "INSERT INTO document_processing_jobs"
            " (id, document_id, job_type, status, attempts, created_date)"
            " VALUES ('JOB-L2', 'DOC-L1', 'ocr', 'failed', 2, '2026-01-02 00:00:00')"))
    return engine


def test_upgrade_schema_makes_document_id_nullable_preserving_rows(tmp_path):
    from sqlalchemy import inspect, text
    from database import upgrade_schema

    engine = _legacy_engine(tmp_path)
    before = {c["name"]: c for c in inspect(engine).get_columns("document_processing_jobs")}
    assert before["document_id"]["nullable"] is False

    assert upgrade_schema(engine) is True
    assert upgrade_schema(engine) is True  # idempotent

    insp = inspect(engine)
    after = {c["name"]: c for c in insp.get_columns("document_processing_jobs")}
    assert after["document_id"]["nullable"] is True
    assert {"subject_type", "subject_id", "submitted_by"} <= set(after)
    index_names = {i["name"] for i in insp.get_indexes("document_processing_jobs")}
    assert "ix_document_processing_jobs_idempotency_key" in index_names
    assert "ix_document_processing_jobs_subject_id" in index_names
    assert "document_processing_jobs__rebuild_tmp" not in insp.get_table_names()

    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT id, document_id, job_type, status, result, attempts, idempotency_key,"
            " created_date FROM document_processing_jobs ORDER BY id")).fetchall()
        assert [tuple(r) for r in rows] == [
            ("JOB-L1", "DOC-L1", "document_enrichment", "completed", '{"pages": 3}', 0,
             "sha-l1:document_enrichment", "2026-01-01 00:00:00"),
            ("JOB-L2", "DOC-L1", "ocr", "failed", None, 2, None, "2026-01-02 00:00:00"),
        ]
        # The whole point: a non-document job row is now storable.
        conn.execute(text(
            "INSERT INTO document_processing_jobs"
            " (id, subject_type, subject_id, job_type, status, attempts, max_attempts, priority)"
            " VALUES ('JOB-N1', 'claim', 'CLM-1', 'claims_bot', 'pending', 0, 3, 100)"))
        conn.commit()
        # Unique index still enforced after the rebuild.
        with pytest.raises(Exception):
            conn.execute(text(
                "INSERT INTO document_processing_jobs"
                " (id, document_id, job_type, status, attempts, max_attempts, priority, idempotency_key)"
                " VALUES ('JOB-DUP', 'DOC-L1', 'x', 'pending', 0, 3, 100, 'sha-l1:document_enrichment')"))
        conn.rollback()
    engine.dispose()


def test_sqlite_rebuild_refuses_to_drop_undeclared_columns(tmp_path):
    """Fail closed: a live column the ORM does not know about would be lost by
    a rebuild, so the migration reports failure and leaves the table intact."""
    from sqlalchemy import inspect, text
    from database import upgrade_schema

    engine = _legacy_engine(tmp_path, extra_column_sql="operator_note TEXT")
    assert upgrade_schema(engine) is False
    insp = inspect(engine)
    cols = {c["name"]: c for c in insp.get_columns("document_processing_jobs")}
    assert cols["document_id"]["nullable"] is False
    assert "operator_note" in cols
    assert "document_processing_jobs__rebuild_tmp" not in insp.get_table_names()
    with engine.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM document_processing_jobs")).scalar() == 2
    engine.dispose()


def test_schema_fingerprint_folds_nullable_migrations(monkeypatch):
    import database as db_module
    before = db_module._schema_fingerprint()
    monkeypatch.setattr(db_module, "_UPGRADE_NULLABLE_COLUMNS",
                        db_module._UPGRADE_NULLABLE_COLUMNS + [("claims", "provider")])
    assert db_module._schema_fingerprint() != before
