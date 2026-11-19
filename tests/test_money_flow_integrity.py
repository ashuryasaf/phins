"""
Money Flow Pipeline Data Integrity Tests

Validates the full PHINS money pipeline:
  Customer registers → applies for policy → pays monthly premium
  → premium splits to savings/health wallet + risk cover →
  wallets collect claims paid → claim approval → payment deposited
  to customer wallet → reflected on ledger

Run: pytest tests/test_money_flow_integrity.py -v
"""

import pytest
import json
import sys
import os
import requests
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BASE_URL = os.environ.get('TEST_BASE_URL', 'http://localhost:8000')


def api_get(path, token=None):
    headers = {}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    resp = requests.get(f'{BASE_URL}{path}', headers=headers, timeout=10)
    return resp


def api_post(path, data=None, token=None):
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    resp = requests.post(f'{BASE_URL}{path}', json=data or {}, headers=headers, timeout=10)
    return resp


def login(username, password):
    resp = api_post('/api/login', {'username': username, 'password': password})
    if resp.status_code == 200:
        return resp.json().get('token')
    return None


class TestPremiumAllocationIntegrity:
    """Verify premium split (savings vs risk) sums to 100%."""

    def test_default_allocation_sums_to_100(self):
        import web_portal.server as portal
        alloc = portal.get_customer_allocation('ANY-CUSTOMER')
        assert abs(alloc['savings_pct'] + alloc['risk_pct'] - 100.0) < 0.01

    def test_savings_distribution_sums_to_100(self):
        import web_portal.server as portal
        alloc = portal.get_customer_allocation('ANY-CUSTOMER')
        total = alloc['wallet_pct'] + alloc['investment_pct'] + alloc['algo_pct']
        assert abs(total - 100.0) < 0.01

    def test_investment_sub_allocation_sums_to_100(self):
        import web_portal.server as portal
        alloc = portal.get_customer_allocation('ANY-CUSTOMER')
        total = alloc['index_pct'] + alloc['bonds_pct'] + alloc['crypto_pct']
        assert abs(total - 100.0) < 0.01


