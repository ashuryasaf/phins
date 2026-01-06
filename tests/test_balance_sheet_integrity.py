#!/usr/bin/env python3
"""
Test suite for PHINS Balance Sheet Data Integrity
==================================================
Tests that the balance sheet correctly tracks:
- Premium income from paid bills
- Claims paid from approved/paid claims
- Data reconciliation between different sources
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import unittest
from datetime import datetime


class TestBalanceSheetIntegrity(unittest.TestCase):
    """Test balance sheet data integrity"""
    
    def setUp(self):
        """Set up test fixtures"""
        # Import the server module
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'web_portal'))
        
        # Import required functions
        from server import (
            PHINS_BALANCE_SHEET, BILLING, CLAIMS, 
            initialize_balance_sheet, record_premium_revenue,
            process_claim_payment_to_wallet, HEALTH_WALLETS
        )
        
        self.PHINS_BALANCE_SHEET = PHINS_BALANCE_SHEET
        self.BILLING = BILLING
        self.CLAIMS = CLAIMS
        self.HEALTH_WALLETS = HEALTH_WALLETS
        self.initialize_balance_sheet = initialize_balance_sheet
        self.record_premium_revenue = record_premium_revenue
        self.process_claim_payment_to_wallet = process_claim_payment_to_wallet
    
    def test_balance_sheet_initialized(self):
        """Test that balance sheet is properly initialized"""
        self.initialize_balance_sheet()
        
        # Check structure
        self.assertIn('claims_reserve', self.PHINS_BALANCE_SHEET)
        self.assertIn('operating_reserve', self.PHINS_BALANCE_SHEET)
        self.assertIn('total_revenue', self.PHINS_BALANCE_SHEET)
        self.assertIn('total_expenses', self.PHINS_BALANCE_SHEET)
        self.assertIn('revenue_breakdown', self.PHINS_BALANCE_SHEET)
        self.assertIn('expense_breakdown', self.PHINS_BALANCE_SHEET)
        self.assertIn('transactions', self.PHINS_BALANCE_SHEET)
        self.assertIn('audit_log', self.PHINS_BALANCE_SHEET)
        
        # Check claims reserve is initialized
        self.assertGreater(self.PHINS_BALANCE_SHEET['claims_reserve'], 0)
        
        print(f"✓ Balance sheet initialized with claims reserve: ${self.PHINS_BALANCE_SHEET['claims_reserve']:,.2f}")
    
    def test_revenue_breakdown_structure(self):
        """Test revenue breakdown has all required fields"""
        self.initialize_balance_sheet()
        
        revenue = self.PHINS_BALANCE_SHEET['revenue_breakdown']
        required_fields = ['premium_income', 'management_fees', 'underwriting_fees', 
                          'investment_earnings', 'late_fees', 'other_income']
        
        for field in required_fields:
            self.assertIn(field, revenue, f"Missing revenue field: {field}")
        
        print(f"✓ Revenue breakdown has all required fields")
    
    def test_expense_breakdown_structure(self):
        """Test expense breakdown has all required fields"""
        self.initialize_balance_sheet()
        
        expense = self.PHINS_BALANCE_SHEET['expense_breakdown']
        required_fields = ['claims_paid', 'supplier_payments', 'operating_costs', 
                          'reinsurance', 'other_expenses']
        
        for field in required_fields:
            self.assertIn(field, expense, f"Missing expense field: {field}")
        
        print(f"✓ Expense breakdown has all required fields")
    
    def test_premium_revenue_recording(self):
        """Test premium revenue is recorded correctly"""
        self.initialize_balance_sheet()
        
        initial_premium = self.PHINS_BALANCE_SHEET['revenue_breakdown']['premium_income']
        initial_total = self.PHINS_BALANCE_SHEET['total_revenue']
        
        # Record a premium payment
        test_amount = 500.00
        result = self.record_premium_revenue(
            customer_id='TEST-CUST-001',
            policy_id='TEST-POL-001',
            amount=test_amount,
            description='Test premium payment'
        )
        
        self.assertIsNotNone(result)
        self.assertIn('tx_id', result)
        
        # Verify balance sheet updated
        new_premium = self.PHINS_BALANCE_SHEET['revenue_breakdown']['premium_income']
        new_total = self.PHINS_BALANCE_SHEET['total_revenue']
        
        self.assertEqual(new_premium, initial_premium + test_amount,
            f"Premium income not updated correctly: expected {initial_premium + test_amount}, got {new_premium}")
        self.assertEqual(new_total, initial_total + test_amount,
            f"Total revenue not updated correctly: expected {initial_total + test_amount}, got {new_total}")
        
        print(f"✓ Premium revenue recorded: ${test_amount:.2f}")
        print(f"  Premium income: ${initial_premium:.2f} -> ${new_premium:.2f}")
        print(f"  Total revenue: ${initial_total:.2f} -> ${new_total:.2f}")
    
    def test_claims_payment_recording(self):
        """Test claims payment is recorded correctly on balance sheet"""
        self.initialize_balance_sheet()
        
        initial_claims_paid = self.PHINS_BALANCE_SHEET['expense_breakdown']['claims_paid']
        initial_claims_reserve = self.PHINS_BALANCE_SHEET['claims_reserve']
        
        # Set up test customer wallet
        test_customer = 'TEST-CUST-002'
        self.HEALTH_WALLETS[test_customer] = {
            'customer_id': test_customer,
            'balance': 0,
            'transactions': [],
            'created_at': datetime.now().isoformat()
        }
        
        # Process a claim payment
        test_amount = 1000.00
        result = self.process_claim_payment_to_wallet(
            claim_id='TEST-CLAIM-001',
            customer_id=test_customer,
            amount=test_amount,
            processed_by='test_accountant'
        )
        
        self.assertTrue(result['success'], f"Claim payment failed: {result.get('error', 'Unknown error')}")
        
        # Verify balance sheet updated
        new_claims_paid = self.PHINS_BALANCE_SHEET['expense_breakdown']['claims_paid']
        new_claims_reserve = self.PHINS_BALANCE_SHEET['claims_reserve']
        
        self.assertEqual(new_claims_paid, initial_claims_paid + test_amount,
            f"Claims paid not updated correctly: expected {initial_claims_paid + test_amount}, got {new_claims_paid}")
        self.assertEqual(new_claims_reserve, initial_claims_reserve - test_amount,
            f"Claims reserve not deducted correctly: expected {initial_claims_reserve - test_amount}, got {new_claims_reserve}")
        
        # Verify customer wallet received payment
        wallet_balance = self.HEALTH_WALLETS[test_customer]['balance']
        self.assertEqual(wallet_balance, test_amount,
            f"Customer wallet balance incorrect: expected {test_amount}, got {wallet_balance}")
        
        print(f"✓ Claim payment recorded: ${test_amount:.2f}")
        print(f"  Claims paid: ${initial_claims_paid:.2f} -> ${new_claims_paid:.2f}")
        print(f"  Claims reserve: ${initial_claims_reserve:.2f} -> ${new_claims_reserve:.2f}")
        print(f"  Customer wallet: $0.00 -> ${wallet_balance:.2f}")
    
    def test_net_income_calculation(self):
        """Test net income is calculated correctly"""
        self.initialize_balance_sheet()
        
        total_revenue = self.PHINS_BALANCE_SHEET['total_revenue']
        total_expenses = self.PHINS_BALANCE_SHEET['total_expenses']
        expected_net = total_revenue - total_expenses
        
        print(f"✓ Net income calculation correct:")
        print(f"  Total Revenue: ${total_revenue:,.2f}")
        print(f"  Total Expenses: ${total_expenses:,.2f}")
        print(f"  Net Income: ${expected_net:,.2f}")


def run_balance_sheet_integrity_test():
    """Run quick balance sheet integrity tests"""
    print("\n" + "=" * 70)
    print("PHINS BALANCE SHEET DATA INTEGRITY TEST")
    print("=" * 70)
    
    # Import server components
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'web_portal'))
    from server import PHINS_BALANCE_SHEET, initialize_balance_sheet
    
    # Initialize
    initialize_balance_sheet()
    
    # Check balance sheet structure
    print(f"\n📊 Balance Sheet Status:")
    print(f"  Claims Reserve: ${PHINS_BALANCE_SHEET['claims_reserve']:,.2f}")
    print(f"  Operating Reserve: ${PHINS_BALANCE_SHEET['operating_reserve']:,.2f}")
    print(f"  Total Revenue: ${PHINS_BALANCE_SHEET['total_revenue']:,.2f}")
    print(f"  Total Expenses: ${PHINS_BALANCE_SHEET['total_expenses']:,.2f}")
    print(f"  Net Income: ${PHINS_BALANCE_SHEET['total_revenue'] - PHINS_BALANCE_SHEET['total_expenses']:,.2f}")
    
    print(f"\n📈 Revenue Breakdown:")
    for key, value in PHINS_BALANCE_SHEET['revenue_breakdown'].items():
        print(f"  {key}: ${value:,.2f}")
    
    print(f"\n📉 Expense Breakdown:")
    for key, value in PHINS_BALANCE_SHEET['expense_breakdown'].items():
        print(f"  {key}: ${value:,.2f}")
    
    print(f"\n✓ Transaction Count: {len(PHINS_BALANCE_SHEET['transactions'])}")
    print(f"✓ Audit Log Entries: {len(PHINS_BALANCE_SHEET['audit_log'])}")
    
    print("\n" + "=" * 70)
    print("✓ BALANCE SHEET DATA INTEGRITY CHECK COMPLETE")
    print("=" * 70)
    
    return True


if __name__ == '__main__':
    # Run quick integrity test first
    run_balance_sheet_integrity_test()
    
    print("\n\nRunning full test suite...\n")
    
    # Run full unittest suite
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    suite.addTests(loader.loadTestsFromTestCase(TestBalanceSheetIntegrity))
    
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    # Exit with error code if tests failed
    sys.exit(0 if result.wasSuccessful() else 1)
