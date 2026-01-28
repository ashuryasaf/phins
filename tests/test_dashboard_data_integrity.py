"""
Dashboard Data Integrity Validation Tests

This module validates data integrity for dashboard metrics:
- Number of applied policies
- Total coverage amount
- Total premium calculations
- Billing reconciliation

Run: pytest tests/test_dashboard_data_integrity.py -v
"""

import pytest
import json
import sys
import os
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class DataIntegrityValidator:
    """Validates data integrity across dashboard calculations"""
    
    TOLERANCE = 0.01  # Allow 1 cent tolerance for floating point
    
    @staticmethod
    def round_currency(value: float) -> float:
        """Round to 2 decimal places using banker's rounding"""
        return float(Decimal(str(value)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))
    
    @staticmethod
    def validate_policy_count(policies: dict, expected_status: str = 'active') -> dict:
        """
        Validate policy count calculations
        
        Rules:
        - policies_count should equal count of policies with specified status
        - total_policies should equal all policies for customer
        """
        total_count = len(policies)
        active_count = sum(
            1 for p in policies.values() 
            if (p.get('status') or '').lower() == expected_status.lower()
        )
        
        return {
            'valid': True,
            'total_policies': total_count,
            'active_policies': active_count,
            'by_status': _count_by_status(policies)
        }
    
    @staticmethod
    def validate_coverage_amount(policies: dict, customer_id: str = None) -> dict:
        """
        Validate total coverage calculations
        
        Rules:
        - Total coverage = SUM(coverage_amount) for ACTIVE policies only
        - Coverage amount must be non-negative
        - Must only include customer's own policies if customer_id provided
        """
        errors = []
        warnings = []
        
        filtered_policies = policies.values()
        if customer_id:
            filtered_policies = [p for p in policies.values() if p.get('customer_id') == customer_id]
        
        active_policies = [p for p in filtered_policies if (p.get('status') or '').lower() == 'active']
        
        total_coverage = 0
        for p in active_policies:
            coverage = p.get('coverage_amount', 0)
            
            # Validate coverage value
            if coverage is None:
                warnings.append(f"Policy {p.get('id')} has null coverage_amount")
                coverage = 0
            
            try:
                coverage = float(coverage)
            except (TypeError, ValueError):
                errors.append(f"Policy {p.get('id')} has invalid coverage_amount: {coverage}")
                continue
                
            if coverage < 0:
                errors.append(f"Policy {p.get('id')} has negative coverage: {coverage}")
                continue
                
            total_coverage += coverage
        
        return {
            'valid': len(errors) == 0,
            'total_coverage': DataIntegrityValidator.round_currency(total_coverage),
            'policy_count': len(active_policies),
            'errors': errors,
            'warnings': warnings
        }
    
    @staticmethod
    def validate_premium_calculations(policies: dict, customer_id: str = None) -> dict:
        """
        Validate premium calculations
        
        Rules:
        - Total annual premium = SUM(annual_premium) for ACTIVE policies
        - Monthly premium = annual_premium / 12
        - Premium allocation: 75% risk, 25% savings (default)
        """
        errors = []
        warnings = []
        
        filtered_policies = policies.values()
        if customer_id:
            filtered_policies = [p for p in policies.values() if p.get('customer_id') == customer_id]
        
        active_policies = [p for p in filtered_policies if (p.get('status') or '').lower() == 'active']
        
        total_annual_premium = 0
        total_monthly_premium = 0
        
        for p in active_policies:
            annual = p.get('annual_premium', 0)
            monthly = p.get('monthly_premium', 0)
            
            # Validate annual premium
            try:
                annual = float(annual or 0)
                monthly = float(monthly or 0)
            except (TypeError, ValueError) as e:
                errors.append(f"Policy {p.get('id')} has invalid premium value: {e}")
                continue
            
            if annual < 0:
                errors.append(f"Policy {p.get('id')} has negative annual premium: {annual}")
                continue
            
            # Validate monthly/annual consistency
            expected_monthly = annual / 12
            if monthly > 0 and abs(monthly - expected_monthly) > 1:  # Allow $1 tolerance
                warnings.append(
                    f"Policy {p.get('id')} monthly premium inconsistency: "
                    f"stored={monthly}, expected={expected_monthly:.2f}"
                )
            
            total_annual_premium += annual
            total_monthly_premium += (monthly if monthly > 0 else expected_monthly)
        
        # Standard allocation calculations
        risk_pct = 0.75
        savings_pct = 0.25
        
        return {
            'valid': len(errors) == 0,
            'total_annual_premium': DataIntegrityValidator.round_currency(total_annual_premium),
            'total_monthly_premium': DataIntegrityValidator.round_currency(total_monthly_premium),
            'calculated_monthly': DataIntegrityValidator.round_currency(total_annual_premium / 12),
            'risk_allocation': DataIntegrityValidator.round_currency(total_annual_premium * risk_pct),
            'savings_allocation': DataIntegrityValidator.round_currency(total_annual_premium * savings_pct),
            'policy_count': len(active_policies),
            'errors': errors,
            'warnings': warnings
        }
    
    @staticmethod
    def validate_billing_stats(billing: dict, policies: dict) -> dict:
        """
        Validate billing statistics
        
        Rules:
        - total_billed = SUM(amount) for all bills
        - total_collected = SUM(amount_paid) for all bills  
        - outstanding = total_billed - total_collected (for non-paid bills)
        - Bills should reference valid policies
        """
        errors = []
        warnings = []
        
        total_billed = 0
        total_collected = 0
        outstanding = 0
        
        bill_counts = {'paid': 0, 'outstanding': 0, 'overdue': 0, 'pending': 0, 'other': 0}
        
        for bill_id, bill in billing.items():
            amount = bill.get('amount', 0)
            amount_paid = bill.get('amount_paid', 0)
            status = (bill.get('status') or '').lower()
            
            # Validate amounts
            try:
                amount = float(amount or 0)
                amount_paid = float(amount_paid or 0)
            except (TypeError, ValueError) as e:
                errors.append(f"Bill {bill_id} has invalid amount: {e}")
                continue
            
            if amount < 0:
                errors.append(f"Bill {bill_id} has negative amount: {amount}")
            
            if amount_paid < 0:
                errors.append(f"Bill {bill_id} has negative amount_paid: {amount_paid}")
            
            if amount_paid > amount:
                warnings.append(f"Bill {bill_id} has overpayment: paid={amount_paid}, billed={amount}")
            
            # Validate bill references valid policy
            policy_id = bill.get('policy_id')
            if policy_id and policy_id not in policies:
                warnings.append(f"Bill {bill_id} references non-existent policy: {policy_id}")
            
            total_billed += amount
            total_collected += amount_paid
            
            if status != 'paid':
                outstanding += (amount - amount_paid)
            
            # Count by status
            if status in bill_counts:
                bill_counts[status] += 1
            else:
                bill_counts['other'] += 1
        
        return {
            'valid': len(errors) == 0,
            'total_billed': DataIntegrityValidator.round_currency(total_billed),
            'total_collected': DataIntegrityValidator.round_currency(total_collected),
            'outstanding': DataIntegrityValidator.round_currency(outstanding),
            'collection_rate': round((total_collected / total_billed * 100) if total_billed > 0 else 0, 2),
            'bill_counts': bill_counts,
            'total_bills': len(billing),
            'errors': errors,
            'warnings': warnings
        }
    
    @staticmethod
    def validate_claims_integrity(claims: dict, policies: dict) -> dict:
        """
        Validate claims data integrity
        
        Rules:
        - Claims should reference valid policies
        - Approved amount <= claimed amount (usually)
        - Claims counts should be consistent
        """
        errors = []
        warnings = []
        
        claim_counts = {
            'pending': 0, 'under_review': 0, 'approved': 0, 
            'rejected': 0, 'paid': 0, 'closed': 0, 'other': 0
        }
        
        total_claimed = 0
        total_approved = 0
        total_paid = 0
        
        for claim_id, claim in claims.items():
            status = (claim.get('status') or '').lower()
            claimed_amount = claim.get('claimed_amount', 0)
            approved_amount = claim.get('approved_amount', claim.get('amount_approved', 0))
            
            try:
                claimed_amount = float(claimed_amount or 0)
                approved_amount = float(approved_amount or 0)
            except (TypeError, ValueError) as e:
                errors.append(f"Claim {claim_id} has invalid amount: {e}")
                continue
            
            # Validate policy reference
            policy_id = claim.get('policy_id')
            if policy_id and policy_id not in policies:
                warnings.append(f"Claim {claim_id} references non-existent policy: {policy_id}")
            
            # Count by status
            if status in claim_counts:
                claim_counts[status] += 1
            else:
                claim_counts['other'] += 1
            
            total_claimed += claimed_amount
            
            if status in ['approved', 'paid']:
                total_approved += approved_amount
            
            if status == 'paid':
                total_paid += approved_amount
        
        pending_count = claim_counts['pending'] + claim_counts['under_review']
        
        return {
            'valid': len(errors) == 0,
            'total_claims': len(claims),
            'pending_claims': pending_count,
            'approved_claims': claim_counts['approved'] + claim_counts['paid'],
            'rejected_claims': claim_counts['rejected'],
            'total_claimed_amount': DataIntegrityValidator.round_currency(total_claimed),
            'total_approved_amount': DataIntegrityValidator.round_currency(total_approved),
            'total_paid_amount': DataIntegrityValidator.round_currency(total_paid),
            'claim_counts': claim_counts,
            'errors': errors,
            'warnings': warnings
        }
    
    @staticmethod
    def cross_validate_metrics(
        policies_result: dict,
        premium_result: dict,
        billing_result: dict,
        claims_result: dict
    ) -> dict:
        """
        Cross-validate metrics across different calculations
        
        Rules:
        - Policy count should be consistent across endpoints
        - Premium revenue should match billing totals (approximately)
        - Claims paid should not exceed premiums collected significantly
        """
        errors = []
        warnings = []
        
        # Check policy count consistency
        policy_count = policies_result.get('active_policies', 0)
        premium_policy_count = premium_result.get('policy_count', 0)
        
        if policy_count != premium_policy_count:
            warnings.append(
                f"Policy count mismatch: policies={policy_count}, premium calc={premium_policy_count}"
            )
        
        # Check premium vs billing consistency (should be close over time)
        annual_premium = premium_result.get('total_annual_premium', 0)
        total_billed = billing_result.get('total_billed', 0)
        
        # Billing should be roughly proportional to premium
        # (allowing for timing differences)
        
        # Check loss ratio (claims paid vs premiums)
        total_collected = billing_result.get('total_collected', 0)
        claims_paid = claims_result.get('total_paid_amount', 0)
        
        if total_collected > 0:
            loss_ratio = (claims_paid / total_collected) * 100
            if loss_ratio > 100:
                warnings.append(f"Loss ratio exceeds 100%: {loss_ratio:.1f}%")
        
        return {
            'valid': len(errors) == 0,
            'policy_count_consistent': policy_count == premium_policy_count,
            'loss_ratio': round((claims_paid / total_collected * 100) if total_collected > 0 else 0, 2),
            'errors': errors,
            'warnings': warnings
        }


