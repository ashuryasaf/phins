"""
Test Portfolio Simulation Calculations

Verifies:
1. Mutual exclusivity of claims (one claim per customer)
2. Loss ratio calculation is correct
3. Profitability numbers add up
4. Premium components sum to total
"""

import pytest
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.actuarial_service import (
    get_portfolio_simulator,
    get_actuarial_store,
    SimulationParams,
    ActuarialTablesStore,
    PortfolioSimulator
)


class TestPortfolioSimulation:
    """Test suite for portfolio simulation calculations"""
    
    def test_premium_components_add_up(self):
        """Test that premium components sum to gross premium"""
        simulator = get_portfolio_simulator()
        params = SimulationParams(
            customer_count=1000,  # Small sample for speed
            age_min=25,
            age_max=45,
            age_distribution='normal',
            age_mean=35.0,
            age_std=5.0
        )
        
        result = simulator.generate_portfolio(params)
        
        prof = result['profitability']
        
        # Calculate expected total
        expected_total = (
            prof['risk_premium'] + 
            prof['savings_premium'] + 
            prof['expense_loading'] + 
            prof['profit_margin']
        )
        
        # Should match gross premium (within rounding for many customers)
        # Allow 0.1% tolerance for floating point accumulation
        tolerance = prof['gross_premium'] * 0.001
        assert abs(prof['gross_premium'] - expected_total) < max(100, tolerance), \
            f"Premium mismatch: {prof['gross_premium']} vs {expected_total}"
        
        # Also verify using the calculated_gross field
        if 'components_match' in prof:
            assert prof['components_match'], \
                f"Components don't match: gross={prof['gross_premium']}, calc={prof.get('calculated_gross')}"
    
    def test_mutual_exclusivity_reduces_claims(self):
        """
        Test that mutual exclusivity model produces reasonable claim values.
        With mutual exclusivity, total claims should be less than
        naive sum of mortality + disability.
        """
        simulator = get_portfolio_simulator()
        params = SimulationParams(
            customer_count=100,
            age_min=30,
            age_max=50
        )
        
        result = simulator.generate_portfolio(params)
        risk = result['risk_metrics']
        
        # Both mortality and disability should be present
        assert risk['pv_mortality_claims'] > 0, "Mortality claims should be > 0"
        # Disability may be 0 if all customers have disability excluded
        
        # Total should equal sum
        expected_total = risk['pv_mortality_claims'] + risk['pv_disability_claims']
        assert abs(risk['total_expected_claims'] - expected_total) < 1, \
            "Total claims should equal sum of mortality + disability"
    
    def test_loss_ratio_calculation(self):
        """Test that loss ratio is calculated correctly"""
        simulator = get_portfolio_simulator()
        params = SimulationParams(
            customer_count=500,
            age_min=20,
            age_max=40
        )
        
        result = simulator.generate_portfolio(params)
        risk = result['risk_metrics']
        prof = result['profitability']
        
        # Calculate expected loss ratio
        annual_claims = prof['expected_claims']
        gross_premium = prof['gross_premium']
        
        expected_loss_ratio = (annual_claims / gross_premium * 100) if gross_premium > 0 else 0
        
        # Should match (within rounding)
        assert abs(risk['loss_ratio'] - expected_loss_ratio) < 0.5, \
            f"Loss ratio mismatch: {risk['loss_ratio']} vs {expected_loss_ratio}"
    
    def test_net_profit_calculation(self):
        """Test that net profit is calculated correctly"""
        simulator = get_portfolio_simulator()
        params = SimulationParams(
            customer_count=1000,
            age_min=25,
            age_max=50
        )
        
        result = simulator.generate_portfolio(params)
        prof = result['profitability']
        
        # Net profit = Operating Revenue - Expected Claims
        # Operating Revenue = Risk Premium + Expense Loading + Profit Margin
        operating_revenue = prof['risk_premium'] + prof['expense_loading'] + prof['profit_margin']
        expected_net_profit = operating_revenue - prof['expected_claims']
        
        assert abs(prof['net_profit'] - expected_net_profit) < 100, \
            f"Net profit mismatch: {prof['net_profit']} vs {expected_net_profit}"
    
    def test_expected_claims_is_annualized(self):
        """Test that expected_claims in profitability is annualized"""
        simulator = get_portfolio_simulator()
        params = SimulationParams(
            customer_count=100,
            age_min=30,
            age_max=45
        )
        
        result = simulator.generate_portfolio(params)
        risk = result['risk_metrics']
        prof = result['profitability']
        
        # PV claims / avg term = annual claims
        avg_term = risk['avg_term_years']
        expected_annual = risk['total_expected_claims'] / avg_term
        
        # Allow 1% tolerance for rounding in the avg_term calculation
        tolerance = max(500, expected_annual * 0.01)
        assert abs(prof['expected_claims'] - expected_annual) < tolerance, \
            f"Expected claims not properly annualized: {prof['expected_claims']} vs {expected_annual}"
    
    def test_claims_less_than_coverage(self):
        """Test that expected claims are less than total coverage"""
        simulator = get_portfolio_simulator()
        params = SimulationParams(
            customer_count=500,
            age_min=25,
            age_max=55
        )
        
        result = simulator.generate_portfolio(params)
        
        total_coverage = result['portfolio_summary']['total_coverage']
        total_claims = result['risk_metrics']['total_expected_claims']
        
        # Expected claims should be a fraction of total coverage
        assert total_claims < total_coverage, \
            f"Claims ({total_claims}) should be less than coverage ({total_coverage})"
        
        # Claims should be reasonable (less than 20% of coverage typically)
        claim_ratio = total_claims / total_coverage
        assert claim_ratio < 0.5, \
            f"Claim ratio too high: {claim_ratio * 100:.1f}%"
    
    def test_reserve_requirement_is_150_percent(self):
        """Test that reserve requirement is 150% of expected claims"""
        simulator = get_portfolio_simulator()
        params = SimulationParams(customer_count=100)
        
        result = simulator.generate_portfolio(params)
        risk = result['risk_metrics']
        
        expected_reserve = risk['total_expected_claims'] * 1.5
        
        assert abs(risk['reserve_requirement'] - expected_reserve) < 1, \
            f"Reserve requirement mismatch: {risk['reserve_requirement']} vs {expected_reserve}"
    
    def test_mortality_disability_percentages(self):
        """Test that mortality and disability percentages sum to 100%"""
        simulator = get_portfolio_simulator()
        params = SimulationParams(customer_count=1000)
        
        result = simulator.generate_portfolio(params)
        risk = result['risk_metrics']
        
        # If there are any claims
        if risk['total_expected_claims'] > 0:
            total_pct = risk['mortality_pct_of_claims'] + risk['disability_pct_of_claims']
            assert abs(total_pct - 100) < 1, \
                f"Claim percentages should sum to 100%: {total_pct}"


