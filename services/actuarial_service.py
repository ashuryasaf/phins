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
        
        # Expense loading is on risk premium only
        expense_amount = annual_risk_premium * config.expense_loading_pct
        
        # Profit margin is on operational premium (risk + expense), not savings
        # Savings is pass-through to customer
        profit_amount = (annual_risk_premium + expense_amount) * config.profit_margin_pct
        
        # Net profit calculation:
        # Revenue = Risk Premium + Expense Loading + Profit Margin
        # Cost = Expected Claims
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
            'return_on_risk': round((net_profit / annual_risk_premium) * 100, 2) if annual_risk_premium > 0 else 0
        }
        
        # Build result
        duration = (datetime.now() - start_time).total_seconds()
        
        return {
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
        """Placeholder for future community integration"""
        return {
            'status': 'future_development',
            'features_planned': [
                'community_risk_pools',
                'group_discounts',
                'referral_tracking',
                'social_wellness_programs'
            ]
        }


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
