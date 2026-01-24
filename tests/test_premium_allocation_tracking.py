#!/usr/bin/env python3
"""
Test Suite for Premium Allocation Tracking

Tests the complete flow:
1. Bills created with risk/savings split
2. Payments recorded with automatic allocation
3. Risk reserves sum correctly
4. Savings tracked across multiple policies
5. Customer-level reporting shows full picture

Example Scenario:
    Customer: asaf@assurance.co.il
    Billed: 5 times on 3 different policies
    Allocation: 75% risk / 25% savings
"""

import sys
import os
import pytest
from datetime import datetime, timedelta
from decimal import Decimal

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from services.premium_allocation_tracker import (
    PremiumAllocationTracker,
    BillPremiumAllocation,
    CustomerAllocationSummary,
    RiskReserveReport,
    AllocationStatus,
    init_premium_allocation_tracker
)
from services.reserves_reporting_service import (
    ReservesReportingService,
    ReserveSummary,
    init_reserves_reporting_service
)
from services.billing_service import BillingService


class TestPremiumAllocationTracker:
    """Test the PremiumAllocationTracker service"""
    
    def setup_method(self):
        """Setup test fixtures"""
        self.bills = {}
        self.policies = {
            'POL001': {'policy_id': 'POL001', 'customer_id': 'CUST001', 'status': 'active'},
            'POL002': {'policy_id': 'POL002', 'customer_id': 'CUST001', 'status': 'active'},
            'POL003': {'policy_id': 'POL003', 'customer_id': 'CUST001', 'status': 'active'},
        }
        self.claims = {}
        self.customers = {
            'CUST001': {'customer_id': 'CUST001', 'email': 'asaf@assurance.co.il', 'name': 'Asaf Test'}
        }
        self.health_wallets = {}
        self.investment_accounts = {}
        
        self.tracker = PremiumAllocationTracker(
            bills=self.bills,
            policies=self.policies,
            claims=self.claims,
            customers=self.customers,
            health_wallets=self.health_wallets,
            investment_accounts=self.investment_accounts
        )
    
    def test_record_single_allocation(self):
        """Test recording a single bill allocation"""
        allocation = self.tracker.record_bill_allocation(
            bill_id='BILL001',
            policy_id='POL001',
            customer_id='CUST001',
            bill_amount=1000.00,
            risk_percentage=75,
            savings_percentage=25
        )
        
        assert allocation.allocation_id == 'ALLOC-000001'
        assert allocation.bill_amount == Decimal('1000.00')
        assert allocation.risk_percentage == Decimal('75')
        assert allocation.savings_percentage == Decimal('25')
        assert allocation.risk_amount == Decimal('750.00')
        assert allocation.savings_amount == Decimal('250.00')
        assert allocation.status == AllocationStatus.ALLOCATED
    
    def test_savings_sub_allocation(self):
        """Test that savings are sub-allocated to wallet/investment/algo"""
        allocation = self.tracker.record_bill_allocation(
            bill_id='BILL001',
            policy_id='POL001',
            customer_id='CUST001',
            bill_amount=1000.00,
            auto_allocate_savings=True
        )
        
        # Default sub-allocation: 15% wallet, 60% investment, 25% algo
        # Savings = 250, so:
        # Wallet = 250 * 0.15 = 37.50
        # Investment = 250 * 0.60 = 150.00
        # Algo = 250 * 0.25 = 62.50
        assert allocation.wallet_amount == Decimal('37.50')
        assert allocation.investment_amount == Decimal('150.00')
        assert allocation.algo_trading_amount == Decimal('62.50')
        
        # Total should equal savings amount
        total_sub = allocation.wallet_amount + allocation.investment_amount + allocation.algo_trading_amount
        assert total_sub == allocation.savings_amount
    
    def test_multiple_bills_multiple_policies(self):
        """
        Test scenario: Customer billed 5 times on 3 different policies
        This is the key scenario mentioned by the user.
        """
        # Record 5 bills across 3 policies
        bills_data = [
            ('BILL001', 'POL001', 1000.00),
            ('BILL002', 'POL001', 1000.00),  # Second bill on same policy
            ('BILL003', 'POL002', 1500.00),
            ('BILL004', 'POL002', 1500.00),
            ('BILL005', 'POL003', 2000.00),
        ]
        
        for bill_id, policy_id, amount in bills_data:
            self.tracker.record_bill_allocation(
                bill_id=bill_id,
                policy_id=policy_id,
                customer_id='CUST001',
                bill_amount=amount,
                risk_percentage=75,
                savings_percentage=25
            )
        
        # Get customer summary
        summary = self.tracker.get_customer_allocation_summary('CUST001')
        
        # Verify counts
        assert summary.total_bills == 5
        assert summary.paid_bills == 5
        assert summary.total_policies == 3
        assert summary.active_policies == 3
        
        # Verify totals
        # Total paid: 1000 + 1000 + 1500 + 1500 + 2000 = 7000
        assert summary.total_premiums_paid == Decimal('7000.00')
        
        # Risk: 7000 * 75% = 5250
        assert summary.total_risk_allocated == Decimal('5250.00')
        
        # Savings: 7000 * 25% = 1750
        assert summary.total_savings_allocated == Decimal('1750.00')
        
        # Verify sum = total
        assert summary.total_risk_allocated + summary.total_savings_allocated == summary.total_premiums_paid
    
    def test_per_policy_breakdown(self):
        """Test that allocations are properly broken down by policy"""
        # Record bills
        self.tracker.record_bill_allocation('BILL001', 'POL001', 'CUST001', 1000.00)
        self.tracker.record_bill_allocation('BILL002', 'POL001', 'CUST001', 1000.00)
        self.tracker.record_bill_allocation('BILL003', 'POL002', 'CUST001', 1500.00)
        
        summary = self.tracker.get_customer_allocation_summary('CUST001')
        
        # Check per-policy allocations
        assert len(summary.policy_allocations) == 2
        
        pol1_alloc = next(p for p in summary.policy_allocations if p['policy_id'] == 'POL001')
        assert pol1_alloc['bill_count'] == 2
        assert pol1_alloc['total_paid'] == 2000.00
        assert pol1_alloc['risk_total'] == 1500.00  # 2000 * 75%
        assert pol1_alloc['savings_total'] == 500.00  # 2000 * 25%
        
        pol2_alloc = next(p for p in summary.policy_allocations if p['policy_id'] == 'POL002')
        assert pol2_alloc['bill_count'] == 1
        assert pol2_alloc['total_paid'] == 1500.00
    
    def test_risk_reserve_report(self):
        """Test risk reserve calculation"""
        # Record some allocations
        self.tracker.record_bill_allocation('BILL001', 'POL001', 'CUST001', 1000.00)
        self.tracker.record_bill_allocation('BILL002', 'POL002', 'CUST001', 2000.00)
        
        # Add a paid claim
        self.claims['CLM001'] = {
            'claim_id': 'CLM001',
            'policy_id': 'POL001',
            'claimed_amount': 500.00,
            'approved_amount': 450.00,
            'status': 'paid'
        }
        
        # Add a pending claim
        self.claims['CLM002'] = {
            'claim_id': 'CLM002',
            'policy_id': 'POL002',
            'claimed_amount': 1000.00,
            'status': 'pending'
        }
        
        report = self.tracker.calculate_risk_reserve_report()
        
        # Total risk premiums: (1000 + 2000) * 75% = 2250
        assert report.total_risk_premiums == Decimal('2250.00')
        
        # Paid claims: 450
        assert report.paid_claims_total == Decimal('450.00')
        
        # Claims reserve: 1000 * 80% = 800 (pending at 80% approval rate)
        assert report.claims_reserve == Decimal('800.00')
        
        # Net reserve: 2250 - 450 - 800 = 1000
        assert report.net_risk_reserve == Decimal('1000.00')
    
    def test_customer_detailed_report_by_email(self):
        """Test getting customer report by email lookup"""
        # Record allocations
        self.tracker.record_bill_allocation('BILL001', 'POL001', 'CUST001', 1000.00)
        self.tracker.record_bill_allocation('BILL002', 'POL002', 'CUST001', 1500.00)
        
        # Get report by email
        report = self.tracker.get_customer_detailed_report(
            customer_id=None,
            customer_email='asaf@assurance.co.il'
        )
        
        assert report['customer_id'] == 'CUST001'
        assert report['customer_email'] == 'asaf@assurance.co.il'
        assert report['summary']['total_bills'] == 2
        assert report['summary']['total_premiums_paid'] == 2500.00
        
        # Check allocation breakdown
        assert report['allocation']['risk_portion']['total_contributed'] == 1875.00  # 2500 * 75%
        assert report['allocation']['savings_portion']['total_contributed'] == 625.00  # 2500 * 25%
        
        # Verify integrity
        assert report['verification']['allocation_matches_payment'] == True


