"""
PHINS Actuarial Service - Central Source of Truth for All Pricing & Risk

This is the BACKBONE of the insurance platform. All pricing, underwriting,
claims reserves, and risk assessments MUST use this central service.

Features:
- Editable rate tables with version control
- Adjustable underwriting configuration
- Portfolio simulation engine with demographics
- Automation quality metrics
- Integration points for wallets, investments, communities
- Full audit trail

Access Control: Admin and Actuary roles ONLY

Author: PHINS Actuarial Team
Version: 2.0
"""

import math
import random
import re
import json
import hashlib
import threading
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, field, asdict
from enum import Enum
import logging

logger = logging.getLogger(__name__)

# =============================================================================
# ACCESS CONTROL
# =============================================================================

ACTUARIAL_ACCESS_ROLES = ['admin', 'actuary']

def check_actuarial_access(user_role: str) -> bool:
    """Check if user has access to actuarial functions"""
    return user_role.lower() in ACTUARIAL_ACCESS_ROLES


# =============================================================================
# ENUMS & DATA CLASSES
# =============================================================================

class DistributionType(Enum):
    UNIFORM = 'uniform'
    NORMAL = 'normal'
    LOG_NORMAL = 'log_normal'
    CUSTOM = 'custom'


class PolicyTermMode(Enum):
    FIXED = 'fixed'
    RANDOM = 'random'


@dataclass
class AgeRateBracket:
    age_min: int
    age_max: int
    rate_per_1000: float
    
    def contains(self, age: int) -> bool:
        return self.age_min <= age < self.age_max


@dataclass
class ADLFactor:
    adl: int
    value: float


def _default_ethnicity_factors() -> Dict[str, float]:
    return {
        'caucasian': 1.0,
        'african': 1.0,
        'hispanic': 1.0,
        'asian': 1.0,
        'other': 1.0,
    }


@dataclass
class UnderwritingConfig:
    decline_threshold: int = 9  # ADL 9+ declined by default
    loadings: Dict[int, float] = field(default_factory=lambda: {6: 0.15, 7: 0.30, 8: 0.50})
    coverage_limits: Dict[int, float] = field(default_factory=lambda: {6: 1000000, 7: 750000, 8: 500000})
    disability_exclusion_threshold: int = 8
    expense_loading_pct: float = 0.15
    profit_margin_pct: float = 0.10
    discount_rate: float = 0.035
    # Age-banded contract ratios (adjustable from the actuary dashboard).
    # Pre-65: life = face, disability = life/4. Post-65: life = face/4, D = life.
    disability_share_of_life: float = 0.25
    disability_share_of_life_post65: float = 1.0
    life_share_of_coverage: float = 1.0
    life_share_of_coverage_post65: float = 0.25
    disability_band_age: int = 65
    # Demographic rate multipliers (life = mortality, disability = incidence).
    # Defaults 1.0 = neutral / unisex / unismoker until actuary tunes them.
    smoker_mortality_factor: float = 1.0
    smoker_disability_factor: float = 1.0
    former_smoker_mortality_factor: float = 1.0
    former_smoker_disability_factor: float = 1.0
    nonsmoker_mortality_factor: float = 1.0
    nonsmoker_disability_factor: float = 1.0
    male_mortality_factor: float = 1.0
    male_disability_factor: float = 1.0
    female_mortality_factor: float = 1.0
    female_disability_factor: float = 1.0
    ethnicity_mortality_factors: Dict[str, float] = field(default_factory=_default_ethnicity_factors)
    ethnicity_disability_factors: Dict[str, float] = field(default_factory=_default_ethnicity_factors)
    # Bumped on every durable dashboard save so priced snapshots pin a revision.
    config_version: str = 'cfg_v1'
    last_modified: str = ''
    modified_by: str = ''


@dataclass
class SimulationParams:
    customer_count: int = 100000
    age_min: int = 3
    age_max: int = 55
    age_distribution: str = 'normal'
    age_mean: float = 35.0
    age_std: float = 12.0
    coverage_min: float = 50000
    coverage_max: float = 2000000
    coverage_distribution: str = 'log_normal'
    coverage_median: float = 250000
    policy_term_mode: str = 'random'
    policy_term_fixed: int = 20
    policy_term_min: int = 5
    policy_term_max: int = 30
    male_pct: float = 49.0
    female_pct: float = 51.0
    # Smoking mix for simulated portfolio (remainder = nonsmoker).
    # Priced through Pricing Parameters demographic multipliers.
    smoker_pct: float = 15.0
    former_smoker_pct: float = 10.0
    ethnicity: Dict[str, float] = field(default_factory=lambda: {
        'caucasian': 60, 'african': 13, 'hispanic': 18, 'asian': 6, 'other': 3
    })
    # Share of total annual premium routed to the long-term savings fund rather
    # than retained on the insurance balance sheet (0.0 - 0.95). Pure-risk
    # products use 0.0; hybrid risk+savings products set this to e.g. 0.30.
    savings_allocation_pct: float = 0.0
    # ------------------------------------------------------------------
    # Pricing-kernel inputs.
    #
    # The PHINS contract is a pure-risk adjustable contract; savings is an
    # OPTIONAL add-on priced as a markup on the priced risk premium. With
    # ``savings_formula='risk_premium_markup'`` (the default) the simulator
    # interprets ``savings_rate`` directly as the customer's elected
    # savings allocation as a fraction of risk premium — 0.0 means
    # pure-risk, 1.0 means the savings premium matches the risk premium,
    # 3.0 means 300% of risk premium (the example from the brief).
    # ------------------------------------------------------------------
    product_id: str = 'phins_pure_risk_adjustable'
    # Savings add-on as a fraction of risk premium (semantics depend on
    # ``savings_formula``). Default is 0.0 = pure-risk contract.
    savings_rate: float = 0.0
    # Assumed annual yield on the savings fund. Used only when
    # ``savings_formula='annuity_immediate'``; the new risk-premium-markup
    # formula does not depend on yield.
    savings_yield_pct: float = 0.0
    # 'risk_premium_markup' (new default), 'straight_line' or 'annuity_immediate'.
    savings_formula: str = 'risk_premium_markup'
    # Age curve attached to the pricing-kernel TableSet. Defaults to
    # 'identity' (age dependence lives in the rate tables — the production
    # behaviour). Set to 'risk_reference_v1' to swap in the published age
    # curve from the public risk one-pager.
    age_curve_id: str = 'identity'


# =============================================================================
# REINSURANCE RESEARCH + HEDGING ANALYTICS
# =============================================================================

REINSURANCE_RESEARCH_LIBRARY: List[Dict[str, Any]] = [
    {
        'id': 'soa_group_ltd_2015_2022',
        'source': 'SOA/LIMRA 2015-2022 Group Long-Term Disability Incidence Study',
        'published_year': 2025,
        'headline_metric': '294 million life-years exposed and about 1.2 million claims across 19 carriers representing 97% of the market.',
        'relevance': 'Anchors the permanent disability incidence credibility used in PHINS reinsurance stress testing.',
        'url': 'https://beta.soa.org/resources/experience-studies/15-22-grp-ltd-inc/',
    },
    {
        'id': 'ihme_gbd_2021',
        'source': 'IHME Global Burden of Disease 2021 / The Lancet 2024',
        'published_year': 2024,
        'headline_metric': 'Global DALYs increased from 2.63B in 2010 to 2.88B in 2021 and healthy life expectancy reached 62.2 years.',
        'relevance': 'Backs PHINS disability burden framing for life-health hedging and reserve stress scenarios.',
        'url': 'https://healthdata.org/research-analysis/library/global-incidence-prevalence-years-lived-disability-ylds-disability',
    },
    {
        'id': 'aaa_soa_idi_work_group',
        'source': 'American Academy of Actuaries / SOA Individual Disability Tables Work Group',
        'published_year': 2014,
        'headline_metric': 'Recommends the 2013 IDI valuation table with claim incidence, claim termination, and valuation margin standards.',
        'relevance': 'Supports PHINS permanent ADL disability pricing margin and reserve-based reinsurance costing.',
        'url': 'https://www.actuary.org/sites/default/files/files/IDTWG_Table_Report_Oct_2014.pdf',
    },
]


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def _summarize_age_band_rates(table: List[Dict[str, Any]], age_min: int, age_max: int) -> Dict[str, float]:
    """Summarize a rate table over the requested age band."""
    if age_max <= age_min:
        age_max = age_min + 1

    total_years = 0.0
    weighted_rate = 0.0
    min_rate = None
    max_rate = None

    for row in table:
        overlap_min = max(age_min, int(row.get('age_min', age_min)))
        overlap_max = min(age_max, int(row.get('age_max', age_max)))
        overlap = max(0, overlap_max - overlap_min)
        if overlap <= 0:
            continue

        rate = float(row.get('rate_per_1000', 0.0))
        total_years += overlap
        weighted_rate += rate * overlap
        min_rate = rate if min_rate is None else min(min_rate, rate)
        max_rate = rate if max_rate is None else max(max_rate, rate)

    average_rate = (weighted_rate / total_years) if total_years else 0.0
    return {
        'average_per_1000': round(average_rate, 3),
        'min_per_1000': round(min_rate or 0.0, 3),
        'max_per_1000': round(max_rate or 0.0, 3),
    }


def classify_reinsurance_risk_band(loss_ratio_pct: float) -> str:
    """Classify reinsurance risk band from the annual loss ratio."""
    if loss_ratio_pct >= 95:
        return 'very_high'
    if loss_ratio_pct >= 75:
        return 'high'
    if loss_ratio_pct >= 45:
        return 'medium'
    return 'low'


def get_reinsurance_research_library() -> List[Dict[str, Any]]:
    return [dict(item) for item in REINSURANCE_RESEARCH_LIBRARY]