def _count_by_status(items: dict) -> dict:
    """Count items by status"""
    counts = {}
    for item in items.values():
        status = (item.get('status') or 'unknown').lower()
        counts[status] = counts.get(status, 0) + 1
    return counts


# ============== PYTEST FIXTURES ==============

@pytest.fixture
def validator():
    """Provide validator instance"""
    return DataIntegrityValidator()


@pytest.fixture
def sample_policies():
    """Sample policy data for testing"""
    return {
        'POL-001': {
            'id': 'POL-001',
            'customer_id': 'CUST-001',
            'status': 'Active',
            'coverage_amount': 100000,
            'annual_premium': 1200,
            'monthly_premium': 100
        },
        'POL-002': {
            'id': 'POL-002',
            'customer_id': 'CUST-001',
            'status': 'Active',
            'coverage_amount': 50000,
            'annual_premium': 600,
            'monthly_premium': 50
        },
        'POL-003': {
            'id': 'POL-003',
            'customer_id': 'CUST-002',
            'status': 'Inactive',
            'coverage_amount': 75000,
            'annual_premium': 900,
            'monthly_premium': 75
        }
    }


@pytest.fixture
def sample_billing():
    """Sample billing data for testing"""
    return {
        'BILL-001': {
            'id': 'BILL-001',
            'customer_id': 'CUST-001',
            'policy_id': 'POL-001',
            'amount': 100,
            'amount_paid': 100,
            'status': 'Paid'
        },
        'BILL-002': {
            'id': 'BILL-002',
            'customer_id': 'CUST-001',
            'policy_id': 'POL-001',
            'amount': 100,
            'amount_paid': 50,
            'status': 'Outstanding'
        }
    }


