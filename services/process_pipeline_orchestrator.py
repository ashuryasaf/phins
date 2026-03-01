"""
PHINS Process Pipeline Orchestrator
====================================
Unified orchestration layer for all cross-cutting processes:

  Customer Health Wallet -> Supply Chain -> Delivery Allocation ->
  Claims Automation -> Billing Automation -> Data Integrity Validation

Key Capabilities:
1. Health Wallet Pipeline - validates wallet funding, allocation, and spend integrity
2. Supply Chain Pipeline - validates supplier onboarding, offers, and marketplace integrity
3. Delivery Allocation Pipeline - validates bid selection, payment, and fulfillment
4. Claims Automation Pipeline - automates claim intake, fraud check, and payout routing
5. Billing Automation Pipeline - automates bill generation, payment, and premium split
6. Marketplace Supply Validation - validates new supplies entering the marketplace
7. Cross-Pipeline Data Integrity - ensures consistency across all subsystems
"""

import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field, asdict
from enum import Enum


class PipelineStage(str, Enum):
    HEALTH_WALLET = "health_wallet"
    SUPPLY_CHAIN = "supply_chain"
    DELIVERY = "delivery"
    CLAIMS = "claims"
    BILLING = "billing"
    MARKETPLACE = "marketplace"


class ValidationSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class SupplyValidationStatus(str, Enum):
    PENDING = "pending"
    UNDER_REVIEW = "under_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    REQUIRES_DOCUMENTATION = "requires_documentation"


@dataclass
class PipelineValidationResult:
    stage: str
    is_valid: bool
    score: float
    issues: List[Dict[str, Any]] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class MarketplaceSupplyValidation:
    """Validation record for new supplies entering the marketplace"""
    validation_id: str
    supplier_id: str
    offer_id: str
    offer_name: str
    category: str
    item_type: str
    price: float
    status: str = SupplyValidationStatus.PENDING.value
    compliance_checks: Dict[str, bool] = field(default_factory=dict)
    quality_score: float = 0.0
    risk_score: float = 0.0
    reviewer_notes: str = ""
    auto_approved: bool = False
    submitted_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    reviewed_at: Optional[str] = None
    data_hash: str = ""

    def compute_hash(self) -> str:
        data_str = f"{self.supplier_id}:{self.offer_id}:{self.price}:{self.category}"
        self.data_hash = hashlib.sha256(data_str.encode()).hexdigest()[:16]
        return self.data_hash

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class CrossPipelineIntegrityReport:
    """Full cross-pipeline integrity report"""
    report_id: str
    generated_at: str
    overall_score: float
    overall_status: str
    stage_results: Dict[str, PipelineValidationResult] = field(default_factory=dict)
    cross_pipeline_issues: List[Dict[str, Any]] = field(default_factory=list)
    data_integrity_hash: str = ""
    recommendations: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict:
        result = asdict(self)
        result['stage_results'] = {
            k: v.to_dict() if hasattr(v, 'to_dict') else v
            for k, v in self.stage_results.items()
        }
        return result


