"""
PHINS Billing Service
=====================
Enhanced billing service with premium allocation tracking.

When a bill is paid, the premium is automatically split into:
- Risk Premium: Goes to company risk reserves (covers claims)
- Savings Premium: Goes to customer's savings (wallet/investment)

Default split is 75% risk / 25% savings (configurable per policy).
"""

from datetime import datetime, timedelta
from typing import Dict, Any, Optional, Callable
import logging

logger = logging.getLogger(__name__)


class BillingService:
    """
    Enhanced billing service with premium allocation tracking.
    
    Features:
    - Bill creation with premium split configuration
    - Payment recording with automatic allocation
    - Integration with premium allocation tracker
    - Late fee application
    """
    
    def __init__(self, 
                 bills: Dict[str, Any],
                 policies: Dict[str, Any] = None,
                 premium_allocation_tracker=None):
        """
        Initialize billing service.
        
        Args:
            bills: Reference to bills data store
            policies: Reference to policies data store (for customer lookup)
            premium_allocation_tracker: Optional tracker for recording allocations
        """
        self._bills = bills
        self._policies = policies or {}
        self._allocation_tracker = premium_allocation_tracker
        
        # Default allocation percentages
        self.default_risk_pct = 75.0
        self.default_savings_pct = 25.0

    def create_bill(self, 
                    policy_id: str, 
                    amount_due: float, 
                    due_days: int = 30,
                    customer_id: str = None,
                    risk_pct: float = None,
                    savings_pct: float = None,
                    description: str = None) -> Dict[str, Any]:
        """
        Create a new bill with premium allocation configuration.
        
        Args:
            policy_id: Associated policy ID
            amount_due: Total amount due
            due_days: Days until due
            customer_id: Customer ID (will be looked up from policy if not provided)
            risk_pct: Risk allocation percentage (default 75%)
            savings_pct: Savings allocation percentage (default 25%)
            description: Bill description
        
        Returns:
            Created bill record
        """
        bill_id = f"BILL{len(self._bills) + 1:06d}"
        
        # Get customer ID from policy if not provided
        if not customer_id and policy_id:
            policy = self._policies.get(policy_id, {})
            customer_id = policy.get('customer_id', '')
        
        # Set allocation percentages
        risk_pct = risk_pct if risk_pct is not None else self.default_risk_pct
        savings_pct = savings_pct if savings_pct is not None else self.default_savings_pct
        
        # Ensure they sum to 100
        if risk_pct + savings_pct != 100:
            savings_pct = 100 - risk_pct
        
        # Calculate allocation amounts
        amount = float(amount_due)
        risk_amount = round(amount * risk_pct / 100, 2)
        savings_amount = round(amount * savings_pct / 100, 2)
        
        bill = {
            'bill_id': bill_id,
            'policy_id': policy_id,
            'customer_id': customer_id,
            'amount_due': amount,
            'amount_paid': 0.0,
            'status': 'outstanding',
            'due_date': (datetime.now() + timedelta(days=due_days)).date().isoformat(),
            'description': description or f'Premium bill for policy {policy_id}',
            
            # Premium allocation configuration
            'premium_allocation': {
                'risk_percentage': risk_pct,
                'savings_percentage': savings_pct,
                'risk_amount_due': risk_amount,
                'savings_amount_due': savings_amount,
                'risk_amount_paid': 0.0,
                'savings_amount_paid': 0.0,
                'allocated': False,
                'allocation_id': None
            },
            
            'created_at': datetime.now().isoformat(),
            'updated_at': datetime.now().isoformat(),
        }
        self._bills[bill_id] = bill
        
        logger.info(f"Created bill {bill_id}: ${amount:.2f} ({risk_pct}% risk / {savings_pct}% savings)")
        
        return bill

    def record_payment(self, 
                       bill_id: str, 
                       amount: float,
                       auto_allocate: bool = True) -> Optional[Dict[str, Any]]:
        """
        Record a payment and optionally trigger premium allocation.
        
        Args:
            bill_id: Bill being paid
            amount: Payment amount
            auto_allocate: If True, automatically record premium allocation
        
        Returns:
            Updated bill record with allocation details
        """
        b = self._bills.get(bill_id)
        if not b:
            return None
        
        # Update payment amount
        prev_paid = float(b.get('amount_paid', 0.0))
        was_already_paid = b.get('status') == 'paid'
        b['amount_paid'] = round(prev_paid + float(amount), 2)
        
        # Update status
        if b['amount_paid'] >= b['amount_due']:
            b['status'] = 'paid'
            b['paid_date'] = datetime.now().isoformat()
            # Update balance sheet in real-time on status transition to paid
            if not was_already_paid:
                try:
                    from server import record_premium_revenue
                    record_premium_revenue(
                        customer_id=b.get('customer_id', ''),
                        policy_id=b.get('policy_id', ''),
                        amount=float(amount),
                        description=f"Premium payment for bill {bill_id}"
                    )
                except (ImportError, AttributeError, Exception) as e:
                    logger.warning(f"Could not update balance sheet for bill {bill_id}: {e}")
        elif b['amount_paid'] > 0:
            b['status'] = 'partial'
        
        b['updated_at'] = datetime.now().isoformat()
        
        # Calculate allocation amounts for this payment
        allocation = b.get('premium_allocation', {})
        risk_pct = allocation.get('risk_percentage', self.default_risk_pct)
        savings_pct = allocation.get('savings_percentage', self.default_savings_pct)
        
        payment_risk = round(float(amount) * risk_pct / 100, 2)
        payment_savings = round(float(amount) * savings_pct / 100, 2)
        
        # Update allocation tracking on the bill
        allocation['risk_amount_paid'] = round(
            float(allocation.get('risk_amount_paid', 0)) + payment_risk, 2)
        allocation['savings_amount_paid'] = round(
            float(allocation.get('savings_amount_paid', 0)) + payment_savings, 2)
        
        b['premium_allocation'] = allocation
        
        # Record in premium allocation tracker if available and bill is fully paid
        if auto_allocate and self._allocation_tracker and b['status'] == 'paid':
            try:
                alloc_record = self._allocation_tracker.record_bill_allocation(
                    bill_id=bill_id,
                    policy_id=b.get('policy_id', ''),
                    customer_id=b.get('customer_id', ''),
                    bill_amount=b['amount_paid'],
                    payment_date=datetime.now().isoformat(),
                    risk_percentage=risk_pct,
                    savings_percentage=savings_pct,
                    auto_allocate_savings=True
                )
                allocation['allocated'] = True
                allocation['allocation_id'] = alloc_record.allocation_id
                b['premium_allocation'] = allocation
                
                logger.info(f"Recorded allocation for bill {bill_id}: ${payment_risk:.2f} risk, ${payment_savings:.2f} savings")
            except Exception as e:
                logger.error(f"Failed to record allocation for bill {bill_id}: {e}")
        
        return b

    def apply_late_fee(self, bill_id: str, pct: float = 5.0) -> Optional[Dict[str, Any]]:
        """
        Apply late fee to overdue bill.
        
        Args:
            bill_id: Bill to apply fee to
            pct: Late fee percentage (default 5%)
        
        Returns:
            Updated bill record
        """
        b = self._bills.get(bill_id)
        if not b:
            return None
        
        # Apply only if overdue and not paid
        try:
            due = datetime.fromisoformat(b['due_date'])
        except Exception:
            return b
        
        if b.get('status') != 'paid' and datetime.now().date() > due.date():
            old_amount = b['amount_due']
            b['amount_due'] = round(b['amount_due'] * (1 + pct / 100.0), 2)
            b['status'] = 'overdue'
            b['updated_at'] = datetime.now().isoformat()
            
            # Recalculate allocation amounts
            allocation = b.get('premium_allocation', {})
            risk_pct = allocation.get('risk_percentage', self.default_risk_pct)
            savings_pct = allocation.get('savings_percentage', self.default_savings_pct)
            allocation['risk_amount_due'] = round(b['amount_due'] * risk_pct / 100, 2)
            allocation['savings_amount_due'] = round(b['amount_due'] * savings_pct / 100, 2)
            b['premium_allocation'] = allocation
            
            # Track fee applied
            if 'late_fees' not in b:
                b['late_fees'] = []
            b['late_fees'].append({
                'applied_date': datetime.now().isoformat(),
                'percentage': pct,
                'amount_added': round(b['amount_due'] - old_amount, 2)
            })
            
            logger.info(f"Applied {pct}% late fee to bill {bill_id}")
        
        return b
    
    def get_bill_allocation_summary(self, bill_id: str) -> Optional[Dict[str, Any]]:
        """
        Get allocation summary for a specific bill.
        
        Returns detailed breakdown of how the premium was/will be split.
        """
        b = self._bills.get(bill_id)
        if not b:
            return None
        
        allocation = b.get('premium_allocation', {})
        
        return {
            'bill_id': bill_id,
            'policy_id': b.get('policy_id'),
            'customer_id': b.get('customer_id'),
            'status': b.get('status'),
            'total_amount': b.get('amount_due'),
            'total_paid': b.get('amount_paid'),
            
            'allocation': {
                'risk_percentage': allocation.get('risk_percentage', 75),
                'savings_percentage': allocation.get('savings_percentage', 25),
                
                'risk_amount_due': allocation.get('risk_amount_due', 0),
                'risk_amount_paid': allocation.get('risk_amount_paid', 0),
                
                'savings_amount_due': allocation.get('savings_amount_due', 0),
                'savings_amount_paid': allocation.get('savings_amount_paid', 0),
                
                'allocated_to_tracker': allocation.get('allocated', False),
                'allocation_id': allocation.get('allocation_id')
            },
            
            'interpretation': {
                'risk_goes_to': 'Company Risk Reserves (for claims coverage)',
                'savings_goes_to': 'Customer Savings (wallet + investments)'
            }
        }
    
    def get_customer_billing_summary(self, customer_id: str) -> Dict[str, Any]:
        """
        Get billing and allocation summary for a customer across all bills.
        
        Shows total risk allocated and savings allocated from all bills.
        """
        bills = [b for b in self._bills.values() if b.get('customer_id') == customer_id]
        
        summary = {
            'customer_id': customer_id,
            'total_bills': len(bills),
            'paid_bills': 0,
            'outstanding_bills': 0,
            'total_billed': 0.0,
            'total_paid': 0.0,
            'total_outstanding': 0.0,
            
            'allocation_summary': {
                'total_risk_allocated': 0.0,
                'total_savings_allocated': 0.0,
                'total_risk_pending': 0.0,
                'total_savings_pending': 0.0
            },
            
            'bills': []
        }
        
        for b in bills:
            allocation = b.get('premium_allocation', {})
            
            summary['total_billed'] += b.get('amount_due', 0)
            summary['total_paid'] += b.get('amount_paid', 0)
            
            if b.get('status') == 'paid':
                summary['paid_bills'] += 1
                summary['allocation_summary']['total_risk_allocated'] += allocation.get('risk_amount_paid', 0)
                summary['allocation_summary']['total_savings_allocated'] += allocation.get('savings_amount_paid', 0)
            else:
                summary['outstanding_bills'] += 1
                summary['allocation_summary']['total_risk_pending'] += allocation.get('risk_amount_due', 0) - allocation.get('risk_amount_paid', 0)
                summary['allocation_summary']['total_savings_pending'] += allocation.get('savings_amount_due', 0) - allocation.get('savings_amount_paid', 0)
            
            summary['bills'].append({
                'bill_id': b.get('bill_id'),
                'policy_id': b.get('policy_id'),
                'amount_due': b.get('amount_due'),
                'amount_paid': b.get('amount_paid'),
                'status': b.get('status'),
                'risk_paid': allocation.get('risk_amount_paid', 0),
                'savings_paid': allocation.get('savings_amount_paid', 0)
            })
        
        summary['total_outstanding'] = round(summary['total_billed'] - summary['total_paid'], 2)
        
        # Round all values
        for key in ['total_billed', 'total_paid', 'total_outstanding']:
            summary[key] = round(summary[key], 2)
        for key in summary['allocation_summary']:
            summary['allocation_summary'][key] = round(summary['allocation_summary'][key], 2)
        
        return summary
    
    def set_allocation_tracker(self, tracker):
        """Set the premium allocation tracker for recording allocations"""
        self._allocation_tracker = tracker
    
    def set_policies(self, policies: Dict[str, Any]):
        """Set the policies reference for customer lookup"""
        self._policies = policies