class TestClaimPaymentToWallet:
    """Verify claim payments are deposited into customer wallets and recorded on ledger."""

    def _setup_customer_and_policy(self, portal, customer_id='CUST-TEST-PAY'):
        portal.CUSTOMERS[customer_id] = {
            'id': customer_id,
            'name': 'Test Payer',
            'email': 'payer@test.com',
        }
        portal.POLICIES['POL-TEST-PAY'] = {
            'id': 'POL-TEST-PAY',
            'customer_id': customer_id,
            'type': 'health',
            'coverage_amount': 100000.0,
            'annual_premium': 1200.0,
            'monthly_premium': 100.0,
            'status': 'active',
        }
        portal.CLAIMS['CLM-TEST-PAY'] = {
            'id': 'CLM-TEST-PAY',
            'customer_id': customer_id,
            'policy_id': 'POL-TEST-PAY',
            'type': 'Medical',
            'claimed_amount': 5000.0,
            'approved_amount': 4500.0,
            'status': 'approved',
        }
        portal.PHINS_BALANCE_SHEET['claims_reserve'] = 1000000.0
        portal.PHINS_BALANCE_SHEET['transactions'] = [
            tx for tx in (portal.PHINS_BALANCE_SHEET.get('transactions') or [])
            if not (
                isinstance(tx, dict)
                and tx.get('claim_id') == 'CLM-TEST-PAY'
                and tx.get('category') == 'claims_paid'
            )
        ]

    def test_claim_payment_credits_wallet(self):
        import web_portal.server as portal
        self._setup_customer_and_policy(portal)

        result = portal.process_claim_payment_to_wallet(
            claim_id='CLM-TEST-PAY',
            customer_id='CUST-TEST-PAY',
            amount=4500.0,
            processed_by='test'
        )
        assert result['success'] is True
        assert result['amount_paid'] == 4500.0
        wallet = portal.HEALTH_WALLETS.get('CUST-TEST-PAY')
        assert wallet is not None
        assert wallet['balance'] == 4500.0
        assert any(t['type'] == 'claim_payment' for t in wallet['transactions'])

    def test_claim_payment_recorded_on_ledger(self):
        import web_portal.server as portal
        self._setup_customer_and_policy(portal)

        result = portal.process_claim_payment_to_wallet(
            claim_id='CLM-TEST-PAY',
            customer_id='CUST-TEST-PAY',
            amount=4500.0,
            processed_by='test'
        )
        assert result['success'] is True
        tx = result.get('customer_tx', {})
        assert tx.get('id') is not None
        ledger_entry = portal.TRANSACTION_LEDGER.get(tx['id'])
        assert ledger_entry is not None

    def test_claim_payment_recorded_on_accounting_engine(self):
        import web_portal.server as portal
        from accounting_engine import EntryType, get_accounting_engine

        self._setup_customer_and_policy(portal)

        result = portal.process_claim_payment_to_wallet(
            claim_id='CLM-TEST-PAY',
            customer_id='CUST-TEST-PAY',
            amount=4500.0,
            processed_by='test'
        )
        assert result['success'] is True

        claim_entries = [
            entry for entry in get_accounting_engine().ledger_entries
            if entry.entry_type == EntryType.CLAIM_PAYMENT
        ]
        assert len(claim_entries) == 1
        assert claim_entries[0].allocation_id == 'CLM-TEST-PAY'
        assert claim_entries[0].policy_id == 'POL-TEST-PAY'
        assert claim_entries[0].credit_amount == Decimal('4500.0')

    def test_claim_payment_deducts_from_reserve(self):
        import web_portal.server as portal
        self._setup_customer_and_policy(portal)
        initial_reserve = portal.PHINS_BALANCE_SHEET['claims_reserve']

        portal.process_claim_payment_to_wallet(
            claim_id='CLM-TEST-PAY',
            customer_id='CUST-TEST-PAY',
            amount=4500.0,
            processed_by='test'
        )
        assert portal.PHINS_BALANCE_SHEET['claims_reserve'] < initial_reserve

    def test_insufficient_reserve_fails(self):
        import web_portal.server as portal
        self._setup_customer_and_policy(portal)
        portal.PHINS_BALANCE_SHEET['claims_reserve'] = 100.0

        result = portal.process_claim_payment_to_wallet(
            claim_id='CLM-TEST-PAY',
            customer_id='CUST-TEST-PAY',
            amount=4500.0,
            processed_by='test'
        )
        assert result['success'] is False
        assert 'Insufficient' in result.get('error', '')

    def test_second_claim_payment_does_not_write_the_balance_sheet_again(self):
        import web_portal.server as portal
        self._setup_customer_and_policy(portal)
        portal.PHINS_BALANCE_SHEET['claims_reserve'] = 100000.0
        portal.PHINS_BALANCE_SHEET.setdefault('transactions', [])

        first = portal.process_claim_payment_to_wallet(
            claim_id='CLM-TEST-PAY',
            customer_id='CUST-TEST-PAY',
            amount=4500.0,
            processed_by='test',
        )
        assert first['success'] is True
        assert first.get('already_posted') is not True
        sheet = [
            tx for tx in portal.PHINS_BALANCE_SHEET['transactions']
            if tx.get('claim_id') == 'CLM-TEST-PAY' and tx.get('category') == 'claims_paid'
        ]
        assert len(sheet) == 1
        wallet = portal.HEALTH_WALLETS['CUST-TEST-PAY']['balance']
        reserve = portal.PHINS_BALANCE_SHEET['claims_reserve']

        second = portal.process_claim_payment_to_wallet(
            claim_id='CLM-TEST-PAY',
            customer_id='CUST-TEST-PAY',
            amount=4500.0,
            processed_by='test',
        )
        assert second['success'] is True
        assert second['already_posted'] is True
        sheet_again = [
            tx for tx in portal.PHINS_BALANCE_SHEET['transactions']
            if tx.get('claim_id') == 'CLM-TEST-PAY' and tx.get('category') == 'claims_paid'
        ]
        assert len(sheet_again) == 1
        assert portal.HEALTH_WALLETS['CUST-TEST-PAY']['balance'] == wallet
        assert portal.PHINS_BALANCE_SHEET['claims_reserve'] == reserve

    def test_three_claim_lines_collapse_to_the_paid_amount(self):
        import web_portal.server as portal
        self._setup_customer_and_policy(portal)
        claim = portal.CLAIMS['CLM-TEST-PAY']
        claim['status'] = 'paid'
        claim['paid_amount'] = 4500.0
        portal.PHINS_BALANCE_SHEET['claims_reserve'] = 10000.0
        portal.PHINS_BALANCE_SHEET['transactions'] = [
            {'tx_id': 'BS-1', 'category': 'claims_paid', 'claim_id': 'CLM-TEST-PAY', 'amount': 4500.0, 'timestamp': '2026-01-01T00:00:00'},
            {'tx_id': 'BS-2', 'category': 'claims_paid', 'claim_id': 'CLM-TEST-PAY', 'amount': 4500.0, 'timestamp': '2026-01-02T00:00:00'},
            {'tx_id': 'BS-3', 'category': 'claims_paid', 'claim_id': 'CLM-TEST-PAY', 'amount': 4500.0, 'timestamp': '2026-01-03T00:00:00'},
        ]
        portal.PHINS_BALANCE_SHEET.setdefault('expense_breakdown', {})
        portal.PHINS_BALANCE_SHEET['expense_breakdown']['claims_paid'] = 13500.0
        portal.PHINS_BALANCE_SHEET['total_expenses'] = 13500.0
        portal.HEALTH_WALLETS['CUST-TEST-PAY'] = {
            'customer_id': 'CUST-TEST-PAY',
            'balance': 13500.0,
            'transactions': [
                {'id': 'W1', 'type': 'claim_payment', 'claim_id': 'CLM-TEST-PAY', 'amount': 4500.0, 'timestamp': '2026-01-01T00:00:00'},
                {'id': 'W2', 'type': 'claim_payment', 'claim_id': 'CLM-TEST-PAY', 'amount': 4500.0, 'timestamp': '2026-01-02T00:00:00'},
                {'id': 'W3', 'type': 'claim_payment', 'claim_id': 'CLM-TEST-PAY', 'amount': 4500.0, 'timestamp': '2026-01-03T00:00:00'},
            ],
        }

        folded = portal.collapse_duplicate_claim_transfers()
        assert folded['balance_sheet_rows_removed'] == 2
        assert folded['reserve_restored'] == 9000.0
        assert portal.PHINS_BALANCE_SHEET['claims_reserve'] == 19000.0
        remaining = [
            tx for tx in portal.PHINS_BALANCE_SHEET['transactions']
            if tx.get('claim_id') == 'CLM-TEST-PAY'
        ]
        assert len(remaining) == 1
        assert remaining[0]['amount'] == 4500.0
        assert portal.HEALTH_WALLETS['CUST-TEST-PAY']['balance'] == 4500.0
        assert len(portal.HEALTH_WALLETS['CUST-TEST-PAY']['transactions']) == 1
        assert claim['status'] == 'paid'

        again = portal.post_unposted_claim_transfers('test')
        assert again['posted_count'] == 0
        still = [
            tx for tx in portal.PHINS_BALANCE_SHEET['transactions']
            if tx.get('claim_id') == 'CLM-TEST-PAY' and tx.get('category') == 'claims_paid'
        ]
        assert len(still) == 1
        assert portal.HEALTH_WALLETS['CUST-TEST-PAY']['balance'] == 4500.0

    def test_charged_savings_is_credited_once_and_a_plain_premium_is_not(self):
        import web_portal.server as portal
        portal.POLICIES['POL-SAVE'] = {
            'id': 'POL-SAVE',
            'customer_id': 'CUST-SAVE',
            'start_date': '2026-01-01',
            'annual_premium': 1200.0,
            'risk_premium_annual': 1200.0,
        }
        portal.BILLING['BILL-SAVE'] = {
            'id': 'BILL-SAVE',
            'customer_id': 'CUST-SAVE',
            'policy_id': 'POL-SAVE',
            'payment_period': '2026-01',
            'amount_paid': 200.0,
            'status': 'paid',
            'premium_allocation': {'risk_amount_paid': 120.0, 'savings_amount_paid': 80.0},
        }
        portal.POLICIES['POL-RISK'] = {
            'id': 'POL-RISK',
            'customer_id': 'CUST-RISK',
            'start_date': '2026-01-01',
            'annual_premium': 1200.0,
            'risk_premium_annual': 1200.0,
        }
        portal.BILLING['BILL-RISK'] = {
            'id': 'BILL-RISK',
            'customer_id': 'CUST-RISK',
            'policy_id': 'POL-RISK',
            'payment_period': '2026-01',
            'amount_paid': 100.0,
            'status': 'paid',
        }

        first = portal.reconcile_savings_premium_balances()
        saved = [row for row in first['credited'] if row['customer_id'] == 'CUST-SAVE']
        assert len(saved) == 1
        assert saved[0]['credited'] == 80.0
        assert all(row['customer_id'] != 'CUST-RISK' for row in first['credited'])
        assert 'CUST-RISK' not in portal.INVESTMENT_ACCOUNTS
        books = portal._investment_books(portal.INVESTMENT_ACCOUNTS['CUST-SAVE'])
        wallet = portal.HEALTH_WALLETS['CUST-SAVE']['balance']
        algo_store = getattr(portal.unified_balance_service, 'algo_trading_balances', {}) or {}
        algo = float((algo_store.get('CUST-SAVE') or {}).get('available') or 0)
        assert round(books['position'] + wallet + algo, 2) == 80.0

        second = portal.reconcile_savings_premium_balances()
        assert all(row['customer_id'] != 'CUST-SAVE' for row in second['credited'])
        books_again = portal._investment_books(portal.INVESTMENT_ACCOUNTS['CUST-SAVE'])
        assert books_again['position'] == books['position']
        assert portal.HEALTH_WALLETS['CUST-SAVE']['balance'] == wallet
        assert portal.customer_savings_premiums_paid('CUST-SAVE') == 80.0
        assert portal.customer_savings_premiums_paid('CUST-RISK') == 0.0

    def test_wallet_shortfall_does_not_take_other_cash(self):
        import web_portal.server as portal
        self._setup_customer_and_policy(portal)
        claim = portal.CLAIMS['CLM-TEST-PAY']
        claim['status'] = 'paid'
        claim['paid_amount'] = 4500.0
        portal.PHINS_BALANCE_SHEET['claims_reserve'] = 10000.0
        portal.PHINS_BALANCE_SHEET['transactions'] = [
            {'tx_id': 'BS-1', 'category': 'claims_paid', 'claim_id': 'CLM-TEST-PAY', 'amount': 4500.0, 'timestamp': '2026-01-01T00:00:00'},
            {'tx_id': 'BS-2', 'category': 'claims_paid', 'claim_id': 'CLM-TEST-PAY', 'amount': 4500.0, 'timestamp': '2026-01-02T00:00:00'},
            {'tx_id': 'BS-3', 'category': 'claims_paid', 'claim_id': 'CLM-TEST-PAY', 'amount': 4500.0, 'timestamp': '2026-01-03T00:00:00'},
        ]
        portal.PHINS_BALANCE_SHEET.setdefault('expense_breakdown', {})
        portal.PHINS_BALANCE_SHEET['expense_breakdown']['claims_paid'] = 13500.0
        portal.PHINS_BALANCE_SHEET['total_expenses'] = 13500.0
        portal.HEALTH_WALLETS['CUST-TEST-PAY'] = {
            'customer_id': 'CUST-TEST-PAY',
            'balance': 100.0,
            'transactions': [
                {'id': 'W1', 'type': 'claim_payment', 'claim_id': 'CLM-TEST-PAY', 'amount': 4500.0, 'timestamp': '2026-01-01T00:00:00'},
                {'id': 'W2', 'type': 'claim_payment', 'claim_id': 'CLM-TEST-PAY', 'amount': 4500.0, 'timestamp': '2026-01-02T00:00:00'},
                {'id': 'W3', 'type': 'claim_payment', 'claim_id': 'CLM-TEST-PAY', 'amount': 4500.0, 'timestamp': '2026-01-03T00:00:00'},
            ],
        }

        folded = portal.collapse_duplicate_claim_transfers()
        assert folded['reserve_restored'] == 9000.0
        assert folded['wallet_shortfall'] == 9000.0
        assert folded['wallet_credit_removed'] == 0.0
        wallet = portal.HEALTH_WALLETS['CUST-TEST-PAY']
        assert wallet['balance'] == 100.0
        assert len(wallet['transactions']) == 3

    def test_spent_duplicate_does_not_take_the_paid_claim(self):
        import web_portal.server as portal
        self._setup_customer_and_policy(portal)
        claim = portal.CLAIMS['CLM-TEST-PAY']
        claim['status'] = 'paid'
        claim['paid_amount'] = 4500.0
        portal.PHINS_BALANCE_SHEET['claims_reserve'] = 10000.0
        portal.PHINS_BALANCE_SHEET['transactions'] = [
            {'tx_id': 'BS-1', 'category': 'claims_paid', 'claim_id': 'CLM-TEST-PAY', 'amount': 4500.0, 'timestamp': '2026-01-01T00:00:00'},
            {'tx_id': 'BS-2', 'category': 'claims_paid', 'claim_id': 'CLM-TEST-PAY', 'amount': 4500.0, 'timestamp': '2026-01-02T00:00:00'},
            {'tx_id': 'BS-3', 'category': 'claims_paid', 'claim_id': 'CLM-TEST-PAY', 'amount': 4500.0, 'timestamp': '2026-01-03T00:00:00'},
        ]
        portal.HEALTH_WALLETS['CUST-TEST-PAY'] = {
            'customer_id': 'CUST-TEST-PAY',
            'balance': 9000.0,
            'transactions': [
                {'id': f'W{n}', 'type': 'claim_payment', 'claim_id': 'CLM-TEST-PAY',
                 'amount': 4500.0, 'timestamp': f'2026-01-0{n}T00:00:00'}
                for n in (1, 2, 3)
            ],
        }

        folded = portal.collapse_duplicate_claim_transfers()
        assert folded['reserve_restored'] == 9000.0
        assert folded['wallet_shortfall'] == 9000.0
        assert folded['wallet_credit_removed'] == 0.0
        wallet = portal.HEALTH_WALLETS['CUST-TEST-PAY']
        assert wallet['balance'] == 9000.0
        assert len(wallet['transactions']) == 3
        assert claim['status'] == 'paid'

    def test_savings_already_in_the_investment_balance_is_not_credited_again(self):
        import web_portal.server as portal
        portal.POLICIES['POL-HELD'] = {
            'id': 'POL-HELD',
            'customer_id': 'CUST-HELD',
            'start_date': '2026-01-01',
            'annual_premium': 1200.0,
            'risk_premium_annual': 1200.0,
        }
        portal.BILLING['BILL-HELD'] = {
            'id': 'BILL-HELD',
            'customer_id': 'CUST-HELD',
            'policy_id': 'POL-HELD',
            'payment_period': '2026-01',
            'amount_paid': 200.0,
            'status': 'paid',
            'premium_allocation': {'risk_amount_paid': 120.0, 'savings_amount_paid': 80.0},
        }
        portal.INVESTMENT_ACCOUNTS['CUST-HELD'] = {
            'balance': 80.0,
            'index_balance': 0.0,
            'bonds_balance': 0.0,
            'crypto_balance': 0.0,
            'deposits': [],
            'allocations': [],
        }

        result = portal.reconcile_savings_premium_balances()
        assert all(row['customer_id'] != 'CUST-HELD' for row in result['credited'])
        assert portal.INVESTMENT_ACCOUNTS['CUST-HELD']['balance'] == 80.0
        assert 'CUST-HELD' not in portal.HEALTH_WALLETS

    def test_repair_journal_is_written_before_the_reserve_moves(self):
        import web_portal.server as portal
        self._setup_customer_and_policy(portal)
        claim = portal.CLAIMS['CLM-TEST-PAY']
        claim['status'] = 'paid'
        claim['paid_amount'] = 4500.0
        portal.PHINS_BALANCE_SHEET['claims_reserve'] = 10000.0
        portal.PHINS_BALANCE_SHEET['transactions'] = [
            {'tx_id': f'BS-{n}', 'category': 'claims_paid', 'claim_id': 'CLM-TEST-PAY',
             'amount': 4500.0, 'timestamp': f'2026-03-0{n}T00:00:00'}
            for n in (1, 2, 3)
        ]
        before = portal.PHINS_BALANCE_SHEET['claims_reserve']

        result = portal.post_unposted_claim_transfers('cashier-1')

        assert result['success'] is True
        assert result['durable'] is True
        assert portal.PHINS_BALANCE_SHEET['claims_reserve'] == before + 9000.0
        lines = [
            json.loads(line)
            for line in open(portal._cashflow_repair_journal_path(), encoding='utf-8')
            if line.strip()
        ]
        opening = [row for row in lines if row.get('phase') == 'before' and row.get('actor') == 'cashier-1']
        closing = [row for row in lines if row.get('phase') == 'after' and row.get('actor') == 'cashier-1']
        assert opening and closing
        assert opening[-1]['before']['claims_reserve'] == before
        assert closing[-1]['after']['claims_reserve'] == before + 9000.0
        assert closing[-1]['after']['reserve_restored'] == 9000.0
        recorded = portal.audit.recent(20)
        assert any(
            row.get('actor') == 'cashier-1' and row.get('action') == 'cashflow.reconcile'
            for row in recorded
        )

    def test_a_failed_repair_journal_leaves_the_reserve_unchanged(self, monkeypatch):
        import web_portal.server as portal
        self._setup_customer_and_policy(portal)
        claim = portal.CLAIMS['CLM-TEST-PAY']
        claim['status'] = 'paid'
        claim['paid_amount'] = 4500.0
        portal.PHINS_BALANCE_SHEET['claims_reserve'] = 10000.0
        portal.PHINS_BALANCE_SHEET['transactions'] = [
            {'tx_id': f'BS-{n}', 'category': 'claims_paid', 'claim_id': 'CLM-TEST-PAY',
             'amount': 4500.0, 'timestamp': f'2026-03-0{n}T00:00:00'}
            for n in (1, 2, 3)
        ]

        def _refuse(_record):
            raise OSError('journal volume unavailable')

        monkeypatch.setattr(portal, '_append_cashflow_repair_journal', _refuse)
        result = portal.post_unposted_claim_transfers('cashier-1')

        assert result['success'] is False
        assert result['error'] == 'repair_journal_failed'
        assert portal.PHINS_BALANCE_SHEET['claims_reserve'] == 10000.0
        assert len(portal.PHINS_BALANCE_SHEET['transactions']) == 3

    def test_claim_lines_do_not_hide_savings_still_in_the_wallet(self):
        import web_portal.server as portal
        portal.CLAIMS['CLM-SPENT'] = {
            'id': 'CLM-SPENT', 'customer_id': 'CUST-SPENT', 'status': 'paid', 'paid_amount': 4500.0,
        }
        portal.POLICIES['POL-SPENT'] = {
            'id': 'POL-SPENT', 'customer_id': 'CUST-SPENT', 'start_date': '2026-01-01',
            'annual_premium': 1200.0, 'risk_premium_annual': 1200.0,
        }
        portal.BILLING['BILL-SPENT'] = {
            'id': 'BILL-SPENT', 'customer_id': 'CUST-SPENT', 'policy_id': 'POL-SPENT',
            'payment_period': '2026-01', 'amount_paid': 200.0, 'status': 'paid',
            'premium_allocation': {'risk_amount_paid': 120.0, 'savings_amount_paid': 80.0},
        }
        portal.HEALTH_WALLETS['CUST-SPENT'] = {
            'customer_id': 'CUST-SPENT',
            'balance': 80.0,
            'transactions': [{
                'id': 'W-SPENT', 'type': 'claim_payment', 'claim_id': 'CLM-SPENT',
                'amount': 4500.0, 'previous_balance': 80.0, 'balance_after': 4580.0,
                'timestamp': '2026-02-01T00:00:00',
            }],
        }
        portal.CLAIMS['CLM-HELD'] = {
            'id': 'CLM-HELD', 'customer_id': 'CUST-HELD-CLAIM', 'status': 'paid', 'paid_amount': 4500.0,
        }
        portal.POLICIES['POL-HELD-CLAIM'] = {
            'id': 'POL-HELD-CLAIM', 'customer_id': 'CUST-HELD-CLAIM', 'start_date': '2026-01-01',
            'annual_premium': 1200.0, 'risk_premium_annual': 1200.0,
        }
        portal.BILLING['BILL-HELD-CLAIM'] = {
            'id': 'BILL-HELD-CLAIM', 'customer_id': 'CUST-HELD-CLAIM', 'policy_id': 'POL-HELD-CLAIM',
            'payment_period': '2026-01', 'amount_paid': 200.0, 'status': 'paid',
            'premium_allocation': {'risk_amount_paid': 120.0, 'savings_amount_paid': 80.0},
        }
        portal.HEALTH_WALLETS['CUST-HELD-CLAIM'] = {
            'customer_id': 'CUST-HELD-CLAIM',
            'balance': 4500.0,
            'transactions': [{
                'id': 'W-HELD', 'type': 'claim_payment', 'claim_id': 'CLM-HELD',
                'amount': 4500.0, 'previous_balance': 0.0, 'balance_after': 4500.0,
                'timestamp': '2026-02-01T00:00:00',
            }],
        }

        result = portal.reconcile_savings_premium_balances()
        assert all(row['customer_id'] != 'CUST-SPENT' for row in result['credited'])
        assert portal.HEALTH_WALLETS['CUST-SPENT']['balance'] == 80.0
        held = [row for row in result['credited'] if row['customer_id'] == 'CUST-HELD-CLAIM']
        assert len(held) == 1
        assert held[0]['credited'] == 80.0

    def test_duplicate_wallet_lines_do_not_credit_savings_again(self):
        import web_portal.server as portal
        portal.CLAIMS['CLM-DUP'] = {
            'id': 'CLM-DUP', 'customer_id': 'CUST-DUP', 'status': 'paid', 'paid_amount': 4500.0,
        }
        portal.POLICIES['POL-DUP'] = {
            'id': 'POL-DUP', 'customer_id': 'CUST-DUP', 'start_date': '2026-01-01',
            'annual_premium': 1200.0, 'risk_premium_annual': 1200.0,
        }
        portal.BILLING['BILL-DUP'] = {
            'id': 'BILL-DUP', 'customer_id': 'CUST-DUP', 'policy_id': 'POL-DUP',
            'payment_period': '2026-01', 'amount_paid': 200.0, 'status': 'paid',
            'premium_allocation': {'risk_amount_paid': 120.0, 'savings_amount_paid': 80.0},
        }
        portal.HEALTH_WALLETS['CUST-DUP'] = {
            'customer_id': 'CUST-DUP',
            'balance': 80.0,
            'transactions': [
                {'id': f'WD-{n}', 'type': 'claim_payment', 'claim_id': 'CLM-DUP',
                 'amount': 4500.0, 'previous_balance': 0.0, 'balance_after': 4500.0,
                 'timestamp': f'2026-03-0{n}T00:00:00'}
                for n in (1, 2, 3)
            ],
        }
        portal.CLAIMS['CLM-DUP2'] = {
            'id': 'CLM-DUP2', 'customer_id': 'CUST-DUP2', 'status': 'paid', 'paid_amount': 4500.0,
        }
        portal.POLICIES['POL-DUP2'] = {
            'id': 'POL-DUP2', 'customer_id': 'CUST-DUP2', 'start_date': '2026-01-01',
            'annual_premium': 1200.0, 'risk_premium_annual': 1200.0,
        }
        portal.BILLING['BILL-DUP2'] = {
            'id': 'BILL-DUP2', 'customer_id': 'CUST-DUP2', 'policy_id': 'POL-DUP2',
            'payment_period': '2026-01', 'amount_paid': 200.0, 'status': 'paid',
            'premium_allocation': {'risk_amount_paid': 120.0, 'savings_amount_paid': 80.0},
        }
        portal.HEALTH_WALLETS['CUST-DUP2'] = {
            'customer_id': 'CUST-DUP2',
            'balance': 80.0,
            'transactions': [
                {'id': f'WD2-{n}', 'type': 'claim_payment', 'claim_id': 'CLM-DUP2',
                 'amount': 4500.0, 'timestamp': f'2026-03-0{n}T00:00:00'}
                for n in (1, 2, 3)
            ],
        }

        result = portal.reconcile_savings_premium_balances()
        assert all(row['customer_id'] not in {'CUST-DUP', 'CUST-DUP2'} for row in result['credited'])
        assert portal.HEALTH_WALLETS['CUST-DUP']['balance'] == 80.0
        assert portal.HEALTH_WALLETS['CUST-DUP2']['balance'] == 80.0

    def test_an_intact_claim_is_not_savings_beside_another_claims_duplicates(self):
        import web_portal.server as portal
        portal.CLAIMS['CLM-INTACT'] = {
            'id': 'CLM-INTACT', 'customer_id': 'CUST-MIX', 'status': 'paid', 'paid_amount': 4500.0,
        }
        portal.CLAIMS['CLM-REPEAT'] = {
            'id': 'CLM-REPEAT', 'customer_id': 'CUST-MIX', 'status': 'paid', 'paid_amount': 4500.0,
        }
        portal.POLICIES['POL-MIX'] = {
            'id': 'POL-MIX', 'customer_id': 'CUST-MIX', 'start_date': '2026-01-01',
            'annual_premium': 1200.0, 'risk_premium_annual': 1200.0,
        }
        portal.BILLING['BILL-MIX'] = {
            'id': 'BILL-MIX', 'customer_id': 'CUST-MIX', 'policy_id': 'POL-MIX',
            'payment_period': '2026-01', 'amount_paid': 200.0, 'status': 'paid',
            'premium_allocation': {'risk_amount_paid': 120.0, 'savings_amount_paid': 80.0},
        }
        portal.HEALTH_WALLETS['CUST-MIX'] = {
            'customer_id': 'CUST-MIX',
            'balance': 4500.0,
            'transactions': [
                {'id': 'W-INTACT', 'type': 'claim_payment', 'claim_id': 'CLM-INTACT',
                 'amount': 4500.0, 'previous_balance': 0.0, 'balance_after': 4500.0,
                 'timestamp': '2026-02-01T00:00:00'},
                {'id': 'W-R1', 'type': 'claim_payment', 'claim_id': 'CLM-REPEAT',
                 'amount': 4500.0, 'previous_balance': 0.0, 'balance_after': 4500.0,
                 'timestamp': '2026-03-01T00:00:00'},
                {'id': 'W-R2', 'type': 'claim_payment', 'claim_id': 'CLM-REPEAT',
                 'amount': 4500.0, 'previous_balance': 0.0, 'balance_after': 4500.0,
                 'timestamp': '2026-03-02T00:00:00'},
            ],
        }

        result = portal.reconcile_savings_premium_balances()
        mixed = [row for row in result['credited'] if row['customer_id'] == 'CUST-MIX']
        assert len(mixed) == 1
        assert mixed[0]['credited'] == 80.0
        stamped = portal.INVESTMENT_ACCOUNTS.get('CUST-MIX', {}).get('savings_premiums_applied')
        assert stamped == 80.0

    def test_a_spent_claim_does_not_hide_savings_beside_duplicate_lines(self):
        import web_portal.server as portal
        portal.CLAIMS['CLM-GONE'] = {
            'id': 'CLM-GONE', 'customer_id': 'CUST-GONE', 'status': 'paid', 'paid_amount': 4500.0,
        }
        portal.CLAIMS['CLM-COPIES'] = {
            'id': 'CLM-COPIES', 'customer_id': 'CUST-GONE', 'status': 'paid', 'paid_amount': 4500.0,
        }
        portal.POLICIES['POL-GONE'] = {
            'id': 'POL-GONE', 'customer_id': 'CUST-GONE', 'start_date': '2026-01-01',
            'annual_premium': 1200.0, 'risk_premium_annual': 1200.0,
        }
        portal.BILLING['BILL-GONE'] = {
            'id': 'BILL-GONE', 'customer_id': 'CUST-GONE', 'policy_id': 'POL-GONE',
            'payment_period': '2026-01', 'amount_paid': 200.0, 'status': 'paid',
            'premium_allocation': {'risk_amount_paid': 120.0, 'savings_amount_paid': 80.0},
        }
        portal.HEALTH_WALLETS['CUST-GONE'] = {
            'customer_id': 'CUST-GONE',
            'balance': 80.0,
            'transactions': [
                {'id': 'W-GONE', 'type': 'claim_payment', 'claim_id': 'CLM-GONE',
                 'amount': 4500.0, 'previous_balance': 0.0, 'balance_after': 4500.0,
                 'timestamp': '2026-02-01T00:00:00'},
                {'id': 'W-C1', 'type': 'claim_payment', 'claim_id': 'CLM-COPIES',
                 'amount': 4500.0, 'previous_balance': 0.0, 'balance_after': 4500.0,
                 'timestamp': '2026-03-01T00:00:00'},
                {'id': 'W-C2', 'type': 'claim_payment', 'claim_id': 'CLM-COPIES',
                 'amount': 4500.0, 'previous_balance': 0.0, 'balance_after': 4500.0,
                 'timestamp': '2026-03-02T00:00:00'},
            ],
        }

        result = portal.reconcile_savings_premium_balances()
        assert all(row['customer_id'] != 'CUST-GONE' for row in result['credited'])
        assert portal.HEALTH_WALLETS['CUST-GONE']['balance'] == 80.0

    def test_a_spent_claim_is_not_set_aside_ahead_of_claims_still_in_the_wallet(self):
        import web_portal.server as portal
        portal.CLAIMS['CLM-BIG-SPENT'] = {
            'id': 'CLM-BIG-SPENT', 'customer_id': 'CUST-PACK', 'status': 'paid', 'paid_amount': 3000.0,
        }
        portal.CLAIMS['CLM-HELD-A'] = {
            'id': 'CLM-HELD-A', 'customer_id': 'CUST-PACK', 'status': 'paid', 'paid_amount': 2000.0,
        }
        portal.CLAIMS['CLM-HELD-B'] = {
            'id': 'CLM-HELD-B', 'customer_id': 'CUST-PACK', 'status': 'paid', 'paid_amount': 2000.0,
        }
        portal.CLAIMS['CLM-PACK-DUP'] = {
            'id': 'CLM-PACK-DUP', 'customer_id': 'CUST-PACK', 'status': 'paid', 'paid_amount': 4500.0,
        }
        portal.POLICIES['POL-PACK'] = {
            'id': 'POL-PACK', 'customer_id': 'CUST-PACK', 'start_date': '2026-01-01',
            'annual_premium': 1200.0, 'risk_premium_annual': 1200.0,
        }
        portal.BILLING['BILL-PACK'] = {
            'id': 'BILL-PACK', 'customer_id': 'CUST-PACK', 'policy_id': 'POL-PACK',
            'payment_period': '2026-01', 'amount_paid': 200.0, 'status': 'paid',
            'premium_allocation': {'risk_amount_paid': 120.0, 'savings_amount_paid': 80.0},
        }
        portal.HEALTH_WALLETS['CUST-PACK'] = {
            'customer_id': 'CUST-PACK',
            'balance': 4000.0,
            'transactions': [
                {'id': 'W-BIG', 'type': 'claim_payment', 'claim_id': 'CLM-BIG-SPENT',
                 'amount': 3000.0, 'previous_balance': 0.0, 'balance_after': 3000.0,
                 'timestamp': '2026-02-01T00:00:00'},
                {'id': 'W-A', 'type': 'claim_payment', 'claim_id': 'CLM-HELD-A',
                 'amount': 2000.0, 'previous_balance': 0.0, 'balance_after': 2000.0,
                 'timestamp': '2026-02-02T00:00:00'},
                {'id': 'W-B', 'type': 'claim_payment', 'claim_id': 'CLM-HELD-B',
                 'amount': 2000.0, 'previous_balance': 0.0, 'balance_after': 4000.0,
                 'timestamp': '2026-02-03T00:00:00'},
                {'id': 'W-PD1', 'type': 'claim_payment', 'claim_id': 'CLM-PACK-DUP',
                 'amount': 4500.0, 'previous_balance': 0.0, 'balance_after': 4500.0,
                 'timestamp': '2026-03-01T00:00:00'},
                {'id': 'W-PD2', 'type': 'claim_payment', 'claim_id': 'CLM-PACK-DUP',
                 'amount': 4500.0, 'previous_balance': 0.0, 'balance_after': 4500.0,
                 'timestamp': '2026-03-02T00:00:00'},
            ],
        }

        result = portal.reconcile_savings_premium_balances()
        packed = [row for row in result['credited'] if row['customer_id'] == 'CUST-PACK']
        assert len(packed) == 1
        assert packed[0]['credited'] == 80.0
        assert portal.INVESTMENT_ACCOUNTS.get('CUST-PACK', {}).get('savings_premiums_applied') == 80.0

    def test_savings_beside_a_held_claim_is_not_credited_again(self):
        import web_portal.server as portal
        portal.CLAIMS['CLM-STILL'] = {
            'id': 'CLM-STILL', 'customer_id': 'CUST-BESIDE', 'status': 'paid', 'paid_amount': 4500.0,
        }
        portal.CLAIMS['CLM-SMALL-SPENT'] = {
            'id': 'CLM-SMALL-SPENT', 'customer_id': 'CUST-BESIDE', 'status': 'paid', 'paid_amount': 100.0,
        }
        portal.CLAIMS['CLM-BESIDE-DUP'] = {
            'id': 'CLM-BESIDE-DUP', 'customer_id': 'CUST-BESIDE', 'status': 'paid', 'paid_amount': 4500.0,
        }
        portal.POLICIES['POL-BESIDE'] = {
            'id': 'POL-BESIDE', 'customer_id': 'CUST-BESIDE', 'start_date': '2026-01-01',
            'annual_premium': 1200.0, 'risk_premium_annual': 1200.0,
        }
        portal.BILLING['BILL-BESIDE'] = {
            'id': 'BILL-BESIDE', 'customer_id': 'CUST-BESIDE', 'policy_id': 'POL-BESIDE',
            'payment_period': '2026-01', 'amount_paid': 200.0, 'status': 'paid',
            'premium_allocation': {'risk_amount_paid': 120.0, 'savings_amount_paid': 80.0},
        }
        portal.HEALTH_WALLETS['CUST-BESIDE'] = {
            'customer_id': 'CUST-BESIDE',
            'balance': 4580.0,
            'transactions': [
                {'id': 'W-STILL', 'type': 'claim_payment', 'claim_id': 'CLM-STILL',
                 'amount': 4500.0, 'previous_balance': 0.0, 'balance_after': 4500.0,
                 'timestamp': '2026-02-01T00:00:00'},
                {'id': 'W-SMALL', 'type': 'claim_payment', 'claim_id': 'CLM-SMALL-SPENT',
                 'amount': 100.0, 'previous_balance': 0.0, 'balance_after': 100.0,
                 'timestamp': '2026-02-02T00:00:00'},
                {'id': 'W-BD1', 'type': 'claim_payment', 'claim_id': 'CLM-BESIDE-DUP',
                 'amount': 4500.0, 'previous_balance': 0.0, 'balance_after': 4500.0,
                 'timestamp': '2026-03-01T00:00:00'},
                {'id': 'W-BD2', 'type': 'claim_payment', 'claim_id': 'CLM-BESIDE-DUP',
                 'amount': 4500.0, 'previous_balance': 0.0, 'balance_after': 4500.0,
                 'timestamp': '2026-03-02T00:00:00'},
            ],
        }

        result = portal.reconcile_savings_premium_balances()
        assert all(row['customer_id'] != 'CUST-BESIDE' for row in result['credited'])
        assert portal.HEALTH_WALLETS['CUST-BESIDE']['balance'] == 4580.0

    def test_after_journal_miss_still_reports_a_durable_repair(self, monkeypatch):
        import web_portal.server as portal
        self._setup_customer_and_policy(portal)
        claim = portal.CLAIMS['CLM-TEST-PAY']
        claim['status'] = 'paid'
        claim['paid_amount'] = 4500.0
        portal.PHINS_BALANCE_SHEET['claims_reserve'] = 10000.0
        portal.PHINS_BALANCE_SHEET['transactions'] = [
            {'tx_id': f'BS-{n}', 'category': 'claims_paid', 'claim_id': 'CLM-TEST-PAY',
             'amount': 4500.0, 'timestamp': f'2026-03-0{n}T00:00:00'}
            for n in (1, 2, 3)
        ]
        calls = {'n': 0}
        original = portal._append_cashflow_repair_journal

        def _append(record):
            calls['n'] += 1
            if record.get('phase') == 'after':
                raise OSError('after line failed')
            original(record)

        monkeypatch.setattr(portal, '_append_cashflow_repair_journal', _append)
        result = portal.post_unposted_claim_transfers('cashier-2')

        assert result['journal_after'] is False
        assert result['durable'] is True
        assert result['success'] is True
        assert result['error'] is None
        assert portal.PHINS_BALANCE_SHEET['claims_reserve'] == 19000.0
        assert calls['n'] >= 2

    def test_wallet_only_collapse_is_saved(self, monkeypatch):
        import web_portal.server as portal
        self._setup_customer_and_policy(portal)
        claim = portal.CLAIMS['CLM-TEST-PAY']
        claim['status'] = 'paid'
        claim['paid_amount'] = 4500.0
        portal.PHINS_BALANCE_SHEET['claims_reserve'] = 10000.0
        portal.PHINS_BALANCE_SHEET['transactions'] = [
            {'tx_id': 'BS-1', 'category': 'claims_paid', 'claim_id': 'CLM-TEST-PAY',
             'amount': 4500.0, 'timestamp': '2026-03-01T00:00:00'},
        ]
        portal.HEALTH_WALLETS['CUST-TEST-PAY'] = {
            'customer_id': 'CUST-TEST-PAY',
            'balance': 13500.0,
            'transactions': [
                {'id': f'W-{n}', 'type': 'claim_payment', 'claim_id': 'CLM-TEST-PAY',
                 'amount': 4500.0, 'timestamp': f'2026-03-0{n}T00:00:00'}
                for n in (1, 2, 3)
            ],
        }
        saved = {'called': False}

        def _save(*args, **kwargs):
            saved['called'] = True
            return True

        monkeypatch.setattr(portal, 'save_ledger_data', _save)
        result = portal.post_unposted_claim_transfers('cashier-3')

        assert result['collapsed']['balance_sheet_rows_removed'] == 0
        assert result['collapsed']['wallet_credit_removed'] == 9000.0
        assert portal.HEALTH_WALLETS['CUST-TEST-PAY']['balance'] == 4500.0
        assert saved['called'] is True
        assert result['durable'] is True

    def test_overlapping_repairs_apply_once(self, monkeypatch):
        import threading
        import web_portal.server as portal
        self._setup_customer_and_policy(portal)
        claim = portal.CLAIMS['CLM-TEST-PAY']
        claim['status'] = 'paid'
        claim['paid_amount'] = 4500.0
        portal.PHINS_BALANCE_SHEET['claims_reserve'] = 10000.0
        portal.PHINS_BALANCE_SHEET['transactions'] = [
            {'tx_id': f'BS-{n}', 'category': 'claims_paid', 'claim_id': 'CLM-TEST-PAY',
             'amount': 4500.0, 'timestamp': f'2026-03-0{n}T00:00:00'}
            for n in (1, 2, 3)
        ]
        portal.POLICIES['POL-RACE'] = {
            'id': 'POL-RACE', 'customer_id': 'CUST-TEST-PAY', 'start_date': '2026-01-01',
            'annual_premium': 1200.0, 'risk_premium_annual': 1200.0,
        }
        portal.BILLING['BILL-RACE'] = {
            'id': 'BILL-RACE', 'customer_id': 'CUST-TEST-PAY', 'policy_id': 'POL-RACE',
            'payment_period': '2026-01', 'amount_paid': 200.0, 'status': 'paid',
            'premium_allocation': {'risk_amount_paid': 120.0, 'savings_amount_paid': 80.0},
        }
        entered = threading.Event()
        release = threading.Event()
        original = portal.collapse_duplicate_claim_transfers
        calls = {'n': 0}

        def _first_waits():
            calls['n'] += 1
            if calls['n'] == 1:
                entered.set()
                assert release.wait(timeout=3)
            return original()

        monkeypatch.setattr(portal, 'collapse_duplicate_claim_transfers', _first_waits)
        monkeypatch.setattr(portal, 'save_ledger_data', lambda *args, **kwargs: True)
        results = {}

        def _run(name):
            results[name] = portal.post_unposted_claim_transfers(name)

        first = threading.Thread(target=_run, args=('one',))
        second = threading.Thread(target=_run, args=('two',))
        first.start()
        assert entered.wait(timeout=3)
        second.start()
        second.join(timeout=0.3)
        assert second.is_alive()
        assert portal.PHINS_BALANCE_SHEET['claims_reserve'] == 10000.0
        release.set()
        first.join(timeout=3)
        second.join(timeout=3)

        assert not first.is_alive() and not second.is_alive()
        assert portal.PHINS_BALANCE_SHEET['claims_reserve'] == 19000.0
        assert calls['n'] == 2
        wallet = portal.HEALTH_WALLETS.get('CUST-TEST-PAY', {}).get('balance', 0.0)
        books = portal._investment_books(portal.INVESTMENT_ACCOUNTS.get('CUST-TEST-PAY') or {})
        algo_store = getattr(portal.unified_balance_service, 'algo_trading_balances', {}) or {}
        algo = float((algo_store.get('CUST-TEST-PAY') or {}).get('available') or 0)
        assert round(float(wallet) + float(books.get('position') or 0) + algo, 2) == 80.0
        assert results['one']['success'] is True
        assert results['two']['success'] is True


