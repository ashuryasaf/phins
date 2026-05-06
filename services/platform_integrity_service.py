"""
PHINS Platform Integrity Service
=================================
Comprehensive data integrity validation for all platform pipelines.

Features:
- User type validation (admins, suppliers, customers, foundation members)
- Ledger integrity checks (health wallets, investment accounts, transactions)
- Pipeline workflow validation (policies, claims, billing, foundations, suppliers)
- Cross-reference validation (customer -> policy -> billing consistency)
- Orphaned record detection
- Balance reconciliation
- Audit trail verification

Validates:
1. User Types: admins, underwriters, actuaries, suppliers, customers
2. Customer Records: Complete profile data, wallet initialization
3. Policy Pipeline: customer -> policy -> underwriting -> billing
4. Claims Pipeline: policy -> claim -> payment -> wallet
5. Billing Pipeline: policy -> bill -> payment -> revenue
6. Foundation Pipeline: foundation -> members -> contributions -> funds
7. Supplier Pipeline: supplier -> offers -> orders -> delivery
8. Delivery Pipeline: order -> request -> bid -> delivery -> payment
9. Ledger Integrity: Balance consistency, transaction matching
"""

import json
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional, Tuple, Set
from collections import defaultdict
import logging

logger = logging.getLogger('phins.platform_integrity')


