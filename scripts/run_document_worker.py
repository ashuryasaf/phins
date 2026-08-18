#!/usr/bin/env python3
"""
Standalone async document-processing worker.

Launched via ``./scripts/entrypoint.sh worker`` as a dedicated Railway/Render
service when upload volume outgrows the in-process worker threads (Phase 6 of
docs/multimodal_assessment_pipeline_plan.md).

Requires ``USE_DATABASE=true``: a separate process can only share documents
and job rows with the web process through the database. Without a database
the in-process worker inside ``serve`` mode is the only valid topology.

Usage:
    ./scripts/entrypoint.sh worker            # run until terminated
    ./scripts/entrypoint.sh worker --once     # single drain pass (cron-able)
"""

import os
import signal
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main(argv=None):
    args = list(argv or sys.argv[1:])
    once = '--once' in args

    use_database = str(os.environ.get('USE_DATABASE', 'true')).lower() in ('1', 'true', 'yes', 'y')
    if not use_database:
        print("run_document_worker: USE_DATABASE must be true for a standalone "
              "worker (documents/jobs are shared via the database). "
              "Use the in-process worker (PHINS_DOC_ASYNC=true on the web "
              "service) for in-memory deployments.", file=sys.stderr)
        return 64

    from database.manager import DatabaseManager
    from services.document_processing_service import get_document_service
    from services.document_job_worker import get_document_job_worker

    db_manager = DatabaseManager()
    doc_service = get_document_service(db_manager=db_manager)
    worker = get_document_job_worker(doc_service=doc_service, db_manager=db_manager)

    if once:
        stats = worker.process_once(limit=int(os.environ.get('PHINS_DOC_WORKER_BATCH', '50')))
        print(f"run_document_worker: {stats}")
        return 0

    stop = {'requested': False}

    def _handle_signal(_signum, _frame):
        stop['requested'] = True

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    print(f"run_document_worker: started (worker_id={worker.worker_id}, "
          f"concurrency={worker.concurrency}, poll={worker.poll_interval}s, "
          f"retries={worker.retry_schedule}s)")
    worker.start()
    try:
        while not stop['requested']:
            time.sleep(1.0)
    finally:
        print("run_document_worker: stopping...")
        worker.stop()
    return 0


if __name__ == '__main__':
    sys.exit(main())