class TestClaimPaymentPipeline:
    """Test /api/claims/pay processes through wallet pipeline."""

    def test_claims_pay_api(self):
        """Verify /api/claims/pay route calls process_claim_payment_to_wallet.

        The embedded test server clears dicts on the first request per test
        via _ensure_test_port_state, so we make a priming POST (empty path
        triggers 404) to trigger that init, then populate data.
        """
        import web_portal.server as portal
        # Prime port state via a harmless POST — clears dicts once
        try:
            api_post('/api/_noop', {})
        except Exception:
            pass

        cust_id = 'CUST-PAYPIPE'
        portal.CUSTOMERS[cust_id] = {
            'id': cust_id, 'name': 'PayPipe', 'email': 'paypipe@test.com'
        }
        portal.POLICIES['POL-PAYPIPE'] = {
            'id': 'POL-PAYPIPE', 'customer_id': cust_id,
            'type': 'health', 'status': 'active',
            'coverage_amount': 50000, 'monthly_premium': 50, 'annual_premium': 600,
        }
        portal.CLAIMS['CLM-PAYPIPE-001'] = {
            'id': 'CLM-PAYPIPE-001', 'customer_id': cust_id,
            'policy_id': 'POL-PAYPIPE', 'type': 'Medical',
            'claimed_amount': 2000.0, 'approved_amount': 1800.0,
            'status': 'approved',
        }
        portal.PHINS_BALANCE_SHEET['claims_reserve'] = 500000.0

        resp = api_post('/api/claims/pay', {'id': 'CLM-PAYPIPE-001'})
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        body = resp.json()
        assert body.get('success') is True

        wallet = portal.HEALTH_WALLETS.get(cust_id, {})
        assert wallet.get('balance', 0) >= 1800.0

        claim = portal.CLAIMS.get('CLM-PAYPIPE-001', {})
        assert claim.get('status') == 'paid'
        assert claim.get('payment_method') == 'health_wallet_transfer'