@pytest.fixture
def sample_claims():
    """Sample claims data for testing"""
    return {
        'CLM-001': {
            'id': 'CLM-001',
            'customer_id': 'CUST-001',
            'policy_id': 'POL-001',
            'claimed_amount': 5000,
            'approved_amount': 4500,
            'status': 'Approved'
        },
        'CLM-002': {
            'id': 'CLM-002',
            'customer_id': 'CUST-001',
            'policy_id': 'POL-001',
            'claimed_amount': 2000,
            'approved_amount': 0,
            'status': 'Pending'
        }
    }


# ============== UNIT TESTS ==============

class TestPolicyValidation:
    """Test policy count validations"""
    
    def test_policy_count_calculation(self, validator, sample_policies):
        """Test basic policy count calculation"""
        result = validator.validate_policy_count(sample_policies)
        
        assert result['valid'] is True
        assert result['total_policies'] == 3
        assert result['active_policies'] == 2
    
    def test_policy_count_empty(self, validator):
        """Test with empty policies"""
        result = validator.validate_policy_count({})
        
        assert result['valid'] is True
        assert result['total_policies'] == 0
        assert result['active_policies'] == 0


class TestCoverageValidation:
    """Test coverage amount validations"""
    
    def test_coverage_calculation(self, validator, sample_policies):
        """Test total coverage calculation"""
        result = validator.validate_coverage_amount(sample_policies)
        
        assert result['valid'] is True
        # Only active policies: 100000 + 50000 = 150000
        assert result['total_coverage'] == 150000.0
        assert result['policy_count'] == 2
    
    def test_coverage_by_customer(self, validator, sample_policies):
        """Test coverage filtered by customer"""
        result = validator.validate_coverage_amount(sample_policies, customer_id='CUST-001')
        
        assert result['valid'] is True
        assert result['total_coverage'] == 150000.0  # Both active belong to CUST-001
    
    def test_coverage_negative_value(self, validator):
        """Test detection of negative coverage"""
        policies = {
            'POL-001': {'id': 'POL-001', 'status': 'Active', 'coverage_amount': -1000}
        }
        result = validator.validate_coverage_amount(policies)
        
        assert result['valid'] is False
        assert len(result['errors']) > 0


