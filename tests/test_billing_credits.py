"""
PHINS Billing Credits Service Tests
===================================
Comprehensive tests for billing credit management, notifications, and ledger reporting.
"""

import pytest
from decimal import Decimal
from datetime import datetime, timedelta, timezone


class TestBillingCreditService:
    """Tests for the BillingCreditService"""
    
    @pytest.fixture
    def billing_data(self):
        """Sample billing data"""
        return {
            'BILL-001': {
                'bill_id': 'BILL-001',
                'customer_id': 'CUST-001',
                'policy_id': 'POL-001',
                'amount': 150.00,
                'amount_due': 150.00,
                'amount_paid': 0.0,
                'status': 'outstanding',
                'due_date': (datetime.now(timezone.utc) + timedelta(days=7)).isoformat(),
                'created_date': datetime.now(timezone.utc).isoformat()
            },
            'BILL-002': {
                'bill_id': 'BILL-002',
                'customer_id': 'CUST-001',
                'policy_id': 'POL-001',
                'amount': 150.00,
                'amount_due': 150.00,
                'amount_paid': 200.00,  # Overpayment!
                'status': 'paid',
                'due_date': (datetime.now(timezone.utc) - timedelta(days=30)).isoformat(),
                'created_date': (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
            },
            'BILL-003': {
                'bill_id': 'BILL-003',
                'customer_id': 'CUST-002',
                'policy_id': 'POL-002',
                'amount': 200.00,
                'amount_due': 200.00,
                'amount_paid': 0.0,
                'status': 'overdue',
                'due_date': (datetime.now(timezone.utc) - timedelta(days=10)).isoformat(),
                'created_date': (datetime.now(timezone.utc) - timedelta(days=40)).isoformat()
            }
        }
    
    @pytest.fixture
    def policies_data(self):
        """Sample policies data"""
        return {
            'POL-001': {
                'policy_id': 'POL-001',
                'customer_id': 'CUST-001',
                'type': 'Life Insurance',
                'coverage_amount': 500000,
                'monthly_premium': 150.00,
                'status': 'ACTIVE'
            },
            'POL-002': {
                'policy_id': 'POL-002',
                'customer_id': 'CUST-002',
                'type': 'Health Insurance',
                'coverage_amount': 100000,
                'monthly_premium': 200.00,
                'status': 'ACTIVE'
            }
        }
    
    @pytest.fixture
    def customers_data(self):
        """Sample customers data"""
        return {
            'CUST-001': {
                'customer_id': 'CUST-001',
                'name': 'John Doe',
                'email': 'john.doe@example.com',
                'phone': '+1234567890'
            },
            'CUST-002': {
                'customer_id': 'CUST-002',
                'name': 'Jane Smith',
                'email': 'jane.smith@example.com',
                'phone': '+0987654321'
            }
        }
    
    @pytest.fixture
    def health_wallets(self):
        """Sample health wallets"""
        return {
            'CUST-001': {
                'customer_id': 'CUST-001',
                'balance': 1000.00,
                'monthly_deposit': 100.00,
                'transactions': []
            }
        }
    
    @pytest.fixture
    def credit_service(self, billing_data, policies_data, customers_data, health_wallets):
        """Create billing credit service instance"""
        from services.billing_credit_service import BillingCreditService, reset_billing_credit_service
        
        # Reset singleton for clean test
        reset_billing_credit_service()
        
        return BillingCreditService(
            billing_data=billing_data,
            policies_data=policies_data,
            customers_data=customers_data,
            health_wallets=health_wallets
        )
    
    # ========== CREDIT CREATION TESTS ==========
    
    def test_create_credit(self, credit_service):
        """Test creating a billing credit"""
        from services.billing_credit_service import CreditType
        
        credit = credit_service.create_credit(
            customer_id='CUST-001',
            amount=50.00,
            credit_type=CreditType.OVERPAYMENT,
            reason='Overpayment on bill BILL-002',
            source_bill_id='BILL-002'
        )
        
        assert credit is not None
        assert credit.credit_id.startswith('CREDIT-')
        assert credit.customer_id == 'CUST-001'
        assert float(credit.amount) == 50.00
        assert float(credit.remaining_amount) == 50.00
        assert credit.credit_type == CreditType.OVERPAYMENT
        assert credit.source_bill_id == 'BILL-002'
    
    def test_get_customer_credit_balance(self, credit_service):
        """Test getting customer credit balance"""
        from services.billing_credit_service import CreditType
        
        # Create some credits
        credit_service.create_credit('CUST-001', 50.00, CreditType.OVERPAYMENT, 'Test 1')
        credit_service.create_credit('CUST-001', 25.00, CreditType.REFUND, 'Test 2')
        
        balance = credit_service.get_customer_credit_balance('CUST-001')
        
        assert balance['customer_id'] == 'CUST-001'
        assert balance['total_credit_balance'] == 75.00
        assert balance['active_credits_count'] == 2
        assert balance['can_withdraw'] == True
        assert balance['can_transfer_to_wallet'] == True
    
    # ========== CREDIT WITHDRAWAL TESTS ==========
    
    def test_withdraw_credit(self, credit_service):
        """Test withdrawing credit"""
        from services.billing_credit_service import CreditType
        
        # Create credit
        credit_service.create_credit('CUST-001', 100.00, CreditType.OVERPAYMENT, 'Test')
        
        # Withdraw
        result = credit_service.withdraw_credit(
            customer_id='CUST-001',
            amount=50.00,
            withdrawal_method='bank_transfer'
        )
        
        assert result['success'] == True
        assert result['amount'] == 50.00
        assert result['withdrawal_id'].startswith('WDRW-')
        assert result['new_balance'] == 50.00
    
    def test_withdraw_insufficient_balance(self, credit_service):
        """Test withdrawal with insufficient balance"""
        from services.billing_credit_service import CreditType
        
        credit_service.create_credit('CUST-001', 50.00, CreditType.OVERPAYMENT, 'Test')
        
        result = credit_service.withdraw_credit(
            customer_id='CUST-001',
            amount=100.00
        )
        
        assert result['success'] == False
        assert 'Insufficient' in result['error']
    
    # ========== WALLET TRANSFER TESTS ==========
    
    def test_transfer_to_wallet(self, credit_service, health_wallets):
        """Test transferring credit to health wallet"""
        from services.billing_credit_service import CreditType
        
        initial_wallet_balance = health_wallets['CUST-001']['balance']
        
        credit_service.create_credit('CUST-001', 100.00, CreditType.OVERPAYMENT, 'Test')
        
        result = credit_service.transfer_to_wallet(
            customer_id='CUST-001',
            amount=75.00,
            wallet_type='health_wallet'
        )
        
        assert result['success'] == True
        assert result['amount'] == 75.00
        assert result['transfer_id'].startswith('TRFR-')
        assert result['new_credit_balance'] == 25.00
        assert result['new_wallet_balance'] == initial_wallet_balance + 75.00
    
    def test_transfer_creates_wallet_if_not_exists(self, credit_service, health_wallets):
        """Test transfer creates wallet for new customer"""
        from services.billing_credit_service import CreditType
        
        # CUST-002 has no wallet
        assert 'CUST-002' not in health_wallets
        
        credit_service.create_credit('CUST-002', 50.00, CreditType.REFUND, 'Test')
        
        result = credit_service.transfer_to_wallet(
            customer_id='CUST-002',
            amount=50.00,
            wallet_type='health_wallet'
        )
        
        assert result['success'] == True
        assert 'CUST-002' in health_wallets
        assert health_wallets['CUST-002']['balance'] == 50.00
    
    # ========== APPLY TO BILL TESTS ==========
    
    def test_apply_to_bill(self, credit_service, billing_data):
        """Test applying credit to a bill"""
        from services.billing_credit_service import CreditType
        
        credit_service.create_credit('CUST-001', 100.00, CreditType.OVERPAYMENT, 'Test')
        
        result = credit_service.apply_to_bill(
            customer_id='CUST-001',
            bill_id='BILL-001',
            amount=100.00
        )
        
        assert result['success'] == True
        assert result['amount_applied'] == 100.00
        assert result['bill_status'] == 'partial'
        assert result['bill_remaining'] == 50.00  # 150 - 100
    
    def test_apply_full_credit_pays_bill(self, credit_service, billing_data):
        """Test applying enough credit pays bill in full"""
        from services.billing_credit_service import CreditType
        
        credit_service.create_credit('CUST-001', 200.00, CreditType.OVERPAYMENT, 'Test')
        
        result = credit_service.apply_to_bill(
            customer_id='CUST-001',
            bill_id='BILL-001'  # amount_due = 150
        )
        
        assert result['success'] == True
        assert result['amount_applied'] == 150.00  # Capped at bill amount
        assert result['bill_status'] == 'paid'
        assert result['bill_remaining'] == 0.00
        assert result['new_credit_balance'] == 50.00  # 200 - 150
    
    # ========== BILLING VALIDATION TESTS ==========
    
    def test_validate_detects_overpayment(self, credit_service):
        """Test billing validation detects overpayment"""
        result = credit_service.validate_customer_billing(
            customer_id='CUST-001',
            auto_create_credits=True
        )
        
        # BILL-002 has overpayment of 50 (paid 200 for 150 due)
        assert float(result.overbilled_amount) == 50.00
        assert len(result.credits_detected) >= 1
        assert result.warnings  # Should have warning about overpayment
    
    def test_validate_no_auto_create(self, credit_service):
        """Test validation without auto-creating credits"""
        result = credit_service.validate_customer_billing(
            customer_id='CUST-001',
            auto_create_credits=False
        )
        
        # Check balance - no credits should be created
        balance = credit_service.get_customer_credit_balance('CUST-001')
        assert balance['active_credits_count'] == 0
    
    # ========== NOTIFICATION TESTS ==========
    
    def test_check_outstanding_bills_notification(self, credit_service):
        """Test outstanding bills notification check"""
        results = credit_service.check_and_notify_outstanding_bills('CUST-001')
        
        # CUST-001 has BILL-001 which is outstanding
        assert len(results) >= 1
        # Should have at least one notification result
        assert any(r.notification_type.value in ['outstanding_bill', 'bill_overdue'] for r in results)
    
    def test_check_overdue_bills_notification(self, credit_service):
        """Test overdue bills notification check"""
        results = credit_service.check_and_notify_outstanding_bills('CUST-002')
        
        # CUST-002 has BILL-003 which is overdue
        assert len(results) >= 1
        # Should have overdue notification
        overdue_results = [r for r in results if r.notification_type.value == 'bill_overdue']
        assert len(overdue_results) >= 1
    
    # ========== LEDGER REPORT TESTS ==========
    
    def test_get_billing_ledger_report(self, credit_service):
        """Test billing ledger report generation"""
        from services.billing_credit_service import CreditType
        
        # Create some credits
        credit_service.create_credit('CUST-001', 100.00, CreditType.OVERPAYMENT, 'Test')
        
        report = credit_service.get_billing_ledger_report(
            customer_id='CUST-001',
            include_credits=True,
            include_transactions=True,
            refresh=True
        )
        
        assert 'generated_at' in report
        assert report['customer_id'] == 'CUST-001'
        assert 'summary' in report
        assert 'bills' in report
        assert 'credits' in report
        assert 'integrity' in report
        
        # Check summary calculations
        summary = report['summary']
        assert summary['total_billed'] > 0
        # 100.00 manual credit + 50.00 auto-detected overpayment on BILL-002 (refresh=True)
        assert summary['total_credits'] == 150.00
    
    def test_ledger_report_includes_credits(self, credit_service):
        """Test ledger report includes credit details"""
        from services.billing_credit_service import CreditType
        
        credit_service.create_credit('CUST-001', 75.00, CreditType.REFUND, 'Test refund')
        
        report = credit_service.get_billing_ledger_report(
            customer_id='CUST-001',
            include_credits=True
        )
        
        assert len(report['credits']) >= 1
        assert any(c.get('remaining_amount', 0) == 75.0 for c in report['credits'])
    
    # ========== EXPORT/IMPORT TESTS ==========
    
    def test_export_credits(self, credit_service):
        """Test exporting credits data"""
        from services.billing_credit_service import CreditType
        
        credit_service.create_credit('CUST-001', 100.00, CreditType.OVERPAYMENT, 'Test')
        
        export_data = credit_service.export_credits()
        
        assert 'credits' in export_data
        assert 'customer_credits' in export_data
        assert 'transactions' in export_data
        assert len(export_data['credits']) >= 1
    
    def test_import_credits(self, credit_service):
        """Test importing credits data"""
        from services.billing_credit_service import CreditType
        
        # Create and export
        credit = credit_service.create_credit('CUST-001', 100.00, CreditType.OVERPAYMENT, 'Test')
        export_data = credit_service.export_credits()
        
        # Reset and import
        from services.billing_credit_service import BillingCreditService
        new_service = BillingCreditService()
        new_service.import_credits(export_data)
        
        # Verify imported data
        balance = new_service.get_customer_credit_balance('CUST-001')
        assert balance['total_credit_balance'] == 100.00


class TestBillingCreditIntegration:
    """Integration tests for billing credits with other services"""
    
    def test_credit_workflow_end_to_end(self):
        """Test complete credit workflow from detection to use"""
        from services.billing_credit_service import (
            BillingCreditService,
            CreditType,
            reset_billing_credit_service
        )
        
        reset_billing_credit_service()
        
        # Setup data
        billing = {
            'BILL-001': {
                'bill_id': 'BILL-001',
                'customer_id': 'CUST-001',
                'policy_id': 'POL-001',
                'amount': 100.00,
                'amount_due': 100.00,
                'amount_paid': 150.00,  # Overpaid by 50
                'status': 'paid',
                'due_date': datetime.now(timezone.utc).isoformat()
            },
            'BILL-002': {
                'bill_id': 'BILL-002',
                'customer_id': 'CUST-001',
                'policy_id': 'POL-001',
                'amount': 100.00,
                'amount_due': 100.00,
                'amount_paid': 0.0,
                'status': 'outstanding',
                'due_date': (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
            }
        }
        
        wallets = {
            'CUST-001': {
                'customer_id': 'CUST-001',
                'balance': 500.00,
                'transactions': []
            }
        }
        
        service = BillingCreditService(
            billing_data=billing,
            health_wallets=wallets
        )
        
        # Step 1: Validate and detect overpayment
        validation = service.validate_customer_billing('CUST-001', auto_create_credits=True)
        assert float(validation.overbilled_amount) == 50.00
        
        # Step 2: Check credit balance
        balance = service.get_customer_credit_balance('CUST-001')
        assert balance['total_credit_balance'] == 50.00
        
        # Step 3: Apply credit to outstanding bill
        result = service.apply_to_bill('CUST-001', 'BILL-002', amount=50.00)
        assert result['success'] == True
        assert result['bill_remaining'] == 50.00  # 100 - 50
        
        # Step 4: Verify credit balance is now 0
        balance = service.get_customer_credit_balance('CUST-001')
        assert balance['total_credit_balance'] == 0.0
        
        # Step 5: Check ledger report
        report = service.get_billing_ledger_report('CUST-001')
        assert report['summary']['total_outstanding'] == 50.00  # Remaining on BILL-002


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