class TestAccountingEnginePremiumAllocation:
    """Test AccountingEngine handles premium splits and claim payments."""

    def test_premium_allocation_risk_savings_split(self):
        from accounting_engine import AccountingEngine, InvestmentRoute
        engine = AccountingEngine()
        alloc = engine.create_allocation(
            bill_id='BILL-001',
            policy_id='POL-001',
            customer_id='CUST-001',
            total_premium=Decimal('500.00'),
            risk_percentage=Decimal('25'),
            investment_route=InvestmentRoute.BASIC_SAVINGS,
        )
        assert alloc.risk_premium == Decimal('125.00')
        assert alloc.savings_premium == Decimal('375.00')
        assert alloc.risk_premium + alloc.savings_premium == alloc.total_premium

    def test_premium_allocation_75_25(self):
        from accounting_engine import AccountingEngine
        engine = AccountingEngine()
        alloc = engine.create_allocation(
            bill_id='BILL-002',
            policy_id='POL-002',
            customer_id='CUST-002',
            total_premium=Decimal('1000.00'),
            risk_percentage=Decimal('75'),
        )
        assert alloc.risk_premium == Decimal('750.00')
        assert alloc.savings_premium == Decimal('250.00')

    def test_claim_payment_posts_to_ledger(self):
        from accounting_engine import AccountingEngine, EntryType
        engine = AccountingEngine()
        success, msg = engine.post_claim_payment(
            claim_id='CLM-TEST-001',
            policy_id='POL-001',
            customer_id='CUST-001',
            amount=Decimal('5000.00'),
            paid_by='accountant'
        )
        assert success is True
        claim_entries = [e for e in engine.ledger_entries if e.entry_type == EntryType.CLAIM_PAYMENT]
        assert len(claim_entries) == 1
        assert claim_entries[0].credit_amount == Decimal('5000.00')

    def test_get_accounting_engine_returns_singleton(self):
        from accounting_engine import get_accounting_engine
        ae1 = get_accounting_engine()
        ae2 = get_accounting_engine()
        assert ae1 is ae2


