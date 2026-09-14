"""Automated underwriting gate (pure rules).

``assess_risk`` is the deterministic rule scorer (0.0–1.0, higher is
better); ``gate`` turns a score, a fraud level and the segment's cut-offs
into the decision + details the controller has always returned; and
``confidence_band`` names where the score sits relative to those cut-offs so
callers (and the calibration loop) can see how close a decision was to the
edge without re-deriving it.
"""

from typing import Any, Dict, Tuple

from services.automation.types import AutomationDecision, FraudRisk

BAND_AUTO_APPROVE = 'auto_approve'
BAND_REVIEW_UPPER = 'review_upper'    # between the cut-offs, above the midpoint
BAND_REVIEW_LOWER = 'review_lower'    # between the cut-offs, at or below the midpoint
BAND_AUTO_REJECT = 'auto_reject'
BAND_FRAUD_HOLD = 'fraud_hold'        # decision forced to review by the fraud gate


def assess_risk(application_data: Dict[str, Any]) -> float:
    """Rule score in 0.0–1.0, higher is better (identical to the historical
    ``AIAutomationController._assess_risk``)."""
    score = 0.5

    age = application_data.get('age', 30)
    if 25 <= age <= 45:
        score += 0.2
    elif 18 <= age < 25 or 45 < age <= 55:
        score += 0.1
    elif age > 65:
        score -= 0.2

    if not application_data.get('smoker', False):
        score += 0.1
    else:
        score -= 0.15

    if not application_data.get('pre_existing_conditions', False):
        score += 0.15
    else:
        score -= 0.2

    health_score = application_data.get('health_score', 5)
    score += (health_score - 5) * 0.05

    if application_data.get('employment_stable', False):
        score += 0.1

    return max(0.0, min(1.0, score))


def confidence_band(risk_score: float, approve_threshold: float, reject_threshold: float,
                    fraud_hold: bool = False) -> Dict[str, Any]:
    """Where ``risk_score`` sits relative to the segment's cut-offs.

    ``margin`` is the distance to the nearest cut-off (how far the score
    would have to move to change the automated outcome); near-zero margins
    are the decisions a reviewer should look at first and the ones threshold
    calibration moves.
    """
    approve = float(approve_threshold)
    reject = float(reject_threshold)
    score = float(risk_score)
    if fraud_hold:
        band = BAND_FRAUD_HOLD
    elif score >= approve:
        band = BAND_AUTO_APPROVE
    elif score <= reject:
        band = BAND_AUTO_REJECT
    elif score > (approve + reject) / 2:
        band = BAND_REVIEW_UPPER
    else:
        band = BAND_REVIEW_LOWER
    return {
        'band': band,
        'margin': round(min(abs(score - approve), abs(score - reject)), 4),
        'approve_threshold': approve,
        'reject_threshold': reject,
    }


def gate(risk_score: float, fraud_risk: FraudRisk, approve_threshold: float,
         reject_threshold: float) -> Tuple[AutomationDecision, Dict[str, Any]]:
    """The historical decision ladder: fraud first, then the two cut-offs."""
    if fraud_risk in (FraudRisk.HIGH, FraudRisk.CRITICAL):
        return AutomationDecision.HUMAN_REVIEW, {
            'reason': 'Potential fraud detected',
            'fraud_risk': fraud_risk.value,
            'requires_investigation': True,
        }
    if risk_score >= approve_threshold:
        return AutomationDecision.AUTO_APPROVE, {
            'risk_score': risk_score,
            'premium_adjustment': 1.0,
            'conditions': [],
        }
    if risk_score <= reject_threshold:
        return AutomationDecision.AUTO_REJECT, {
            'risk_score': risk_score,
            'rejection_reason': 'Risk score too low for coverage',
        }
    return AutomationDecision.HUMAN_REVIEW, {
        'risk_score': risk_score,
        'review_priority': 'medium' if risk_score > 0.5 else 'high',
        'suggested_action': 'approve_with_conditions' if risk_score > 0.5 else 'request_medical_exam',
    }


def risk_level(risk_score: float) -> str:
    """Coarse label used by the function-based ``auto_underwrite`` API."""
    if risk_score >= 0.8:
        return 'low'
    if risk_score >= 0.6:
        return 'medium'
    if risk_score >= 0.4:
        return 'high'
    return 'very_high'


__all__ = [
    'assess_risk', 'confidence_band', 'gate', 'risk_level',
    'BAND_AUTO_APPROVE', 'BAND_REVIEW_UPPER', 'BAND_REVIEW_LOWER', 'BAND_AUTO_REJECT', 'BAND_FRAUD_HOLD',
]