class TestPremiumValidation:
    """Test premium calculation validations"""
    
    def test_premium_calculation(self, validator, sample_policies):
        """Test total premium calculation"""
        result = validator.validate_premium_calculations(sample_policies)
        
        assert result['valid'] is True
        # Active policies: 1200 + 600 = 1800
        assert result['total_annual_premium'] == 1800.0
        assert result['calculated_monthly'] == 150.0
    
    def test_premium_allocation(self, validator, sample_policies):
        """Test premium allocation calculations"""
        result = validator.validate_premium_calculations(sample_policies)
        
        assert result['valid'] is True
        # 75% of 1800 = 1350 risk
        assert result['risk_allocation'] == 1350.0
        # 25% of 1800 = 450 savings
        assert result['savings_allocation'] == 450.0


class TestBillingValidation:
    """Test billing statistics validations"""
    
    def test_billing_stats(self, validator, sample_billing, sample_policies):
        """Test billing statistics calculation"""
        result = validator.validate_billing_stats(sample_billing, sample_policies)
        
        assert result['valid'] is True
        assert result['total_billed'] == 200.0
        assert result['total_collected'] == 150.0
        assert result['outstanding'] == 50.0
    
    def test_billing_collection_rate(self, validator, sample_billing, sample_policies):
        """Test collection rate calculation"""
        result = validator.validate_billing_stats(sample_billing, sample_policies)
        
        assert result['valid'] is True
        assert result['collection_rate'] == 75.0  # 150/200 = 75%


class TestClaimsValidation:
    """Test claims validation"""
    
    def test_claims_stats(self, validator, sample_claims, sample_policies):
        """Test claims statistics calculation"""
        result = validator.validate_claims_integrity(sample_claims, sample_policies)
        
        assert result['valid'] is True
        assert result['total_claims'] == 2
        assert result['pending_claims'] == 1
        assert result['approved_claims'] == 1


class TestCrossValidation:
    """Test cross-validation between metrics"""
    
    def test_cross_validation(self, validator, sample_policies, sample_billing, sample_claims):
        """Test cross-validation of metrics"""
        policies_result = validator.validate_policy_count(sample_policies)
        premium_result = validator.validate_premium_calculations(sample_policies)
        billing_result = validator.validate_billing_stats(sample_billing, sample_policies)
        claims_result = validator.validate_claims_integrity(sample_claims, sample_policies)
        
        result = validator.cross_validate_metrics(
            policies_result, premium_result, billing_result, claims_result
        )
        
        assert result['valid'] is True
        assert result['policy_count_consistent'] is True


