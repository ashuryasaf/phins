"""
Tests for Platform Integrity Service
=====================================
Tests comprehensive data integrity validation across all pipelines.
"""

import pytest
from services.platform_integrity_service import PlatformIntegrityService


@pytest.fixture
def integrity_service():
    """Create platform integrity service instance"""
    return PlatformIntegrityService()


def test_user_validation(integrity_service):
    """Test user type and role validation"""
    users = {
        'admin': {'hash': 'hash1', 'salt': 'salt1', 'role': 'admin', 'name': 'Admin'},
        'customer': {'hash': 'hash2', 'salt': 'salt2', 'role': 'customer', 'name': 'Customer'},
        'invalid_user': {'hash': 'hash3', 'salt': 'salt3', 'role': 'invalid_role', 'name': 'Invalid'}
    }
    
    result = integrity_service._validate_users(users)
    
    assert result['total_users'] == 3
    assert result['invalid_roles'] == 1
    assert result['status'] == 'FAIL'  # Due to invalid role


def test_customer_validation(integrity_service):
    """Test customer record validation"""
    users = {
        'customer@test.com': {'role': 'customer', 'hash': 'h', 'salt': 's', 'name': 'Customer'}
    }
    
    customers = {
        'CUST-001': {'id': 'CUST-001', 'email': 'customer@test.com', 'name': 'Customer'},
        'CUST-002': {'id': 'CUST-002', 'email': None, 'name': 'No Email'},  # Missing email
        'CUST-003': {'id': 'CUST-003', 'email': 'orphan@test.com', 'name': 'Orphan'}  # No user account
    }
    
    result = integrity_service._validate_customers(customers, users)
    
    assert result['total_customers'] == 3
    assert result['missing_email'] == 1
    assert result['missing_user_account'] == 1
    assert result['status'] == 'FAIL'  # Due to missing email


def test_policy_pipeline_validation(integrity_service):
    """Test policy pipeline integrity"""
    customers = {
        'CUST-001': {'id': 'CUST-001', 'email': 'test@test.com'}
    }
    
    policies = {
        'POL-001': {'id': 'POL-001', 'customer_id': 'CUST-001', 'status': 'active'},
        'POL-002': {'id': 'POL-002', 'customer_id': 'CUST-999', 'status': 'active'},  # Orphaned
        'POL-003': {'id': 'POL-003', 'customer_id': 'CUST-001', 'status': 'active', 'underwriting_id': 'UW-MISSING'}
    }
    
    underwriting_applications = {}
    billing = {}
    
    result = integrity_service._validate_policy_pipeline(
        customers, policies, underwriting_applications, billing
    )
    
    assert result['total_policies'] == 3
    assert result['orphaned_policies'] == 1
    assert result['policies_without_billing'] == 3  # All active but no billing
    assert result['missing_underwriting'] == 1
    assert result['status'] == 'FAIL'  # Due to orphaned policy


def test_claims_pipeline_validation(integrity_service):
    """Test claims pipeline integrity"""
    policies = {
        'POL-001': {'id': 'POL-001', 'customer_id': 'CUST-001'}
    }
    
    claims = {
        'CLM-001': {'id': 'CLM-001', 'policy_id': 'POL-001', 'customer_id': 'CUST-001', 'status': 'pending'},
        'CLM-002': {'id': 'CLM-002', 'policy_id': 'POL-999', 'customer_id': 'CUST-001', 'status': 'paid'},  # Orphaned
        'CLM-003': {'id': 'CLM-003', 'policy_id': 'POL-001', 'customer_id': 'CUST-001', 'status': 'paid'}
    }
    
    health_wallets = {
        'CUST-001': {'customer_id': 'CUST-001', 'balance': 1000.0, 'transactions': []}
    }
    
    transaction_ledger = {}
    
    result = integrity_service._validate_claims_pipeline(
        policies, claims, health_wallets, transaction_ledger
    )
    
    assert result['total_claims'] == 3
    assert result['orphaned_claims'] == 1
    assert result['paid_claims_without_wallet_tx'] == 2  # Both paid claims have no wallet tx
    assert result['status'] == 'FAIL'  # Due to orphaned claim


def test_billing_pipeline_validation(integrity_service):
    """Test billing pipeline integrity"""
    policies = {
        'POL-001': {'id': 'POL-001', 'customer_id': 'CUST-001'}
    }
    
    billing = {
        'BILL-001': {'id': 'BILL-001', 'policy_id': 'POL-001', 'amount': 100.0, 'amount_paid': 50.0},
        'BILL-002': {'id': 'BILL-002', 'policy_id': 'POL-999', 'amount': 200.0, 'amount_paid': 0.0},  # Orphaned
        'BILL-003': {'id': 'BILL-003', 'policy_id': 'POL-001', 'amount': -50.0, 'amount_paid': 0.0}  # Negative
    }
    
    balance_sheet = {}
    
    result = integrity_service._validate_billing_pipeline(
        policies, billing, balance_sheet
    )
    
    assert result['total_bills'] == 3
    assert result['orphaned_bills'] == 1
    assert result['negative_amounts'] == 1
    assert result['total_billed'] == 250.0  # 100 + 200 + (-50)
    assert result['total_paid'] == 50.0
    assert result['total_outstanding'] == 200.0
    assert result['status'] == 'FAIL'  # Due to orphaned bill and negative amount


