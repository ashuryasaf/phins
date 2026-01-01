"""
PHINS Unified Actuarial Tables Module

This module provides a SINGLE SOURCE OF TRUTH for all actuarial calculations
across the PHINS platform. All premium calculations MUST source their actuarial
factors from this module to ensure data integrity and consistency.

Data Source: PHINS_ACTUARIAL_TABLES_V1
Version: 1.0.0
Effective Date: 2025-01-01

Components:
- Mortality rates by age bracket (per 1000 lives per year)
- ADL (Activities of Daily Living) risk multipliers (1-10 scale)
- Lapse rates by policy year
- Investment return assumptions
- Discount rate for present value calculations

Usage:
    from services.actuarial_tables import (
        get_mortality_rate,
        get_adl_multiplier,
        get_lapse_rate,
        calculate_risk_premium,
        ACTUARIAL_SOURCE
    )
"""

from typing import Dict, Tuple, Optional
import math

# ==============================================================================
# ACTUARIAL SOURCE IDENTIFIER
# ==============================================================================
ACTUARIAL_SOURCE = "PHINS_ACTUARIAL_TABLES_V1"
ACTUARIAL_VERSION = "1.0.0"
EFFECTIVE_DATE = "2025-01-01"


# ==============================================================================
# MORTALITY RATES BY AGE BRACKET
# Rates are per 1000 lives per year
# Based on industry standard mortality tables adjusted for insured population
# ==============================================================================
MORTALITY_RATES: Dict[Tuple[int, int], float] = {
    (0, 30): 0.5,    # Young adults - very low mortality
    (30, 40): 1.2,   # Early middle age
    (40, 50): 2.5,   # Middle age
    (50, 60): 5.0,   # Late middle age
    (60, 70): 12.0,  # Early senior
    (70, 80): 30.0,  # Senior
    (80, 100): 75.0, # Advanced age
}


# ==============================================================================
# ADL (ACTIVITIES OF DAILY LIVING) RISK MULTIPLIERS
# Scale 1-10, where 5 is baseline medium risk (multiplier = 1.0)
#
# ADL Levels:
# 1: Fully Independent (Very Low Risk)
# 2: Independent with Supervision (Low Risk)
# 3: Minimal Assistance (Low-Medium Risk)
# 4: Moderate Assistance (Medium Risk)
# 5: Significant Assistance (Medium Risk) - BASELINE
# 6: Extensive Assistance (Medium-High Risk)
# 7: Maximum Assistance (High Risk)
# 8: Total Dependence - Some Areas (High Risk)
# 9: Total Dependence - Most Areas (Very High Risk)
# 10: Complete Dependence (Highest Risk)
# ==============================================================================
ADL_RISK_MULTIPLIERS: Dict[int, float] = {
    1: 0.6,    # Very low risk - fully independent
    2: 0.75,   # Low risk
    3: 0.85,   # Low-medium risk
    4: 0.95,   # Medium risk (below baseline)
    5: 1.0,    # Medium risk - BASELINE
    6: 1.15,   # Medium-high risk
    7: 1.35,   # High risk
    8: 1.6,    # High risk
    9: 1.9,    # Very high risk
    10: 2.5,   # Highest risk - complete dependence
}


# ==============================================================================
# RISK SCORE TO ADL LEVEL MAPPING
# Used when policies have risk_score (low/medium/high/very_high) instead of ADL
# ==============================================================================
RISK_SCORE_TO_ADL: Dict[str, int] = {
    'low': 3,         # Low risk -> ADL 3 (independent with minimal assistance)
    'medium': 5,      # Medium risk -> ADL 5 (baseline)
    'high': 7,        # High risk -> ADL 7 (significant assistance)
    'very_high': 9,   # Very high risk -> ADL 9 (total dependence)
}


# ==============================================================================
# LAPSE RATES BY POLICY YEAR
# Probability of policy lapsing (not renewing) each year
# ==============================================================================
LAPSE_RATES: Dict = {
    1: 0.08,           # 8% lapse in year 1 (highest)
    2: 0.05,           # 5% lapse in year 2
    3: 0.04,           # 4% lapse in year 3
    (4, 10): 0.03,     # 3% lapse years 4-10
    (11, 25): 0.02,    # 2% lapse years 11-25
    (26, 100): 0.01,   # 1% lapse years 26+ (most loyal)
}


