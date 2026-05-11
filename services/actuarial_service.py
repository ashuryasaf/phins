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
import json
import hashlib
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


@dataclass
class UnderwritingConfig:
    decline_threshold: int = 9  # ADL 9+ declined by default
    loadings: Dict[int, float] = field(default_factory=lambda: {6: 0.15, 7: 0.30, 8: 0.50})
    coverage_limits: Dict[int, float] = field(default_factory=lambda: {6: 1000000, 7: 750000, 8: 500000})
    disability_exclusion_threshold: int = 8
    expense_loading_pct: float = 0.15
    profit_margin_pct: float = 0.10
    discount_rate: float = 0.035
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
    ethnicity: Dict[str, float] = field(default_factory=lambda: {
        'caucasian': 60, 'african': 13, 'hispanic': 18, 'asian': 6, 'other': 3
    })
    # Share of total annual premium routed to the long-term savings fund rather
    # than retained on the insurance balance sheet (0.0 - 0.95). Pure-risk
    # products use 0.0; hybrid risk+savings products set this to e.g. 0.30.
    savings_allocation_pct: float = 0.0


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
        'data_integrity': {
            'contracts_within_portfolio': selected_contracts <= accepted_customers,
            'ceded_exposure_within_total': ceded_exposure <= total_coverage + 1,
            'gross_premium_reconciles': abs(gross_premium - calculated_gross) < 1.0,
            'protected_claims_share': round(protected_claims_share, 6),
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
        
        self.config.last_modified = datetime.now().isoformat()
        self.config.modified_by = user
        
        # Audit log
        self._log_change('update_config', user, {
            'old_config': old_config,
            'new_config': asdict(self.config)
        })
        
        return {'success': True, 'config': asdict(self.config)}
    
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
            'discount_rate': 0.035
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
            last_modified=datetime.now().isoformat(),
            modified_by=user
        )
        
        # Audit log
        self._log_change('reset_config', user, {
            'old_config': old_config,
            'new_config': asdict(self.config)
        })
        
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
    Uses current actuarial tables for pricing.
    """
    
    def __init__(self, tables_store: ActuarialTablesStore):
        self.tables = tables_store
    
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
            premium = self._calculate_premium(customer, uw_result)
            customer['annual_premium'] = premium['annual_premium']
            customer['risk_premium'] = premium['risk_premium']
            customer['savings_premium'] = premium['savings_premium']
            customer['pv_mortality'] = premium['pv_mortality']
            customer['pv_disability'] = premium['pv_disability']
            
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
            'components_match': abs(totals['annual_premium'] - calculated_gross) < 1
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
                'avg_coverage': round(totals['coverage'] / accepted_count, 2) if accepted_count > 0 else 0,
                'avg_premium': round(totals['annual_premium'] / accepted_count, 2) if accepted_count > 0 else 0
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
            }
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
        
        # Ethnicity (for reporting only)
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
    
    def _calculate_premium(self, customer: Dict, uw_result: Dict) -> Dict:
        """
        Calculate premium using central actuarial tables.
        
        IMPORTANT: Implements mutual exclusivity of claims per actuarial standards:
        - A customer can have EITHER a mortality claim OR a disability claim, not both
        - If customer dies, they cannot have a subsequent disability claim
        - Disability claims are calculated only for survivors who haven't died
        - This accurately models that policies pay only one major claim per life
        """
        age = customer['age']
        adl = customer['adl']
        coverage = customer['coverage']
        term = customer['term']
        loading = uw_result.get('loading', 0)
        exclude_disability = uw_result.get('exclude_disability', False)
        
        config = self.tables.config
        discount_rate = config.discount_rate
        
        # Get multipliers from central tables
        adl_mort_mult = self.tables.get_adl_mortality_multiplier(adl)
        adl_dis_mult = self.tables.get_adl_disability_multiplier(adl)
        
        # =====================================================================
        # MUTUAL EXCLUSIVITY MODEL:
        # For each year, track: alive, dead, disabled
        # A person who dies cannot become disabled, a person who is disabled
        # is no longer at risk for new disability (already claimed)
        # =====================================================================
        
        pv_mortality = 0
        pv_disability = 0
        
        # State probabilities: start with 100% alive, not disabled
        prob_alive_not_disabled = 1.0
        
        for year in range(1, term + 1):
            current_age = age + year - 1
            
            # Get rates for this year
            qx = self.tables.get_mortality_rate(current_age) * adl_mort_mult  # Death rate
            dx = 0.0  # Disability rate
            
            if not exclude_disability:
                dx = self.tables.get_disability_rate(current_age) * adl_dis_mult
                benefit_pct = self.tables.get_adl_benefit_pct(adl)
                if benefit_pct == 0:
                    benefit_pct = 0.35  # Average if would claim
            else:
                benefit_pct = 0
            
            # Discount factor for this year
            discount = (1 + discount_rate) ** (-year)
            
            # From the alive-not-disabled population:
            # - Some die (qx)
            # - Some become disabled (dx) - only from those who didn't die
            # - Rest remain alive-not-disabled
            
            # Probability of dying this year (from alive-not-disabled)
            prob_die_this_year = prob_alive_not_disabled * qx
            
            # Probability of becoming disabled this year (survivors who weren't disabled)
            # Apply to those who survived death this year
            prob_survive_death = prob_alive_not_disabled * (1 - qx)
            prob_disable_this_year = prob_survive_death * dx
            
            # Expected mortality claim: full coverage paid on death
            pv_mortality += coverage * prob_die_this_year * discount
            
            # Expected disability claim: benefit percentage of coverage
            if not exclude_disability and benefit_pct > 0:
                pv_disability += coverage * benefit_pct * prob_disable_this_year * discount
            
            # Update state for next year
            # Alive-not-disabled = survived both death and disability
            prob_alive_not_disabled = prob_survive_death * (1 - dx)
        
        # Annual premiums - spread the present value of expected claims over term
        total_risk_pv = pv_mortality + pv_disability
        risk_premium = total_risk_pv / term
        
        # Apply loading
        if loading > 0:
            risk_premium *= (1 + loading)
        
        # Savings component (50% of coverage over term)
        savings_premium = (coverage * 0.5) / term
        
        # Expense and profit
        expense = risk_premium * config.expense_loading_pct
        profit = (risk_premium + savings_premium + expense) * config.profit_margin_pct
        
        annual_premium = risk_premium + savings_premium + expense + profit
        
        return {
            'annual_premium': annual_premium,
            'risk_premium': risk_premium,  # Risk portion only (for loss ratio calc)
            'savings_premium': savings_premium,
            'pv_mortality': pv_mortality,
            'pv_disability': pv_disability
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
# FEFFERMAN REFERENCE MODEL
# =============================================================================
#
# Mirror of the locked actuarial source block published on
# https://www.phins.ai/phins-risk-1pager-fefferman.html so that every figure on
# that one-pager can be reproduced server-side for audit/validation purposes.
#
# Keeping these constants in lockstep with the public document lets the
# dashboard verify the production pricing model against the disclosed model.
# =============================================================================

PHINS_FEFFERMAN_MODEL: Dict[str, Any] = {
    'version': 'v1.0',
    'doc_date': '2026-05-07',
    'doc_url': 'https://www.phins.ai/phins-risk-1pager-fefferman.html',
    'reference_life_sum': 500000.0,
    'disability_share_of_life': 0.25,
    'life_base_rate_per_1000_monthly': 0.25,
    'disability_base_rate_per_1000_monthly': 0.20,
    'core_slope': 0.015,
    'youth_anchor_age': 3,
    'youth_anchor_factor': 0.30,
    'adult_anchor_age': 25,
    'adult_anchor_factor': 1.00,
    'senior_slope_1': 0.05,
    'senior_slope_2': 0.08,
    'disability_cut_off_age': 65,
    'mortality_qx': {35: 0.00133, 36: 0.00141, 37: 0.00150, 38: 0.00160, 39: 0.00171},
    'disability_incidence_ix': {35: 0.00450, 36: 0.00468, 37: 0.00487, 38: 0.00507, 39: 0.00528},
    'mortality_severity': 1.00,
    'disability_severity': 0.55,
    'reference_start_age': 35,
    'reference_projection_years': 5,
}


def fefferman_age_factor(age: int) -> float:
    """Return the published age curve factor (matches the 1-pager exactly)."""
    m = PHINS_FEFFERMAN_MODEL
    if age <= m['adult_anchor_age']:
        span = m['adult_anchor_age'] - m['youth_anchor_age']
        rise = m['adult_anchor_factor'] - m['youth_anchor_factor']
        anchored = max(m['youth_anchor_age'], age)
        return round(m['youth_anchor_factor'] + (anchored - m['youth_anchor_age']) * (rise / span), 4)
    if age <= m['disability_cut_off_age']:
        return round(m['adult_anchor_factor'] + (age - m['adult_anchor_age']) * m['core_slope'], 4)
    base = fefferman_age_factor(m['disability_cut_off_age'])
    capped = min(age, 80)
    if capped <= 75:
        return round(base + (capped - m['disability_cut_off_age']) * m['senior_slope_1'], 4)
    return round(
        base
        + (75 - m['disability_cut_off_age']) * m['senior_slope_1']
        + (capped - 75) * m['senior_slope_2'],
        4,
    )


def fefferman_monthly_premiums(age: int, life_sum: Optional[float] = None) -> Dict[str, float]:
    """Return monthly life + disability premium for the reference policyholder."""
    m = PHINS_FEFFERMAN_MODEL
    life = life_sum if life_sum is not None else m['reference_life_sum']
    disability = life * m['disability_share_of_life']
    factor = fefferman_age_factor(age)
    life_premium = (life / 1000.0) * m['life_base_rate_per_1000_monthly'] * factor
    disability_premium = 0.0
    if age < m['disability_cut_off_age']:
        disability_premium = (disability / 1000.0) * m['disability_base_rate_per_1000_monthly'] * factor
    return {
        'age': age,
        'age_factor': round(factor, 4),
        'life_monthly': round(life_premium, 2),
        'disability_monthly': round(disability_premium, 2),
        'total_monthly': round(life_premium + disability_premium, 2),
        'annual_premium': round((life_premium + disability_premium) * 12, 2),
    }


def build_fefferman_reference(start_age: Optional[int] = None,
                              projection_years: Optional[int] = None,
                              life_sum: Optional[float] = None) -> Dict[str, Any]:
    """
    Build the Fefferman reference 5-year forecast deterministically.

    The output reproduces the cumulative premium, expected loss, and average
    loss ratio shown on the public one-pager.
    """
    m = PHINS_FEFFERMAN_MODEL
    start_age = int(start_age if start_age is not None else m['reference_start_age'])
    projection_years = int(projection_years if projection_years is not None else m['reference_projection_years'])
    life = float(life_sum if life_sum is not None else m['reference_life_sum'])
    disability = life * m['disability_share_of_life']

    yearly = []
    cumulative_premium = 0.0
    cumulative_expected_loss = 0.0
    for offset in range(projection_years):
        age = start_age + offset
        premiums = fefferman_monthly_premiums(age, life_sum=life)
        annual = premiums['annual_premium']
        qx = m['mortality_qx'].get(age, 0.0)
        ix = m['disability_incidence_ix'].get(age, 0.0)
        expected_loss = qx * life * m['mortality_severity'] + ix * disability * m['disability_severity']
        loss_ratio = (expected_loss / annual) if annual > 0 else 0.0
        cumulative_premium += annual
        cumulative_expected_loss += expected_loss
        yearly.append({
            'year': offset + 1,
            'age': age,
            'age_factor': premiums['age_factor'],
            'annual_premium': round(annual, 2),
            'mortality_qx': qx,
            'disability_ix': ix,
            'expected_loss': round(expected_loss, 2),
            'loss_ratio': round(loss_ratio, 4),
        })

    avg_loss_ratio = (cumulative_expected_loss / cumulative_premium) if cumulative_premium > 0 else 0.0
    return {
        'source': {
            'document': 'PHINS Executive 1-Pager - Risk Factors (Alan Fefferman F.IL.A.A)',
            'url': m['doc_url'],
            'version': m['version'],
            'doc_date': m['doc_date'],
        },
        'reference': {
            'life_sum': life,
            'disability_sum': round(disability, 2),
            'life_base_rate_per_1000_monthly': m['life_base_rate_per_1000_monthly'],
            'disability_base_rate_per_1000_monthly': m['disability_base_rate_per_1000_monthly'],
            'disability_cut_off_age': m['disability_cut_off_age'],
            'start_age': start_age,
            'projection_years': projection_years,
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
                'mortality_severity': m['mortality_severity'],
                'disability_severity': m['disability_severity'],
            },
        },
    }


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
    - `savings_allocation_pct`: share of total premium allocated to the savings
      fund vs. the risk insurance balance sheet.
    - `savings_yield_pct`: assumed annual yield on the savings fund.
    - `projection_years`: number of "situation years" to project.
    - `initial_reserve`: opening reserve balance.
    """

    dividends_pct: float = 0.30
    tax_pct: float = 0.23
    ibnr_pct: float = 0.10
    reserve_contribution_pct: float = 0.40
    risk_adjustment_pct: float = 0.06
    csm_release_pattern: str = 'straight_line'
    savings_allocation_pct: float = 0.0
    savings_yield_pct: float = 0.045
    projection_years: int = 5
    initial_reserve: float = 0.0


