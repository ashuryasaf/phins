#!/usr/bin/env python3
"""
Comprehensive test suite for Monthly Billing Projection Service.

Tests:
- Customer billing ledger tracking
- Future payment projections
- Prepaid premium discounts
- Risk vs savings allocation
- Data integrity validation
- Hash chain verification

PHINS - Most Advanced AI BI Insurance Platform
"""

import sys
import os
import json
from datetime import datetime, timedelta
from decimal import Decimal

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from services.monthly_billing_projection_service import (
    MonthlyBillingProjectionService,
    BillingLedgerEntry,
    CustomerBillingProjection,
    PaymentFrequency,
    PrepaidDiscountTier,
    ProjectionEntryStatus,
    PREPAID_DISCOUNT_RATES,
    init_billing_projection_service,
    get_billing_projection_service
)


class TestBillingLedgerEntry:
    """Test cases for BillingLedgerEntry dataclass"""
    
    def test_entry_creation_with_allocation(self):
        """Test ledger entry creation with risk/savings allocation"""
        entry = BillingLedgerEntry(
            entry_id="LEDGER-001",
            customer_id="CUST001",
            customer_email="test@phins.ai",
            policy_id="POL001",
            entry_type="projected",
            payment_period="2026-02",
            due_date="2026-02-01",
            base_amount=Decimal("250.00"),
            risk_percentage=Decimal("75"),
            savings_percentage=Decimal("25")
        )
        
        # Verify allocation calculated correctly
        assert entry.risk_amount == Decimal("187.50")
        assert entry.savings_amount == Decimal("62.50")
        assert entry.final_amount == Decimal("250.00")
    
    def test_entry_with_discount(self):
        """Test ledger entry with prepaid discount applied"""
        entry = BillingLedgerEntry(
            entry_id="LEDGER-002",
            customer_id="CUST001",
            customer_email="test@phins.ai",
            policy_id="POL001",
            entry_type="projected",
            payment_period="2026-Q1",
            due_date="2026-01-01",
            base_amount=Decimal("750.00"),  # 3 months
            discount_rate=Decimal("2.00"),  # 2% quarterly discount
            risk_percentage=Decimal("75"),
            savings_percentage=Decimal("25")
        )
        
        # Verify discount applied
        assert entry.discount_amount == Decimal("15.00")  # 2% of 750
        assert entry.final_amount == Decimal("735.00")  # 750 - 15
        
        # Risk/savings calculated on final (discounted) amount
        assert entry.risk_amount == Decimal("551.25")  # 75% of 735
        assert entry.savings_amount == Decimal("183.75")  # 25% of 735
    
    def test_savings_breakdown_calculation(self):
        """Test savings breakdown into wallet/investment/algo"""
        entry = BillingLedgerEntry(
            entry_id="LEDGER-003",
            customer_id="CUST001",
            customer_email="test@phins.ai",
            policy_id="POL001",
            entry_type="projected",
            payment_period="2026-02",
            due_date="2026-02-01",
            base_amount=Decimal("1000.00"),
            risk_percentage=Decimal("75"),
            savings_percentage=Decimal("25")
        )
        
        # Savings = 25% of 1000 = 250
        entry.calculate_savings_breakdown(
            wallet_pct=Decimal("15"),
            investment_pct=Decimal("60"),
            algo_pct=Decimal("25")
        )
        
        assert entry.wallet_amount == Decimal("37.50")  # 15% of 250
        assert entry.investment_amount == Decimal("150.00")  # 60% of 250
        assert entry.algo_trading_amount == Decimal("62.50")  # 25% of 250
        
        # Total should equal savings_amount
        total = entry.wallet_amount + entry.investment_amount + entry.algo_trading_amount
        assert total == entry.savings_amount
    
    def test_hash_generation(self):
        """Test hash generation for ledger integrity"""
        entry1 = BillingLedgerEntry(
            entry_id="LEDGER-001",
            customer_id="CUST001",
            customer_email="test@phins.ai",
            policy_id="POL001",
            entry_type="projected",
            payment_period="2026-02",
            due_date="2026-02-01",
            base_amount=Decimal("250.00"),
            previous_hash=None
        )
        
        hash1 = entry1.generate_hash()
        assert len(hash1) == 32
        
        # Same entry should produce same hash
        hash1_again = entry1.generate_hash()
        assert hash1 == hash1_again
        
        # Different entry should produce different hash
        entry2 = BillingLedgerEntry(
            entry_id="LEDGER-002",
            customer_id="CUST001",
            customer_email="test@phins.ai",
            policy_id="POL001",
            entry_type="projected",
            payment_period="2026-03",
            due_date="2026-03-01",
            base_amount=Decimal("250.00"),
            previous_hash=hash1
        )
        
        hash2 = entry2.generate_hash()
        assert hash2 != hash1
    
    def test_to_dict(self):
        """Test conversion to dictionary"""
        entry = BillingLedgerEntry(
            entry_id="LEDGER-001",
            customer_id="CUST001",
            customer_email="test@phins.ai",
            policy_id="POL001",
            entry_type="historical",
            payment_period="2026-01",
            due_date="2026-01-15",
            payment_date="2026-01-14",
            base_amount=Decimal("250.00"),
            amount_paid=Decimal("250.00"),
            status=ProjectionEntryStatus.PAID
        )
        
        d = entry.to_dict()
        
        assert d['entry_id'] == "LEDGER-001"
        assert d['customer_email'] == "test@phins.ai"
        assert d['base_amount'] == 250.00
        assert d['status'] == 'paid'
        assert 'risk_amount' in d
        assert 'savings_amount' in d


