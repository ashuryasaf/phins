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
# ACTUARIAL CONSTANTS & TABLES
# ==============================================================================

# Mortality rates by age bracket (per 1000 lives per year)
MORTALITY_RATES = {
    (0, 30): 0.5,
    (30, 40): 1.2,
    (40, 50): 2.5,
    (50, 60): 5.0,
    (60, 70): 12.0,
    (70, 80): 30.0,
    (80, 100): 75.0,
}

# ADL Risk multipliers (1-10 scale, 5 is baseline medium risk)
ADL_RISK_MULTIPLIERS = {
    1: 0.6,   # Very low risk - fully independent
    2: 0.75,
    3: 0.85,
    4: 0.95,
    5: 1.0,   # Medium risk (baseline)
    6: 1.15,
    7: 1.35,
    8: 1.6,
    9: 1.9,
    10: 2.5,  # Very high risk - total dependence
}

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


class FinancialReportingService:
    """
    Comprehensive financial reporting service with actuarial calculations.
    """
    
    def __init__(self, policies: Dict, claims: Dict, billing: Dict, 
                 customers: Dict, underwriting: Dict):
        self._policies = policies
        self._claims = claims
        self._billing = billing
        self._customers = customers
        self._underwriting = underwriting
    
    # ==========================================================================
    # ACTUARIAL CALCULATIONS
    # ==========================================================================
    
    def get_mortality_rate(self, age: int) -> float:
        """Get mortality rate per 1000 lives for given age"""
        for (low, high), rate in MORTALITY_RATES.items():
            if low <= age < high:
                return rate / 1000.0
        return 0.075  # Default for very old ages
    
    def get_adl_multiplier(self, adl_level: int) -> float:
        """Get risk multiplier based on ADL level (1-10)"""
        adl_level = max(1, min(10, adl_level))
        return ADL_RISK_MULTIPLIERS.get(adl_level, 1.0)
    
    def get_lapse_rate(self, policy_year: int) -> float:
        """Get lapse rate for given policy year"""
        if policy_year in LAPSE_RATES:
            return LAPSE_RATES[policy_year]
        for key, rate in LAPSE_RATES.items():
            if isinstance(key, tuple) and key[0] <= policy_year <= key[1]:
                return rate
        return 0.01
    
    def calculate_premium(self, coverage: float, age: int, adl_level: int,
                         savings_pct: float, term_years: int) -> Dict[str, float]:
        """
        Calculate actuarially sound premium based on:
        - Coverage amount
        - Customer age
        - ADL risk level
        - Savings allocation percentage
        - Policy term in years
        
        Returns breakdown of premium components.
        """
        # Base mortality cost (PV of expected death benefit)
        mortality_cost = 0.0
        for year in range(1, term_years + 1):
            current_age = age + year - 1
            qx = self.get_mortality_rate(current_age)
            adl_mult = self.get_adl_multiplier(adl_level)
            adjusted_qx = qx * adl_mult
            
            # Probability of surviving to year, then dying
            px_prev = math.prod([(1 - self.get_mortality_rate(age + y) * self.get_adl_multiplier(adl_level)) 
                                 for y in range(year - 1)])
            death_prob = px_prev * adjusted_qx
            
            # Lapse-adjusted probability
            lapse_survival = math.prod([(1 - self.get_lapse_rate(y + 1)) for y in range(year)])
            adjusted_death_prob = death_prob * lapse_survival
            
            # Discount death benefit to present value
            discount_factor = (1 + DISCOUNT_RATE) ** (-year)
            mortality_cost += coverage * adjusted_death_prob * discount_factor
        
        # Risk premium (mortality cost spread over term)
        risk_premium_annual = mortality_cost / term_years
        
        # Savings component (target accumulation)
        savings_allocation = coverage * savings_pct
        savings_premium_annual = savings_allocation / term_years
        
        # Expense loading (15% of risk premium)
        expense_loading = risk_premium_annual * 0.15
        
        # Total annual premium
        total_annual = risk_premium_annual + savings_premium_annual + expense_loading
        
        return {
            'annual_premium': round(total_annual, 2),
            'monthly_premium': round(total_annual / 12, 2),
            'risk_component': round(risk_premium_annual, 2),
            'savings_component': round(savings_premium_annual, 2),
            'expense_loading': round(expense_loading, 2),
            'coverage': coverage,
            'savings_target': round(savings_allocation, 2),
            'term_years': term_years,
            'adl_level': adl_level,
            'customer_age': age
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
        
        # Claims liability
        for claim_id, claim in self._claims.items():
            if claim.get('status') in ['pending', 'under_review', 'approved']:
                total_claims_liability += claim.get('claimed_amount', 0)
        
        return {
            'summary': {
                'total_policies': len([p for p in self._policies.values() if p.get('status') == 'active']),
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
        Generate long-term forecast for the portfolio.
        """
        current_premiums = sum(p.get('annual_premium', 0) for p in self._policies.values() 
                               if p.get('status') == 'active')
        current_policies = len([p for p in self._policies.values() if p.get('status') == 'active'])
        
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
                
                # Get their policy data if exists
                for policy in self._policies.values():
                    if policy.get('customer_id') == customer_id and policy.get('status') == 'active':
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
        """
        issues = []
        warnings = []
        
        # 1. Policy validation
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
            
            if uw.get('status') == 'approved':
                policy = self._policies.get(policy_id, {})
                if policy.get('status') not in ['active', 'pending_billing']:
                    warnings.append(f"Underwriting {uw_id}: Approved but policy status is {policy.get('status')}")
        
        # 5. Financial reconciliation
        total_premiums_expected = sum(p.get('annual_premium', 0) for p in self._policies.values() 
                                      if p.get('status') == 'active')
        total_billed = sum(b.get('amount_due', b.get('amount', 0)) for b in self._billing.values())
        total_paid = sum(b.get('amount_paid', 0) for b in self._billing.values())
        total_claims_approved = sum(c.get('approved_amount', 0) for c in self._claims.values() 
                                    if c.get('status') in ['approved', 'paid'])
        
        financial_summary = {
            'total_expected_premiums': round(total_premiums_expected, 2),
            'total_billed': round(total_billed, 2),
            'total_collected': round(total_paid, 2),
            'collection_rate': round(total_paid / max(total_billed, 1) * 100, 2),
            'total_claims_approved': round(total_claims_approved, 2),
            'loss_ratio': round(total_claims_approved / max(total_paid, 1) * 100, 2)
        }
        
        return {
            'status': 'healthy' if not issues else 'issues_found',
            'issues_count': len(issues),
            'warnings_count': len(warnings),
            'issues': issues[:20],  # Limit to first 20
            'warnings': warnings[:20],
            'financial_reconciliation': financial_summary,
            'data_counts': {
                'policies': len(self._policies),
                'active_policies': len([p for p in self._policies.values() if p.get('status') == 'active']),
                'customers': len(self._customers),
                'claims': len(self._claims),
                'billing_records': len(self._billing),
                'underwriting_apps': len(self._underwriting)
            },
            'validated_at': datetime.now().isoformat()
        }
    
    def get_dashboard_summary(self, dashboard_type: str) -> Dict[str, Any]:
        """
        Get data summary for a specific dashboard type.
        
        Dashboard types: 'accountant', 'underwriter', 'claims', 'admin', 'customer'
        """
        base_data = {
            'total_policies': len(self._policies),
            'active_policies': len([p for p in self._policies.values() if p.get('status') == 'active']),
            'total_customers': len(self._customers),
            'generated_at': datetime.now().isoformat()
        }
        
        if dashboard_type == 'accountant':
            return {
                **base_data,
                'total_revenue': sum(p.get('annual_premium', 0) for p in self._policies.values() 
                                    if p.get('status') == 'active'),
                'total_billed': sum(b.get('amount_due', b.get('amount', 0)) for b in self._billing.values()),
                'total_collected': sum(b.get('amount_paid', 0) for b in self._billing.values()),
                'outstanding_ar': sum((b.get('amount_due', b.get('amount', 0)) - b.get('amount_paid', 0)) 
                                     for b in self._billing.values() if b.get('status') != 'paid'),
                'claims_paid': sum(c.get('paid_amount', c.get('approved_amount', 0)) 
                                  for c in self._claims.values() if c.get('status') == 'paid'),
                'claims_pending': sum(c.get('claimed_amount', 0) for c in self._claims.values() 
                                     if c.get('status') in ['pending', 'under_review', 'approved']),
            }
        
        elif dashboard_type == 'underwriter':
            return {
                **base_data,
                'pending_applications': len([u for u in self._underwriting.values() 
                                            if u.get('status') == 'pending']),
                'approved_count': len([u for u in self._underwriting.values() 
                                      if u.get('status') == 'approved']),
                'rejected_count': len([u for u in self._underwriting.values() 
                                      if u.get('status') == 'rejected']),
                'total_coverage_pending': sum(self._policies.get(u.get('policy_id'), {}).get('coverage_amount', 0)
                                             for u in self._underwriting.values() if u.get('status') == 'pending'),
            }
        
        elif dashboard_type == 'claims':
            return {
                **base_data,
                'pending_claims': len([c for c in self._claims.values() if c.get('status') == 'pending']),
                'under_review': len([c for c in self._claims.values() if c.get('status') == 'under_review']),
                'approved_unpaid': len([c for c in self._claims.values() if c.get('status') == 'approved']),
                'paid_claims': len([c for c in self._claims.values() if c.get('status') == 'paid']),
                'total_pending_amount': sum(c.get('claimed_amount', 0) for c in self._claims.values() 
                                           if c.get('status') in ['pending', 'under_review']),
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
_service_instance: Optional[FinancialReportingService] = None

def get_financial_reporting_service(policies, claims, billing, customers, underwriting) -> FinancialReportingService:
    """Get or create financial reporting service instance"""
    global _service_instance
    if _service_instance is None:
        _service_instance = FinancialReportingService(
            policies=policies,
            claims=claims,
            billing=billing,
            customers=customers,
            underwriting=underwriting
        )
    return _service_instance


__all__ = ['FinancialReportingService', 'get_financial_reporting_service']