# ==============================================================================
# AGE ADJUSTMENT FACTORS BY POLICY TYPE
# Derived from mortality tables for premium calculation
# ==============================================================================
AGE_FACTORS: Dict[str, Dict[Tuple[int, int], float]] = {
    'life': {
        (0, 30): 0.7,
        (30, 40): 0.85,
        (40, 45): 1.0,
        (45, 50): 1.15,
        (50, 55): 1.30,
        (55, 60): 1.60,
        (60, 65): 2.0,
        (65, 70): 2.5,
        (70, 100): 3.2
    },
    'health': {
        (0, 30): 0.6,
        (30, 40): 0.8,
        (40, 50): 1.0,
        (50, 60): 1.4,
        (60, 70): 1.9,
        (70, 100): 2.6
    },
    'auto': {
        (0, 25): 1.3,    # Young drivers higher risk
        (25, 65): 1.0,
        (65, 100): 1.2
    },
    'property': {
        (0, 100): 1.0    # Property doesn't depend on age
    },
    'business': {
        (0, 100): 1.0    # Business doesn't depend on age
    }
}


# ==============================================================================
# INVESTMENT RETURN ASSUMPTIONS (Annual)
# ==============================================================================
INVESTMENT_RETURNS: Dict[str, float] = {
    'conservative': 0.04,   # 4% annual
    'moderate': 0.06,       # 6% annual (default)
    'aggressive': 0.08,     # 8% annual
}


# ==============================================================================
# DISCOUNT RATE FOR PRESENT VALUE CALCULATIONS
# ==============================================================================
DISCOUNT_RATE: float = 0.035  # 3.5% annual


# ==============================================================================
# EXPENSE LOADING (% of risk premium added for administrative costs)
# ==============================================================================
EXPENSE_LOADING_PCT: float = 0.15  # 15% of risk premium


# ==============================================================================
# BASE PREMIUM BY POLICY TYPE (per $100,000 coverage, age 45 baseline)
# ==============================================================================
BASE_PREMIUM_RATES: Dict[str, float] = {
    'life': 1200,
    'health': 800,
    'auto': 600,
    'property': 1500,
    'business': 3000
}


# ==============================================================================
# HELPER FUNCTIONS
# ==============================================================================

def get_mortality_rate(age: int) -> float:
    """
    Get mortality rate per 1000 lives for given age.
    Returns rate as decimal (e.g., 0.0025 for 2.5 per 1000).
    
    Args:
        age: Customer age in years
        
    Returns:
        Mortality rate as decimal
    """
    for (low, high), rate in MORTALITY_RATES.items():
        if low <= age < high:
            return rate / 1000.0
    return 0.075  # Default for very old ages (75 per 1000)


def get_adl_multiplier(adl_level: int) -> float:
    """
    Get risk multiplier based on ADL level (1-10).
    
    Args:
        adl_level: ADL level from 1 (independent) to 10 (complete dependence)
        
    Returns:
        Risk multiplier (1.0 = baseline medium risk)
    """
    adl_level = max(1, min(10, adl_level))  # Clamp to 1-10
    return ADL_RISK_MULTIPLIERS.get(adl_level, 1.0)


def get_adl_from_risk_score(risk_score: str) -> int:
    """
    Convert risk_score string to ADL level.
    
    Args:
        risk_score: One of 'low', 'medium', 'high', 'very_high'
        
    Returns:
        ADL level (1-10)
    """
    return RISK_SCORE_TO_ADL.get(risk_score.lower() if risk_score else 'medium', 5)


def get_lapse_rate(policy_year: int) -> float:
    """
    Get lapse rate for given policy year.
    
    Args:
        policy_year: Year of policy (1 = first year)
        
    Returns:
        Lapse rate as decimal (e.g., 0.08 for 8%)
    """
    if policy_year in LAPSE_RATES:
        return LAPSE_RATES[policy_year]
    for key, rate in LAPSE_RATES.items():
        if isinstance(key, tuple) and key[0] <= policy_year <= key[1]:
            return rate
    return 0.01