class TestMonthlyBillingProjectionService:
    """Test cases for MonthlyBillingProjectionService"""
    
    @pytest.fixture
    def sample_customers(self):
        """Sample customers data"""
        return {
            'CUST001': {
                'id': 'CUST001',
                'name': 'Efrat Cohen',
                'first_name': 'Efrat',
                'last_name': 'Cohen',
                'email': 'efrat@phins.ai',
                'phone': '555-1234'
            },
            'CUST002': {
                'id': 'CUST002',
                'name': 'David Levi',
                'first_name': 'David',
                'last_name': 'Levi',
                'email': 'david@phins.ai',
                'phone': '555-5678'
            }
        }
    
    @pytest.fixture
    def sample_policies(self):
        """Sample policies data"""
        return {
            'POL001': {
                'id': 'POL001',
                'customer_id': 'CUST001',
                'type': 'health',
                'status': 'active',
                'monthly_premium': 250.00,
                'annual_premium': 3000.00,
                'start_date': '2026-01-01T00:00:00',
                'billing': json.dumps({
                    'payment_frequency': 'monthly',
                    'risk_percentage': 75,
                    'savings_percentage': 25
                })
            },
            'POL002': {
                'id': 'POL002',
                'customer_id': 'CUST001',
                'type': 'life',
                'status': 'active',
                'monthly_premium': 150.00,
                'annual_premium': 1800.00,
                'start_date': '2026-01-01T00:00:00',
                'billing': json.dumps({
                    'payment_frequency': 'quarterly',
                    'risk_percentage': 80,
                    'savings_percentage': 20
                })
            },
            'POL003': {
                'id': 'POL003',
                'customer_id': 'CUST002',
                'type': 'auto',
                'status': 'active',
                'monthly_premium': 100.00,
                'annual_premium': 1200.00,
                'start_date': '2026-01-01T00:00:00'
            }
        }
    
    @pytest.fixture
    def sample_billing(self):
        """Sample billing data - historical bills"""
        return {
            'BILL001': {
                'id': 'BILL001',
                'policy_id': 'POL001',
                'customer_id': 'CUST001',
                'amount': 250.00,
                'amount_paid': 250.00,
                'status': 'paid',
                'due_date': '2026-01-15',
                'paid_date': '2026-01-14',
                'premium_allocation': json.dumps({
                    'risk_percentage': 75,
                    'savings_percentage': 25
                })
            },
            'BILL002': {
                'id': 'BILL002',
                'policy_id': 'POL001',
                'customer_id': 'CUST001',
                'amount': 250.00,
                'amount_paid': 250.00,
                'status': 'paid',
                'due_date': '2026-02-15',
                'paid_date': '2026-02-10'
            },
            'BILL003': {
                'id': 'BILL003',
                'policy_id': 'POL001',
                'customer_id': 'CUST001',
                'amount': 250.00,
                'amount_paid': 0.00,
                'status': 'outstanding',
                'due_date': '2026-03-15'
            }
        }
    
    @pytest.fixture
    def service(self, sample_customers, sample_policies, sample_billing):
        """Create service instance with sample data"""
        return MonthlyBillingProjectionService(
            customers=sample_customers,
            policies=sample_policies,
            billing=sample_billing,
            claims={},
            health_wallets={},
            investment_accounts={}
        )
    
    def test_get_customer_projection_by_id(self, service):
        """Test getting projection by customer ID"""
        projections = service.get_customer_billing_projection(
            customer_id='CUST001',
            projection_months=6
        )
        
        assert len(projections) == 2  # Two policies for CUST001
        
        # Find the health policy projection
        health_proj = next(p for p in projections if p.policy_type == 'health')
        
        assert health_proj.customer_email == 'efrat@phins.ai'
        assert health_proj.customer_name == 'Efrat Cohen'
        assert health_proj.monthly_premium == Decimal('250.00')
        assert health_proj.risk_percentage == Decimal('75')
        assert health_proj.savings_percentage == Decimal('25')
        
        # Should have historical entries from billing data
        assert len(health_proj.historical_entries) > 0
        
        # Should have projected entries for 6 months
        assert len(health_proj.projected_entries) > 0
    
    def test_get_customer_projection_by_email(self, service):
        """Test getting projection by customer email"""
        projections = service.get_customer_billing_projection(
            customer_email='efrat@phins.ai',
            projection_months=12
        )
        
        assert len(projections) == 2  # Two policies
        assert all(p.customer_email == 'efrat@phins.ai' for p in projections)
    
    def test_projection_includes_historical_payments(self, service):
        """Test that projections include historical payments"""
        projections = service.get_customer_billing_projection(
            customer_id='CUST001',
            policy_id='POL001'
        )
        
        assert len(projections) == 1
        proj = projections[0]
        
        # Should have 3 historical entries (BILL001, BILL002, BILL003)
        assert len(proj.historical_entries) == 3
        
        # Check paid entries
        paid_entries = [e for e in proj.historical_entries if e.status == ProjectionEntryStatus.PAID]
        assert len(paid_entries) == 2
        
        # Check outstanding entry
        outstanding = [e for e in proj.historical_entries if e.status == ProjectionEntryStatus.DUE]
        assert len(outstanding) == 1
    
    def test_policy_projection_does_not_mix_other_policy_bills(self, service):
        """Historical entries must remain policy-scoped for integrity."""
        projections = service.get_customer_billing_projection(
            customer_id='CUST001',
            policy_id='POL002'
        )
        
        assert len(projections) == 1
        proj = projections[0]
        
        # Sample billing data only has POL001 bills.
        assert len(proj.historical_entries) == 0
    
    def test_projection_totals_calculation(self, service):
        """Test that projection totals are calculated correctly"""
        projections = service.get_customer_billing_projection(
            customer_id='CUST001',
            policy_id='POL001',
            projection_months=6
        )
        
        proj = projections[0]
        
        # Total billed should include historical
        assert proj.total_billed > 0
        
        # Total paid should match paid bills
        assert proj.total_paid == Decimal('500.00')  # BILL001 + BILL002
        
        # Total outstanding should be the unpaid amount
        assert proj.total_outstanding == Decimal('250.00')  # BILL003
        
        # Risk/savings allocation totals
        assert proj.total_risk_allocated > 0
        assert proj.total_savings_allocated > 0
    
    def test_prepaid_discount_quarterly(self, service):
        """Test prepaid discount calculation for quarterly"""
        result = service.apply_prepaid_discount(
            customer_id='CUST001',
            policy_id='POL001',
            prepaid_months=3
        )
        
        assert 'calculation' in result
        assert result['discount_tier'] == 'quarterly'
        assert result['discount_rate_pct'] == 2.0
        
        # 3 months at $250 = $750, 2% discount = $15
        assert result['calculation']['base_amount'] == 750.00
        assert result['calculation']['discount_amount'] == 15.00
        assert result['calculation']['final_amount'] == 735.00
    
    def test_prepaid_discount_semi_annual(self, service):
        """Test prepaid discount calculation for semi-annual"""
        result = service.apply_prepaid_discount(
            customer_id='CUST001',
            policy_id='POL001',
            prepaid_months=6
        )
        
        assert result['discount_tier'] == 'semi_annual'
        assert result['discount_rate_pct'] == 4.0
        
        # 6 months at $250 = $1500, 4% discount = $60
        assert result['calculation']['base_amount'] == 1500.00
        assert result['calculation']['discount_amount'] == 60.00
        assert result['calculation']['final_amount'] == 1440.00
    
    def test_prepaid_discount_annual(self, service):
        """Test prepaid discount calculation for annual"""
        result = service.apply_prepaid_discount(
            customer_id='CUST001',
            policy_id='POL001',
            prepaid_months=12
        )
        
        assert result['discount_tier'] == 'annual'
        assert result['discount_rate_pct'] == 6.0
        
        # 12 months at $250 = $3000, 6% discount = $180
        assert result['calculation']['base_amount'] == 3000.00
        assert result['calculation']['discount_amount'] == 180.00
        assert result['calculation']['final_amount'] == 2820.00
    
    def test_data_integrity_validation_passes(self, service):
        """Test data integrity validation passes for valid data"""
        result = service.validate_billing_integrity(customer_id='CUST001')
        
        assert result['validation_result'] == 'passed'
        assert result['bills_validated'] > 0
    
    def test_data_integrity_detects_duplicate_ids(self):
        """Test that validation detects duplicate bill IDs"""
        billing_with_dupe = {
            'BILL001': {
                'id': 'BILL001',
                'customer_id': 'CUST001',
                'amount': 250.00
            },
            'BILL001_DUPE': {
                'id': 'BILL001',  # Duplicate ID!
                'customer_id': 'CUST001',
                'amount': 300.00
            }
        }
        
        service = MonthlyBillingProjectionService(
            customers={'CUST001': {'id': 'CUST001', 'email': 'test@phins.ai'}},
            policies={},
            billing=billing_with_dupe
        )
        
        result = service.validate_billing_integrity(customer_id='CUST001')
        
        # Should detect duplicate
        duplicate_issues = [i for i in result['issues'] if i['type'] == 'duplicate_bill_id']
        assert len(duplicate_issues) > 0
    
    def test_data_integrity_detects_overpayment(self):
        """Test that validation detects overpayment"""
        billing = {
            'BILL001': {
                'id': 'BILL001',
                'customer_id': 'CUST001',
                'amount': 250.00,
                'amount_paid': 300.00,  # Overpayment!
                'status': 'paid'
            }
        }
        
        service = MonthlyBillingProjectionService(
            customers={'CUST001': {'id': 'CUST001', 'email': 'test@phins.ai'}},
            policies={},
            billing=billing
        )
        
        result = service.validate_billing_integrity(customer_id='CUST001')
        
        overpayment_issues = [i for i in result['issues'] if i['type'] == 'overpayment']
        assert len(overpayment_issues) > 0
    
    def test_ledger_hash_chain_integrity(self, service):
        """Test that ledger hash chain is maintained"""
        projections = service.get_customer_billing_projection(
            customer_id='CUST001',
            policy_id='POL001'
        )
        
        proj = projections[0]
        
        # Integrity should be verified
        assert proj.integrity_verified is True
        assert proj.ledger_hash is not None
        assert len(proj.ledger_hash) == 32
        
        # Check hash chain
        all_entries = proj.historical_entries + proj.projected_entries
        
        for i, entry in enumerate(all_entries):
            if i == 0:
                assert entry.previous_hash is None
            else:
                assert entry.previous_hash == all_entries[i-1].ledger_hash
    
    def test_customer_billing_summary(self, service):
        """Test getting billing summary"""
        summary = service.get_customer_billing_summary(customer_id='CUST001')
        
        assert 'summary' in summary
        assert summary['customer_email'] == 'efrat@phins.ai'
        assert summary['summary']['total_policies'] == 2
        assert summary['summary']['total_bills'] >= 3
        assert summary['summary']['total_paid'] >= 500.00
        
        assert 'allocation_breakdown' in summary
        assert 'policies' in summary
    
    def test_payment_frequency_detection(self, service):
        """Test payment frequency is detected from policy"""
        projections = service.get_customer_billing_projection(
            customer_id='CUST001'
        )
        
        # Find monthly and quarterly policies
        monthly_proj = next(p for p in projections if p.policy_type == 'health')
        quarterly_proj = next(p for p in projections if p.policy_type == 'life')
        
        assert monthly_proj.payment_frequency == PaymentFrequency.MONTHLY
        assert quarterly_proj.payment_frequency == PaymentFrequency.QUARTERLY
        
        # Quarterly should have discount tier
        assert quarterly_proj.prepaid_tier == PrepaidDiscountTier.QUARTERLY
        assert quarterly_proj.prepaid_discount_rate == Decimal('2.00')
    
    def test_payment_frequency_detection_supports_frequency_key(self, sample_customers):
        """Policies using billing.frequency should map correctly."""
        policies = {
            'POLFREQ': {
                'id': 'POLFREQ',
                'customer_id': 'CUST001',
                'type': 'health',
                'status': 'active',
                'monthly_premium': 100.00,
                'annual_premium': 1200.00,
                'start_date': '2026-01-01T00:00:00',
                'billing': {
                    'frequency': 'quarterly',
                    'risk_percentage': 75,
                    'savings_percentage': 25
                }
            }
        }
        service = MonthlyBillingProjectionService(
            customers=sample_customers,
            policies=policies,
            billing={}
        )
        
        projections = service.get_customer_billing_projection(
            customer_id='CUST001',
            policy_id='POLFREQ'
        )
        
        assert len(projections) == 1
        assert projections[0].payment_frequency == PaymentFrequency.QUARTERLY
    
    def test_projection_to_dict(self, service):
        """Test projection conversion to dictionary"""
        projections = service.get_customer_billing_projection(
            customer_id='CUST001',
            policy_id='POL001'
        )
        
        proj_dict = projections[0].to_dict()
        
        assert 'customer_id' in proj_dict
        assert 'customer_email' in proj_dict
        assert 'policy_id' in proj_dict
        assert 'summary' in proj_dict
        assert 'historical_payments' in proj_dict
        assert 'future_projections' in proj_dict
        assert 'ledger_hash' in proj_dict
        assert 'integrity_verified' in proj_dict
    
    def test_risk_savings_allocation_in_projections(self, service):
        """Test that risk/savings allocation is included in projections"""
        projections = service.get_customer_billing_projection(
            customer_id='CUST001',
            policy_id='POL001',
            projection_months=3
        )
        
        proj = projections[0]
        
        # Check projected entries have allocation
        for entry in proj.projected_entries:
            assert entry.risk_amount > 0
            assert entry.savings_amount > 0
            assert entry.risk_amount + entry.savings_amount == entry.final_amount
            
            # Check savings breakdown
            assert entry.wallet_amount >= 0
            assert entry.investment_amount >= 0
            assert entry.algo_trading_amount >= 0


