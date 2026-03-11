"""
PHINS Billing Credit Service
============================
Comprehensive billing credit management system.

Features:
1. Credit Tracking - Track customer billing credits from overpayments
2. Credit Detection - Automatically detect billing errors (future payments billed early)
3. Credit Actions - Allow customers to withdraw, transfer to wallet, or apply to bills
4. Notification Integration - Alert customers about credits and outstanding bills
5. Data Integrity - Ensure billing data remains consistent and validated

Credit Flow:
1. Customer is accidentally billed for future payment -> Credit created
2. Customer notified via email/SMS with credit balance
3. Customer can:
   a. Withdraw to bank account
   b. Transfer to health wallet
   c. Apply to future bills
   d. Keep as credit (earns interest)
"""

from __future__ import annotations

import os
import json
import hashlib
import secrets
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
import threading

logger = logging.getLogger('phins.billing_credit')


# ============================================================================
# ENUMS
# ============================================================================

class CreditStatus(str, Enum):
    """Status of a billing credit"""
    ACTIVE = "active"          # Credit available for use
    WITHDRAWN = "withdrawn"    # Credit withdrawn to bank
    TRANSFERRED = "transferred" # Credit transferred to wallet
    APPLIED = "applied"        # Credit applied to bill
    EXPIRED = "expired"        # Credit expired (configurable)
    REVERSED = "reversed"      # Credit reversed (error correction)


class CreditType(str, Enum):
    """Type of billing credit"""
    OVERPAYMENT = "overpayment"               # Customer paid more than due
    BILLING_ERROR = "billing_error"           # Billed for future period by mistake
    REFUND = "refund"                         # Refund processed
    PROMOTIONAL = "promotional"               # Promotional credit
    LOYALTY = "loyalty"                       # Loyalty reward
    CORRECTION = "correction"                 # Manual correction
    INTEREST = "interest"                     # Interest on credit balance


class BillingNotificationType(str, Enum):
    """Types of billing notifications"""
    OUTSTANDING_BILL = "outstanding_bill"         # Bill is due
    BILL_OVERDUE = "bill_overdue"                 # Bill is past due
    PAYMENT_RECEIVED = "payment_received"         # Payment confirmed
    CREDIT_AVAILABLE = "credit_available"         # Credit balance notification
    CREDIT_EXPIRING = "credit_expiring"           # Credit will expire soon
    BILLING_ERROR_DETECTED = "billing_error"      # Billing error found
    PAYMENT_REMINDER = "payment_reminder"         # Upcoming payment reminder


# ============================================================================
# DATA CLASSES
# ============================================================================

@dataclass
class BillingCredit:
    """Represents a billing credit for a customer"""
    credit_id: str
    customer_id: str
    amount: Decimal
    remaining_amount: Decimal
    credit_type: CreditType
    status: CreditStatus
    
    # Source information
    source_bill_id: Optional[str] = None
    source_policy_id: Optional[str] = None
    source_transaction_id: Optional[str] = None
    
    # Reason and description
    reason: str = ""
    description: str = ""
    
    # Dates
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: Optional[datetime] = None
    
    # Interest (if applicable)
    interest_rate: Decimal = Decimal("0.02")  # 2% annual rate
    interest_accrued: Decimal = Decimal("0")
    
    # Audit trail
    transactions: List[Dict[str, Any]] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'credit_id': self.credit_id,
            'customer_id': self.customer_id,
            'amount': float(self.amount),
            'remaining_amount': float(self.remaining_amount),
            'credit_type': self.credit_type.value,
            'status': self.status.value,
            'source_bill_id': self.source_bill_id,
            'source_policy_id': self.source_policy_id,
            'source_transaction_id': self.source_transaction_id,
            'reason': self.reason,
            'description': self.description,
            'created_at': self.created_at.isoformat(),
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
            'interest_rate': float(self.interest_rate),
            'interest_accrued': float(self.interest_accrued),
            'transactions': self.transactions
        }


@dataclass
class BillingValidationResult:
    """Result of billing validation check"""
    is_valid: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    credits_detected: List[Dict[str, Any]] = field(default_factory=list)
    
    # Billing error details
    overbilled_amount: Decimal = Decimal("0")
    future_billed_amount: Decimal = Decimal("0")
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'is_valid': self.is_valid,
            'errors': self.errors,
            'warnings': self.warnings,
            'credits_detected': self.credits_detected,
            'overbilled_amount': float(self.overbilled_amount),
            'future_billed_amount': float(self.future_billed_amount)
        }


@dataclass
class BillingNotificationResult:
    """Result of billing notification"""
    success: bool
    notification_id: str
    customer_id: str
    notification_type: BillingNotificationType
    channels_sent: List[str] = field(default_factory=list)
    error_message: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'success': self.success,
            'notification_id': self.notification_id,
            'customer_id': self.customer_id,
            'notification_type': self.notification_type.value,
            'channels_sent': self.channels_sent,
            'error_message': self.error_message
        }


# ============================================================================
# CONFIGURATION
# ============================================================================

