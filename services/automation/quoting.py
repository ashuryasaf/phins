"""Auto-quote premium rules (pure functions, no I/O, no logging).

Moved verbatim from ``AIAutomationController.generate_auto_quote`` /
``_calculate_quote_confidence``; the controller adds ids, timestamps and the
decision-log record around these.
"""

from typing import Any, Dict

BASE_RATE = 0.0012  # 0.12% of coverage

OCCUPATION_RISK = {
    'office_worker': 1.0,
    'healthcare': 1.1,
    'construction': 1.4,
    'transportation': 1.3,
    'emergency_services': 1.5,
    'manual_labor': 1.35,
}
DEFAULT_OCCUPATION_MULTIPLIER = 1.2


def age_multiplier(age: Any) -> float:
    if age < 25:
        return 1.2
    if age < 35:
        return 1.0
    if age < 45:
        return 1.15
    if age < 55:
        return 1.35
    return 1.6


def health_multiplier(health_score: Any) -> float:
    """1.0 (perfect health) … 1.9 on the 1-10 health scale."""
    return 2.0 - (health_score / 10)


def occupation_multiplier(occupation: Any) -> float:
    return OCCUPATION_RISK.get(occupation, DEFAULT_OCCUPATION_MULTIPLIER)


def quote_confidence(customer_data: Dict[str, Any]) -> float:
    """Confidence in the quote, from data completeness (0.7 base, cap 1.0)."""
    confidence = 0.7
    if customer_data.get('complete_medical_history'):
        confidence += 0.15
    if customer_data.get('stable_employment'):
        confidence += 0.1
    if customer_data.get('no_pre_existing_conditions'):
        confidence += 0.05
    return min(confidence, 1.0)


def compute_quote(customer_data: Dict[str, Any]) -> Dict[str, Any]:
    """Premium, multipliers and confidence for a customer profile.

    Returns the deterministic part of a quote; callers attach identifiers
    and validity timestamps.
    """
    age = customer_data.get('age', 30)
    occupation = customer_data.get('occupation', 'office_worker')
    health_score = customer_data.get('health_score', 7)
    coverage_amount = customer_data.get('coverage_amount', 500000)
    smoking = customer_data.get('smoking', False)

    base_premium = coverage_amount * BASE_RATE
    factors = {
        'age': age_multiplier(age),
        'health': health_multiplier(health_score),
        'smoking': 1.5 if smoking else 1.0,
        'occupation': occupation_multiplier(occupation),
    }
    annual_premium = base_premium * factors['age'] * factors['health'] * factors['smoking'] * factors['occupation']
    return {
        'annual_premium': round(annual_premium, 2),
        'monthly_premium': round(annual_premium / 12, 2),
        'coverage_amount': coverage_amount,
        'confidence_score': quote_confidence(customer_data),
        'risk_factors': factors,
    }


__all__ = [
    'BASE_RATE', 'OCCUPATION_RISK', 'DEFAULT_OCCUPATION_MULTIPLIER',
    'age_multiplier', 'health_multiplier', 'occupation_multiplier',
    'quote_confidence', 'compute_quote',
]
