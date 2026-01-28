"""
Test Advanced Portfolio Integrity Service
=========================================
Tests for the cryptographic validation and reset functionality.
"""

import pytest
from services.advanced_portfolio_integrity_service import (
    AdvancedPortfolioIntegrityService,
    ValidationLevel,
    IntegrityStatus,
    BalanceSnapshot,
    IntegrityValidationResult,
    ResetResult
)


@pytest.fixture
def service():
    """Create a test instance of the service"""
    health_wallets = {
        'CUST-001': {
            'customer_id': 'CUST-001',
            'balance': 5000.00,
            'transactions': [],
            'monthly_deposit': 500
        }
    }
    investment_accounts = {
        'CUST-001': {
            'customer_id': 'CUST-001',
            'balance': 10000.00,
            'index_balance': 6000.00,
            'bonds_balance': 3000.00,
            'crypto_balance': 1000.00,
            'deposits': []
        }
    }
    transaction_ledger = {}
    nft_ledger = {}
    
    return AdvancedPortfolioIntegrityService(
        health_wallets=health_wallets,
        investment_accounts=investment_accounts,
        transaction_ledger=transaction_ledger,
        nft_ledger=nft_ledger
    )


def test_capture_balance_snapshot(service):
    """Test capturing a cryptographically signed balance snapshot"""
    snapshot = service.capture_balance_snapshot('CUST-001')
    
    assert snapshot.customer_id == 'CUST-001'
    assert snapshot.health_wallet == 5000.00
    assert snapshot.investment_cash == 10000.00
    assert snapshot.invested_assets == 10000.00  # index + bonds + crypto
    assert snapshot.hash_signature != ''
    assert snapshot.sequence_number == 0


def test_snapshot_hash_verification(service):
    """Test that snapshot hash can be verified"""
    snapshot = service.capture_balance_snapshot('CUST-001')
    
    # Hash should verify correctly
    assert snapshot.verify_hash() == True
    
    # Tamper with the snapshot
    snapshot.health_wallet = 999999
    
    # Hash should now fail
    assert snapshot.verify_hash() == False


def test_snapshot_chain_integrity(service):
    """Test hash chain integrity across multiple snapshots"""
    # Capture multiple snapshots
    snap1 = service.capture_balance_snapshot('CUST-001')
    snap2 = service.capture_balance_snapshot('CUST-001')
    snap3 = service.capture_balance_snapshot('CUST-001')
    
    # Verify chain linkage
    assert snap2.previous_hash == snap1.hash_signature
    assert snap3.previous_hash == snap2.hash_signature
    
    # Verify sequence numbers
    assert snap1.sequence_number == 0
    assert snap2.sequence_number == 1
    assert snap3.sequence_number == 2


def test_validate_integrity_valid_state(service):
    """Test integrity validation for valid state"""
    result = service.validate_integrity('CUST-001', ValidationLevel.STANDARD)
    
    assert result.is_valid == True
    assert result.status == IntegrityStatus.VALID
    assert result.score >= 90
    assert result.balances_valid == True
    assert len(result.issues) == 0


def test_validate_integrity_with_negative_balance():
    """Test integrity validation detects negative balances"""
    health_wallets = {
        'CUST-002': {
            'balance': -100.00  # Invalid negative balance
        }
    }
    
    service = AdvancedPortfolioIntegrityService(
        health_wallets=health_wallets,
        investment_accounts={},
        transaction_ledger={},
        nft_ledger={}
    )
    
    result = service.validate_integrity('CUST-002', ValidationLevel.STANDARD)
    
    # Negative balance should be detected and flagged
    assert result.balances_valid == False
    assert any('Negative' in issue for issue in result.issues)
    # Status should be WARNING (score 75) since only one issue
    assert result.status == IntegrityStatus.WARNING
    assert result.score < 100


def test_reset_portfolio_full(service):
    """Test full portfolio reset"""
    # Verify initial state has balances
    initial_snapshot = service.capture_balance_snapshot('CUST-001')
    assert initial_snapshot.total_portfolio > 0
    
    # Execute reset
    result = service.reset_portfolio('CUST-001', 'full', True)
    
    assert result.success == True
    assert result.reset_type == 'full'
    assert result.audit_token != ''
    assert len(result.components_reset) > 0
    
    # Verify balances are now zero
    post_snapshot = service.capture_balance_snapshot('CUST-001')
    assert post_snapshot.health_wallet == 0.0
    assert post_snapshot.investment_cash == 0.0
    assert post_snapshot.invested_assets == 0.0


def test_reset_portfolio_preserves_history(service):
    """Test that reset preserves transaction history when requested"""
    # Add some test transactions
    service.health_wallets['CUST-001']['transactions'] = [
        {'id': 'tx1', 'amount': 100}
    ]
    
    # Reset with preserve_history=True
    result = service.reset_portfolio('CUST-001', 'full', preserve_history=True)
    
    assert result.success == True
    # History should be preserved
    assert len(service.health_wallets['CUST-001'].get('transactions', [])) > 0


def test_get_display_data(service):
    """Test getting verified display data for all tabs"""
    display_data = service.get_display_data('CUST-001')
    
    assert display_data['customer_id'] == 'CUST-001'
    assert 'display_tabs' in display_data
    
    tabs = display_data['display_tabs']
    assert 'total_portfolio' in tabs
    assert 'health_wallet' in tabs
    assert 'invested_assets' in tabs
    assert 'investment_cash' in tabs
    assert 'algo_trading' in tabs
    
    # Check formatting
    assert tabs['total_portfolio']['formatted'].startswith('$')
    assert tabs['health_wallet']['value'] == 5000.00


def test_validation_levels(service):
    """Test different validation levels"""
    standard = service.validate_integrity('CUST-001', ValidationLevel.STANDARD)
    strict = service.validate_integrity('CUST-001', ValidationLevel.STRICT)
    audit = service.validate_integrity('CUST-001', ValidationLevel.AUDIT)
    
    # All should pass for valid state
    assert standard.is_valid == True
    assert strict.is_valid == True
    assert audit.is_valid == True
    
    # Validation level should be recorded
    assert standard.validation_level == ValidationLevel.STANDARD
    assert strict.validation_level == ValidationLevel.STRICT
    assert audit.validation_level == ValidationLevel.AUDIT


def test_audit_token_uniqueness(service):
    """Test that audit tokens are unique across resets"""
    result1 = service.reset_portfolio('CUST-001', 'full', True)
    
    # Re-add some balance for second reset
    service.health_wallets['CUST-001']['balance'] = 1000
    
    result2 = service.reset_portfolio('CUST-001', 'full', True)
    
    # Audit tokens should be different
    assert result1.audit_token != result2.audit_token


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
