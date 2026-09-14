"""
Risk Reports job adapter (``POST /api/reports/analyze`` and
``POST /api/reports/generate``).

Authorization (owner / role scoping via ``authorize_access``) happens in the
route before a job is enqueued; the handler only performs the analysis or
report generation the synchronous route performed and returns the same
``service.to_dict(...) + {'success': True}`` body.
"""

from typing import Any, Dict, Optional

from services.agent_job_queue import AgentJobQueue

ANALYZE_JOB_TYPE = 'risk_report_analyze'
GENERATE_JOB_TYPE = 'risk_report_generate'
SUBJECT_TYPE = 'report'


def _service():
    from services.ai_risk_reports_service import get_ai_reports_service
    return get_ai_reports_service()


def run_analyze(document_id: str) -> Dict[str, Any]:
    service = _service()
    analysis = service.analyze(document_id)
    result = service.to_dict(analysis)
    result['success'] = True
    return result


def run_generate(analysis_id: str, language: Optional[str] = None) -> Dict[str, Any]:
    service = _service()
    report = service.generate_report(analysis_id, language)
    result = service.to_dict(report)
    result['success'] = True
    return result


def enqueue_analyze(queue: AgentJobQueue, *, document_id: str, submitted_by: str,
                    idempotency_key: Optional[str] = None, priority: int = 100) -> Dict[str, Any]:
    return queue.enqueue(
        job_type=ANALYZE_JOB_TYPE,
        subject_type=SUBJECT_TYPE,
        subject_id=document_id,
        submitted_by=submitted_by,
        priority=priority,
        idempotency_key=idempotency_key,
        input_params={'document_id': document_id},
    )


def enqueue_generate(queue: AgentJobQueue, *, analysis_id: str, language: Optional[str],
                     submitted_by: str, idempotency_key: Optional[str] = None,
                     priority: int = 100) -> Dict[str, Any]:
    return queue.enqueue(
        job_type=GENERATE_JOB_TYPE,
        subject_type=SUBJECT_TYPE,
        subject_id=analysis_id,
        submitted_by=submitted_by,
        priority=priority,
        idempotency_key=idempotency_key,
        input_params={'analysis_id': analysis_id, 'language': language},
    )


def _handle_analyze(job: Dict[str, Any]) -> Dict[str, Any]:
    params = job.get('input_params') or {}
    return run_analyze(str(params.get('document_id') or job.get('subject_id') or ''))


def _handle_generate(job: Dict[str, Any]) -> Dict[str, Any]:
    params = job.get('input_params') or {}
    return run_generate(str(params.get('analysis_id') or job.get('subject_id') or ''),
                        params.get('language'))


def register(queue: AgentJobQueue) -> None:
    queue.register_handler(ANALYZE_JOB_TYPE, _handle_analyze)
    queue.register_handler(GENERATE_JOB_TYPE, _handle_generate)