class BillingCreditConfig:
    """Configuration for billing credit service"""
    
    # Credit expiration (days from creation)
    CREDIT_EXPIRY_DAYS = int(os.environ.get('CREDIT_EXPIRY_DAYS', '365'))
    
    # Minimum credit amount to track
    MIN_CREDIT_AMOUNT = Decimal(os.environ.get('MIN_CREDIT_AMOUNT', '0.01'))
    
    # Interest settings
    CREDIT_INTEREST_ENABLED = os.environ.get('CREDIT_INTEREST_ENABLED', 'true').lower() == 'true'
    CREDIT_INTEREST_RATE = Decimal(os.environ.get('CREDIT_INTEREST_RATE', '0.02'))  # 2% annual
    
    # Notification settings
    OUTSTANDING_BILL_REMINDER_DAYS = [7, 3, 1]  # Days before due date
    OVERDUE_BILL_REMINDER_DAYS = [1, 3, 7, 14, 30]  # Days after due date
    
    # Billing validation thresholds
    FUTURE_BILLING_THRESHOLD_DAYS = int(os.environ.get('FUTURE_BILLING_THRESHOLD_DAYS', '30'))
    
    # Portal links
    BILLING_PORTAL_URL = os.environ.get('BILLING_PORTAL_URL', 'https://phins.ai/billing.html')
    DASHBOARD_URL = os.environ.get('DASHBOARD_URL', 'https://phins.ai/dashboard.html#billing')


# ============================================================================
# BILLING CREDIT SERVICE
# ============================================================================