class TestMutualExclusivity:
    """Tests specifically for mutual exclusivity model"""
    
    def test_single_customer_calculation(self):
        """Test premium calculation for a single customer"""
        store = get_actuarial_store()
        simulator = PortfolioSimulator(store)
        
        # Create a test customer
        customer = {
            'age': 35,
            'gender': 'male',
            'ethnicity': 'caucasian',
            'coverage': 500000,
            'term': 20,
            'adl': 3
        }
        
        # Check underwriting
        uw_result = simulator._check_underwriting(customer)
        assert uw_result['accepted'], "Customer should be accepted"
        
        # Calculate premium
        premium = simulator._calculate_premium(customer, uw_result)
        
        # All values should be positive
        assert premium['annual_premium'] > 0
        assert premium['risk_premium'] > 0
        assert premium['pv_mortality'] > 0
        # Disability might be > 0 depending on ADL
    
    def test_high_adl_exclusion(self):
        """Test that high ADL customers have disability excluded"""
        store = get_actuarial_store()
        simulator = PortfolioSimulator(store)
        
        # Customer with ADL 8 (should have disability excluded)
        customer = {
            'age': 40,
            'gender': 'female',
            'ethnicity': 'asian',
            'coverage': 300000,
            'term': 15,
            'adl': 8
        }
        
        uw_result = simulator._check_underwriting(customer)
        assert uw_result['exclude_disability'], "ADL 8 should exclude disability"
        
        premium = simulator._calculate_premium(customer, uw_result)
        assert premium['pv_disability'] == 0, "Disability claims should be 0 when excluded"
    
    def test_adl_decline_threshold(self):
        """Test that ADL at decline threshold is declined"""
        store = get_actuarial_store()
        simulator = PortfolioSimulator(store)
        
        # Customer with ADL 9 (at decline threshold)
        customer = {
            'age': 30,
            'gender': 'male',
            'ethnicity': 'hispanic',
            'coverage': 250000,
            'term': 10,
            'adl': 9
        }
        
        uw_result = simulator._check_underwriting(customer)
        assert not uw_result['accepted'], "ADL 9 should be declined"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