class TestPrepaidDiscountTiers:
    """Test prepaid discount tier calculations"""
    
    def test_discount_rates(self):
        """Test that discount rates are correctly defined"""
        assert PREPAID_DISCOUNT_RATES[PrepaidDiscountTier.NONE] == Decimal('0.00')
        assert PREPAID_DISCOUNT_RATES[PrepaidDiscountTier.QUARTERLY] == Decimal('2.00')
        assert PREPAID_DISCOUNT_RATES[PrepaidDiscountTier.SEMI_ANNUAL] == Decimal('4.00')
        assert PREPAID_DISCOUNT_RATES[PrepaidDiscountTier.ANNUAL] == Decimal('6.00')
    
    def test_minimal_discount_rate(self):
        """Test that discounts are minimal to protect revenue"""
        # Verify quarterly discount is small (2%)
        quarterly_discount = PREPAID_DISCOUNT_RATES[PrepaidDiscountTier.QUARTERLY]
        assert quarterly_discount <= Decimal('5.00')  # Max 5%
        
        # Verify annual discount is reasonable (6%)
        annual_discount = PREPAID_DISCOUNT_RATES[PrepaidDiscountTier.ANNUAL]
        assert annual_discount <= Decimal('10.00')  # Max 10%


class TestServiceInitialization:
    """Test service initialization and singleton behavior"""
    
    def test_init_billing_projection_service(self):
        """Test service initialization function"""
        service = init_billing_projection_service(
            customers={'CUST001': {'id': 'CUST001', 'email': 'test@phins.ai'}},
            policies={},
            billing={}
        )
        
        assert service is not None
        assert isinstance(service, MonthlyBillingProjectionService)
    
    def test_get_billing_projection_service(self):
        """Test getting singleton instance"""
        # Initialize first
        init_billing_projection_service(
            customers={'CUST001': {'id': 'CUST001', 'email': 'test@phins.ai'}},
            policies={},
            billing={}
        )
        
        service = get_billing_projection_service()
        assert service is not None