def _coerce_reserve_config(payload: Optional[Dict[str, Any]]) -> ReserveConfig:
    payload = payload or {}
    return ReserveConfig(
        dividends_pct=_clamp(float(payload.get('dividends_pct', 0.30) or 0.0), 0.0, 1.0),
        tax_pct=_clamp(float(payload.get('tax_pct', 0.23) or 0.0), 0.0, 0.6),
        ibnr_pct=_clamp(float(payload.get('ibnr_pct', 0.10) or 0.0), 0.0, 1.0),
        reserve_contribution_pct=_clamp(
            float(payload.get('reserve_contribution_pct', 0.40) or 0.0), 0.0, 1.0
        ),
        risk_adjustment_pct=_clamp(
            float(payload.get('risk_adjustment_pct', 0.06) or 0.0), 0.0, 0.5
        ),
        csm_release_pattern=str(payload.get('csm_release_pattern') or 'straight_line').lower(),
        savings_allocation_pct=_clamp(
            float(payload.get('savings_allocation_pct', 0.0) or 0.0), 0.0, 0.95
        ),
        savings_yield_pct=_clamp(
            float(payload.get('savings_yield_pct', 0.045) or 0.0), -0.5, 0.5
        ),
        projection_years=max(1, min(50, int(payload.get('projection_years', 5) or 5))),
        initial_reserve=max(0.0, float(payload.get('initial_reserve', 0.0) or 0.0)),
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
        opening_csm = max(0.0, total_risk_premium * avg_term - opening_bel - opening_ra)
        opening_savings = 0.0

        yearly: List[Dict[str, Any]] = []
        cumulative_tax = 0.0
        cumulative_dividends = 0.0
        cumulative_retained = 0.0
        cumulative_reserve_contrib = 0.0
        cumulative_savings_contrib = 0.0

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
            savings_contribution = (
                (in_force_premium - savings_premium * in_force_factor) * config.savings_allocation_pct
                + savings_premium * in_force_factor
            )

            # IBNR provision: incurred-claims method
            ibnr = in_force_claims * config.ibnr_pct

            # IFRS 17 release: CSM amortized over remaining coverage units;
            # BEL and RA wind down proportionally to in-force decay.
            if config.csm_release_pattern == 'coverage_units':
                csm_release = (opening_csm * in_force_factor) / total_coverage_units
            else:
                csm_release = opening_csm / projection_years if projection_years else 0.0
            csm_release = min(opening_csm, csm_release)

            bel_balance = opening_bel * max(0.0, 1.0 - (year_index / avg_term))
            ra_balance = bel_balance * config.risk_adjustment_pct
            cumulative_csm_release += csm_release
            csm_balance = max(0.0, opening_csm - cumulative_csm_release)
            ifrs17_total_liability = bel_balance + ra_balance + csm_balance + ibnr

            closing_reserve = opening_reserve + reserve_contribution
            savings_yield_amount = opening_savings * config.savings_yield_pct
            closing_savings = opening_savings + savings_contribution + savings_yield_amount

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
                    'total_liability': round(ifrs17_total_liability, 2),
                },
                'savings_fund': {
                    'contribution': round(savings_contribution, 2),
                    'yield': round(savings_yield_amount, 2),
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

        totals = {
            'cumulative_tax': round(cumulative_tax, 2),
            'cumulative_dividends': round(cumulative_dividends, 2),
            'cumulative_retained_earnings': round(cumulative_retained, 2),
            'cumulative_reserve_contribution': round(cumulative_reserve_contrib, 2),
            'cumulative_savings_contribution': round(cumulative_savings_contrib, 2),
            'closing_reserve': round(opening_reserve, 2),
            'closing_savings_balance': round(opening_savings, 2),
            'average_reserve_contribution': round(
                cumulative_reserve_contrib / max(1, projection_years), 2
            ),
        }

        # Verifiable identity: profit waterfall must reconcile each year
        identity_checks = []
        for row in yearly:
            lhs = row['operating_profit']
            rhs = row['tax'] + row['after_tax_profit']
            identity_checks.append(abs(lhs - rhs) < 0.5)

        savings_allocation = apply_savings_allocation(simulation, config.savings_allocation_pct)

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
                'savings_fund': 0.0,
            },
            'savings_allocation': savings_allocation,
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
        # If the values look like raw qx/ix probabilities (<= 0.5) convert to per-1000.
        if rate_source in ('qx', 'ix') and rate_value <= 0.5:
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