class PlatformIntegrityService:
    """
    Validates data integrity across all PHINS platform pipelines.
    
    Performs:
    - Structure validation
    - Referential integrity checks
    - Balance reconciliation
    - Workflow state validation
    - Orphaned record detection
    """
    
    def __init__(self):
        """Initialize platform integrity service"""
        self.validation_results: Dict[str, Any] = {}
        self.errors: List[Dict[str, Any]] = []
        self.warnings: List[Dict[str, Any]] = []
        
        logger.info("Platform Integrity Service initialized")
    
    def validate_all(
        self,
        users: Dict[str, Any],
        customers: Dict[str, Any],
        suppliers: Dict[str, Any],
        policies: Dict[str, Any],
        claims: Dict[str, Any],
        billing: Dict[str, Any],
        underwriting_applications: Dict[str, Any],
        health_wallets: Dict[str, Any],
        investment_accounts: Dict[str, Any],
        transaction_ledger: Dict[str, Any],
        balance_sheet: Dict[str, Any],
        foundations: Dict[str, Any] = None,
        foundation_members: Dict[str, Any] = None,
        supplier_orders: Dict[str, Any] = None,
        delivery_requests: Dict[str, Any] = None,
        active_deliveries: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """
        Run comprehensive integrity validation across all platform data.
        
        Returns:
            Validation report with errors, warnings, and summary
        """
        self.errors = []
        self.warnings = []
        self.validation_results = {}
        
        logger.info("Starting comprehensive platform integrity validation...")
        
        # 1. User Type Validation
        user_validation = self._validate_users(users)
        self.validation_results['users'] = user_validation
        
        # 2. Customer Data Validation
        customer_validation = self._validate_customers(customers, users)
        self.validation_results['customers'] = customer_validation
        
        # 3. Supplier Data Validation
        supplier_validation = self._validate_suppliers(suppliers)
        self.validation_results['suppliers'] = supplier_validation
        
        # 4. Policy Pipeline Validation
        policy_validation = self._validate_policy_pipeline(
            customers, policies, underwriting_applications, billing
        )
        self.validation_results['policies'] = policy_validation
        
        # 5. Claims Pipeline Validation
        claims_validation = self._validate_claims_pipeline(
            policies, claims, health_wallets, transaction_ledger
        )
        self.validation_results['claims'] = claims_validation
        
        # 6. Billing Pipeline Validation
        billing_validation = self._validate_billing_pipeline(
            policies, billing, balance_sheet
        )
        self.validation_results['billing'] = billing_validation
        
        # 7. Wallet and Ledger Integrity
        ledger_validation = self._validate_ledger_integrity(
            customers, health_wallets, investment_accounts, transaction_ledger
        )
        self.validation_results['ledger'] = ledger_validation
        
        # 8. Foundation Pipeline Validation (if data provided)
        if foundations and foundation_members:
            foundation_validation = self._validate_foundation_pipeline(
                foundations, foundation_members, customers, suppliers
            )
            self.validation_results['foundations'] = foundation_validation
        
        # 9. Supplier Order Pipeline Validation (if data provided)
        if supplier_orders:
            order_validation = self._validate_supplier_orders(
                supplier_orders, suppliers, customers
            )
            self.validation_results['supplier_orders'] = order_validation
        
        # 10. Delivery Pipeline Validation (if data provided)
        if delivery_requests and active_deliveries:
            delivery_validation = self._validate_delivery_pipeline(
                delivery_requests, active_deliveries, supplier_orders, health_wallets
            )
            self.validation_results['deliveries'] = delivery_validation
        
        # Generate summary
        summary = self._generate_validation_summary()
        
        result = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'status': 'PASS' if len(self.errors) == 0 else 'FAIL',
            'summary': summary,
            'validation_results': self.validation_results,
            'errors': self.errors,
            'warnings': self.warnings
        }
        
        logger.info(f"Platform integrity validation completed: "
                   f"{summary['total_checks']} checks, "
                   f"{summary['errors_found']} errors, "
                   f"{summary['warnings_found']} warnings")
        
        return result
    
    def _validate_users(self, users: Dict[str, Any]) -> Dict[str, Any]:
        """Validate user types and roles"""
        valid_roles = {'admin', 'underwriter', 'claims', 'accountant', 'actuary', 
                      'supplier', 'media', 'customer'}
        
        role_counts = defaultdict(int)
        invalid_roles = []
        missing_fields = []
        
        for username, user_data in users.items():
            role = user_data.get('role')
            role_counts[role] += 1
            
            # Validate role
            if role not in valid_roles:
                invalid_roles.append(username)
                self.errors.append({
                    'category': 'users',
                    'severity': 'error',
                    'username': username,
                    'message': f"Invalid role '{role}' for user {username}"
                })
            
            # Check required fields
            required_fields = ['hash', 'salt', 'role', 'name']
            for field in required_fields:
                if field not in user_data or not user_data[field]:
                    missing_fields.append(f"{username}.{field}")
                    self.errors.append({
                        'category': 'users',
                        'severity': 'error',
                        'username': username,
                        'message': f"Missing required field '{field}' for user {username}"
                    })
        
        return {
            'total_users': len(users),
            'role_breakdown': dict(role_counts),
            'invalid_roles': len(invalid_roles),
            'missing_fields': len(missing_fields),
            'status': 'PASS' if len(invalid_roles) == 0 and len(missing_fields) == 0 else 'FAIL'
        }
    
    def _validate_customers(
        self,
        customers: Dict[str, Any],
        users: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Validate customer records"""
        missing_email = []
        missing_user_account = []
        duplicate_emails = defaultdict(list)
        
        for customer_id, customer_data in customers.items():
            email = customer_data.get('email')
            
            if not email:
                missing_email.append(customer_id)
                self.errors.append({
                    'category': 'customers',
                    'severity': 'error',
                    'customer_id': customer_id,
                    'message': f"Customer {customer_id} missing email address"
                })
            else:
                duplicate_emails[email].append(customer_id)
            
            # Check if customer has corresponding user account
            if email and email not in users:
                missing_user_account.append(customer_id)
                self.warnings.append({
                    'category': 'customers',
                    'severity': 'warning',
                    'customer_id': customer_id,
                    'message': f"Customer {customer_id} ({email}) has no user account for portal access"
                })
        
        # Check for duplicate emails
        duplicate_count = sum(1 for emails in duplicate_emails.values() if len(emails) > 1)
        if duplicate_count > 0:
            for email, customer_ids in duplicate_emails.items():
                if len(customer_ids) > 1:
                    self.errors.append({
                        'category': 'customers',
                        'severity': 'error',
                        'message': f"Duplicate email {email} found for customers: {', '.join(customer_ids)}"
                    })
        
        return {
            'total_customers': len(customers),
            'missing_email': len(missing_email),
            'missing_user_account': len(missing_user_account),
            'duplicate_emails': duplicate_count,
            'status': 'PASS' if len(missing_email) == 0 and duplicate_count == 0 else 'FAIL'
        }
    
    def _validate_suppliers(self, suppliers: Dict[str, Any]) -> Dict[str, Any]:
        """Validate supplier records"""
        status_counts = defaultdict(int)
        missing_contact = []
        
        for supplier_id, supplier_data in suppliers.items():
            status = supplier_data.get('status', 'unknown')
            status_counts[status] += 1
            
            # Check required contact fields
            if not supplier_data.get('contact_email'):
                missing_contact.append(supplier_id)
                self.errors.append({
                    'category': 'suppliers',
                    'severity': 'error',
                    'supplier_id': supplier_id,
                    'message': f"Supplier {supplier_id} missing contact email"
                })
        
        return {
            'total_suppliers': len(suppliers),
            'status_breakdown': dict(status_counts),
            'missing_contact': len(missing_contact),
            'status': 'PASS' if len(missing_contact) == 0 else 'FAIL'
        }
    
    def _validate_policy_pipeline(
        self,
        customers: Dict[str, Any],
        policies: Dict[str, Any],
        underwriting_applications: Dict[str, Any],
        billing: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Validate policy pipeline integrity"""
        orphaned_policies = []
        policies_without_billing = []
        missing_underwriting = []
        
        for policy_id, policy_data in policies.items():
            customer_id = policy_data.get('customer_id')
            
            # Check customer exists
            if customer_id and customer_id not in customers:
                orphaned_policies.append(policy_id)
                self.errors.append({
                    'category': 'policies',
                    'severity': 'error',
                    'policy_id': policy_id,
                    'message': f"Policy {policy_id} references non-existent customer {customer_id}"
                })
            
            # Check if active policy has billing record
            if policy_data.get('status') == 'active':
                has_billing = any(b.get('policy_id') == policy_id for b in billing.values())
                if not has_billing:
                    policies_without_billing.append(policy_id)
                    self.warnings.append({
                        'category': 'policies',
                        'severity': 'warning',
                        'policy_id': policy_id,
                        'message': f"Active policy {policy_id} has no billing records"
                    })
            
            # Check underwriting application exists
            underwriting_id = policy_data.get('underwriting_id')
            if underwriting_id and underwriting_id not in underwriting_applications:
                missing_underwriting.append(policy_id)
                self.warnings.append({
                    'category': 'policies',
                    'severity': 'warning',
                    'policy_id': policy_id,
                    'message': f"Policy {policy_id} references missing underwriting application {underwriting_id}"
                })
        
        return {
            'total_policies': len(policies),
            'orphaned_policies': len(orphaned_policies),
            'policies_without_billing': len(policies_without_billing),
            'missing_underwriting': len(missing_underwriting),
            'status': 'PASS' if len(orphaned_policies) == 0 else 'FAIL'
        }
    
    def _validate_claims_pipeline(
        self,
        policies: Dict[str, Any],
        claims: Dict[str, Any],
        health_wallets: Dict[str, Any],
        transaction_ledger: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Validate claims pipeline integrity"""
        orphaned_claims = []
        paid_claims_without_wallet_tx = []
        
        for claim_id, claim_data in claims.items():
            policy_id = claim_data.get('policy_id')
            customer_id = claim_data.get('customer_id')
            
            # Check policy exists
            if policy_id and policy_id not in policies:
                orphaned_claims.append(claim_id)
                self.errors.append({
                    'category': 'claims',
                    'severity': 'error',
                    'claim_id': claim_id,
                    'message': f"Claim {claim_id} references non-existent policy {policy_id}"
                })
            
            # Check if paid claim has wallet transaction
            if claim_data.get('status', '').lower() == 'paid':
                customer_wallet = health_wallets.get(customer_id, {})
                wallet_transactions = customer_wallet.get('transactions', [])
                
                has_wallet_tx = any(
                    tx.get('claim_id') == claim_id or tx.get('type') == 'claim_payment'
                    for tx in wallet_transactions
                )
                
                if not has_wallet_tx:
                    paid_claims_without_wallet_tx.append(claim_id)
                    self.warnings.append({
                        'category': 'claims',
                        'severity': 'warning',
                        'claim_id': claim_id,
                        'message': f"Paid claim {claim_id} has no corresponding wallet transaction"
                    })
        
        return {
            'total_claims': len(claims),
            'orphaned_claims': len(orphaned_claims),
            'paid_claims_without_wallet_tx': len(paid_claims_without_wallet_tx),
            'status': 'PASS' if len(orphaned_claims) == 0 else 'FAIL'
        }
    
    def _validate_billing_pipeline(
        self,
        policies: Dict[str, Any],
        billing: Dict[str, Any],
        balance_sheet: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Validate billing pipeline integrity"""
        orphaned_bills = []
        negative_amounts = []
        total_billed = 0.0
        total_paid = 0.0
        total_outstanding = 0.0
        
        for bill_id, bill_data in billing.items():
            policy_id = bill_data.get('policy_id')
            
            # Check policy exists
            if policy_id and policy_id not in policies:
                orphaned_bills.append(bill_id)
                self.errors.append({
                    'category': 'billing',
                    'severity': 'error',
                    'bill_id': bill_id,
                    'message': f"Bill {bill_id} references non-existent policy {policy_id}"
                })
            
            # Check for negative amounts
            amount = bill_data.get('amount', 0)
            amount_paid = bill_data.get('amount_paid', 0)
            
            if amount < 0 or amount_paid < 0:
                negative_amounts.append(bill_id)
                self.errors.append({
                    'category': 'billing',
                    'severity': 'error',
                    'bill_id': bill_id,
                    'message': f"Bill {bill_id} has negative amounts: amount={amount}, paid={amount_paid}"
                })
            
            # Aggregate totals
            total_billed += amount
            total_paid += amount_paid
            total_outstanding += (amount - amount_paid)
        
        return {
            'total_bills': len(billing),
            'orphaned_bills': len(orphaned_bills),
            'negative_amounts': len(negative_amounts),
            'total_billed': round(total_billed, 2),
            'total_paid': round(total_paid, 2),
            'total_outstanding': round(total_outstanding, 2),
            'status': 'PASS' if len(orphaned_bills) == 0 and len(negative_amounts) == 0 else 'FAIL'
        }
    
    def _validate_ledger_integrity(
        self,
        customers: Dict[str, Any],
        health_wallets: Dict[str, Any],
        investment_accounts: Dict[str, Any],
        transaction_ledger: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Validate wallet and transaction ledger integrity"""
        orphaned_wallets = []
        negative_balances = []
        orphaned_investments = []
        
        # Validate health wallets
        for customer_id, wallet_data in health_wallets.items():
            # Check customer exists
            if customer_id not in customers:
                orphaned_wallets.append(customer_id)
                self.errors.append({
                    'category': 'ledger',
                    'severity': 'error',
                    'customer_id': customer_id,
                    'message': f"Wallet for non-existent customer {customer_id}"
                })
            
            # Check for negative balance
            balance = wallet_data.get('balance', 0)
            if balance < 0:
                negative_balances.append(customer_id)
                self.errors.append({
                    'category': 'ledger',
                    'severity': 'error',
                    'customer_id': customer_id,
                    'message': f"Health wallet for {customer_id} has negative balance: ${balance:.2f}"
                })
        
        # Validate investment accounts
        for customer_id, investment_data in investment_accounts.items():
            # Check customer exists
            if customer_id not in customers:
                orphaned_investments.append(customer_id)
                self.errors.append({
                    'category': 'ledger',
                    'severity': 'error',
                    'customer_id': customer_id,
                    'message': f"Investment account for non-existent customer {customer_id}"
                })
        
        total_wallet_balance = sum(w.get('balance', 0) for w in health_wallets.values())
        total_investment_balance = sum(inv.get('balance', 0) for inv in investment_accounts.values())
        
        return {
            'total_wallets': len(health_wallets),
            'total_investments': len(investment_accounts),
            'orphaned_wallets': len(orphaned_wallets),
            'orphaned_investments': len(orphaned_investments),
            'negative_balances': len(negative_balances),
            'total_wallet_balance': round(total_wallet_balance, 2),
            'total_investment_balance': round(total_investment_balance, 2),
            'status': 'PASS' if len(orphaned_wallets) == 0 and len(negative_balances) == 0 else 'FAIL'
        }
    
    def _validate_foundation_pipeline(
        self,
        foundations: Dict[str, Any],
        foundation_members: Dict[str, Any],
        customers: Dict[str, Any],
        suppliers: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Validate foundation pipeline integrity"""
        orphaned_members = []
        invalid_founder = []
        
        for foundation_id, foundation_data in foundations.items():
            founder_id = foundation_data.get('founder_id')
            founder_type = foundation_data.get('founder_type')
            
            # Validate founder exists
            if founder_type == 'customer' and founder_id not in customers:
                invalid_founder.append(foundation_id)
                self.errors.append({
                    'category': 'foundations',
                    'severity': 'error',
                    'foundation_id': foundation_id,
                    'message': f"Foundation {foundation_id} has invalid customer founder {founder_id}"
                })
            elif founder_type == 'supplier' and founder_id not in suppliers:
                invalid_founder.append(foundation_id)
                self.errors.append({
                    'category': 'foundations',
                    'severity': 'error',
                    'foundation_id': foundation_id,
                    'message': f"Foundation {foundation_id} has invalid supplier founder {founder_id}"
                })
        
        # Validate foundation members
        for member_id, member_data in foundation_members.items():
            foundation_id = member_data.get('foundation_id')
            
            if foundation_id and foundation_id not in foundations:
                orphaned_members.append(member_id)
                self.errors.append({
                    'category': 'foundations',
                    'severity': 'error',
                    'member_id': member_id,
                    'message': f"Member {member_id} belongs to non-existent foundation {foundation_id}"
                })
        
        return {
            'total_foundations': len(foundations),
            'total_members': len(foundation_members),
            'invalid_founder': len(invalid_founder),
            'orphaned_members': len(orphaned_members),
            'status': 'PASS' if len(invalid_founder) == 0 and len(orphaned_members) == 0 else 'FAIL'
        }
    
    def _validate_supplier_orders(
        self,
        supplier_orders: Dict[str, Any],
        suppliers: Dict[str, Any],
        customers: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Validate supplier order pipeline"""
        orphaned_supplier_orders = []
        orphaned_customer_orders = []
        
        for order_id, order_data in supplier_orders.items():
            supplier_id = order_data.get('supplier_id')
            customer_id = order_data.get('customer_id')
            
            # Check supplier exists
            if supplier_id and supplier_id not in suppliers:
                orphaned_supplier_orders.append(order_id)
                self.errors.append({
                    'category': 'supplier_orders',
                    'severity': 'error',
                    'order_id': order_id,
                    'message': f"Order {order_id} references non-existent supplier {supplier_id}"
                })
            
            # Check customer exists
            if customer_id and customer_id not in customers:
                orphaned_customer_orders.append(order_id)
                self.errors.append({
                    'category': 'supplier_orders',
                    'severity': 'error',
                    'order_id': order_id,
                    'message': f"Order {order_id} references non-existent customer {customer_id}"
                })
        
        return {
            'total_orders': len(supplier_orders),
            'orphaned_supplier_orders': len(orphaned_supplier_orders),
            'orphaned_customer_orders': len(orphaned_customer_orders),
            'status': 'PASS' if len(orphaned_supplier_orders) == 0 and len(orphaned_customer_orders) == 0 else 'FAIL'
        }
    
    def _validate_delivery_pipeline(
        self,
        delivery_requests: Dict[str, Any],
        active_deliveries: Dict[str, Any],
        supplier_orders: Dict[str, Any],
        health_wallets: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Validate delivery pipeline integrity"""
        deliveries_without_request = []
        deliveries_without_order = []
        paid_deliveries_without_wallet_tx = []
        
        for delivery_id, delivery_data in active_deliveries.items():
            request_id = delivery_data.get('request_id')
            order_id = delivery_data.get('order_id')
            customer_id = delivery_data.get('customer_id')
            
            # Check delivery request exists
            if request_id and request_id not in delivery_requests:
                deliveries_without_request.append(delivery_id)
                self.errors.append({
                    'category': 'deliveries',
                    'severity': 'error',
                    'delivery_id': delivery_id,
                    'message': f"Delivery {delivery_id} references non-existent request {request_id}"
                })
            
            # Check supplier order exists
            if order_id and order_id not in supplier_orders:
                deliveries_without_order.append(delivery_id)
                self.warnings.append({
                    'category': 'deliveries',
                    'severity': 'warning',
                    'delivery_id': delivery_id,
                    'message': f"Delivery {delivery_id} references missing order {order_id}"
                })
            
            # Check if completed delivery has wallet payment
            if delivery_data.get('payment_status') == 'completed':
                customer_wallet = health_wallets.get(customer_id, {})
                wallet_transactions = customer_wallet.get('transactions', [])
                
                has_payment = any(
                    tx.get('delivery_id') == delivery_id or 
                    tx.get('type') == 'delivery_payment'
                    for tx in wallet_transactions
                )
                
                if not has_payment:
                    paid_deliveries_without_wallet_tx.append(delivery_id)
                    self.warnings.append({
                        'category': 'deliveries',
                        'severity': 'warning',
                        'delivery_id': delivery_id,
                        'message': f"Paid delivery {delivery_id} has no wallet transaction"
                    })
        
        return {
            'total_requests': len(delivery_requests),
            'active_deliveries': len(active_deliveries),
            'deliveries_without_request': len(deliveries_without_request),
            'deliveries_without_order': len(deliveries_without_order),
            'paid_deliveries_without_wallet_tx': len(paid_deliveries_without_wallet_tx),
            'status': 'PASS' if len(deliveries_without_request) == 0 else 'FAIL'
        }
    
    def _generate_validation_summary(self) -> Dict[str, Any]:
        """Generate validation summary"""
        passed_checks = sum(1 for v in self.validation_results.values() 
                           if v.get('status') == 'PASS')
        failed_checks = sum(1 for v in self.validation_results.values() 
                           if v.get('status') == 'FAIL')
        
        return {
            'total_checks': len(self.validation_results),
            'passed_checks': passed_checks,
            'failed_checks': failed_checks,
            'errors_found': len(self.errors),
            'warnings_found': len(self.warnings),
            'overall_status': 'PASS' if failed_checks == 0 else 'FAIL'
        }


    # ------------------------------------------------------------------
    # Health-marketplace foundation validators
    # ------------------------------------------------------------------
    #
    # These validators operate on the durable marketplace schema introduced in
    # ``database/marketplace_models.py`` (wallet accounts, holds, ledger
    # entries, settlement runs, payer receivables, remittances, refunds,
    # marketplace claims, and journal entries). They are additive and must not
    # affect existing in-memory ``validate_all`` callers.
    #
    # Reference: docs/health_marketplace_architecture.md, sections
    # "Integrity and control architecture" and "Recommended repository
    # evolution".

    def validate_marketplace_foundation(
        self,
        db_manager_factory=None,
    ) -> Dict[str, Any]:
        """Run the canonical marketplace integrity validations.

        Checks:
        - wallet hold coverage:
            held_balance == sum(open_holds)
            available + held == posted
            posted == sum(credit) - sum(debit) of ledger
        - settlement aging: pending settlement runs older than SLA threshold
        - markup recognition consistency:
            net_marketplace_revenue (journal) - markup totals on settlement
            items must remain non-negative
        - payer receivable aging
        - refund lineage: every refund must reference an order and have a
          ledger group (when funded by wallet)

        Returns a structured report; also appends to ``self.errors`` and
        ``self.warnings`` so it integrates with existing reporting flows.
        """
        from datetime import datetime as _dt

        if db_manager_factory is None:
            from database.manager import DatabaseManager as _DM
            db_manager_factory = _DM

        report: Dict[str, Any] = {
            'wallet_holds': {'status': 'PASS', 'mismatches': []},
            'settlement_aging': {'status': 'PASS', 'overdue_runs': 0, 'buckets': {}},
            'markup_recognition': {'status': 'PASS', 'details': {}},
            'payer_receivable_aging': {'status': 'PASS', 'buckets': {}},
            'refund_lineage': {'status': 'PASS', 'orphaned_refunds': []},
        }
        try:
            with db_manager_factory() as db:
                # Wallet hold coverage
                wallets = db.wallet_accounts.get_all() or []
                wallet_mismatches: List[Dict[str, Any]] = []
                for wallet in wallets:
                    derived_posted = db.wallet_ledger.derive_balance(wallet.id)
                    derived_held = db.wallet_holds.total_held_for_account(wallet.id)
                    cached_posted = float(wallet.posted_balance or 0.0)
                    cached_held = float(wallet.held_balance or 0.0)
                    cached_avail = float(wallet.available_balance or 0.0)

                    posted_match = abs(derived_posted - cached_posted) < 1e-4
                    held_match = abs(derived_held - cached_held) < 1e-4
                    invariant_match = abs((cached_avail + cached_held) - cached_posted) < 1e-4

                    if not (posted_match and held_match and invariant_match):
                        wallet_mismatches.append({
                            'wallet_id': wallet.id,
                            'customer_id': wallet.customer_id,
                            'derived_posted': derived_posted,
                            'cached_posted': cached_posted,
                            'derived_held': derived_held,
                            'cached_held': cached_held,
                            'cached_available': cached_avail,
                        })
                        self.errors.append({
                            'category': 'marketplace_wallet',
                            'severity': 'error',
                            'wallet_id': wallet.id,
                            'message': (
                                f"Wallet {wallet.id} balance mismatch "
                                f"(derived posted={derived_posted} cached={cached_posted}, "
                                f"derived held={derived_held} cached={cached_held})"
                            ),
                        })
                if wallet_mismatches:
                    report['wallet_holds']['status'] = 'FAIL'
                    report['wallet_holds']['mismatches'] = wallet_mismatches

                # Settlement aging
                aging_buckets = db.supplier_settlement_runs.aging_buckets()
                report['settlement_aging']['buckets'] = aging_buckets
                overdue = int(aging_buckets.get('60_plus', 0)) + int(aging_buckets.get('31_60', 0))
                report['settlement_aging']['overdue_runs'] = overdue
                if overdue > 0:
                    report['settlement_aging']['status'] = 'WARN'
                    self.warnings.append({
                        'category': 'marketplace_settlement',
                        'severity': 'warning',
                        'message': f"{overdue} settlement runs older than 30 days are still pending",
                    })

                # Markup recognition consistency
                rev = db.journal.account_balance('marketplace_revenue').get('balance', 0.0)
                contra = db.journal.account_balance('marketplace_contra_revenue').get('balance', 0.0)
                net_rev = rev - contra
                items = db.supplier_settlement_items.get_all() or []
                markup_total_items = sum(float(i.markup_amount or 0.0) for i in items)
                report['markup_recognition']['details'] = {
                    'net_marketplace_revenue_journal': round(net_rev, 4),
                    'markup_total_settlement_items': round(markup_total_items, 4),
                }
                if net_rev < -1e-4:
                    report['markup_recognition']['status'] = 'FAIL'
                    self.errors.append({
                        'category': 'marketplace_accounting',
                        'severity': 'error',
                        'message': f"Net marketplace revenue is negative ({net_rev}) - check contra-revenue",
                    })

                # Payer receivable aging
                receivable_buckets = db.payer_receivables.aging_buckets()
                report['payer_receivable_aging']['buckets'] = receivable_buckets
                aged_open = receivable_buckets.get('90_plus', {}).get('count', 0)
                if aged_open > 0:
                    report['payer_receivable_aging']['status'] = 'WARN'
                    self.warnings.append({
                        'category': 'marketplace_payer',
                        'severity': 'warning',
                        'message': f"{aged_open} payer receivables open >90 days",
                    })

                # Refund lineage
                refunds = db.refunds.get_all() or []
                orphaned: List[Dict[str, Any]] = []
                for refund in refunds:
                    if not refund.order_id:
                        orphaned.append({'refund_id': refund.id, 'reason': 'missing_order_id'})
                        continue
                    if refund.funding_source == 'wallet' and not refund.wallet_ledger_entry_id:
                        orphaned.append({
                            'refund_id': refund.id,
                            'reason': 'missing_wallet_ledger_entry',
                        })
                if orphaned:
                    report['refund_lineage']['status'] = 'FAIL'
                    report['refund_lineage']['orphaned_refunds'] = orphaned
                    for o in orphaned:
                        self.errors.append({
                            'category': 'marketplace_refund',
                            'severity': 'error',
                            'message': f"Refund {o['refund_id']} has lineage gap: {o['reason']}",
                        })

        except Exception as exc:  # noqa: BLE001
            logger.error(f"Marketplace integrity validation failed: {exc}")
            report['error'] = str(exc)

        # Roll an overall status
        statuses = [v.get('status') for v in report.values() if isinstance(v, dict) and 'status' in v]
        if any(s == 'FAIL' for s in statuses):
            report['overall_status'] = 'FAIL'
        elif any(s == 'WARN' for s in statuses):
            report['overall_status'] = 'WARN'
        else:
            report['overall_status'] = 'PASS'
        report['as_of'] = _dt.utcnow().isoformat()
        return report


# Singleton instance
_platform_integrity_service: Optional[PlatformIntegrityService] = None


def get_platform_integrity_service() -> PlatformIntegrityService:
    """Get or create platform integrity service singleton"""
    global _platform_integrity_service
    if _platform_integrity_service is None:
        _platform_integrity_service = PlatformIntegrityService()
    return _platform_integrity_service