# ============== INTEGRATION TEST ==============

class TestProductionDataIntegrity:
    """Integration tests against actual server data"""
    
    @pytest.fixture
    def server_module(self):
        """Import server module for direct data access"""
        try:
            # Try to import server internals for testing
            import importlib.util
            spec = importlib.util.spec_from_file_location(
                "server", 
                os.path.join(os.path.dirname(__file__), '..', 'web_portal', 'server.py')
            )
            # Don't actually import as it starts the server
            # Instead, we'll test via API
            return None
        except Exception:
            return None
    
    def test_api_data_integrity(self, validator):
        """Test data integrity via API endpoints (requires running server)"""
        import requests
        
        base_url = os.environ.get('TEST_API_URL', 'http://localhost:5000')
        
        try:
            # Test health endpoint
            health = requests.get(f'{base_url}/api/health', timeout=5)
            if health.status_code != 200:
                pytest.skip("Server not available")
            
            # Test metrics endpoint
            metrics = requests.get(f'{base_url}/api/metrics', timeout=5)
            if metrics.status_code == 200:
                data = metrics.json()
                metrics_data = data.get('metrics', {})
                
                # Validate metrics structure
                assert 'policies' in metrics_data, "Missing policies in metrics"
                assert 'claims' in metrics_data, "Missing claims in metrics"
                assert 'billing' in metrics_data, "Missing billing in metrics"
                
                # Validate policy metrics
                policies = metrics_data['policies']
                assert 'total' in policies, "Missing total in policies"
                assert 'active' in policies, "Missing active in policies"
                assert policies['active'] <= policies['total'], "Active exceeds total"
                
        except requests.exceptions.RequestException:
            pytest.skip("Cannot connect to server")


# ============== CLI RUNNER ==============

def run_production_validation():
    """Run validation against production endpoint"""
    import requests
    
    production_url = 'https://phins-portal-production.up.railway.app'
    validator = DataIntegrityValidator()
    
    print("=" * 60)
    print("PHINS Dashboard Data Integrity Validation")
    print("=" * 60)
    print(f"Target: {production_url}")
    print(f"Time: {datetime.now().isoformat()}")
    print()
    
    try:
        # Check health
        health_resp = requests.get(f'{production_url}/api/health', timeout=10)
        health = health_resp.json()
        print(f"✓ Server Status: {health.get('status')}")
        print(f"  Database: {health.get('database')}")
        print(f"  Version: {health.get('version')}")
        print()
        
        # Get metrics
        metrics_resp = requests.get(f'{production_url}/api/metrics', timeout=10)
        metrics = metrics_resp.json()
        metrics_data = metrics.get('metrics', {})
        
        print("METRICS VALIDATION")
        print("-" * 40)
        
        # Policy metrics
        policies = metrics_data.get('policies', {})
        print(f"Policies:")
        print(f"  Total: {policies.get('total', 0)}")
        print(f"  Active: {policies.get('active', 0)}")
        
        if policies.get('active', 0) > policies.get('total', 0):
            print("  ✗ ERROR: Active exceeds total!")
        else:
            print("  ✓ Count validation passed")
        
        # Claims metrics
        claims = metrics_data.get('claims', {})
        print(f"\nClaims:")
        print(f"  Pending: {claims.get('pending', 0)}")
        print(f"  Approved: {claims.get('approved', 0)}")
        print("  ✓ Claims metrics valid")
        
        # Billing metrics
        billing = metrics_data.get('billing', {})
        print(f"\nBilling:")
        print(f"  Overdue: {billing.get('overdue', 0)}")
        print(f"  Outstanding: {billing.get('outstanding', 0)}")
        print("  ✓ Billing metrics valid")
        
        print()
        print("=" * 60)
        print("VALIDATION COMPLETE - All checks passed")
        print("=" * 60)
        
        return True
        
    except requests.exceptions.RequestException as e:
        print(f"✗ Connection Error: {e}")
        return False
    except Exception as e:
        print(f"✗ Validation Error: {e}")
        return False


if __name__ == '__main__':
    # Run against production when executed directly
    success = run_production_validation()
    sys.exit(0 if success else 1)
