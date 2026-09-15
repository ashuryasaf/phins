"""
Claims Bot job adapter: claim authenticity / fraud probability report
(``POST /api/claims/probability-report``).

``generate_probability_report`` is the route's former inline body (full
Claims Bot when importable, the basic scoring fallback otherwise). It
returns the *unsanitised* report; the route and the handler both apply the
portal's ``sanitize_claim_probability_report`` before anything leaves the
process.
"""

import hashlib
import json
from datetime import datetime
from typing import Any, Dict, Optional

from services.agent_job_queue import AgentJobQueue

JOB_TYPE = 'claims_probability_report'
SUBJECT_TYPE = 'claim'


def generate_probability_report(context, claim_id: str) -> Optional[Dict[str, Any]]:
    """Return the probability report for ``claim_id`` or ``None`` when the
    Claims Bot could not produce one. Raises ``KeyError`` if the claim does
    not exist (the route has already checked, the worker re-checks)."""
    claim = context.claims.get(claim_id)
    if not claim:
        raise KeyError(f'Claim {claim_id} not found')

    try:
        from services.claims_bot_service import init_claims_bot_service
        claims_bot = init_claims_bot_service(
            customers=context.customers,
            policies=context.policies,
            claims=context.claims,
            underwriting=context.underwriting_apps,
            audit_service=context.audit,
        )
    except ImportError:
        claims_bot = None

    if not claims_bot:
        # Fallback: Generate a basic probability report without the full service
        customer_id = claim.get('customer_id', '')
        policy_id = claim.get('policy_id', '')
        claimed_amount = float(claim.get('claimed_amount', 0) or 0)

        uw_data = None
        for _uw_id, uw in context.underwriting_apps.items():
            if uw.get('customer_id') == customer_id or uw.get('policy_id') == policy_id:
                uw_data = uw
                break

        policy = context.policies.get(policy_id, {})
        coverage = float(policy.get('coverage_amount', 500000) or 500000)
        amount_ratio = claimed_amount / coverage if coverage > 0 else 0

        auth_score = 0.75
        if amount_ratio > 0.9:
            auth_score -= 0.2
        elif amount_ratio > 0.7:
            auth_score -= 0.1
        if uw_data:
            if uw_data.get('medical_conditions'):
                auth_score += 0.05
            if uw_data.get('identity_verified'):
                auth_score += 0.05
        auth_score = max(0.1, min(0.95, auth_score))

        return {
            'id': f"PROB-RPT-{datetime.now().strftime('%Y%m%d%H%M%S')}",
            'claim_id': claim_id,
            'customer_id': customer_id,
            'policy_id': policy_id,
            'assessment_date': datetime.now().isoformat(),
            'authenticity_probability': auth_score,
            'authenticity_percentage': f"{auth_score * 100:.1f}%",
            'fraud_probability': 1 - auth_score,
            'fraud_percentage': f"{(1 - auth_score) * 100:.1f}%",
            'component_scores': {
                'document_authenticity': 0.85,
                'medical_consistency': 0.80,
                'timing_legitimacy': 0.75,
                'amount_reasonability': 1 - (amount_ratio * 0.5),
                'customer_history': 0.85,
                'underwriting_alignment': 0.80 if uw_data else 0.50,
            },
            'hidden_conditions': {'detected': 0, 'conditions': [], 'impact_score': 0},
            'fraud_indicators': {'count': 0, 'indicators': [], 'high_severity_count': 0},
            'recommendation': 'approve_full' if auth_score >= 0.7 else 'refer_investigation',
            'recommendation_display': 'Approve Full' if auth_score >= 0.7 else 'Refer Investigation',
            'confidence_level': 0.75,
            'risk_level': 'low' if auth_score >= 0.8 else ('medium' if auth_score >= 0.6 else 'high'),
            'explanation': f"Basic assessment completed. Authenticity probability: {auth_score:.1%}",
            'ai_analysis': {
                'summary': f"This claim has been assessed with {auth_score:.1%} authenticity probability.",
                'key_findings': [f"Claim amount ratio: {amount_ratio:.1%} of coverage"],
                'red_flags': [] if auth_score >= 0.7 else ['Amount ratio high'],
                'green_flags': ['Documentation provided'] if claim.get('files_count', 0) > 0 else [],
            },
        }

    prob_report = claims_bot.generate_probability_report(claim_id)
    return prob_report.to_dict() if prob_report else None


def response_body(report: Dict[str, Any]) -> Dict[str, Any]:
    return {'success': True, 'report': report}


def idempotency_key(claim: Dict[str, Any], submitted_by: str) -> str:
    # Content-addressed on the claim record: an identical re-request by the
    # same principal returns the existing job; once the claim changes (new
    # files, status, amount) a fresh report is produced.
    digest = hashlib.sha256(json.dumps(claim, sort_keys=True, default=str).encode('utf-8')).hexdigest()
    return f"{digest}:{JOB_TYPE}:{submitted_by}"


def enqueue_probability_report(queue: AgentJobQueue, *, claim_id: str, claim: Dict[str, Any],
                               submitted_by: str, priority: int = 100) -> Dict[str, Any]:
    return queue.enqueue(
        job_type=JOB_TYPE,
        subject_type=SUBJECT_TYPE,
        subject_id=claim_id,
        submitted_by=submitted_by,
        priority=priority,
        idempotency_key=idempotency_key(claim, submitted_by),
        input_params={'claim_id': claim_id},
    )


def sanitize_claim_probability_report(report: Dict[str, Any]) -> Dict[str, Any]:
    """Return a safe report payload for UI usage.

    Removes raw evidence arrays that can expose unnecessary sensitive details.
    Shared by the web route and the standalone worker so both paths serve the
    identical redaction (``web_portal/server.py`` delegates here).
    """
    if not isinstance(report, dict):
        return {}

    def _severity(value) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    sanitized = dict(report)
    fraud_section = sanitized.get('fraud_indicators')
    if isinstance(fraud_section, dict):
        cleaned_indicators = []
        for indicator in fraud_section.get('indicators', []):
            if not isinstance(indicator, dict):
                continue
            cleaned = dict(indicator)
            cleaned.pop('evidence', None)
            cleaned_indicators.append(cleaned)
        fraud_section = dict(fraud_section)
        fraud_section['indicators'] = cleaned_indicators
        fraud_section['count'] = len(cleaned_indicators)
        fraud_section['high_severity_count'] = sum(
            1 for item in cleaned_indicators if _severity(item.get('severity')) > 0.7
        )
        sanitized['fraud_indicators'] = fraud_section
    return sanitized


def make_handler(context):
    def _handle(job: Dict[str, Any]) -> Dict[str, Any]:
        params = job.get('input_params') or {}
        claim_id = str(params.get('claim_id') or job.get('subject_id') or '')
        report = generate_probability_report(context, claim_id)
        if report is None:
            raise RuntimeError('Failed to generate probability report')
        sanitize = context.sanitize_claim_report or sanitize_claim_probability_report
        report = sanitize(report)
        return response_body(report)
    return _handle


def register(queue: AgentJobQueue, context) -> None:
    queue.register_handler(JOB_TYPE, make_handler(context))
