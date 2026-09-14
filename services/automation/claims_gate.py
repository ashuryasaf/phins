"""Smart claims processing ladder (pure rules).

Moved verbatim from ``AIAutomationController.auto_process_claim``. Returns the
decision, its details and the fraud level consulted (``FraudRisk.LOW`` when
the low-value fast path skipped the fraud check).
"""

from typing import Any, Dict, Tuple

from services.automation.fraud import claim_fraud_risk
from services.automation.types import AutomationDecision, FraudRisk

LOW_VALUE_LIMIT = 1000
LOW_VALUE_TYPES = ('medical', 'dental')
COMPLEX_TYPES = ('disability', 'death', 'major_medical')


def gate(claim_data: Dict[str, Any]) -> Tuple[AutomationDecision, Dict[str, Any], FraudRisk]:
    claim_amount = claim_data.get('claimed_amount', 0)
    claim_type = claim_data.get('type', 'unknown')
    policy_coverage = claim_data.get('policy_coverage', 0)

    if claim_amount < LOW_VALUE_LIMIT and claim_type in LOW_VALUE_TYPES:
        return AutomationDecision.AUTO_APPROVE, {
            'approved_amount': claim_amount,
            'reason': 'Low-value claim with standard documentation',
            'payment_method': 'direct_deposit',
        }, FraudRisk.LOW

    fraud_risk = claim_fraud_risk(claim_data)
    if fraud_risk in (FraudRisk.HIGH, FraudRisk.CRITICAL):
        details = {
            'reason': 'Potential fraud detected in claim',
            'fraud_risk': fraud_risk.value,
            'requires_investigation': True,
        }
    elif claim_amount > policy_coverage:
        details = {
            'reason': 'Claim exceeds policy coverage',
            'suggested_action': 'approve_partial',
            'max_approved_amount': policy_coverage,
        }
    elif claim_type in COMPLEX_TYPES:
        details = {
            'reason': 'Complex claim type requires adjuster review',
            'priority': 'high',
        }
    else:
        details = {
            'reason': 'Standard review required',
            'priority': 'normal',
            'suggested_action': 'approve',
            'suggested_amount': claim_amount,
        }
    return AutomationDecision.HUMAN_REVIEW, details, fraud_risk


__all__ = ['gate', 'LOW_VALUE_LIMIT', 'LOW_VALUE_TYPES', 'COMPLEX_TYPES']