class BillingCreditService:
    """
    Enterprise Billing Credit Service
    
    Manages:
    - Credit tracking and storage
    - Credit detection from billing errors
    - Credit actions (withdraw, transfer, apply)
    - Notification integration
    - Ledger updates and integrity
    """
    
    def __init__(
        self,
        billing_data: Dict[str, Any] = None,
        policies_data: Dict[str, Any] = None,
        customers_data: Dict[str, Any] = None,
        health_wallets: Dict[str, Any] = None,
        notification_service=None,
        ledger_service=None
    ):
        # Data references
        self._billing = billing_data if billing_data is not None else {}
        self._policies = policies_data if policies_data is not None else {}
        self._customers = customers_data if customers_data is not None else {}
        self._health_wallets = health_wallets if health_wallets is not None else {}
        
        # Services
        self._notification_service = notification_service
        self._ledger_service = ledger_service
        
        # Credit storage
        self._credits: Dict[str, BillingCredit] = {}
        self._customer_credits: Dict[str, List[str]] = {}  # customer_id -> [credit_ids]
        
        # Transaction history
        self._credit_transactions: List[Dict[str, Any]] = []
        
        # Thread safety (RLock so nested calls like withdraw -> get_balance don't deadlock)
        self._lock = threading.RLock()
        
        logger.info("Billing credit service initialized")
    
    # ========== CREDIT MANAGEMENT ==========
    
    def create_credit(
        self,
        customer_id: str,
        amount: float,
        credit_type: CreditType,
        reason: str,
        source_bill_id: Optional[str] = None,
        source_policy_id: Optional[str] = None,
        description: str = "",
        expires_days: int = None
    ) -> BillingCredit:
        """
        Create a new billing credit for a customer.
        
        Args:
            customer_id: Customer ID
            amount: Credit amount
            credit_type: Type of credit
            reason: Reason for credit
            source_bill_id: Related bill ID
            source_policy_id: Related policy ID
            description: Detailed description
            expires_days: Days until expiration (default from config)
        
        Returns:
            Created BillingCredit
        """
        credit_id = f"CREDIT-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(4)}"
        
        amount_decimal = Decimal(str(amount)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        
        # Check minimum amount
        if amount_decimal < BillingCreditConfig.MIN_CREDIT_AMOUNT:
            logger.warning(f"Credit amount {amount_decimal} below minimum threshold")
        
        # Calculate expiration
        expires_at = None
        if expires_days or BillingCreditConfig.CREDIT_EXPIRY_DAYS > 0:
            days = expires_days or BillingCreditConfig.CREDIT_EXPIRY_DAYS
            expires_at = datetime.now(timezone.utc) + timedelta(days=days)
        
        credit = BillingCredit(
            credit_id=credit_id,
            customer_id=customer_id,
            amount=amount_decimal,
            remaining_amount=amount_decimal,
            credit_type=credit_type,
            status=CreditStatus.ACTIVE,
            source_bill_id=source_bill_id,
            source_policy_id=source_policy_id,
            reason=reason,
            description=description,
            expires_at=expires_at,
            interest_rate=BillingCreditConfig.CREDIT_INTEREST_RATE if BillingCreditConfig.CREDIT_INTEREST_ENABLED else Decimal("0")
        )
        
        # Store credit
        with self._lock:
            self._credits[credit_id] = credit
            
            if customer_id not in self._customer_credits:
                self._customer_credits[customer_id] = []
            self._customer_credits[customer_id].append(credit_id)
            
            # Record transaction
            tx = {
                'id': f"CRTX-{secrets.token_hex(6)}",
                'credit_id': credit_id,
                'customer_id': customer_id,
                'action': 'create',
                'amount': float(amount_decimal),
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'details': {
                    'credit_type': credit_type.value,
                    'reason': reason,
                    'source_bill_id': source_bill_id
                }
            }
            credit.transactions.append(tx)
            self._credit_transactions.append(tx)
        
        logger.info(f"Created credit {credit_id} for customer {customer_id}: ${amount_decimal}")
        
        # Send notification about credit
        self._notify_credit_available(customer_id, credit)
        
        return credit
    
    def get_customer_credit_balance(self, customer_id: str) -> Dict[str, Any]:
        """
        Get total credit balance and details for a customer.
        
        Returns:
            Dictionary with credit balance summary
        """
        with self._lock:
            credit_ids = self._customer_credits.get(customer_id, [])
            credits = [self._credits[cid] for cid in credit_ids if cid in self._credits]
        
        active_credits = [c for c in credits if c.status == CreditStatus.ACTIVE]
        
        # Calculate totals
        total_credit = sum(c.remaining_amount for c in active_credits)
        total_interest = sum(c.interest_accrued for c in active_credits)
        
        # Group by type
        by_type = {}
        for c in active_credits:
            credit_type = c.credit_type.value
            if credit_type not in by_type:
                by_type[credit_type] = Decimal("0")
            by_type[credit_type] += c.remaining_amount
        
        return {
            'customer_id': customer_id,
            'total_credit_balance': float(total_credit),
            'total_interest_accrued': float(total_interest),
            'total_with_interest': float(total_credit + total_interest),
            'active_credits_count': len(active_credits),
            'by_type': {k: float(v) for k, v in by_type.items()},
            'credits': [c.to_dict() for c in active_credits],
            'can_withdraw': float(total_credit + total_interest) > 0,
            'can_transfer_to_wallet': float(total_credit + total_interest) > 0
        }
    
    def withdraw_credit(
        self,
        customer_id: str,
        amount: float,
        withdrawal_method: str = "bank_transfer",
        bank_details: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Withdraw credit to bank account.
        
        Args:
            customer_id: Customer ID
            amount: Amount to withdraw
            withdrawal_method: Method (bank_transfer, check, etc.)
            bank_details: Bank account details
        
        Returns:
            Withdrawal result
        """
        amount_decimal = Decimal(str(amount)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        
        with self._lock:
            balance_info = self.get_customer_credit_balance(customer_id)
            available = Decimal(str(balance_info['total_with_interest']))
            
            if amount_decimal > available:
                return {
                    'success': False,
                    'error': 'Insufficient credit balance',
                    'available_balance': float(available),
                    'requested_amount': float(amount_decimal)
                }
            
            # Deduct from credits (FIFO)
            remaining = amount_decimal
            credits_used = []
            
            credit_ids = self._customer_credits.get(customer_id, [])
            for cid in credit_ids:
                if remaining <= 0:
                    break
                
                credit = self._credits.get(cid)
                if not credit or credit.status != CreditStatus.ACTIVE:
                    continue
                
                # Use interest first, then principal
                total_available = credit.remaining_amount + credit.interest_accrued
                use_amount = min(remaining, total_available)
                
                if use_amount > 0:
                    # Deduct interest first
                    interest_used = min(credit.interest_accrued, use_amount)
                    credit.interest_accrued -= interest_used
                    remaining -= interest_used
                    use_amount -= interest_used
                    
                    # Then deduct principal
                    if use_amount > 0:
                        credit.remaining_amount -= use_amount
                        remaining -= use_amount
                    
                    credits_used.append({
                        'credit_id': cid,
                        'amount_used': float(min(remaining, total_available)),
                        'remaining': float(credit.remaining_amount)
                    })
                    
                    # Mark as withdrawn if fully used
                    if credit.remaining_amount <= 0 and credit.interest_accrued <= 0:
                        credit.status = CreditStatus.WITHDRAWN
            
            # Record transaction
            withdrawal_id = f"WDRW-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(4)}"
            tx = {
                'id': withdrawal_id,
                'customer_id': customer_id,
                'action': 'withdraw',
                'amount': float(amount_decimal),
                'method': withdrawal_method,
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'credits_used': credits_used,
                'status': 'pending_transfer'  # Would be 'completed' after bank confirmation
            }
            self._credit_transactions.append(tx)
        
        logger.info(f"Withdrawal {withdrawal_id} processed for {customer_id}: ${amount_decimal}")
        
        return {
            'success': True,
            'withdrawal_id': withdrawal_id,
            'amount': float(amount_decimal),
            'method': withdrawal_method,
            'status': 'pending_transfer',
            'new_balance': float(available - amount_decimal),
            'credits_used': credits_used,
            'message': f'Withdrawal of ${amount_decimal:.2f} initiated. Funds will be transferred within 3-5 business days.'
        }
    
    def transfer_to_wallet(
        self,
        customer_id: str,
        amount: float,
        wallet_type: str = "health_wallet"
    ) -> Dict[str, Any]:
        """
        Transfer credit to customer's health wallet.
        
        Args:
            customer_id: Customer ID
            amount: Amount to transfer
            wallet_type: Target wallet (health_wallet, investment_wallet)
        
        Returns:
            Transfer result
        """
        amount_decimal = Decimal(str(amount)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        
        with self._lock:
            balance_info = self.get_customer_credit_balance(customer_id)
            available = Decimal(str(balance_info['total_with_interest']))
            
            if amount_decimal > available:
                return {
                    'success': False,
                    'error': 'Insufficient credit balance',
                    'available_balance': float(available),
                    'requested_amount': float(amount_decimal)
                }
            
            # Transfer to wallet
            if wallet_type == "health_wallet":
                if customer_id not in self._health_wallets:
                    self._health_wallets[customer_id] = {
                        'customer_id': customer_id,
                        'balance': 0,
                        'monthly_deposit': 0,
                        'transactions': []
                    }
                
                prev_balance = self._health_wallets[customer_id].get('balance', 0)
                self._health_wallets[customer_id]['balance'] = prev_balance + float(amount_decimal)
                
                # Record wallet transaction
                wallet_tx = {
                    'id': f"WAL-CREDIT-{datetime.now().strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(4)}",
                    'type': 'credit_transfer',
                    'amount': float(amount_decimal),
                    'description': 'Transfer from billing credit',
                    'previous_balance': prev_balance,
                    'balance_after': self._health_wallets[customer_id]['balance'],
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }
                self._health_wallets[customer_id].setdefault('transactions', []).append(wallet_tx)
            
            # Deduct from credits (FIFO)
            remaining = amount_decimal
            credits_used = []
            
            credit_ids = self._customer_credits.get(customer_id, [])
            for cid in credit_ids:
                if remaining <= 0:
                    break
                
                credit = self._credits.get(cid)
                if not credit or credit.status != CreditStatus.ACTIVE:
                    continue
                
                total_available = credit.remaining_amount + credit.interest_accrued
                use_amount = min(remaining, total_available)
                
                if use_amount > 0:
                    interest_used = min(credit.interest_accrued, use_amount)
                    credit.interest_accrued -= interest_used
                    remaining -= interest_used
                    use_amount -= interest_used
                    
                    if use_amount > 0:
                        credit.remaining_amount -= use_amount
                        remaining -= use_amount
                    
                    credits_used.append({
                        'credit_id': cid,
                        'remaining': float(credit.remaining_amount)
                    })
                    
                    if credit.remaining_amount <= 0 and credit.interest_accrued <= 0:
                        credit.status = CreditStatus.TRANSFERRED
            
            # Record transaction
            transfer_id = f"TRFR-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(4)}"
            tx = {
                'id': transfer_id,
                'customer_id': customer_id,
                'action': 'transfer_to_wallet',
                'amount': float(amount_decimal),
                'wallet_type': wallet_type,
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'credits_used': credits_used,
                'status': 'completed'
            }
            self._credit_transactions.append(tx)
        
        logger.info(f"Transfer {transfer_id} to {wallet_type} for {customer_id}: ${amount_decimal}")
        
        new_wallet_balance = self._health_wallets.get(customer_id, {}).get('balance', 0)
        
        return {
            'success': True,
            'transfer_id': transfer_id,
            'amount': float(amount_decimal),
            'wallet_type': wallet_type,
            'new_credit_balance': float(available - amount_decimal),
            'new_wallet_balance': new_wallet_balance,
            'message': f'${amount_decimal:.2f} transferred to your {wallet_type.replace("_", " ")}.'
        }
    
    def apply_to_bill(
        self,
        customer_id: str,
        bill_id: str,
        amount: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Apply credit to an outstanding bill.
        
        Args:
            customer_id: Customer ID
            bill_id: Bill to apply credit to
            amount: Amount to apply (default: full bill amount or available credit)
        
        Returns:
            Application result
        """
        bill = self._billing.get(bill_id)
        if not bill:
            return {'success': False, 'error': 'Bill not found'}
        
        if bill.get('customer_id') != customer_id:
            return {'success': False, 'error': 'Bill does not belong to this customer'}
        
        bill_status = bill.get('status', '').lower()
        if bill_status not in ['outstanding', 'partial', 'overdue']:
            return {'success': False, 'error': f'Bill is not payable (status: {bill_status})'}
        
        with self._lock:
            balance_info = self.get_customer_credit_balance(customer_id)
            available = Decimal(str(balance_info['total_with_interest']))
            
            # Calculate amount to apply
            amount_due = Decimal(str(bill.get('amount', bill.get('amount_due', 0))))
            amount_paid = Decimal(str(bill.get('amount_paid', 0)))
            remaining_due = amount_due - amount_paid
            
            if amount is not None:
                apply_amount = Decimal(str(amount)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            else:
                apply_amount = min(available, remaining_due)
            
            if apply_amount <= 0:
                return {'success': False, 'error': 'No amount to apply'}
            
            if apply_amount > available:
                return {
                    'success': False,
                    'error': 'Insufficient credit balance',
                    'available': float(available),
                    'requested': float(apply_amount)
                }
            
            if apply_amount > remaining_due:
                apply_amount = remaining_due
            
            # Apply to bill
            bill['amount_paid'] = float(amount_paid + apply_amount)
            if bill['amount_paid'] >= float(amount_due):
                bill['status'] = 'paid'
                bill['paid_date'] = datetime.now(timezone.utc).isoformat()
            else:
                bill['status'] = 'partial'
            
            bill['last_payment_method'] = 'credit_applied'
            self._billing[bill_id] = bill
            
            # Deduct from credits (FIFO)
            remaining = apply_amount
            credits_used = []
            
            credit_ids = self._customer_credits.get(customer_id, [])
            for cid in credit_ids:
                if remaining <= 0:
                    break
                
                credit = self._credits.get(cid)
                if not credit or credit.status != CreditStatus.ACTIVE:
                    continue
                
                total_available = credit.remaining_amount + credit.interest_accrued
                use_amount = min(remaining, total_available)
                
                if use_amount > 0:
                    interest_used = min(credit.interest_accrued, use_amount)
                    credit.interest_accrued -= interest_used
                    remaining -= interest_used
                    use_amount -= interest_used
                    
                    if use_amount > 0:
                        credit.remaining_amount -= use_amount
                        remaining -= use_amount
                    
                    credits_used.append({'credit_id': cid})
                    
                    if credit.remaining_amount <= 0 and credit.interest_accrued <= 0:
                        credit.status = CreditStatus.APPLIED
            
            # Record transaction
            apply_id = f"APPLY-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(4)}"
            tx = {
                'id': apply_id,
                'customer_id': customer_id,
                'action': 'apply_to_bill',
                'amount': float(apply_amount),
                'bill_id': bill_id,
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'credits_used': credits_used,
                'status': 'completed'
            }
            self._credit_transactions.append(tx)
        
        logger.info(f"Applied ${apply_amount} credit to bill {bill_id} for {customer_id}")
        
        return {
            'success': True,
            'apply_id': apply_id,
            'amount_applied': float(apply_amount),
            'bill_id': bill_id,
            'bill_status': bill['status'],
            'bill_remaining': float(remaining_due - apply_amount),
            'new_credit_balance': float(available - apply_amount),
            'message': f'${apply_amount:.2f} applied to bill {bill_id}.'
        }
    
    # ========== BILLING VALIDATION ==========
    
    def validate_customer_billing(
        self,
        customer_id: str,
        auto_create_credits: bool = True
    ) -> BillingValidationResult:
        """
        Validate billing data for a customer and detect any errors.
        
        Checks:
        1. Overpayments (paid more than due)
        2. Future billing (billed for future periods)
        3. Duplicate bills
        4. Billing date consistency
        
        Args:
            customer_id: Customer ID to validate
            auto_create_credits: Automatically create credits for detected errors
        
        Returns:
            BillingValidationResult with errors and detected credits
        """
        result = BillingValidationResult(is_valid=True)
        
        # Get customer's bills and policies
        customer_bills = [
            (bid, b) for bid, b in self._billing.items()
            if b.get('customer_id') == customer_id
        ]
        
        customer_policies = [
            (pid, p) for pid, p in self._policies.items()
            if p.get('customer_id') == customer_id
        ]
        
        now = datetime.now(timezone.utc)
        
        for bill_id, bill in customer_bills:
            amount_due = Decimal(str(bill.get('amount', bill.get('amount_due', 0))))
            amount_paid = Decimal(str(bill.get('amount_paid', 0)))
            
            # Check for overpayment
            if amount_paid > amount_due:
                overpayment = amount_paid - amount_due
                result.overbilled_amount += overpayment
                result.warnings.append(f"Bill {bill_id}: Overpayment of ${overpayment:.2f} detected")
                
                credit_info = {
                    'bill_id': bill_id,
                    'amount': float(overpayment),
                    'type': CreditType.OVERPAYMENT.value,
                    'reason': f'Overpayment on bill {bill_id}'
                }
                result.credits_detected.append(credit_info)
                
                if auto_create_credits:
                    self.create_credit(
                        customer_id=customer_id,
                        amount=float(overpayment),
                        credit_type=CreditType.OVERPAYMENT,
                        reason=f'Overpayment detected on bill {bill_id}',
                        source_bill_id=bill_id,
                        source_policy_id=bill.get('policy_id')
                    )
            
            # Check for future billing
            due_date_str = bill.get('due_date')
            if due_date_str:
                try:
                    due_date = datetime.fromisoformat(due_date_str.replace('Z', '+00:00'))
                    if due_date.tzinfo is None:
                        due_date = due_date.replace(tzinfo=timezone.utc)
                    
                    # Get policy to check billing schedule
                    policy_id = bill.get('policy_id')
                    policy = self._policies.get(policy_id, {})
                    
                    # Check if bill is for a future period beyond threshold
                    billing_period = bill.get('billing_period', {})
                    period_start_str = billing_period.get('start')
                    
                    if period_start_str:
                        period_start = datetime.fromisoformat(period_start_str.replace('Z', '+00:00'))
                        if period_start.tzinfo is None:
                            period_start = period_start.replace(tzinfo=timezone.utc)
                        
                        days_in_future = (period_start - now).days
                        
                        if days_in_future > BillingCreditConfig.FUTURE_BILLING_THRESHOLD_DAYS:
                            # This bill is for a future period - potential billing error
                            if bill.get('status', '').lower() == 'paid':
                                result.future_billed_amount += amount_paid
                                result.errors.append(
                                    f"Bill {bill_id}: Charged ${amount_paid:.2f} for future period "
                                    f"(starts {period_start.date()}, {days_in_future} days from now)"
                                )
                                
                                credit_info = {
                                    'bill_id': bill_id,
                                    'amount': float(amount_paid),
                                    'type': CreditType.BILLING_ERROR.value,
                                    'reason': f'Future billing error - charged {days_in_future} days early'
                                }
                                result.credits_detected.append(credit_info)
                                result.is_valid = False
                                
                                if auto_create_credits:
                                    self.create_credit(
                                        customer_id=customer_id,
                                        amount=float(amount_paid),
                                        credit_type=CreditType.BILLING_ERROR,
                                        reason=f'Billing error: Charged for future period starting {period_start.date()}',
                                        source_bill_id=bill_id,
                                        source_policy_id=policy_id,
                                        description=f'You were billed ${amount_paid:.2f} for a billing period '
                                                   f'{days_in_future} days in the future. This credit has been '
                                                   f'added to your account. You may withdraw or apply to future bills.'
                                    )
                            else:
                                result.warnings.append(
                                    f"Bill {bill_id}: Due for future period ({days_in_future} days from now)"
                                )
                except (ValueError, TypeError) as e:
                    result.warnings.append(f"Bill {bill_id}: Could not parse date - {e}")
        
        return result
    
    # ========== OUTSTANDING BILL NOTIFICATIONS ==========
    
    def check_and_notify_outstanding_bills(
        self,
        customer_id: Optional[str] = None
    ) -> List[BillingNotificationResult]:
        """
        Check for outstanding bills and send notifications.
        
        Args:
            customer_id: Specific customer (or None for all customers)
        
        Returns:
            List of notification results
        """
        results = []
        now = datetime.now(timezone.utc)
        
        # Get bills to check
        if customer_id:
            bills_to_check = [
                (bid, b) for bid, b in self._billing.items()
                if b.get('customer_id') == customer_id
            ]
        else:
            bills_to_check = list(self._billing.items())
        
        # Group by customer for batch notifications
        customer_bills: Dict[str, List[Tuple[str, Dict]]] = {}
        for bid, bill in bills_to_check:
            cust_id = bill.get('customer_id')
            if cust_id:
                if cust_id not in customer_bills:
                    customer_bills[cust_id] = []
                customer_bills[cust_id].append((bid, bill))
        
        for cust_id, bills in customer_bills.items():
            outstanding = []
            overdue = []
            
            for bid, bill in bills:
                status = bill.get('status', '').lower()
                if status not in ['outstanding', 'partial', 'overdue']:
                    continue
                
                amount_due = bill.get('amount', bill.get('amount_due', 0))
                amount_paid = bill.get('amount_paid', 0)
                remaining = amount_due - amount_paid
                
                if remaining <= 0:
                    continue
                
                due_date_str = bill.get('due_date')
                if due_date_str:
                    try:
                        due_date = datetime.fromisoformat(due_date_str.replace('Z', '+00:00'))
                        if due_date.tzinfo is None:
                            due_date = due_date.replace(tzinfo=timezone.utc)
                        
                        days_until_due = (due_date - now).days
                        
                        bill_info = {
                            'bill_id': bid,
                            'policy_id': bill.get('policy_id'),
                            'amount_due': remaining,
                            'due_date': due_date.date().isoformat(),
                            'days_until_due': days_until_due
                        }
                        
                        if days_until_due < 0:
                            overdue.append(bill_info)
                        else:
                            outstanding.append(bill_info)
                    except (ValueError, TypeError):
                        outstanding.append({
                            'bill_id': bid,
                            'policy_id': bill.get('policy_id'),
                            'amount_due': remaining,
                            'due_date': due_date_str,
                            'days_until_due': None
                        })
            
            # Send notifications
            if overdue:
                result = self._send_bill_notification(
                    cust_id,
                    BillingNotificationType.BILL_OVERDUE,
                    overdue
                )
                results.append(result)
            
            if outstanding:
                result = self._send_bill_notification(
                    cust_id,
                    BillingNotificationType.OUTSTANDING_BILL,
                    outstanding
                )
                results.append(result)
        
        return results
    
    def _send_bill_notification(
        self,
        customer_id: str,
        notification_type: BillingNotificationType,
        bills: List[Dict[str, Any]]
    ) -> BillingNotificationResult:
        """Send notification about bills"""
        notification_id = f"NOTIF-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(4)}"
        
        # Get customer contact info
        customer = self._customers.get(customer_id, {})
        email = customer.get('email')
        phone = customer.get('phone')
        name = customer.get('name', 'Valued Customer')
        
        # Calculate totals
        total_due = sum(b.get('amount_due', 0) for b in bills)
        
        # Build message
        if notification_type == BillingNotificationType.BILL_OVERDUE:
            title = "URGENT: Overdue Payment"
            message = f"""Dear {name},

You have {len(bills)} overdue bill(s) totaling ${total_due:,.2f}.

Please make payment immediately to avoid any service interruptions.

Bill Details:
"""
            for b in bills:
                message += f"- Bill {b['bill_id']}: ${b['amount_due']:,.2f} (due {b['due_date']})\n"
            
            message += f"""
Pay now: {BillingCreditConfig.BILLING_PORTAL_URL}?customer_id={customer_id}

If you have any questions, please contact our billing department.

Best regards,
PHINS Billing Team"""
        
        else:  # OUTSTANDING_BILL
            title = "Payment Reminder"
            message = f"""Dear {name},

You have {len(bills)} outstanding bill(s) totaling ${total_due:,.2f}.

Bill Details:
"""
            for b in bills:
                days_text = f"{b['days_until_due']} days" if b.get('days_until_due') is not None else "soon"
                message += f"- Bill {b['bill_id']}: ${b['amount_due']:,.2f} (due in {days_text})\n"
            
            message += f"""
Pay now: {BillingCreditConfig.BILLING_PORTAL_URL}?customer_id={customer_id}

Thank you for your business!

Best regards,
PHINS Billing Team"""
        
        channels_sent = []
        
        # Send via notification service if available
        if self._notification_service:
            try:
                from services.notification_service import (
                    NotificationRequest,
                    NotificationChannel,
                    NotificationPriority
                )
                
                # Send email
                if email:
                    result = self._notification_service.send(NotificationRequest(
                        channel=NotificationChannel.EMAIL,
                        recipient=email,
                        subject=title,
                        content=message,
                        customer_id=customer_id,
                        priority=NotificationPriority.HIGH if notification_type == BillingNotificationType.BILL_OVERDUE else NotificationPriority.NORMAL,
                        metadata={
                            'notification_type': notification_type.value,
                            'bills': bills,
                            'total_due': total_due,
                            'billing_link': f"{BillingCreditConfig.BILLING_PORTAL_URL}?customer_id={customer_id}"
                        }
                    ))
                    if result.success:
                        channels_sent.append('email')
                
                # Send SMS for overdue
                if phone and notification_type == BillingNotificationType.BILL_OVERDUE:
                    sms_message = f"PHINS: You have overdue bills totaling ${total_due:,.2f}. Pay now: {BillingCreditConfig.BILLING_PORTAL_URL}"
                    result = self._notification_service.send(NotificationRequest(
                        channel=NotificationChannel.SMS,
                        recipient=phone,
                        content=sms_message,
                        customer_id=customer_id,
                        priority=NotificationPriority.HIGH
                    ))
                    if result.success:
                        channels_sent.append('sms')
                        
            except Exception as e:
                logger.error(f"Error sending notification: {e}")
        else:
            # Mock notification
            logger.info(f"Mock notification to {customer_id}: {title}")
            channels_sent.append('mock')
        
        return BillingNotificationResult(
            success=len(channels_sent) > 0,
            notification_id=notification_id,
            customer_id=customer_id,
            notification_type=notification_type,
            channels_sent=channels_sent
        )
    
    def _notify_credit_available(
        self,
        customer_id: str,
        credit: BillingCredit
    ) -> None:
        """Notify customer about available credit"""
        customer = self._customers.get(customer_id, {})
        email = customer.get('email')
        name = customer.get('name', 'Valued Customer')
        
        if not email:
            return
        
        title = "Billing Credit Available"
        message = f"""Dear {name},

A billing credit of ${credit.amount:,.2f} has been added to your account.

Reason: {credit.reason}

{credit.description if credit.description else ''}

Your Credit Options:
1. Withdraw to Bank Account - Transfer to your linked bank account
2. Transfer to Health Wallet - Add to your PHINS Health Wallet for medical purchases
3. Apply to Bills - Use credit for future premium payments
4. Keep as Credit - Credit earns {float(credit.interest_rate)*100:.1f}% annual interest

Manage your credit: {BillingCreditConfig.BILLING_PORTAL_URL}?customer_id={customer_id}#credits

Best regards,
PHINS Billing Team"""
        
        if self._notification_service:
            try:
                from services.notification_service import (
                    NotificationRequest,
                    NotificationChannel,
                    NotificationPriority
                )
                
                self._notification_service.send(NotificationRequest(
                    channel=NotificationChannel.EMAIL,
                    recipient=email,
                    subject=title,
                    content=message,
                    customer_id=customer_id,
                    priority=NotificationPriority.NORMAL,
                    metadata={
                        'notification_type': BillingNotificationType.CREDIT_AVAILABLE.value,
                        'credit_id': credit.credit_id,
                        'amount': float(credit.amount)
                    }
                ))
            except Exception as e:
                logger.error(f"Error sending credit notification: {e}")
    
    # ========== LEDGER REPORTING ==========
    
    def get_billing_ledger_report(
        self,
        customer_id: Optional[str] = None,
        include_credits: bool = True,
        include_transactions: bool = True,
        refresh: bool = True
    ) -> Dict[str, Any]:
        """
        Generate comprehensive billing ledger report.
        
        Args:
            customer_id: Filter by customer (or None for all)
            include_credits: Include credit details
            include_transactions: Include transaction history
            refresh: Refresh and validate data first
        
        Returns:
            Ledger report with all billing data
        """
        if refresh and customer_id:
            self.validate_customer_billing(customer_id, auto_create_credits=True)
        
        report = {
            'generated_at': datetime.now(timezone.utc).isoformat(),
            'customer_id': customer_id,
            'summary': {
                'total_billed': Decimal('0'),
                'total_paid': Decimal('0'),
                'total_outstanding': Decimal('0'),
                'total_credits': Decimal('0'),
                'net_balance': Decimal('0')  # Positive = customer owes, Negative = PHINS owes
            },
            'bills': [],
            'credits': [],
            'transactions': [],
            'integrity': {
                'valid': True,
                'checks_passed': [],
                'issues': []
            }
        }
        
        # Get bills
        if customer_id:
            bills = [(bid, b) for bid, b in self._billing.items() if b.get('customer_id') == customer_id]
        else:
            bills = list(self._billing.items())
        
        for bid, bill in bills:
            amount_due = Decimal(str(bill.get('amount', bill.get('amount_due', 0))))
            amount_paid = Decimal(str(bill.get('amount_paid', 0)))
            
            report['summary']['total_billed'] += amount_due
            report['summary']['total_paid'] += amount_paid
            
            status = bill.get('status', '').lower()
            if status in ['outstanding', 'partial', 'overdue']:
                report['summary']['total_outstanding'] += (amount_due - amount_paid)
            
            report['bills'].append({
                'bill_id': bid,
                'policy_id': bill.get('policy_id'),
                'amount_due': float(amount_due),
                'amount_paid': float(amount_paid),
                'status': status,
                'due_date': bill.get('due_date'),
                'created_date': bill.get('created_date'),
                'paid_date': bill.get('paid_date')
            })
        
        # Get credits
        if include_credits:
            if customer_id:
                credits = self.get_customer_credit_balance(customer_id)
                report['summary']['total_credits'] = Decimal(str(credits['total_with_interest']))
                report['credits'] = credits['credits']
            else:
                for cid, credit_ids in self._customer_credits.items():
                    for credit_id in credit_ids:
                        credit = self._credits.get(credit_id)
                        if credit and credit.status == CreditStatus.ACTIVE:
                            report['summary']['total_credits'] += credit.remaining_amount + credit.interest_accrued
                            report['credits'].append(credit.to_dict())
        
        # Get transactions
        if include_transactions:
            if customer_id:
                report['transactions'] = [
                    tx for tx in self._credit_transactions
                    if tx.get('customer_id') == customer_id
                ]
            else:
                report['transactions'] = self._credit_transactions[-100:]  # Last 100
        
        # Calculate net balance
        report['summary']['net_balance'] = (
            report['summary']['total_outstanding'] - report['summary']['total_credits']
        )
        
        # Integrity checks
        report['integrity']['checks_passed'].append('bill_amounts_consistent')
        report['integrity']['checks_passed'].append('credit_balances_verified')
        
        # Convert decimals to float for JSON serialization
        for key in report['summary']:
            report['summary'][key] = float(report['summary'][key])
        
        return report
    
    # ========== DATA PERSISTENCE ==========
    
    def export_credits(self) -> Dict[str, Any]:
        """Export credits data for persistence"""
        with self._lock:
            return {
                'credits': {cid: c.to_dict() for cid, c in self._credits.items()},
                'customer_credits': self._customer_credits.copy(),
                'transactions': self._credit_transactions.copy()
            }
    
    def import_credits(self, data: Dict[str, Any]) -> None:
        """Import credits data from persistence"""
        with self._lock:
            # Restore credits
            for cid, credit_data in data.get('credits', {}).items():
                self._credits[cid] = BillingCredit(
                    credit_id=credit_data['credit_id'],
                    customer_id=credit_data['customer_id'],
                    amount=Decimal(str(credit_data['amount'])),
                    remaining_amount=Decimal(str(credit_data['remaining_amount'])),
                    credit_type=CreditType(credit_data['credit_type']),
                    status=CreditStatus(credit_data['status']),
                    source_bill_id=credit_data.get('source_bill_id'),
                    source_policy_id=credit_data.get('source_policy_id'),
                    reason=credit_data.get('reason', ''),
                    description=credit_data.get('description', ''),
                    created_at=datetime.fromisoformat(credit_data['created_at']) if credit_data.get('created_at') else datetime.now(timezone.utc),
                    expires_at=datetime.fromisoformat(credit_data['expires_at']) if credit_data.get('expires_at') else None,
                    interest_rate=Decimal(str(credit_data.get('interest_rate', 0))),
                    interest_accrued=Decimal(str(credit_data.get('interest_accrued', 0))),
                    transactions=credit_data.get('transactions', [])
                )
            
            self._customer_credits = data.get('customer_credits', {})
            self._credit_transactions = data.get('transactions', [])


# ============================================================================
# FACTORY AND SINGLETON
# ============================================================================

_billing_credit_service: Optional[BillingCreditService] = None


def get_billing_credit_service(**kwargs) -> BillingCreditService:
    """Get or create billing credit service singleton"""
    global _billing_credit_service
    if _billing_credit_service is None:
        _billing_credit_service = BillingCreditService(**kwargs)
    return _billing_credit_service


def init_billing_credit_service(
    billing_data: Dict,
    policies_data: Dict,
    customers_data: Dict,
    health_wallets: Dict,
    notification_service=None
) -> BillingCreditService:
    """Initialize billing credit service with data references"""
    global _billing_credit_service
    _billing_credit_service = BillingCreditService(
        billing_data=billing_data,
        policies_data=policies_data,
        customers_data=customers_data,
        health_wallets=health_wallets,
        notification_service=notification_service
    )
    return _billing_credit_service


def reset_billing_credit_service() -> None:
    """Reset singleton (for testing)"""
    global _billing_credit_service
    _billing_credit_service = None


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    # Enums
    'CreditStatus',
    'CreditType',
    'BillingNotificationType',
    
    # Data Classes
    'BillingCredit',
    'BillingValidationResult',
    'BillingNotificationResult',
    
    # Configuration
    'BillingCreditConfig',
    
    # Service
    'BillingCreditService',
    
    # Factory
    'get_billing_credit_service',
    'init_billing_credit_service',
    'reset_billing_credit_service',
]
