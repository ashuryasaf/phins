"""
Pension Data Agent job adapter: Mislaka (מסלקה) policy import into the AI
risk-reports pipeline (``POST /api/mislaka/import``).

``run_pension_import`` is the route's former inline body — fetch the
person's policies, convert to the Hebrew CSV layout, parse, analyse and
generate the Hebrew report — and returns the synchronous response body.
Failure modes the route mapped to HTTP statuses are typed exceptions so the
synchronous path keeps its 503 / 404 and the queue records them as errors.

The national ID number is PII: the job subject is a SHA-256 prefix of it,
never the number, and the number itself travels in ``input_params`` inside
a ``security.vault`` blob (Fernet-encrypted whenever ``PHINS_ENCRYPTION_KEY``
is configured). Job views served over HTTP drop ``input_params`` entirely.
"""

import csv
import hashlib
import io
from typing import Any, Dict, Optional

from security.vault import decrypt_json, encrypt_json
from services.agent_job_queue import AgentJobQueue

JOB_TYPE = 'pension_import'
SUBJECT_TYPE = 'pension_import'

CSV_FIELDNAMES = [
    'מספר פוליסה', 'סוג מוצר', 'חברה', 'תאריך תחילה',
    'סטטוס', 'פרמיה חודשית', 'סכום כיסוי', 'ערך צבירה',
    'דמי ניהול', 'מסלול השקעה', 'מוטבים',
]


class MislakaNotConfigured(RuntimeError):
    """The Mislaka API has no credentials (route: 503)."""


class NoPoliciesFound(LookupError):
    """Mislaka returned no policies for the person (route: 404)."""

    def __init__(self, message: Optional[str]):
        super().__init__(message or 'No policies returned from Mislaka')
        self.message = message or 'No policies returned from Mislaka'


def policies_to_csv(policies) -> bytes:
    csv_buffer = io.StringIO()
    writer = csv.DictWriter(csv_buffer, fieldnames=CSV_FIELDNAMES)
    writer.writeheader()
    for p in policies:
        writer.writerow({
            'מספר פוליסה': p.policy_number,
            'סוג מוצר': p.product_type,
            'חברה': p.company_name,
            'תאריך תחילה': p.start_date,
            'סטטוס': p.status,
            'פרמיה חודשית': p.premium_monthly,
            'סכום כיסוי': p.cover_amount,
            'ערך צבירה': p.accumulated_value,
            'דמי ניהול': f"{p.management_fee_percent}%",
            'מסלול השקעה': p.investment_track,
            'מוטבים': ', '.join(p.beneficiaries) if p.beneficiaries else '',
        })
    return csv_buffer.getvalue().encode('utf-8')


def run_pension_import(*, id_number: str, user_id: str, user_role: str) -> Dict[str, Any]:
    from services.mislaka_api_service import get_mislaka_service
    from services.ai_risk_reports_service import get_ai_reports_service

    mislaka = get_mislaka_service()
    if not mislaka.is_configured():
        raise MislakaNotConfigured('Mislaka API not configured')

    result = mislaka.get_person_policies(id_number)
    if result.status.value != 'success' or not result.policies:
        raise NoPoliciesFound(result.error_message)

    csv_content = policies_to_csv(result.policies)
    ai_service = get_ai_reports_service()
    doc_result = ai_service.parse_file(
        filename=f'mislaka_policies_{id_number[-4:]}.csv',
        file_content=csv_content,
        file_type='csv',
        owner_id=user_id,
        owner_role=user_role,
    )
    analysis = ai_service.analyze(doc_result['document_id'])
    report = ai_service.generate_report(analysis.id, language='hebrew')

    return {
        'success': True,
        'message': f'Imported {len(result.policies)} policies from Mislaka',
        'document_id': doc_result['document_id'],
        'analysis_id': analysis.id,
        'report_id': report.id,
        'policies_count': len(result.policies),
        'total_accumulated': result.total_accumulated,
        'total_monthly_premium': result.total_monthly_premium,
    }


def subject_id_for(id_number: str) -> str:
    """Job subject key for a person. Uses the identity master's keyed hash so
    the queue never carries a value that a 9-digit brute force could invert;
    the same person therefore maps to the same subject across pension jobs
    and the customer record."""
    cleaned = str(id_number or '').strip()
    try:
        from services.customer_identity_service import hash_national_id, normalize_national_id
        try:
            code, normalized = normalize_national_id(cleaned, 'IL')
        except Exception:
            code, normalized = 'IL', cleaned
        digest = hash_national_id(code, normalized)
    except ImportError:
        digest = hashlib.sha256(cleaned.encode('utf-8')).hexdigest()
    return f"PERSON-{digest[:16]}"


def enqueue_pension_import(queue: AgentJobQueue, *, id_number: str, user_id: str,
                           user_role: str, submitted_by: str,
                           idempotency_key: Optional[str] = None,
                           priority: int = 100) -> Dict[str, Any]:
    return queue.enqueue(
        job_type=JOB_TYPE,
        subject_type=SUBJECT_TYPE,
        subject_id=subject_id_for(id_number),
        submitted_by=submitted_by,
        priority=priority,
        idempotency_key=idempotency_key,
        input_params={
            'subject_vault': encrypt_json({'id_number': id_number}).to_json(),
            'user_id': user_id,
            'user_role': user_role,
        },
    )


def _handle(job: Dict[str, Any]) -> Dict[str, Any]:
    params = job.get('input_params') or {}
    secret = decrypt_json(str(params.get('subject_vault') or ''), default=None) or {}
    id_number = str(secret.get('id_number') or '')
    if not id_number:
        raise RuntimeError('pension import job is missing its subject (vault unreadable)')
    return run_pension_import(
        id_number=id_number,
        user_id=str(params.get('user_id') or job.get('submitted_by') or ''),
        user_role=str(params.get('user_role') or 'customer'),
    )


def register(queue: AgentJobQueue) -> None:
    queue.register_handler(JOB_TYPE, _handle)
