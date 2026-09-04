"""
Financial Reporting Service for PHINS Insurance Platform

Provides comprehensive financial reporting with:
- Long-term actuarial projections (25+ years)
- ADL (Activities of Daily Living) risk assessment
- Savings allocation and investment forecasting
- Lump sum benefit calculations
- Data integrity validation (bottom-up)
- Cross-dashboard data validation

ADL Levels (Activities of Daily Living):
- Level 1: Independent (lowest risk)
- Level 2-3: Mild impairment
- Level 4-5: Moderate impairment (medium risk)
- Level 6-7: Severe impairment
- Level 8+: Total dependence (highest risk)
"""

from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple
import math
import logging

logger = logging.getLogger(__name__)


# ==============================================================================
# CASE-INSENSITIVE STATUS HELPERS (for data integrity)
# ==============================================================================
def _status_eq(item: Dict, *statuses: str) -> bool:
    """Case-insensitive status check for an item."""
    item_status = (item.get('status') or '').lower().replace(' ', '_')
    return item_status in [s.lower().replace(' ', '_') for s in statuses]

def _status_in(item: Dict, statuses: list) -> bool:
    """Case-insensitive check if item's status is in a list of statuses."""
    item_status = (item.get('status') or '').lower().replace(' ', '_')
    return item_status in [s.lower().replace(' ', '_') for s in statuses]


# ==============================================================================
# ACTUARIAL CONSTANTS & TABLES (V2 - Corrected Risk Model)
# ==============================================================================
# 
# IMPORTANT: This model uses ADDITIVE risk pricing, not multiplicative.
# Premium = Mortality_Risk + Disability_Risk + Savings + Expenses
#
# Previous model flaw: combined_factor = age_factor × adl_multiplier
# Corrected model: separate mortality and disability risk calculations
# ==============================================================================

# Mortality rates by age bracket (per 1000 lives per year)
# Source: Standard mortality tables adjusted for insurance population
MORTALITY_RATES = {
    (0, 30): 0.5,
    (30, 40): 1.2,
    (40, 50): 2.5,
    (50, 60): 5.0,
    (60, 70): 12.0,
    (70, 80): 30.0,
    (80, 100): 75.0,
}

# DISABILITY INCIDENCE RATES by age bracket (per 1000 lives per year)
# Source: Industry data for severe disability (2+ ADLs impaired)
# This is SEPARATE from mortality - represents probability of becoming disabled
DISABILITY_INCIDENCE_RATES = {
    (0, 30): 2.0,     # Younger people - lower disability incidence
    (30, 40): 4.0,
    (40, 50): 8.0,
    (50, 60): 15.0,
    (60, 70): 30.0,
    (70, 80): 50.0,
    (80, 100): 80.0,
}

# ADL MORTALITY multipliers (1-10 scale, 5 is baseline)
# These adjust MORTALITY risk based on current ADL status
# Higher ADL = slightly higher mortality due to health conditions
ADL_MORTALITY_MULTIPLIERS = {
    1: 0.8,    # Very healthy - lower mortality
    2: 0.85,
    3: 0.9,
    4: 0.95,
    5: 1.0,    # Baseline
    6: 1.1,
    7: 1.2,
    8: 1.35,
    9: 1.5,
    10: 1.8,   # Severely impaired - higher mortality
}

# ADL DISABILITY INCIDENCE multipliers (1-10 scale, 5 is baseline)
# CRITICAL: This is the key correction - ADL level predicts DISABILITY claims
# Someone with higher ADL is MORE likely to progress to claiming disability benefits
ADL_DISABILITY_INCIDENCE_MULTIPLIERS = {
    1: 0.3,    # Very healthy - low progression to disability claim
    2: 0.5,
    3: 0.7,
    4: 0.9,
    5: 1.0,    # Baseline
    6: 1.5,    # Already showing signs - elevated risk
    7: 2.0,    # Moderate impairment - high progression risk
    8: 3.0,    # Significant impairment - very high risk
    9: 5.0,    # Severe - near-certain to claim
    10: 8.0,   # Total dependence - will claim immediately
}

# ADL BENEFIT PERCENTAGES - what % of coverage is paid for disability claim
# This determines the SIZE of the claim based on severity
ADL_BENEFIT_PERCENTAGES = {
    1: 0.0,    # Independent - no disability benefit
    2: 0.0,
    3: 0.0,
    4: 0.25,   # Mild impairment - 25% of coverage
    5: 0.25,
    6: 0.50,   # Moderate impairment - 50% of coverage
    7: 0.50,
    8: 0.85,   # Severe impairment - 85% of coverage
    9: 1.0,    # Near-total - 100% of coverage
    10: 1.0,   # Total dependence - 100% of coverage
}

# UNDERWRITING RESTRICTIONS by ADL level
# ADL 7+: Apply special loading or decline
ADL_UNDERWRITING_RULES = {
    1: {'accept': True, 'loading': 0.0, 'max_coverage': None},
    2: {'accept': True, 'loading': 0.0, 'max_coverage': None},
    3: {'accept': True, 'loading': 0.0, 'max_coverage': None},
    4: {'accept': True, 'loading': 0.0, 'max_coverage': None},
    5: {'accept': True, 'loading': 0.0, 'max_coverage': None},
    6: {'accept': True, 'loading': 0.15, 'max_coverage': 1_000_000},  # 15% loading
    7: {'accept': True, 'loading': 0.30, 'max_coverage': 750_000},   # 30% loading, reduced coverage
    8: {'accept': True, 'loading': 0.50, 'max_coverage': 500_000, 'exclude_disability': True},  # 50% loading, exclude disability
    9: {'accept': False, 'loading': None, 'max_coverage': None, 'reason': 'ADL too high'},  # Decline
    10: {'accept': False, 'loading': None, 'max_coverage': None, 'reason': 'ADL too high'},  # Decline
}

# Legacy alias for backward compatibility (use ADL_MORTALITY_MULTIPLIERS instead)
ADL_RISK_MULTIPLIERS = ADL_MORTALITY_MULTIPLIERS