def get_age_factor(age: int, policy_type: str = 'life') -> float:
    """
    Get age adjustment factor for premium calculation.
    
    Args:
        age: Customer age in years
        policy_type: Type of policy (life, health, auto, property, business)
        
    Returns:
        Age factor multiplier (1.0 = baseline at age 40-45)
    """
    factors = AGE_FACTORS.get(policy_type, AGE_FACTORS['life'])
    for (min_age, max_age), factor in factors.items():
        if min_age <= age < max_age:
            return factor
    return 1.0


def get_adl_description(adl_level: int) -> str:
    """
    Get human-readable description for ADL level.
    
    Args:
        adl_level: ADL level from 1 to 10
        
    Returns:
        Human-readable description
    """
    descriptions = {
        1: 'Fully Independent (Very Low Risk)',
        2: 'Independent with Supervision (Low Risk)',
        3: 'Minimal Assistance (Low-Medium Risk)',
        4: 'Moderate Assistance (Medium Risk)',
        5: 'Significant Assistance (Medium Risk)',
        6: 'Extensive Assistance (Medium-High Risk)',
        7: 'Maximum Assistance (High Risk)',
        8: 'Total Dependence - Some Areas (High Risk)',
        9: 'Total Dependence - Most Areas (Very High Risk)',
        10: 'Complete Dependence (Highest Risk)'
    }
    return descriptions.get(adl_level, 'Unknown')


def calculate_risk_premium(
    coverage: float,
    age: int,
    adl_level: int,
    term_years: int = 25
) -> Dict[str, float]:
    """
    Calculate actuarially-sound risk premium component.
    
    This function calculates the present value of expected mortality costs
    adjusted for ADL risk and lapse rates.
    
    Args:
        coverage: Coverage amount in dollars
        age: Customer age in years
        adl_level: ADL level (1-10)
        term_years: Policy term in years
        
    Returns:
        Dictionary with mortality_cost, annual_risk_premium, and actuarial details
    """
    # Calculate present value of expected mortality costs
    mortality_cost = 0.0
    
    for year in range(1, term_years + 1):
        current_age = age + year - 1
        qx = get_mortality_rate(current_age)
        adl_mult = get_adl_multiplier(adl_level)
        adjusted_qx = qx * adl_mult
        
        # Probability of surviving to year, then dying
        px_prev = 1.0
        for y in range(year - 1):
            prev_qx = get_mortality_rate(age + y) * get_adl_multiplier(adl_level)
            px_prev *= (1 - prev_qx)
        
        death_prob = px_prev * adjusted_qx
        
        # Lapse-adjusted probability
        lapse_survival = 1.0
        for y in range(year):
            lapse_survival *= (1 - get_lapse_rate(y + 1))
        
        adjusted_death_prob = death_prob * lapse_survival
        
        # Discount death benefit to present value
        discount_factor = (1 + DISCOUNT_RATE) ** (-year)
        mortality_cost += coverage * adjusted_death_prob * discount_factor
    
    # Annual risk premium (spread cost over term)
    annual_risk_premium = mortality_cost / term_years
    
    return {
        'mortality_cost_pv': round(mortality_cost, 2),
        'annual_risk_premium': round(annual_risk_premium, 2),
        'monthly_risk_premium': round(annual_risk_premium / 12, 2),
        'age': age,
        'adl_level': adl_level,
        'adl_multiplier': get_adl_multiplier(adl_level),
        'term_years': term_years,
        'discount_rate': DISCOUNT_RATE,
        'actuarial_source': ACTUARIAL_SOURCE
    }