class TestReservesReportingService:
    """Test the ReservesReportingService"""
    
    def setup_method(self):
        """Setup test fixtures"""
        self.bills = {}
        self.policies = {}
        self.claims = {}
        self.health_wallets = {}
        self.investment_accounts = {}
        
        self.tracker = PremiumAllocationTracker(
            bills=self.bills,
            policies=self.policies,
            claims=self.claims,
            health_wallets=self.health_wallets,
            investment_accounts=self.investment_accounts
        )
        
        self.reserves_service = ReservesReportingService(
            premium_allocation_tracker=self.tracker,
            policies=self.policies,
            claims=self.claims,
            bills=self.bills,
            health_wallets=self.health_wallets,
            investment_accounts=self.investment_accounts
        )
    
    def test_reserve_summary_calculation(self):
        """Test full reserve summary calculation"""
        # Setup data
        self.tracker.record_bill_allocation('BILL001', 'POL001', 'CUST001', 10000.00)
        
        # Add paid claim
        self.claims['CLM001'] = {
            'claimed_amount': 2000.00,
            'approved_amount': 1800.00,
            'status': 'paid',
            'paid_date': datetime.now().isoformat()
        }
        
        # Add wallet balance
        self.health_wallets['CUST001'] = {'balance': 500.00}
        
        # Add investment balance
        self.investment_accounts['CUST001'] = {
            'balance': 100.00,
            'index_balance': 300.00,
            'bonds_balance': 200.00,
            'crypto_balance': 100.00
        }
        
        summary = self.reserves_service.calculate_reserve_summary()
        
        # Risk reserve: 10000 * 75% = 7500
        assert summary.gross_risk_reserve == Decimal('7500.00')
        
        # Paid claims
        assert summary.claims_paid_total == Decimal('1800.00')
        
        # Customer savings
        assert summary.total_wallet_balances == Decimal('500.00')
        assert summary.total_investment_balances == Decimal('700.00')  # 100 + 300 + 200 + 100
        assert summary.total_customer_savings == Decimal('1200.00')
    
    def test_full_report_generation(self):
        """Test full report generation with all sections"""
        # Setup data
        self.tracker.record_bill_allocation('BILL001', 'POL001', 'CUST001', 10000.00)
        
        report = self.reserves_service.generate_full_report()
        
        assert 'risk_reserves' in report
        assert 'claims_reserves' in report
        assert 'paid_claims' in report
        assert 'net_reserve' in report
        assert 'customer_savings' in report
        assert 'ratios' in report
        assert 'status' in report
        
        # Verify risk reserve is correctly calculated
        assert report['risk_reserves']['gross_risk_reserve'] == 7500.00


