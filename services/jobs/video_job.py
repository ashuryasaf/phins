"""
Video Agents job adapter: provider submission of one video generation job
(``POST /api/admin/media/video-agents/submit``).

The synchronous route validates, applies the per-user / per-campaign / global
daily caps and submits to the provider inline. Under ``PHINS_AGENT_ASYNC``
the same ``VideoAgentsService.submit_video_job`` call runs on the queue, so
the provider round-trip (and its retries) leaves the request thread; the
video job dict the route used to return is the queue job's ``result``.

Validation and cost-control errors (``ValueError`` / ``RuntimeError``) raised
by the service are recorded as the job's ``error_message`` exactly as the
route would have reported them.
"""

import hashlib
import json
from typing import Any, Dict, Optional

from services.agent_job_queue import AgentJobQueue

JOB_TYPE = 'video_generation_submit'
SUBJECT_TYPE = 'video_job'

SUBMIT_FIELDS = (
    'campaign_id', 'provider', 'pipeline_type', 'title', 'prompt_override',
    'provider_model', 'aspect_ratio', 'duration_seconds', 'resolution',
    'image_data_url', 'reference_image_asset_id', 'poll_mode',
    'auto_publish_to_hero', 'callback_url', 'submitted_by', 'metadata',
)


def run_submit(**params) -> Dict[str, Any]:
    from services.video_agents_service import get_video_agents_service
    job = get_video_agents_service().submit_video_job(**params)
    return {'job': job, 'success': True}


def enqueue_submit(queue: AgentJobQueue, *, params: Dict[str, Any], submitted_by: str,
                   idempotency_key: Optional[str] = None, priority: int = 100) -> Dict[str, Any]:
    clean = {k: params.get(k) for k in SUBMIT_FIELDS if k in params}
    clean['submitted_by'] = submitted_by
    digest = hashlib.sha256(
        json.dumps(clean, sort_keys=True, default=str).encode('utf-8')).hexdigest()
    return queue.enqueue(
        job_type=JOB_TYPE,
        subject_type=SUBJECT_TYPE,
        subject_id=f"VIDEO-{digest[:16]}",
        submitted_by=submitted_by,
        priority=priority,
        idempotency_key=idempotency_key,
        input_params=clean,
        # A provider submit is not idempotent (the provider may have accepted
        # a paid job before the error surfaced) and each attempt creates a
        # video job record, so the queue never retries it — same rule as the
        # external-call gateway's submit policy.
        max_attempts=1,
    )


def _handle(job: Dict[str, Any]) -> Dict[str, Any]:
    params = dict(job.get('input_params') or {})
    params.setdefault('submitted_by', job.get('submitted_by') or 'admin')
    # Same defaults the route applies before calling the service.
    params.setdefault('campaign_id', '')
    params.setdefault('provider', 'gemini')
    params.setdefault('pipeline_type', 'introductions')
    return run_submit(**{k: v for k, v in params.items() if k in SUBMIT_FIELDS})


def register(queue: AgentJobQueue) -> None:
    queue.register_handler(JOB_TYPE, _handle)
