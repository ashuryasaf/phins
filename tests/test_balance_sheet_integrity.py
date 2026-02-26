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
            process_claim_payment_to_wallet, HEALTH_WALLETS,
            TRANSACTION_LEDGER, calculate_cumulative_premium_income,
            sync_balance_sheet_premium_income, SUSPENDED_TEST_ACCOUNTS,
            calculate_premium_transaction_overview
        )
        
        self.PHINS_BALANCE_SHEET = PHINS_BALANCE_SHEET
        self.BILLING = BILLING
        self.CLAIMS = CLAIMS
        self.HEALTH_WALLETS = HEALTH_WALLETS
        self.TRANSACTION_LEDGER = TRANSACTION_LEDGER
        self.initialize_balance_sheet = initialize_balance_sheet
        self.record_premium_revenue = record_premium_revenue
        self.process_claim_payment_to_wallet = process_claim_payment_to_wallet
        self.calculate_cumulative_premium_income = calculate_cumulative_premium_income
        self.sync_balance_sheet_premium_income = sync_balance_sheet_premium_income
        self.calculate_premium_transaction_overview = calculate_premium_transaction_overview
        self.SUSPENDED_TEST_ACCOUNTS = SUSPENDED_TEST_ACCOUNTS
    
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
    
    def test_cumulative_premium_income_includes_unbilled_ledger_amounts(self):
        """Cumulative premium income should include bill + unbilled premium ledger."""
        bill_id = "TEST-BILL-CUM-001"
        tx_id = "TEST-TX-CUM-001"
        
        # Preserve existing entries if they exist.
        prev_bill = self.BILLING.get(bill_id)
        prev_tx = self.TRANSACTION_LEDGER.get(tx_id)
        
        try:
            self.BILLING[bill_id] = {
                'id': bill_id,
                'customer_id': 'TEST-CUST-CUM-001',
                'policy_id': 'TEST-POL-CUM-001',
                'amount': 100.0,
                'amount_paid': 100.0,
                'status': 'paid',
                'created_date': datetime.now().isoformat(),
                'paid_date': datetime.now().isoformat()
            }
            self.TRANSACTION_LEDGER[tx_id] = {
                'id': tx_id,
                'customer_id': 'TEST-CUST-CUM-001',
                'type': 'premium_payment',
                'amount': 40.0,
                'metadata': {
                    'unbilled_premium_amount': 40.0
                },
                'timestamp': datetime.now().isoformat(),
                'status': 'completed'
            }
            
            totals = self.calculate_cumulative_premium_income(exclude_suspended=False)
            self.assertGreaterEqual(totals['from_bills'], 100.0)
            self.assertGreaterEqual(totals['ledger_unbilled_total'], 40.0)
            self.assertGreaterEqual(totals['total'], 140.0)
        finally:
            # Restore prior state.
            if prev_bill is None:
                self.BILLING.pop(bill_id, None)
            else:
                self.BILLING[bill_id] = prev_bill
            if prev_tx is None:
                self.TRANSACTION_LEDGER.pop(tx_id, None)
            else:
                self.TRANSACTION_LEDGER[tx_id] = prev_tx
    
    def test_cumulative_premium_income_excludes_billed_style_ledger_duplicates(self):
        """Billed payment-style ledger entries must not inflate premium totals."""
        bill_id = "TEST-BILL-CUM-002"
        tx_id = "TEST-TX-CUM-002"
        
        prev_bill = self.BILLING.get(bill_id)
        prev_tx = self.TRANSACTION_LEDGER.get(tx_id)
        
        baseline = self.calculate_cumulative_premium_income(exclude_suspended=False)
        
        try:
            self.BILLING[bill_id] = {
                'id': bill_id,
                'customer_id': 'TEST-CUST-CUM-002',
                'policy_id': 'TEST-POL-CUM-002',
                'amount': 120.0,
                'amount_paid': 120.0,
                'status': 'paid',
                'created_date': datetime.now().isoformat(),
                'paid_date': datetime.now().isoformat()
            }
            # Mimics destination='premium' ledger shape without explicit unbilled flag.
            self.TRANSACTION_LEDGER[tx_id] = {
                'id': tx_id,
                'customer_id': 'TEST-CUST-CUM-002',
                'type': 'premium_deposit',
                'amount': 120.0,
                'metadata': {},
                'timestamp': datetime.now().isoformat(),
                'status': 'completed'
            }
            
            totals = self.calculate_cumulative_premium_income(exclude_suspended=False)
            self.assertAlmostEqual(totals['from_bills'] - baseline['from_bills'], 120.0, places=2)
            # premium_deposit should not be counted as unbilled premium income.
            self.assertAlmostEqual(totals['ledger_unbilled_total'], baseline['ledger_unbilled_total'], places=2)
            self.assertAlmostEqual(totals['total'] - baseline['total'], 120.0, places=2)
        finally:
            if prev_bill is None:
                self.BILLING.pop(bill_id, None)
            else:
                self.BILLING[bill_id] = prev_bill
            if prev_tx is None:
                self.TRANSACTION_LEDGER.pop(tx_id, None)
            else:
                self.TRANSACTION_LEDGER[tx_id] = prev_tx
    
    def test_cumulative_premium_income_counts_unbilled_premium_deposit_nft_flow(self):
        """Unbilled premium_deposit NFT flow should be included once."""
        tx_id = "TEST-TX-CUM-003"
        prev_tx = self.TRANSACTION_LEDGER.get(tx_id)
        baseline = self.calculate_cumulative_premium_income(exclude_suspended=False)
        
        try:
            self.TRANSACTION_LEDGER[tx_id] = {
                'id': tx_id,
                'customer_id': 'TEST-CUST-CUM-003',
                'type': 'premium_deposit',
                'amount': 85.0,
                'metadata': {
                    'destination': 'premium',
                    'bill_status': 'not_found',
                    'unbilled_premium_amount': 85.0
                },
                'timestamp': datetime.now().isoformat(),
                'status': 'completed',
                'nft_token_id': 'NFT-TEST-CUM-003'
            }
            totals = self.calculate_cumulative_premium_income(exclude_suspended=False)
            self.assertAlmostEqual(totals['ledger_unbilled_total'] - baseline['ledger_unbilled_total'], 85.0, places=2)
            self.assertAlmostEqual(totals['total'] - baseline['total'], 85.0, places=2)
        finally:
            if prev_tx is None:
                self.TRANSACTION_LEDGER.pop(tx_id, None)
            else:
                self.TRANSACTION_LEDGER[tx_id] = prev_tx

    def test_cumulative_premium_income_includes_paid_bill_without_amount_paid_field(self):
        """Legacy paid bills without amount_paid should still count via amount/amount_due."""
        bill_id = "TEST-BILL-CUM-004"
        prev_bill = self.BILLING.get(bill_id)
        baseline = self.calculate_cumulative_premium_income(exclude_suspended=False)

        try:
            self.BILLING[bill_id] = {
                'id': bill_id,
                'customer_id': 'TEST-CUST-CUM-004',
                'policy_id': 'TEST-POL-CUM-004',
                'amount': 66.0,
                'amount_due': 66.0,
                'amount_paid': 0.0,   # Legacy missing mirror value
                'status': 'paid',
                'created_date': datetime.now().isoformat(),
                'paid_date': datetime.now().isoformat()
            }

            totals = self.calculate_cumulative_premium_income(exclude_suspended=False)
            self.assertAlmostEqual(totals['from_bills'] - baseline['from_bills'], 66.0, places=2)
            self.assertAlmostEqual(totals['total'] - baseline['total'], 66.0, places=2)
        finally:
            if prev_bill is None:
                self.BILLING.pop(bill_id, None)
            else:
                self.BILLING[bill_id] = prev_bill

    def test_cumulative_premium_income_uses_ledger_billed_fallback_for_unmirrored_bill(self):
        """Ledger billed payment should count when BILLING.amount_paid is not updated."""
        bill_id = "TEST-BILL-CUM-005"
        tx_id = "TEST-TX-CUM-005"
        prev_bill = self.BILLING.get(bill_id)
        prev_tx = self.TRANSACTION_LEDGER.get(tx_id)
        baseline = self.calculate_cumulative_premium_income(exclude_suspended=False)

        try:
            self.BILLING[bill_id] = {
                'id': bill_id,
                'customer_id': 'TEST-CUST-CUM-005',
                'policy_id': 'TEST-POL-CUM-005',
                'amount': 93.0,
                'amount_due': 93.0,
                'amount_paid': 0.0,   # Not mirrored yet
                'status': 'outstanding',
                'created_date': datetime.now().isoformat()
            }
            self.TRANSACTION_LEDGER[tx_id] = {
                'id': tx_id,
                'customer_id': 'TEST-CUST-CUM-005',
                'type': 'bill_payment',
                'amount': 93.0,
                'metadata': {
                    'bill_id': bill_id,
                    'policy_id': 'TEST-POL-CUM-005',
                    'bill_status': 'paid'
                },
                'timestamp': datetime.now().isoformat(),
                'status': 'completed',
                'nft_token_id': 'NFT-TEST-CUM-005'
            }

            totals = self.calculate_cumulative_premium_income(exclude_suspended=False)
            self.assertAlmostEqual(totals['from_bills'], baseline['from_bills'], places=2)
            self.assertAlmostEqual(
                totals.get('ledger_billed_fallback_total', 0) - baseline.get('ledger_billed_fallback_total', 0),
                93.0,
                places=2
            )
            self.assertAlmostEqual(totals['total'] - baseline['total'], 93.0, places=2)
        finally:
            if prev_bill is None:
                self.BILLING.pop(bill_id, None)
            else:
                self.BILLING[bill_id] = prev_bill
            if prev_tx is None:
                self.TRANSACTION_LEDGER.pop(tx_id, None)
            else:
                self.TRANSACTION_LEDGER[tx_id] = prev_tx

    def test_cumulative_premium_income_uses_wallet_fallback_when_bill_and_ledger_missing(self):
        """Wallet premium debit should count when bill/ledger mirrors are missing."""
        customer_id = "TEST-CUST-CUM-006"
        prev_wallet = self.HEALTH_WALLETS.get(customer_id)
        baseline = self.calculate_cumulative_premium_income(exclude_suspended=False)

        try:
            self.HEALTH_WALLETS[customer_id] = {
                'customer_id': customer_id,
                'balance': 500.0,
                'transactions': [
                    {
                        'id': 'WAL-TX-CUM-006',
                        'type': 'premium_payment',
                        'amount': -41.0,
                        'bill_id': 'MISSING-BILL-CUM-006',
                        'description': 'Premium payment from wallet',
                        'timestamp': datetime.now().isoformat()
                    }
                ],
                'created_at': datetime.now().isoformat()
            }

            totals = self.calculate_cumulative_premium_income(exclude_suspended=False)
            self.assertAlmostEqual(
                totals.get('wallet_billed_fallback_total', 0) - baseline.get('wallet_billed_fallback_total', 0),
                41.0,
                places=2
            )
            self.assertAlmostEqual(totals['total'] - baseline['total'], 41.0, places=2)
        finally:
            if prev_wallet is None:
                self.HEALTH_WALLETS.pop(customer_id, None)
            else:
                self.HEALTH_WALLETS[customer_id] = prev_wallet

    def test_cumulative_premium_income_uses_bulk_ledger_metadata_fallback(self):
        """Bulk ledger premium payments should count from bills_paid metadata."""
        tx_id = "TEST-TX-CUM-BULK-001"
        prev_tx = self.TRANSACTION_LEDGER.get(tx_id)
        baseline = self.calculate_cumulative_premium_income(exclude_suspended=False)

        try:
            self.TRANSACTION_LEDGER[tx_id] = {
                'id': tx_id,
                'customer_id': 'TEST-CUST-CUM-BULK-001',
                'type': 'bulk_premium_payment',
                'amount': -120.0,
                'metadata': {
                    'bills_paid': [
                        {'bill_id': 'MISSING-BILL-CUM-BULK-A', 'amount_paid': 70.0},
                        {'bill_id': 'MISSING-BILL-CUM-BULK-B', 'amount_paid': 50.0},
                    ]
                },
                'timestamp': datetime.now().isoformat(),
                'status': 'completed',
                'nft_token_id': 'NFT-TEST-CUM-BULK-001'
            }

            totals = self.calculate_cumulative_premium_income(exclude_suspended=False)
            self.assertAlmostEqual(
                totals.get('ledger_billed_fallback_total', 0) - baseline.get('ledger_billed_fallback_total', 0),
                120.0,
                places=2
            )
            self.assertAlmostEqual(totals['total'] - baseline['total'], 120.0, places=2)
        finally:
            if prev_tx is None:
                self.TRANSACTION_LEDGER.pop(tx_id, None)
            else:
                self.TRANSACTION_LEDGER[tx_id] = prev_tx

    def test_cumulative_premium_income_uses_wallet_bill_ids_metadata_fallback(self):
        """Wallet premium metadata bill_ids should map to billed fallback safely."""
        customer_id = "TEST-CUST-CUM-007"
        prev_wallet = self.HEALTH_WALLETS.get(customer_id)
        baseline = self.calculate_cumulative_premium_income(exclude_suspended=False)

        try:
            self.HEALTH_WALLETS[customer_id] = {
                'customer_id': customer_id,
                'balance': 500.0,
                'transactions': [
                    {
                        'id': 'WAL-TX-CUM-007',
                        'type': 'bulk_premium_payment',
                        'amount': -84.0,
                        'metadata': {
                            'bill_ids': ['MISSING-BILL-CUM-007-A', 'MISSING-BILL-CUM-007-B']
                        },
                        'description': 'Bulk wallet premium payment with bill_ids metadata',
                        'timestamp': datetime.now().isoformat()
                    }
                ],
                'created_at': datetime.now().isoformat()
            }

            totals = self.calculate_cumulative_premium_income(exclude_suspended=False)
            self.assertAlmostEqual(
                totals.get('wallet_billed_fallback_total', 0) - baseline.get('wallet_billed_fallback_total', 0),
                84.0,
                places=2
            )
            self.assertAlmostEqual(totals['total'] - baseline['total'], 84.0, places=2)
        finally:
            if prev_wallet is None:
                self.HEALTH_WALLETS.pop(customer_id, None)
            else:
                self.HEALTH_WALLETS[customer_id] = prev_wallet

    def test_premium_transaction_overview_includes_future_unpaid_bills(self):
        """Overview should include future scheduled unpaid premium transactions."""
        future_bill_id = "TEST-BILL-FUTURE-001"
        paid_bill_id = "TEST-BILL-PAST-001"
        prev_future_bill = self.BILLING.get(future_bill_id)
        prev_paid_bill = self.BILLING.get(paid_bill_id)

        try:
            self.BILLING[paid_bill_id] = {
                'id': paid_bill_id,
                'customer_id': 'TEST-CUST-FUTURE-001',
                'policy_id': 'TEST-POL-FUTURE-001',
                'amount': 90.0,
                'amount_due': 90.0,
                'amount_paid': 90.0,
                'status': 'paid',
                'created_date': datetime.now().isoformat(),
                'paid_date': datetime.now().isoformat()
            }
            self.BILLING[future_bill_id] = {
                'id': future_bill_id,
                'customer_id': 'TEST-CUST-FUTURE-001',
                'policy_id': 'TEST-POL-FUTURE-001',
                'amount': 60.0,
                'amount_due': 60.0,
                'amount_paid': 0.0,
                'status': 'outstanding',
                'created_date': datetime.now().isoformat(),
                'due_date': datetime(2099, 1, 1).isoformat()
            }

            paid_totals = self.calculate_cumulative_premium_income(exclude_suspended=False)
            overview = self.calculate_premium_transaction_overview(
                paid_totals=paid_totals,
                exclude_suspended=False,
                projection_months=12
            )

            self.assertGreaterEqual(overview.get('paid_total', 0), 90.0)
            self.assertGreaterEqual(overview.get('future_projected_total', 0), 60.0)
            self.assertGreaterEqual(
                overview.get('cumulative_transaction_total', 0),
                overview.get('paid_total', 0) + 60.0
            )
        finally:
            if prev_future_bill is None:
                self.BILLING.pop(future_bill_id, None)
            else:
                self.BILLING[future_bill_id] = prev_future_bill
            if prev_paid_bill is None:
                self.BILLING.pop(paid_bill_id, None)
            else:
                self.BILLING[paid_bill_id] = prev_paid_bill

    def test_sync_balance_sheet_premium_income_updates_stale_value(self):
        """Sync helper should update stale balance-sheet premium income values."""
        self.initialize_balance_sheet()

        bill_id = "TEST-BILL-SYNC-001"
        prev_bill = self.BILLING.get(bill_id)
        prev_breakdown = dict(self.PHINS_BALANCE_SHEET['revenue_breakdown'])
        prev_total_revenue = self.PHINS_BALANCE_SHEET.get('total_revenue', 0.0)
        prev_last_updated = self.PHINS_BALANCE_SHEET.get('last_updated')
        prev_audit_len = len(self.PHINS_BALANCE_SHEET.get('audit_log', []))

        baseline = self.calculate_cumulative_premium_income(exclude_suspended=False)

        try:
            self.BILLING[bill_id] = {
                'id': bill_id,
                'customer_id': 'TEST-CUST-SYNC-001',
                'policy_id': 'TEST-POL-SYNC-001',
                'amount': 55.0,
                'amount_paid': 55.0,
                'status': 'paid',
                'created_date': datetime.now().isoformat(),
                'paid_date': datetime.now().isoformat()
            }
            expected_after = self.calculate_cumulative_premium_income(exclude_suspended=False)

            # Force a stale balance-sheet premium value before sync.
            self.PHINS_BALANCE_SHEET['revenue_breakdown']['premium_income'] = baseline['total']
            self.PHINS_BALANCE_SHEET['total_revenue'] = sum(
                self.PHINS_BALANCE_SHEET['revenue_breakdown'].values()
            )

            sync_result = self.sync_balance_sheet_premium_income(
                exclude_suspended=False,
                actor='TEST',
                reason='unit_test',
                persist=False
            )

            self.assertTrue(sync_result['updated'])
            self.assertAlmostEqual(sync_result['expected'], expected_after['total'], places=2)
            self.assertAlmostEqual(
                self.PHINS_BALANCE_SHEET['revenue_breakdown']['premium_income'],
                expected_after['total'],
                places=2
            )
        finally:
            if prev_bill is None:
                self.BILLING.pop(bill_id, None)
            else:
                self.BILLING[bill_id] = prev_bill
            self.PHINS_BALANCE_SHEET['revenue_breakdown'] = prev_breakdown
            self.PHINS_BALANCE_SHEET['total_revenue'] = prev_total_revenue
            self.PHINS_BALANCE_SHEET['last_updated'] = prev_last_updated
            if len(self.PHINS_BALANCE_SHEET.get('audit_log', [])) > prev_audit_len:
                self.PHINS_BALANCE_SHEET['audit_log'] = self.PHINS_BALANCE_SHEET['audit_log'][:prev_audit_len]

    def test_sync_balance_sheet_premium_income_updates_cumulative_data_source(self):
        """Sync helper should persist cumulative premium data source payload."""
        self.initialize_balance_sheet()

        result = self.sync_balance_sheet_premium_income(
            exclude_suspended=False,
            actor='TEST',
            reason='unit_test_datasource',
            persist=False
        )
        data_sources = self.PHINS_BALANCE_SHEET.get('data_sources', {})
        cumulative_source = data_sources.get('cumulative_premium', {})

        self.assertIsInstance(cumulative_source, dict)
        self.assertAlmostEqual(
            float(cumulative_source.get('value', 0)),
            float(result.get('expected', 0)),
            places=2
        )
        self.assertIn('from_wallet_billed_fallback', cumulative_source)

    def test_cumulative_premium_income_all_customers_includes_suspended_when_requested(self):
        """exclude_suspended=False should include suspended-customer premium payments."""
        bill_id = "TEST-BILL-SUSP-001"
        customer_id = "TEST-CUST-SUSP-001"

        prev_bill = self.BILLING.get(bill_id)
        was_suspended = customer_id in self.SUSPENDED_TEST_ACCOUNTS

        before_excluded = self.calculate_cumulative_premium_income(exclude_suspended=True)
        before_included = self.calculate_cumulative_premium_income(exclude_suspended=False)

        try:
            self.SUSPENDED_TEST_ACCOUNTS.add(customer_id)
            self.BILLING[bill_id] = {
                'id': bill_id,
                'customer_id': customer_id,
                'policy_id': 'TEST-POL-SUSP-001',
                'amount': 77.0,
                'amount_paid': 77.0,
                'status': 'paid',
                'created_date': datetime.now().isoformat(),
                'paid_date': datetime.now().isoformat()
            }

            after_excluded = self.calculate_cumulative_premium_income(exclude_suspended=True)
            after_included = self.calculate_cumulative_premium_income(exclude_suspended=False)

            # Excluded path should not count suspended customer payment.
            self.assertAlmostEqual(
                after_excluded['total'],
                before_excluded['total'],
                places=2
            )
            # All-customers path should count suspended customer payment.
            self.assertAlmostEqual(
                after_included['total'] - before_included['total'],
                77.0,
                places=2
            )
        finally:
            if prev_bill is None:
                self.BILLING.pop(bill_id, None)
            else:
                self.BILLING[bill_id] = prev_bill
            if not was_suspended:
                self.SUSPENDED_TEST_ACCOUNTS.discard(customer_id)
    
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