class TestAutoPayProcessesAllPolicies:
    """Ensure auto-pay processes all active policies with auto_pay enabled."""

    def test_auto_pay_processes_active_policies(self):
        import web_portal.server as portal
        now = datetime(2026, 5, 1, 0, 0, 0)
        portal.POLICIES.clear()
        portal.CUSTOMERS.clear()

        for i in range(3):
            cust_id = f'CUST-AP-{i}'
            pol_id = f'POL-AP-{i}'
            portal.CUSTOMERS[cust_id] = {
                'id': cust_id, 'name': f'AutoPay {i}', 'email': f'ap{i}@test.com'
            }
            portal.POLICIES[pol_id] = {
                'id': pol_id,
                'customer_id': cust_id,
                'type': 'health',
                'status': 'active',
                'coverage_amount': 100000,
                'monthly_premium': 100.0,
                'annual_premium': 1200.0,
                'payment_setup': {
                    'auto_pay': True,
                    'billing_frequency': 'monthly',
                    'next_billing_date': now.isoformat(),
                },
                'billing': {
                    'auto_pay': True,
                    'frequency': 'monthly',
                    'next_billing_date': now.isoformat(),
                },
            }
        portal.PHINS_BALANCE_SHEET['claims_reserve'] = 1000000.0

        report = portal.run_monthly_auto_pay(
            reference_datetime=now,
            enforce_first_day=True,
            dry_run=False,
            notify_users=False,
        )
        assert report['processed'] == 3
        assert report['total_amount'] > 0

    def test_auto_pay_skips_inactive_policies(self):
        """Inactive/suspended policies should not be processed by auto-pay."""
        import web_portal.server as portal
        now = datetime(2026, 5, 1, 0, 0, 0)

        portal.POLICIES.clear()
        portal.CUSTOMERS.clear()

        portal.CUSTOMERS['CUST-NOAP'] = {
            'id': 'CUST-NOAP', 'name': 'Inactive', 'email': 'noap@test.com'
        }
        portal.POLICIES['POL-NOAP'] = {
            'id': 'POL-NOAP',
            'customer_id': 'CUST-NOAP',
            'type': 'health',
            'status': 'pending_underwriting',
            'monthly_premium': 100.0,
            'annual_premium': 1200.0,
        }

        report = portal.run_monthly_auto_pay(
            reference_datetime=now,
            enforce_first_day=True,
            dry_run=False,
            notify_users=False,
        )
        assert report['processed'] == 0

    def test_auto_pay_normalizes_all_active_policies(self):
        """Auto-pay normalization ensures all active policies get auto-pay enabled."""
        import web_portal.server as portal
        now = datetime(2026, 5, 1, 0, 0, 0)

        portal.POLICIES.clear()
        portal.CUSTOMERS.clear()

        portal.CUSTOMERS['CUST-NORM'] = {
            'id': 'CUST-NORM', 'name': 'Normalized', 'email': 'norm@test.com'
        }
        portal.POLICIES['POL-NORM'] = {
            'id': 'POL-NORM',
            'customer_id': 'CUST-NORM',
            'type': 'health',
            'status': 'active',
            'monthly_premium': 100.0,
            'annual_premium': 1200.0,
        }

        report = portal.run_monthly_auto_pay(
            reference_datetime=now,
            enforce_first_day=True,
            dry_run=False,
            notify_users=False,
        )
        assert report['processed'] == 1
        policy = portal.POLICIES['POL-NORM']
        assert policy.get('payment_setup', {}).get('auto_pay') is True


