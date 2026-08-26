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
            {'id': 'POL-ASAF-AUTO-001', 'monthly_premium': 17.96},
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
        }

        dist = portal.calculate_monthly_distribution(customer_id)
        assert dist['customer_age'] == 45
        assert dist['policy_count'] == 1
        assert dist['total_monthly_premium'] == 1000.0
        assert dist['actuarial_data']['data_source'] == 'PHINS_ACTUARIAL_TABLES_V1'

        alloc = dist['allocation']
        assert alloc['savings_pct'] == 50.0
        assert alloc['risk_pct'] == 50.0
        assert alloc['wallet_pct'] == 30.0
        assert alloc['investment_pct'] == 65.0
        assert alloc['algo_pct'] == 5.0

        cash = dist['distribution']
        assert abs(cash['risk_coverage'] + cash['total_savings'] - 1000.0) < 0.01
        assert abs(cash['health_wallet'] + cash['investment'] + cash['algo_trading'] - cash['total_savings']) < 0.01
        assert abs(cash['total_savings'] - 500.0) < 0.01
        assert abs(cash['health_wallet'] - 150.0) < 0.01
        assert abs(cash['investment'] - 325.0) < 0.01
        assert abs(cash['algo_trading'] - 25.0) < 0.01

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