# Lapse rates by policy year
LAPSE_RATES = {
    1: 0.08,   # 8% lapse in year 1
    2: 0.05,
    3: 0.04,
    (4, 10): 0.03,
    (11, 25): 0.02,
    (26, 100): 0.01,
}

# Investment return assumptions (annual)
INVESTMENT_RETURNS = {
    'conservative': 0.04,   # 4% annual
    'moderate': 0.06,       # 6% annual
    'aggressive': 0.08,     # 8% annual
}

# Discount rate for present value calculations
DISCOUNT_RATE = 0.035  # 3.5% annual

# Expense loading as percentage of risk premium
EXPENSE_LOADING_PCT = 0.15  # 15%

# Profit margin target (added to break-even premium)
PROFIT_MARGIN_PCT = 0.10  # 10% target profit margin


try:
    from services.financial_unification_service import PREMIUM_CASH_TYPES as _PREMIUM_LEDGER_TX_TYPES
except Exception:
    _PREMIUM_LEDGER_TX_TYPES = {
        'premium_payment',
        'bill_payment',
        'bill_paid',
        'premium_received',
        'premium_deposit',
        'bulk_premium_payment',
    }


def _get_tx_type(tx: Dict) -> str:
    return str(tx.get('type') or tx.get('tx_type') or '').strip().lower()


