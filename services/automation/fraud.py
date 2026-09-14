"""Fraud heuristics (pure rules) for applications, claims and activity
patterns. Moved verbatim from ``ai_automation_controller``."""

from typing import Any, Dict

from services.automation.types import FraudRisk


def application_fraud_risk(application_data: Dict[str, Any]) -> FraudRisk:
    """Pattern/anomaly indicators on an underwriting application."""
    fraud_indicators = 0
    if application_data.get('multiple_applications_same_day', False):
        fraud_indicators += 2
    if application_data.get('inconsistent_information', False):
        fraud_indicators += 3
    if application_data.get('high_coverage_new_customer', False):
        fraud_indicators += 1
    if application_data.get('suspicious_documents', False):
        fraud_indicators += 3
    if application_data.get('recent_claims_count', 0) > 2:
        fraud_indicators += 2

    if fraud_indicators >= 5:
        return FraudRisk.CRITICAL
    if fraud_indicators >= 3:
        return FraudRisk.HIGH
    if fraud_indicators >= 1:
        return FraudRisk.MEDIUM
    return FraudRisk.LOW


def claim_fraud_risk(claim_data: Dict[str, Any]) -> FraudRisk:
    """Fraud indicators on a claim submission."""
    fraud_score = 0
    if claim_data.get('recent_claims_count', 0) > 3:
        fraud_score += 2
    if claim_data.get('days_since_policy_start', 365) < 30:
        fraud_score += 1
    if not claim_data.get('has_complete_documentation', True):
        fraud_score += 1
    average_claim = claim_data.get('average_claim_for_type', 5000)
    if claim_data.get('claimed_amount', 0) > average_claim * 3:
        fraud_score += 2

    if fraud_score >= 4:
        return FraudRisk.CRITICAL
    if fraud_score >= 2:
        return FraudRisk.HIGH
    if fraud_score >= 1:
        return FraudRisk.MEDIUM
    return FraudRisk.LOW


def activity_fraud_report(data: Dict[str, Any]) -> Dict[str, Any]:
    """Scored flags over activity patterns (the function-based ``detect_fraud``)."""
    fraud_score = 0.0
    flags = []

    multiple_apps = data.get('multiple_applications', 0)
    if multiple_apps >= 5:
        fraud_score += 0.4
        flags.append('multiple_applications_same_ip')
    elif multiple_apps >= 3:
        fraud_score += 0.2
        flags.append('several_applications_same_ip')

    claim_amount = data.get('claim_amount', 0)
    policy_age_days = data.get('policy_age_days', 365)
    if claim_amount > 0:
        if claim_amount > 500000:
            fraud_score += 0.3
            flags.append('unusually_high_claim_amount')
        if policy_age_days < 30 and claim_amount > 10000:
            fraud_score += 0.4
            flags.append('claim_shortly_after_policy_start')

    claim_frequency = data.get('claim_frequency', 0)
    if claim_frequency >= 5:
        fraud_score += 0.3
        flags.append('excessive_claim_frequency')
    elif claim_frequency >= 3:
        fraud_score += 0.15
        flags.append('high_claim_frequency')

    if data.get('inconsistent_data', False):
        fraud_score += 0.25
        flags.append('data_inconsistencies_detected')

    if claim_amount > 0 and claim_amount % 1000 == 0 and claim_amount >= 5000:
        fraud_score += 0.1
        flags.append('suspicious_round_number_claim')

    if data.get('applications_last_24h', 0) >= 10:
        fraud_score += 0.5
        flags.append('suspicious_application_velocity')

    fraud_score = min(1.0, fraud_score)
    if fraud_score >= 0.7:
        level, action = 'CRITICAL', 'BLOCK_AND_INVESTIGATE'
    elif fraud_score >= 0.5:
        level, action = 'HIGH', 'MANUAL_REVIEW_REQUIRED'
    elif fraud_score >= 0.3:
        level, action = 'MEDIUM', 'ENHANCED_VERIFICATION'
    else:
        level, action = 'LOW', 'PROCEED_NORMALLY'

    return {
        'fraud_risk_level': level,
        'fraud_score': round(fraud_score, 2),
        'flags': flags,
        'recommended_action': action,
        'requires_investigation': fraud_score >= 0.5,
    }


__all__ = ['application_fraud_risk', 'claim_fraud_risk', 'activity_fraud_report']
