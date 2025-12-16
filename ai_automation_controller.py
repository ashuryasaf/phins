#!/usr/bin/env python3
"""
AI Automation Controller for PHINS Insurance Platform

This module provides automated decision-making capabilities for:
- Quote generation
- Underwriting decisions
- Claims processing
- Fraud detection

All functions use rule-based logic with confidence scoring.
"""

from typing import Dict, Any, Literal
from datetime import datetime
import random


def auto_quote(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Generate automated insurance quote based on customer data.
    
    Args:
        data: Dictionary containing:
            - age: int (customer age)
            - coverage_type: str (health, life, auto, property)
            - coverage_amount: float (desired coverage amount)
            - health_score: int (1-10, optional, for health/life insurance)
    
    Returns:
        Dictionary with:
            - quote_amount: float (annual premium)
            - confidence_score: float (0.0-1.0)
            - risk_factors: list of identified risk factors
    """
    age = data.get('age', 30)
    coverage_type = data.get('coverage_type', 'life').lower()
    coverage_amount = data.get('coverage_amount', 100000)
    health_score = data.get('health_score', 7)
    
    # Base rates per $100k coverage
    base_rates = {
        'health': 800,
        'life': 1200,
        'auto': 600,
        'property': 1500,
        'disability': 1000
    }
    
    base_rate = base_rates.get(coverage_type, 1000)
    
    # Age factor
    if age < 25:
        age_factor = 1.3
    elif age < 35:
        age_factor = 1.0
    elif age < 50:
        age_factor = 1.2
    elif age < 65:
        age_factor = 1.5
    else:
        age_factor = 2.0
    
    # Health score factor (for health/life insurance)
    if coverage_type in ['health', 'life', 'disability']:
        health_factor = 2.0 - (health_score / 10.0)  # 1.0 to 1.9
    else:
        health_factor = 1.0
    
    # Coverage amount factor
    coverage_factor = coverage_amount / 100000
    
    # Calculate quote
    annual_premium = base_rate * age_factor * health_factor * coverage_factor
    
    # Calculate confidence score
    confidence = 0.85
    risk_factors = []
    
    if age < 18 or age > 75:
        confidence -= 0.2
        risk_factors.append('age_out_of_standard_range')
    
    if health_score < 5 and coverage_type in ['health', 'life']:
        confidence -= 0.15
        risk_factors.append('low_health_score')
    
    if coverage_amount > 1000000:
        confidence -= 0.1
        risk_factors.append('high_coverage_amount')
    
    # Ensure confidence is between 0 and 1
    confidence = max(0.0, min(1.0, confidence))
    
    return {
        'quote_amount': round(annual_premium, 2),
        'confidence_score': round(confidence, 2),
        'risk_factors': risk_factors,
        'monthly_premium': round(annual_premium / 12, 2),
        'coverage_type': coverage_type
    }


def auto_underwrite(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Automated underwriting decision based on risk assessment.
    
    Args:
        data: Dictionary containing:
            - age: int (applicant age)
            - smoker: bool (smoking status)
            - health_score: int (1-10)
            - bmi: float (Body Mass Index)
            - coverage_amount: float (optional)
            - medical_history: list (optional, list of conditions)
    
    Returns:
        Dictionary with:
            - decision: str (AUTO_APPROVE, AUTO_REJECT, MANUAL_REVIEW)
            - risk_score: float (0.0-1.0)
            - risk_level: str (low, medium, high, very_high)
            - reasons: list of decision factors
    """
    age = data.get('age', 30)
    smoker = data.get('smoker', False)
    health_score = data.get('health_score', 7)
    bmi = data.get('bmi', 25)
    coverage_amount = data.get('coverage_amount', 100000)
    medical_history = data.get('medical_history', [])
    
    # Calculate risk score (0 = highest risk, 1 = lowest risk)
    risk_score = 1.0
    reasons = []
    
    # Age risk
    if age < 18 or age > 70:
        risk_score -= 0.25
        reasons.append('age_high_risk')
    elif age > 60:
        risk_score -= 0.1
        reasons.append('age_moderate_risk')
    
    # Smoking risk
    if smoker:
        risk_score -= 0.2
        reasons.append('smoker')
    
    # Health score risk
    if health_score < 4:
        risk_score -= 0.3
        reasons.append('poor_health_score')
    elif health_score < 7:
        risk_score -= 0.15
        reasons.append('moderate_health_score')
    
    # BMI risk
    if bmi < 18.5 or bmi > 35:
        risk_score -= 0.2
        reasons.append('bmi_out_of_range')
    elif bmi > 30:
        risk_score -= 0.1
        reasons.append('bmi_elevated')
    
    # Medical history risk
    if len(medical_history) > 3:
        risk_score -= 0.2
        reasons.append('extensive_medical_history')
    elif len(medical_history) > 0:
        risk_score -= 0.1
        reasons.append('medical_history_present')
    
    # High coverage amount increases scrutiny
    if coverage_amount > 1000000:
        risk_score -= 0.05
        reasons.append('high_coverage_amount')
    
    # Ensure risk score is between 0 and 1
    risk_score = max(0.0, min(1.0, risk_score))
    
    # Determine risk level
    if risk_score >= 0.8:
        risk_level = 'low'
    elif risk_score >= 0.6:
        risk_level = 'medium'
    elif risk_score >= 0.4:
        risk_level = 'high'
    else:
        risk_level = 'very_high'
    
    # Make decision
    if risk_score >= 0.85:
        decision = 'AUTO_APPROVE'
        reasons.append('excellent_risk_profile')
    elif risk_score < 0.4:
        decision = 'AUTO_REJECT'
        reasons.append('unacceptable_risk_level')
    else:
        decision = 'MANUAL_REVIEW'
        reasons.append('requires_human_review')
    
    return {
        'decision': decision,
        'risk_score': round(risk_score, 2),
        'risk_level': risk_level,
        'reasons': reasons,
        'requires_medical_exam': risk_score < 0.7,
        'recommended_premium_adjustment': round((1.0 - risk_score) * 50, 2)  # % adjustment
    }


def auto_process_claim(claim: Dict[str, Any]) -> Dict[str, Any]:
    """
    Automated claims processing decision.
    
    Args:
        claim: Dictionary containing:
            - amount: float (claimed amount)
            - has_documents: bool (supporting documents provided)
            - claim_type: str (medical, accident, property, etc.)
            - policy_active: bool (policy in good standing)
            - claim_history: int (optional, number of previous claims)
    
    Returns:
        Dictionary with:
            - decision: str (AUTO_APPROVED, AUTO_REJECTED, MANUAL_REVIEW)
            - approved_amount: float (approved amount, may differ from claimed)
            - confidence: float (0.0-1.0)
            - reasons: list of decision factors
    """
    amount = claim.get('amount', 0)
    has_documents = claim.get('has_documents', False)
    claim_type = claim.get('claim_type', 'other').lower()
    policy_active = claim.get('policy_active', True)
    claim_history = claim.get('claim_history', 0)
    
    reasons = []
    approved_amount = amount
    confidence = 0.9
    
    # Policy must be active
    if not policy_active:
        return {
            'decision': 'AUTO_REJECTED',
            'approved_amount': 0,
            'confidence': 1.0,
            'reasons': ['policy_not_active']
        }
    
    # Documents required for processing
    if not has_documents:
        confidence -= 0.5
        reasons.append('missing_documents')
    
    # Small claims with documentation can be auto-approved
    if amount < 1000 and has_documents:
        decision = 'AUTO_APPROVED'
        reasons.append('small_claim_with_documentation')
    # Large claims need review
    elif amount > 10000:
        decision = 'MANUAL_REVIEW'
        reasons.append('large_claim_amount')
        confidence -= 0.2
    # Multiple claims trigger review
    elif claim_history > 3:
        decision = 'MANUAL_REVIEW'
        reasons.append('frequent_claimant')
        confidence -= 0.15
    # Medium claims with docs can be auto-approved
    elif amount <= 10000 and has_documents:
        decision = 'AUTO_APPROVED'
        reasons.append('standard_claim_with_documentation')
    # No docs = manual review
    else:
        decision = 'MANUAL_REVIEW'
        reasons.append('requires_verification')
    
    # Adjust confidence based on claim type
    high_risk_types = ['accident', 'liability', 'legal']
    if claim_type in high_risk_types:
        confidence -= 0.1
        if decision == 'AUTO_APPROVED' and amount > 5000:
            decision = 'MANUAL_REVIEW'
            reasons.append('high_risk_claim_type')
    
    confidence = max(0.0, min(1.0, confidence))
    
    return {
        'decision': decision,
        'approved_amount': approved_amount if decision == 'AUTO_APPROVED' else 0,
        'confidence': round(confidence, 2),
        'reasons': reasons,
        'processing_time_hours': 1 if decision == 'AUTO_APPROVED' else 48
    }


def detect_fraud(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Detect potential fraudulent activity patterns.
    
    Args:
        data: Dictionary containing:
            - ip_address: str (optional)
            - multiple_applications: int (applications from same IP)
            - claim_amount: float (optional)
            - policy_age_days: int (optional, days since policy started)
            - claim_frequency: int (optional, claims in last 12 months)
            - inconsistent_data: bool (optional, data inconsistencies detected)
    
    Returns:
        Dictionary with:
            - fraud_risk_level: str (LOW, MEDIUM, HIGH, CRITICAL)
            - fraud_score: float (0.0-1.0, higher = more suspicious)
            - flags: list of detected suspicious patterns
            - recommended_action: str
    """
    fraud_score = 0.0
    flags = []
    
    # Multiple applications from same IP
    multiple_apps = data.get('multiple_applications', 0)
    if multiple_apps >= 5:
        fraud_score += 0.4
        flags.append('multiple_applications_same_ip')
    elif multiple_apps >= 3:
        fraud_score += 0.2
        flags.append('several_applications_same_ip')
    
    # Unrealistic claim amount
    claim_amount = data.get('claim_amount', 0)
    policy_age_days = data.get('policy_age_days', 365)
    
    if claim_amount > 0:
        if claim_amount > 500000:
            fraud_score += 0.3
            flags.append('unusually_high_claim_amount')
        
        # Claim too soon after policy start
        if policy_age_days < 30 and claim_amount > 10000:
            fraud_score += 0.4
            flags.append('claim_shortly_after_policy_start')
    
    # High claim frequency
    claim_frequency = data.get('claim_frequency', 0)
    if claim_frequency >= 5:
        fraud_score += 0.3
        flags.append('excessive_claim_frequency')
    elif claim_frequency >= 3:
        fraud_score += 0.15
        flags.append('high_claim_frequency')
    
    # Data inconsistencies
    if data.get('inconsistent_data', False):
        fraud_score += 0.25
        flags.append('data_inconsistencies_detected')
    
    # Round-number claims (often fraudulent)
    if claim_amount > 0 and claim_amount % 1000 == 0 and claim_amount >= 5000:
        fraud_score += 0.1
        flags.append('suspicious_round_number_claim')
    
    # Velocity checks
    application_velocity = data.get('applications_last_24h', 0)
    if application_velocity >= 10:
        fraud_score += 0.5
        flags.append('suspicious_application_velocity')
    
    # Ensure fraud score is between 0 and 1
    fraud_score = min(1.0, fraud_score)
    
    # Determine risk level
    if fraud_score >= 0.7:
        fraud_risk_level = 'CRITICAL'
        recommended_action = 'BLOCK_AND_INVESTIGATE'
    elif fraud_score >= 0.5:
        fraud_risk_level = 'HIGH'
        recommended_action = 'MANUAL_REVIEW_REQUIRED'
    elif fraud_score >= 0.3:
        fraud_risk_level = 'MEDIUM'
        recommended_action = 'ENHANCED_VERIFICATION'
    else:
        fraud_risk_level = 'LOW'
        recommended_action = 'PROCEED_NORMALLY'
    
    return {
        'fraud_risk_level': fraud_risk_level,
        'fraud_score': round(fraud_score, 2),
        'flags': flags,
        'recommended_action': recommended_action,
        'requires_investigation': fraud_score >= 0.5
    }


def get_automation_controller():
    """
    Factory function to get the automation controller.
    Returns a dictionary with all automation functions.
    """
    return {
        'auto_quote': auto_quote,
        'auto_underwrite': auto_underwrite,
        'auto_process_claim': auto_process_claim,
        'detect_fraud': detect_fraud
    }


if __name__ == '__main__':
    # Demo usage
    print("=== AI Automation Controller Demo ===\n")
    
    # Demo: Auto Quote
    print("1. Auto Quote Generation:")
    quote_data = {
        'age': 30,
        'coverage_type': 'health',
        'coverage_amount': 100000,
        'health_score': 8
    }
    result = auto_quote(quote_data)
    print(f"   Quote Amount: ${result['quote_amount']:.2f}/year")
    print(f"   Confidence: {result['confidence_score']}")
    print(f"   Risk Factors: {result['risk_factors']}\n")
    
    # Demo: Auto Underwriting
    print("2. Automated Underwriting:")
    uw_data = {
        'age': 30,
        'smoker': False,
        'health_score': 9,
        'bmi': 22
    }
    result = auto_underwrite(uw_data)
    print(f"   Decision: {result['decision']}")
    print(f"   Risk Score: {result['risk_score']}")
    print(f"   Risk Level: {result['risk_level']}\n")
    
    # Demo: Claims Processing
    print("3. Smart Claims Processing:")
    claim_data = {
        'amount': 500,
        'has_documents': True,
        'claim_type': 'medical',
        'policy_active': True
    }
    result = auto_process_claim(claim_data)
    print(f"   Decision: {result['decision']}")
    print(f"   Approved Amount: ${result['approved_amount']}")
    print(f"   Confidence: {result['confidence']}\n")
    
    # Demo: Fraud Detection
    print("4. Fraud Detection:")
    fraud_data = {
        'multiple_applications': 6,
        'claim_amount': 50000,
        'policy_age_days': 15
    }
    result = detect_fraud(fraud_data)
    print(f"   Fraud Risk Level: {result['fraud_risk_level']}")
    print(f"   Fraud Score: {result['fraud_score']}")
    print(f"   Flags: {result['flags']}")
    print(f"   Recommended Action: {result['recommended_action']}")