def calculate_full_premium(
    coverage: float,
    age: int,
    adl_level: int = 5,
    savings_pct: float = 0.50,
    term_years: int = 25,
    policy_type: str = 'life'
) -> Dict[str, float]:
    """
    Calculate complete premium with risk, savings, and expense components.
    
    This is the PRIMARY premium calculation function that should be used
    across the platform for consistent actuarial basis.
    
    Args:
        coverage: Coverage amount in dollars
        age: Customer age in years
        adl_level: ADL level (1-10), default 5 (medium)
        savings_pct: Portion of coverage for savings target (0.0-1.0)
        term_years: Policy term in years
        policy_type: Type of policy (life, health, auto, property, business)
        
    Returns:
        Dictionary with complete premium breakdown and actuarial details
    """
    # Calculate risk premium component using full actuarial method
    risk_calc = calculate_risk_premium(coverage, age, adl_level, term_years)
    risk_premium_annual = risk_calc['annual_risk_premium']
    
    # Savings component (target accumulation spread over term)
    savings_allocation = coverage * savings_pct
    savings_premium_annual = savings_allocation / term_years
    
    # Expense loading (15% of risk premium)
    expense_loading = risk_premium_annual * EXPENSE_LOADING_PCT
    
    # Total annual premium
    total_annual = risk_premium_annual + savings_premium_annual + expense_loading
    
    return {
        'annual_premium': round(total_annual, 2),
        'monthly_premium': round(total_annual / 12, 2),
        'quarterly_premium': round(total_annual / 4, 2),
        'risk_component': round(risk_premium_annual, 2),
        'savings_component': round(savings_premium_annual, 2),
        'expense_loading': round(expense_loading, 2),
        'coverage': coverage,
        'savings_target': round(savings_allocation, 2),
        'term_years': term_years,
        'policy_type': policy_type,
        'age': age,
        'age_factor': get_age_factor(age, policy_type),
        'adl_level': adl_level,
        'adl_multiplier': get_adl_multiplier(adl_level),
        'adl_description': get_adl_description(adl_level),
        'mortality_rate': get_mortality_rate(age),
        'discount_rate': DISCOUNT_RATE,
        'expense_loading_pct': EXPENSE_LOADING_PCT,
        'actuarial_source': ACTUARIAL_SOURCE,
        'actuarial_version': ACTUARIAL_VERSION
    }


def calculate_premium_from_risk_score(
    coverage: float,
    age: int,
    risk_score: str,
    savings_pct: float = 0.50,
    term_years: int = 25,
    policy_type: str = 'life'
) -> Dict[str, float]:
    """
    Calculate premium using risk_score instead of ADL level.
    
    This is a convenience function for when the system has risk_score
    (low/medium/high/very_high) instead of explicit ADL level.
    
    Args:
        coverage: Coverage amount in dollars
        age: Customer age in years
        risk_score: Risk assessment (low, medium, high, very_high)
        savings_pct: Portion of coverage for savings target
        term_years: Policy term in years
        policy_type: Type of policy
        
    Returns:
        Dictionary with complete premium breakdown
    """
    adl_level = get_adl_from_risk_score(risk_score)
    result = calculate_full_premium(
        coverage=coverage,
        age=age,
        adl_level=adl_level,
        savings_pct=savings_pct,
        term_years=term_years,
        policy_type=policy_type
    )
    result['risk_score'] = risk_score
    result['risk_score_to_adl'] = adl_level
    return result


# ==============================================================================
# MODULE EXPORTS
# ==============================================================================

__all__ = [
    # Constants
    'ACTUARIAL_SOURCE',
    'ACTUARIAL_VERSION',
    'EFFECTIVE_DATE',
    'MORTALITY_RATES',
    'ADL_RISK_MULTIPLIERS',
    'RISK_SCORE_TO_ADL',
    'LAPSE_RATES',
    'AGE_FACTORS',
    'INVESTMENT_RETURNS',
    'DISCOUNT_RATE',
    'EXPENSE_LOADING_PCT',
    'BASE_PREMIUM_RATES',
    # Functions
    'get_mortality_rate',
    'get_adl_multiplier',
    'get_adl_from_risk_score',
    'get_lapse_rate',
    'get_age_factor',
    'get_adl_description',
    'calculate_risk_premium',
    'calculate_full_premium',
    'calculate_premium_from_risk_score',
]