class ProcessPipelineOrchestrator:
    """
    Orchestrates validation and automation across all PHINS subsystems.

    Provides:
    - End-to-end pipeline validation
    - Marketplace supply validation for new offerings
    - Automated claims-to-billing flow
    - Health wallet integrity across supply chain and delivery
    - Cross-pipeline data integrity checks
    """

    def __init__(self,
                 policies: Dict = None,
                 customers: Dict = None,
                 claims: Dict = None,
                 billing: Dict = None,
                 health_wallets: Dict = None,
                 investment_accounts: Dict = None,
                 transaction_ledger: Dict = None,
                 suppliers: Dict = None,
                 supplier_offers: Dict = None,
                 supplier_orders: Dict = None,
                 supply_chain_ledger: Dict = None,
                 nft_ledger: Dict = None,
                 underwriting_apps: Dict = None,
                 pipeline_integrity_service=None,
                 supply_chain_service=None,
                 delivery_service=None,
                 billing_service=None,
                 data_integrity_service=None,
                 savings_pipeline_service=None):

        self.policies = policies or {}
        self.customers = customers or {}
        self.claims = claims or {}
        self.billing = billing or {}
        self.health_wallets = health_wallets or {}
        self.investment_accounts = investment_accounts or {}
        self.transaction_ledger = transaction_ledger or {}
        self.suppliers = suppliers or {}
        self.supplier_offers = supplier_offers or {}
        self.supplier_orders = supplier_orders or {}
        self.supply_chain_ledger = supply_chain_ledger or {}
        self.nft_ledger = nft_ledger or {}
        self.underwriting_apps = underwriting_apps or {}

        self.pipeline_integrity = pipeline_integrity_service
        self.supply_chain = supply_chain_service
        self.delivery = delivery_service
        self.billing_service = billing_service
        self.data_integrity = data_integrity_service
        self.savings_pipeline = savings_pipeline_service

        self.supply_validations: Dict[str, MarketplaceSupplyValidation] = {}
        self.automation_log: List[Dict[str, Any]] = []

        self.MEDICAL_CATEGORIES = {"medical", "pharmacy", "laboratory", "equipment", "wellness", "health"}
        self.REGULATED_CATEGORIES = {"medical", "pharmacy", "legal", "financial"}
        self.AUTO_APPROVE_PRICE_LIMIT = 5000.0
        self.MIN_SUPPLIER_RATING_FOR_AUTO_APPROVE = 4.0

    # =========================================================================
    # 1. HEALTH WALLET PIPELINE VALIDATION
    # =========================================================================

    def validate_health_wallet_pipeline(self, customer_id: str) -> PipelineValidationResult:
        """
        Validate health wallet funding, allocation, and spend integrity.

        Checks:
        - Wallet balance >= 0
        - All wallet transactions have valid references
        - Wallet spend matches supply chain/delivery order records
        - Premium allocation flows correctly to wallet
        """
        issues = []
        score = 100.0

        wallet = self.health_wallets.get(customer_id, {})
        if not wallet:
            return PipelineValidationResult(
                stage=PipelineStage.HEALTH_WALLET.value,
                is_valid=True,
                score=100.0,
                metadata={"status": "no_wallet"}
            )

        balance = float(wallet.get('balance', 0))

        if balance < 0:
            issues.append({
                'severity': ValidationSeverity.CRITICAL.value,
                'field': 'balance',
                'message': f'Negative wallet balance: ${balance:.2f}',
                'auto_fixable': False
            })
            score -= 30

        transactions = wallet.get('transactions', [])
        tx_total = sum(float(tx.get('amount', 0)) for tx in transactions)
        initial_balance = float(wallet.get('initial_balance', 0))
        expected_balance = initial_balance + tx_total

        if abs(expected_balance - balance) > 0.01 and transactions:
            issues.append({
                'severity': ValidationSeverity.WARNING.value,
                'field': 'transaction_reconciliation',
                'message': f'Wallet balance ${balance:.2f} does not match transaction history (expected ${expected_balance:.2f})',
                'auto_fixable': True
            })
            score -= 10

        order_debits = [tx for tx in transactions if tx.get('type') in ('order_payment', 'delivery_payment')]
        for debit in order_debits:
            order_id = debit.get('order_id')
            if order_id and order_id not in self.supplier_orders:
                delivery_ref = debit.get('delivery_request_id')
                if not delivery_ref:
                    issues.append({
                        'severity': ValidationSeverity.WARNING.value,
                        'field': 'orphan_transaction',
                        'message': f'Wallet transaction references non-existent order: {order_id}',
                        'auto_fixable': False
                    })
                    score -= 5

        recommendations = []
        if balance > 0 and balance < 100:
            recommendations.append("Health wallet balance is low. Consider topping up before marketplace purchases.")
        if not transactions:
            recommendations.append("No wallet activity yet. Health wallet is funded from premium savings allocation.")

        return PipelineValidationResult(
            stage=PipelineStage.HEALTH_WALLET.value,
            is_valid=len([i for i in issues if i['severity'] == ValidationSeverity.CRITICAL.value]) == 0,
            score=max(0, score),
            issues=issues,
            recommendations=recommendations,
            metadata={
                'balance': balance,
                'transaction_count': len(transactions),
                'total_debits': sum(abs(float(tx.get('amount', 0))) for tx in transactions if float(tx.get('amount', 0)) < 0),
                'total_credits': sum(float(tx.get('amount', 0)) for tx in transactions if float(tx.get('amount', 0)) > 0)
            }
        )

    # =========================================================================
    # 2. SUPPLY CHAIN PIPELINE VALIDATION
    # =========================================================================

    def validate_supply_chain_pipeline(self) -> PipelineValidationResult:
        """
        Validate supply chain integrity: suppliers, offers, orders, ledger.

        Checks:
        - All approved suppliers have valid invitation codes
        - Active offers belong to approved suppliers
        - Order amounts match offer prices * quantity
        - Commission calculations are correct
        - Ledger entries have valid hash chains
        """
        issues = []
        score = 100.0

        for sup_id, supplier in self.suppliers.items():
            status = supplier.get('status', '')
            if status == 'approved' and not supplier.get('invitation_code'):
                issues.append({
                    'severity': ValidationSeverity.WARNING.value,
                    'entity': 'supplier',
                    'id': sup_id,
                    'message': f'Approved supplier {sup_id} missing invitation code'
                })
                score -= 3

        for offer_id, offer in self.supplier_offers.items():
            price = float(offer.get('price', 0))
            if price <= 0 and offer.get('active'):
                issues.append({
                    'severity': ValidationSeverity.WARNING.value,
                    'entity': 'offer',
                    'id': offer_id,
                    'message': f'Active offer {offer_id} has zero or negative price'
                })
                score -= 5

        core_integrity_delegated = False
        if self.pipeline_integrity and hasattr(self.pipeline_integrity, 'validate_supply_chain_integrity'):
            try:
                integrity_result = self.pipeline_integrity.validate_supply_chain_integrity(
                    self.suppliers,
                    self.supplier_offers,
                    self.supplier_orders,
                    self.health_wallets
                )
                for integrity_issue in integrity_result.get('issues', []):
                    field = integrity_issue.get('field')
                    description = integrity_issue.get('description', '')

                    if field == 'offer_supplier_status':
                        offer_id = ''
                        if description.startswith('Active offer '):
                            offer_id = description.split(' ', 3)[2]
                        issue = {
                            'severity': ValidationSeverity.ERROR.value,
                            'entity': 'offer',
                            'message': description
                        }
                        if offer_id:
                            issue['id'] = offer_id
                        issues.append(issue)
                        score -= 10

                    elif field == 'order_financials':
                        order_id = ''
                        if description.startswith('Order '):
                            order_id = description.split(' ', 2)[1].rstrip(':')
                        issue = {
                            'severity': ValidationSeverity.ERROR.value,
                            'entity': 'order',
                            'message': description
                        }
                        if order_id:
                            issue['id'] = order_id
                        issues.append(issue)
                        score -= 8

                core_integrity_delegated = True
            except Exception:
                core_integrity_delegated = False

        if not core_integrity_delegated:
            for offer_id, offer in self.supplier_offers.items():
                sup_id = offer.get('supplier_id')
                supplier = self.suppliers.get(sup_id, {})
                if offer.get('active') and supplier.get('status') != 'approved':
                    issues.append({
                        'severity': ValidationSeverity.ERROR.value,
                        'entity': 'offer',
                        'id': offer_id,
                        'message': f'Active offer {offer_id} belongs to non-approved supplier {sup_id}'
                    })
                    score -= 10

            for order_id, order in self.supplier_orders.items():
                total = float(order.get('total_amount', 0))
                commission = float(order.get('commission', 0))
                payout = float(order.get('supplier_payout', 0))

                if total > 0 and abs((commission + payout) - total) > 1.0:
                    issues.append({
                        'severity': ValidationSeverity.ERROR.value,
                        'entity': 'order',
                        'id': order_id,
                        'message': f'Order {order_id} financial mismatch: commission(${commission:.2f}) + payout(${payout:.2f}) != total(${total:.2f})'
                    })
                    score -= 8

        if self.supply_chain:
            try:
                ledger_result = self.supply_chain.verify_ledger_integrity()
                ledger_score = ledger_result.get('integrity_score', 100)
                if ledger_score < 100:
                    issues.append({
                        'severity': ValidationSeverity.ERROR.value,
                        'entity': 'ledger',
                        'message': f'Supply chain ledger integrity: {ledger_score:.1f}%'
                    })
                    score -= (100 - ledger_score) * 0.3
            except Exception:
                pass

        return PipelineValidationResult(
            stage=PipelineStage.SUPPLY_CHAIN.value,
            is_valid=len([i for i in issues if i['severity'] in (ValidationSeverity.CRITICAL.value, ValidationSeverity.ERROR.value)]) == 0,
            score=max(0, score),
            issues=issues,
            metadata={
                'total_suppliers': len(self.suppliers),
                'approved_suppliers': len([s for s in self.suppliers.values() if s.get('status') == 'approved']),
                'active_offers': len([o for o in self.supplier_offers.values() if o.get('active')]),
                'total_orders': len(self.supplier_orders)
            }
        )

    # =========================================================================
    # 3. DELIVERY ALLOCATION PIPELINE VALIDATION
    # =========================================================================

    def validate_delivery_pipeline(self) -> PipelineValidationResult:
        """
        Validate delivery bidding, allocation, and fulfillment integrity.
        """
        issues = []
        score = 100.0

        if not self.delivery:
            return PipelineValidationResult(
                stage=PipelineStage.DELIVERY.value,
                is_valid=True,
                score=100.0,
                metadata={"status": "service_not_initialized"}
            )

        requests = self.delivery.delivery_requests
        bids = self.delivery.delivery_bids

        for req_id, req in requests.items():
            if hasattr(req, 'status'):
                status = req.status
                if status == DeliveryStatus.BID_SELECTED and not req.selected_bid_id:
                    issues.append({
                        'severity': ValidationSeverity.ERROR.value,
                        'entity': 'delivery_request',
                        'id': req_id,
                        'message': f'Request {req_id} marked as bid_selected but no bid_id set'
                    })
                    score -= 10

                if req.selected_bid_id:
                    bid = bids.get(req.selected_bid_id)
                    if bid and hasattr(bid, 'bid_price') and bid.bid_price < 0:
                        issues.append({
                            'severity': ValidationSeverity.CRITICAL.value,
                            'entity': 'delivery_bid',
                            'id': req.selected_bid_id,
                            'message': f'Selected bid has negative price: ${bid.bid_price}'
                        })
                        score -= 20

        for bid_id, bid in bids.items():
            if hasattr(bid, 'status') and bid.status == BidStatus.ACCEPTED:
                req = requests.get(bid.request_id)
                if req and hasattr(req, 'selected_bid_id') and req.selected_bid_id != bid_id:
                    issues.append({
                        'severity': ValidationSeverity.WARNING.value,
                        'entity': 'delivery_bid',
                        'id': bid_id,
                        'message': f'Bid {bid_id} marked accepted but not selected on request {bid.request_id}'
                    })
                    score -= 5

        try:
            from services.delivery_bidding_service import BidStatus as _BS, DeliveryStatus as _DS
        except ImportError:
            pass

        return PipelineValidationResult(
            stage=PipelineStage.DELIVERY.value,
            is_valid=len([i for i in issues if i['severity'] == ValidationSeverity.CRITICAL.value]) == 0,
            score=max(0, score),
            issues=issues,
            metadata={
                'total_requests': len(requests),
                'total_bids': len(bids),
                'open_requests': len([r for r in requests.values() if hasattr(r, 'status') and r.status.value == 'bidding_open']),
            }
        )

    # =========================================================================
    # 4. CLAIMS AUTOMATION PIPELINE
    # =========================================================================

    def automate_claim_processing(self, claim_id: str) -> Dict[str, Any]:
        """
        Automate claim processing through the pipeline:
        1. Validate claim data completeness
        2. Cross-reference with policy and underwriting
        3. Run fraud probability check
        4. Route to appropriate handler (auto-approve, manual review, reject)
        5. If approved, trigger billing/payment pipeline
        """
        claim = self.claims.get(claim_id)
        if not claim:
            return {'success': False, 'error': f'Claim {claim_id} not found'}
        current_status = str(claim.get('status', 'pending')).lower()
        if current_status in ('approved', 'paid'):
            return {'success': False, 'error': f'Claim {claim_id} already processed (status: {current_status})'}

        policy_id = claim.get('policy_id', '')
        customer_id = claim.get('customer_id', '')
        claim_amount = float(claim.get('amount', claim.get('claim_amount', 0)))
        policy = self.policies.get(policy_id, {})
        customer = self.customers.get(customer_id, {})

        validation_result = self._validate_claim_completeness(claim, policy, customer)
        fraud_score = self._calculate_claim_fraud_score(claim, policy, customer_id)
        coverage = float(policy.get('coverage_amount', 0))

        decision = 'pending'
        reason = ''

        if not validation_result['is_complete']:
            decision = 'requires_info'
            reason = f"Missing: {', '.join(validation_result['missing_fields'])}"
        elif fraud_score > 0.7:
            decision = 'refer_investigation'
            reason = f'High fraud probability: {fraud_score:.0%}'
        elif fraud_score > 0.4:
            decision = 'manual_review'
            reason = f'Moderate fraud probability: {fraud_score:.0%}'
        elif coverage <= 0 and claim_amount > 0:
            decision = 'manual_review'
            reason = 'Policy coverage amount missing or zero; requires manual review'
        elif coverage > 0 and claim_amount > coverage * 0.5:
            decision = 'manual_review'
            reason = f'High-value claim: ${claim_amount:,.2f} ({claim_amount/coverage*100:.0f}% of coverage)'
        elif claim_amount <= 2000 and fraud_score <= 0.2:
            decision = 'auto_approve'
            reason = f'Low-risk auto-approval: ${claim_amount:,.2f}, fraud score {fraud_score:.0%}'
        else:
            decision = 'manual_review'
            reason = 'Standard review required'

        self._log_automation('claim_processing', {
            'claim_id': claim_id,
            'decision': decision,
            'fraud_score': fraud_score,
            'claim_amount': claim_amount,
            'reason': reason
        })

        result = {
            'success': True,
            'claim_id': claim_id,
            'decision': decision,
            'reason': reason,
            'fraud_score': round(fraud_score, 3),
            'validation': validation_result,
            'claim_amount': claim_amount,
            'coverage_amount': coverage,
            'automation_level': 'full' if decision == 'auto_approve' else 'partial'
        }

        if decision == 'auto_approve':
            claim['status'] = 'approved'
            claim['approved_date'] = datetime.now(timezone.utc).isoformat()
            payout_result = self._process_claim_payout(claim, policy, customer_id, claim_amount)
            if payout_result.get('success') and payout_result.get('destination') == 'health_wallet':
                claim['status'] = 'paid'
                claim['paid_date'] = datetime.now(timezone.utc).isoformat()
            result['payout'] = payout_result

        return result

    def _validate_claim_completeness(self, claim: Dict, policy: Dict, customer: Dict) -> Dict[str, Any]:
        required_fields = ['policy_id', 'customer_id', 'amount', 'description']
        alt_fields = {'amount': 'claim_amount'}
        missing = []
        for f in required_fields:
            if not claim.get(f) and not claim.get(alt_fields.get(f, '')):
                missing.append(f)

        if not policy:
            missing.append('valid_policy')

        return {
            'is_complete': len(missing) == 0,
            'missing_fields': missing,
            'has_policy': bool(policy),
            'has_customer': bool(customer),
            'policy_status': policy.get('status', 'unknown'),
            'policy_active': policy.get('status', '').lower() in ('active', 'in_force')
        }

    def _calculate_claim_fraud_score(self, claim: Dict, policy: Dict, customer_id: str) -> float:
        score = 0.0

        claim_date = claim.get('date', claim.get('created_date', ''))
        policy_start = policy.get('start_date', '')
        if claim_date and policy_start:
            try:
                cd = datetime.fromisoformat(str(claim_date).replace('Z', '+00:00'))
                ps = datetime.fromisoformat(str(policy_start).replace('Z', '+00:00'))
                days_since_start = (cd - ps).days
                if 0 < days_since_start < 30:
                    score += 0.25
                elif 0 < days_since_start < 90:
                    score += 0.10
            except Exception:
                pass

        customer_claims = [c for c in self.claims.values()
                           if c.get('customer_id') == customer_id]
        if len(customer_claims) > 5:
            score += 0.15
        elif len(customer_claims) > 3:
            score += 0.08

        claim_amount = float(claim.get('amount', claim.get('claim_amount', 0)))
        coverage = float(policy.get('coverage_amount', 1))
        if coverage > 0 and claim_amount > coverage * 0.8:
            score += 0.2

        return min(1.0, score)

    def _process_claim_payout(self, claim: Dict, policy: Dict, customer_id: str, amount: float) -> Dict[str, Any]:
        destination = claim.get('payment_destination', 'health_wallet')

        if destination == 'health_wallet':
            wallet = self.health_wallets.get(customer_id)
            if wallet:
                wallet['balance'] = float(wallet.get('balance', 0)) + amount
                wallet.setdefault('transactions', []).append({
                    'id': f"CLM-PAY-{claim.get('id', claim.get('claim_id', 'unknown'))}",
                    'type': 'claim_payout',
                    'amount': amount,
                    'claim_id': claim.get('id', claim.get('claim_id')),
                    'timestamp': datetime.now(timezone.utc).isoformat()
                })
                return {
                    'success': True,
                    'destination': 'health_wallet',
                    'amount': amount,
                    'new_balance': wallet['balance']
                }

        return {
            'success': True,
            'destination': destination,
            'amount': amount,
            'status': 'queued_for_payment'
        }

    # =========================================================================
    # 5. BILLING AUTOMATION PIPELINE
    # =========================================================================

    def automate_billing_cycle(self, policy_id: str) -> Dict[str, Any]:
        """
        Automate billing for a policy:
        1. Validate policy is active and billable
        2. Calculate premium with risk/savings split
        3. Generate bill with proper allocation
        4. Route savings portion to health wallet pipeline
        5. Validate premium consistency
        """
        policy = self.policies.get(policy_id)
        if not policy:
            return {'success': False, 'error': f'Policy {policy_id} not found'}

        status = str(policy.get('status', '')).lower()
        if status not in ('active', 'in_force', 'approved'):
            return {'success': False, 'error': f'Policy {policy_id} is not active (status: {status})'}

        customer_id = policy.get('customer_id', '')
        annual_premium = float(policy.get('annual_premium', 0))
        monthly_premium = float(policy.get('monthly_premium', annual_premium / 12 if annual_premium else 0))

        hw = policy.get('health_wallet', {})
        if isinstance(hw, str):
            try:
                hw = json.loads(hw)
            except Exception:
                hw = {}
        savings_pct = float(hw.get('allocation_percentage', 25)) / 100.0
        risk_pct = 1.0 - savings_pct

        risk_amount = round(monthly_premium * risk_pct, 2)
        savings_amount = round(monthly_premium * savings_pct, 2)

        bill_id = f"BILL-AUTO-{datetime.now().strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(3).upper()}"
        now = datetime.now(timezone.utc)

        bill = {
            'bill_id': bill_id,
            'policy_id': policy_id,
            'customer_id': customer_id,
            'amount_due': monthly_premium,
            'amount_paid': 0.0,
            'status': 'outstanding',
            'due_date': (now + timedelta(days=30)).isoformat(),
            'created_date': now.isoformat(),
            'premium_breakdown': {
                'risk_amount': risk_amount,
                'risk_percentage': round(risk_pct * 100, 2),
                'savings_amount': savings_amount,
                'savings_percentage': round(savings_pct * 100, 2),
                'health_wallet_amount': savings_amount
            },
            'automation': {
                'auto_generated': True,
                'generated_at': now.isoformat(),
                'pipeline': 'billing_automation'
            }
        }

        self.billing[bill_id] = bill

        self._log_automation('billing_generation', {
            'bill_id': bill_id,
            'policy_id': policy_id,
            'amount': monthly_premium,
            'risk_amount': risk_amount,
            'savings_amount': savings_amount
        })

        return {
            'success': True,
            'bill_id': bill_id,
            'bill': bill,
            'premium_breakdown': bill['premium_breakdown'],
            'next_step': 'await_payment'
        }

    def process_billing_payment(self, bill_id: str, amount: float,
                                 payment_method: str = "auto") -> Dict[str, Any]:
        """
        Process a billing payment and route savings to health wallet.
        """
        bill = self.billing.get(bill_id)
        if not bill:
            return {'success': False, 'error': f'Bill {bill_id} not found'}

        if bill.get('status') == 'paid':
            return {'success': False, 'error': 'Bill already paid'}

        amount_due = float(bill.get('amount_due', 0))
        already_paid = float(bill.get('amount_paid', 0))
        remaining_due = max(0.0, amount_due - already_paid)
        payment_applied = min(amount, remaining_due)

        if already_paid + payment_applied < amount_due:
            bill['amount_paid'] = already_paid + payment_applied
            bill['status'] = 'partial'
        else:
            bill['amount_paid'] = amount_due
            bill['status'] = 'paid'
            if not bill.get('paid_date'):
                bill['paid_date'] = datetime.now(timezone.utc).isoformat()

        breakdown = bill.get('premium_breakdown', {})
        savings_amount = float(breakdown.get('savings_amount', 0))
        customer_id = bill.get('customer_id', '')

        wallet_credit = None
        if savings_amount > 0 and customer_id and bill['status'] == 'paid':
            wallet_credit = self._credit_health_wallet(
                customer_id, savings_amount,
                source='premium_savings',
                reference_id=bill_id
            )

        self._log_automation('billing_payment', {
            'bill_id': bill_id,
            'amount_paid': payment_applied,
            'status': bill['status'],
            'savings_routed': savings_amount if bill['status'] == 'paid' else 0
        })

        return {
            'success': True,
            'bill_id': bill_id,
            'status': bill['status'],
            'amount_paid': bill['amount_paid'],
            'wallet_credit': wallet_credit
        }

    def _credit_health_wallet(self, customer_id: str, amount: float,
                               source: str, reference_id: str) -> Dict[str, Any]:
        if customer_id not in self.health_wallets:
            self.health_wallets[customer_id] = {
                'customer_id': customer_id,
                'balance': 0.0,
                'transactions': [],
                'created_at': datetime.now(timezone.utc).isoformat()
            }

        wallet = self.health_wallets[customer_id]
        wallet['balance'] = float(wallet.get('balance', 0)) + amount
        wallet.setdefault('transactions', []).append({
            'id': f"PIPE-{secrets.token_hex(4).upper()}",
            'type': source,
            'amount': amount,
            'reference_id': reference_id,
            'timestamp': datetime.now(timezone.utc).isoformat()
        })

        return {
            'credited': True,
            'amount': amount,
            'new_balance': wallet['balance']
        }

    # =========================================================================
    # 6. MARKETPLACE SUPPLY VALIDATION
    # =========================================================================

    def validate_new_supply(self, supplier_id: str, offer_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate a new supply/offer before it enters the marketplace.

        Checks:
        - Supplier is approved and in good standing
        - Offer data is complete and valid
        - Price is within acceptable range for category
        - Required certifications/licenses for regulated categories
        - Quality score based on supplier history
        - Risk assessment for the offering

        Returns validation result with approval/rejection decision.
        """
        validation_id = f"SV-{datetime.now().strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(3).upper()}"

        supplier = self.suppliers.get(supplier_id, {})
        if not supplier:
            return {
                'success': False,
                'error': f'Supplier {supplier_id} not found',
                'validation_id': validation_id,
                'status': SupplyValidationStatus.REJECTED.value
            }

        if supplier.get('status') != 'approved':
            return {
                'success': False,
                'error': f'Supplier {supplier_id} is not approved (status: {supplier.get("status")})',
                'validation_id': validation_id,
                'status': SupplyValidationStatus.REJECTED.value
            }

        compliance_checks = self._run_supply_compliance_checks(supplier, offer_data)
        quality_score = self._calculate_supply_quality_score(supplier, offer_data)
        risk_score = self._calculate_supply_risk_score(supplier, offer_data)

        offer_id = offer_data.get('id', f"OFF-PENDING-{secrets.token_hex(4).upper()}")
        category = str(offer_data.get('category', '')).lower()
        price = float(offer_data.get('price', 0))

        validation = MarketplaceSupplyValidation(
            validation_id=validation_id,
            supplier_id=supplier_id,
            offer_id=offer_id,
            offer_name=offer_data.get('name', ''),
            category=category,
            item_type=offer_data.get('item_type', 'product'),
            price=price,
            compliance_checks=compliance_checks,
            quality_score=quality_score,
            risk_score=risk_score
        )
        validation.compute_hash()

        all_compliant = all(compliance_checks.values())
        auto_approve = (
            all_compliant and
            quality_score >= 70 and
            risk_score <= 30 and
            price <= self.AUTO_APPROVE_PRICE_LIMIT and
            float(supplier.get('average_rating', 0)) >= self.MIN_SUPPLIER_RATING_FOR_AUTO_APPROVE
        )

        if not all_compliant:
            failed_checks = [k for k, v in compliance_checks.items() if not v]
            validation.status = SupplyValidationStatus.REJECTED.value
            validation.reviewer_notes = f"Failed compliance: {', '.join(failed_checks)}"
        elif auto_approve:
            validation.status = SupplyValidationStatus.APPROVED.value
            validation.auto_approved = True
            validation.reviewer_notes = "Auto-approved: meets all criteria"
            validation.reviewed_at = datetime.now(timezone.utc).isoformat()
        elif risk_score > 60:
            validation.status = SupplyValidationStatus.REJECTED.value
            validation.reviewer_notes = f"High risk score: {risk_score:.0f}"
        elif category in self.REGULATED_CATEGORIES:
            validation.status = SupplyValidationStatus.UNDER_REVIEW.value
            validation.reviewer_notes = "Regulated category requires manual review"
        else:
            validation.status = SupplyValidationStatus.UNDER_REVIEW.value
            validation.reviewer_notes = "Queued for review"

        self.supply_validations[validation_id] = validation

        self._log_automation('supply_validation', {
            'validation_id': validation_id,
            'supplier_id': supplier_id,
            'offer_name': offer_data.get('name'),
            'status': validation.status,
            'quality_score': quality_score,
            'risk_score': risk_score,
            'auto_approved': validation.auto_approved
        })

        return {
            'success': True,
            'validation_id': validation_id,
            'status': validation.status,
            'auto_approved': validation.auto_approved,
            'compliance_checks': compliance_checks,
            'quality_score': round(quality_score, 1),
            'risk_score': round(risk_score, 1),
            'notes': validation.reviewer_notes,
            'data_hash': validation.data_hash,
            'validation': validation.to_dict()
        }

    def _run_supply_compliance_checks(self, supplier: Dict, offer_data: Dict) -> Dict[str, bool]:
        checks = {}
        name = str(offer_data.get('name', '')).strip()
        checks['has_name'] = len(name) >= 3
        checks['has_category'] = bool(offer_data.get('category'))
        checks['has_valid_price'] = float(offer_data.get('price', -1)) >= 0
        checks['has_description'] = bool(offer_data.get('description'))

        item_type = str(offer_data.get('item_type', '')).lower()
        checks['valid_item_type'] = item_type in ('service', 'product')

        category = str(offer_data.get('category', '')).lower()
        if category in self.REGULATED_CATEGORIES:
            checks['supplier_licensed'] = bool(supplier.get('license_number'))
        else:
            checks['supplier_licensed'] = True

        checks['supplier_approved'] = supplier.get('status') == 'approved'

        if category in self.MEDICAL_CATEGORIES:
            checks['medical_compliance'] = bool(
                supplier.get('license_number') or
                supplier.get('insurance_certificate') or
                category in ('wellness', 'equipment')
            )
        else:
            checks['medical_compliance'] = True

        return checks

    def _calculate_supply_quality_score(self, supplier: Dict, offer_data: Dict) -> float:
        score = 50.0

        rating = float(supplier.get('average_rating', 0))
        if rating >= 4.5:
            score += 25
        elif rating >= 4.0:
            score += 15
        elif rating >= 3.5:
            score += 5

        completed = int(supplier.get('completed_orders', 0))
        if completed >= 100:
            score += 15
        elif completed >= 50:
            score += 10
        elif completed >= 10:
            score += 5

        if offer_data.get('description') and len(str(offer_data.get('description', ''))) > 50:
            score += 5
        if offer_data.get('delivery_config'):
            score += 5

        return min(100, score)

    def _calculate_supply_risk_score(self, supplier: Dict, offer_data: Dict) -> float:
        risk = 10.0

        disputes = int(supplier.get('dispute_count', 0))
        total_orders = max(1, int(supplier.get('total_orders', 1)))
        dispute_rate = disputes / total_orders
        if dispute_rate > 0.1:
            risk += 30
        elif dispute_rate > 0.05:
            risk += 15

        price = float(offer_data.get('price', 0))
        if price > 10000:
            risk += 15
        elif price > 5000:
            risk += 8

        category = str(offer_data.get('category', '')).lower()
        if category in self.REGULATED_CATEGORIES and not supplier.get('license_number'):
            risk += 25

        rating = float(supplier.get('average_rating', 5))
        if rating < 3.0:
            risk += 20
        elif rating < 4.0:
            risk += 10

        return min(100, risk)

    def get_supply_validation(self, validation_id: str) -> Optional[Dict]:
        v = self.supply_validations.get(validation_id)
        return v.to_dict() if v else None

    def approve_supply_validation(self, validation_id: str, reviewer: str,
                                   notes: str = "") -> Dict[str, Any]:
        v = self.supply_validations.get(validation_id)
        if not v:
            return {'success': False, 'error': 'Validation not found'}

        v.status = SupplyValidationStatus.APPROVED.value
        v.reviewed_at = datetime.now(timezone.utc).isoformat()
        v.reviewer_notes = notes or f"Approved by {reviewer}"

        return {
            'success': True,
            'validation_id': validation_id,
            'status': v.status,
            'offer_id': v.offer_id,
            'message': f'Supply {v.offer_name} approved for marketplace'
        }

    def reject_supply_validation(self, validation_id: str, reviewer: str,
                                  reason: str) -> Dict[str, Any]:
        v = self.supply_validations.get(validation_id)
        if not v:
            return {'success': False, 'error': 'Validation not found'}

        v.status = SupplyValidationStatus.REJECTED.value
        v.reviewed_at = datetime.now(timezone.utc).isoformat()
        v.reviewer_notes = f"Rejected by {reviewer}: {reason}"

        return {
            'success': True,
            'validation_id': validation_id,
            'status': v.status,
            'message': f'Supply {v.offer_name} rejected: {reason}'
        }

    def get_pending_supply_validations(self) -> List[Dict]:
        return [
            v.to_dict() for v in self.supply_validations.values()
            if v.status in (SupplyValidationStatus.PENDING.value, SupplyValidationStatus.UNDER_REVIEW.value)
        ]

    # =========================================================================
    # 7. CROSS-PIPELINE DATA INTEGRITY
    # =========================================================================

    def run_full_integrity_check(self) -> CrossPipelineIntegrityReport:
        """
        Run comprehensive data integrity check across all pipelines.
        Ensures consistency between health wallets, supply chain, delivery,
        claims, billing, and marketplace.
        """
        report_id = f"XPIR-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        now = datetime.now(timezone.utc).isoformat()

        stage_results = {}
        cross_issues = []

        supply_result = self.validate_supply_chain_pipeline()
        stage_results[PipelineStage.SUPPLY_CHAIN.value] = supply_result

        delivery_result = self.validate_delivery_pipeline()
        stage_results[PipelineStage.DELIVERY.value] = delivery_result

        claims_result = self._validate_claims_integrity()
        stage_results[PipelineStage.CLAIMS.value] = claims_result

        billing_result = self._validate_billing_integrity()
        stage_results[PipelineStage.BILLING.value] = billing_result

        customer_ids = set()
        customer_ids.update(self.health_wallets.keys())
        for policy in self.policies.values():
            cid = policy.get('customer_id')
            if cid:
                customer_ids.add(cid)

        wallet_issues_count = 0
        for cid in list(customer_ids)[:50]:
            wallet_result = self.validate_health_wallet_pipeline(cid)
            if not wallet_result.is_valid:
                wallet_issues_count += 1

        stage_results[PipelineStage.HEALTH_WALLET.value] = PipelineValidationResult(
            stage=PipelineStage.HEALTH_WALLET.value,
            is_valid=wallet_issues_count == 0,
            score=max(0, 100 - wallet_issues_count * 10),
            metadata={
                'customers_checked': min(len(customer_ids), 50),
                'issues_found': wallet_issues_count
            }
        )

        cross_issues.extend(self._check_wallet_order_consistency())
        cross_issues.extend(self._check_claims_billing_consistency())
        cross_issues.extend(self._check_policy_billing_alignment())

        scores = [r.score for r in stage_results.values()]
        overall_score = sum(scores) / len(scores) if scores else 100.0

        cross_penalty = len([i for i in cross_issues if i.get('severity') == 'critical']) * 10
        cross_penalty += len([i for i in cross_issues if i.get('severity') == 'error']) * 5
        overall_score = max(0, overall_score - cross_penalty)

        if overall_score >= 90:
            overall_status = 'healthy'
        elif overall_score >= 70:
            overall_status = 'warning'
        else:
            overall_status = 'critical'

        integrity_data = json.dumps({
            'scores': {k: v.score for k, v in stage_results.items()},
            'overall': overall_score,
            'timestamp': now
        }, sort_keys=True)
        data_hash = hashlib.sha256(integrity_data.encode()).hexdigest()[:16]

        recommendations = self._generate_cross_pipeline_recommendations(stage_results, cross_issues)

        report = CrossPipelineIntegrityReport(
            report_id=report_id,
            generated_at=now,
            overall_score=round(overall_score, 1),
            overall_status=overall_status,
            stage_results=stage_results,
            cross_pipeline_issues=cross_issues,
            data_integrity_hash=data_hash,
            recommendations=recommendations
        )

        self._log_automation('full_integrity_check', {
            'report_id': report_id,
            'overall_score': overall_score,
            'overall_status': overall_status,
            'stages_checked': len(stage_results),
            'cross_issues': len(cross_issues)
        })

        return report

    def _validate_claims_integrity(self) -> PipelineValidationResult:
        issues = []
        score = 100.0

        for claim_id, claim in self.claims.items():
            policy_id = claim.get('policy_id', '')
            if policy_id and policy_id not in self.policies:
                issues.append({
                    'severity': ValidationSeverity.ERROR.value,
                    'entity': 'claim',
                    'id': claim_id,
                    'message': f'Claim {claim_id} references non-existent policy {policy_id}'
                })
                score -= 8

            amount = float(claim.get('amount', claim.get('claim_amount', 0)))
            if amount < 0:
                issues.append({
                    'severity': ValidationSeverity.CRITICAL.value,
                    'entity': 'claim',
                    'id': claim_id,
                    'message': f'Claim {claim_id} has negative amount: ${amount:.2f}'
                })
                score -= 15

        return PipelineValidationResult(
            stage=PipelineStage.CLAIMS.value,
            is_valid=len([i for i in issues if i['severity'] == ValidationSeverity.CRITICAL.value]) == 0,
            score=max(0, score),
            issues=issues,
            metadata={'total_claims': len(self.claims)}
        )

    def _validate_billing_integrity(self) -> PipelineValidationResult:
        issues = []
        score = 100.0

        for bill_id, bill in self.billing.items():
            due = float(bill.get('amount_due', 0))
            paid = float(bill.get('amount_paid', 0))

            if paid > due and due > 0:
                issues.append({
                    'severity': ValidationSeverity.WARNING.value,
                    'entity': 'bill',
                    'id': bill_id,
                    'message': f'Bill {bill_id} overpaid: due ${due:.2f}, paid ${paid:.2f}'
                })
                score -= 3

            status = str(bill.get('status', '')).lower()
            if status == 'paid' and paid < due and due > 0:
                issues.append({
                    'severity': ValidationSeverity.ERROR.value,
                    'entity': 'bill',
                    'id': bill_id,
                    'message': f'Bill {bill_id} marked paid but underpaid: due ${due:.2f}, paid ${paid:.2f}'
                })
                score -= 8

        return PipelineValidationResult(
            stage=PipelineStage.BILLING.value,
            is_valid=len([i for i in issues if i['severity'] in (ValidationSeverity.CRITICAL.value, ValidationSeverity.ERROR.value)]) == 0,
            score=max(0, score),
            issues=issues,
            metadata={'total_bills': len(self.billing)}
        )

    def _check_wallet_order_consistency(self) -> List[Dict]:
        """Verify wallet debits match supply chain orders."""
        issues = []
        for cid, wallet in self.health_wallets.items():
            for tx in wallet.get('transactions', []):
                if tx.get('type') == 'order_payment':
                    order_id = tx.get('order_id')
                    if order_id and order_id not in self.supplier_orders:
                        issues.append({
                            'severity': 'warning',
                            'pipeline': 'wallet_supply_chain',
                            'message': f'Wallet debit for order {order_id} but order not found in supply chain',
                            'customer_id': cid
                        })
        return issues

    def _check_claims_billing_consistency(self) -> List[Dict]:
        """Verify approved claims have corresponding billing adjustments."""
        issues = []
        for claim_id, claim in self.claims.items():
            status = str(claim.get('status', '')).lower()
            if status in ('approved', 'paid'):
                policy_id = claim.get('policy_id', '')
                has_related_bill = any(
                    b.get('policy_id') == policy_id
                    for b in self.billing.values()
                )
                if policy_id and not has_related_bill:
                    issues.append({
                        'severity': 'info',
                        'pipeline': 'claims_billing',
                        'message': f'Approved claim {claim_id} on policy {policy_id} but no billing records found for this policy',
                        'claim_id': claim_id
                    })
        return issues

    def _check_policy_billing_alignment(self) -> List[Dict]:
        """Verify active policies have associated billing."""
        issues = []
        for pol_id, policy in self.policies.items():
            status = str(policy.get('status', '')).lower()
            if status in ('active', 'in_force'):
                has_billing = any(
                    b.get('policy_id') == pol_id
                    for b in self.billing.values()
                )
                if not has_billing:
                    issues.append({
                        'severity': 'warning',
                        'pipeline': 'policy_billing',
                        'message': f'Active policy {pol_id} has no billing records',
                        'policy_id': pol_id
                    })
        return issues

    def _generate_cross_pipeline_recommendations(self, stage_results: Dict,
                                                   cross_issues: List) -> List[str]:
        recommendations = []

        for stage, result in stage_results.items():
            if result.score < 70:
                recommendations.append(
                    f"CRITICAL: {stage} pipeline score is {result.score:.0f}/100. "
                    f"Found {len(result.issues)} issues requiring attention."
                )
            elif result.score < 90:
                recommendations.append(
                    f"WARNING: {stage} pipeline score is {result.score:.0f}/100. "
                    f"Minor issues detected."
                )

        wallet_order_issues = [i for i in cross_issues if i.get('pipeline') == 'wallet_supply_chain']
        if wallet_order_issues:
            recommendations.append(
                f"DATA SYNC: {len(wallet_order_issues)} wallet transactions reference missing supply chain orders. "
                f"Run data reconciliation."
            )

        billing_issues = [i for i in cross_issues if i.get('pipeline') == 'policy_billing']
        if billing_issues:
            recommendations.append(
                f"BILLING GAP: {len(billing_issues)} active policies have no billing records. "
                f"Run billing generation pipeline."
            )

        if not recommendations:
            recommendations.append("All pipelines are healthy. No action required.")

        return recommendations

    # =========================================================================
    # AUTOMATION LOGGING
    # =========================================================================

    def _log_automation(self, action: str, details: Dict[str, Any]):
        self.automation_log.append({
            'action': action,
            'details': details,
            'timestamp': datetime.now(timezone.utc).isoformat()
        })

    def get_automation_log(self, limit: int = 50) -> List[Dict]:
        return sorted(self.automation_log, key=lambda x: x['timestamp'], reverse=True)[:limit]

    def get_pipeline_dashboard(self) -> Dict[str, Any]:
        """Get unified dashboard data for all pipelines."""
        return {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'health_wallets': {
                'total_wallets': len(self.health_wallets),
                'total_balance': sum(float(w.get('balance', 0)) for w in self.health_wallets.values()),
            },
            'supply_chain': {
                'total_suppliers': len(self.suppliers),
                'approved_suppliers': len([s for s in self.suppliers.values() if s.get('status') == 'approved']),
                'active_offers': len([o for o in self.supplier_offers.values() if o.get('active')]),
                'total_orders': len(self.supplier_orders),
            },
            'claims': {
                'total_claims': len(self.claims),
                'pending': len([c for c in self.claims.values() if str(c.get('status', '')).lower() == 'pending']),
                'approved': len([c for c in self.claims.values() if str(c.get('status', '')).lower() in ('approved', 'paid')]),
            },
            'billing': {
                'total_bills': len(self.billing),
                'outstanding': len([b for b in self.billing.values() if str(b.get('status', '')).lower() == 'outstanding']),
                'paid': len([b for b in self.billing.values() if str(b.get('status', '')).lower() == 'paid']),
            },
            'marketplace_validations': {
                'total': len(self.supply_validations),
                'pending': len([v for v in self.supply_validations.values() if v.status in (SupplyValidationStatus.PENDING.value, SupplyValidationStatus.UNDER_REVIEW.value)]),
                'approved': len([v for v in self.supply_validations.values() if v.status == SupplyValidationStatus.APPROVED.value]),
                'rejected': len([v for v in self.supply_validations.values() if v.status == SupplyValidationStatus.REJECTED.value]),
            },
            'automation': {
                'total_actions': len(self.automation_log),
                'recent_actions': self.get_automation_log(5)
            }
        }


# Singleton
_orchestrator: Optional[ProcessPipelineOrchestrator] = None


def get_process_pipeline_orchestrator(**kwargs) -> ProcessPipelineOrchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = ProcessPipelineOrchestrator(**kwargs)
    return _orchestrator


def init_process_pipeline_orchestrator(**kwargs) -> ProcessPipelineOrchestrator:
    global _orchestrator
    _orchestrator = ProcessPipelineOrchestrator(**kwargs)
    return _orchestrator


def reset_process_pipeline_orchestrator():
    global _orchestrator
    _orchestrator = None