class TestBillingServiceIntegration:
    """Test billing service integration with allocation tracker"""
    
    def setup_method(self):
        """Setup test fixtures"""
        self.bills = {}
        self.policies = {
            'POL001': {'policy_id': 'POL001', 'customer_id': 'CUST001', 'status': 'active'},
            'POL002': {'policy_id': 'POL002', 'customer_id': 'CUST001', 'status': 'active'},
        }
        
        self.tracker = PremiumAllocationTracker(bills=self.bills, policies=self.policies)
        self.billing = BillingService(
            bills=self.bills,
            policies=self.policies,
            premium_allocation_tracker=self.tracker
        )
    
    def test_create_bill_with_allocation(self):
        """Test bill creation includes allocation config"""
        bill = self.billing.create_bill(
            policy_id='POL001',
            amount_due=1000.00,
            risk_pct=75,
            savings_pct=25
        )
        
        assert 'premium_allocation' in bill
        assert bill['premium_allocation']['risk_percentage'] == 75
        assert bill['premium_allocation']['savings_percentage'] == 25
        assert bill['premium_allocation']['risk_amount_due'] == 750.00
        assert bill['premium_allocation']['savings_amount_due'] == 250.00
    
    def test_payment_triggers_allocation(self):
        """Test that payment recording triggers allocation tracking"""
        # Create and pay a bill
        bill = self.billing.create_bill('POL001', 1000.00)
        paid_bill = self.billing.record_payment(bill['bill_id'], 1000.00)
        
        # Check bill allocation was updated
        assert paid_bill['premium_allocation']['risk_amount_paid'] == 750.00
        assert paid_bill['premium_allocation']['savings_amount_paid'] == 250.00
        assert paid_bill['premium_allocation']['allocated'] == True
        assert paid_bill['premium_allocation']['allocation_id'] is not None
        
        # Verify tracker recorded it
        assert len(self.tracker.allocations) == 1
    
    def test_customer_billing_summary(self):
        """Test customer billing summary with allocations"""
        # Create and pay multiple bills
        bill1 = self.billing.create_bill('POL001', 1000.00, customer_id='CUST001')
        bill2 = self.billing.create_bill('POL002', 1500.00, customer_id='CUST001')
        
        self.billing.record_payment(bill1['bill_id'], 1000.00)
        self.billing.record_payment(bill2['bill_id'], 1500.00)
        
        summary = self.billing.get_customer_billing_summary('CUST001')
        
        assert summary['total_bills'] == 2
        assert summary['paid_bills'] == 2
        assert summary['total_billed'] == 2500.00
        assert summary['total_paid'] == 2500.00
        
        # Check allocation summary
        assert summary['allocation_summary']['total_risk_allocated'] == 1875.00  # 2500 * 75%
        assert summary['allocation_summary']['total_savings_allocated'] == 625.00  # 2500 * 25%