def test_ledger_integrity_validation(integrity_service):
    """Test wallet and ledger integrity"""
    customers = {
        'CUST-001': {'id': 'CUST-001', 'email': 'test@test.com'}
    }
    
    health_wallets = {
        'CUST-001': {'customer_id': 'CUST-001', 'balance': 1000.0},
        'CUST-999': {'customer_id': 'CUST-999', 'balance': 500.0},  # Orphaned
        'CUST-002': {'customer_id': 'CUST-002', 'balance': -100.0}  # Negative balance (error)
    }
    
    investment_accounts = {
        'CUST-001': {'customer_id': 'CUST-001', 'balance': 5000.0}
    }
    
    transaction_ledger = {}
    
    result = integrity_service._validate_ledger_integrity(
        customers, health_wallets, investment_accounts, transaction_ledger
    )
    
    assert result['total_wallets'] == 3
    assert result['orphaned_wallets'] == 2  # CUST-999 and CUST-002
    assert result['negative_balances'] == 1
    assert result['total_wallet_balance'] == 1400.0
    assert result['status'] == 'FAIL'  # Due to orphaned wallets and negative balance


def test_complete_validation(integrity_service):
    """Test complete platform validation"""
    users = {
        'admin': {'hash': 'h', 'salt': 's', 'role': 'admin', 'name': 'Admin'},
        'customer@test.com': {'hash': 'h', 'salt': 's', 'role': 'customer', 'name': 'Customer'}
    }
    
    customers = {
        'CUST-001': {'id': 'CUST-001', 'email': 'customer@test.com', 'name': 'Customer'}
    }
    
    suppliers = {}
    
    policies = {
        'POL-001': {'id': 'POL-001', 'customer_id': 'CUST-001', 'status': 'active'}
    }
    
    claims = {}
    
    billing = {
        'BILL-001': {'id': 'BILL-001', 'policy_id': 'POL-001', 'amount': 100.0, 'amount_paid': 100.0}
    }
    
    underwriting_applications = {}
    
    health_wallets = {
        'CUST-001': {'customer_id': 'CUST-001', 'balance': 1000.0}
    }
    
    investment_accounts = {}
    
    transaction_ledger = {}
    
    balance_sheet = {
        'total_assets': 100000.0,
        'total_liabilities': 20000.0,
        'claims_reserve': 50000.0
    }
    
    result = integrity_service.validate_all(
        users=users,
        customers=customers,
        suppliers=suppliers,
        policies=policies,
        claims=claims,
        billing=billing,
        underwriting_applications=underwriting_applications,
        health_wallets=health_wallets,
        investment_accounts=investment_accounts,
        transaction_ledger=transaction_ledger,
        balance_sheet=balance_sheet
    )
    
    assert 'timestamp' in result
    assert 'status' in result
    assert 'summary' in result
    assert 'validation_results' in result
    assert 'errors' in result
    assert 'warnings' in result
    
    summary = result['summary']
    assert summary['total_checks'] > 0
    assert 'passed_checks' in summary
    assert 'failed_checks' in summary
    assert 'errors_found' in summary
    assert 'warnings_found' in summary


def test_supplier_order_validation(integrity_service):
    """Test supplier order pipeline validation"""
    suppliers = {
        'SUP-001': {'id': 'SUP-001', 'contact_email': 'supplier@test.com'}
    }
    
    customers = {
        'CUST-001': {'id': 'CUST-001', 'email': 'customer@test.com'}
    }
    
    supplier_orders = {
        'ORD-001': {'id': 'ORD-001', 'supplier_id': 'SUP-001', 'customer_id': 'CUST-001'},
        'ORD-002': {'id': 'ORD-002', 'supplier_id': 'SUP-999', 'customer_id': 'CUST-001'},  # Orphaned supplier
        'ORD-003': {'id': 'ORD-003', 'supplier_id': 'SUP-001', 'customer_id': 'CUST-999'}  # Orphaned customer
    }
    
    result = integrity_service._validate_supplier_orders(
        supplier_orders, suppliers, customers
    )
    
    assert result['total_orders'] == 3
    assert result['orphaned_supplier_orders'] == 1
    assert result['orphaned_customer_orders'] == 1
    assert result['status'] == 'FAIL'


def test_validation_summary_generation(integrity_service):
    """Test validation summary generation"""
    # Simulate some validation results
    integrity_service.validation_results = {
        'users': {'status': 'PASS'},
        'customers': {'status': 'PASS'},
        'policies': {'status': 'FAIL'},
        'claims': {'status': 'PASS'}
    }
    
    integrity_service.errors = [
        {'category': 'policies', 'message': 'Error 1'},
        {'category': 'policies', 'message': 'Error 2'}
    ]
    
    integrity_service.warnings = [
        {'category': 'claims', 'message': 'Warning 1'}
    ]
    
    summary = integrity_service._generate_validation_summary()
    
    assert summary['total_checks'] == 4
    assert summary['passed_checks'] == 3
    assert summary['failed_checks'] == 1
    assert summary['errors_found'] == 2
    assert summary['warnings_found'] == 1
    assert summary['overall_status'] == 'FAIL'


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