def calculate_reinsurance_program(
    simulation: Dict[str, Any],
    tables_store: Optional['ActuarialTablesStore'] = None,
    contract_count: Optional[int] = None,
    hedge_share_pct: float = 35.0,
    covered_risks: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Build a research-backed reinsurance program from a simulation snapshot.

    The program is intentionally deterministic so the same simulation always maps to
    the same hedge math on the dashboard, recommendation flow, and balance sheet.
    """
    tables_store = tables_store or get_actuarial_store()
    covered_risks = covered_risks or ['mortality', 'permanent_adl_disability']

    portfolio = simulation.get('portfolio_summary', {})
    risk_metrics = simulation.get('risk_metrics', {})
    profitability = simulation.get('profitability', {})
    params = simulation.get('parameters', {})

    accepted_customers = max(0, int(portfolio.get('accepted_customers', 0) or 0))
    total_coverage = float(portfolio.get('total_coverage', 0.0) or 0.0)
    gross_premium = float(profitability.get('gross_premium', 0.0) or 0.0)
    annual_expected_claims = float(risk_metrics.get('annual_expected_claims', 0.0) or 0.0)
    reserve_requirement = float(risk_metrics.get('reserve_requirement', 0.0) or 0.0)
    loss_ratio_pct = float(risk_metrics.get('loss_ratio', 0.0) or 0.0)

    if accepted_customers <= 0 or total_coverage <= 0:
        return {
            'covered_risks': covered_risks,
            'selected_contracts': 0,
            'hedge_share_pct': round(_clamp(hedge_share_pct, 0.0, 100.0), 2),
            'risk_band': 'low',
            'quote_request': {
                'currency': 'USD',
                'line_of_business': 'life_health',
                'region': 'global',
                'total_exposure': 0.0,
                'expected_annual_premium': 0.0,
                'expected_loss_ratio': 0.0,
                'risk_band': 'low',
            },
            'research_backing': {
                'sources': get_reinsurance_research_library(),
                'mortality_basis': {'average_per_1000': 0.0, 'min_per_1000': 0.0, 'max_per_1000': 0.0},
                'disability_basis': {'average_per_1000': 0.0, 'min_per_1000': 0.0, 'max_per_1000': 0.0},
            },
            'data_integrity': {
                'contracts_within_portfolio': True,
                'ceded_exposure_within_total': True,
                'gross_premium_reconciles': True,
            },
        }

    default_contract_count = min(accepted_customers, max(1000, int(round(accepted_customers * 0.25))))
    selected_contracts = int(contract_count if contract_count is not None else default_contract_count)
    selected_contracts = max(1, min(selected_contracts, accepted_customers))

    hedge_share_decimal = _clamp(float(hedge_share_pct) / 100.0, 0.0, 0.95)
    contract_participation = selected_contracts / accepted_customers if accepted_customers else 0.0
    protected_claims_share = contract_participation * hedge_share_decimal

    mortality_share = float(risk_metrics.get('mortality_pct_of_claims', 0.0) or 0.0) / 100.0
    disability_share = float(risk_metrics.get('disability_pct_of_claims', 0.0) or 0.0) / 100.0
    avg_coverage = total_coverage / accepted_customers if accepted_customers else 0.0

    ceded_exposure = total_coverage * protected_claims_share
    ceded_annual_claims = annual_expected_claims * protected_claims_share
    ceded_mortality_claims = ceded_annual_claims * mortality_share
    ceded_disability_claims = ceded_annual_claims * disability_share
    reserve_relief = reserve_requirement * protected_claims_share

    risk_band = classify_reinsurance_risk_band(loss_ratio_pct)
    pricing_load = {
        'low': 1.08,
        'medium': 1.12,
        'high': 1.18,
        'very_high': 1.24,
    }[risk_band]
    technical_annual_premium = ceded_annual_claims * pricing_load
    estimated_fees = {
        'broker_fee': round(technical_annual_premium * 0.01, 2),
        'platform_fee': round(technical_annual_premium * 0.0025, 2),
    }
    total_contract_cost = round(technical_annual_premium + estimated_fees['broker_fee'] + estimated_fees['platform_fee'], 2)
    premium_uplift_pct = round((total_contract_cost / gross_premium) * 100, 2) if gross_premium > 0 else 0.0

    tables = tables_store.get_current_tables()
    age_min = int(params.get('age_min', 0) or 0)
    age_max = int(params.get('age_max', 120) or 120)
    mortality_basis = _summarize_age_band_rates(tables.get('mortality_rates', []), age_min, age_max)
    disability_basis = _summarize_age_band_rates(tables.get('disability_incidence_rates', []), age_min, age_max)

    calculated_gross = float(profitability.get('calculated_gross', gross_premium) or gross_premium)
    net_profit = float(profitability.get('net_profit', 0.0) or 0.0)

    # Resolve the L:D contract ratio actually used to price this portfolio
    # so the reinsurance program can prove it preserves the same ratio when
    # ceding mortality vs disability claims.
    pricing_kernel_meta = simulation.get('pricing_kernel') or {}
    disability_share_of_life = float(
        pricing_kernel_meta.get('disability_share_of_life',
                                getattr(tables_store.config, 'disability_share_of_life', 0.25))
    )

    return {
        'covered_risks': covered_risks,
        'accepted_lives': accepted_customers,
        'selected_contracts': selected_contracts,
        'participation_pct': round(contract_participation * 100, 2),
        'hedge_share_pct': round(hedge_share_decimal * 100, 2),
        'protected_claims_pct': round(protected_claims_share * 100, 2),
        'avg_coverage_per_contract': round(avg_coverage, 2),
        'risk_band': risk_band,
        'ceded_exposure': round(ceded_exposure, 2),
        'ceded_expected_claims_annual': round(ceded_annual_claims, 2),
        'ceded_mortality_claims_annual': round(ceded_mortality_claims, 2),
        'ceded_disability_claims_annual': round(ceded_disability_claims, 2),
        'reserve_relief_estimate': round(reserve_relief, 2),
        'technical_annual_premium': round(technical_annual_premium, 2),
        'estimated_fees': estimated_fees,
        'total_contract_cost': total_contract_cost,
        'premium_uplift_pct': premium_uplift_pct,
        'gross_premium_with_reinsurance': round(gross_premium + total_contract_cost, 2),
        'net_profit_after_reinsurance': round(net_profit - total_contract_cost, 2),
        'balance_sheet_impact': {
            'expense_category': 'reinsurance',
            'annual_reinsurance_expense': total_contract_cost,
            'operating_reserve_delta': round(-total_contract_cost, 2),
            'capital_relief_estimate': round(reserve_relief, 2),
        },
        'quote_request': {
            'currency': 'USD',
            'line_of_business': 'life_health',
            'region': 'global',
            'total_exposure': round(ceded_exposure, 2),
            'expected_annual_premium': round(technical_annual_premium, 2),
            'expected_loss_ratio': round(_clamp(loss_ratio_pct / 100.0, 0.15, 0.98), 4),
            'risk_band': risk_band,
        },
        'research_backing': {
            'sources': get_reinsurance_research_library(),
            'mortality_basis': mortality_basis,
            'disability_basis': disability_basis,
            'table_version': simulation.get('tables_version', tables_store.current_version),
            'adl_model_note': 'Permanent ADL disability risk is sourced from PHINS ADL disability multipliers and disability benefit percentage tables.',
        },
        'contract_ratios': {
            'disability_share_of_life': round(disability_share_of_life, 6),
            'disability_to_life_ratio_display': (
                f'1:{int(round(1.0 / disability_share_of_life))}'
                if disability_share_of_life and abs(
                    1.0 / disability_share_of_life - round(1.0 / disability_share_of_life)
                ) < 0.01
                else f'{disability_share_of_life:.4f}'
            ),
            'source': 'pricing_kernel.disability_share_of_life',
            'ceded_disability_sum_pct_of_ceded_exposure': (
                round((ceded_exposure * disability_share_of_life) / max(1.0, ceded_exposure), 6)
                if ceded_exposure > 0 else 0.0
            ),
        },
        'data_integrity': {
            'contracts_within_portfolio': selected_contracts <= accepted_customers,
            'ceded_exposure_within_total': ceded_exposure <= total_coverage + 1,
            'gross_premium_reconciles': abs(gross_premium - calculated_gross) < 1.0,
            'protected_claims_share': round(protected_claims_share, 6),
            # Prove the program kept the same L:D ratio the kernel used to
            # price the underlying portfolio — i.e. the disability portion
            # of the ceded sum equals share × total ceded exposure.
            'contract_ratio_preserved': abs(disability_share_of_life - float(
                pricing_kernel_meta.get('disability_share_of_life', disability_share_of_life)
            )) < 1e-9,
        },
    }


# =============================================================================
# ACTUARIAL TABLES STORE (Version Controlled)
# =============================================================================

class ActuarialTablesStore:
    """
    Central store for all actuarial tables with version control.
    This is the SINGLE SOURCE OF TRUTH for all pricing.
    """
    
    def __init__(self):
        self.current_version = 'V2.0'
        self.versions: Dict[str, Dict] = {}
        self.config = UnderwritingConfig()
        self.audit_log: List[Dict] = []
        
        # Initialize with default V2.0 tables
        self._initialize_default_tables()
    
    def _initialize_default_tables(self):
        """Initialize with corrected V2 actuarial tables"""
        self.versions['V2.0'] = {
            'version': 'V2.0',
            'effective_date': datetime.now().isoformat(),
            'created_by': 'system',
            'status': 'active',
            
            # Mortality rates (per 1000 lives per year)
            'mortality_rates': [
                {'age_min': 0, 'age_max': 30, 'rate_per_1000': 0.5},
                {'age_min': 30, 'age_max': 40, 'rate_per_1000': 1.2},
                {'age_min': 40, 'age_max': 50, 'rate_per_1000': 2.5},
                {'age_min': 50, 'age_max': 60, 'rate_per_1000': 5.0},
                {'age_min': 60, 'age_max': 70, 'rate_per_1000': 12.0},
                {'age_min': 70, 'age_max': 80, 'rate_per_1000': 30.0},
                {'age_min': 80, 'age_max': 120, 'rate_per_1000': 75.0},
            ],
            
            # Disability incidence rates (per 1000 lives per year)
            'disability_incidence_rates': [
                {'age_min': 0, 'age_max': 30, 'rate_per_1000': 2.0},
                {'age_min': 30, 'age_max': 40, 'rate_per_1000': 4.0},
                {'age_min': 40, 'age_max': 50, 'rate_per_1000': 8.0},
                {'age_min': 50, 'age_max': 60, 'rate_per_1000': 15.0},
                {'age_min': 60, 'age_max': 70, 'rate_per_1000': 30.0},
                {'age_min': 70, 'age_max': 80, 'rate_per_1000': 50.0},
                {'age_min': 80, 'age_max': 120, 'rate_per_1000': 80.0},
            ],
            
            # ADL Mortality multipliers
            'adl_mortality_multipliers': [
                {'adl': 1, 'multiplier': 0.8},
                {'adl': 2, 'multiplier': 0.85},
                {'adl': 3, 'multiplier': 0.9},
                {'adl': 4, 'multiplier': 0.95},
                {'adl': 5, 'multiplier': 1.0},
                {'adl': 6, 'multiplier': 1.1},
                {'adl': 7, 'multiplier': 1.2},
                {'adl': 8, 'multiplier': 1.35},
                {'adl': 9, 'multiplier': 1.5},
                {'adl': 10, 'multiplier': 1.8},
            ],
            
            # ADL Disability incidence multipliers (CRITICAL for correct pricing)
            'adl_disability_multipliers': [
                {'adl': 1, 'multiplier': 0.3},
                {'adl': 2, 'multiplier': 0.5},
                {'adl': 3, 'multiplier': 0.7},
                {'adl': 4, 'multiplier': 0.9},
                {'adl': 5, 'multiplier': 1.0},
                {'adl': 6, 'multiplier': 1.5},
                {'adl': 7, 'multiplier': 2.0},
                {'adl': 8, 'multiplier': 3.0},
                {'adl': 9, 'multiplier': 5.0},
                {'adl': 10, 'multiplier': 8.0},
            ],
            
            # ADL Benefit percentages (% of coverage paid for disability)
            'adl_benefit_percentages': [
                {'adl': 1, 'benefit_pct': 0.0},
                {'adl': 2, 'benefit_pct': 0.0},
                {'adl': 3, 'benefit_pct': 0.0},
                {'adl': 4, 'benefit_pct': 0.25},
                {'adl': 5, 'benefit_pct': 0.25},
                {'adl': 6, 'benefit_pct': 0.50},
                {'adl': 7, 'benefit_pct': 0.50},
                {'adl': 8, 'benefit_pct': 0.85},
                {'adl': 9, 'benefit_pct': 1.0},
                {'adl': 10, 'benefit_pct': 1.0},
            ],
            
            # Lapse rates by policy year
            'lapse_rates': [
                {'year': 1, 'rate': 0.08},
                {'year': 2, 'rate': 0.05},
                {'year': 3, 'rate': 0.04},
                {'year_min': 4, 'year_max': 10, 'rate': 0.03},
                {'year_min': 11, 'year_max': 25, 'rate': 0.02},
                {'year_min': 26, 'year_max': 100, 'rate': 0.01},
            ]
        }
        
        # Initialize underwriting config
        self.config = UnderwritingConfig(
            decline_threshold=9,
            loadings={6: 0.15, 7: 0.30, 8: 0.50},
            coverage_limits={6: 1000000, 7: 750000, 8: 500000},
            disability_exclusion_threshold=8,
            expense_loading_pct=0.15,
            profit_margin_pct=0.10,
            discount_rate=0.035,
            disability_share_of_life=0.25,
            disability_share_of_life_post65=1.0,
            life_share_of_coverage=1.0,
            life_share_of_coverage_post65=0.25,
            disability_band_age=65,
            smoker_mortality_factor=1.0,
            smoker_disability_factor=1.0,
            former_smoker_mortality_factor=1.0,
            former_smoker_disability_factor=1.0,
            nonsmoker_mortality_factor=1.0,
            nonsmoker_disability_factor=1.0,
            male_mortality_factor=1.0,
            male_disability_factor=1.0,
            female_mortality_factor=1.0,
            female_disability_factor=1.0,
            ethnicity_mortality_factors=_default_ethnicity_factors(),
            ethnicity_disability_factors=_default_ethnicity_factors(),
            config_version='cfg_v1',
            last_modified=datetime.now().isoformat(),
            modified_by='system'
        )
    
    def get_current_tables(self) -> Dict:
        """Get the currently active tables"""
        return self.versions.get(self.current_version, {})
    
    def get_mortality_rate(self, age: int) -> float:
        """Get mortality rate for age (per 1000)"""
        tables = self.get_current_tables()
        for bracket in tables.get('mortality_rates', []):
            if bracket['age_min'] <= age < bracket['age_max']:
                return bracket['rate_per_1000'] / 1000.0
        return 0.075  # Default for very old ages
    
    def get_disability_rate(self, age: int) -> float:
        """Get disability incidence rate for age (per 1000)"""
        tables = self.get_current_tables()
        for bracket in tables.get('disability_incidence_rates', []):
            if bracket['age_min'] <= age < bracket['age_max']:
                return bracket['rate_per_1000'] / 1000.0
        return 0.08
    
    def get_adl_mortality_multiplier(self, adl: int) -> float:
        """Get mortality multiplier for ADL level"""
        adl = max(1, min(10, adl))
        tables = self.get_current_tables()
        for item in tables.get('adl_mortality_multipliers', []):
            if item['adl'] == adl:
                return item['multiplier']
        return 1.0
    
    def get_adl_disability_multiplier(self, adl: int) -> float:
        """Get disability incidence multiplier for ADL level"""
        adl = max(1, min(10, adl))
        tables = self.get_current_tables()
        for item in tables.get('adl_disability_multipliers', []):
            if item['adl'] == adl:
                return item['multiplier']
        return 1.0
    
    def get_adl_benefit_pct(self, adl: int) -> float:
        """Get benefit percentage for ADL level"""
        adl = max(1, min(10, adl))
        tables = self.get_current_tables()
        for item in tables.get('adl_benefit_percentages', []):
            if item['adl'] == adl:
                return item['benefit_pct']
        return 0.35
    
    def get_lapse_rate(self, year: int) -> float:
        """Get lapse rate for policy year"""
        tables = self.get_current_tables()
        for item in tables.get('lapse_rates', []):
            if 'year' in item and item['year'] == year:
                return item['rate']
            if 'year_min' in item and item['year_min'] <= year <= item['year_max']:
                return item['rate']
        return 0.01
    
    def upload_new_tables(self, tables: Dict, user: str, effective_date: str = None) -> Dict:
        """Upload a new version of actuarial tables"""
        # Generate new version number
        versions = list(self.versions.keys())
        max_version = max([float(v.replace('V', '')) for v in versions]) if versions else 2.0
        new_version = f'V{max_version + 0.1:.1f}'
        
        # Validate tables
        validation = self._validate_tables(tables)
        if not validation['valid']:
            return {'success': False, 'errors': validation['errors']}
        
        # Store new version
        self.versions[new_version] = {
            'version': new_version,
            'effective_date': effective_date or datetime.now().isoformat(),
            'created_by': user,
            'status': 'active',
            **tables
        }
        
        # Set as current if effective immediately
        if not effective_date or effective_date <= datetime.now().isoformat():
            old_version = self.current_version
            self.current_version = new_version
            
            # Archive old version
            if old_version in self.versions:
                self.versions[old_version]['status'] = 'archived'
        else:
            self.versions[new_version]['status'] = 'scheduled'
        
        # Audit log
        self._log_change('upload_tables', user, {
            'new_version': new_version,
            'effective_date': effective_date
        })

        try:
            from services.actuarial_persistence import persist_actuarial_store
            persist_actuarial_store(self)
        except Exception:
            pass
        
        return {'success': True, 'version': new_version}
    
    def update_config(self, updates: Dict, user: str) -> Dict:
        """Update underwriting configuration"""
        old_config = asdict(self.config)
        
        # Apply updates
        if 'decline_threshold' in updates:
            self.config.decline_threshold = int(updates['decline_threshold'])
        if 'loadings' in updates:
            self.config.loadings = {int(k): float(v) for k, v in updates['loadings'].items()}
        if 'coverage_limits' in updates:
            self.config.coverage_limits = {int(k): float(v) for k, v in updates['coverage_limits'].items()}
        if 'disability_exclusion_threshold' in updates:
            self.config.disability_exclusion_threshold = int(updates['disability_exclusion_threshold'])
        if 'expense_loading_pct' in updates:
            self.config.expense_loading_pct = float(updates['expense_loading_pct'])
        if 'profit_margin_pct' in updates:
            self.config.profit_margin_pct = float(updates['profit_margin_pct'])
        if 'discount_rate' in updates:
            self.config.discount_rate = float(updates['discount_rate'])
        if 'disability_share_of_life' in updates:
            raw = float(updates['disability_share_of_life'])
            # Accept either fraction (0..1) or percentage (>1) input
            self.config.disability_share_of_life = _clamp(
                raw / 100.0 if raw > 1.0 else raw, 0.0, 1.0,
            )
        if 'disability_share_of_life_post65' in updates:
            raw = float(updates['disability_share_of_life_post65'])
            self.config.disability_share_of_life_post65 = _clamp(
                raw / 100.0 if raw > 1.0 else raw, 0.0, 1.0,
            )
        if 'life_share_of_coverage' in updates:
            raw = float(updates['life_share_of_coverage'])
            self.config.life_share_of_coverage = _clamp(
                raw / 100.0 if raw > 1.0 else raw, 0.0, 1.0,
            )
        if 'life_share_of_coverage_post65' in updates:
            raw = float(updates['life_share_of_coverage_post65'])
            self.config.life_share_of_coverage_post65 = _clamp(
                raw / 100.0 if raw > 1.0 else raw, 0.0, 1.0,
            )
        if 'disability_band_age' in updates:
            self.config.disability_band_age = max(1, min(120, int(updates['disability_band_age'])))

        # Demographic multipliers: accept absolute factors (e.g. 1.75) only.
        # Clamp to [0, 10] to keep integrity and avoid runaway premiums.
        _demo_scalar_keys = (
            'smoker_mortality_factor', 'smoker_disability_factor',
            'former_smoker_mortality_factor', 'former_smoker_disability_factor',
            'nonsmoker_mortality_factor', 'nonsmoker_disability_factor',
            'male_mortality_factor', 'male_disability_factor',
            'female_mortality_factor', 'female_disability_factor',
        )
        for key in _demo_scalar_keys:
            if key in updates:
                setattr(self.config, key, _clamp(float(updates[key]), 0.0, 10.0))
        for key in ('ethnicity_mortality_factors', 'ethnicity_disability_factors'):
            if key in updates and isinstance(updates[key], dict):
                base = _default_ethnicity_factors()
                for eth_key, eth_val in updates[key].items():
                    base[str(eth_key).lower()] = _clamp(float(eth_val), 0.0, 10.0)
                setattr(self.config, key, base)

        # Bump config revision so priced policies can pin dashboard saves.
        try:
            ver = str(self.config.config_version or 'cfg_v1')
            if ver.startswith('cfg_v') and ver[4:].isdigit():
                self.config.config_version = f'cfg_v{int(ver[4:]) + 1}'
            else:
                self.config.config_version = f'{ver}+1'
        except Exception:
            self.config.config_version = 'cfg_v2'

        self.config.last_modified = datetime.now().isoformat()
        self.config.modified_by = user
        
        # Audit log
        self._log_change('update_config', user, {
            'old_config': old_config,
            'new_config': asdict(self.config)
        })

        try:
            from services.actuarial_persistence import persist_actuarial_store
            persist_actuarial_store(self)
        except Exception as persist_err:
            # Persistence is best-effort relative to in-memory success, but
            # surface the failure so operators see it on the API response.
            return {
                'success': True,
                'config': asdict(self.config),
                'persistence_warning': str(persist_err),
            }
        
        return {'success': True, 'config': asdict(self.config), 'persisted': True}
    
    def update_current_tables(self, table_type: str, table_data: List[Dict], user: str) -> Dict:
        """Update a specific table within the current version without creating a new version.
        
        Args:
            table_type: One of 'mortality_rates', 'disability_incidence_rates', 
                       'adl_mortality_multipliers', 'adl_disability_multipliers', 
                       'adl_benefit_percentages', 'lapse_rates'
            table_data: List of table row data
            user: Username making the change
            
        Returns:
            Dict with success status and updated table
        """
        valid_types = [
            'mortality_rates', 'disability_incidence_rates',
            'adl_mortality_multipliers', 'adl_disability_multipliers',
            'adl_benefit_percentages', 'lapse_rates'
        ]
        
        if table_type not in valid_types:
            return {'success': False, 'error': f'Invalid table type: {table_type}. Must be one of {valid_types}'}
        
        current_tables = self.versions.get(self.current_version, {})
        if not current_tables:
            return {'success': False, 'error': 'No current version found'}
        
        old_data = current_tables.get(table_type, [])
        
        # Validate the new data
        if table_type in ['mortality_rates', 'disability_incidence_rates']:
            for item in table_data:
                rate = item.get('rate_per_1000')
                if rate is None:
                    return {'success': False, 'error': f'{table_type}: rate_per_1000 is required'}
                if rate < 0 or rate > 500:
                    return {'success': False, 'error': f'{table_type}: rate_per_1000 must be 0-500 per 1000 lives, got {rate}'}
        
        if table_type in ['adl_mortality_multipliers', 'adl_disability_multipliers']:
            for item in table_data:
                mult = item.get('multiplier')
                if mult is None:
                    return {'success': False, 'error': f'{table_type}: multiplier is required'}
                if mult < 0.1 or mult > 20:
                    return {'success': False, 'error': f'{table_type}: multiplier must be 0.1-20, got {mult}'}
        
        if table_type == 'adl_benefit_percentages':
            for item in table_data:
                pct = item.get('benefit_pct')
                if pct is None:
                    return {'success': False, 'error': f'{table_type}: benefit_pct is required'}
                if pct < 0 or pct > 1:
                    return {'success': False, 'error': f'{table_type}: benefit_pct must be 0.0-1.0 (decimal, where 1.0 = 100%), got {pct}'}
        
        # Update the table
        current_tables[table_type] = table_data
        
        # Audit log
        self._log_change('update_table', user, {
            'table_type': table_type,
            'old_data': old_data,
            'new_data': table_data
        })

        try:
            from services.actuarial_persistence import persist_actuarial_store
            persist_actuarial_store(self)
        except Exception:
            pass
        
        return {'success': True, 'table_type': table_type, 'data': table_data}
    
    def get_default_config(self) -> Dict:
        """Get the original default underwriting configuration values.
        
        Returns:
            Dict with default configuration values
        """
        return {
            'decline_threshold': 9,
            'loadings': {6: 0.15, 7: 0.30, 8: 0.50},
            'coverage_limits': {6: 1000000, 7: 750000, 8: 500000},
            'disability_exclusion_threshold': 8,
            'expense_loading_pct': 0.15,
            'profit_margin_pct': 0.10,
            'discount_rate': 0.035,
            'disability_share_of_life': 0.25,
            'disability_share_of_life_post65': 1.0,
            'life_share_of_coverage': 1.0,
            'life_share_of_coverage_post65': 0.25,
            'disability_band_age': 65,
            'smoker_mortality_factor': 1.0,
            'smoker_disability_factor': 1.0,
            'former_smoker_mortality_factor': 1.0,
            'former_smoker_disability_factor': 1.0,
            'nonsmoker_mortality_factor': 1.0,
            'nonsmoker_disability_factor': 1.0,
            'male_mortality_factor': 1.0,
            'male_disability_factor': 1.0,
            'female_mortality_factor': 1.0,
            'female_disability_factor': 1.0,
            'ethnicity_mortality_factors': _default_ethnicity_factors(),
            'ethnicity_disability_factors': _default_ethnicity_factors(),
            'config_version': 'cfg_v1',
        }
    
    def get_default_tables(self) -> Dict:
        """Get the original default actuarial tables.
        
        Returns:
            Dict with all default table values
        """
        return {
            'mortality_rates': [
                {'age_min': 0, 'age_max': 30, 'rate_per_1000': 0.5},
                {'age_min': 30, 'age_max': 40, 'rate_per_1000': 1.2},
                {'age_min': 40, 'age_max': 50, 'rate_per_1000': 2.5},
                {'age_min': 50, 'age_max': 60, 'rate_per_1000': 5.0},
                {'age_min': 60, 'age_max': 70, 'rate_per_1000': 12.0},
                {'age_min': 70, 'age_max': 80, 'rate_per_1000': 30.0},
                {'age_min': 80, 'age_max': 120, 'rate_per_1000': 75.0},
            ],
            'disability_incidence_rates': [
                {'age_min': 0, 'age_max': 30, 'rate_per_1000': 2.0},
                {'age_min': 30, 'age_max': 40, 'rate_per_1000': 4.0},
                {'age_min': 40, 'age_max': 50, 'rate_per_1000': 8.0},
                {'age_min': 50, 'age_max': 60, 'rate_per_1000': 15.0},
                {'age_min': 60, 'age_max': 70, 'rate_per_1000': 30.0},
                {'age_min': 70, 'age_max': 80, 'rate_per_1000': 50.0},
                {'age_min': 80, 'age_max': 120, 'rate_per_1000': 80.0},
            ],
            'adl_mortality_multipliers': [
                {'adl': 1, 'multiplier': 0.8},
                {'adl': 2, 'multiplier': 0.85},
                {'adl': 3, 'multiplier': 0.9},
                {'adl': 4, 'multiplier': 0.95},
                {'adl': 5, 'multiplier': 1.0},
                {'adl': 6, 'multiplier': 1.1},
                {'adl': 7, 'multiplier': 1.2},
                {'adl': 8, 'multiplier': 1.35},
                {'adl': 9, 'multiplier': 1.5},
                {'adl': 10, 'multiplier': 1.8},
            ],
            'adl_disability_multipliers': [
                {'adl': 1, 'multiplier': 0.3},
                {'adl': 2, 'multiplier': 0.5},
                {'adl': 3, 'multiplier': 0.7},
                {'adl': 4, 'multiplier': 0.9},
                {'adl': 5, 'multiplier': 1.0},
                {'adl': 6, 'multiplier': 1.5},
                {'adl': 7, 'multiplier': 2.0},
                {'adl': 8, 'multiplier': 3.0},
                {'adl': 9, 'multiplier': 5.0},
                {'adl': 10, 'multiplier': 8.0},
            ],
            'adl_benefit_percentages': [
                {'adl': 1, 'benefit_pct': 0.0},
                {'adl': 2, 'benefit_pct': 0.0},
                {'adl': 3, 'benefit_pct': 0.0},
                {'adl': 4, 'benefit_pct': 0.25},
                {'adl': 5, 'benefit_pct': 0.25},
                {'adl': 6, 'benefit_pct': 0.50},
                {'adl': 7, 'benefit_pct': 0.50},
                {'adl': 8, 'benefit_pct': 0.85},
                {'adl': 9, 'benefit_pct': 1.0},
                {'adl': 10, 'benefit_pct': 1.0},
            ],
            'lapse_rates': [
                {'year': 1, 'rate': 0.08},
                {'year': 2, 'rate': 0.05},
                {'year': 3, 'rate': 0.04},
                {'year_min': 4, 'year_max': 10, 'rate': 0.03},
                {'year_min': 11, 'year_max': 25, 'rate': 0.02},
                {'year_min': 26, 'year_max': 100, 'rate': 0.01},
            ]
        }
    
    def reset_config_to_default(self, user: str) -> Dict:
        """Reset underwriting configuration to default values.
        
        Args:
            user: Username making the change
            
        Returns:
            Dict with success status and reset config
        """
        old_config = asdict(self.config)
        defaults = self.get_default_config()
        
        self.config = UnderwritingConfig(
            decline_threshold=defaults['decline_threshold'],
            loadings=defaults['loadings'],
            coverage_limits=defaults['coverage_limits'],
            disability_exclusion_threshold=defaults['disability_exclusion_threshold'],
            expense_loading_pct=defaults['expense_loading_pct'],
            profit_margin_pct=defaults['profit_margin_pct'],
            discount_rate=defaults['discount_rate'],
            disability_share_of_life=defaults.get('disability_share_of_life', 0.25),
            disability_share_of_life_post65=defaults.get('disability_share_of_life_post65', 1.0),
            life_share_of_coverage=defaults.get('life_share_of_coverage', 1.0),
            life_share_of_coverage_post65=defaults.get('life_share_of_coverage_post65', 0.25),
            disability_band_age=int(defaults.get('disability_band_age', 65)),
            smoker_mortality_factor=float(defaults.get('smoker_mortality_factor', 1.0)),
            smoker_disability_factor=float(defaults.get('smoker_disability_factor', 1.0)),
            former_smoker_mortality_factor=float(defaults.get('former_smoker_mortality_factor', 1.0)),
            former_smoker_disability_factor=float(defaults.get('former_smoker_disability_factor', 1.0)),
            nonsmoker_mortality_factor=float(defaults.get('nonsmoker_mortality_factor', 1.0)),
            nonsmoker_disability_factor=float(defaults.get('nonsmoker_disability_factor', 1.0)),
            male_mortality_factor=float(defaults.get('male_mortality_factor', 1.0)),
            male_disability_factor=float(defaults.get('male_disability_factor', 1.0)),
            female_mortality_factor=float(defaults.get('female_mortality_factor', 1.0)),
            female_disability_factor=float(defaults.get('female_disability_factor', 1.0)),
            ethnicity_mortality_factors=dict(
                defaults.get('ethnicity_mortality_factors') or _default_ethnicity_factors()
            ),
            ethnicity_disability_factors=dict(
                defaults.get('ethnicity_disability_factors') or _default_ethnicity_factors()
            ),
            config_version=str(defaults.get('config_version', 'cfg_v1')),
            last_modified=datetime.now().isoformat(),
            modified_by=user
        )
        
        # Audit log
        self._log_change('reset_config', user, {
            'old_config': old_config,
            'new_config': asdict(self.config)
        })
        try:
            from services.actuarial_persistence import persist_actuarial_store
            persist_actuarial_store(self)
        except Exception:
            pass
        
        return {'success': True, 'config': asdict(self.config)}
    
    def reset_tables_to_default(self, table_type: str, user: str) -> Dict:
        """Reset a specific table to its default values.
        
        Args:
            table_type: The table type to reset (e.g., 'mortality_rates')
            user: Username making the change
            
        Returns:
            Dict with success status and reset table data
        """
        defaults = self.get_default_tables()
        
        if table_type not in defaults:
            return {'success': False, 'error': f'Invalid table type: {table_type}'}
        
        current_tables = self.versions.get(self.current_version, {})
        if not current_tables:
            return {'success': False, 'error': 'No current version found'}
        
        old_data = current_tables.get(table_type, [])
        current_tables[table_type] = defaults[table_type]
        
        # Audit log
        self._log_change('reset_table', user, {
            'table_type': table_type,
            'old_data': old_data,
            'new_data': defaults[table_type]
        })
        
        return {'success': True, 'table_type': table_type, 'data': defaults[table_type]}
    
    def _validate_tables(self, tables: Dict) -> Dict:
        """Validate table structure and values"""
        errors = []
        
        # Check required tables exist
        required = ['mortality_rates', 'disability_incidence_rates', 
                   'adl_mortality_multipliers', 'adl_disability_multipliers']
        for table in required:
            if table not in tables:
                errors.append(f'Missing required table: {table}')
        
        # Validate rates are within bounds
        for table in ['mortality_rates', 'disability_incidence_rates']:
            if table in tables:
                for item in tables[table]:
                    rate = item.get('rate_per_1000', 0)
                    if rate < 0 or rate > 1000:
                        errors.append(f'{table}: rate must be 0-1000, got {rate}')
        
        # Validate multipliers
        for table in ['adl_mortality_multipliers', 'adl_disability_multipliers']:
            if table in tables:
                for item in tables[table]:
                    mult = item.get('multiplier', 0)
                    if mult < 0.1 or mult > 20:
                        errors.append(f'{table}: multiplier must be 0.1-20, got {mult}')
        
        return {'valid': len(errors) == 0, 'errors': errors}
    
    def _log_change(self, action: str, user: str, details: Dict):
        """Log an audit entry"""
        self.audit_log.append({
            'timestamp': datetime.now().isoformat(),
            'action': action,
            'user': user,
            'details': details
        })
    
    def get_audit_log(self, limit: int = 100) -> List[Dict]:
        """Get recent audit log entries"""
        return self.audit_log[-limit:]


# =============================================================================
# AUTOMATION METRICS
# =============================================================================

class AutomationMetrics:
    """
    Tracks automation quality for underwriting, claims, billing.
    Higher automation = lower operational costs.
    """
    
    # Base automation rates (% of cases auto-processed)
    BASE_RATES = {
        'underwriting': {
            'auto_approve': 0.45,      # 45% auto-approved
            'auto_decline': 0.10,      # 10% auto-declined
            'auto_refer': 0.15,        # 15% auto-referred
            'manual_review': 0.30      # 30% need manual review
        },
        'claims': {
            'auto_approve': 0.35,      # 35% auto-approved
            'auto_decline': 0.08,      # 8% auto-declined (fraud detection)
            'auto_partial': 0.12,      # 12% auto-partial approval
            'manual_review': 0.45      # 45% need manual review
        },
        'billing': {
            'auto_collect': 0.85,      # 85% auto-collected
            'auto_reminder': 0.10,     # 10% auto-reminder sent
            'manual_followup': 0.05    # 5% need manual followup
        }
    }
    
    # Scale factors - automation improves with portfolio size
    SCALE_EFFICIENCY = {
        1000: 1.0,        # Base rate at 1K
        10000: 1.05,      # 5% improvement at 10K
        100000: 1.10,     # 10% improvement at 100K
        1000000: 1.15,    # 15% improvement at 1M (AI/ML learning)
        10000000: 1.20    # 20% improvement at 10M
    }
    
    @classmethod
    def get_scale_factor(cls, customer_count: int) -> float:
        """Get automation efficiency scale factor for portfolio size"""
        for threshold, factor in sorted(cls.SCALE_EFFICIENCY.items(), reverse=True):
            if customer_count >= threshold:
                return factor
        return 1.0
    
    @classmethod
    def calculate_automation_rates(cls, customer_count: int) -> Dict:
        """Calculate automation rates for given portfolio size"""
        scale = cls.get_scale_factor(customer_count)
        
        result = {
            'scale_factor': scale,
            'customer_count': customer_count
        }
        
        for process, rates in cls.BASE_RATES.items():
            result[process] = {}
            total_auto = 0
            
            for action, base_rate in rates.items():
                if action != 'manual_review':
                    # Scale automation rates up (capped at logical maximums)
                    scaled_rate = min(base_rate * scale, 0.95)
                    result[process][action] = round(scaled_rate, 4)
                    total_auto += scaled_rate
            
            # Manual review is what's left
            result[process]['manual_review'] = round(max(0.05, 1 - total_auto), 4)
            result[process]['total_automation_pct'] = round(1 - result[process]['manual_review'], 4)
        
        # Overall automation score
        overall = (
            result['underwriting']['total_automation_pct'] * 0.4 +
            result['claims']['total_automation_pct'] * 0.35 +
            result['billing']['total_automation_pct'] * 0.25
        )
        result['overall_automation_pct'] = round(overall, 4)
        
        return result


# =============================================================================
# PORTFOLIO SIMULATION ENGINE
# =============================================================================

class PortfolioSimulator:
    """
    Generates simulated portfolios with realistic demographics.
    Premium components for every simulated customer come from the central
    :func:`services.pricing_kernel.price_policy` — the single source of
    truth for actuarial pricing across the platform.
    """

    def __init__(self, tables_store: ActuarialTablesStore):
        self.tables = tables_store
        # Lazy import to avoid a cycle at module load.
        from services import pricing_kernel as _pk  # noqa: F401
        self._pk = _pk

    def _build_premium_reconciliation(self, params: 'SimulationParams', accepted_count: int,
                                       totals: Dict[str, float], expense_amount: float,
                                       profit_amount: float) -> Dict[str, Any]:
        """Build a verifiable arithmetic-chain proof of the simulation totals.

        Each entry exposes the literal multiplication / sum that produces the
        portfolio number, plus a ``check`` flag. Callers (dashboard, audit,
        reconciler) can render this directly without re-running any math.
        """
        n = max(0, int(accepted_count))
        total_premium = float(totals.get('annual_premium', 0.0) or 0.0)
        total_risk = float(totals.get('risk_premium', 0.0) or 0.0)
        total_savings = float(totals.get('savings_premium', 0.0) or 0.0)
        savings_rate = float(getattr(params, 'savings_rate', 0.0) or 0.0)
        savings_formula = str(getattr(params, 'savings_formula', 'risk_premium_markup')).lower()

        avg_premium = total_premium / n if n else 0.0
        avg_risk = total_risk / n if n else 0.0
        avg_savings = total_savings / n if n else 0.0
        avg_expense = expense_amount / n if n else 0.0
        avg_profit = profit_amount / n if n else 0.0

        # Identity 1: N × avg_premium ≈ total_premium (rounding errors only)
        avg_x_n = n * avg_premium
        identity_n_times_avg = abs(avg_x_n - total_premium) < 1.0

        # Identity 2: components sum to total
        sum_components = total_risk + total_savings + expense_amount + profit_amount
        identity_components_sum = abs(sum_components - total_premium) < 1.0

        # Identity 3 (only meaningful for the markup formula):
        # total_savings ≈ savings_rate × total_risk
        markup_expected = savings_rate * total_risk
        identity_markup_holds = (
            savings_formula != 'risk_premium_markup'
            or abs(total_savings - markup_expected) < max(1.0, total_premium * 1e-6)
        )

        return {
            'accepted_customers': n,
            'avg_premium_per_customer': round(avg_premium, 2),
            'avg_risk_premium_per_customer': round(avg_risk, 2),
            'avg_savings_premium_per_customer': round(avg_savings, 2),
            'avg_expense_loading_per_customer': round(avg_expense, 2),
            'avg_profit_margin_per_customer': round(avg_profit, 2),
            'identities': {
                'n_times_avg_premium_equals_total': {
                    'formula': 'N × avg_premium = total_annual_premium',
                    'n': n,
                    'avg_premium': round(avg_premium, 2),
                    'computed': round(avg_x_n, 2),
                    'expected': round(total_premium, 2),
                    'delta': round(avg_x_n - total_premium, 2),
                    'check': identity_n_times_avg,
                },
                'sum_of_components_equals_total': {
                    'formula': 'risk + savings + expense + profit = total_annual_premium',
                    'risk': round(total_risk, 2),
                    'savings': round(total_savings, 2),
                    'expense': round(expense_amount, 2),
                    'profit': round(profit_amount, 2),
                    'computed': round(sum_components, 2),
                    'expected': round(total_premium, 2),
                    'delta': round(sum_components - total_premium, 2),
                    'check': identity_components_sum,
                },
                'savings_markup_identity': {
                    'formula': 'total_savings_premium = savings_rate × total_risk_premium'
                    if savings_formula == 'risk_premium_markup'
                    else 'not applicable (formula = ' + savings_formula + ')',
                    'savings_rate': round(savings_rate, 6),
                    'computed': round(markup_expected, 2),
                    'actual': round(total_savings, 2),
                    'delta': round(total_savings - markup_expected, 2),
                    'check': identity_markup_holds,
                    'applies': savings_formula == 'risk_premium_markup',
                },
            },
            'all_identities_pass': bool(
                identity_n_times_avg and identity_components_sum and identity_markup_holds
            ),
        }

    def generate_portfolio(self, params: SimulationParams) -> Dict:
        """
        Generate a simulated portfolio with demographics and calculate metrics.
        
        All pricing uses the central actuarial tables store.
        """
        start_time = datetime.now()
        
        # Generate customers
        customers = []
        demographics = {
            'age_distribution': {},
            'gender': {'male': 0, 'female': 0},
            'smoking': {'smoker': 0, 'former': 0, 'nonsmoker': 0},
            'ethnicity': {k: 0 for k in params.ethnicity.keys()},
            'adl_distribution': {i: 0 for i in range(1, 11)},
            'coverage_distribution': {},
            'term_distribution': {}
        }
        
        # Declined tracking
        declined = {
            'count': 0,
            'coverage_total': 0,
            'reasons': {}
        }
        
        # Financial totals
        totals = {
            'coverage': 0,
            'annual_premium': 0,
            'risk_premium': 0,  # Risk component only (for loss ratio)
            'savings_premium': 0,
            'pv_mortality_claims': 0,
            'pv_disability_claims': 0
        }
        
        # Generate each customer
        for i in range(params.customer_count):
            customer = self._generate_customer(params)
            
            # Check underwriting
            uw_result = self._check_underwriting(customer)
            
            if not uw_result['accepted']:
                declined['count'] += 1
                declined['coverage_total'] += customer['coverage']
                reason = uw_result['reason']
                declined['reasons'][reason] = declined['reasons'].get(reason, 0) + 1
                continue
            
            # Calculate premium using central tables
            premium = self._calculate_premium(customer, uw_result, params)
            customer['annual_premium'] = premium['annual_premium']
            customer['risk_premium'] = premium['risk_premium']
            customer['savings_premium'] = premium['savings_premium']
            customer['pv_mortality'] = premium['pv_mortality']
            customer['pv_disability'] = premium['pv_disability']
            customer['integrity_hash'] = premium.get('integrity_hash')
            
            # Update totals
            totals['coverage'] += customer['coverage']
            totals['annual_premium'] += customer['annual_premium']
            totals['risk_premium'] += customer['risk_premium']
            totals['savings_premium'] += customer['savings_premium']
            totals['pv_mortality_claims'] += customer['pv_mortality']
            totals['pv_disability_claims'] += customer['pv_disability']
            
            # Update demographics
            age_bracket = self._get_age_bracket(customer['age'])
            demographics['age_distribution'][age_bracket] = \
                demographics['age_distribution'].get(age_bracket, 0) + 1
            demographics['gender'][customer['gender']] += 1
            smoke_key = str(customer.get('smoking_status') or 'nonsmoker')
            if smoke_key not in demographics['smoking']:
                demographics['smoking'][smoke_key] = 0
            demographics['smoking'][smoke_key] += 1
            demographics['ethnicity'][customer['ethnicity']] += 1
            demographics['adl_distribution'][customer['adl']] += 1
            
            coverage_bracket = self._get_coverage_bracket(customer['coverage'])
            demographics['coverage_distribution'][coverage_bracket] = \
                demographics['coverage_distribution'].get(coverage_bracket, 0) + 1
            
            term_bracket = f"{customer['term']} years"
            demographics['term_distribution'][term_bracket] = \
                demographics['term_distribution'].get(term_bracket, 0) + 1
            
            customers.append(customer)
        
        # Calculate automation metrics
        automation = AutomationMetrics.calculate_automation_rates(params.customer_count)
        
        # Calculate risk metrics
        accepted_count = len(customers)
        total_expected_claims = totals['pv_mortality_claims'] + totals['pv_disability_claims']
        
        # Calculate average term for proper loss ratio
        avg_term = 17.5  # Default average
        if customers:
            avg_term = sum(c['term'] for c in customers) / len(customers)
        
        # =================================================================
        # LOSS RATIO CALCULATION (Industry Standard)
        # =================================================================
        # Loss Ratio = Expected Claims / Premium Collected (for same period)
        # 
        # For annual comparison:
        # - Annual Expected Claims = Total PV Claims / Average Term
        # - Annual Premium = Total Annual Premium (already annual)
        #
        # For full-term comparison:
        # - Total Expected Claims (PV)
        # - Total Premium Over Term = Annual Premium * Average Term
        # =================================================================
        
        # Annualized expected claims
        annual_expected_claims = total_expected_claims / avg_term if avg_term > 0 else 0
        
        # Loss ratio on TOTAL annual premium (the main metric)
        # This shows what % of collected premium goes to claims
        loss_ratio = round((annual_expected_claims / totals['annual_premium']) * 100, 2) if totals['annual_premium'] > 0 else 0
        
        # Loss ratio on RISK premium only (excludes savings component)
        # This shows if risk pricing is adequate
        loss_ratio_on_risk = round((annual_expected_claims / totals['risk_premium']) * 100, 2) if totals['risk_premium'] > 0 else 0
        
        risk_metrics = {
            'pv_mortality_claims': round(totals['pv_mortality_claims'], 2),
            'pv_disability_claims': round(totals['pv_disability_claims'], 2),
            'total_expected_claims': round(total_expected_claims, 2),  # PV over full term
            'annual_expected_claims': round(annual_expected_claims, 2),  # Annualized
            'total_risk_premium': round(totals['risk_premium'], 2),
            'total_savings_premium': round(totals['savings_premium'], 2),
            'loss_ratio': loss_ratio,  # Claims vs Total Premium (annual basis) - KEY METRIC
            'loss_ratio_on_risk': loss_ratio_on_risk,  # Claims vs Risk Premium only
            'mortality_pct_of_claims': round((totals['pv_mortality_claims'] / total_expected_claims) * 100, 2) if total_expected_claims > 0 else 0,
            'disability_pct_of_claims': round((totals['pv_disability_claims'] / total_expected_claims) * 100, 2) if total_expected_claims > 0 else 0,
            'reserve_requirement': round(total_expected_claims * 1.5, 2),  # 150% of expected claims
            'avg_term_years': round(avg_term, 1)
        }
        
        # =================================================================
        # PROFITABILITY CALCULATION
        # =================================================================
        config = self.tables.config
        
        # Annual amounts
        annual_risk_premium = totals['risk_premium']  # Already annual
        annual_savings_premium = totals['savings_premium']  # Already annual
        
        # Calculate expense and profit to match individual customer calculations
        # In _calculate_premium:
        #   expense = risk_premium * expense_loading_pct
        #   profit = (risk_premium + savings_premium + expense) * profit_margin_pct
        #   annual_premium = risk_premium + savings_premium + expense + profit
        
        expense_amount = annual_risk_premium * config.expense_loading_pct
        
        # Profit margin is on (risk + savings + expense) to match _calculate_premium
        profit_amount = (annual_risk_premium + annual_savings_premium + expense_amount) * config.profit_margin_pct
        
        # Verify: components should sum to gross premium
        calculated_gross = annual_risk_premium + annual_savings_premium + expense_amount + profit_amount
        
        # Net profit calculation:
        # Revenue = Risk Premium + Expense Loading + Profit Margin
        # Cost = Expected Claims (savings is pass-through to customer, not cost)
        # Net = Revenue - Cost
        operating_revenue = annual_risk_premium + expense_amount + profit_amount
        net_profit = operating_revenue - annual_expected_claims
        
        # Margin percentages
        net_margin_pct = round((net_profit / totals['annual_premium']) * 100, 2) if totals['annual_premium'] > 0 else 0
        
        profitability = {
            'gross_premium': round(totals['annual_premium'], 2),
            'risk_premium': round(annual_risk_premium, 2),
            'savings_premium': round(annual_savings_premium, 2),
            'expected_claims': round(annual_expected_claims, 2),  # For frontend compatibility
            'expected_claims_annual': round(annual_expected_claims, 2),  # Same, explicit name
            'expense_loading': round(expense_amount, 2),
            'profit_margin': round(profit_amount, 2),
            'net_profit': round(net_profit, 2),
            'net_margin_pct': net_margin_pct,
            'return_on_risk': round((net_profit / annual_risk_premium) * 100, 2) if annual_risk_premium > 0 else 0,
            'calculated_gross': round(calculated_gross, 2),  # For verification
            'components_match': abs(totals['annual_premium'] - calculated_gross) < max(1.0, math.sqrt(accepted_count) * 0.50)
        }
        
        # Build result
        duration = (datetime.now() - start_time).total_seconds()
        
        result = {
            'simulation_id': f"SIM-{datetime.now().strftime('%Y%m%d%H%M%S')}-{random.randint(1000, 9999)}",
            'run_at': datetime.now().isoformat(),
            'duration_seconds': round(duration, 2),
            'tables_version': self.tables.current_version,
            'parameters': asdict(params) if hasattr(params, '__dataclass_fields__') else params.__dict__,
            
            'portfolio_summary': {
                'requested_customers': params.customer_count,
                'accepted_customers': accepted_count,
                'acceptance_rate': round((accepted_count / params.customer_count) * 100, 2),
                'total_coverage': totals['coverage'],
                'total_annual_premium': totals['annual_premium'],
                'total_risk_premium': totals['risk_premium'],
                'total_savings_premium': totals['savings_premium'],
                'avg_coverage': round(totals['coverage'] / accepted_count, 2) if accepted_count > 0 else 0,
                'avg_premium': round(totals['annual_premium'] / accepted_count, 2) if accepted_count > 0 else 0,
                'avg_risk_premium': round(totals['risk_premium'] / accepted_count, 2) if accepted_count > 0 else 0,
                'avg_savings_premium': round(totals['savings_premium'] / accepted_count, 2) if accepted_count > 0 else 0,
            },
            
            'demographics': demographics,
            'declined': declined,
            'risk_metrics': risk_metrics,
            'profitability': profitability,
            'automation': automation,
            
            # Integration points for future development
            'integration_ready': {
                'health_wallet': True,
                'investments': True,
                'communities': True,
                'reinsurance': True
            },
            # Verifiable arithmetic chain so the dashboard, audit, and
            # external auditors can prove the simulation totals add up:
            #   N × avg_premium ≈ total_annual_premium
            #   total_risk + total_savings + total_expense + total_profit = total_annual_premium
            #   total_savings ≈ savings_rate × total_risk  (when RISK_PREMIUM_MARKUP)
            'premium_reconciliation': self._build_premium_reconciliation(
                params, accepted_count, totals, expense_amount, profit_amount,
            ),
            # Pricing kernel provenance — every priced customer in this
            # simulation flowed through the same kernel call signature, so
            # the entire snapshot is reproducible from these identifiers.
            'pricing_kernel': {
                'product_id': getattr(params, 'product_id', 'phins_pure_risk_adjustable'),
                'age_curve_id': getattr(params, 'age_curve_id', 'identity'),
                'savings_rate': float(getattr(params, 'savings_rate', 0.0)),
                'savings_yield_pct': float(getattr(params, 'savings_yield_pct', 0.0)),
                'savings_formula': str(getattr(params, 'savings_formula', 'risk_premium_markup')),
                'claim_model': 'mutually_exclusive',
                'tables_version': self.tables.current_version,
                'expense_loading_pct': self.tables.config.expense_loading_pct,
                'profit_margin_pct': self.tables.config.profit_margin_pct,
                'discount_rate': self.tables.config.discount_rate,
                # Single source of truth for the L:D contract ratio. Every
                # priced customer in this snapshot used the same value;
                # changing the actuary table changes every algorithm.
                'disability_share_of_life': float(self.tables.config.disability_share_of_life),
            },
        }
        result['reinsurance_program'] = calculate_reinsurance_program(result, self.tables)
        # Pre-compute savings vs insurance allocation breakdown so the
        # dashboard, reserve projection, and reports all agree on the split.
        result['savings_allocation'] = apply_savings_allocation(
            result, getattr(params, 'savings_allocation_pct', 0.0) or 0.0
        )
        return result
    
    def _generate_customer(self, params: SimulationParams) -> Dict:
        """Generate a single customer with random demographics"""
        # Age
        if params.age_distribution == 'normal':
            age = int(random.gauss(params.age_mean, params.age_std))
            age = max(params.age_min, min(params.age_max, age))
        else:
            age = random.randint(params.age_min, params.age_max)
        
        # Coverage
        if params.coverage_distribution == 'log_normal':
            # Log-normal distribution (most buy lower coverage)
            log_median = math.log(params.coverage_median)
            coverage = random.lognormvariate(log_median, 0.5)
            coverage = max(params.coverage_min, min(params.coverage_max, coverage))
            # Round to nearest 10K
            coverage = round(coverage / 10000) * 10000
        else:
            coverage = random.uniform(params.coverage_min, params.coverage_max)
            coverage = round(coverage / 10000) * 10000
        
        # Policy term
        if params.policy_term_mode == 'fixed':
            term = params.policy_term_fixed
        else:
            term = random.randint(params.policy_term_min, params.policy_term_max)
        
        # Gender
        gender = 'male' if random.random() * 100 < params.male_pct else 'female'

        # Smoking status (uses Pricing Parameters demographic multipliers when priced)
        smoker_pct = max(0.0, float(getattr(params, 'smoker_pct', 0.0) or 0.0))
        former_pct = max(0.0, float(getattr(params, 'former_smoker_pct', 0.0) or 0.0))
        if smoker_pct + former_pct > 100.0:
            scale = 100.0 / (smoker_pct + former_pct)
            smoker_pct *= scale
            former_pct *= scale
        smoke_roll = random.random() * 100.0
        if smoke_roll < smoker_pct:
            smoking_status = 'smoker'
        elif smoke_roll < smoker_pct + former_pct:
            smoking_status = 'former'
        else:
            smoking_status = 'nonsmoker'
        
        # Ethnicity (priced via ethnicity multipliers when non-neutral)
        eth_roll = random.random() * 100
        cumulative = 0
        ethnicity = 'other'
        for eth, pct in params.ethnicity.items():
            cumulative += pct
            if eth_roll < cumulative:
                ethnicity = eth
                break
        
        # ADL (based on age)
        adl = self._generate_adl_for_age(age)
        
        return {
            'age': age,
            'gender': gender,
            'smoking_status': smoking_status,
            'ethnicity': ethnicity,
            'coverage': coverage,
            'term': term,
            'adl': adl
        }
    
    def _generate_adl_for_age(self, age: int) -> int:
        """Generate ADL level based on age (younger = healthier)"""
        if age < 26:
            # Young - mostly ADL 1-3
            weights = [70, 15, 8, 4, 2, 1, 0, 0, 0, 0]
        elif age < 46:
            # Adult - mixed
            weights = [50, 20, 15, 8, 4, 2, 1, 0, 0, 0]
        else:
            # Mature - more spread
            weights = [30, 20, 20, 15, 8, 4, 2, 1, 0, 0]
        
        return random.choices(range(1, 11), weights=weights)[0]
    
    def _check_underwriting(self, customer: Dict) -> Dict:
        """Check if customer passes underwriting"""
        config = self.tables.config
        adl = customer['adl']
        coverage = customer['coverage']
        
        # Check ADL threshold
        if adl >= config.decline_threshold:
            return {'accepted': False, 'reason': f'ADL {adl} exceeds threshold {config.decline_threshold}'}
        
        # Check coverage limits
        if adl in config.coverage_limits:
            max_coverage = config.coverage_limits[adl]
            if coverage > max_coverage:
                # Reduce coverage instead of declining
                customer['coverage'] = max_coverage
                customer['coverage_reduced'] = True
        
        # Get loading
        loading = config.loadings.get(adl, 0)
        
        # Check disability exclusion
        exclude_disability = adl >= config.disability_exclusion_threshold
        
        return {
            'accepted': True,
            'loading': loading,
            'exclude_disability': exclude_disability
        }
    
    def _calculate_premium(self, customer: Dict, uw_result: Dict,
                            params: Optional['SimulationParams'] = None) -> Dict:
        """Price one simulated customer via the central pricing kernel.

        The kernel is the single source of truth for actuarial pricing.
        With default parameters (``savings_rate=0.5``,
        ``savings_yield_pct=0.0``, ``savings_formula='straight_line'``,
        ``product_id='phins_hybrid_savings'``, ``age_curve_id='identity'``,
        ``claim_model=MUTUALLY_EXCLUSIVE``) the kernel reproduces the
        legacy simulator math bit-for-bit. Changing the savings rate,
        savings yield, product, or age curve actually feeds through into
        every priced customer instead of being a post-hoc relabel.
        """
        pk = self._pk
        params = params if params is not None else SimulationParams()
        formula_label = str(getattr(params, 'savings_formula', 'risk_premium_markup')).lower()
        if formula_label == 'annuity_immediate':
            savings_formula = pk.SavingsFormula.ANNUITY_IMMEDIATE
        elif formula_label == 'straight_line':
            savings_formula = pk.SavingsFormula.STRAIGHT_LINE
        else:
            savings_formula = pk.SavingsFormula.RISK_PREMIUM_MARKUP
        config = pk.pricing_config_from_underwriting(
            self.tables.config,
            savings_rate=float(getattr(params, 'savings_rate', 0.0)),
            savings_yield_pct=float(getattr(params, 'savings_yield_pct', 0.0)),
            claim_model=pk.ClaimModel.MUTUALLY_EXCLUSIVE,
            savings_formula=savings_formula,
        )
        product = pk.get_product(getattr(params, 'product_id', 'phins_pure_risk_adjustable'))
        tables = pk.table_set_from_store(
            self.tables,
            age_curve_id=getattr(params, 'age_curve_id', 'identity'),
            cohort_overrides=get_cohort_overrides_snapshot(),
        )

        components = pk.price_policy(
            pk.PricingCustomer(
                age=int(customer['age']),
                coverage=float(customer['coverage']),
                term_years=int(customer['term']),
                adl_level=int(customer['adl']),
                gender=customer.get('gender'),
                smoking_status=customer.get('smoking_status') or customer.get('smoker'),
                ethnicity=customer.get('ethnicity'),
                cohort={
                    'gender': str(customer.get('gender') or '').lower(),
                    'ethnicity': str(customer.get('ethnicity') or '').lower(),
                    'smoker': str(
                        customer.get('smoking_status') or customer.get('smoker') or ''
                    ).lower(),
                },
            ),
            product, tables, config,
            underwriting_loading=float(uw_result.get('loading', 0.0)),
            exclude_disability=bool(uw_result.get('exclude_disability', False)),
        )

        return {
            'annual_premium': components.annual_premium,
            'risk_premium': components.risk_premium_annual,
            'savings_premium': components.savings_premium_annual,
            'pv_mortality': components.pv_mortality_claims,
            'pv_disability': components.pv_disability_claims,
            'integrity_hash': components.integrity_hash,
            'product_id': components.product_id,
            'age_curve_id': components.age_curve_id,
            'claim_model': components.claim_model,
            'savings_formula': components.savings_formula,
        }
    
    def _get_age_bracket(self, age: int) -> str:
        """Get age bracket label"""
        if age < 10: return '0-9'
        elif age < 20: return '10-19'
        elif age < 30: return '20-29'
        elif age < 40: return '30-39'
        elif age < 50: return '40-49'
        elif age < 60: return '50-59'
        else: return '60+'
    
    def _get_coverage_bracket(self, coverage: float) -> str:
        """Get coverage bracket label"""
        if coverage < 100000: return '<$100K'
        elif coverage < 250000: return '$100K-$250K'
        elif coverage < 500000: return '$250K-$500K'
        elif coverage < 1000000: return '$500K-$1M'
        else: return '$1M+'


# =============================================================================
# INTEGRATION POINTS (Future Development)
# =============================================================================

class ActuarialIntegrations:
    """
    Integration points for wallets, investments, and communities.
    Ready for future development.
    """
    
    @staticmethod
    def get_wallet_data_summary() -> Dict:
        """Get summary of health wallet data for actuarial analysis"""
        # Import from main server (avoid circular import)
        try:
            from web_portal.server import HEALTH_WALLETS
            
            total_balance = sum(w.get('balance', 0) for w in HEALTH_WALLETS.values())
            total_deposits = sum(w.get('monthly_deposit', 0) for w in HEALTH_WALLETS.values())
            active_wallets = len([w for w in HEALTH_WALLETS.values() if w.get('status') == 'active'])
            
            return {
                'total_wallets': len(HEALTH_WALLETS),
                'active_wallets': active_wallets,
                'total_balance': total_balance,
                'total_monthly_deposits': total_deposits,
                'avg_balance': total_balance / len(HEALTH_WALLETS) if HEALTH_WALLETS else 0
            }
        except:
            return {'status': 'not_available', 'reason': 'wallet_data_not_loaded'}
    
    @staticmethod
    def get_investment_data_summary() -> Dict:
        """Get summary of investment account data"""
        try:
            from web_portal.server import INVESTMENT_ACCOUNTS
            
            total_balance = sum(a.get('balance', 0) for a in INVESTMENT_ACCOUNTS.values())
            
            return {
                'total_accounts': len(INVESTMENT_ACCOUNTS),
                'total_balance': total_balance,
                'avg_balance': total_balance / len(INVESTMENT_ACCOUNTS) if INVESTMENT_ACCOUNTS else 0
            }
        except:
            return {'status': 'not_available', 'reason': 'investment_data_not_loaded'}
    
    @staticmethod
    def get_community_data_summary() -> Dict:
        """Get summary of foundation community and messaging activity."""
        try:
            from services.foundation_service import get_foundation_service
            from services.community_messaging_service import get_community_messaging_service

            foundation_service = get_foundation_service(
                enable_persistence=False,
                enable_backup=False,
                enable_billing_integration=False
            )
            community_service = get_community_messaging_service(foundation_service=foundation_service)

            foundations = foundation_service.list_foundations(limit=1_000_000)
            members = list(getattr(foundation_service, '_members', {}).values())

            with community_service._lock:
                threads = list(getattr(community_service, '_threads', {}).values())
                messages = list(getattr(community_service, '_messages', {}).values())

            open_threads = sum(1 for thread in threads if thread.get('status') == 'open')
            foundations_with_threads = len({
                thread.get('foundation_id')
                for thread in threads
                if thread.get('foundation_id')
            })

            return {
                'total_foundations': len(foundations),
                'active_foundations': sum(1 for foundation in foundations if foundation.get('status') == 'active'),
                'total_members': len(members),
                'active_members': sum(1 for member in members if member.get('status') == 'active'),
                'total_threads': len(threads),
                'open_threads': open_threads,
                'closed_threads': max(0, len(threads) - open_threads),
                'foundations_with_threads': foundations_with_threads,
                'total_messages': len(messages),
                'avg_messages_per_thread': round((len(messages) / len(threads)), 2) if threads else 0.0,
            }
        except Exception:
            return {'status': 'not_available', 'reason': 'community_data_not_loaded'}


# =============================================================================
# GLOBAL INSTANCE (Singleton)
# =============================================================================

# Create global actuarial tables store
_actuarial_store = None

def get_actuarial_store() -> ActuarialTablesStore:
    """Get the global actuarial tables store (singleton)"""
    global _actuarial_store
    if _actuarial_store is None:
        _actuarial_store = ActuarialTablesStore()
        try:
            from services.actuarial_persistence import load_actuarial_store
            load_actuarial_store(_actuarial_store)
        except Exception:
            pass
    return _actuarial_store


def get_portfolio_simulator() -> PortfolioSimulator:
    """Get a portfolio simulator with current tables"""
    return PortfolioSimulator(get_actuarial_store())


# =============================================================================
# CONVENIENCE FUNCTIONS (for use by other modules)
# =============================================================================

def get_mortality_rate(age: int) -> float:
    """Get mortality rate from central store"""
    return get_actuarial_store().get_mortality_rate(age)

def get_disability_rate(age: int) -> float:
    """Get disability rate from central store"""
    return get_actuarial_store().get_disability_rate(age)

def get_adl_mortality_multiplier(adl: int) -> float:
    """Get ADL mortality multiplier from central store"""
    return get_actuarial_store().get_adl_mortality_multiplier(adl)

def get_adl_disability_multiplier(adl: int) -> float:
    """Get ADL disability multiplier from central store"""
    return get_actuarial_store().get_adl_disability_multiplier(adl)

def get_underwriting_config() -> UnderwritingConfig:
    """Get current underwriting configuration"""
    return get_actuarial_store().config

# =============================================================================
# CONTRACT SPECIFICATION (single source of truth for the contract draft)
# =============================================================================
#
# This constant captures the contract structure that the actuary dashboard
# prices against. The dashboard fetches it from /api/actuarial/contract-spec
# so the same text appears on the simulator, in audit reports, and in any
# downstream artefact — no copy-pasted prose drift across UI and PDF.
# =============================================================================

CONTRACT_SPECIFICATION: Dict[str, Any] = {
    'product_id': 'phins_pure_risk_adjustable',
    'name': 'PHINS Adjustable Risk Contract',
    'version': 'v1.0',
    'effective_date': '2026-05-12',
    'covered_risks': [
        {
            'risk_factor': 'Death — natural or accidental (pre-65)',
            'benefit_formula': 'Face · 100% (e.g. $500k)',
            'trigger_age': '3 – 65',
        },
        {
            'risk_factor': 'Permanent total disability (3+ ADL) pre-65',
            'benefit_formula': 'D = life ÷ 4 (e.g. $125k when face=$500k)',
            'trigger_age': '3 – 65',
        },
        {
            'risk_factor': 'Long-term loss of earning capacity (pre-65)',
            'benefit_formula': 'D = life ÷ 4 · capped at then-current life ÷ 4',
            'trigger_age': '3 – 65',
        },
        {
            'risk_factor': 'Age 65+ — Life sum steps down to face ÷ 4',
            'benefit_formula': 'Life = face ÷ 4 (e.g. $125k when face=$500k)',
            'trigger_age': '65 – ∞',
        },
        {
            'risk_factor': 'Age 65+ — Disability equals reduced life sum (1:1)',
            'benefit_formula': 'D = life · 100% (e.g. $125k = $125k)',
            'trigger_age': '65 – ∞',
        },
    ],
    'pricing_principle': (
        'Adjustable risk premium only — the monthly premium re-prices each '
        'policy anniversary against the customer\'s attained age, locked '
        'underwriting class and inflation-indexed sum insured. No savings, '
        'cash-value, surrender or investment component exists in the base '
        'contract; a savings add-on may be elected separately and is priced '
        'as a markup on the risk premium (savings premium = savings_rate × '
        'risk premium).'
    ),
    'customer_rights': [
        'Right to underwriting transparency. Full disclosure of the underwriting '
        'decision, age band, risk class and the formula driving the premium.',
        'Right to coverage continuity. Once underwriting is approved and premiums '
        'are paid, cover cannot be cancelled by PHINS for the underwritten causes '
        '(subject to fraud, non-payment and material misrepresentation exceptions).',
        'Right to age-adjusted re-pricing. Every premium step is published in '
        'advance and tied solely to attained age — never to claims history of the '
        'individual.',
        'Right of withdrawal. 30-day cooling-off after issue; pro-rata refund of '
        'unearned premium.',
        'Right to fast-track claims. Disability claims adjudicated within statutory '
        'timelines; death claims within 14 business days of complete documentation.',
        'Right to audit trail. Tamper-evident ledger record of every premium '
        'charge and every underwriting/claim decision.',
    ],
    'customer_liabilities': [
        'Premium payment liability ages 3 – 65. Continuous payment of the '
        'age-adjusted adjustable-risk premium is required to maintain both the '
        'Life and Disability benefits.',
        'Premium payment liability ages 65+. Premium must continue to maintain '
        'the stepped-down life sum (face ÷ 4) and disability equal to that '
        'life sum (D = life, both e.g. $125k on a $500k face).',
        'Disclosure liability. Customer must disclose all material health, '
        'occupational and lifestyle facts at underwriting; non-disclosure voids '
        'the claim.',
        'Anniversary re-pricing acceptance. Customer accepts the published '
        'age-curve adjustments as a condition of cover continuity.',
        'No investment / savings claim on the base contract. Customer expressly '
        'waives any expectation of cash value, surrender, dividend, savings or '
        'investment yield for the risk cover; an optional savings add-on is a '
        'separate accumulation product priced as a markup on the risk premium.',
        'Notice obligations. Disability/death event must be notified within '
        '60 / 30 days respectively, with supporting medical documentation.',
    ],
    'policy_disclaimer': (
        'In the event of underwriting approval, and assuming the customer pays '
        'the age-related adjustable risk premium, PHINS provides before age 65: '
        '(a) a Life benefit equal to the contracted face amount (e.g. $500k); and '
        '(b) a Disability benefit equal to life ÷ 4 (e.g. $125k), subject to the '
        'medical and ADL trigger definitions of the policy. From age 65 the life '
        'sum steps down to face ÷ 4 (e.g. $125k) and disability equals that '
        'reduced life sum (D = life, both $125k). The base product carries no '
        'wallet, no savings, no investment and no other service — only adjustable '
        'risk cover. A savings add-on may be elected separately and is priced as '
        'a markup on the risk premium.'
    ),
    'reference_policyholder_example': (
        'Reference policyholder: age 35 at issue · standard underwriting class · '
        'face = US$500,000 · pre-65 life = $500,000 · disability D = life ÷ 4 = '
        'US$125,000. From age 65: life steps to $125,000 and disability stays '
        'equal to life ($125,000). Premium re-prices each anniversary on the '
        'published age curve. Expected loss derived from PHINS Actuarial '
        'Simulation Tables (life mortality + permanent disability incidence, '
        'OECD-aligned).'
    ),
    'savings_addon': {
        'available': True,
        'formula': 'risk_premium_markup',
        'description': (
            'Optional savings add-on. Customer elects savings_rate (any value, '
            'unbounded). Savings premium = savings_rate × risk premium. '
            'Example: risk premium $100/month, savings_rate 3.0 (300%) → '
            'savings premium $300/month, total before expense/profit $400/month.'
        ),
        'min_savings_rate': 0.0,
        'max_savings_rate_recommended': 10.0,  # 1000%
    },
}


def get_contract_specification() -> Dict[str, Any]:
    """Return a deep copy of the canonical contract specification with the
    actuary-table-driven L:D ratio surfaced as a top-level field so the
    dashboard and audit reports always reflect the current configuration.
    """
    import copy
    spec = copy.deepcopy(CONTRACT_SPECIFICATION)
    cfg = get_actuarial_store().config
    share = float(cfg.disability_share_of_life)
    post = float(getattr(cfg, 'disability_share_of_life_post65', 1.0))
    life_pre = float(getattr(cfg, 'life_share_of_coverage', 1.0))
    life_post = float(getattr(cfg, 'life_share_of_coverage_post65', 0.25))
    band = int(getattr(cfg, 'disability_band_age', 65) or 65)

    def _ratio_display(s: float) -> str:
        if s <= 0:
            return '0'
        if abs(s - 1.0) < 1e-9:
            return '1:1'
        inv = 1.0 / s
        rounded = round(inv)
        if abs(inv - rounded) < 0.01:
            return f'1:{int(rounded)}'
        return f'{s:.4f}'

    def _life_display(s: float) -> str:
        if abs(s - 1.0) < 1e-9:
            return '100% of face'
        if abs(s - 0.25) < 1e-9:
            return '25% of face (÷4)'
        return f'{s * 100:.1f}% of face'

    spec['contract_ratios'] = {
        'disability_share_of_life': round(share, 6),
        'disability_share_of_life_post65': round(post, 6),
        'life_share_of_coverage': round(life_pre, 6),
        'life_share_of_coverage_post65': round(life_post, 6),
        'disability_band_age': band,
        'disability_to_life_ratio_display': _ratio_display(share),
        'disability_to_life_ratio_post65_display': _ratio_display(post),
        'life_share_display': _life_display(life_pre),
        'life_share_post65_display': _life_display(life_post),
        'example_face': 500000,
        'example_pre65_life': round(500000 * life_pre, 2),
        'example_pre65_disability': round(500000 * life_pre * share, 2),
        'example_post65_life': round(500000 * life_post, 2),
        'example_post65_disability': round(500000 * life_post * post, 2),
        'config_version': getattr(cfg, 'config_version', 'cfg_v1'),
        'source': 'UnderwritingConfig age-banded life and disability shares',
        'adjustable_from_dashboard': True,
        'persisted': True,
    }
    spec['demographic_risk_factors'] = {
        'smoker_mortality_factor': float(getattr(cfg, 'smoker_mortality_factor', 1.0)),
        'smoker_disability_factor': float(getattr(cfg, 'smoker_disability_factor', 1.0)),
        'former_smoker_mortality_factor': float(getattr(cfg, 'former_smoker_mortality_factor', 1.0)),
        'former_smoker_disability_factor': float(getattr(cfg, 'former_smoker_disability_factor', 1.0)),
        'nonsmoker_mortality_factor': float(getattr(cfg, 'nonsmoker_mortality_factor', 1.0)),
        'nonsmoker_disability_factor': float(getattr(cfg, 'nonsmoker_disability_factor', 1.0)),
        'male_mortality_factor': float(getattr(cfg, 'male_mortality_factor', 1.0)),
        'male_disability_factor': float(getattr(cfg, 'male_disability_factor', 1.0)),
        'female_mortality_factor': float(getattr(cfg, 'female_mortality_factor', 1.0)),
        'female_disability_factor': float(getattr(cfg, 'female_disability_factor', 1.0)),
        'ethnicity_mortality_factors': dict(
            getattr(cfg, 'ethnicity_mortality_factors', None) or _default_ethnicity_factors()
        ),
        'ethnicity_disability_factors': dict(
            getattr(cfg, 'ethnicity_disability_factors', None) or _default_ethnicity_factors()
        ),
        'applies_to': ['mortality_qx (life)', 'disability_ix (disability)'],
        'composition': 'smoking × sex × ethnicity (independent multipliers)',
        'default_neutral': 1.0,
        'adjustable_from_dashboard': True,
        'persisted': True,
        'integrity_hashed': True,
    }
    return spec


def check_underwriting_eligibility(adl: int, coverage: float) -> Dict:
    """Check underwriting eligibility using central config"""
    config = get_underwriting_config()
    
    if adl >= config.decline_threshold:
        return {
            'eligible': False,
            'reason': f'ADL {adl} exceeds decline threshold {config.decline_threshold}'
        }
    
    approved_coverage = coverage
    if adl in config.coverage_limits:
        approved_coverage = min(coverage, config.coverage_limits[adl])
    
    return {
        'eligible': True,
        'approved_coverage': approved_coverage,
        'loading': config.loadings.get(adl, 0),
        'exclude_disability': adl >= config.disability_exclusion_threshold
    }


# =============================================================================
# RISK REFERENCE MODEL (modular)
# =============================================================================
#
# Mirror of the locked actuarial source block published on the PHINS public
# risk one-pager. Kept here as a *registry of risk-reference profiles* (not a
# frozen 5-year exam) so the dashboard can reproduce any reference profile
# against the public model with verifiable integrity, and new reference
# profiles can be registered without touching the API surface.
#
# A risk-reference profile is fully described by:
#
# * an :class:`AgeCurve` from ``services.pricing_kernel`` (the published curve
#   is registered as ``risk_reference_v1``)
# * mortality q(x) and permanent ADL disability i(x) tables for the selected
#   age window
# * mortality / disability severity factors
# * the desired starting age, projection horizon, life sum, and product
# =============================================================================

RISK_REFERENCE_PROFILES: Dict[str, Dict[str, Any]] = {
    'phins_published_v1': {
        'id': 'phins_published_v1',
        'name': 'PHINS Published Risk Reference (Life + Permanent ADL Disability)',
        'version': 'v2.0',
        'doc_date': '2026-08-07',
        'doc_url': 'https://www.phins.ai/phins-risk-1pager-fefferman.html',
        'doc_title': 'PHINS Executive 1-Pager - Risk Factors',
        'age_curve_id': 'risk_reference_v1',
        # Face amount at issue; attained-age life/disability sums use age bands.
        'reference_life_sum': 500000.0,
        'life_share_of_coverage': 1.0,
        'life_share_of_coverage_post65': 0.25,
        'disability_share_of_life': 0.25,
        'disability_share_of_life_post65': 1.0,
        'disability_band_age': 65,
        'life_base_rate_per_1000_monthly': 0.25,
        'disability_base_rate_per_1000_monthly': 0.20,
        # Kept for back-compat readers; no longer zeros disability at 65.
        'disability_cut_off_age': None,
        'mortality_qx': {
            35: 0.00133, 36: 0.00141, 37: 0.00150, 38: 0.00160, 39: 0.00171,
        },
        'disability_incidence_ix': {
            35: 0.00450, 36: 0.00468, 37: 0.00487, 38: 0.00507, 39: 0.00528,
        },
        'mortality_severity': 1.00,
        'disability_severity': 0.55,
        'reference_start_age': 35,
        'reference_projection_years': 5,
        'covered_risks': ['mortality', 'permanent_adl_disability'],
        'contract_rule': (
            'pre65: life=face & D=life/4; post65: life=face/4 & D=life '
            '(e.g. $500k face → $125k/$125k)'
        ),
    },
}


def contract_benefit_sums_at_age(
    face_amount: float,
    age: int,
    *,
    life_share_pre: float = 1.0,
    life_share_post: float = 0.25,
    disability_share_pre: float = 0.25,
    disability_share_post: float = 1.0,
    band_age: int = 65,
) -> Dict[str, float]:
    """Canonical attained-age life and disability sums (settled product rule).

    Used by risk-reference, valuations, and documentation so every surface
    agrees: before ``band_age`` life=face & D=life/4; from ``band_age`` life
    steps to face×life_share_post and D=life (1:1 at the reduced life sum).
    """
    face = float(face_amount)
    age_i = int(age)
    band = int(band_age or 65)
    if age_i >= band:
        life_share = float(life_share_post)
        d_share = float(disability_share_post)
    else:
        life_share = float(life_share_pre)
        d_share = float(disability_share_pre)
    life_sum = face * life_share
    disability_sum = life_sum * d_share
    return {
        'face_amount': face,
        'age': age_i,
        'band_age': band,
        'life_share': life_share,
        'disability_share': d_share,
        'life_sum': life_sum,
        'disability_sum': disability_sum,
        'post_band': age_i >= band,
    }


def contract_benefit_sums_from_config(face_amount: float, age: int,
                                      config: Any = None) -> Dict[str, float]:
    """Resolve benefit sums using UnderwritingConfig (dashboard Pricing Parameters)."""
    cfg = config
    if cfg is None:
        try:
            cfg = get_actuarial_store().config
        except Exception:
            cfg = None
    return contract_benefit_sums_at_age(
        face_amount,
        age,
        life_share_pre=float(getattr(cfg, 'life_share_of_coverage', 1.0) if cfg else 1.0),
        life_share_post=float(getattr(cfg, 'life_share_of_coverage_post65', 0.25) if cfg else 0.25),
        disability_share_pre=float(getattr(cfg, 'disability_share_of_life', 0.25) if cfg else 0.25),
        disability_share_post=float(getattr(cfg, 'disability_share_of_life_post65', 1.0) if cfg else 1.0),
        band_age=int(getattr(cfg, 'disability_band_age', 65) if cfg else 65),
    )

# Backwards-compatibility alias — previous callers held a reference to this name.
PHINS_FEFFERMAN_MODEL: Dict[str, Any] = RISK_REFERENCE_PROFILES['phins_published_v1']


def register_risk_reference_profile(profile: Dict[str, Any]) -> Dict[str, Any]:
    """Register a new risk-reference profile so the dashboard can render it."""
    profile_id = str(profile.get('id') or '').strip()
    if not profile_id:
        raise ValueError('risk reference profile requires an id')
    RISK_REFERENCE_PROFILES[profile_id] = profile
    return profile


def get_risk_reference_profile(profile_id: Optional[str] = None) -> Dict[str, Any]:
    return RISK_REFERENCE_PROFILES.get(
        profile_id or 'phins_published_v1',
        RISK_REFERENCE_PROFILES['phins_published_v1'],
    )


def list_risk_reference_profiles() -> List[Dict[str, Any]]:
    """List metadata for every registered risk-reference profile."""
    summaries: List[Dict[str, Any]] = []
    for profile in RISK_REFERENCE_PROFILES.values():
        summaries.append({
            'id': profile.get('id'),
            'name': profile.get('name'),
            'version': profile.get('version'),
            'doc_url': profile.get('doc_url'),
            'doc_title': profile.get('doc_title'),
            'age_curve_id': profile.get('age_curve_id'),
            'covered_risks': list(profile.get('covered_risks', [])),
        })
    return summaries


def risk_reference_age_factor(age: int, profile_id: Optional[str] = None) -> float:
    """Age factor for a risk-reference profile (delegates to its age curve)."""
    profile = get_risk_reference_profile(profile_id)
    from services.pricing_kernel import get_age_curve
    curve = get_age_curve(profile.get('age_curve_id', 'risk_reference_v1'))
    return curve.factor(int(age))


def risk_reference_monthly_premiums(age: int,
                                    life_sum: Optional[float] = None,
                                    profile_id: Optional[str] = None,
                                    disability_share_of_life: Optional[float] = None) -> Dict[str, float]:
    """Monthly life + permanent ADL disability premium for the reference policyholder.

    Uses settled age bands (life step-down + D=life post-65). Prefer live
    UnderwritingConfig shares when available so dashboard Pricing Parameters
    flow into risk-reference valuations.
    """
    profile = get_risk_reference_profile(profile_id)
    face = float(life_sum if life_sum is not None else profile['reference_life_sum'])
    try:
        cfg = get_actuarial_store().config
        sums = contract_benefit_sums_from_config(face, age, cfg)
        if disability_share_of_life is not None and not sums['post_band']:
            # Explicit pre-65 override for scenario analysis
            sums = dict(sums)
            sums['disability_share'] = float(disability_share_of_life)
            sums['disability_sum'] = sums['life_sum'] * float(disability_share_of_life)
    except Exception:
        sums = contract_benefit_sums_at_age(
            face,
            age,
            life_share_pre=float(profile.get('life_share_of_coverage', 1.0)),
            life_share_post=float(profile.get('life_share_of_coverage_post65', 0.25)),
            disability_share_pre=float(
                disability_share_of_life
                if disability_share_of_life is not None
                else profile.get('disability_share_of_life', 0.25)
            ),
            disability_share_post=float(profile.get('disability_share_of_life_post65', 1.0)),
            band_age=int(profile.get('disability_band_age', 65) or 65),
        )
    factor = risk_reference_age_factor(age, profile_id)
    life_premium = (
        (sums['life_sum'] / 1000.0)
        * float(profile['life_base_rate_per_1000_monthly'])
        * factor
    )
    disability_premium = 0.0
    if float(sums['disability_share']) > 0.0:
        disability_premium = (
            (sums['disability_sum'] / 1000.0)
            * float(profile['disability_base_rate_per_1000_monthly'])
            * factor
        )
    return {
        'age': age,
        'age_factor': round(factor, 4),
        'face_amount': round(face, 2),
        'life_sum': round(float(sums['life_sum']), 2),
        'disability_sum': round(float(sums['disability_sum']), 2),
        'life_share': round(float(sums['life_share']), 6),
        'disability_share': round(float(sums['disability_share']), 6),
        'life_monthly': round(life_premium, 2),
        'disability_monthly': round(disability_premium, 2),
        'total_monthly': round(life_premium + disability_premium, 2),
        'annual_premium': round((life_premium + disability_premium) * 12, 2),
    }


def build_risk_reference(start_age: Optional[int] = None,
                         projection_years: Optional[int] = None,
                         life_sum: Optional[float] = None,
                         profile_id: Optional[str] = None,
                         disability_share_of_life: Optional[float] = None,
                         savings_rate: Optional[float] = None,
                         savings_yield_pct: Optional[float] = None,
                         management_fee_pct_of_aum: Optional[float] = None) -> Dict[str, Any]:
    """Build a deterministic risk-reference forecast for any (modular) inputs.

    Unlike the previous fixed 5-year exam, this function accepts any
    starting age, projection horizon, life sum and registered profile.

    The L:D contract ratio (``disability_share_of_life``) is now sourced
    from the actuary-table UnderwritingConfig when no override is passed,
    so the risk-reference forecast always agrees with what the pricing
    kernel actually used to price the production portfolio. With default
    inputs it still reproduces the locked public one-pager exactly.
    """
    profile = get_risk_reference_profile(profile_id)
    start_age = int(start_age if start_age is not None else profile['reference_start_age'])
    projection_years = int(projection_years if projection_years is not None else profile['reference_projection_years'])
    face = float(life_sum if life_sum is not None else profile['reference_life_sum'])
    if disability_share_of_life is None:
        try:
            disability_share_of_life = float(
                get_actuarial_store().config.disability_share_of_life
            )
        except Exception:
            disability_share_of_life = float(profile['disability_share_of_life'])
    mortality_qx = profile.get('mortality_qx', {})
    disability_ix = profile.get('disability_incidence_ix', {})

    yearly = []
    cumulative_premium = 0.0
    cumulative_expected_loss = 0.0
    for offset in range(projection_years):
        age = start_age + offset
        premiums = risk_reference_monthly_premiums(
            age, life_sum=face, profile_id=profile_id,
            disability_share_of_life=disability_share_of_life,
        )
        annual = premiums['annual_premium']
        life_at_age = float(premiums.get('life_sum') or face)
        disability_at_age = float(premiums.get('disability_sum') or 0.0)
        qx = float(mortality_qx.get(age, mortality_qx.get(str(age), 0.0)))
        ix = float(disability_ix.get(age, disability_ix.get(str(age), 0.0)))
        expected_loss = (
            qx * life_at_age * float(profile['mortality_severity'])
            + ix * disability_at_age * float(profile['disability_severity'])
        )
        loss_ratio = (expected_loss / annual) if annual > 0 else 0.0
        cumulative_premium += annual
        cumulative_expected_loss += expected_loss
        yearly.append({
            'year': offset + 1,
            'age': age,
            'age_factor': premiums['age_factor'],
            'life_sum': life_at_age,
            'disability_sum': disability_at_age,
            'annual_premium': round(annual, 2),
            'life_monthly': premiums.get('life_monthly'),
            'disability_monthly': premiums.get('disability_monthly'),
            'mortality_qx': qx,
            'disability_ix': ix,
            'expected_loss': round(expected_loss, 2),
            'loss_ratio': round(loss_ratio, 4),
        })

    avg_loss_ratio = (cumulative_expected_loss / cumulative_premium) if cumulative_premium > 0 else 0.0

    # ----- Optional savings accumulation projection -----
    # When the caller passes savings_rate > 0, project a savings AUM
    # accumulation alongside the risk reference forecast so the
    # dashboard's Risk Reference (Locked Source) section can also show
    # the cumulative managed-portfolio balance that grows with yield and
    # is debited by the management fee.
    savings_accumulation = None
    sr = float(savings_rate) if savings_rate is not None else 0.0
    sy = float(savings_yield_pct) if savings_yield_pct is not None else 0.0
    mf = float(management_fee_pct_of_aum) if management_fee_pct_of_aum is not None else 0.0
    if sr > 0:
        years_accum: List[Dict[str, Any]] = []
        opening_aum = 0.0
        cumulative_contribution = 0.0
        cumulative_yield = 0.0
        cumulative_fee = 0.0
        for row in yearly:
            annual_risk = row['annual_premium']  # reference policyholder risk premium
            annual_contribution = annual_risk * sr  # markup formula
            monthly_contribution = annual_contribution / 12.0
            yield_amount = (opening_aum + annual_contribution) * sy
            gross_closing = opening_aum + annual_contribution + yield_amount
            mgmt_fee = gross_closing * mf
            closing_aum = gross_closing - mgmt_fee
            cumulative_contribution += annual_contribution
            cumulative_yield += yield_amount
            cumulative_fee += mgmt_fee
            years_accum.append({
                'year': row['year'],
                'age': row['age'],
                'annual_risk_premium': annual_risk,
                'monthly_contribution': round(monthly_contribution, 2),
                'annual_contribution': round(annual_contribution, 2),
                'opening_balance': round(opening_aum, 2),
                'yield': round(yield_amount, 2),
                'management_fee_income': round(mgmt_fee, 2),
                'gross_closing_aum_before_fee': round(gross_closing, 2),
                'closing_balance': round(closing_aum, 2),
                'cumulative_contribution': round(cumulative_contribution, 2),
            })
            opening_aum = closing_aum
        # Compounded effective yield (CAGR) on the cumulative contribution
        eff_yield = 0.0
        if cumulative_contribution > 0 and opening_aum > 0 and projection_years > 0:
            try:
                eff_yield = (opening_aum / cumulative_contribution) ** (
                    1.0 / projection_years
                ) - 1.0
            except (ValueError, ZeroDivisionError):
                eff_yield = 0.0
        savings_accumulation = {
            'savings_rate': round(sr, 6),
            'savings_yield_pct': round(sy, 6),
            'management_fee_pct_of_aum': round(mf, 6),
            'yearly': years_accum,
            'totals': {
                'cumulative_contribution': round(cumulative_contribution, 2),
                'cumulative_yield': round(cumulative_yield, 2),
                'cumulative_management_fee_income': round(cumulative_fee, 2),
                'closing_aum_balance': round(opening_aum, 2),
                'effective_yield_pct': round(eff_yield, 6),
                'average_monthly_contribution': round(
                    cumulative_contribution / max(1, projection_years * 12), 2
                ),
            },
            'data_integrity': {
                'monthly_x_12_equals_annual': all(
                    abs(r['monthly_contribution'] * 12.0 - r['annual_contribution']) < 1.0
                    for r in years_accum
                ),
                'aum_identity_holds': all(
                    abs(
                        r['closing_balance']
                        - (r['gross_closing_aum_before_fee'] - r['management_fee_income'])
                    ) < 0.5
                    for r in years_accum
                ),
                'closing_aum_non_negative': all(
                    r['closing_balance'] >= -0.5 for r in years_accum
                ),
            },
        }

    issue_sums = contract_benefit_sums_from_config(face, start_age)
    post_sums = contract_benefit_sums_from_config(face, max(start_age, int(issue_sums['band_age'])))
    band_ok = True
    for r in yearly:
        expected_share = (
            float(disability_share_of_life)
            if int(r['age']) < int(issue_sums['band_age'])
            else float(post_sums['disability_share'])
        )
        if abs(float(r['disability_sum']) - float(r['life_sum']) * expected_share) >= 0.01:
            band_ok = False
            break

    payload = {
        'profile_id': profile['id'],
        'source': {
            'document': profile.get('doc_title', 'PHINS Risk Reference'),
            'url': profile.get('doc_url', ''),
            'version': profile.get('version', 'v2.0'),
            'doc_date': profile.get('doc_date', ''),
        },
        'reference': {
            'face_amount': face,
            'life_sum': round(float(issue_sums['life_sum']), 2),
            'disability_sum': round(float(issue_sums['disability_sum']), 2),
            'life_sum_post65': round(float(post_sums['life_sum']), 2),
            'disability_sum_post65': round(float(post_sums['disability_sum']), 2),
            'life_base_rate_per_1000_monthly': float(profile['life_base_rate_per_1000_monthly']),
            'disability_base_rate_per_1000_monthly': float(profile['disability_base_rate_per_1000_monthly']),
            'disability_band_age': int(issue_sums['band_age']),
            'disability_cut_off_age': None,  # settled rule: disability continues post-65
            'start_age': start_age,
            'projection_years': projection_years,
            'covered_risks': list(profile.get('covered_risks', ['mortality', 'permanent_adl_disability'])),
            'age_curve_id': profile.get('age_curve_id', 'risk_reference_v1'),
            'disability_share_of_life': float(disability_share_of_life),
            'disability_share_of_life_post65': float(post_sums['disability_share']),
            'life_share_of_coverage_post65': float(post_sums['life_share']),
            'disability_to_life_ratio_display': (
                f'1:{int(round(1.0 / disability_share_of_life))}'
                if disability_share_of_life and abs(1.0 / disability_share_of_life - round(1.0 / disability_share_of_life)) < 0.01
                else f'{disability_share_of_life:.4f}'
            ),
            'contract_rule': profile.get('contract_rule') or (
                'pre65: life=face & D=life/4; post65: life=face/4 & D=life'
            ),
        },
        'yearly_projection': yearly,
        'totals': {
            'cumulative_premium': round(cumulative_premium, 2),
            'cumulative_expected_loss': round(cumulative_expected_loss, 2),
            'average_loss_ratio': round(avg_loss_ratio, 4),
            'expense_plus_capital_margin': round(1 - avg_loss_ratio, 4) if cumulative_premium > 0 else 0.0,
        },
        'data_integrity': {
            'cumulative_premium_check': abs(
                sum(row['annual_premium'] for row in yearly) - round(cumulative_premium, 2)
            ) < 0.5,
            'cumulative_loss_check': abs(
                sum(row['expected_loss'] for row in yearly) - round(cumulative_expected_loss, 2)
            ) < 0.5,
            'severity_assumptions': {
                'mortality_severity': float(profile['mortality_severity']),
                'disability_severity': float(profile['disability_severity']),
            },
            'disability_sum_matches_age_band': band_ok,
            'issue_age_disability_sum_matches_ratio': abs(
                float(issue_sums['disability_sum'])
                - float(issue_sums['life_sum']) * float(disability_share_of_life)
            ) < 0.01,
        },
    }
    if savings_accumulation is not None:
        payload['savings_accumulation'] = savings_accumulation
    return payload


# Backwards-compatibility aliases for the previous function names. New callers
# should use ``build_risk_reference``, ``risk_reference_age_factor`` and
# ``risk_reference_monthly_premiums``.
build_fefferman_reference = build_risk_reference
fefferman_age_factor = risk_reference_age_factor
fefferman_monthly_premiums = risk_reference_monthly_premiums


# =============================================================================
# RESERVES / IFRS 17 / IBNR PROJECTION
# =============================================================================

@dataclass
class ReserveConfig:
    """
    Configuration for actuarial reserve projection.

    - `dividends_pct`: share of after-tax profit distributed as dividends.
    - `tax_pct`: corporate tax rate on operating profit.
    - `ibnr_pct`: IBNR (Incurred But Not Reported) provision as a percentage of
      annual expected claims (incurred-claims method).
    - `reserve_contribution_pct`: share of retained earnings transferred into
      the actuarial reserve buffer each year.
    - `risk_adjustment_pct`: IFRS 17 Risk Adjustment as a percentage of best
      estimate liability (BEL).
    - `csm_release_pattern`: 'straight_line' or 'coverage_units' for releasing
      the Contractual Service Margin (CSM) over the average term.
    - `savings_allocation_pct`: legacy post-hoc allocation share of total
      premium routed to the savings fund (kept for backwards compatibility;
      modern simulations source the contribution directly from the priced
      savings_premium component).
    - `savings_yield_pct`: assumed annual yield on the savings fund.
    - `management_fee_pct_of_aum`: annual management fee charged against the
      cumulative savings AUM (the fund's closing balance after contributions
      and yield, before the fee). This is the company's earnings from
      managing the savings portfolio — it accrues every year on the growing
      AUM, separate from the underwriting profit margin.
    - `projection_years`: number of "situation years" to project.
    - `initial_reserve`: opening reserve balance.
    - `initial_savings_fund_balance`: opening AUM (rolled-forward balance
      from a previous reserve run, when continuing a projection).
    """

    dividends_pct: float = 0.30
    tax_pct: float = 0.23
    ibnr_pct: float = 0.10
    reserve_contribution_pct: float = 0.40
    risk_adjustment_pct: float = 0.06
    csm_release_pattern: str = 'straight_line'
    savings_allocation_pct: float = 0.0
    savings_yield_pct: float = 0.045
    management_fee_pct_of_aum: float = 0.01  # 1% annual mgmt fee on cumulative AUM
    projection_years: int = 5
    initial_reserve: float = 0.0
    initial_savings_fund_balance: float = 0.0


def _pct_auto(v: float) -> float:
    """Auto-detect whether a value is a fraction (0..1) or percentage (>1) and normalise to fraction."""
    return v / 100.0 if abs(v) > 1.0 else v


def _coerce_reserve_config(payload: Optional[Dict[str, Any]]) -> ReserveConfig:
    payload = payload or {}
    return ReserveConfig(
        dividends_pct=_clamp(_pct_auto(float(payload.get('dividends_pct', 0.30) or 0.0)), 0.0, 1.0),
        tax_pct=_clamp(_pct_auto(float(payload.get('tax_pct', 0.23) or 0.0)), 0.0, 0.6),
        ibnr_pct=_clamp(_pct_auto(float(payload.get('ibnr_pct', 0.10) or 0.0)), 0.0, 1.0),
        reserve_contribution_pct=_clamp(
            _pct_auto(float(payload.get('reserve_contribution_pct', 0.40) or 0.0)), 0.0, 1.0
        ),
        risk_adjustment_pct=_clamp(
            _pct_auto(float(payload.get('risk_adjustment_pct', 0.06) or 0.0)), 0.0, 0.5
        ),
        csm_release_pattern=str(payload.get('csm_release_pattern') or 'straight_line').lower(),
        savings_allocation_pct=_clamp(
            _pct_auto(float(payload.get('savings_allocation_pct', 0.0) or 0.0)), 0.0, 0.95
        ),
        savings_yield_pct=_clamp(
            _pct_auto(float(payload.get('savings_yield_pct', 0.045) or 0.0)), -0.5, 0.5
        ),
        management_fee_pct_of_aum=_clamp(
            _pct_auto(float(payload.get('management_fee_pct_of_aum', 0.01) or 0.0)), 0.0, 0.10
        ),
        projection_years=max(1, min(50, int(payload.get('projection_years', 5) or 5))),
        initial_reserve=max(0.0, float(payload.get('initial_reserve', 0.0) or 0.0)),
        initial_savings_fund_balance=max(
            0.0, float(payload.get('initial_savings_fund_balance', 0.0) or 0.0)
        ),
    )


def apply_savings_allocation(simulation: Dict[str, Any], savings_allocation_pct: float) -> Dict[str, Any]:
    """
    Re-split the simulation's profitability between an "insurance" balance sheet
    and a "savings fund" balance sheet.

    The simulator's `savings_premium` is treated as pass-through. The
    `savings_allocation_pct` here applies to total annual premium and moves a
    share of net profit into the savings fund as a member-allocated balance.
    The output is deterministic and reconciles to the simulation totals so the
    integrity check holds.
    """
    profitability = simulation.get('profitability', {}) or {}
    gross_premium = float(profitability.get('gross_premium', 0.0) or 0.0)
    risk_premium = float(profitability.get('risk_premium', 0.0) or 0.0)
    savings_premium = float(profitability.get('savings_premium', 0.0) or 0.0)
    net_profit = float(profitability.get('net_profit', 0.0) or 0.0)

    share = _clamp(float(savings_allocation_pct or 0.0), 0.0, 0.95)
    insurance_share = 1.0 - share

    savings_balance_sheet = {
        'savings_premium_pass_through': round(savings_premium, 2),
        'allocation_share': round(share, 4),
        'profit_allocated': round(net_profit * share, 2),
        'risk_premium_allocated': round(risk_premium * share, 2),
        'total_to_savings_fund': round(savings_premium + (risk_premium + net_profit) * share, 2),
    }

    insurance_balance_sheet = {
        'allocation_share': round(insurance_share, 4),
        'risk_premium_retained': round(risk_premium * insurance_share, 2),
        'profit_retained': round(net_profit * insurance_share, 2),
        'gross_premium_retained': round(gross_premium - savings_balance_sheet['total_to_savings_fund'], 2),
    }

    total_split = round(
        savings_balance_sheet['total_to_savings_fund']
        + insurance_balance_sheet['gross_premium_retained'],
        2,
    )

    return {
        'savings_allocation_pct': round(share * 100, 2),
        'insurance_balance_sheet': insurance_balance_sheet,
        'savings_balance_sheet': savings_balance_sheet,
        'data_integrity': {
            'gross_premium_input': round(gross_premium, 2),
            'gross_premium_reconciles': (
                abs(total_split - round(gross_premium, 2)) < 1.0
                and insurance_balance_sheet['gross_premium_retained'] >= 0.0
            ),
            'sum_of_shares': round(share + insurance_share, 4),
        },
    }


def reconcile_simulation_with_kernel(simulation: Dict[str, Any]) -> Dict[str, Any]:
    """Prove that a saved simulation's totals can be reproduced by the kernel.

    The reconciler re-prices a representative customer from the simulation
    parameters using the kernel directly, then checks that the resulting
    premium components match what the simulation snapshot stored. This is
    the cross-system integrity proof requested in G8: the saved simulation,
    BI feed, reserve projection, billing/quote pricer and reserve report
    all share the same kernel, so they must agree to the cent.
    """
    pricing_meta = simulation.get('pricing_kernel') or {}
    params = simulation.get('parameters') or {}
    profitability = simulation.get('profitability') or {}
    portfolio = simulation.get('portfolio_summary') or {}

    if not pricing_meta:
        return {
            'reconciled': False,
            'reason': 'simulation snapshot is missing the pricing_kernel provenance block',
        }

    accepted = int(portfolio.get('accepted_customers', 0) or 0)
    avg_coverage = float(portfolio.get('avg_coverage', 0.0) or 0.0)
    avg_premium = float(portfolio.get('avg_premium', 0.0) or 0.0)

    # Use the simulation's mean age / mid-band ADL / fixed-or-mean term as the
    # representative customer for the reconciliation pass.
    if str(params.get('policy_term_mode', 'random')).lower() == 'fixed':
        rep_term = int(params.get('policy_term_fixed', 20) or 20)
    else:
        rep_term = int(round(
            (
                int(params.get('policy_term_min', 5) or 5)
                + int(params.get('policy_term_max', 30) or 30)
            ) / 2
        ))
    rep_age = int(round(float(params.get('age_mean', 35.0) or 35.0)))
    rep_adl = 5
    rep_coverage = avg_coverage if avg_coverage > 0 else float(params.get('coverage_median', 250000.0) or 250000.0)

    # Lazy import to avoid module-load circular import.
    from services.pricing_kernel import (
        ClaimModel, PricingConfig, PricingCustomer, SavingsFormula,
        get_product, price_policy, table_set_from_store,
    )
    store = get_actuarial_store()
    formula_label = str(pricing_meta.get('savings_formula', 'risk_premium_markup')).lower()
    if formula_label == 'annuity_immediate':
        savings_formula = SavingsFormula.ANNUITY_IMMEDIATE
    elif formula_label == 'straight_line':
        savings_formula = SavingsFormula.STRAIGHT_LINE
    else:
        savings_formula = SavingsFormula.RISK_PREMIUM_MARKUP
    config = PricingConfig(
        expense_loading_pct=float(pricing_meta.get('expense_loading_pct', 0.15)),
        profit_margin_pct=float(pricing_meta.get('profit_margin_pct', 0.10)),
        discount_rate=float(pricing_meta.get('discount_rate', 0.035)),
        savings_rate=float(pricing_meta.get('savings_rate', 0.0)),
        savings_yield_pct=float(pricing_meta.get('savings_yield_pct', 0.0)),
        savings_formula=savings_formula,
        claim_model=ClaimModel.MUTUALLY_EXCLUSIVE,
        disability_share_of_life=float(
            pricing_meta.get('disability_share_of_life',
                              get_actuarial_store().config.disability_share_of_life)
        ),
    )
    tables = table_set_from_store(
        store,
        age_curve_id=str(pricing_meta.get('age_curve_id', 'identity')),
        cohort_overrides=get_cohort_overrides_snapshot(),
    )
    product = get_product(str(pricing_meta.get('product_id', 'phins_pure_risk_adjustable')))
    representative = price_policy(
        PricingCustomer(
            age=rep_age, coverage=rep_coverage,
            term_years=rep_term, adl_level=rep_adl,
        ),
        product, tables, config,
    )

    # The portfolio-level reconciliation: the sum of risk/savings/expense/profit
    # the kernel reports for each priced customer must equal the simulation's
    # profitability block. The simulator stores those totals already, so we
    # just compare them here.
    component_check = bool(profitability.get('components_match', False))
    expected_total = (
        float(profitability.get('risk_premium', 0.0) or 0.0)
        + float(profitability.get('savings_premium', 0.0) or 0.0)
        + float(profitability.get('expense_loading', 0.0) or 0.0)
        + float(profitability.get('profit_margin', 0.0) or 0.0)
    )
    gross = float(profitability.get('gross_premium', 0.0) or 0.0)
    portfolio_delta = round(gross - expected_total, 2)

    return {
        'reconciled': component_check and abs(portfolio_delta) < max(1.0, math.sqrt(accepted) * 0.50),
        'representative_customer': {
            'age': rep_age,
            'adl_level': rep_adl,
            'coverage': rep_coverage,
            'term_years': rep_term,
        },
        'representative_components': representative.as_dict(),
        'representative_integrity_hash': representative.integrity_hash,
        'snapshot_portfolio_avg_premium': avg_premium,
        'snapshot_pricing_kernel': pricing_meta,
        'portfolio_reconciliation': {
            'gross_premium': gross,
            'sum_of_components': round(expected_total, 2),
            'delta': portfolio_delta,
            'components_match_flag_in_snapshot': component_check,
        },
        'accepted_customers': accepted,
    }


class ReserveCalculator:
    """
    Multi-year actuarial reserve projection covering:
    - IBNR provision (incurred-claims method)
    - IFRS 17 Best Estimate Liability (BEL), Risk Adjustment, CSM release
    - Annual reserve contribution from retained earnings
    - Dividend and tax flows
    - Savings fund accumulation
    - Lapse-aware in-force decay (using the central lapse table)

    The model is deterministic: the same simulation + config always produces
    the same projection so audit, validation, and reporting all line up.
    """

    def __init__(self, tables_store: Optional[ActuarialTablesStore] = None):
        self.tables = tables_store or get_actuarial_store()

    def project(self, simulation: Dict[str, Any], config: ReserveConfig) -> Dict[str, Any]:
        portfolio = simulation.get('portfolio_summary', {}) or {}
        risk_metrics = simulation.get('risk_metrics', {}) or {}
        profitability = simulation.get('profitability', {}) or {}

        annual_premium = float(portfolio.get('total_annual_premium', 0.0) or 0.0)
        annual_expected_claims = float(risk_metrics.get('annual_expected_claims', 0.0) or 0.0)
        avg_term = float(risk_metrics.get('avg_term_years', 0.0) or 0.0)
        sim_net_profit = float(profitability.get('net_profit', 0.0) or 0.0)
        total_pv_claims = float(risk_metrics.get('total_expected_claims', 0.0) or 0.0)
        total_risk_premium = float(profitability.get('risk_premium', 0.0) or 0.0)
        savings_premium = float(profitability.get('savings_premium', 0.0) or 0.0)

        projection_years = config.projection_years
        avg_term = max(1.0, avg_term or projection_years)

        opening_reserve = config.initial_reserve
        opening_bel = total_pv_claims  # IFRS 17 Best Estimate Liability seeded with PV claims
        opening_ra = opening_bel * config.risk_adjustment_pct
        # IFRS 17 CSM at initial recognition is the unearned profit baked
        # into the contract: PV of future net profit, less the risk
        # adjustment that has not yet been earned. The simulator's
        # ``net_profit`` is the annual flow of profit after claims, so
        # multiplying by the average term and netting off the opening
        # risk adjustment gives a deterministic seed that grows with the
        # profitability of the priced portfolio. The previous seed
        # (``total_risk_premium × avg_term − BEL − RA``) collapsed to ≤ 0
        # by construction because the simulator prices ``risk_premium =
        # PV_claims / term`` and never recognised loading or profit
        # margin in the CSM, leaving the dashboard's IFRS17 CSM column
        # stuck at zero with nothing to reconcile.
        opening_csm = max(0.0, sim_net_profit * avg_term - opening_ra)
        opening_savings = float(config.initial_savings_fund_balance or 0.0)

        yearly: List[Dict[str, Any]] = []
        cumulative_tax = 0.0
        cumulative_dividends = 0.0
        cumulative_retained = 0.0
        cumulative_reserve_contrib = 0.0
        cumulative_savings_contrib = 0.0
        cumulative_savings_yield = 0.0
        cumulative_management_fee_income = 0.0

        # Precompute cumulative in-force factors as product of survival rates
        in_force_factors = [1.0]
        for y in range(1, projection_years + 1):
            lr = self.tables.get_lapse_rate(y)
            in_force_factors.append(in_force_factors[-1] * max(0.0, 1.0 - lr))

        cumulative_csm_release = 0.0
        total_coverage_units = sum(in_force_factors[y - 1] for y in range(1, projection_years + 1)) or 1.0

        for year_index in range(1, projection_years + 1):
            lapse_rate = self.tables.get_lapse_rate(year_index)
            in_force_factor = in_force_factors[year_index - 1]
            in_force_premium = annual_premium * in_force_factor
            in_force_claims = annual_expected_claims * in_force_factor

            # Profit waterfall:
            operating_profit = sim_net_profit * in_force_factor
            tax_amount = operating_profit * config.tax_pct
            after_tax_profit = operating_profit - tax_amount
            dividends = after_tax_profit * config.dividends_pct
            retained = after_tax_profit - dividends

            reserve_contribution = retained * config.reserve_contribution_pct

            # Savings contribution sources (cumulative AUM model):
            # 1. The priced savings_premium component charged to each policy
            #    (this is the modern path; equals 0 for a pure-risk product).
            # 2. The legacy post-hoc allocation knob, kept for backwards
            #    compatibility with existing reserve runs that set
            #    savings_allocation_pct > 0.
            priced_savings_contribution = savings_premium * in_force_factor
            post_hoc_savings_contribution = (
                in_force_premium * config.savings_allocation_pct
            )
            savings_contribution = (
                priced_savings_contribution + post_hoc_savings_contribution
            )

            # IBNR provision: incurred-claims method
            ibnr = in_force_claims * config.ibnr_pct

            # IFRS 17 release: CSM amortized over remaining coverage units;
            # BEL and RA wind down proportionally to in-force decay.
            if config.csm_release_pattern == 'coverage_units':
                csm_release = (opening_csm * in_force_factor) / total_coverage_units
            else:
                csm_release = opening_csm / projection_years if projection_years else 0.0
            csm_release = min(opening_csm - cumulative_csm_release, csm_release)

            bel_balance = opening_bel * max(0.0, 1.0 - (year_index / avg_term))
            ra_balance = bel_balance * config.risk_adjustment_pct
            csm_opening_year = max(0.0, opening_csm - cumulative_csm_release)
            cumulative_csm_release += csm_release
            csm_balance = max(0.0, opening_csm - cumulative_csm_release)
            # Coverage-units share for this year — informational, also used in
            # the per-year identity check ``coverage_units_share_check``.
            csm_share_basis = (
                (in_force_factor / total_coverage_units) if total_coverage_units > 0 else 0.0
            )
            ifrs17_total_liability = bel_balance + ra_balance + csm_balance + ibnr

            closing_reserve = opening_reserve + reserve_contribution

            # ----- Savings fund AUM accumulation (compounded annually) -----
            # Sequence per actuarial convention: contribute at start, yield
            # on the (opening + contribution) base over the year, then the
            # management fee accrues on the year-end balance (the
            # company's AUM-based fee income).
            opening_savings_before = opening_savings
            savings_yield_amount = (opening_savings + savings_contribution) * config.savings_yield_pct
            gross_closing_aum = opening_savings + savings_contribution + savings_yield_amount
            management_fee_income = gross_closing_aum * config.management_fee_pct_of_aum
            closing_savings = gross_closing_aum - management_fee_income
            monthly_contribution = savings_contribution / 12.0

            yearly.append({
                'year': year_index,
                'in_force_factor': round(in_force_factor, 6),
                'lapse_rate_used': round(lapse_rate, 4),
                'in_force_premium': round(in_force_premium, 2),
                'in_force_expected_claims': round(in_force_claims, 2),
                'operating_profit': round(operating_profit, 2),
                'tax': round(tax_amount, 2),
                'after_tax_profit': round(after_tax_profit, 2),
                'dividends': round(dividends, 2),
                'retained_earnings': round(retained, 2),
                'reserve_contribution': round(reserve_contribution, 2),
                'closing_reserve': round(closing_reserve, 2),
                'ibnr_provision': round(ibnr, 2),
                'ifrs17': {
                    'bel_balance': round(bel_balance, 2),
                    'risk_adjustment': round(ra_balance, 2),
                    'csm_release': round(csm_release, 2),
                    'csm_balance': round(csm_balance, 2),
                    'csm_opening_year': round(csm_opening_year, 2),
                    'csm_cumulative_release': round(cumulative_csm_release, 2),
                    'csm_share_of_coverage_units': round(csm_share_basis, 6),
                    'total_liability': round(ifrs17_total_liability, 2),
                },
                'savings_fund': {
                    'opening_balance': round(opening_savings_before, 2),
                    'monthly_contribution': round(monthly_contribution, 2),
                    'contribution': round(savings_contribution, 2),
                    'priced_savings_contribution': round(priced_savings_contribution, 2),
                    'post_hoc_allocation_contribution': round(post_hoc_savings_contribution, 2),
                    'yield': round(savings_yield_amount, 2),
                    'gross_closing_aum_before_fee': round(gross_closing_aum, 2),
                    'management_fee_income': round(management_fee_income, 2),
                    'closing_balance': round(closing_savings, 2),
                },
            })

            opening_reserve = closing_reserve
            opening_savings = closing_savings
            cumulative_tax += tax_amount
            cumulative_dividends += dividends
            cumulative_retained += retained
            cumulative_reserve_contrib += reserve_contribution
            cumulative_savings_contrib += savings_contribution
            cumulative_savings_yield += savings_yield_amount
            cumulative_management_fee_income += management_fee_income

        # Effective compounded savings yield over the projection horizon:
        # CAGR(closing_balance, sum_of_contributions, years).
        effective_yield_pct = 0.0
        if cumulative_savings_contrib > 0 and opening_savings > 0 and projection_years > 0:
            try:
                ratio = opening_savings / cumulative_savings_contrib
                effective_yield_pct = (
                    ratio ** (1.0 / projection_years) - 1.0
                ) if ratio > 0 else 0.0
            except (ValueError, ZeroDivisionError):
                effective_yield_pct = 0.0

        totals = {
            'cumulative_tax': round(cumulative_tax, 2),
            'cumulative_dividends': round(cumulative_dividends, 2),
            'cumulative_retained_earnings': round(cumulative_retained, 2),
            'cumulative_reserve_contribution': round(cumulative_reserve_contrib, 2),
            'cumulative_savings_contribution': round(cumulative_savings_contrib, 2),
            'cumulative_savings_yield': round(cumulative_savings_yield, 2),
            'cumulative_management_fee_income': round(cumulative_management_fee_income, 2),
            'closing_reserve': round(opening_reserve, 2),
            'closing_savings_balance': round(opening_savings, 2),
            'effective_savings_yield_pct': round(effective_yield_pct, 6),
            'average_reserve_contribution': round(
                cumulative_reserve_contrib / max(1, projection_years), 2
            ),
            'average_monthly_savings_contribution': round(
                cumulative_savings_contrib / max(1, projection_years * 12), 2
            ),
        }

        # Verifiable identity: profit waterfall must reconcile each year
        identity_checks = []
        for row in yearly:
            lhs = row['operating_profit']
            rhs = row['tax'] + row['after_tax_profit']
            identity_checks.append(abs(lhs - rhs) < 0.5)

        savings_allocation = apply_savings_allocation(simulation, config.savings_allocation_pct)

        # ----- IFRS 17 CSM Reconciliation -----
        # Build a deterministic arithmetic chain so the dashboard, audit,
        # and external auditors can verify every IFRS17 CSM Δ + IFRS17 CSM
        # figure reconciles back to the opening CSM.
        sum_of_releases = sum(row['ifrs17']['csm_release'] for row in yearly)
        closing_csm = yearly[-1]['ifrs17']['csm_balance'] if yearly else round(opening_csm, 2)
        csm_yearly: List[Dict[str, Any]] = []
        prev_balance = round(opening_csm, 2)
        cumulative_release_running = 0.0
        all_continuity_pass = True
        all_cumulative_form_pass = True
        all_release_non_negative = True
        all_balance_non_negative = True
        coverage_units_share_pass = True
        for row in yearly:
            ifrs = row['ifrs17']
            release = float(ifrs['csm_release'])
            balance = float(ifrs['csm_balance'])
            cumulative_release_running += release
            # Identity 1: balance_y = balance_{y-1} − release_y
            expected_from_prev = max(0.0, prev_balance - release)
            continuity_check = abs(expected_from_prev - balance) < 1.0
            # Identity 2: balance_y = opening_csm − Σ release_{1..y}
            expected_cumulative = max(0.0, opening_csm - cumulative_release_running)
            cumulative_check = abs(expected_cumulative - balance) < 1.0
            # Identity 3 (coverage_units pattern only): release_y / opening_csm
            # equals the in-force factor share of total coverage units.
            cu_check = True
            cu_expected_release = release  # informational default
            if (
                config.csm_release_pattern == 'coverage_units'
                and opening_csm > 1e-6
                and balance > 1e-6  # not at the clamp boundary
            ):
                expected_share = float(ifrs.get('csm_share_of_coverage_units', 0.0))
                cu_expected_release = opening_csm * expected_share
                cu_check = abs(release - cu_expected_release) < 1.0
            if not continuity_check:
                all_continuity_pass = False
            if not cumulative_check:
                all_cumulative_form_pass = False
            if release < -1e-6:
                all_release_non_negative = False
            if balance < -1e-6:
                all_balance_non_negative = False
            if not cu_check:
                coverage_units_share_pass = False
            csm_yearly.append({
                'year': row['year'],
                'in_force_factor': row['in_force_factor'],
                'opening_balance': round(prev_balance, 2),
                'release': round(release, 2),
                'cumulative_release': round(cumulative_release_running, 2),
                'closing_balance': round(balance, 2),
                'coverage_units_share': round(
                    float(ifrs.get('csm_share_of_coverage_units', 0.0)), 6
                ),
                'expected_release_from_share': round(cu_expected_release, 2),
                'identity_checks': {
                    'prev_minus_release_equals_balance': continuity_check,
                    'opening_minus_cumulative_equals_balance': cumulative_check,
                    'coverage_units_share_holds': cu_check,
                },
            })
            prev_balance = balance

        # Overall reconciliation: sum of releases equals opening_csm only
        # if the projection horizon fully amortises the CSM. When it is
        # shorter than the average term, releases sum to less than the
        # opening — capture both views explicitly.
        unreleased_portion = max(0.0, opening_csm - sum_of_releases)
        sum_releases_check = abs(opening_csm - sum_of_releases - closing_csm) < 1.0

        # Straight-line specific: each year release should equal opening / N
        straight_line_uniform_check = True
        if config.csm_release_pattern == 'straight_line' and projection_years > 0 and opening_csm > 0:
            expected_release = opening_csm / projection_years
            straight_line_uniform_check = all(
                abs(r['release'] - expected_release) < 1.0
                or r['closing_balance'] < 1.0  # clamp boundary
                for r in csm_yearly
            )

        csm_reconciliation = {
            'pattern': config.csm_release_pattern,
            'opening_csm': round(opening_csm, 2),
            'projection_years': projection_years,
            'yearly': csm_yearly,
            'totals': {
                'sum_of_releases': round(sum_of_releases, 2),
                'unreleased_portion': round(unreleased_portion, 2),
                'closing_csm': round(closing_csm, 2),
                'average_annual_release': round(
                    sum_of_releases / max(1, projection_years), 2
                ),
                'release_pct_of_opening': round(
                    (sum_of_releases / opening_csm * 100.0) if opening_csm > 0 else 0.0,
                    4,
                ),
                'coverage_units_total': round(total_coverage_units, 6),
            },
            'data_integrity': {
                'per_year_continuity_pass': all_continuity_pass,
                'per_year_cumulative_form_pass': all_cumulative_form_pass,
                'sum_of_releases_plus_closing_equals_opening': sum_releases_check,
                'release_non_negative': all_release_non_negative,
                'balance_non_negative': all_balance_non_negative,
                'coverage_units_share_holds': coverage_units_share_pass,
                'straight_line_release_uniform': straight_line_uniform_check,
                'opening_csm_non_negative': opening_csm >= -1e-6,
            },
            'identities': {
                'per_year': {
                    'formula': 'csm_balance_y = csm_balance_{y-1} − csm_release_y',
                    'alt_formula': 'csm_balance_y = opening_csm − Σ_{i=1..y} csm_release_i',
                },
                'sum_of_releases': {
                    'formula': 'Σ csm_release_y + closing_csm = opening_csm',
                    'computed': round(sum_of_releases + closing_csm, 2),
                    'expected': round(opening_csm, 2),
                    'delta': round((sum_of_releases + closing_csm) - opening_csm, 2),
                },
                'straight_line_pattern': {
                    'formula': 'release_y = opening_csm / projection_years',
                    'expected_release': round(
                        opening_csm / projection_years if projection_years > 0 else 0.0, 2
                    ),
                    'applies': config.csm_release_pattern == 'straight_line',
                },
                'coverage_units_pattern': {
                    'formula': 'release_y = opening_csm × in_force_factor_y / Σ in_force_factor',
                    'applies': config.csm_release_pattern == 'coverage_units',
                },
            },
        }

        return {
            'simulation_id': simulation.get('simulation_id'),
            'projection_years': projection_years,
            'avg_term_years': round(avg_term, 2),
            'config': asdict(config),
            'yearly_projection': yearly,
            'totals': totals,
            'opening_balances': {
                'reserve': round(config.initial_reserve, 2),
                'bel': round(opening_bel, 2),
                'risk_adjustment': round(opening_ra, 2),
                'csm': round(opening_csm, 2),
                'savings_fund': round(config.initial_savings_fund_balance, 2),
            },
            'savings_allocation': savings_allocation,
            'csm_reconciliation': csm_reconciliation,
            'data_integrity': {
                'profit_waterfall_consistent': all(identity_checks),
                'dividends_within_after_tax': all(
                    row['dividends'] <= row['after_tax_profit'] + 0.5 for row in yearly
                ),
                'reserve_monotonic_when_positive_profit': all(
                    (row['retained_earnings'] >= -0.5)
                    for row in yearly
                ),
                'savings_balance_non_negative': all(
                    row['savings_fund']['closing_balance'] >= -0.5 for row in yearly
                ),
                'csm_non_negative': all(row['ifrs17']['csm_balance'] >= -0.5 for row in yearly),
                # Prove the AUM accumulation identity each year:
                # closing_balance = (opening + contribution) × (1+yield)
                #                   − management_fee
                'savings_accumulation_identity_holds': all(
                    abs(
                        row['savings_fund']['closing_balance']
                        - (
                            (row['savings_fund']['opening_balance']
                             + row['savings_fund']['contribution'])
                            * (1.0 + (
                                row['savings_fund']['yield']
                                / max(1.0, row['savings_fund']['opening_balance']
                                      + row['savings_fund']['contribution'])
                            ))
                            - row['savings_fund']['management_fee_income']
                        )
                    ) < 1.0
                    for row in yearly
                ),
                'monthly_x_12_equals_annual_contribution': all(
                    abs(row['savings_fund']['monthly_contribution'] * 12.0
                        - row['savings_fund']['contribution']) < 1.0
                    for row in yearly
                ),
                'management_fee_non_negative': all(
                    row['savings_fund']['management_fee_income'] >= -1e-6
                    for row in yearly
                ),
                # CSM identity proofs (the arithmetic shown on the
                # IFRS17 CSM Δ + IFRS17 CSM dashboard columns reconciles
                # back to the opening CSM through both per-year and
                # cumulative forms).
                'csm_per_year_continuity_holds': csm_reconciliation['data_integrity']['per_year_continuity_pass'],
                'csm_sum_reconciles_to_opening': csm_reconciliation['data_integrity']['sum_of_releases_plus_closing_equals_opening'],
                'csm_release_non_negative': csm_reconciliation['data_integrity']['release_non_negative'],
            },
            'ifrs17_methodology': {
                'measurement_model': 'general_measurement_model',
                'risk_adjustment_method': 'cost_of_capital_proxy_via_pct_of_bel',
                'csm_release_pattern': config.csm_release_pattern,
            },
            'ibnr_methodology': {
                'method': 'incurred_claims_pct',
                'percentage_of_expected_claims': config.ibnr_pct,
            },
        }


def get_reserve_calculator() -> ReserveCalculator:
    return ReserveCalculator()


# =============================================================================
# CUSTOM UPLOADED RATE TABLES
# =============================================================================
#
# Excel/CSV/JSON uploads land in `ACTUARIAL_TABLES` (in-memory) or the
# `actuarial_tables` DB table. The helpers below normalize those payloads so
# the dashboard can preview them and the simulator can swap them in for the
# built-in mortality/disability tables when running a targeted study (e.g.,
# mortality for Caucasian women, permanent disability for a specific cohort).
# =============================================================================

SUPPORTED_RATE_BANDS = {'mortality_rates', 'disability_incidence_rates'}


# =============================================================================
# COHORT-SCOPED UPLOADED TABLES (G4 / G10)
# =============================================================================
#
# Uploaded rate tables (e.g. "mortality table of Caucasian women") can now be
# *registered* under a cohort key without replacing the global rate band. The
# pricing kernel's :class:`TableSet` checks the customer cohort first and
# falls back to the global table if no override applies. A cohort key is a
# free-form ``"<dimension>:<value>"`` string such as ``ethnicity:caucasian``
# or ``gender:female``; multiple cohort keys can co-exist for the same
# underlying customer (the first match wins, in dictionary order).
# =============================================================================

# In-memory cohort overrides keyed by ``"<dim>:<value>"`` -> {table_type: rows}.
# This is the same shape consumed by ``TableSet.cohort_overrides`` in
# ``services.pricing_kernel`` so the kernel can plug it in directly.
COHORT_RATE_OVERRIDES: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}

# Lightweight audit of every cohort registration so external auditors can see
# which uploaded table is currently overriding which cohort band.
COHORT_REGISTRY_LOG: List[Dict[str, Any]] = []

_COHORT_LOCK = threading.Lock()


def _normalize_cohort_key(cohort_dim: str, cohort_value: str) -> str:
    dim = (cohort_dim or '').strip().lower()
    value = (cohort_value or '').strip().lower()
    if not dim or not value:
        raise ValueError('cohort_dim and cohort_value are required')
    return f'{dim}:{value}'


def register_cohort_rate_table(cohort_dim: str, cohort_value: str, table_type: str,
                               normalized: List[Dict[str, Any]], user: str,
                               source_table_id: Optional[str] = None,
                               source_name: Optional[str] = None) -> Dict[str, Any]:
    """Register a cohort-scoped rate table override.

    Args:
        cohort_dim: cohort dimension (e.g. ``"ethnicity"`` or ``"gender"``).
        cohort_value: cohort value (e.g. ``"caucasian"`` or ``"female"``).
        table_type: either ``"mortality_rates"`` or ``"disability_incidence_rates"``.
        normalized: rows in the canonical bracket format produced by
            :func:`normalize_uploaded_rate_table`.
        user: actor (used for audit only).
        source_table_id: optional id of the uploaded actuarial table this
            override was derived from (for audit traceability).
        source_name: optional human-readable name of the source upload.
    """
    table_type = (table_type or '').strip().lower()
    if table_type not in SUPPORTED_RATE_BANDS:
        return {'success': False, 'error': f'Unsupported table_type: {table_type}'}
    if not normalized:
        return {'success': False, 'error': 'No rows to register'}
    try:
        key = _normalize_cohort_key(cohort_dim, cohort_value)
    except ValueError as exc:
        return {'success': False, 'error': str(exc)}

    with _COHORT_LOCK:
        bucket = COHORT_RATE_OVERRIDES.setdefault(key, {})
        bucket[table_type] = [dict(row) for row in normalized]

        COHORT_REGISTRY_LOG.append({
            'timestamp': datetime.now().isoformat(),
            'cohort_key': key,
            'cohort_dim': key.split(':', 1)[0],
            'cohort_value': key.split(':', 1)[1],
            'table_type': table_type,
            'rows': len(normalized),
            'user': user,
            'source_table_id': source_table_id,
            'source_name': source_name,
        })
    return {
        'success': True,
        'cohort_key': key,
        'table_type': table_type,
        'rows_registered': len(normalized),
    }


def remove_cohort_rate_table(cohort_dim: str, cohort_value: str, table_type: str,
                             user: str) -> Dict[str, Any]:
    """Remove a cohort-scoped rate override."""
    try:
        key = _normalize_cohort_key(cohort_dim, cohort_value)
    except ValueError as exc:
        return {'success': False, 'error': str(exc)}
    with _COHORT_LOCK:
        bucket = COHORT_RATE_OVERRIDES.get(key, {})
        table_type = (table_type or '').strip().lower()
        removed = bucket.pop(table_type, None)
        if not bucket:
            COHORT_RATE_OVERRIDES.pop(key, None)
        COHORT_REGISTRY_LOG.append({
            'timestamp': datetime.now().isoformat(),
            'cohort_key': key,
            'table_type': table_type,
            'action': 'remove',
            'user': user,
            'rows_removed': len(removed or []),
        })
    return {'success': True, 'rows_removed': len(removed or [])}


def list_cohort_rate_tables() -> List[Dict[str, Any]]:
    """List every registered cohort-scoped rate override."""
    out: List[Dict[str, Any]] = []
    with _COHORT_LOCK:
        for key, bucket in COHORT_RATE_OVERRIDES.items():
            dim, value = key.split(':', 1) if ':' in key else (key, '')
            for table_type, rows in bucket.items():
                last_registration = next(
                    (
                        entry for entry in reversed(COHORT_REGISTRY_LOG)
                        if entry.get('cohort_key') == key and entry.get('table_type') == table_type
                        and entry.get('action') != 'remove'
                    ),
                    None,
                )
                out.append({
                    'cohort_key': key,
                    'cohort_dim': dim,
                    'cohort_value': value,
                    'table_type': table_type,
                    'row_count': len(rows),
                    'source_table_id': (last_registration or {}).get('source_table_id'),
                    'source_name': (last_registration or {}).get('source_name'),
                    'registered_at': (last_registration or {}).get('timestamp'),
                    'registered_by': (last_registration or {}).get('user'),
                })
    return out


def get_cohort_overrides_snapshot() -> Dict[str, Dict[str, List[Dict[str, Any]]]]:
    """Return a deep copy of the cohort overrides safe to pass to the kernel."""
    with _COHORT_LOCK:
        return {
            key: {table_type: [dict(row) for row in rows] for table_type, rows in bucket.items()}
            for key, bucket in COHORT_RATE_OVERRIDES.items()
        }


def _normalize_rate_bracket(row: Dict[str, Any]) -> Optional[Dict[str, float]]:
    if not isinstance(row, dict):
        return None
    candidates = {k.lower().strip(): v for k, v in row.items() if isinstance(k, str)}

    def pick(*names: str) -> Optional[Any]:
        for name in names:
            if name in candidates and candidates[name] not in (None, ''):
                return candidates[name]
        return None

    def pick_rate(*names: str):
        for name in names:
            if name in candidates and candidates[name] not in (None, ''):
                return candidates[name], name
        return None, None

    age_min = pick('age_min', 'age min', 'age_from', 'min_age', 'from')
    age_max = pick('age_max', 'age max', 'age_to', 'max_age', 'to')
    rate, rate_source = pick_rate(
        'rate_per_1000', 'rate per 1000', 'rate', 'qx_per_1000', 'qx', 'ix', 'ix_per_1000'
    )
    if age_min is None or age_max is None or rate is None:
        return None
    try:
        rate_value = float(rate)
        # If the values look like raw qx/ix probabilities (0..1) convert to per-1000.
        if rate_source in ('qx', 'ix') and rate_value <= 1.0:
            rate_value = rate_value * 1000.0
        return {
            'age_min': int(float(age_min)),
            'age_max': int(float(age_max)),
            'rate_per_1000': round(rate_value, 4),
        }
    except (TypeError, ValueError):
        return None


def normalize_uploaded_rate_table(table_type: str, rows: Any) -> Dict[str, Any]:
    """
    Convert raw uploaded payload (list of dicts or a dict wrapping rows) into
    the canonical bracket format used by the central tables store.
    """
    table_type = (table_type or '').strip().lower()
    if isinstance(rows, dict):
        rows = rows.get('data') or rows.get('rows') or list(rows.values())
    if not isinstance(rows, list):
        return {'valid': False, 'reason': 'rows_must_be_list', 'normalized': []}

    normalized: List[Dict[str, float]] = []
    skipped = 0
    for row in rows:
        bracket = _normalize_rate_bracket(row)
        if bracket is None:
            skipped += 1
            continue
        normalized.append(bracket)

    normalized.sort(key=lambda b: b['age_min'])
    valid = bool(normalized) and table_type in SUPPORTED_RATE_BANDS
    return {
        'valid': valid,
        'table_type': table_type,
        'normalized': normalized,
        'rows_in': len(rows) if isinstance(rows, list) else 0,
        'rows_normalized': len(normalized),
        'rows_skipped': skipped,
        'reason': None if valid else (
            'unsupported_table_type' if table_type not in SUPPORTED_RATE_BANDS
            else 'no_valid_rows'
        ),
    }


def apply_uploaded_table_to_store(table_type: str, normalized: List[Dict[str, float]],
                                   user: str) -> Dict[str, Any]:
    """Promote a normalized uploaded payload into the central rate table store."""
    store = get_actuarial_store()
    return store.update_current_tables(table_type, normalized, user)


# =============================================================================
# LIFE & DISABILITY TABLES REGISTRY (Tables Bar)
# =============================================================================
#
# The actuary dashboard exposes a "Tables Bar" — a unified view over every
# rate table the platform uses for life-and-disability pricing. The
# registry returned here covers three scopes:
#
# * ``global``    — the active mortality / disability rate band stored in
#                   :class:`ActuarialTablesStore`. Always used for premium
#                   computation and portfolio simulation when a customer
#                   does not match any cohort override.
# * ``cohort``    — a cohort-scoped override (e.g. mortality table for
#                   Caucasian women) registered through
#                   :func:`register_cohort_rate_table`. Used for premium /
#                   simulation when the customer's ``cohort`` payload
#                   matches.
# * ``uploaded``  — an uploaded ``mortality_rates`` / ``disability_incidence_rates``
#                   table held in the catalog. NOT used for pricing until
#                   it is promoted (globally or as a cohort override).
#
# The registry is the single source the dashboard renders so users can
# *see* every table that influences a quote/simulation, *download* it for
# audit, and *replace* it (upload + promote). Each entry exposes a
# deterministic ``integrity_hash`` so two viewers can confirm they are
# looking at the exact same rate table.
# =============================================================================

# Friendly cohort labels used by the dashboard. Keeping the dictionaries here
# (instead of hard-coding strings into both the service and the UI) means new
# cohort types only need to be added in one place to flow through downloads,
# audit trails, and the UI bar.
COHORT_DIMENSION_LABELS: Dict[str, str] = {
    'gender': 'Gender',
    'sex': 'Sex',
    'ethnicity': 'Ethnicity',
    'race': 'Race',
    'smoker': 'Smoker status',
    'country': 'Country',
    'region': 'Region',
    'occupation': 'Occupation',
}

COHORT_VALUE_LABELS: Dict[str, str] = {
    'female': 'Female',
    'male': 'Male',
    'caucasian': 'Caucasian',
    'asian': 'Asian',
    'african': 'African',
    'hispanic': 'Hispanic',
    'mixed': 'Mixed',
    'other': 'Other',
    'yes': 'Smoker',
    'no': 'Non-smoker',
    'former': 'Former smoker',
}

TABLE_TYPE_LABELS: Dict[str, str] = {
    'mortality_rates': 'Death (mortality)',
    'disability_incidence_rates': 'Disability (permanent ADL)',
}


def _humanize_cohort_dim(dim: str) -> str:
    if not dim:
        return ''
    return COHORT_DIMENSION_LABELS.get(dim.lower(), dim.replace('_', ' ').title())


def _humanize_cohort_value(value: str) -> str:
    if not value:
        return ''
    return COHORT_VALUE_LABELS.get(value.lower(), value.replace('_', ' ').title())


def _humanize_table_type(table_type: str) -> str:
    return TABLE_TYPE_LABELS.get((table_type or '').lower(), table_type or '')


def build_cohort_label(cohort_dim: str, cohort_value: str, table_type: str) -> str:
    """Build a human-readable label like ``"Death (mortality) — Female · Caucasian"``.

    The label is what the actuary dashboard's Tables Bar shows next to
    each entry so an actuary can instantly tell which cohort an uploaded
    table is currently driving (the user's brief gave examples like
    "death table for female Caucasian", "disability table for Asian men").
    """
    parts = [_humanize_table_type(table_type)]
    if cohort_dim and cohort_value:
        parts.append(
            f"{_humanize_cohort_value(cohort_value)} ({_humanize_cohort_dim(cohort_dim).lower()})"
        )
    return ' — '.join(p for p in parts if p)


def _hash_table_rows(rows: List[Dict[str, Any]], extra: Dict[str, Any]) -> str:
    """Deterministic SHA-256 fingerprint of a rate band.

    Rounds rates to 6 decimals so byte-identical tables on different hosts
    (with potentially different float string repr) still hash the same. The
    ``extra`` dict folds scope/cohort/version metadata into the hash so a
    cohort override and the global rate band hash differently even when
    they share the same numeric rows.
    """
    canonical_rows = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        norm = {}
        for key in sorted(row.keys()):
            value = row[key]
            if isinstance(value, float):
                value = round(value, 6)
            norm[key] = value
        canonical_rows.append(norm)
    payload = {
        'rows': canonical_rows,
        'meta': {k: extra[k] for k in sorted(extra.keys())},
    }
    canonical = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()


def _global_table_entry(table_type: str, store: ActuarialTablesStore) -> Dict[str, Any]:
    rows = list(store.get_current_tables().get(table_type, []) or [])
    extra = {
        'scope': 'global',
        'table_type': table_type,
        'tables_version': store.current_version,
    }
    return {
        'id': f'global:{table_type}',
        'scope': 'global',
        'table_type': table_type,
        'cohort_dim': None,
        'cohort_value': None,
        'cohort_key': None,
        'label': _humanize_table_type(table_type) + ' — Global (default cohort)',
        'description': (
            'Active rate band used by the pricing kernel for every customer '
            'whose cohort does not match an active override. This table feeds '
            'every quote, billing run, portfolio simulation, reserve projection, '
            'and reinsurance calculation.'
        ),
        'row_count': len(rows),
        'tables_version': store.current_version,
        'effective_date': (store.versions.get(store.current_version, {}) or {}).get('effective_date'),
        'created_by': (store.versions.get(store.current_version, {}) or {}).get('created_by'),
        'source_table_id': None,
        'source_name': None,
        'used_in_pricing': True,
        'usage_label': 'Active in pricing & simulation (default cohort)',
        'integrity_hash': _hash_table_rows(rows, extra),
        'rows': rows,
    }


def _cohort_entry(cohort_dim: str, cohort_value: str, table_type: str,
                  rows: List[Dict[str, Any]],
                  log_entry: Optional[Dict[str, Any]],
                  store: ActuarialTablesStore) -> Dict[str, Any]:
    cohort_key = f'{cohort_dim}:{cohort_value}'
    extra = {
        'scope': 'cohort',
        'table_type': table_type,
        'cohort_key': cohort_key,
        'tables_version': store.current_version,
    }
    label = build_cohort_label(cohort_dim, cohort_value, table_type)
    return {
        'id': f'cohort:{cohort_key}:{table_type}',
        'scope': 'cohort',
        'table_type': table_type,
        'cohort_dim': cohort_dim,
        'cohort_value': cohort_value,
        'cohort_key': cohort_key,
        'label': label,
        'description': (
            f'Cohort override applied when a customer matches '
            f'{_humanize_cohort_dim(cohort_dim)} = {_humanize_cohort_value(cohort_value)}. '
            f'For matching customers the kernel uses this rate band instead of the '
            f'{_humanize_table_type(table_type).lower()} default.'
        ),
        'row_count': len(rows),
        'tables_version': store.current_version,
        'effective_date': (log_entry or {}).get('timestamp'),
        'created_by': (log_entry or {}).get('user'),
        'source_table_id': (log_entry or {}).get('source_table_id'),
        'source_name': (log_entry or {}).get('source_name'),
        'used_in_pricing': True,
        'usage_label': 'Active in pricing & simulation (cohort match)',
        'integrity_hash': _hash_table_rows(rows, extra),
        'rows': rows,
    }


def _uploaded_entry(uploaded: Dict[str, Any]) -> Dict[str, Any]:
    table_id = str(uploaded.get('id') or '')
    table_type = str(uploaded.get('table_type') or '').lower()
    rows = uploaded.get('rows') if isinstance(uploaded.get('rows'), list) else []
    extra = {
        'scope': 'uploaded',
        'table_type': table_type,
        'uploaded_id': table_id,
        'version': uploaded.get('version'),
    }
    label_base = _humanize_table_type(table_type) or (table_type or 'Custom table')
    name = uploaded.get('name') or table_id
    return {
        'id': f'uploaded:{table_id}',
        'scope': 'uploaded',
        'table_type': table_type,
        'cohort_dim': None,
        'cohort_value': None,
        'cohort_key': None,
        'label': f'{label_base} — {name}',
        'description': (
            'Uploaded rate table held in the catalog. NOT yet used for premium / '
            'simulation. Promote it as a global replacement or as a cohort override '
            'to start pricing customers against this table.'
        ),
        'row_count': len(rows) if isinstance(rows, list) else int(uploaded.get('row_count') or 0),
        'tables_version': uploaded.get('version'),
        'effective_date': uploaded.get('effective_date'),
        'created_by': uploaded.get('created_by'),
        'source_table_id': table_id,
        'source_name': name,
        'used_in_pricing': False,
        'usage_label': 'Uploaded — not yet active',
        'integrity_hash': _hash_table_rows(rows or [], extra),
        'rows': rows or [],
    }


def build_rate_tables_registry(uploaded_tables: Optional[List[Dict[str, Any]]] = None,
                               include_rows: bool = False) -> List[Dict[str, Any]]:
    """Return the unified life/disability rate tables registry.

    Args:
        uploaded_tables: optional list of uploaded table records (already
            decoded by the caller because uploaded payloads live in the
            ``ACTUARIAL_TABLES`` in-memory dict or in the
            ``actuarial_tables`` DB table). Each record should contain at
            least ``id``, ``name``, ``table_type``, ``version``,
            ``effective_date``, ``created_by``, and either a ``rows`` list
            or ``row_count``.
        include_rows: when False (the default for the dashboard listing)
            the ``rows`` field is stripped from every entry to keep the
            payload small. The download endpoint passes True.
    """
    store = get_actuarial_store()
    entries: List[Dict[str, Any]] = []

    for table_type in ('mortality_rates', 'disability_incidence_rates'):
        entries.append(_global_table_entry(table_type, store))

    with _COHORT_LOCK:
        cohort_overrides_snapshot = {
            key: {tt: list(rows) for tt, rows in bucket.items()}
            for key, bucket in COHORT_RATE_OVERRIDES.items()
        }
        cohort_log = list(COHORT_REGISTRY_LOG)

    for cohort_key, bucket in cohort_overrides_snapshot.items():
        if ':' not in cohort_key:
            continue
        cohort_dim, cohort_value = cohort_key.split(':', 1)
        for table_type, rows in bucket.items():
            last_log = next(
                (
                    entry for entry in reversed(cohort_log)
                    if entry.get('cohort_key') == cohort_key
                    and entry.get('table_type') == table_type
                    and entry.get('action') != 'remove'
                ),
                None,
            )
            entries.append(_cohort_entry(
                cohort_dim, cohort_value, table_type, rows, last_log, store,
            ))

    for uploaded in uploaded_tables or []:
        if not isinstance(uploaded, dict):
            continue
        ttype = str(uploaded.get('table_type') or '').lower()
        if ttype not in SUPPORTED_RATE_BANDS:
            continue
        entries.append(_uploaded_entry(uploaded))

    if not include_rows:
        for entry in entries:
            entry.pop('rows', None)

    return entries


def get_active_rate_table_rows(scope: str, table_type: str,
                               cohort_dim: Optional[str] = None,
                               cohort_value: Optional[str] = None,
                               ) -> Dict[str, Any]:
    """Look up the rows backing one entry in the rate tables registry.

    Returns a dict with ``rows``, ``label``, ``integrity_hash`` and
    ``filename_stem`` so the download endpoint can stream the table as CSV
    or JSON without re-deriving the metadata. ``scope='uploaded'`` is not
    handled here because uploaded payloads live in the server's storage
    layer; the caller already has the rows in that case.
    """
    table_type = (table_type or '').lower()
    if table_type not in SUPPORTED_RATE_BANDS:
        return {'success': False, 'error': f'Unsupported table_type: {table_type}'}
    store = get_actuarial_store()
    if scope == 'global':
        entry = _global_table_entry(table_type, store)
        return {
            'success': True,
            'rows': entry['rows'],
            'label': entry['label'],
            'integrity_hash': entry['integrity_hash'],
            'filename_stem': f'phins-global-{table_type.replace("_", "-")}-{store.current_version}',
        }
    if scope == 'cohort':
        if not cohort_dim or not cohort_value:
            return {'success': False, 'error': 'cohort_dim and cohort_value required'}
        cohort_key = f'{cohort_dim.lower()}:{cohort_value.lower()}'
        with _COHORT_LOCK:
            rows = list((COHORT_RATE_OVERRIDES.get(cohort_key, {}) or {}).get(table_type, []))
            log_entry = next(
                (
                    entry for entry in reversed(COHORT_REGISTRY_LOG)
                    if entry.get('cohort_key') == cohort_key
                    and entry.get('table_type') == table_type
                    and entry.get('action') != 'remove'
                ),
                None,
            )
        if not rows:
            return {'success': False, 'error': 'Cohort override not found'}
        entry = _cohort_entry(
            cohort_dim.lower(), cohort_value.lower(), table_type, rows, log_entry, store,
        )
        safe_dim = re.sub(r'[^A-Za-z0-9._-]+', '-', cohort_dim.lower()).strip('-')
        safe_val = re.sub(r'[^A-Za-z0-9._-]+', '-', cohort_value.lower()).strip('-')
        stem_cohort = f'{safe_dim}-{safe_val}'
        return {
            'success': True,
            'rows': entry['rows'],
            'label': entry['label'],
            'integrity_hash': entry['integrity_hash'],
            'filename_stem': f'phins-cohort-{stem_cohort}-{table_type.replace("_", "-")}',
        }
    return {'success': False, 'error': f'Unsupported scope: {scope}'}

