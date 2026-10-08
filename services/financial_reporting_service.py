"""
Financial Reporting Service for PHINS Insurance Platform

Provides comprehensive financial reporting with:
- Long-term actuarial projections (25+ years)
- ADL (Activities of Daily Living) risk assessment
- Savings allocation and investment forecasting
- Lump sum benefit calculations
- Data integrity validation (bottom-up)
- Cross-dashboard data validation

ADL figures are the PHINS internal underwriting score (1-10). Score 10
is a fully disabled customer and meets global ADL 3+. Score 5 is the
×1.0 multiplier-table unit. It is not the average internal score and
not a default health finding. A missing assessment stays unassessed.
A scenario priced at score 5 discloses that input; it does not relabel
the premium with a different score.
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


def _risk_band(score: Any) -> str:
    """Map a policy risk label onto the four portfolio bands.

    Missing scores stay ``medium`` (the historical default). Any other
    label stays in ``very_high``, which is where the portfolio report
    already sent unrecognised scores. Spelling and case are normalised
    so ``Very High`` and ``very_high`` count as the same band.
    """
    if score is None:
        raw = 'medium'
    else:
        raw = str(score).strip().lower().replace('-', ' ').replace('_', ' ')
        raw = ' '.join(raw.split())
    if raw == 'low':
        return 'low'
    if raw == 'medium':
        return 'medium'
    if raw == 'high':
        return 'high'
    if raw in ('very high', 'veryhigh'):
        return 'very_high'
    return 'very_high'


def _policy_coverage(policy: Dict) -> float:
    """Face amount of a policy, whichever key it is stored under."""
    coverage = policy.get('coverage_amount')
    if coverage is None:
        coverage = policy.get('coverage', 0)
    return coverage or 0


# Planning-case defaults. Adjustable factors must stay inside these bounds
# so a forecast cannot be driven by an unbounded rate. Omitted factors use
# the default and reproduce the historical projection.
FORECAST_FACTOR_BOUNDS = {
    'growth_rate': (0.0, 0.50, 0.10),
    'inflation_rate': (-0.05, 0.20, 0.03),
    'claim_rate': (0.0, 0.50, 0.02),
    'lapse_rate': (0.0, 0.40, 0.03),
}


def _coerce_forecast_factor(name: str, value: Any) -> Tuple[float, str]:
    """Return (rate, source) for one forecast factor.

    ``source`` is ``default`` when the caller omitted the factor and
    ``request`` when a number inside the published bounds was supplied.
    """
    lo, hi, default = FORECAST_FACTOR_BOUNDS[name]
    if value is None or value == '':
        return default, 'default'
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f'{name} must be a number between {lo} and {hi}')
    if math.isnan(number) or math.isinf(number) or number < lo or number > hi:
        raise ValueError(f'{name} must be between {lo} and {hi}')
    return number, 'request'


# Mortality, disability, ADL multipliers, lapse, and underwriting gates are
# read from ActuarialTablesStore. This module does not keep a second copy.
# Investment-return scenarios are projection assumptions, not a rate table.
INVESTMENT_RETURNS = {
    'conservative': 0.04,   # 4% annual
    'moderate': 0.06,       # 6% annual
    'aggressive': 0.08,     # 8% annual
}


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
    
    def _actuarial_store(self):
        """Central actuarial tables — same store the kernel and actuary dashboard use."""
        try:
            from services.actuarial_service import get_actuarial_store
            return get_actuarial_store()
        except Exception:
            return None

    def get_mortality_rate(self, age: int) -> float:
        """Mortality q(x) from the actuarial store. Uncovered ages are 0."""
        store = self._actuarial_store()
        if store is None:
            return 0.0
        try:
            return float(store.get_mortality_rate(age))
        except Exception:
            return 0.0

    def get_disability_incidence_rate(self, age: int) -> float:
        """Disability incidence i(x) from the actuarial store. Uncovered ages are 0."""
        store = self._actuarial_store()
        if store is None:
            return 0.0
        try:
            return float(store.get_disability_rate(age))
        except Exception:
            return 0.0

    def get_adl_mortality_multiplier(self, adl_level: int) -> float:
        """Mortality multiplier for an internal score, from the actuarial store."""
        adl_level = max(1, min(10, adl_level))
        store = self._actuarial_store()
        if store is None:
            return 1.0
        try:
            return float(store.get_adl_mortality_multiplier(adl_level))
        except Exception:
            return 1.0

    def get_adl_disability_incidence_multiplier(self, adl_level: int) -> float:
        """Disability incidence multiplier for an internal score, from the store."""
        adl_level = max(1, min(10, adl_level))
        store = self._actuarial_store()
        if store is None:
            return 1.0
        try:
            return float(store.get_adl_disability_multiplier(adl_level))
        except Exception:
            return 1.0

    def get_adl_benefit_percentage(self, adl_level: int) -> float:
        """ADL benefit percentage from the actuarial store. Missing rows are 0."""
        adl_level = max(1, min(10, adl_level))
        store = self._actuarial_store()
        if store is None:
            return 0.0
        try:
            return float(store.get_adl_benefit_pct(adl_level))
        except Exception:
            return 0.0
    
    def get_adl_multiplier(self, adl_level: int) -> float:
        """Legacy method - returns mortality multiplier for backward compatibility"""
        return self.get_adl_mortality_multiplier(adl_level)
    
    def get_lapse_rate(self, policy_year: int) -> float:
        """Lapse rate from the actuarial store. A missing year is 0."""
        store = self._actuarial_store()
        if store is None:
            return 0.0
        try:
            return float(store.get_lapse_rate(policy_year))
        except Exception:
            return 0.0

    def _underwriting_config(self):
        store = self._actuarial_store()
        return getattr(store, 'config', None) if store is not None else None

    def check_underwriting_eligibility(self, adl_level: int, coverage: float,
                                       age: Optional[int] = None) -> Dict[str, Any]:
        """Eligibility from the live underwriting config, the same gates as the simulator."""
        adl_level = max(1, min(10, int(adl_level)))
        cfg = self._underwriting_config()
        result = {
            'eligible': False,
            'adl_level': adl_level,
            'requested_coverage': coverage,
            'approved_coverage': 0,
            'loading': None,
            'exclude_disability': False,
            'coverage_reduced': False,
        }
        if cfg is None:
            result['decline_reason'] = 'underwriting_config_unavailable'
            return result
        if age is not None:
            from services.actuarial_service import acceptance_age_cap
            cap = acceptance_age_cap(cfg)
            if int(age) > cap:
                result['decline_reason'] = f'Age exceeds maximum acceptance age {cap}'
                return result
        if adl_level >= int(cfg.decline_threshold):
            result['decline_reason'] = (
                f'ADL {adl_level} exceeds threshold {int(cfg.decline_threshold)}'
            )
            return result
        limits = cfg.coverage_limits or {}
        max_cov = limits.get(adl_level)
        if max_cov is None:
            max_cov = limits.get(str(adl_level))
        loading = (cfg.loadings or {}).get(adl_level, (cfg.loadings or {}).get(str(adl_level), 0.0))
        result['eligible'] = True
        result['loading'] = float(loading or 0.0)
        result['exclude_disability'] = adl_level >= int(cfg.disability_exclusion_threshold)
        if max_cov is not None and float(coverage) > float(max_cov):
            result['approved_coverage'] = float(max_cov)
            result['coverage_reduced'] = True
            result['reduction_reason'] = (
                f'ADL {adl_level} limited to ${float(max_cov):,.0f} coverage'
            )
        else:
            result['approved_coverage'] = float(coverage)
        return result
    
    def calculate_premium(self, coverage: float, age: int, adl_level: int,
                         savings_pct: float, term_years: int,
                         include_profit_margin: bool = True) -> Dict[str, float]:
        """
        Calculate actuarially sound premium via the central pricing kernel.

        Uses the same ``price_application_with_kernel`` path as issuance so
        accountant quotes and billed premiums share one identity.

        Args:
            coverage: Face value of policy
            age: Customer's current age
            adl_level: ADL score (1-10)
            savings_pct: % of coverage allocated to savings (now flows
                directly into the kernel's savings_rate)
            term_years: Policy term in years
            include_profit_margin: Whether to add profit margin (default True)
        """
        # Check underwriting eligibility first (live config, including age).
        uw_check = self.check_underwriting_eligibility(adl_level, coverage, age=int(age))
        if not uw_check['eligible']:
            return {
                'annual_premium': 0,
                'monthly_premium': 0,
                'eligible': False,
                'decline_reason': uw_check['decline_reason'],
                'adl_level': adl_level,
                'customer_age': age
            }
        
        # Use approved coverage (may be reduced for high ADL). The kernel below
        # re-derives the coverage cap, underwriting loading, and disability
        # exclusion from the live actuarial store, so the reported values are
        # taken from the kernel result (not this private FRS table) to keep
        # accountant quotes and issued kernel prices on one identity.
        approved_coverage = uw_check['approved_coverage']

        # Same kernel + persisted Pricing Parameters as issuance.
        from services.pricing_shadow_service import price_application_with_kernel

        kernel = price_application_with_kernel({
            "type": "phins_unified",
            "coverage_amount": approved_coverage,
            "age": int(age),
            "term_years": int(term_years),
            "coverage_years": int(term_years),
            "adl_level": int(adl_level),
            "savings_rate": float(savings_pct or 0.0),
            "risk_score": "medium",
        }) or {}
        if not kernel or float(kernel.get("annual") or 0) <= 0:
            return {
                'annual_premium': 0,
                'monthly_premium': 0,
                'eligible': False,
                'decline_reason': 'kernel_unavailable',
                'adl_level': adl_level,
                'customer_age': age,
            }

        # Underwriting rules the kernel actually applied (from the live store),
        # so the quote does not advertise a loading, exclusion, or coverage that
        # was never used to price the premium.
        underwriting_loading = float(kernel.get('underwriting_loading') or 0.0)
        exclude_disability = bool(kernel.get('disability_excluded', False))
        kernel_coverage_cap = kernel.get('adl_coverage_cap')
        if kernel_coverage_cap is not None:
            approved_coverage = min(float(approved_coverage), float(kernel_coverage_cap))
        coverage_reduced = float(approved_coverage) < float(coverage)

        comps = kernel.get("components") or {}
        adl_mort_mult = float(kernel.get('adl_mortality_multiplier') or 1.0)
        adl_dis_mult = float(kernel.get('adl_disability_multiplier') or 1.0)
        mortality_cost_pv = float(comps.get('pv_mortality_claims') or 0)
        disability_cost_pv = float(comps.get('pv_disability_claims') or 0)
        total_risk_cost_pv = mortality_cost_pv + disability_cost_pv
        mortality_premium_annual = float(kernel.get('mortality_premium_annual') or 0)
        disability_premium_annual = float(kernel.get('disability_premium_annual') or 0)
        risk_premium_annual = float(kernel.get('risk_premium_annual') or 0)
        savings_premium_annual = float(kernel.get('savings_premium_annual') or 0)
        expense_loading = float(comps.get('expense_loading_annual') or 0)
        profit_margin = float(comps.get('profit_margin_annual') or 0)
        total_annual = float(kernel.get('annual') or 0)
        monthly_premium = float(kernel.get('monthly') or 0)
        savings_allocation = approved_coverage * float(savings_pct or 0.0)
        if not include_profit_margin and total_annual:
            total_annual = round(total_annual - profit_margin, 2)
            monthly_premium = round(total_annual / 12.0, 2)
            profit_margin = 0.0

        return {
            'annual_premium': total_annual,
            'monthly_premium': monthly_premium,
            'risk_component': risk_premium_annual,
            'mortality_component': mortality_premium_annual,
            'disability_component': disability_premium_annual,
            'savings_component': savings_premium_annual,
            'expense_loading': expense_loading,
            'profit_margin': profit_margin,
            'coverage': approved_coverage,
            'original_coverage': coverage,
            'coverage_reduced': coverage_reduced,
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
            'pricing_kernel_integrity_hash': kernel.get('integrity_hash'),
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
        if not premium_calc.get('eligible'):
            # Declined quotes (age gate, ADL, unavailable kernel) have no
            # premium breakdown to project.
            return []
        annual_premium = premium_calc['annual_premium']
        risk_component = premium_calc['risk_component']
        savings_component = premium_calc['savings_component']
        approved_face = float(premium_calc.get('coverage') or coverage)
        
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
            
            # Attained-age life and disability sums from Pricing Parameters.
            sums = self._benefit_sums(approved_face, age + year - 1)
            death_benefit = sums['life_sum'] + savings_fund
            adl_claim_payout = self._calculate_adl_benefit(
                approved_face, adl_level, year, issue_age=age,
            )
            
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
    
    def _benefit_sums(self, coverage: float, age: int) -> Dict[str, float]:
        from services.actuarial_service import contract_benefit_sums_from_config
        return contract_benefit_sums_from_config(coverage, int(age), self._underwriting_config())

    def _calculate_adl_benefit(self, coverage: float, adl_level: int, policy_year: int,
                               issue_age: Optional[int] = None) -> float:
        """Disability sum at the attained age from the contract bands.

        Exclusion and decline follow the live underwriting config. Without an
        issue age the pre-band sums apply.
        """
        cfg = self._underwriting_config()
        level = int(adl_level)
        if cfg is not None and level >= int(cfg.disability_exclusion_threshold):
            return 0.0
        if cfg is not None and level >= int(cfg.decline_threshold):
            return 0.0
        if issue_age is None:
            attained = 0
        else:
            attained = int(issue_age) + max(0, int(policy_year) - 1)
        return float(self._benefit_sums(coverage, attained)['disability_sum'])
    
    # ==========================================================================
    # LUMP SUM CALCULATIONS
    # ==========================================================================
    
    def calculate_lump_sum_options(self, coverage: float, savings_pct: float,
                                   adl_level: int, years_paid: int,
                                   total_premiums_paid: float,
                                   age: Optional[int] = None) -> Dict[str, Any]:
        """
        Lump-sum options using the attained-age life sum, not a share of face.
        """
        savings_accumulated = total_premiums_paid * savings_pct * 1.06 ** years_paid
        # Attained age follows the projection convention: issue_age + policy_year - 1.
        attained = int(age) + max(0, int(years_paid) - 1) if age is not None else 0
        life_sum = float(self._benefit_sums(coverage, attained)['life_sum'])
        insured = life_sum + savings_accumulated

        options = {
            'death_benefit_lump_sum': round(insured, 2),
            'terminal_illness_lump_sum': round(life_sum * 0.9, 2),
            'adl_claim_lump_sum': round(self._calculate_adl_benefit(
                coverage, adl_level, years_paid, issue_age=age,
            ), 2),
            'surrender_value': round(savings_accumulated * (0.95 if years_paid >= 5 else 0.85), 2),
            'maturity_value': round(insured, 2),
            'annuity_conversion': {
                '10_year': round(insured / 120, 2),
                '20_year': round(insured / 240, 2),
                'lifetime': round(insured / 300, 2),
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
        risk_exposure = {'low': 0.0, 'medium': 0.0, 'high': 0.0, 'very_high': 0.0}
        coverage_by_type = {}
        age_distribution = {}
        
        policies_data = []
        
        for policy_id, policy in self._policies.items():
            if policy.get('status') != 'active':
                continue
                
            coverage = _policy_coverage(policy)
            annual_premium = policy.get('annual_premium', 0)
            policy_type = policy.get('type') or policy.get('policy_type') or 'life'
            risk_score = policy.get('risk_score', 'medium')
            risk_band = _risk_band(risk_score)

            total_coverage += coverage
            total_premiums += annual_premium
            
            # Get customer age
            customer_id = policy.get('customer_id')
            customer = self._customers.get(customer_id, {})
            age = self._calculate_age(customer.get('dob'))
            
            # Risk distribution — same bands as before. Exposure is the
            # coverage already added into total_coverage, split by band.
            risk_distribution[risk_band] += 1
            risk_exposure[risk_band] += float(coverage or 0)
            
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
                # Distinct from PortfolioSimulator.risk_metrics.reserve_requirement
                # (1.5 × PV of expected claims); this is a capital indication.
                'reserve_requirement_basis': 'coverage_x0.05_plus_savings_liability',
                'reserve_requirement_label': 'Capital indication (5% of coverage + savings liability)',
                'solvency_ratio': round(total_premiums * 3 / max(total_claims_liability + total_savings_liability, 1), 2)
            },
            'risk_distribution': risk_distribution,
            # Coverage by the same band as risk_distribution. Rounded per
            # band; total_coverage remains the unsplit sum.
            'risk_exposure': {band: round(amount, 2) for band, amount in risk_exposure.items()},
            'coverage_by_type': coverage_by_type,
            'age_distribution': age_distribution,
            'generated_at': datetime.now().isoformat()
        }
    
    def generate_forecast_report(
        self,
        years: int = 25,
        customer_id: Optional[str] = None,
        growth_rate: Optional[float] = None,
        inflation_rate: Optional[float] = None,
        claim_rate: Optional[float] = None,
        lapse_rate: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Generate a long-term forecast from the current active book.

        Omitted factors use the planning-case defaults (10% new-business
        growth, 3% premium inflation, 2% claim incidence, 3% lapse) and
        reproduce the historical projection. Supplied factors are scenario
        inputs only: they never rewrite premiums, bills, or the ledger.

        ``customer_id`` limits the opening book to that customer's active
        policies. When that book is empty the projection is empty rather
        than substituted with the portfolio.
        """
        try:
            years = int(years)
        except (TypeError, ValueError):
            raise ValueError('years must be an integer between 1 and 50')
        if years < 1 or years > 50:
            raise ValueError('years must be an integer between 1 and 50')

        new_policy_growth, growth_source = _coerce_forecast_factor('growth_rate', growth_rate)
        premium_inflation, inflation_source = _coerce_forecast_factor('inflation_rate', inflation_rate)
        claim_incidence, claim_source = _coerce_forecast_factor('claim_rate', claim_rate)
        lapse, lapse_source = _coerce_forecast_factor('lapse_rate', lapse_rate)
        factor_source = (
            'default'
            if {growth_source, inflation_source, claim_source, lapse_source} == {'default'}
            else 'request'
        )

        active = [
            p for p in self._policies.values()
            if _status_eq(p, 'active') and (
                not customer_id or str(p.get('customer_id') or '') == str(customer_id)
            )
        ]
        current_premiums = sum(p.get('annual_premium', 0) for p in active)
        current_policies = len(active)
        opening_coverage = sum(_policy_coverage(p) for p in active)

        assumptions = {
            'new_policy_growth_rate': f"{new_policy_growth * 100}%",
            'premium_inflation_rate': f"{premium_inflation * 100}%",
            'claim_rate': f"{claim_incidence * 100}%",
            'lapse_rate': f"{lapse * 100}%",
            'avg_claim_amount': round(
                (opening_coverage / max(current_policies, 1)) * 0.3, 2
            ),
            'applied': {
                'growth_rate': new_policy_growth,
                'inflation_rate': premium_inflation,
                'claim_rate': claim_incidence,
                'lapse_rate': lapse,
                'source': factor_source,
            },
            'basis': (
                'Scenario on the current active book. Factors change this '
                'projection only and do not post to premiums, bills, or the ledger.'
            ),
        }

        empty_customer = bool(customer_id) and current_policies == 0
        if empty_customer:
            return {
                'forecast_years': years,
                'customer_id': str(customer_id),
                'empty_reason': 'no_active_policies',
                'assumptions': assumptions,
                'projections': [],
                'summary': {
                    'year_25_policies': 0,
                    'year_25_revenue': 0,
                    'year_25_profit': 0,
                    'terminal_year': years,
                    'terminal_policies': 0,
                    'terminal_revenue': 0,
                    'terminal_profit': 0,
                },
                'opening_book': {
                    'active_policies': 0,
                    'annual_premium': 0.0,
                    'customer_id': str(customer_id),
                },
                'generated_at': datetime.now().isoformat(),
            }

        # The loop uses the unrounded average so a default run matches the
        # historical projection. The displayed assumption stays rounded.
        avg_claim_unrounded = (opening_coverage / max(current_policies, 1)) * 0.3

        yearly_projections = []
        cumulative_revenue = 0.0
        cumulative_claims = 0.0
        # The count is carried unrounded and rounded only for display. A
        # truncated step wipes a small book (one policy steps to
        # int(1 * 0.97) == 0) while premiums keep inflating.
        policies = float(current_policies)
        premiums = current_premiums

        for year in range(1, years + 1):
            new_policies = policies * new_policy_growth
            policies = (policies + new_policies) * (1 - lapse)

            premiums = premiums * (1 + premium_inflation) + new_policies * (premiums / max(current_policies, 1))

            expected_claims = policies * claim_incidence * avg_claim_unrounded

            cumulative_revenue += premiums
            cumulative_claims += expected_claims

            yearly_projections.append({
                'year': year,
                'projected_date': (datetime.now() + timedelta(days=365 * year)).strftime('%Y-%m-%d'),
                'active_policies': int(round(policies)),
                'annual_premium_revenue': round(premiums, 2),
                'expected_claims': round(expected_claims, 2),
                'net_income': round(premiums - expected_claims, 2),
                'cumulative_revenue': round(cumulative_revenue, 2),
                'cumulative_claims': round(cumulative_claims, 2),
                'cumulative_profit': round(cumulative_revenue - cumulative_claims, 2)
            })

        last = yearly_projections[-1] if yearly_projections else None
        report = {
            'forecast_years': years,
            'assumptions': assumptions,
            'projections': yearly_projections,
            'summary': {
                'year_25_policies': last['active_policies'] if last else 0,
                'year_25_revenue': last['cumulative_revenue'] if last else 0,
                'year_25_profit': last['cumulative_profit'] if last else 0,
                'terminal_year': years,
                'terminal_policies': last['active_policies'] if last else 0,
                'terminal_revenue': last['cumulative_revenue'] if last else 0,
                'terminal_profit': last['cumulative_profit'] if last else 0,
            },
            'opening_book': {
                'active_policies': current_policies,
                'annual_premium': round(float(current_premiums or 0), 2),
                'customer_id': str(customer_id) if customer_id else None,
            },
            'generated_at': datetime.now().isoformat()
        }
        if customer_id:
            report['customer_id'] = str(customer_id)
        # avg_claim_amount on assumptions is the rounded display figure.
        # Keep the key equal to the historical rounded value.
        assumptions['avg_claim_amount'] = round(avg_claim_unrounded, 2)
        return report
    
    def generate_customer_projection(self, customer_id: str = None, 
                                     coverage: float = 250000,
                                     savings_pct: float = 0.50,
                                     adl_level: int = 5,
                                     term_years: int = 25,
                                     age: int = 35) -> Dict[str, Any]:
        """
        Generate detailed projection for a specific customer scenario.
        
        Default: $250,000 coverage, 50% savings, internal score 5 as a
        pricing input (not the average), 25 years.
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
            coverage, savings_pct, adl_level, years_paid, total_premiums, age=age,
        )
        
        from services.adl_mapping import INTERNAL_UNDERWRITING_SCORE_DISCLAIMER
        score_status = self._get_adl_description(adl_level)
        return {
            'scenario': {
                'coverage': coverage,
                'savings_allocation': f"{savings_pct * 100}%",
                'adl_level': adl_level,
                'adl_risk': score_status,
                'adl_status': score_status,
                'adl_basis': 'scenario_input',
                'adl_is_health_status': False,
                'internal_score_is_average': False,
                'internal_score_disclaimer': INTERNAL_UNDERWRITING_SCORE_DISCLAIMER,
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
        """Internal-score status. Score 5 is not described as the average."""
        from services.adl_mapping import published_adl_label
        return published_adl_label(adl_level)
    
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
        
        # A risk band is not an ADL finding. "medium" must not be reported
        # as clinical ADL 5. Only a resolved clinical level is a health status.
        from services.adl_mapping import (
            INTERNAL_UNDERWRITING_SCORE_DISCLAIMER,
            SOURCE_UNSPECIFIED,
            internal_score_status,
            resolve_adl_evidence,
        )

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
                
                risk_score = policy.get('risk_score', 'medium')
                resolution = resolve_adl_evidence(
                    adl_level=policy.get('adl_level'),
                    adl_level_source=policy.get('adl_level_source'),
                    daily_function=policy.get('daily_function'),
                    health_score=policy.get('health_score'),
                )
                clinical_adl = (
                    None
                    if resolution.source == SOURCE_UNSPECIFIED
                    else resolution.clinical_level
                )
                # Get coverage and premium
                coverage = policy.get('coverage_amount', 0)
                stored_premium = policy.get('annual_premium', 0)
                
                # Premium-ratio check uses the issued premium and coverage only.
                # It does not invent an ADL multiplier from the risk band.
                if coverage > 0 and stored_premium > 0:
                    expected_ratio = stored_premium / coverage  # Premium per dollar of coverage
                    
                    # Expected ratio should be higher for older/higher-risk customers
                    # Typical range: 0.002 (low risk) to 0.015 (high risk)
                    min_expected_ratio = 0.001
                    max_expected_ratio = 0.02
                    detail = {
                        'policy_id': policy_id,
                        'risk_score': risk_score,
                        'adl_level': clinical_adl,
                        'adl_status': (
                            internal_score_status(clinical_adl)
                            if clinical_adl is not None else None
                        ),
                        'adl_basis': resolution.source,
                        'adl_is_health_status': clinical_adl is not None,
                        # One policy score is never the book's average.
                        'internal_score_is_average': False,
                        'internal_score_disclaimer': (
                            INTERNAL_UNDERWRITING_SCORE_DISCLAIMER
                            if clinical_adl is not None else None
                        ),
                        'premium_ratio': round(expected_ratio, 6),
                    }
                    
                    if min_expected_ratio <= expected_ratio <= max_expected_ratio:
                        actuarial_checks['passed'] += 1
                        detail['status'] = 'PASS'
                        actuarial_checks['details'].append(detail)
                    else:
                        actuarial_checks['failed'] += 1
                        detail['status'] = 'REVIEW'
                        detail['note'] = (
                            f"Premium ratio {expected_ratio:.4f} outside expected range"
                        )
                        actuarial_checks['details'].append(detail)
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
            
            # Calculate billing totals. Collected cash identity is the customer
            # ledger when attached; bill records remain in total_billed / A/R.
            total_billed = sum(safe_num(b.get('amount_due', b.get('amount', 0))) for b in self._billing.values())
            cumulative_data = self.calculate_cumulative_premium()
            total_collected = cumulative_data['total']
            ledger_premium_collected = None
            if self._ledger_attached:
                try:
                    from services.financial_unification_service import PREMIUM_CASH_TYPES, ledger_cash_total
                    ledger_premium_collected = ledger_cash_total(
                        self._transaction_ledger.values(), PREMIUM_CASH_TYPES
                    )['total']
                    total_collected = ledger_premium_collected
                except Exception:
                    ledger_premium_collected = None
            
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
                'ledger_premium_collected': ledger_premium_collected if ledger_premium_collected is not None else total_collected,
                'ledger_claims_paid': claims_paid_amt,
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
            
            paid_amount = 0.0
            if self._ledger_attached:
                try:
                    from services.financial_unification_service import CLAIM_CASH_TYPES, ledger_cash_total
                    paid_amount = ledger_cash_total(
                        self._transaction_ledger.values(), CLAIM_CASH_TYPES
                    )['total']
                except Exception:
                    paid_amount = sum(
                        c.get('approved_amount', c.get('paid_amount', 0)) for c in self._claims.values()
                        if claim_status(c, 'paid', 'Paid')
                    )
            else:
                paid_amount = sum(
                    c.get('approved_amount', c.get('paid_amount', 0)) for c in self._claims.values()
                    if claim_status(c, 'paid', 'Paid')
                )
            return {
                **base_data,
                'pending_claims': len([c for c in self._claims.values() if claim_status(c, 'pending', 'Pending')]),
                'under_review': len([c for c in self._claims.values() if claim_status(c, 'under_review', 'Under Review', 'medical_assessment')]),
                'approved_unpaid': len([c for c in self._claims.values() if claim_status(c, 'approved', 'Approved')]),
                'paid_claims': len([c for c in self._claims.values() if claim_status(c, 'paid', 'Paid')]),
                'total_pending_amount': sum(c.get('claimed_amount', 0) for c in self._claims.values() 
                                           if claim_status(c, 'pending', 'under_review', 'Pending', 'Under Review')),
                'total_paid_amount': paid_amount,
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