class FinancialReportingService:
    """
    Comprehensive financial reporting service with actuarial calculations.
    """
    
    def __init__(self, policies: Dict, claims: Dict, billing: Dict, 
                 customers: Dict, underwriting: Dict,
                 transaction_ledger: Optional[Dict] = None,
                 health_wallets: Optional[Dict] = None):
        self._policies = policies
        self._claims = claims
        self._billing = billing
        self._customers = customers
        self._underwriting = underwriting
        self._ledger_attached = transaction_ledger is not None
        self._transaction_ledger = transaction_ledger if transaction_ledger is not None else {}
        self._health_wallets = health_wallets if health_wallets is not None else {}

    def calculate_cumulative_premium(self, exclude_suspended: bool = True) -> Dict[str, Any]:
        """
        Calculate cumulative premium income from ALL data sources:
        1. Billing records (amount_paid from self._billing)
        2. Transaction ledger entries (premium_payment type from self._transaction_ledger)

        Returns dict with:
          - from_bills: sum of amount_paid from billing records
          - ledger_unbilled_total: sum of unbilled premium amounts from transaction ledger
          - from_allocations: 0 (reserved for future premium allocation tracker)
          - total: cumulative sum of ALL sources (deduplicated)
          - cumulative_premium: same as total (canonical field name)
        """
        def _safe(val):
            if val is None:
                return 0.0
            try:
                return float(val)
            except (TypeError, ValueError):
                return 0.0

        bill_paid_total = 0.0
        paid_bill_ids: set = set()

        for bill_id, bill in self._billing.items():
            amount_paid = _safe(bill.get('amount_paid', 0))
            if amount_paid <= 0:
                continue
            bill_paid_total += amount_paid
            paid_bill_ids.add(str(bill.get('id') or bill_id))

        ledger_unbilled_total = 0.0

        for tx in self._transaction_ledger.values():
            tx_type = _get_tx_type(tx)
            if tx_type not in _PREMIUM_LEDGER_TX_TYPES:
                continue

            amount = abs(_safe(tx.get('amount', 0)))
            if amount <= 0:
                continue

            metadata = tx.get('metadata', {})
            if not isinstance(metadata, dict):
                metadata = {}

            linked_bill_id = str(metadata.get('bill_id') or '').strip()
            if linked_bill_id and linked_bill_id in paid_bill_ids:
                continue

            if tx_type == 'premium_payment' and metadata.get('unbilled_premium_amount') is not None:
                amount = _safe(metadata.get('unbilled_premium_amount', 0))

            if amount <= 0:
                continue

            ledger_unbilled_total += amount

        total = round(bill_paid_total + ledger_unbilled_total, 2)
        return {
            'from_bills': round(bill_paid_total, 2),
            'ledger_unbilled_total': round(ledger_unbilled_total, 2),
            'from_allocations': 0,
            'total': total,
            'cumulative_premium': total,
        }
    
    # ==========================================================================
    # ACTUARIAL CALCULATIONS (V2 - CORRECTED ADDITIVE RISK MODEL)
    # ==========================================================================
    # 
    # IMPORTANT: Premium = Mortality_Risk + Disability_Risk + Savings + Expenses
    # NOT: Premium = (Mortality × ADL_Multiplier) + Savings + Expenses (OLD/WRONG)
    # ==========================================================================
    
    def get_mortality_rate(self, age: int) -> float:
        """Get base mortality rate per 1000 lives for given age"""
        for (low, high), rate in MORTALITY_RATES.items():
            if low <= age < high:
                return rate / 1000.0
        return 0.075  # Default for very old ages
    
    def get_disability_incidence_rate(self, age: int) -> float:
        """Get disability incidence rate per 1000 lives for given age (NEW)"""
        for (low, high), rate in DISABILITY_INCIDENCE_RATES.items():
            if low <= age < high:
                return rate / 1000.0
        return 0.08  # Default for very old ages
    
    def get_adl_mortality_multiplier(self, adl_level: int) -> float:
        """Get MORTALITY risk multiplier based on ADL level (1-10)"""
        adl_level = max(1, min(10, adl_level))
        return ADL_MORTALITY_MULTIPLIERS.get(adl_level, 1.0)
    
    def get_adl_disability_incidence_multiplier(self, adl_level: int) -> float:
        """Get DISABILITY INCIDENCE multiplier based on ADL level (1-10) (NEW)
        
        This is the critical factor - higher ADL means MORE likely to claim disability.
        """
        adl_level = max(1, min(10, adl_level))
        return ADL_DISABILITY_INCIDENCE_MULTIPLIERS.get(adl_level, 1.0)
    
    def get_adl_benefit_percentage(self, adl_level: int) -> float:
        """Get disability benefit percentage based on ADL level (NEW)
        
        Returns the % of coverage paid out for disability claim at this ADL level.
        """
        adl_level = max(1, min(10, adl_level))
        return ADL_BENEFIT_PERCENTAGES.get(adl_level, 0.35)  # Default 35% avg
    
    def get_adl_multiplier(self, adl_level: int) -> float:
        """Legacy method - returns mortality multiplier for backward compatibility"""
        return self.get_adl_mortality_multiplier(adl_level)
    
    def get_lapse_rate(self, policy_year: int) -> float:
        """Get lapse rate for given policy year"""
        if policy_year in LAPSE_RATES:
            return LAPSE_RATES[policy_year]
        for key, rate in LAPSE_RATES.items():
            if isinstance(key, tuple) and key[0] <= policy_year <= key[1]:
                return rate
        return 0.01
    
    def check_underwriting_eligibility(self, adl_level: int, coverage: float) -> Dict[str, Any]:
        """Check if customer is eligible for coverage based on ADL level (NEW)"""
        adl_level = max(1, min(10, adl_level))
        rules = ADL_UNDERWRITING_RULES.get(adl_level, ADL_UNDERWRITING_RULES[5])
        
        result = {
            'eligible': rules['accept'],
            'adl_level': adl_level,
            'requested_coverage': coverage,
        }
        
        if not rules['accept']:
            result['decline_reason'] = rules.get('reason', 'ADL level too high for coverage')
            result['approved_coverage'] = 0
            result['loading'] = None
        else:
            max_cov = rules.get('max_coverage')
            result['loading'] = rules.get('loading', 0)
            result['exclude_disability'] = rules.get('exclude_disability', False)
            
            if max_cov and coverage > max_cov:
                result['approved_coverage'] = max_cov
                result['coverage_reduced'] = True
                result['reduction_reason'] = f'ADL {adl_level} limited to ${max_cov:,} coverage'
            else:
                result['approved_coverage'] = coverage
                result['coverage_reduced'] = False
        
        return result
    
    def calculate_premium(self, coverage: float, age: int, adl_level: int,
                         savings_pct: float, term_years: int,
                         include_profit_margin: bool = True) -> Dict[str, float]:
        """
        Calculate actuarially sound premium via the central pricing kernel.

        The kernel (``services.pricing_kernel.price_policy``) is the single
        source of truth for actuarial pricing across the platform. This
        method routes the legacy financial-reporting inputs at the kernel
        with the legacy claim model (``ClaimModel.INDEPENDENT``), lapse
        adjustment, and minimum-risk floor enabled so output stays
        bit-for-bit compatible with previous releases.

        Args:
            coverage: Face value of policy
            age: Customer's current age
            adl_level: ADL score (1-10)
            savings_pct: % of coverage allocated to savings (now flows
                directly into the kernel's savings_rate)
            term_years: Policy term in years
            include_profit_margin: Whether to add profit margin (default True)
        """
        # Check underwriting eligibility first
        uw_check = self.check_underwriting_eligibility(adl_level, coverage)
        if not uw_check['eligible']:
            return {
                'annual_premium': 0,
                'monthly_premium': 0,
                'eligible': False,
                'decline_reason': uw_check['decline_reason'],
                'adl_level': adl_level,
                'customer_age': age
            }
        
        # Use approved coverage (may be reduced for high ADL)
        approved_coverage = uw_check['approved_coverage']
        underwriting_loading = uw_check.get('loading', 0)
        exclude_disability = uw_check.get('exclude_disability', False)

        # Delegate the pricing math to the central pricing kernel. The legacy
        # FinancialReportingService used independent mortality/disability PVs
        # with lapse adjustment and a minimum-risk floor for ADL 8+, so the
        # kernel is configured to match that behaviour exactly.
        from services.pricing_kernel import (
            ClaimModel, PricingConfig, PricingCustomer, SavingsFormula,
            TableSet, get_age_curve, get_product, price_policy,
        )

        kernel_tables = TableSet(
            mortality_rates=[
                {'age_min': low, 'age_max': high, 'rate_per_1000': rate}
                for (low, high), rate in MORTALITY_RATES.items()
            ],
            disability_incidence_rates=[
                {'age_min': low, 'age_max': high, 'rate_per_1000': rate}
                for (low, high), rate in DISABILITY_INCIDENCE_RATES.items()
            ],
            adl_mortality_multipliers=[
                {'adl': adl, 'multiplier': mult}
                for adl, mult in ADL_MORTALITY_MULTIPLIERS.items()
            ],
            adl_disability_multipliers=[
                {'adl': adl, 'multiplier': mult}
                for adl, mult in ADL_DISABILITY_INCIDENCE_MULTIPLIERS.items()
            ],
            adl_benefit_percentages=[
                {'adl': adl, 'benefit_pct': pct}
                for adl, pct in ADL_BENEFIT_PERCENTAGES.items()
            ],
            lapse_rates=[
                ({'year': key, 'rate': rate} if isinstance(key, int)
                 else {'year_min': key[0], 'year_max': key[1], 'rate': rate})
                for key, rate in LAPSE_RATES.items()
            ],
            age_curve=get_age_curve('identity'),
            version='financial_reporting_v2',
        )
        # FRS expects each ADL bracket to carry its own benefit percentage but
        # the legacy disability PV applied wider age-bracket fallbacks. Mirror
        # those overrides on the table so the kernel sees identical inputs.
        adl_benefit_override = {
            1: 0.25, 2: 0.25, 3: 0.25, 4: 0.35, 5: 0.35,
            6: 0.65, 7: 0.65, 8: 0.90, 9: 0.90, 10: 0.90,
        }
        kernel_tables.adl_benefit_percentages = [
            {'adl': adl, 'benefit_pct': pct} for adl, pct in adl_benefit_override.items()
        ]

        kernel_config = PricingConfig(
            expense_loading_pct=EXPENSE_LOADING_PCT,
            profit_margin_pct=PROFIT_MARGIN_PCT if include_profit_margin else 0.0,
            discount_rate=DISCOUNT_RATE,
            savings_rate=float(savings_pct or 0.0),
            savings_yield_pct=0.0,
            savings_formula=SavingsFormula.STRAIGHT_LINE,
            claim_model=ClaimModel.INDEPENDENT,
            apply_lapse_adjustment=True,
            apply_min_risk_floor=True,
            version='financial_reporting_v2',
        )

        components = price_policy(
            PricingCustomer(
                age=int(age),
                coverage=float(approved_coverage),
                term_years=int(term_years),
                adl_level=int(adl_level),
            ),
            get_product('phins_hybrid_savings'),
            kernel_tables,
            kernel_config,
            underwriting_loading=float(underwriting_loading),
            exclude_disability=bool(exclude_disability),
        )

        adl_mort_mult = components.adl_mortality_multiplier
        adl_dis_mult = components.adl_disability_multiplier
        mortality_cost_pv = components.pv_mortality_claims
        disability_cost_pv = components.pv_disability_claims
        total_risk_cost_pv = components.pv_total_risk_claims
        mortality_premium_annual = components.mortality_premium_annual
        disability_premium_annual = components.disability_premium_annual
        risk_premium_annual = components.risk_premium_annual
        savings_premium_annual = components.savings_premium_annual
        expense_loading = components.expense_loading_annual
        profit_margin = components.profit_margin_annual
        total_annual = components.annual_premium
        savings_allocation = approved_coverage * float(savings_pct or 0.0)

        return {
            'annual_premium': total_annual,
            'monthly_premium': components.monthly_premium,
            'risk_component': risk_premium_annual,
            'mortality_component': mortality_premium_annual,
            'disability_component': disability_premium_annual,
            'savings_component': savings_premium_annual,
            'expense_loading': expense_loading,
            'profit_margin': profit_margin,
            'coverage': approved_coverage,
            'original_coverage': coverage,
            'coverage_reduced': uw_check.get('coverage_reduced', False),
            'savings_target': round(savings_allocation, 2),
            'term_years': term_years,
            'adl_level': adl_level,
            'adl_mortality_multiplier': round(adl_mort_mult, 3),
            'adl_disability_multiplier': round(adl_dis_mult, 3),
            'underwriting_loading': round(underwriting_loading, 3),
            'exclude_disability': exclude_disability,
            'customer_age': age,
            'eligible': True,
            'pv_mortality_risk': mortality_cost_pv,
            'pv_disability_risk': disability_cost_pv,
            'pv_total_risk': total_risk_cost_pv,
            'actuarial_model': 'PHINS_PRICING_KERNEL_V1',
            'pricing_kernel_integrity_hash': components.integrity_hash,
            'expected_loss_ratio': round(
                (total_risk_cost_pv / (risk_premium_annual * term_years)) * 100, 1
            ) if risk_premium_annual > 0 else 0
        }

    
    def project_policy_value(self, coverage: float, age: int, adl_level: int,
                            savings_pct: float, term_years: int,
                            investment_profile: str = 'moderate') -> List[Dict]:
        """
        Project policy value over the full term with yearly breakdown.
        
        Returns list of yearly projections including:
        - Year number
        - Age
        - Premiums paid (cumulative)
        - Risk fund balance
        - Savings fund balance
        - Total cash value
        - Death benefit (lump sum if claim)
        - Surrender value
        """
        premium_calc = self.calculate_premium(coverage, age, adl_level, savings_pct, term_years)
        annual_premium = premium_calc['annual_premium']
        risk_component = premium_calc['risk_component']
        savings_component = premium_calc['savings_component']
        
        investment_return = INVESTMENT_RETURNS.get(investment_profile, 0.06)
        
        projections = []
        cumulative_premiums = 0.0
        risk_fund = 0.0
        savings_fund = 0.0
        
        for year in range(1, term_years + 1):
            current_age = age + year
            cumulative_premiums += annual_premium
            
            # Risk fund accumulation (decreasing over time as mortality risk decreases)
            risk_fund = risk_fund * (1 - self.get_mortality_rate(current_age - 1)) + risk_component
            
            # Savings fund with investment growth
            savings_fund = (savings_fund + savings_component) * (1 + investment_return)
            
            # Cash value (surrender value = 85% of savings fund after year 3)
            surrender_penalty = 0.15 if year < 3 else 0.05 if year < 5 else 0.0
            cash_value = savings_fund * (1 - surrender_penalty)
            
            # Death benefit (coverage + accumulated savings)
            death_benefit = coverage + savings_fund
            
            # Living benefit (if ADL claim - payout structure)
            adl_claim_payout = self._calculate_adl_benefit(coverage, adl_level, year)
            
            projections.append({
                'year': year,
                'age': current_age,
                'cumulative_premiums': round(cumulative_premiums, 2),
                'risk_fund_balance': round(risk_fund, 2),
                'savings_fund_balance': round(savings_fund, 2),
                'total_cash_value': round(cash_value, 2),
                'death_benefit': round(death_benefit, 2),
                'adl_claim_benefit': round(adl_claim_payout, 2),
                'surrender_value': round(cash_value, 2),
                'investment_return_pct': round(investment_return * 100, 2),
                'projected_date': (datetime.now() + timedelta(days=365 * year)).strftime('%Y-%m-%d')
            })
        
        return projections
    
    def _calculate_adl_benefit(self, coverage: float, adl_level: int, policy_year: int) -> float:
        """
        Calculate ADL claim benefit based on impairment level.
        
        ADL 1-3: No benefit (independent)
        ADL 4-5: 25% of coverage as monthly benefit for 24 months
        ADL 6-7: 50% of coverage as lump sum OR monthly for 60 months
        ADL 8+: 100% of coverage as lump sum
        """
        if adl_level <= 3:
            return 0.0
        elif adl_level <= 5:
            return coverage * 0.25  # Partial benefit
        elif adl_level <= 7:
            return coverage * 0.50  # Moderate benefit
        else:
            return coverage  # Full benefit
    
    # ==========================================================================
    # LUMP SUM CALCULATIONS
    # ==========================================================================
    
    def calculate_lump_sum_options(self, coverage: float, savings_pct: float,
                                   adl_level: int, years_paid: int,
                                   total_premiums_paid: float) -> Dict[str, Any]:
        """
        Calculate various lump sum payout options for a policy.
        """
        savings_accumulated = total_premiums_paid * savings_pct * 1.06 ** years_paid
        
        options = {
            'death_benefit_lump_sum': round(coverage + savings_accumulated, 2),
            'terminal_illness_lump_sum': round(coverage * 0.9, 2),  # 90% accelerated
            'adl_claim_lump_sum': round(self._calculate_adl_benefit(coverage, adl_level, years_paid), 2),
            'surrender_value': round(savings_accumulated * (0.95 if years_paid >= 5 else 0.85), 2),
            'maturity_value': round(coverage * 0.5 + savings_accumulated, 2),  # At term end
            'annuity_conversion': {
                '10_year': round((coverage + savings_accumulated) / 120, 2),  # Monthly for 10 years
                '20_year': round((coverage + savings_accumulated) / 240, 2),  # Monthly for 20 years
                'lifetime': round((coverage + savings_accumulated) / 300, 2),  # Estimated lifetime
            }
        }
        
        return options
    
    # ==========================================================================
    # FINANCIAL REPORTS
    # ==========================================================================
    
    def generate_portfolio_report(self) -> Dict[str, Any]:
        """
        Generate comprehensive portfolio report with all policies.
        """
        total_coverage = 0.0
        total_premiums = 0.0
        total_claims_liability = 0.0
        total_savings_liability = 0.0
        risk_distribution = {'low': 0, 'medium': 0, 'high': 0, 'very_high': 0}
        coverage_by_type = {}
        age_distribution = {}
        
        policies_data = []
        
        for policy_id, policy in self._policies.items():
            if policy.get('status') != 'active':
                continue
                
            coverage = policy.get('coverage_amount', 0)
            annual_premium = policy.get('annual_premium', 0)
            policy_type = policy.get('type', 'life')
            risk_score = policy.get('risk_score', 'medium')
            
            total_coverage += coverage
            total_premiums += annual_premium
            
            # Get customer age
            customer_id = policy.get('customer_id')
            customer = self._customers.get(customer_id, {})
            age = self._calculate_age(customer.get('dob'))
            
            # Risk distribution
            if risk_score in ['low']:
                risk_distribution['low'] += 1
            elif risk_score in ['medium']:
                risk_distribution['medium'] += 1
            elif risk_score in ['high']:
                risk_distribution['high'] += 1
            else:
                risk_distribution['very_high'] += 1
            
            # Coverage by type
            coverage_by_type[policy_type] = coverage_by_type.get(policy_type, 0) + coverage
            
            # Age distribution
            age_bucket = f"{(age // 10) * 10}-{(age // 10) * 10 + 9}" if age else 'Unknown'
            age_distribution[age_bucket] = age_distribution.get(age_bucket, 0) + 1
            
            # Estimate savings liability (assume 50% savings, 6% annual growth, avg 5 years)
            savings_liability = annual_premium * 0.5 * 5 * 1.06 ** 2.5
            total_savings_liability += savings_liability
            
            policies_data.append({
                'policy_id': policy_id,
                'coverage': coverage,
                'premium': annual_premium,
                'type': policy_type,
                'risk': risk_score,
                'age': age
            })
        
        # Claims liability (case-insensitive)
        for claim_id, claim in self._claims.items():
            if _status_in(claim, ['pending', 'under_review', 'approved']):
                total_claims_liability += claim.get('claimed_amount', 0)
        
        return {
            'summary': {
                'total_policies': len([p for p in self._policies.values() if _status_eq(p, 'active')]),
                'total_coverage': round(total_coverage, 2),
                'total_annual_premiums': round(total_premiums, 2),
                'total_claims_liability': round(total_claims_liability, 2),
                'total_savings_liability': round(total_savings_liability, 2),
                'reserve_requirement': round(total_coverage * 0.05 + total_savings_liability, 2),
                'solvency_ratio': round(total_premiums * 3 / max(total_claims_liability + total_savings_liability, 1), 2)
            },
            'risk_distribution': risk_distribution,
            'coverage_by_type': coverage_by_type,
            'age_distribution': age_distribution,
            'generated_at': datetime.now().isoformat()
        }
    
    def generate_forecast_report(self, years: int = 25) -> Dict[str, Any]:
        """
        Generate long-term forecast for the portfolio (case-insensitive status checks).
        """
        current_premiums = sum(p.get('annual_premium', 0) for p in self._policies.values() 
                               if _status_eq(p, 'active'))
        current_policies = len([p for p in self._policies.values() if _status_eq(p, 'active')])
        
        # Growth assumptions
        new_policy_growth = 0.10  # 10% annual new policy growth
        premium_inflation = 0.03  # 3% annual premium inflation
        claim_rate = 0.02  # 2% of policies claim per year
        avg_claim_amount = sum(p.get('coverage_amount', 0) for p in self._policies.values()) / max(current_policies, 1) * 0.3
        
        yearly_projections = []
        cumulative_revenue = 0.0
        cumulative_claims = 0.0
        policies = current_policies
        premiums = current_premiums
        
        for year in range(1, years + 1):
            # Project growth
            new_policies = int(policies * new_policy_growth)
            policies += new_policies
            policies = int(policies * (1 - 0.03))  # 3% lapse
            
            premiums = premiums * (1 + premium_inflation) + new_policies * (premiums / max(current_policies, 1))
            
            # Claims projection
            expected_claims = policies * claim_rate * avg_claim_amount
            
            cumulative_revenue += premiums
            cumulative_claims += expected_claims
            
            yearly_projections.append({
                'year': year,
                'projected_date': (datetime.now() + timedelta(days=365 * year)).strftime('%Y-%m-%d'),
                'active_policies': policies,
                'annual_premium_revenue': round(premiums, 2),
                'expected_claims': round(expected_claims, 2),
                'net_income': round(premiums - expected_claims, 2),
                'cumulative_revenue': round(cumulative_revenue, 2),
                'cumulative_claims': round(cumulative_claims, 2),
                'cumulative_profit': round(cumulative_revenue - cumulative_claims, 2)
            })
        
        return {
            'forecast_years': years,
            'assumptions': {
                'new_policy_growth_rate': f"{new_policy_growth * 100}%",
                'premium_inflation_rate': f"{premium_inflation * 100}%",
                'claim_rate': f"{claim_rate * 100}%",
                'avg_claim_amount': round(avg_claim_amount, 2)
            },
            'projections': yearly_projections,
            'summary': {
                'year_25_policies': yearly_projections[-1]['active_policies'] if yearly_projections else 0,
                'year_25_revenue': yearly_projections[-1]['cumulative_revenue'] if yearly_projections else 0,
                'year_25_profit': yearly_projections[-1]['cumulative_profit'] if yearly_projections else 0
            },
            'generated_at': datetime.now().isoformat()
        }
    
    def generate_customer_projection(self, customer_id: str = None, 
                                     coverage: float = 250000,
                                     savings_pct: float = 0.50,
                                     adl_level: int = 5,
                                     term_years: int = 25,
                                     age: int = 35) -> Dict[str, Any]:
        """
        Generate detailed projection for a specific customer scenario.
        
        Default: $250,000 coverage, 50% savings, ADL level 5 (medium risk), 25 years
        """
        # If customer_id provided, get their actual data
        if customer_id:
            customer = self._customers.get(customer_id, {})
            if customer:
                age = self._calculate_age(customer.get('dob')) or age
                
                # Get their policy data if exists (case-insensitive)
                for policy in self._policies.values():
                    if policy.get('customer_id') == customer_id and _status_eq(policy, 'active'):
                        coverage = policy.get('coverage_amount', coverage)
                        # Extract savings_pct from policy if available
                        break
        
        # Calculate premium
        premium_breakdown = self.calculate_premium(coverage, age, adl_level, savings_pct, term_years)
        
        # Generate yearly projections
        yearly_projections = self.project_policy_value(
            coverage, age, adl_level, savings_pct, term_years
        )
        
        # Lump sum options
        # Estimate years paid as middle of term for illustration
        years_paid = term_years // 2
        total_premiums = premium_breakdown['annual_premium'] * years_paid
        lump_sum_options = self.calculate_lump_sum_options(
            coverage, savings_pct, adl_level, years_paid, total_premiums
        )
        
        return {
            'scenario': {
                'coverage': coverage,
                'savings_allocation': f"{savings_pct * 100}%",
                'adl_level': adl_level,
                'adl_risk': self._get_adl_description(adl_level),
                'term_years': term_years,
                'customer_age': age
            },
            'premium_breakdown': premium_breakdown,
            'yearly_projections': yearly_projections,
            'lump_sum_options': lump_sum_options,
            'key_milestones': {
                'year_5': yearly_projections[4] if len(yearly_projections) >= 5 else None,
                'year_10': yearly_projections[9] if len(yearly_projections) >= 10 else None,
                'year_15': yearly_projections[14] if len(yearly_projections) >= 15 else None,
                'year_20': yearly_projections[19] if len(yearly_projections) >= 20 else None,
                'year_25': yearly_projections[24] if len(yearly_projections) >= 25 else None,
            },
            'generated_at': datetime.now().isoformat()
        }
    
    def _get_adl_description(self, adl_level: int) -> str:
        """Get human-readable ADL description"""
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
    
    def _calculate_age(self, dob: str) -> int:
        """Calculate age from date of birth string"""
        if not dob:
            return 35  # Default age
        try:
            birth_date = datetime.fromisoformat(dob.replace('Z', '+00:00').split('T')[0])
            today = datetime.now()
            age = today.year - birth_date.year
            if (today.month, today.day) < (birth_date.month, birth_date.day):
                age -= 1
            return max(18, min(age, 100))  # Clamp between 18-100
        except:
            return 35
    
    # ==========================================================================
    # DATA INTEGRITY VALIDATION
    # ==========================================================================
    
    def validate_data_integrity(self) -> Dict[str, Any]:
        """
        Bottom-up data integrity validation across all data stores.
        Includes actuarial consistency checks.
        """
        issues = []
        warnings = []
        actuarial_checks = {
            'total_checked': 0,
            'passed': 0,
            'failed': 0,
            'details': []
        }
        
        # Map risk_score to ADL level (same as server.py)
        RISK_TO_ADL_MAP = {
            'low': 3,
            'medium': 5,
            'high': 7,
            'very_high': 9,
        }
        
        # 1. Policy validation with actuarial checks
        for policy_id, policy in self._policies.items():
            # Check required fields
            if not policy.get('customer_id'):
                issues.append(f"Policy {policy_id}: Missing customer_id")
            elif policy.get('customer_id') not in self._customers:
                issues.append(f"Policy {policy_id}: Customer {policy.get('customer_id')} not found")
            
            if not policy.get('coverage_amount') or policy.get('coverage_amount', 0) <= 0:
                issues.append(f"Policy {policy_id}: Invalid coverage amount")
            
            if not policy.get('annual_premium') or policy.get('annual_premium', 0) <= 0:
                warnings.append(f"Policy {policy_id}: Missing or zero premium")
            
            # Actuarial consistency check for life/health policies (case-insensitive)
            if _status_eq(policy, 'active') and policy.get('type') in ['life', 'health']:
                actuarial_checks['total_checked'] += 1
                
                # Get customer age
                customer_id = policy.get('customer_id')
                customer = self._customers.get(customer_id, {})
                age = self._calculate_age(customer.get('dob'))
                
                # Get risk score and convert to ADL
                risk_score = policy.get('risk_score', 'medium')
                adl_level = RISK_TO_ADL_MAP.get(risk_score, 5)
                
                # Get coverage and premium
                coverage = policy.get('coverage_amount', 0)
                stored_premium = policy.get('annual_premium', 0)
                
                # Calculate expected premium using actuarial tables
                if coverage > 0 and stored_premium > 0:
                    # Simple check: premium should be proportional to coverage and risk
                    expected_ratio = stored_premium / coverage  # Premium per dollar of coverage
                    adl_mult = self.get_adl_multiplier(adl_level)
                    
                    # Expected ratio should be higher for older/higher-risk customers
                    # Typical range: 0.002 (low risk) to 0.015 (high risk)
                    min_expected_ratio = 0.001
                    max_expected_ratio = 0.02
                    
                    if min_expected_ratio <= expected_ratio <= max_expected_ratio:
                        actuarial_checks['passed'] += 1
                        actuarial_checks['details'].append({
                            'policy_id': policy_id,
                            'status': 'PASS',
                            'risk_score': risk_score,
                            'adl_level': adl_level,
                            'premium_ratio': round(expected_ratio, 6)
                        })
                    else:
                        actuarial_checks['failed'] += 1
                        actuarial_checks['details'].append({
                            'policy_id': policy_id,
                            'status': 'REVIEW',
                            'risk_score': risk_score,
                            'adl_level': adl_level,
                            'premium_ratio': round(expected_ratio, 6),
                            'note': f"Premium ratio {expected_ratio:.4f} outside expected range"
                        })
                        warnings.append(f"Policy {policy_id}: Premium ratio may need actuarial review")
        
        # 2. Billing validation
        for bill_id, bill in self._billing.items():
            policy_id = bill.get('policy_id')
            if policy_id and policy_id not in self._policies:
                issues.append(f"Bill {bill_id}: References non-existent policy {policy_id}")
            
            if bill.get('amount_paid', 0) > bill.get('amount_due', bill.get('amount', 0)):
                warnings.append(f"Bill {bill_id}: Paid amount exceeds due amount")
        
        # 3. Claims validation
        for claim_id, claim in self._claims.items():
            policy_id = claim.get('policy_id')
            if policy_id:
                policy = self._policies.get(policy_id)
                if not policy:
                    issues.append(f"Claim {claim_id}: References non-existent policy {policy_id}")
                elif claim.get('claimed_amount', 0) > policy.get('coverage_amount', 0) * 1.5:
                    warnings.append(f"Claim {claim_id}: Claimed amount exceeds 150% of coverage")
        
        # 4. Underwriting validation
        for uw_id, uw in self._underwriting.items():
            policy_id = uw.get('policy_id')
            if policy_id and policy_id not in self._policies:
                issues.append(f"Underwriting {uw_id}: References non-existent policy {policy_id}")
            
            uw_status = (uw.get('status') or '').lower()
            if uw_status == 'approved':
                policy = self._policies.get(policy_id, {})
                policy_status = (policy.get('status') or '').lower()
                if policy_status not in ['active', 'pending_billing']:
                    warnings.append(f"Underwriting {uw_id}: Approved but policy status is {policy.get('status')}")
        
        # 5. Financial reconciliation (case-insensitive)
        total_premiums_expected = sum(p.get('annual_premium', 0) for p in self._policies.values() 
                                      if _status_eq(p, 'active'))
        total_billed = sum(b.get('amount_due', b.get('amount', 0)) for b in self._billing.values())
        cumulative_data = self.calculate_cumulative_premium()
        total_paid = cumulative_data['total']
        
        # Case-insensitive status check for claims
        def is_claim_approved_or_paid(claim):
            status = (claim.get('status') or '').lower()
            return status in ['approved', 'paid']
        
        total_claims_approved = sum(
            float(c.get('approved_amount') or 0) 
            for c in self._claims.values() 
            if is_claim_approved_or_paid(c)
        )
        
        # Loss ratio = Claims Approved / Expected Premiums (industry standard)
        # If no premiums collected yet, show projected loss ratio based on expected premiums
        loss_ratio_denominator = total_paid if total_paid > 0 else total_premiums_expected
        loss_ratio = (total_claims_approved / max(loss_ratio_denominator, 1)) * 100
        
        financial_summary = {
            'total_expected_premiums': round(total_premiums_expected, 2),
            'total_billed': round(total_billed, 2),
            'total_collected': round(total_paid, 2),
            'collection_rate': round(total_paid / max(total_billed, 1) * 100, 2),
            'total_claims_approved': round(total_claims_approved, 2),
            'loss_ratio': round(loss_ratio, 2),
            'cumulative_premium_breakdown': {
                'from_bills': cumulative_data['from_bills'],
                'from_ledger': cumulative_data['ledger_unbilled_total'],
                'from_allocations': cumulative_data.get('from_allocations', 0),
            },
        }
        
        # 6. Notification subsystem health
        notification_integrity = {'status': 'ok', 'smtp_circuit_breaker': 'unknown'}
        try:
            from services.notification_service import get_smtp_circuit_breaker, get_active_email_provider_type
            cb = get_smtp_circuit_breaker()
            cb_status = cb.get_status()
            cb_state = cb_status['state']
            provider_type = get_active_email_provider_type()
            if provider_type == 'noop':
                warnings.append("No email provider configured – email delivery disabled")
                notification_integrity['status'] = 'no_provider'
            elif cb_state == 'open':
                warnings.append("SMTP circuit breaker is OPEN – email delivery is paused")
                notification_integrity['status'] = 'degraded'
            elif cb_state == 'half_open':
                warnings.append("SMTP circuit breaker is HALF_OPEN – probing email delivery")
                notification_integrity['status'] = 'recovering'
            else:
                notification_integrity['status'] = 'ok'
            notification_integrity['email_provider'] = provider_type
            notification_integrity['smtp_circuit_breaker'] = cb_state
            notification_integrity['consecutive_failures'] = cb_status['consecutive_failures']
        except Exception:
            pass

        return {
            'status': 'healthy' if not issues else 'issues_found',
            'issues_count': len(issues),
            'warnings_count': len(warnings),
            'issues': issues[:20],
            'warnings': warnings[:20],
            'financial_reconciliation': financial_summary,
            'data_counts': {
                'policies': len(self._policies),
                'active_policies': len([p for p in self._policies.values() if _status_eq(p, 'active')]),
                'customers': len(self._customers),
                'claims': len(self._claims),
                'billing_records': len(self._billing),
                'underwriting_apps': len(self._underwriting)
            },
            'actuarial_validation': {
                'source': 'PHINS_ACTUARIAL_TABLES_V1',
                'policies_checked': actuarial_checks['total_checked'],
                'passed': actuarial_checks['passed'],
                'needs_review': actuarial_checks['failed'],
                'status': 'COMPLIANT' if actuarial_checks['failed'] == 0 else 'REVIEW_NEEDED',
                'details': actuarial_checks['details'][:10]
            },
            'notification_integrity': notification_integrity,
            'validated_at': datetime.now().isoformat()
        }
    
    def get_dashboard_summary(self, dashboard_type: str) -> Dict[str, Any]:
        """
        Get data summary for a specific dashboard type.
        
        Dashboard types: 'accountant', 'underwriter', 'claims', 'admin', 'customer'
        """
        base_data = {
            'total_policies': len(self._policies),
            'active_policies': len([p for p in self._policies.values() if _status_eq(p, 'active')]),
            'total_customers': len(self._customers),
            'generated_at': datetime.now().isoformat()
        }
        
        if dashboard_type == 'accountant':
            # Helper to safely get numeric value
            def safe_num(val, default=0):
                if val is None:
                    return default
                try:
                    return float(val)
                except (TypeError, ValueError):
                    return default
            
            # Claims paid cash: customer ledger is authoritative when attached.
            # Fall back to disbursed claim records (paid/closed only — not approved).
            claims_paid_amt = 0
            used_ledger_cash = False
            if self._ledger_attached:
                try:
                    from services.financial_unification_service import CLAIM_CASH_TYPES, ledger_cash_total
                    claims_paid_amt = ledger_cash_total(
                        self._transaction_ledger.values(), CLAIM_CASH_TYPES
                    )['total']
                    used_ledger_cash = True
                except Exception:
                    used_ledger_cash = False
                    claims_paid_amt = 0
            if not used_ledger_cash:
                for c in self._claims.values():
                    status = (c.get('status') or '').lower()
                    if status in ['paid', 'closed']:
                        amt = safe_num(c.get('paid_amount')) or safe_num(c.get('approved_amount')) or 0
                        claims_paid_amt += amt
            
            # Claims pending - sum of claimed amounts for pending/under review claims
            claims_pending_amt = 0
            for c in self._claims.values():
                status = (c.get('status') or '').lower().replace(' ', '_')
                if status in ['pending', 'under_review']:
                    claims_pending_amt += safe_num(c.get('claimed_amount', 0))
            
            # Calculate total annual revenue from active policies
            total_revenue = 0
            for p in self._policies.values():
                if _status_eq(p, 'active'):
                    premium = safe_num(p.get('annual_premium', 0))
                    if premium == 0:
                        # Estimate from coverage if no premium set (3% of coverage)
                        coverage = safe_num(p.get('coverage_amount', 0))
                        premium = coverage * 0.03
                    total_revenue += premium
            
            # Calculate billing totals
            total_billed = sum(safe_num(b.get('amount_due', b.get('amount', 0))) for b in self._billing.values())
            cumulative_data = self.calculate_cumulative_premium()
            total_collected = cumulative_data['total']
            
            # Outstanding A/R - only for unpaid bills
            outstanding_ar = 0
            for b in self._billing.values():
                if (b.get('status') or '').lower() != 'paid':
                    due = safe_num(b.get('amount_due', b.get('amount', 0)))
                    paid = safe_num(b.get('amount_paid', 0))
                    outstanding_ar += max(0, due - paid)
            
            return {
                **base_data,
                'total_revenue': total_revenue,
                'total_billed': total_billed,
                'total_collected': total_collected,
                'cumulative_premium': total_collected,
                'cumulative_premium_breakdown': {
                    'from_bills': cumulative_data['from_bills'],
                    'from_ledger': cumulative_data['ledger_unbilled_total'],
                    'from_allocations': cumulative_data.get('from_allocations', 0),
                },
                'outstanding_ar': outstanding_ar,
                'claims_paid': claims_paid_amt,
                'claims_pending': claims_pending_amt,
            }
        
        elif dashboard_type == 'underwriter':
            def uw_status(u, status):
                return (u.get('status') or '').lower() == status.lower()
            
            return {
                **base_data,
                'pending_applications': len([u for u in self._underwriting.values() if uw_status(u, 'pending')]),
                'approved_count': len([u for u in self._underwriting.values() if uw_status(u, 'approved')]),
                'rejected_count': len([u for u in self._underwriting.values() if uw_status(u, 'rejected')]),
                'total_coverage_pending': sum(self._policies.get(u.get('policy_id'), {}).get('coverage_amount', 0)
                                             for u in self._underwriting.values() if uw_status(u, 'pending')),
            }
        
        elif dashboard_type == 'claims':
            def claim_status(c, *statuses):
                s = (c.get('status') or '').lower()
                return s in [st.lower() for st in statuses]
            
            return {
                **base_data,
                'pending_claims': len([c for c in self._claims.values() if claim_status(c, 'pending', 'Pending')]),
                'under_review': len([c for c in self._claims.values() if claim_status(c, 'under_review', 'Under Review', 'medical_assessment')]),
                'approved_unpaid': len([c for c in self._claims.values() if claim_status(c, 'approved', 'Approved')]),
                'paid_claims': len([c for c in self._claims.values() if claim_status(c, 'paid', 'Paid')]),
                'total_pending_amount': sum(c.get('claimed_amount', 0) for c in self._claims.values() 
                                           if claim_status(c, 'pending', 'under_review', 'Pending', 'Under Review')),
                'total_paid_amount': sum(c.get('approved_amount', c.get('paid_amount', 0)) for c in self._claims.values() 
                                        if claim_status(c, 'paid', 'Paid')),
            }
        
        elif dashboard_type == 'admin':
            integrity = self.validate_data_integrity()
            return {
                **base_data,
                'data_integrity': integrity['status'],
                'issues_count': integrity['issues_count'],
                'warnings_count': integrity['warnings_count'],
                'financial_summary': integrity['financial_reconciliation'],
            }
        
        return base_data


# Singleton instance getter
def get_financial_reporting_service(policies, claims, billing, customers, underwriting,
                                    transaction_ledger=None, health_wallets=None) -> FinancialReportingService:
    """Get financial reporting service instance"""
    return FinancialReportingService(
        policies=policies,
        claims=claims,
        billing=billing,
        customers=customers,
        underwriting=underwriting,
        transaction_ledger=transaction_ledger,
        health_wallets=health_wallets,
    )


__all__ = ['FinancialReportingService', 'get_financial_reporting_service']