class TestEdgeCases:
    """Test edge cases and error handling"""
    
    def test_empty_billing_data(self):
        """Test with no billing data"""
        service = MonthlyBillingProjectionService(
            customers={'CUST001': {'id': 'CUST001', 'email': 'test@phins.ai'}},
            policies={
                'POL001': {
                    'id': 'POL001',
                    'customer_id': 'CUST001',
                    'monthly_premium': 100.00,
                    'status': 'active',
                    'start_date': '2026-01-01'
                }
            },
            billing={}
        )
        
        projections = service.get_customer_billing_projection(
            customer_id='CUST001'
        )
        
        assert len(projections) == 1
        assert len(projections[0].historical_entries) == 0
        assert len(projections[0].projected_entries) > 0
    
    def test_customer_not_found(self):
        """Test with non-existent customer"""
        service = MonthlyBillingProjectionService(
            customers={},
            policies={},
            billing={}
        )
        
        projections = service.get_customer_billing_projection(
            customer_id='NONEXISTENT'
        )
        
        assert projections == []
    
    def test_customer_with_no_policies(self):
        """Test customer with no policies"""
        service = MonthlyBillingProjectionService(
            customers={'CUST001': {'id': 'CUST001', 'email': 'test@phins.ai'}},
            policies={},  # No policies
            billing={}
        )
        
        projections = service.get_customer_billing_projection(
            customer_id='CUST001'
        )
        
        assert projections == []
    
    def test_policy_with_zero_premium(self):
        """Test policy with zero premium"""
        service = MonthlyBillingProjectionService(
            customers={'CUST001': {'id': 'CUST001', 'email': 'test@phins.ai'}},
            policies={
                'POL001': {
                    'id': 'POL001',
                    'customer_id': 'CUST001',
                    'monthly_premium': 0,  # Zero premium
                    'annual_premium': 0,
                    'status': 'active',
                    'start_date': '2026-01-01'
                }
            },
            billing={}
        )
        
        projections = service.get_customer_billing_projection(
            customer_id='CUST001'
        )
        
        assert len(projections) == 1
        # Projections should handle zero premium gracefully
        for entry in projections[0].projected_entries:
            assert entry.base_amount == Decimal('0')
    
    def test_invalid_policy_id_for_prepaid(self):
        """Test prepaid discount with invalid policy ID"""
        service = MonthlyBillingProjectionService(
            customers={'CUST001': {'id': 'CUST001', 'email': 'test@phins.ai'}},
            policies={},
            billing={}
        )
        
        result = service.apply_prepaid_discount(
            customer_id='CUST001',
            policy_id='INVALID',
            prepaid_months=3
        )
        
        assert 'error' in result


def main():
    """Run tests"""
    pytest.main([__file__, '-v', '--tb=short'])


if __name__ == '__main__':
    main()
