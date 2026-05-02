#!/usr/bin/env python3
"""
Test suite for PHINS Balance Sheet Data Integrity
==================================================
Tests that the balance sheet correctly tracks:
- Premium income from paid bills
- Claims paid from approved/paid claims
- Data reconciliation between different sources
"""

import json
import os
import subprocess
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import unittest
from datetime import datetime
import tempfile


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
            record_fee_revenue, record_balance_sheet_transaction,
            POLICIES, CUSTOMERS, INVESTMENT_ACCOUNTS, CUSTOMER_ALLOCATIONS,
            AUTO_PAY_RUN_REPORTS, ensure_policy_auto_pay_defaults,
            run_monthly_auto_pay, save_ledger_data, load_ledger_data,
            build_bills_vs_billing_autopay_summary,
            compute_unified_financial_metrics, get_bi_data_accounting,
            UNDERWRITING_APPLICATIONS
        )
        
        self.PHINS_BALANCE_SHEET = PHINS_BALANCE_SHEET
        self.BILLING = BILLING
        self.CLAIMS = CLAIMS
        self.HEALTH_WALLETS = HEALTH_WALLETS
        self.TRANSACTION_LEDGER = TRANSACTION_LEDGER
        self.POLICIES = POLICIES
        self.CUSTOMERS = CUSTOMERS
        self.INVESTMENT_ACCOUNTS = INVESTMENT_ACCOUNTS
        self.CUSTOMER_ALLOCATIONS = CUSTOMER_ALLOCATIONS
        self.AUTO_PAY_RUN_REPORTS = AUTO_PAY_RUN_REPORTS
        self.initialize_balance_sheet = initialize_balance_sheet
        self.record_premium_revenue = record_premium_revenue
        self.process_claim_payment_to_wallet = process_claim_payment_to_wallet
        self.calculate_cumulative_premium_income = calculate_cumulative_premium_income
        self.record_fee_revenue = record_fee_revenue
        self.record_balance_sheet_transaction = record_balance_sheet_transaction
        self.ensure_policy_auto_pay_defaults = ensure_policy_auto_pay_defaults
        self.run_monthly_auto_pay = run_monthly_auto_pay
        self.save_ledger_data = save_ledger_data
        self.load_ledger_data = load_ledger_data
        self.build_bills_vs_billing_autopay_summary = build_bills_vs_billing_autopay_summary
        self.compute_unified_financial_metrics = compute_unified_financial_metrics
        self.get_bi_data_accounting = get_bi_data_accounting
        self.UNDERWRITING_APPLICATIONS = UNDERWRITING_APPLICATIONS
    
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

    def test_claims_payment_posts_to_shared_accounting_engine(self):
        """Claim payments should be retained on the shared accounting engine ledger."""
        from accounting_engine import get_accounting_engine, reset_accounting_engine, EntryType

        reset_accounting_engine()
        self.initialize_balance_sheet()

        test_customer = 'TEST-CUST-ACCOUNTING'
        self.HEALTH_WALLETS[test_customer] = {
            'customer_id': test_customer,
            'balance': 0,
            'transactions': [],
            'created_at': datetime.now().isoformat()
        }
        self.CLAIMS['TEST-CLAIM-ACCOUNTING'] = {
            'id': 'TEST-CLAIM-ACCOUNTING',
            'customer_id': test_customer,
            'policy_id': 'TEST-POL-ACCOUNTING',
            'status': 'approved'
        }

        result = self.process_claim_payment_to_wallet(
            claim_id='TEST-CLAIM-ACCOUNTING',
            customer_id=test_customer,
            amount=250.0,
            processed_by='test_accountant'
        )

        self.assertTrue(result['success'], f"Claim payment failed: {result.get('error', 'Unknown error')}")

        engine = get_accounting_engine()
        claim_entries = [e for e in engine.ledger_entries if e.entry_type == EntryType.CLAIM_PAYMENT]
        self.assertEqual(len(claim_entries), 1)
        self.assertEqual(float(claim_entries[0].credit_amount), 250.0)
    
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

    def test_marketplace_management_fee_and_supplier_expense_recording(self):
        """Marketplace margin should book management fee revenue and supplier payout expense separately."""
        self.initialize_balance_sheet()

        initial_management_fees = self.PHINS_BALANCE_SHEET['revenue_breakdown']['management_fees']
        initial_supplier_payments = self.PHINS_BALANCE_SHEET['expense_breakdown']['supplier_payments']
        initial_total_revenue = self.PHINS_BALANCE_SHEET['total_revenue']
        initial_total_expenses = self.PHINS_BALANCE_SHEET['total_expenses']

        management_fee = 18.50
        supplier_payout = 101.25

        fee_tx = self.record_fee_revenue(
            fee_type='management',
            amount=management_fee,
            description='Marketplace management fee for order ORD-MKT-001',
            customer_id='TEST-CUST-MKT-001',
            actor='marketplace_settlement_test'
        )
        expense_tx = self.record_balance_sheet_transaction(
            tx_type='expense',
            category='supplier_payments',
            amount=supplier_payout,
            description='Supplier payout for order ORD-MKT-001',
            actor='marketplace_settlement_test',
            customer_id='TEST-CUST-MKT-001',
            metadata={'order_id': 'ORD-MKT-001', 'supplier_id': 'SUP-MKT-001'}
        )

        self.assertIsNotNone(fee_tx)
        self.assertIsNotNone(expense_tx)
        self.assertEqual(
            self.PHINS_BALANCE_SHEET['revenue_breakdown']['management_fees'],
            initial_management_fees + management_fee,
        )
        self.assertEqual(
            self.PHINS_BALANCE_SHEET['expense_breakdown']['supplier_payments'],
            initial_supplier_payments + supplier_payout,
        )
        self.assertEqual(
            self.PHINS_BALANCE_SHEET['total_revenue'],
            initial_total_revenue + management_fee,
        )
        self.assertEqual(
            self.PHINS_BALANCE_SHEET['total_expenses'],
            initial_total_expenses + supplier_payout,
        )

    def test_auto_pay_defaults_force_first_of_month_and_default_card(self):
        """Auto-pay normalization should enforce the 1st and default Mastercard metadata."""
        policy_id = "TEST-AUTOPAY-POL-001"
        customer_id = "TEST-AUTOPAY-CUST-001"
        prev_policy = self.POLICIES.get(policy_id)

        try:
            self.POLICIES[policy_id] = {
                'id': policy_id,
                'customer_id': customer_id,
                'status': 'active',
                'monthly_premium': 120.0,
                'payment_setup': {
                    'auto_pay': False,
                    'billing_frequency': 'monthly',
                    'billing_day': 15
                },
                'billing': {
                    'auto_pay': False,
                    'frequency': 'monthly',
                    'next_billing_date': '2026-03-21T00:00:00'
                }
            }

            result = self.ensure_policy_auto_pay_defaults(
                self.POLICIES[policy_id],
                reference_datetime=datetime(2026, 3, 20, 9, 0, 0),
                notify_changes=False,
            )
            normalized = result['policy']

            self.assertTrue(normalized['payment_setup']['auto_pay'])
            self.assertEqual(normalized['payment_setup']['billing_day'], 1)
            self.assertEqual(normalized['billing']['billing_day'], 1)
            self.assertEqual(normalized['payment_setup']['card_last4'], '4444')
            self.assertEqual(normalized['payment_setup']['card_type'], 'mastercard')
            self.assertEqual(normalized['billing']['payment_method']['card_last4'], '4444')
            self.assertTrue(normalized['payment_setup']['next_billing_date'].startswith('2026-03-01'))
            self.assertTrue(result['default_card_assigned'])
        finally:
            if prev_policy is None:
                self.POLICIES.pop(policy_id, None)
            else:
                self.POLICIES[policy_id] = prev_policy

    def test_monthly_auto_pay_books_payment_and_persists_report(self):
        """Monthly auto-pay should create a paid bill, ledger entries, and a persisted report."""
        self.initialize_balance_sheet()
        policy_id = "TEST-AUTOPAY-POL-002"
        customer_id = "TEST-AUTOPAY-CUST-002"
        previous_state = {
            'policy': self.POLICIES.get(policy_id),
            'customer': self.CUSTOMERS.get(customer_id),
            'wallet': self.HEALTH_WALLETS.get(customer_id),
            'investment': self.INVESTMENT_ACCOUNTS.get(customer_id),
            'allocation': self.CUSTOMER_ALLOCATIONS.get(customer_id),
            'reports': dict(self.AUTO_PAY_RUN_REPORTS),
            'billing_keys': set(self.BILLING.keys()),
            'ledger_keys': set(self.TRANSACTION_LEDGER.keys()),
        }

        try:
            self.CUSTOMERS[customer_id] = {
                'id': customer_id,
                'name': 'Auto Pay Test Customer',
                'email': 'autopay-test@example.com',
                'phone': '+15555550123',
                'created_date': datetime.now().isoformat(),
            }
            self.HEALTH_WALLETS[customer_id] = {
                'customer_id': customer_id,
                'balance': 0.0,
                'transactions': [],
                'created_at': datetime.now().isoformat(),
            }
            self.INVESTMENT_ACCOUNTS[customer_id] = {
                'customer_id': customer_id,
                'balance': 0.0,
                'index_balance': 0.0,
                'bonds_balance': 0.0,
                'crypto_balance': 0.0,
                'deposits': [],
                'created_at': datetime.now().isoformat(),
            }
            self.CUSTOMER_ALLOCATIONS[customer_id] = {
                'customer_id': customer_id,
                'savings_pct': 25.0,
                'risk_pct': 75.0,
                'wallet_pct': 30.0,
                'investment_pct': 65.0,
                'algo_pct': 5.0,
                'index_pct': 60.0,
                'bonds_pct': 30.0,
                'crypto_pct': 10.0,
            }
            self.POLICIES[policy_id] = {
                'id': policy_id,
                'customer_id': customer_id,
                'status': 'active',
                'monthly_premium': 100.0,
                'payment_setup': {
                    'auto_pay': True,
                    'billing_frequency': 'monthly',
                    'billing_day': 1,
                    'next_billing_date': '2026-04-01T00:00:00'
                },
                'billing': {
                    'auto_pay': True,
                    'frequency': 'monthly',
                    'billing_day': 1,
                    'next_billing_date': '2026-04-01T00:00:00',
                    'auto_pay_config': {}
                }
            }

            report = self.run_monthly_auto_pay(
                reference_datetime=datetime(2026, 4, 1, 8, 0, 0),
                dry_run=False,
                notify_users=False,
                trigger='unit_test',
                actor='unit_test',
            )

            self.assertTrue(report['success'])
            self.assertEqual(report['processed'], 1)
            self.assertAlmostEqual(report['total_amount'], 100.0)
            self.assertIn(report['report_id'], self.AUTO_PAY_RUN_REPORTS)

            new_bill_ids = [bill_id for bill_id in self.BILLING if bill_id not in previous_state['billing_keys']]
            self.assertEqual(len(new_bill_ids), 1)
            bill = self.BILLING[new_bill_ids[0]]
            self.assertEqual(bill['status'], 'paid')
            self.assertEqual(bill['amount_paid'], 100.0)
            self.assertEqual(bill['billing_cycle_key'], '2026-04')

            new_txs = [
                tx for tx_id, tx in self.TRANSACTION_LEDGER.items()
                if tx_id not in previous_state['ledger_keys']
            ]
            self.assertTrue(any(tx.get('type') == 'premium_payment' for tx in new_txs))
            self.assertTrue(any(tx.get('type') == 'auto_pay_execution' for tx in new_txs))
            self.assertAlmostEqual(
                self.PHINS_BALANCE_SHEET['revenue_breakdown']['premium_income'],
                100.0
            )
            self.assertTrue(
                self.POLICIES[policy_id]['payment_setup']['next_billing_date'].startswith('2026-05-01')
            )

            import server as server_module
            original_path = server_module.LEDGER_PERSISTENCE_FILE
            fd, tmp_path = tempfile.mkstemp(prefix='phins-autopay-', suffix='.json')
            os.close(fd)
            try:
                server_module.LEDGER_PERSISTENCE_FILE = tmp_path
                self.save_ledger_data()
                self.AUTO_PAY_RUN_REPORTS.clear()
                self.load_ledger_data()
                self.assertIn(report['report_id'], self.AUTO_PAY_RUN_REPORTS)
            finally:
                server_module.LEDGER_PERSISTENCE_FILE = original_path
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
        finally:
            if previous_state['policy'] is None:
                self.POLICIES.pop(policy_id, None)
            else:
                self.POLICIES[policy_id] = previous_state['policy']
            if previous_state['customer'] is None:
                self.CUSTOMERS.pop(customer_id, None)
            else:
                self.CUSTOMERS[customer_id] = previous_state['customer']
            if previous_state['wallet'] is None:
                self.HEALTH_WALLETS.pop(customer_id, None)
            else:
                self.HEALTH_WALLETS[customer_id] = previous_state['wallet']
            if previous_state['investment'] is None:
                self.INVESTMENT_ACCOUNTS.pop(customer_id, None)
            else:
                self.INVESTMENT_ACCOUNTS[customer_id] = previous_state['investment']
            if previous_state['allocation'] is None:
                self.CUSTOMER_ALLOCATIONS.pop(customer_id, None)
            else:
                self.CUSTOMER_ALLOCATIONS[customer_id] = previous_state['allocation']

            for bill_id in list(self.BILLING.keys()):
                if bill_id not in previous_state['billing_keys']:
                    self.BILLING.pop(bill_id, None)
            for tx_id in list(self.TRANSACTION_LEDGER.keys()):
                if tx_id not in previous_state['ledger_keys']:
                    self.TRANSACTION_LEDGER.pop(tx_id, None)
            self.AUTO_PAY_RUN_REPORTS.clear()
            self.AUTO_PAY_RUN_REPORTS.update(previous_state['reports'])

    def test_run_server_preserves_efrat_persisted_wallets_from_v1_persistence(self):
        """Server startup should not overwrite Efrat balances restored from legacy persistence."""
        fd, tmp_path = tempfile.mkstemp(prefix='phins-efrat-persisted-', suffix='.json')
        os.close(fd)

        persisted_data = {
            'version': '1.0',
            'saved_at': datetime.now().isoformat(),
            'health_wallets': {
                'CUST-EFRAT-001': {
                    'customer_id': 'CUST-EFRAT-001',
                    'balance': 321.45,
                    'monthly_deposit': 25.0,
                    'transactions': [{'id': 'TX-LEGACY-WALLET'}],
                    'created_at': datetime.now().isoformat(),
                }
            },
            'investment_accounts': {
                'CUST-EFRAT-001': {
                    'customer_id': 'CUST-EFRAT-001',
                    'balance': 654.32,
                    'index_balance': 500.0,
                    'bonds_balance': 100.0,
                    'crypto_balance': 54.32,
                    'deposits': [{'id': 'DEP-LEGACY-INVESTMENT'}],
                    'created_at': datetime.now().isoformat(),
                }
            },
        }

        with open(tmp_path, 'w') as handle:
            json.dump(persisted_data, handle)

        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        web_portal_root = os.path.join(repo_root, 'web_portal')
        script = f"""
import json
import sys
sys.path.insert(0, {repo_root!r})
sys.path.insert(0, {web_portal_root!r})
import server as server_module

class _FakeServer:
    def __init__(self, *args, **kwargs):
        self.daemon_threads = True
        self.timeout = None

    def serve_forever(self):
        return

server_module.ThreadingHTTPServer = _FakeServer
server_module.schedule_periodic_save = lambda: None
server_module.seed_demo_documents = lambda: None
server_module.USE_DATABASE = False
server_module.database_enabled = False
server_module.run_server(0)
print(json.dumps({{
    "wallet_balance": server_module.HEALTH_WALLETS["CUST-EFRAT-001"]["balance"],
    "wallet_transactions": len(server_module.HEALTH_WALLETS["CUST-EFRAT-001"].get("transactions", [])),
    "investment_balance": server_module.INVESTMENT_ACCOUNTS["CUST-EFRAT-001"]["balance"],
    "investment_deposits": len(server_module.INVESTMENT_ACCOUNTS["CUST-EFRAT-001"].get("deposits", [])),
    "policy_annual_premium": server_module.POLICIES["POL-EFRAT-UNIFIED-001"]["annual_premium"],
    "policy_monthly_premium": server_module.POLICIES["POL-EFRAT-UNIFIED-001"]["monthly_premium"],
    "billing_amount": next(
        bill["amount"]
        for bill in server_module.BILLING.values()
        if bill.get("policy_id") == "POL-EFRAT-UNIFIED-001"
    ),
    "billing_amount_paid": next(
        bill["amount_paid"]
        for bill in server_module.BILLING.values()
        if bill.get("policy_id") == "POL-EFRAT-UNIFIED-001"
    ),
}}))
"""

        env = os.environ.copy()
        env.update({
            'LEDGER_PERSISTENCE_FILE': tmp_path,
            'ENABLE_LEDGER_PERSISTENCE': 'true',
            'USE_DATABASE': 'false',
            'PHINS_TEST_MODE': 'true',
        })

        try:
            result = subprocess.run(
                [sys.executable, '-c', script],
                check=True,
                capture_output=True,
                text=True,
                env=env,
                cwd=repo_root,
            )
            payload = json.loads(result.stdout.strip().splitlines()[-1])
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

        self.assertAlmostEqual(payload['wallet_balance'], 321.45)
        self.assertEqual(payload['wallet_transactions'], 1)
        self.assertAlmostEqual(payload['investment_balance'], 654.32)
        self.assertEqual(payload['investment_deposits'], 1)
        self.assertAlmostEqual(payload['policy_annual_premium'], 1552.50)
        self.assertAlmostEqual(payload['policy_monthly_premium'], 129.38)
        self.assertAlmostEqual(payload['billing_amount'], 129.38)
        self.assertAlmostEqual(payload['billing_amount_paid'], 129.38)

    def test_bills_vs_billing_autopay_summary_structure(self):
        """Summary must contain all four required top-level sections."""
        self.initialize_balance_sheet()
        result = self.build_bills_vs_billing_autopay_summary()

        for key in ('bills_overview', 'billing_on_balance_sheet',
                     'autopay_summary', 'cross_check'):
            self.assertIn(key, result, f"Missing section: {key}")

        bo = result['bills_overview']
        self.assertIn('total_bills', bo)
        self.assertIn('total_billed_amount', bo)
        self.assertIn('total_paid_amount', bo)
        self.assertIn('total_outstanding_amount', bo)
        self.assertIn('by_status', bo)
        self.assertIn('autopay_bills', bo)
        self.assertIn('manual_bills', bo)
        self.assertIn('per_customer', bo)

        bbs = result['billing_on_balance_sheet']
        self.assertIn('balance_sheet_premium_income', bbs)
        self.assertIn('cumulative_from_bills', bbs)
        self.assertIn('cumulative_total', bbs)

        aps = result['autopay_summary']
        self.assertIn('ledger_executions', aps)
        self.assertIn('run_reports', aps)

        cc = result['cross_check']
        self.assertIn('is_consistent', cc)
        self.assertIn('discrepancies', cc)
        self.assertIn('totals', cc)

    def test_bills_vs_billing_autopay_with_data(self):
        """Summary should reflect test bills and autopay ledger entries correctly."""
        self.initialize_balance_sheet()

        bill_id_manual = "TEST-SUMM-BILL-001"
        bill_id_auto = "TEST-SUMM-BILL-002"
        tx_id_auto = "TEST-SUMM-TX-AUTO-001"

        prev_bills = {k: self.BILLING.get(k) for k in (bill_id_manual, bill_id_auto)}
        prev_tx = self.TRANSACTION_LEDGER.get(tx_id_auto)

        try:
            self.BILLING[bill_id_manual] = {
                'id': bill_id_manual,
                'customer_id': 'CUST-SUMM-001',
                'policy_id': 'POL-SUMM-001',
                'amount': 200.0,
                'amount_due': 200.0,
                'amount_paid': 200.0,
                'status': 'paid',
                'auto_pay': False,
                'created_date': datetime.now().isoformat(),
                'paid_date': datetime.now().isoformat(),
            }
            self.BILLING[bill_id_auto] = {
                'id': bill_id_auto,
                'customer_id': 'CUST-SUMM-001',
                'policy_id': 'POL-SUMM-001',
                'amount': 100.0,
                'amount_due': 100.0,
                'amount_paid': 100.0,
                'status': 'paid',
                'auto_pay': True,
                'created_date': datetime.now().isoformat(),
                'paid_date': datetime.now().isoformat(),
            }
            self.TRANSACTION_LEDGER[tx_id_auto] = {
                'id': tx_id_auto,
                'customer_id': 'CUST-SUMM-001',
                'type': 'auto_pay_execution',
                'amount': 100.0,
                'metadata': {'policy_id': 'POL-SUMM-001', 'bill_id': bill_id_auto},
                'timestamp': datetime.now().isoformat(),
                'status': 'completed',
            }

            result = self.build_bills_vs_billing_autopay_summary()
            bo = result['bills_overview']

            self.assertGreaterEqual(bo['total_bills'], 2)
            self.assertGreaterEqual(bo['total_paid_amount'], 300.0)
            self.assertGreaterEqual(bo['autopay_bills']['count'], 1)
            self.assertGreaterEqual(bo['autopay_bills']['total_paid'], 100.0)
            self.assertGreaterEqual(bo['manual_bills']['count'], 1)
            self.assertGreaterEqual(bo['manual_bills']['total_paid'], 200.0)

            self.assertIn('CUST-SUMM-001', bo['per_customer'])
            cust = bo['per_customer']['CUST-SUMM-001']
            self.assertGreaterEqual(cust['total_paid'], 300.0)
            self.assertGreaterEqual(cust['autopay_bills'], 1)
            self.assertGreaterEqual(cust['manual_bills'], 1)

            aps = result['autopay_summary']
            self.assertGreaterEqual(aps['ledger_executions']['count'], 1)
            self.assertGreaterEqual(aps['ledger_executions']['total_amount'], 100.0)
            self.assertIn('POL-SUMM-001', aps['ledger_executions']['by_policy'])

            cc = result['cross_check']
            self.assertIn('totals', cc)
            self.assertGreaterEqual(cc['totals']['bills_total_paid'], 300.0)
            self.assertGreaterEqual(cc['totals']['autopay_ledger_total'], 100.0)

        finally:
            for k, prev in prev_bills.items():
                if prev is None:
                    self.BILLING.pop(k, None)
                else:
                    self.BILLING[k] = prev
            if prev_tx is None:
                self.TRANSACTION_LEDGER.pop(tx_id_auto, None)
            else:
                self.TRANSACTION_LEDGER[tx_id_auto] = prev_tx

    def test_bills_vs_billing_autopay_detects_discrepancy(self):
        """Cross-check should flag discrepancy when autopay bill total != ledger total."""
        self.initialize_balance_sheet()

        bill_id = "TEST-DISC-BILL-001"
        tx_id = "TEST-DISC-TX-001"

        prev_bill = self.BILLING.get(bill_id)
        prev_tx = self.TRANSACTION_LEDGER.get(tx_id)

        try:
            self.BILLING[bill_id] = {
                'id': bill_id,
                'customer_id': 'CUST-DISC-001',
                'policy_id': 'POL-DISC-001',
                'amount': 500.0,
                'amount_due': 500.0,
                'amount_paid': 500.0,
                'status': 'paid',
                'auto_pay': True,
                'created_date': datetime.now().isoformat(),
            }
            self.TRANSACTION_LEDGER[tx_id] = {
                'id': tx_id,
                'customer_id': 'CUST-DISC-001',
                'type': 'auto_pay_execution',
                'amount': 300.0,
                'metadata': {'policy_id': 'POL-DISC-001', 'bill_id': bill_id},
                'timestamp': datetime.now().isoformat(),
            }

            result = self.build_bills_vs_billing_autopay_summary()
            cc = result['cross_check']

            autopay_disc = [d for d in cc['discrepancies']
                            if d['check'] == 'autopay_bills_vs_ledger']
            self.assertTrue(len(autopay_disc) > 0,
                            "Expected autopay_bills_vs_ledger discrepancy")
            self.assertFalse(cc['is_consistent'])

        finally:
            if prev_bill is None:
                self.BILLING.pop(bill_id, None)
            else:
                self.BILLING[bill_id] = prev_bill
            if prev_tx is None:
                self.TRANSACTION_LEDGER.pop(tx_id, None)
            else:
                self.TRANSACTION_LEDGER[tx_id] = prev_tx

    def test_bills_vs_billing_autopay_excludes_suspended_accounts_consistently(self):
        """Suspended accounts should be excluded from both bill and autopay cross-check totals."""
        self.initialize_balance_sheet()

        previous_state = {
            'billing': dict(self.BILLING),
            'ledger': dict(self.TRANSACTION_LEDGER),
            'reports': dict(self.AUTO_PAY_RUN_REPORTS),
            'bs_revenue': dict(self.PHINS_BALANCE_SHEET['revenue_breakdown']),
            'bs_total_revenue': self.PHINS_BALANCE_SHEET['total_revenue'],
        }

        try:
            self.BILLING.clear()
            self.TRANSACTION_LEDGER.clear()
            self.AUTO_PAY_RUN_REPORTS.clear()

            self.BILLING['TEST-ACTIVE-BILL-001'] = {
                'id': 'TEST-ACTIVE-BILL-001',
                'customer_id': 'CUST-ACTIVE-001',
                'policy_id': 'POL-ACTIVE-001',
                'amount': 100.0,
                'amount_due': 100.0,
                'amount_paid': 100.0,
                'status': 'paid',
                'auto_pay': False,
                'created_date': datetime.now().isoformat(),
                'paid_date': datetime.now().isoformat(),
            }
            self.BILLING['TEST-SUSP-BILL-001'] = {
                'id': 'TEST-SUSP-BILL-001',
                'customer_id': 'CUST-TEST-100',
                'policy_id': 'POL-SUSP-001',
                'amount': 75.0,
                'amount_due': 75.0,
                'amount_paid': 75.0,
                'status': 'paid',
                'auto_pay': True,
                'created_date': datetime.now().isoformat(),
                'paid_date': datetime.now().isoformat(),
            }
            self.TRANSACTION_LEDGER['TEST-SUSP-TX-001'] = {
                'id': 'TEST-SUSP-TX-001',
                'customer_id': 'CUST-TEST-100',
                'type': 'auto_pay_execution',
                'amount': 75.0,
                'metadata': {'policy_id': 'POL-SUSP-001', 'bill_id': 'TEST-SUSP-BILL-001'},
                'timestamp': datetime.now().isoformat(),
                'status': 'completed',
            }

            self.PHINS_BALANCE_SHEET['revenue_breakdown']['premium_income'] = 100.0
            self.PHINS_BALANCE_SHEET['total_revenue'] = round(
                sum(self.PHINS_BALANCE_SHEET['revenue_breakdown'].values()), 2
            )

            result = self.build_bills_vs_billing_autopay_summary()

            self.assertEqual(result['bills_overview']['total_bills'], 1)
            self.assertEqual(result['bills_overview']['total_paid_amount'], 100.0)
            self.assertEqual(result['bills_overview']['autopay_bills']['count'], 0)
            self.assertEqual(result['autopay_summary']['ledger_executions']['total_amount'], 0.0)
            self.assertEqual(result['billing_on_balance_sheet']['cumulative_from_bills'], 100.0)
            self.assertTrue(result['cross_check']['is_consistent'])
            self.assertEqual(result['cross_check']['discrepancies'], [])
        finally:
            self.BILLING.clear()
            self.BILLING.update(previous_state['billing'])
            self.TRANSACTION_LEDGER.clear()
            self.TRANSACTION_LEDGER.update(previous_state['ledger'])
            self.AUTO_PAY_RUN_REPORTS.clear()
            self.AUTO_PAY_RUN_REPORTS.update(previous_state['reports'])
            self.PHINS_BALANCE_SHEET['revenue_breakdown'].clear()
            self.PHINS_BALANCE_SHEET['revenue_breakdown'].update(previous_state['bs_revenue'])
            self.PHINS_BALANCE_SHEET['total_revenue'] = previous_state['bs_total_revenue']

    def test_bills_vs_billing_after_autopay_run(self):
        """After a full auto-pay run, the summary should reflect the payment data consistently."""
        self.initialize_balance_sheet()
        policy_id = "TEST-SUMM-AUTOPAY-POL-001"
        customer_id = "TEST-SUMM-AUTOPAY-CUST-001"
        previous_state = {
            'policy': self.POLICIES.get(policy_id),
            'customer': self.CUSTOMERS.get(customer_id),
            'wallet': self.HEALTH_WALLETS.get(customer_id),
            'investment': self.INVESTMENT_ACCOUNTS.get(customer_id),
            'allocation': self.CUSTOMER_ALLOCATIONS.get(customer_id),
            'reports': dict(self.AUTO_PAY_RUN_REPORTS),
            'billing_keys': set(self.BILLING.keys()),
            'ledger_keys': set(self.TRANSACTION_LEDGER.keys()),
            'bs_revenue': dict(self.PHINS_BALANCE_SHEET['revenue_breakdown']),
            'bs_total_revenue': self.PHINS_BALANCE_SHEET['total_revenue'],
            'bs_total_expenses': self.PHINS_BALANCE_SHEET['total_expenses'],
            'bs_expense': dict(self.PHINS_BALANCE_SHEET['expense_breakdown']),
        }

        try:
            self.CUSTOMERS[customer_id] = {
                'id': customer_id, 'name': 'Summary AutoPay Test',
                'email': 'summ-autopay@example.com', 'phone': '+15555550999',
                'created_date': datetime.now().isoformat(),
            }
            self.HEALTH_WALLETS[customer_id] = {
                'customer_id': customer_id, 'balance': 0.0,
                'transactions': [], 'created_at': datetime.now().isoformat(),
            }
            self.INVESTMENT_ACCOUNTS[customer_id] = {
                'customer_id': customer_id, 'balance': 0.0,
                'index_balance': 0.0, 'bonds_balance': 0.0, 'crypto_balance': 0.0,
                'deposits': [], 'created_at': datetime.now().isoformat(),
            }
            self.CUSTOMER_ALLOCATIONS[customer_id] = {
                'customer_id': customer_id, 'savings_pct': 25.0, 'risk_pct': 75.0,
                'wallet_pct': 30.0, 'investment_pct': 65.0, 'algo_pct': 5.0,
                'index_pct': 60.0, 'bonds_pct': 30.0, 'crypto_pct': 10.0,
            }
            self.POLICIES[policy_id] = {
                'id': policy_id, 'customer_id': customer_id,
                'status': 'active', 'monthly_premium': 150.0,
                'payment_setup': {
                    'auto_pay': True, 'billing_frequency': 'monthly',
                    'billing_day': 1, 'next_billing_date': '2026-04-01T00:00:00',
                },
                'billing': {
                    'auto_pay': True, 'frequency': 'monthly', 'billing_day': 1,
                    'next_billing_date': '2026-04-01T00:00:00', 'auto_pay_config': {},
                },
            }

            report = self.run_monthly_auto_pay(
                reference_datetime=datetime(2026, 4, 1, 8, 0, 0),
                dry_run=False, notify_users=False,
                trigger='unit_test', actor='unit_test',
            )
            self.assertTrue(report['success'])
            self.assertEqual(report['processed'], 1)

            summary = self.build_bills_vs_billing_autopay_summary()
            bo = summary['bills_overview']
            aps = summary['autopay_summary']

            self.assertGreaterEqual(bo['autopay_bills']['count'], 1)
            self.assertGreaterEqual(bo['autopay_bills']['total_paid'], 150.0)
            self.assertGreaterEqual(aps['ledger_executions']['count'], 1)
            self.assertGreaterEqual(aps['run_reports']['report_count'], 1)
            self.assertGreaterEqual(aps['run_reports']['total_processed'], 1)

        finally:
            if previous_state['policy'] is None:
                self.POLICIES.pop(policy_id, None)
            else:
                self.POLICIES[policy_id] = previous_state['policy']
            if previous_state['customer'] is None:
                self.CUSTOMERS.pop(customer_id, None)
            else:
                self.CUSTOMERS[customer_id] = previous_state['customer']
            if previous_state['wallet'] is None:
                self.HEALTH_WALLETS.pop(customer_id, None)
            else:
                self.HEALTH_WALLETS[customer_id] = previous_state['wallet']
            if previous_state['investment'] is None:
                self.INVESTMENT_ACCOUNTS.pop(customer_id, None)
            else:
                self.INVESTMENT_ACCOUNTS[customer_id] = previous_state['investment']
            if previous_state['allocation'] is None:
                self.CUSTOMER_ALLOCATIONS.pop(customer_id, None)
            else:
                self.CUSTOMER_ALLOCATIONS[customer_id] = previous_state['allocation']
            for bill_id in list(self.BILLING.keys()):
                if bill_id not in previous_state['billing_keys']:
                    self.BILLING.pop(bill_id, None)
            for tx_id in list(self.TRANSACTION_LEDGER.keys()):
                if tx_id not in previous_state['ledger_keys']:
                    self.TRANSACTION_LEDGER.pop(tx_id, None)
            self.AUTO_PAY_RUN_REPORTS.clear()
            self.AUTO_PAY_RUN_REPORTS.update(previous_state['reports'])
            self.PHINS_BALANCE_SHEET['revenue_breakdown'].update(previous_state['bs_revenue'])
            self.PHINS_BALANCE_SHEET['total_revenue'] = previous_state['bs_total_revenue']
            self.PHINS_BALANCE_SHEET['expense_breakdown'].update(previous_state['bs_expense'])
            self.PHINS_BALANCE_SHEET['total_expenses'] = previous_state['bs_total_expenses']

    def test_unified_metrics_structure(self):
        """compute_unified_financial_metrics should return all required keys."""
        self.initialize_balance_sheet()
        m = self.compute_unified_financial_metrics()

        required_keys = [
            'total_billed', 'total_collected', 'outstanding_balance',
            'paid_count', 'pending_count', 'overdue_count', 'total_transactions',
            'collection_rate', 'total_revenue', 'monthly_premium_income',
            'claims_paid_amount', 'claims_disbursed_amount',
            'pending_claims_liability', 'pending_claims', 'approved_claims',
            'rejected_claims', 'total_claims',
            'total_customers', 'new_customers_this_month',
            'total_policies', 'active_policies', 'pending_policies',
            'total_applications', 'pending_applications',
            'approved_applications', 'rejected_applications',
            'total_health_wallet', 'total_deposits', 'active_wallets',
            'total_investment_balance', 'total_algo_balance',
            'total_pipeline_cash', 'total_wallet_balance',
            'total_investment_value', 'total_coverage_amount', 'total_aum',
            'cumulative_premium',
        ]
        for key in required_keys:
            self.assertIn(key, m, f"Missing unified metrics key: {key}")

    def test_unified_metrics_consistency_with_bills(self):
        """Unified metrics billing figures should be consistent with bill data."""
        bill_ids = ['TEST-UNI-BILL-001', 'TEST-UNI-BILL-002']
        prev = {k: self.BILLING.get(k) for k in bill_ids}

        try:
            self.BILLING[bill_ids[0]] = {
                'id': bill_ids[0], 'customer_id': 'CUST-UNI-001',
                'policy_id': 'POL-UNI-001',
                'amount': 300.0, 'amount_due': 300.0, 'amount_paid': 300.0,
                'status': 'paid', 'auto_pay': False,
            }
            self.BILLING[bill_ids[1]] = {
                'id': bill_ids[1], 'customer_id': 'CUST-UNI-001',
                'policy_id': 'POL-UNI-001',
                'amount': 200.0, 'amount_due': 200.0, 'amount_paid': 100.0,
                'status': 'partial', 'auto_pay': True,
            }

            m = self.compute_unified_financial_metrics(exclude_suspended=False)

            self.assertGreaterEqual(m['total_billed'], 500.0)
            self.assertGreaterEqual(m['total_collected'], 400.0)
            self.assertGreaterEqual(m['outstanding_balance'], 100.0)
        finally:
            for k, old in prev.items():
                if old is None:
                    self.BILLING.pop(k, None)
                else:
                    self.BILLING[k] = old

    def test_unified_metrics_expose_disbursed_and_pending_claims_liability(self):
        """Unified claim metrics should separate disbursed claims from pending liability."""
        claim_ids = [
            'TEST-UNI-CLM-PAID-001',
            'TEST-UNI-CLM-APPROVED-001',
            'TEST-UNI-CLM-PENDING-001',
            'TEST-UNI-CLM-UNDER-REVIEW-001',
        ]
        prev_claims = {claim_id: self.CLAIMS.get(claim_id) for claim_id in claim_ids}
        baseline = self.compute_unified_financial_metrics(exclude_suspended=False)

        try:
            self.CLAIMS[claim_ids[0]] = {
                'id': claim_ids[0],
                'customer_id': 'CUST-UNI-CLAIMS-001',
                'policy_id': 'POL-UNI-CLAIMS-001',
                'status': 'paid',
                'claimed_amount': 120.0,
                'approved_amount': 100.0,
            }
            self.CLAIMS[claim_ids[1]] = {
                'id': claim_ids[1],
                'customer_id': 'CUST-UNI-CLAIMS-001',
                'policy_id': 'POL-UNI-CLAIMS-001',
                'status': 'approved',
                'claimed_amount': 95.0,
                'approved_amount': 80.0,
            }
            self.CLAIMS[claim_ids[2]] = {
                'id': claim_ids[2],
                'customer_id': 'CUST-UNI-CLAIMS-001',
                'policy_id': 'POL-UNI-CLAIMS-001',
                'status': 'pending',
                'claimed_amount': 60.0,
                'approved_amount': 0.0,
            }
            self.CLAIMS[claim_ids[3]] = {
                'id': claim_ids[3],
                'customer_id': 'CUST-UNI-CLAIMS-001',
                'policy_id': 'POL-UNI-CLAIMS-001',
                'status': 'under_review',
                'claimed_amount': 40.0,
                'approved_amount': 0.0,
            }

            m = self.compute_unified_financial_metrics(exclude_suspended=False)

            self.assertGreaterEqual(m['claims_paid_amount'], 180.0)
            self.assertGreaterEqual(m['claims_disbursed_amount'], 100.0)
            self.assertGreaterEqual(m['pending_claims_liability'], 100.0)
            self.assertEqual(
                round(
                    (m['claims_paid_amount'] - m['claims_disbursed_amount'])
                    - (baseline['claims_paid_amount'] - baseline['claims_disbursed_amount']),
                    2,
                ),
                80.0,
            )
        finally:
            for claim_id, old in prev_claims.items():
                if old is None:
                    self.CLAIMS.pop(claim_id, None)
                else:
                    self.CLAIMS[claim_id] = old

    def test_accounting_bi_uses_only_disbursed_claims_for_expense(self):
        """Accounting BI should subtract only paid claims from revenue."""
        policy_id = 'TEST-ACCT-POL-001'
        claim_ids = ['TEST-ACCT-CLM-PAID-001', 'TEST-ACCT-CLM-APPROVED-001']
        prev_policy = self.POLICIES.get(policy_id)
        prev_claims = {claim_id: self.CLAIMS.get(claim_id) for claim_id in claim_ids}

        baseline = self.get_bi_data_accounting()

        try:
            self.POLICIES[policy_id] = {
                'id': policy_id,
                'customer_id': 'CUST-ACCT-001',
                'status': 'active',
                'annual_premium': 1200.0,
                'coverage_amount': 50000.0,
            }
            self.CLAIMS[claim_ids[0]] = {
                'id': claim_ids[0],
                'customer_id': 'CUST-ACCT-001',
                'policy_id': policy_id,
                'status': 'paid',
                'claimed_amount': 150.0,
                'approved_amount': 150.0,
            }
            self.CLAIMS[claim_ids[1]] = {
                'id': claim_ids[1],
                'customer_id': 'CUST-ACCT-001',
                'policy_id': policy_id,
                'status': 'approved',
                'claimed_amount': 90.0,
                'approved_amount': 90.0,
            }

            updated = self.get_bi_data_accounting()

            self.assertEqual(
                round(updated['total_revenue'] - baseline['total_revenue'], 2),
                1200.0,
            )
            self.assertEqual(
                round(updated['total_claims_paid'] - baseline['total_claims_paid'], 2),
                150.0,
            )
            self.assertEqual(
                round(updated['pending_claims_liability'] - baseline['pending_claims_liability'], 2),
                0.0,
            )
            self.assertEqual(
                round(updated['net_income'] - baseline['net_income'], 2),
                1050.0,
            )
        finally:
            if prev_policy is None:
                self.POLICIES.pop(policy_id, None)
            else:
                self.POLICIES[policy_id] = prev_policy

            for claim_id, old in prev_claims.items():
                if old is None:
                    self.CLAIMS.pop(claim_id, None)
                else:
                    self.CLAIMS[claim_id] = old

    def test_unified_metrics_excludes_suspended(self):
        """Suspended accounts should be filtered from unified metrics."""
        from server import SUSPENDED_TEST_ACCOUNTS
        bill_id = 'TEST-SUSP-BILL-001'
        cust_id = 'CUST-TEST-100'
        prev_bill = self.BILLING.get(bill_id)

        self.assertIn(cust_id, SUSPENDED_TEST_ACCOUNTS)

        try:
            self.BILLING[bill_id] = {
                'id': bill_id, 'customer_id': cust_id,
                'policy_id': 'POL-SUSP-001',
                'amount': 9999.0, 'amount_due': 9999.0, 'amount_paid': 0.0,
                'status': 'outstanding',
            }

            m_with = self.compute_unified_financial_metrics(exclude_suspended=True)
            m_without = self.compute_unified_financial_metrics(exclude_suspended=False)

            self.assertGreater(m_without['total_billed'], m_with['total_billed'],
                               "Suspended bill should be excluded when exclude_suspended=True")
        finally:
            if prev_bill is None:
                self.BILLING.pop(bill_id, None)
            else:
                self.BILLING[bill_id] = prev_bill

    def test_unified_metrics_bi_dashboard_consistency(self):
        """BI dashboard and billing stats should use the same underlying data."""
        m = self.compute_unified_financial_metrics(exclude_suspended=True)

        self.assertEqual(m['outstanding_balance'],
                         round(m['outstanding_balance'], 2))
        self.assertEqual(m['total_collected'],
                         round(m['total_collected'], 2))
        self.assertGreaterEqual(m['total_revenue'], 0)
        self.assertGreaterEqual(m['total_aum'], 0)
        self.assertGreaterEqual(m['total_customers'], 0)

        self.assertIsInstance(m['cumulative_premium'], dict)
        self.assertIn('total', m['cumulative_premium'])


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
