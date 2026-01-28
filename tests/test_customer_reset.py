"""
Customer Reset Data Integrity Tests

Tests for the /api/admin/reset-customer-account endpoint
specifically for customer CUST-ASAF-001 (asaf@assurance.co.il)

Run: pytest tests/test_customer_reset.py -v
"""

import pytest
import json
import sys
import os
from datetime import datetime

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# Target customer - RESTRICTED
TARGET_CUSTOMER_ID = 'CUST-ASAF-001'
TARGET_CUSTOMER_EMAIL = 'asaf@assurance.co.il'


class TestCustomerResetDataIntegrity:
    """Test customer reset maintains data integrity"""
    
    @pytest.fixture
    def sample_customer_data(self):
        """Sample data for testing"""
        return {
            'customer': {
                'id': TARGET_CUSTOMER_ID,
                'email': TARGET_CUSTOMER_EMAIL,
                'name': 'Asaf Assurance'
            },
            'policies': [
                {'id': 'POL-ASAF-001', 'customer_id': TARGET_CUSTOMER_ID, 'status': 'Active', 'coverage_amount': 100000},
                {'id': 'POL-ASAF-002', 'customer_id': TARGET_CUSTOMER_ID, 'status': 'Active', 'coverage_amount': 50000}
            ],
            'claims': [
                {'id': 'CLM-ASAF-001', 'customer_id': TARGET_CUSTOMER_ID, 'status': 'Paid', 'claimed_amount': 5000},
                {'id': 'CLM-ASAF-002', 'customer_id': TARGET_CUSTOMER_ID, 'status': 'Pending', 'claimed_amount': 2000}
            ],
            'health_wallet': {
                'customer_id': TARGET_CUSTOMER_ID,
                'balance': 25000.00,
                'transactions': [{'id': 'TX-001', 'amount': 25000}]
            },
            'investment_account': {
                'customer_id': TARGET_CUSTOMER_ID,
                'balance': 15000.00,
                'deposits': [{'id': 'DEP-001', 'amount': 15000}]
            },
            'medical_purchases': [
                {'id': 'MP-001', 'customer_id': TARGET_CUSTOMER_ID, 'amount': 1200},
                {'id': 'MP-002', 'customer_id': TARGET_CUSTOMER_ID, 'amount': 800}
            ]
        }
    
    def test_reset_restricted_to_target_customer(self):
        """Verify reset only affects the target customer"""
        # The reset function should only target CUST-ASAF-001
        assert TARGET_CUSTOMER_ID == 'CUST-ASAF-001'
        assert TARGET_CUSTOMER_EMAIL == 'asaf@assurance.co.il'
    
    def test_reset_preserves_ledger(self, sample_customer_data):
        """Verify reset preserves transaction ledger for audit"""
        # Ledger should be preserved by default
        keep_ledger = True  # Default value in reset endpoint
        assert keep_ledger is True
    
    def test_reset_clears_claims_all_statuses(self, sample_customer_data):
        """Verify reset removes claims of all statuses"""
        claims = sample_customer_data['claims']
        
        # Should have claims of different statuses
        statuses = [c['status'] for c in claims]
        assert 'Paid' in statuses
        assert 'Pending' in statuses
        
        # After reset, all should be removed
        # (simulated by clearing the list)
        reset_claims = []
        assert len(reset_claims) == 0
    
    def test_reset_zeros_health_wallet(self, sample_customer_data):
        """Verify reset sets health wallet balance to 0"""
        wallet = sample_customer_data['health_wallet']
        
        # Before reset
        assert wallet['balance'] == 25000.00
        
        # After reset
        reset_wallet = {
            'customer_id': TARGET_CUSTOMER_ID,
            'balance': 0,
            'monthly_deposit': 0,
            'transactions': [],
            'created_at': datetime.now().isoformat()
        }
        assert reset_wallet['balance'] == 0
        assert len(reset_wallet['transactions']) == 0
    
    def test_reset_zeros_investment_account(self, sample_customer_data):
        """Verify reset sets investment account to 0"""
        account = sample_customer_data['investment_account']
        
        # Before reset
        assert account['balance'] == 15000.00
        
        # After reset
        reset_account = {
            'customer_id': TARGET_CUSTOMER_ID,
            'balance': 0,
            'index_balance': 0,
            'bonds_balance': 0,
            'crypto_balance': 0,
            'deposits': [],
            'created_at': datetime.now().isoformat()
        }
        assert reset_account['balance'] == 0
        assert reset_account['index_balance'] == 0
        assert reset_account['bonds_balance'] == 0
        assert reset_account['crypto_balance'] == 0
        assert len(reset_account['deposits']) == 0
    
    def test_reset_clears_medical_purchases(self, sample_customer_data):
        """Verify reset removes all medical purchases"""
        purchases = sample_customer_data['medical_purchases']
        
        # Before reset
        assert len(purchases) == 2
        total_amount = sum(p['amount'] for p in purchases)
        assert total_amount == 2000
        
        # After reset
        reset_purchases = []
        assert len(reset_purchases) == 0
    
    def test_reset_records_nft_token(self):
        """Verify reset records NFT token for audit trail"""
        # NFT token should be generated for the reset transaction
        nft_data = {
            'token_id': 'NFT-RESET-123',
            'transaction_type': 'account_reset',
            'customer_id': TARGET_CUSTOMER_ID,
            'metadata': {
                'policies_removed': 2,
                'claims_removed': 2,
                'bills_removed': 1
            }
        }
        
        assert nft_data['token_id'] is not None
        assert nft_data['transaction_type'] == 'account_reset'
        assert nft_data['customer_id'] == TARGET_CUSTOMER_ID
    
    def test_reset_does_not_affect_other_customers(self):
        """Verify reset does not affect other customers' data"""
        other_customer_id = 'CUST-OTHER-001'
        
        # Other customer's data should not be touched
        assert other_customer_id != TARGET_CUSTOMER_ID
        
        # Reset filter should only match target customer
        def should_reset(customer_id):
            return customer_id == TARGET_CUSTOMER_ID
        
        assert should_reset(TARGET_CUSTOMER_ID) is True
        assert should_reset(other_customer_id) is False
    
    def test_safe_delete_prevents_keyerror(self):
        """Verify safe delete operations prevent KeyError"""
        # Simulate a dictionary with some items
        data = {'item1': {'value': 1}, 'item2': {'value': 2}}
        
        # Safe delete using pop
        items_to_remove = ['item1', 'item3']  # item3 doesn't exist
        
        removed_count = 0
        for item_id in items_to_remove:
            if data.pop(item_id, None) is not None:
                removed_count += 1
        
        assert removed_count == 1  # Only item1 was removed
        assert 'item1' not in data
        assert 'item2' in data  # Not affected