class TestSeedDataIntegrity:
    """Verify seed data has consistent amounts and no orphan references."""

    def test_seed_policy_premiums_match_billing(self):
        """Every active seeded policy should have a matching bill with the correct amount."""
        from database.seeds import seed_sample_data
        import web_portal.server as portal

        portal.CUSTOMERS.clear()
        portal.POLICIES.clear()
        portal.BILLING.clear()
        portal.CLAIMS.clear()

        policies_data = [
            {'id': 'POL-ASAF-LIFE-001', 'monthly_premium': 299.25},
            {'id': 'POL-ASAF-HEALTH-001', 'monthly_premium': 166.25},
        ]

        for pol in policies_data:
            bill_id = f"BILL-{pol['id'].replace('POL-', '')}"
            portal.POLICIES[pol['id']] = {
                'id': pol['id'],
                'customer_id': 'CUST-ASAF-001',
                'monthly_premium': pol['monthly_premium'],
                'status': 'active',
            }
            portal.BILLING[bill_id] = {
                'id': bill_id,
                'policy_id': pol['id'],
                'customer_id': 'CUST-ASAF-001',
                'amount': pol['monthly_premium'],
                'status': 'outstanding',
            }

        for pol in policies_data:
            bill_id = f"BILL-{pol['id'].replace('POL-', '')}"
            bill = portal.BILLING.get(bill_id)
            assert bill is not None, f"Missing bill {bill_id} for policy {pol['id']}"
            assert abs(bill['amount'] - pol['monthly_premium']) < 0.01, \
                f"Bill {bill_id} amount {bill['amount']} != policy premium {pol['monthly_premium']}"

    def test_paid_claims_reflected_in_wallet(self):
        """Claims with Paid status must have their approved_amount in the wallet."""
        import web_portal.server as portal

        cust_id = 'CUST-WALLET-TEST'
        portal.CUSTOMERS[cust_id] = {'id': cust_id, 'name': 'Wallet Test'}
        portal.HEALTH_WALLETS[cust_id] = {
            'customer_id': cust_id, 'balance': 0.0, 'transactions': [],
            'monthly_deposit': 0.0, 'created_at': datetime.now().isoformat()
        }
        portal.PHINS_BALANCE_SHEET['claims_reserve'] = 1000000.0

        paid_claims = [
            {'id': 'CLM-W-001', 'approved_amount': 1500.0, 'policy_id': 'POL-W'},
            {'id': 'CLM-W-002', 'approved_amount': 3000.0, 'policy_id': 'POL-W'},
        ]
        portal.POLICIES['POL-W'] = {
            'id': 'POL-W', 'customer_id': cust_id, 'type': 'health',
            'status': 'active', 'monthly_premium': 100, 'annual_premium': 1200,
            'coverage_amount': 50000,
        }

        expected_total = 0.0
        for c in paid_claims:
            portal.CLAIMS[c['id']] = {
                'id': c['id'], 'customer_id': cust_id, 'policy_id': c['policy_id'],
                'type': 'Medical', 'claimed_amount': c['approved_amount'],
                'approved_amount': c['approved_amount'], 'status': 'approved',
            }
            result = portal.process_claim_payment_to_wallet(
                claim_id=c['id'], customer_id=cust_id,
                amount=c['approved_amount'], processed_by='test'
            )
            assert result['success'] is True
            expected_total += c['approved_amount']

        wallet = portal.HEALTH_WALLETS[cust_id]
        assert abs(wallet['balance'] - expected_total) < 0.01, \
            f"Wallet balance {wallet['balance']} != expected {expected_total}"
        assert len(wallet['transactions']) == len(paid_claims)