class TestScenarioAsafAssurance:
    """
    Full integration test for the scenario described by user:
    Customer asaf@assurance.co.il billed 5 times on 3 different policies
    with 25% savings allocation.
    """
    
    def setup_method(self):
        """Setup test fixtures for Asaf scenario"""
        self.bills = {}
        self.policies = {
            'POL-HEALTH-001': {'policy_id': 'POL-HEALTH-001', 'customer_id': 'ASAF001', 'status': 'active', 'type': 'health'},
            'POL-LIFE-001': {'policy_id': 'POL-LIFE-001', 'customer_id': 'ASAF001', 'status': 'active', 'type': 'life'},
            'POL-AUTO-001': {'policy_id': 'POL-AUTO-001', 'customer_id': 'ASAF001', 'status': 'active', 'type': 'auto'},
        }
        self.claims = {}
        self.customers = {
            'ASAF001': {'customer_id': 'ASAF001', 'email': 'asaf@assurance.co.il', 'name': 'Asaf Cohen'}
        }
        self.health_wallets = {}
        self.investment_accounts = {}
        
        # Initialize services
        self.tracker = PremiumAllocationTracker(
            bills=self.bills,
            policies=self.policies,
            claims=self.claims,
            customers=self.customers,
            health_wallets=self.health_wallets,
            investment_accounts=self.investment_accounts
        )
        
        self.billing = BillingService(
            bills=self.bills,
            policies=self.policies,
            premium_allocation_tracker=self.tracker
        )
        
        self.reserves = ReservesReportingService(
            premium_allocation_tracker=self.tracker,
            policies=self.policies,
            claims=self.claims,
            bills=self.bills,
            health_wallets=self.health_wallets,
            investment_accounts=self.investment_accounts
        )
    
    def test_asaf_5_bills_3_policies_25_savings(self):
        """
        Test exact scenario:
        - 5 bills across 3 policies
        - 75% risk / 25% savings allocation
        - Verify proper tracking and reporting
        """
        # Create and pay 5 bills with 75/25 split
        bills_config = [
            ('POL-HEALTH-001', 800.00),   # Health policy bill 1
            ('POL-HEALTH-001', 800.00),   # Health policy bill 2
            ('POL-LIFE-001', 1200.00),    # Life policy bill 1
            ('POL-LIFE-001', 1200.00),    # Life policy bill 2
            ('POL-AUTO-001', 600.00),     # Auto policy bill 1
        ]
        
        for policy_id, amount in bills_config:
            bill = self.billing.create_bill(
                policy_id=policy_id,
                amount_due=amount,
                customer_id='ASAF001',
                risk_pct=75,
                savings_pct=25
            )
            self.billing.record_payment(bill['bill_id'], amount)
        
        # Get customer detailed report
        report = self.tracker.get_customer_detailed_report(
            customer_id=None,
            customer_email='asaf@assurance.co.il'
        )
        
        # Verify summary
        assert report['summary']['total_bills'] == 5
        assert report['summary']['paid_bills'] == 5
        assert report['summary']['total_policies'] == 3
        
        # Total paid: 800 + 800 + 1200 + 1200 + 600 = 4600
        assert report['summary']['total_premiums_paid'] == 4600.00
        
        # Risk allocation: 4600 * 75% = 3450
        assert report['allocation']['risk_portion']['total_contributed'] == 3450.00
        
        # Savings allocation: 4600 * 25% = 1150
        assert report['allocation']['savings_portion']['total_contributed'] == 1150.00
        
        # Verify per-policy breakdown
        policy_allocs = {p['policy_id']: p for p in report['per_policy_allocation']}
        
        # Health policy: 2 bills, $1600 total
        assert policy_allocs['POL-HEALTH-001']['bill_count'] == 2
        assert policy_allocs['POL-HEALTH-001']['total_paid'] == 1600.00
        assert policy_allocs['POL-HEALTH-001']['risk_total'] == 1200.00   # 1600 * 75%
        assert policy_allocs['POL-HEALTH-001']['savings_total'] == 400.00  # 1600 * 25%
        
        # Life policy: 2 bills, $2400 total
        assert policy_allocs['POL-LIFE-001']['bill_count'] == 2
        assert policy_allocs['POL-LIFE-001']['total_paid'] == 2400.00
        assert policy_allocs['POL-LIFE-001']['risk_total'] == 1800.00
        assert policy_allocs['POL-LIFE-001']['savings_total'] == 600.00
        
        # Auto policy: 1 bill, $600 total
        assert policy_allocs['POL-AUTO-001']['bill_count'] == 1
        assert policy_allocs['POL-AUTO-001']['total_paid'] == 600.00
        assert policy_allocs['POL-AUTO-001']['risk_total'] == 450.00
        assert policy_allocs['POL-AUTO-001']['savings_total'] == 150.00
        
        # Verify savings breakdown (sub-allocation)
        savings_breakdown = report['allocation']['savings_portion']
        
        # Default sub-allocation: 15% wallet, 60% investment, 25% algo
        # Total savings: 1150
        expected_wallet = round(1150 * 0.15, 2)       # 172.50
        expected_investment = round(1150 * 0.60, 2)   # 690.00
        expected_algo = round(1150 * 0.25, 2)         # 287.50
        
        assert savings_breakdown['wallet']['allocated'] == expected_wallet
        assert savings_breakdown['investments']['allocated'] == expected_investment
        assert savings_breakdown['algo_trading']['allocated'] == expected_algo
        
        # Verify total savings calculation
        total_allocated = (
            savings_breakdown['wallet']['allocated'] +
            savings_breakdown['investments']['allocated'] +
            savings_breakdown['algo_trading']['allocated']
        )
        assert abs(total_allocated - 1150.00) < 0.01
        
        # Verify integrity check passes
        assert report['verification']['allocation_matches_payment'] == True
        
        # Get reserves report
        full_report = self.reserves.generate_full_report()
        
        # Verify risk reserves match
        assert full_report['risk_reserves']['gross_risk_reserve'] == 3450.00
        
        print("\n" + "="*60)
        print("ASAF SCENARIO TEST PASSED")
        print("="*60)
        print(f"Customer: asaf@assurance.co.il")
        print(f"Total Bills: 5")
        print(f"Total Policies: 3")
        print(f"Total Premiums Paid: ${report['summary']['total_premiums_paid']:,.2f}")
        print(f"Risk Allocated (75%): ${report['allocation']['risk_portion']['total_contributed']:,.2f}")
        print(f"Savings Allocated (25%): ${report['allocation']['savings_portion']['total_contributed']:,.2f}")
        print(f"  - Wallet (15%): ${savings_breakdown['wallet']['allocated']:,.2f}")
        print(f"  - Investment (60%): ${savings_breakdown['investments']['allocated']:,.2f}")
        print(f"  - Algo Trading (25%): ${savings_breakdown['algo_trading']['allocated']:,.2f}")
        print("="*60)


def main():
    """Run all tests"""
    import pytest
    sys.exit(pytest.main([__file__, '-v', '--tb=short']))


if __name__ == '__main__':
    main()
