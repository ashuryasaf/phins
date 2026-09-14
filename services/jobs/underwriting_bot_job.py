"""
Underwriting Bot job adapter: AI document assessment for the risk dashboard
(``POST /api/risk-dashboard/ai-assess``).

``run_ai_assessment`` is the route's former inline body; the synchronous
route and the queue handler both call it, so the payload is identical
either way.
"""

import base64
import hashlib
import random
from datetime import datetime
from typing import Any, Dict, Optional

from services.agent_job_queue import AgentJobQueue

JOB_TYPE = 'underwriting_bot_assessment'
SUBJECT_TYPE = 'application'

# File upload limits enforced by the route (kept here so the queue payload
# can never exceed what the synchronous path accepts).
MAX_FILE_BYTES = 10 * 1024 * 1024
SUPPORTED_EXTENSIONS = ('.pdf', '.png', '.jpg', '.jpeg', '.gif', '.bmp', '.tiff', '.doc', '.docx')


def run_ai_assessment(context, *, filename: str, file_content: bytes,
                      mime_type: str, actor: str) -> Dict[str, Any]:
    """Run the Underwriting Bot over one uploaded file; returns the
    ``assessment`` payload of the synchronous response."""
    from services.underwriting_bot_service import UnderwritingBotService, MetadataType

    bot_service = UnderwritingBotService(
        customers=context.customers,
        policies=context.policies,
        underwriting_apps=context.underwriting_apps,
        claims=context.claims,
        audit_service=context.audit,
    )

    lower_name = (filename or '').lower()
    metadata_type = MetadataType.OTHER_DOCUMENT
    if lower_name.endswith('.pdf'):
        # Attempt to determine if it's a medical report or other document
        metadata_type = MetadataType.MEDICAL_REPORT
    elif lower_name.endswith(('.png', '.jpg', '.jpeg', '.gif', '.bmp', '.tiff')):
        metadata_type = MetadataType.PHOTO
    elif lower_name.endswith(('.doc', '.docx')):
        metadata_type = MetadataType.OTHER_DOCUMENT

    assessment_id = f"AI-ASSESS-{datetime.now().strftime('%Y%m%d%H%M%S')}-{random.randint(1000, 9999)}"
    assessment = bot_service.start_assessment(
        underwriting_id=assessment_id,
        customer_id=f"UPLOAD-{datetime.now().strftime('%Y%m%d')}",
        policy_id=f"POL-UPLOAD-{random.randint(1000, 9999)}",
    )
    metadata = bot_service.add_metadata(
        assessment_id=assessment.id,
        metadata_type=metadata_type,
        file_name=filename,
        file_path='',  # No file path needed for direct content
        file_content=file_content,
        mime_type=mime_type or '',
    )
    bot_service.process_metadata(metadata.id, file_content=file_content)
    report = bot_service.run_risk_assessment(assessment.id)

    risk_level = report.risk_level.value if hasattr(report.risk_level, 'value') else str(report.risk_level)
    recommendation = (report.recommendation.value if hasattr(report.recommendation, 'value')
                      else str(report.recommendation))
    assessment_result = {
        'assessment_id': assessment.id,
        'report_id': report.id,
        'risk_score': report.overall_risk_score,
        'risk_level': risk_level,
        'recommendation': recommendation,
        'confidence_level': report.confidence_level,
        'identity_verified': report.identity_verified,
        'identity_score': report.identity_score,
        'document_score': report.document_score,
        'medical_score': report.medical_score,
        'behavioral_score': report.behavioral_score,
        'fraud_score': report.fraud_score,
        'explanation': report.explanation,
        'risk_factors': [rf.to_dict() for rf in report.risk_factors] if report.risk_factors else [],
        'processing_time_seconds': report.processing_time_seconds,
        'file_analyzed': filename,
        'file_size': len(file_content),
        'analyzed_by': actor,
        'analyzed_at': datetime.now().isoformat(),
    }

    if context.audit:
        try:
            context.audit.log(actor, 'ai_assessment', 'risk_dashboard', assessment.id, {
                'file_name': filename,
                'risk_score': report.overall_risk_score,
                'risk_level': risk_level,
                'recommendation': recommendation,
            })
        except Exception:
            pass
    return assessment_result


def response_body(assessment: Dict[str, Any]) -> Dict[str, Any]:
    """Full synchronous response body around an assessment payload."""
    return {
        'success': True,
        'message': 'AI assessment completed successfully',
        'assessment': assessment,
    }


def idempotency_key(file_content: bytes, submitted_by: str) -> str:
    # Content-addressed per submitter: the same file re-sent by the same
    # user returns the existing job; another user's identical upload is a
    # separate job (no cross-user job visibility).
    digest = hashlib.sha256(file_content).hexdigest()
    return f"{digest}:{JOB_TYPE}:{submitted_by}"


def enqueue_ai_assessment(queue: AgentJobQueue, *, filename: str, file_content: bytes,
                          mime_type: str, actor: str, submitted_by: str,
                          priority: int = 100) -> Dict[str, Any]:
    if len(file_content) > MAX_FILE_BYTES:
        raise ValueError('File too large. Maximum size is 10MB.')
    digest = hashlib.sha256(file_content).hexdigest()
    return queue.enqueue(
        job_type=JOB_TYPE,
        subject_type=SUBJECT_TYPE,
        subject_id=f"UPLOAD-{digest[:16]}",
        submitted_by=submitted_by,
        priority=priority,
        idempotency_key=idempotency_key(file_content, submitted_by),
        input_params={
            'filename': filename,
            'mime_type': mime_type or '',
            'actor': actor,
            'file_b64': base64.b64encode(file_content).decode('ascii'),
        },
    )


def make_handler(context):
    def _handle(job: Dict[str, Any]) -> Dict[str, Any]:
        params = job.get('input_params') or {}
        file_content = base64.b64decode(params.get('file_b64') or b'')
        assessment = run_ai_assessment(
            context,
            filename=str(params.get('filename') or ''),
            file_content=file_content,
            mime_type=str(params.get('mime_type') or ''),
            actor=str(params.get('actor') or job.get('submitted_by') or 'admin'),
        )
        return response_body(assessment)
    return _handle


def register(queue: AgentJobQueue, context) -> None:
    queue.register_handler(JOB_TYPE, make_handler(context))