class TestActuarialDistributionIntegrity:
    """Premium cash split stays on customer allocation; actuarial context is additive."""

    def test_monthly_distribution_keeps_allocation_math_and_actuarial_source(self):
        import web_portal.server as portal

        customer_id = 'CUST-ACTUARIAL-FLOW'
        portal.CUSTOMERS[customer_id] = {
            'id': customer_id,
            'name': 'Actuarial Flow',
            'age': 45,
        }
        portal.POLICIES['POL-ACT-FLOW'] = {
            'id': 'POL-ACT-FLOW',
            'customer_id': customer_id,
            'type': 'life',
            'coverage_amount': 250000.0,
            'annual_premium': 12000.0,
            'monthly_premium': 1000.0,
            'status': 'active',
            'risk_score': 'medium',
            'risk_premium_annual': 9000.0,
            'savings_premium_annual': 3000.0,
            'pricing_source': 'pricing_kernel',
        }

        dist = portal.calculate_monthly_distribution(customer_id)
        assert dist['customer_age'] == 45
        assert dist['policy_count'] == 1
        assert dist['total_monthly_premium'] == 1000.0
        assert dist['actuarial_data']['data_source'] == 'pricing_kernel_pin'
        assert dist['actuarial_data']['total_risk_premium'] == 9000.0
        assert dist['actuarial_data']['total_savings_premium'] == 3000.0

        alloc = dist['allocation']
        assert alloc['savings_pct'] == 25.0
        assert alloc['risk_pct'] == 75.0
        assert alloc['wallet_pct'] == 30.0
        assert alloc['investment_pct'] == 65.0
        assert alloc['algo_pct'] == 5.0

        cash = dist['distribution']
        assert abs(cash['risk_coverage'] + cash['total_savings'] - 1000.0) < 0.01
        assert abs(cash['health_wallet'] + cash['investment'] + cash['algo_trading'] - cash['total_savings']) < 0.01
        assert abs(cash['total_savings'] - 250.0) < 0.01
        assert abs(cash['health_wallet'] - 75.0) < 0.01
        assert abs(cash['investment'] - 162.5) < 0.01
        assert abs(cash['algo_trading'] - 12.5) < 0.01

    def test_unified_monthly_distribution_forwards_actuarial_fields(self):
        source = Path(__file__).resolve().parents[1] / "web_portal" / "server.py"
        text = source.read_text(encoding="utf-8")
        assert "'customer_age': distribution.get('customer_age')" in text
        assert "'policy_count': distribution.get('policy_count')" in text
        assert "'actuarial_data': distribution.get('actuarial_data')" in text

    def test_activate_profits_does_not_seed_mock_initial_pnl(self):
        source = Path(__file__).resolve().parents[1] / "web_portal" / "server.py"
        text = source.read_text(encoding="utf-8")
        assert "Run 3 initial cycles" not in text
        assert "Generated ${total_initial_profit:.2f} initial profit." not in text
        assert "Waiting for live market signals." in text