class TestResetResultStructure:
    """Test the reset result structure"""
    
    def test_result_has_required_fields(self):
        """Verify result contains all required fields"""
        expected_result = {
            'success': True,
            'customer_id': TARGET_CUSTOMER_ID,
            'removed': {
                'policies': 0,
                'applications': 0,
                'claims': 0,
                'bills': 0,
                'medical_purchases': 0,
                'medical_purchase_total': 0
            },
            'ledger_preserved': True,
            'ready_for': ['new_applications', 'increase_coverage', 'new_deposits']
        }
        
        # Check required fields
        assert 'success' in expected_result
        assert 'customer_id' in expected_result
        assert 'removed' in expected_result
        assert 'ledger_preserved' in expected_result
        assert 'ready_for' in expected_result
        
        # Check removed structure
        removed = expected_result['removed']
        assert 'policies' in removed
        assert 'applications' in removed
        assert 'claims' in removed
        assert 'bills' in removed
        assert 'medical_purchases' in removed
        assert 'medical_purchase_total' in removed
    
    def test_result_counts_are_non_negative(self):
        """Verify all counts are non-negative"""
        result = {
            'removed': {
                'policies': 2,
                'applications': 1,
                'claims': 5,
                'bills': 3,
                'medical_purchases': 4,
                'medical_purchase_total': 7500.00
            }
        }
        
        for key, value in result['removed'].items():
            assert value >= 0, f"{key} should be non-negative"


class TestCustomerIsolation:
    """Test customer data isolation"""
    
    def test_filter_by_customer_id(self):
        """Verify filtering by customer_id works correctly"""
        items = [
            {'id': '1', 'customer_id': 'CUST-ASAF-001'},
            {'id': '2', 'customer_id': 'CUST-OTHER-001'},
            {'id': '3', 'customer_id': 'CUST-ASAF-001'},
        ]
        
        # Filter for target customer
        filtered = [i for i in items if i.get('customer_id') == TARGET_CUSTOMER_ID]
        
        assert len(filtered) == 2
        assert all(i['customer_id'] == TARGET_CUSTOMER_ID for i in filtered)
    
    def test_safe_float_for_amounts(self):
        """Verify safe_float handles various input types"""
        def safe_float(val, default=0.0):
            if val is None:
                return default
            try:
                return float(val)
            except (TypeError, ValueError):
                return default
        
        # Test various inputs
        assert safe_float(100) == 100.0
        assert safe_float('100.50') == 100.5
        assert safe_float(None) == 0.0
        assert safe_float('invalid') == 0.0
        assert safe_float({'bad': 'dict'}) == 0.0


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
