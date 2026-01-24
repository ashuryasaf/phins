"""
PHINS Premium Allocation Tracker Service
==========================================
Central tracking for premium allocations across bills and policies.

This service ensures:
1. Risk premiums sum up properly to Risk Reserves
2. Savings premiums are tracked and allocated properly
3. Customer-level aggregation across multiple policies and bills

Premium Flow:
    Bill Payment → Premium Allocation → Risk Reserve + Savings Allocation
                                              ↓              ↓
                                    Claims Reserve     Wallet/Investment
                                              ↓              ↓
                                    Paid Claims        Customer Savings

Key Calculations:
- Risk Reserve = Sum of all Risk Premiums - Paid Claims
- Claims Reserve = Estimated Outstanding Claims (calculated from loss ratio)
- Net Risk Reserve = Risk Reserve - Claims Reserve
- Total Customer Savings = Sum of Savings Allocations + Investment Returns
"""

from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field, asdict
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class AllocationStatus(str, Enum):
    """Status of premium allocation"""
    PENDING = "pending"
    ALLOCATED = "allocated"
    PARTIAL = "partial"
    REVERSED = "reversed"


@dataclass
class BillPremiumAllocation:
    """
    Tracks premium allocation for a single bill payment.
    
    Each bill payment is split into risk and savings components
    based on the policy's allocation percentage.
    """
    allocation_id: str
    bill_id: str
    policy_id: str
    customer_id: str
    
    # Bill details
    bill_amount: Decimal
    payment_date: str
    
    # Allocation percentages
    risk_percentage: Decimal  # e.g., 75 for 75%
    savings_percentage: Decimal  # e.g., 25 for 25%
    
    # Calculated amounts
    risk_amount: Decimal = field(default_factory=Decimal)
    savings_amount: Decimal = field(default_factory=Decimal)
    
    # Savings breakdown (where the savings went)
    wallet_amount: Decimal = field(default_factory=Decimal)
    investment_amount: Decimal = field(default_factory=Decimal)
    algo_trading_amount: Decimal = field(default_factory=Decimal)
    
    # Status
    status: AllocationStatus = AllocationStatus.PENDING
    allocated_at: Optional[str] = None
    
    # Metadata
    created_at: str = ""
    notes: str = ""
    
    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().isoformat()
        
        # Calculate amounts from percentages
        if self.risk_amount == Decimal(0) and self.bill_amount > 0:
            self.risk_amount = (self.bill_amount * self.risk_percentage / Decimal(100)).quantize(
                Decimal('0.01'), rounding=ROUND_HALF_UP)
            self.savings_amount = (self.bill_amount * self.savings_percentage / Decimal(100)).quantize(
                Decimal('0.01'), rounding=ROUND_HALF_UP)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'allocation_id': self.allocation_id,
            'bill_id': self.bill_id,
            'policy_id': self.policy_id,
            'customer_id': self.customer_id,
            'bill_amount': float(self.bill_amount),
            'payment_date': self.payment_date,
            'risk_percentage': float(self.risk_percentage),
            'savings_percentage': float(self.savings_percentage),
            'risk_amount': float(self.risk_amount),
            'savings_amount': float(self.savings_amount),
            'wallet_amount': float(self.wallet_amount),
            'investment_amount': float(self.investment_amount),
            'algo_trading_amount': float(self.algo_trading_amount),
            'status': self.status.value,
            'allocated_at': self.allocated_at,
            'created_at': self.created_at,
            'notes': self.notes
        }


@dataclass
class CustomerAllocationSummary:
    """
    Aggregated allocation summary for a customer across all policies and bills.
    """
    customer_id: str
    
    # Bill counts
    total_bills: int = 0
    paid_bills: int = 0
    
    # Policy counts  
    total_policies: int = 0
    active_policies: int = 0
    
    # Premium totals
    total_premiums_billed: Decimal = field(default_factory=Decimal)
    total_premiums_paid: Decimal = field(default_factory=Decimal)
    
    # Risk allocation totals
    total_risk_allocated: Decimal = field(default_factory=Decimal)
    
    # Savings allocation totals
    total_savings_allocated: Decimal = field(default_factory=Decimal)
    total_wallet_balance: Decimal = field(default_factory=Decimal)
    total_investment_balance: Decimal = field(default_factory=Decimal)
    total_algo_trading_balance: Decimal = field(default_factory=Decimal)
    investment_returns: Decimal = field(default_factory=Decimal)
    
    # Per-policy breakdown
    policy_allocations: List[Dict] = field(default_factory=list)
    
    # Timestamps
    last_updated: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'customer_id': self.customer_id,
            'total_bills': self.total_bills,
            'paid_bills': self.paid_bills,
            'total_policies': self.total_policies,
            'active_policies': self.active_policies,
            'total_premiums_billed': float(self.total_premiums_billed),
            'total_premiums_paid': float(self.total_premiums_paid),
            'total_risk_allocated': float(self.total_risk_allocated),
            'total_savings_allocated': float(self.total_savings_allocated),
            'total_wallet_balance': float(self.total_wallet_balance),
            'total_investment_balance': float(self.total_investment_balance),
            'total_algo_trading_balance': float(self.total_algo_trading_balance),
            'investment_returns': float(self.investment_returns),
            'total_savings_value': float(
                self.total_wallet_balance + 
                self.total_investment_balance + 
                self.total_algo_trading_balance +
                self.investment_returns
            ),
            'policy_allocations': self.policy_allocations,
            'last_updated': self.last_updated
        }


@dataclass
class RiskReserveReport:
    """
    Risk reserve calculation report with claims and payments.
    
    Formula:
    Net Risk Reserve = Total Risk Premiums - Paid Claims - Claims Reserve
    
    Where:
    - Total Risk Premiums = Sum of all risk_amount from allocations
    - Paid Claims = Sum of all approved/paid claim amounts
    - Claims Reserve = Estimated reserve for pending claims
    """
    report_date: str
    
    # Risk Premium totals
    total_risk_premiums: Decimal = field(default_factory=Decimal)
    risk_premiums_by_period: Dict[str, Decimal] = field(default_factory=dict)
    
    # Claims
    paid_claims_total: Decimal = field(default_factory=Decimal)
    claims_reserve: Decimal = field(default_factory=Decimal)  # For pending claims
    
    # Calculated reserves
    gross_risk_reserve: Decimal = field(default_factory=Decimal)  # Before claims
    net_risk_reserve: Decimal = field(default_factory=Decimal)    # After claims
    
    # Loss metrics
    loss_ratio: Decimal = field(default_factory=Decimal)  # Claims / Premiums
    reserve_ratio: Decimal = field(default_factory=Decimal)  # Reserve / Premiums
    
    # Wallet integration
    total_wallet_balance: Decimal = field(default_factory=Decimal)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'report_date': self.report_date,
            'total_risk_premiums': float(self.total_risk_premiums),
            'risk_premiums_by_period': {k: float(v) for k, v in self.risk_premiums_by_period.items()},
            'paid_claims_total': float(self.paid_claims_total),
            'claims_reserve': float(self.claims_reserve),
            'gross_risk_reserve': float(self.gross_risk_reserve),
            'net_risk_reserve': float(self.net_risk_reserve),
            'loss_ratio_pct': float(self.loss_ratio * 100),
            'reserve_ratio_pct': float(self.reserve_ratio * 100),
            'total_wallet_balance': float(self.total_wallet_balance),
            'risk_reserve_health': 'healthy' if self.net_risk_reserve > 0 else 'warning' if self.net_risk_reserve > -10000 else 'critical'
        }


class PremiumAllocationTracker:
    """
    Central service for tracking premium allocations.
    
    This service:
    1. Records all premium allocations from bill payments
    2. Aggregates allocations by customer, policy, and period
    3. Calculates risk reserves with claims integration
    4. Tracks savings allocations to wallets and investments
    """
    
    def __init__(self, 
                 bills: Dict = None,
                 policies: Dict = None, 
                 claims: Dict = None,
                 customers: Dict = None,
                 health_wallets: Dict = None,
                 investment_accounts: Dict = None):
        """
        Initialize tracker with references to data stores.
        
        Args:
            bills: Reference to billing data
            policies: Reference to policies data
            claims: Reference to claims data
            customers: Reference to customers data
            health_wallets: Reference to wallet data
            investment_accounts: Reference to investment accounts
        """
        # Use 'if X is None' pattern to preserve empty dict references
        self.bills = bills if bills is not None else {}
        self.policies = policies if policies is not None else {}
        self.claims = claims if claims is not None else {}
        self.customers = customers if customers is not None else {}
        self.health_wallets = health_wallets if health_wallets is not None else {}
        self.investment_accounts = investment_accounts if investment_accounts is not None else {}
        
        # Internal tracking
        self.allocations: Dict[str, BillPremiumAllocation] = {}
        self.allocation_counter = 0
        
        # Default allocation percentages (can be overridden per policy)
        self.default_risk_percentage = Decimal('75')
        self.default_savings_percentage = Decimal('25')
        
        # Savings sub-allocation defaults
        self.savings_wallet_pct = Decimal('15')
        self.savings_investment_pct = Decimal('60')
        self.savings_algo_pct = Decimal('25')
    
    def record_bill_allocation(self, 
                               bill_id: str,
                               policy_id: str, 
                               customer_id: str,
                               bill_amount: float,
                               payment_date: str = None,
                               risk_percentage: float = None,
                               savings_percentage: float = None,
                               auto_allocate_savings: bool = True) -> BillPremiumAllocation:
        """
        Record a premium allocation when a bill is paid.
        
        Args:
            bill_id: The bill being paid
            policy_id: Associated policy
            customer_id: Customer making payment
            bill_amount: Amount being paid
            payment_date: Date of payment (defaults to now)
            risk_percentage: Override risk allocation % (0-100)
            savings_percentage: Override savings allocation % (0-100)
            auto_allocate_savings: If True, automatically allocate savings to wallet/investment
        
        Returns:
            BillPremiumAllocation record
        """
        self.allocation_counter += 1
        allocation_id = f"ALLOC-{self.allocation_counter:06d}"
        
        # Get allocation percentages
        risk_pct = Decimal(str(risk_percentage)) if risk_percentage is not None else self.default_risk_percentage
        savings_pct = Decimal(str(savings_percentage)) if savings_percentage is not None else self.default_savings_percentage
        
        # Ensure they sum to 100
        if risk_pct + savings_pct != Decimal('100'):
            savings_pct = Decimal('100') - risk_pct
        
        allocation = BillPremiumAllocation(
            allocation_id=allocation_id,
            bill_id=bill_id,
            policy_id=policy_id,
            customer_id=customer_id,
            bill_amount=Decimal(str(bill_amount)),
            payment_date=payment_date or datetime.now().isoformat(),
            risk_percentage=risk_pct,
            savings_percentage=savings_pct
        )
        
        # Auto-allocate savings if requested
        if auto_allocate_savings and allocation.savings_amount > 0:
            self._allocate_savings(allocation)
        
        allocation.status = AllocationStatus.ALLOCATED
        allocation.allocated_at = datetime.now().isoformat()
        
        self.allocations[allocation_id] = allocation
        
        logger.info(f"Recorded allocation {allocation_id}: ${allocation.risk_amount} risk, ${allocation.savings_amount} savings")
        
        return allocation
    
    def _allocate_savings(self, allocation: BillPremiumAllocation):
        """
        Allocate savings portion to wallet, investment, and algo trading.
        """
        savings = allocation.savings_amount
        
        # Calculate sub-allocations
        allocation.wallet_amount = (savings * self.savings_wallet_pct / Decimal(100)).quantize(
            Decimal('0.01'), rounding=ROUND_HALF_UP)
        allocation.investment_amount = (savings * self.savings_investment_pct / Decimal(100)).quantize(
            Decimal('0.01'), rounding=ROUND_HALF_UP)
        allocation.algo_trading_amount = (savings * self.savings_algo_pct / Decimal(100)).quantize(
            Decimal('0.01'), rounding=ROUND_HALF_UP)
        
        # Adjust for rounding differences
        total_sub = allocation.wallet_amount + allocation.investment_amount + allocation.algo_trading_amount
        if total_sub != savings:
            allocation.investment_amount += (savings - total_sub)
    
    def get_customer_allocation_summary(self, customer_id: str) -> CustomerAllocationSummary:
        """
        Get complete allocation summary for a customer.
        
        Aggregates all allocations across policies and bills.
        """
        summary = CustomerAllocationSummary(customer_id=customer_id)
        summary.last_updated = datetime.now().isoformat()
        
        # Get allocations for this customer
        customer_allocations = [a for a in self.allocations.values() 
                                if a.customer_id == customer_id]
        
        # Count bills
        bill_ids = set(a.bill_id for a in customer_allocations)
        summary.total_bills = len(bill_ids)
        summary.paid_bills = len([a for a in customer_allocations 
                                  if a.status == AllocationStatus.ALLOCATED])
        
        # Count policies
        policy_ids = set(a.policy_id for a in customer_allocations)
        summary.total_policies = len(policy_ids)
        summary.active_policies = len([pid for pid in policy_ids 
                                       if self.policies.get(pid, {}).get('status', '').lower() == 'active'])
        
        # Sum allocations
        for alloc in customer_allocations:
            summary.total_premiums_paid += alloc.bill_amount
            summary.total_risk_allocated += alloc.risk_amount
            summary.total_savings_allocated += alloc.savings_amount
            summary.total_wallet_balance += alloc.wallet_amount
            summary.total_investment_balance += alloc.investment_amount
            summary.total_algo_trading_balance += alloc.algo_trading_amount
        
        # Get per-policy breakdown
        policy_totals = {}
        for alloc in customer_allocations:
            if alloc.policy_id not in policy_totals:
                policy_totals[alloc.policy_id] = {
                    'policy_id': alloc.policy_id,
                    'bill_count': 0,
                    'total_paid': Decimal(0),
                    'risk_total': Decimal(0),
                    'savings_total': Decimal(0)
                }
            policy_totals[alloc.policy_id]['bill_count'] += 1
            policy_totals[alloc.policy_id]['total_paid'] += alloc.bill_amount
            policy_totals[alloc.policy_id]['risk_total'] += alloc.risk_amount
            policy_totals[alloc.policy_id]['savings_total'] += alloc.savings_amount
        
        summary.policy_allocations = [
            {k: float(v) if isinstance(v, Decimal) else v for k, v in p.items()}
            for p in policy_totals.values()
        ]
        
        # Get actual wallet balance from health_wallets store if available
        if customer_id in self.health_wallets:
            wallet = self.health_wallets[customer_id]
            actual_wallet = Decimal(str(wallet.get('balance', 0) or 0))
            # Use actual wallet balance if higher (includes any direct deposits)
            if actual_wallet > summary.total_wallet_balance:
                summary.total_wallet_balance = actual_wallet
        
        # Get investment returns from investment accounts
        if customer_id in self.investment_accounts:
            inv_acc = self.investment_accounts[customer_id]
            # Calculate returns from balances
            current_total = Decimal(str(inv_acc.get('balance', 0) or 0))
            current_total += Decimal(str(inv_acc.get('index_balance', 0) or 0))
            current_total += Decimal(str(inv_acc.get('bonds_balance', 0) or 0))
            current_total += Decimal(str(inv_acc.get('crypto_balance', 0) or 0))
            
            # Returns = current - invested
            if current_total > summary.total_investment_balance:
                summary.investment_returns = current_total - summary.total_investment_balance
                summary.total_investment_balance = current_total
        
        return summary
    
    def calculate_risk_reserve_report(self) -> RiskReserveReport:
        """
        Calculate comprehensive risk reserve report.
        
        Risk Reserve = Total Risk Premiums - Paid Claims - Claims Reserve
        
        Where Claims Reserve is estimated for pending/in-review claims.
        """
        report = RiskReserveReport(
            report_date=datetime.now().isoformat()
        )
        
        # Sum all risk premiums
        for alloc in self.allocations.values():
            if alloc.status == AllocationStatus.ALLOCATED:
                report.total_risk_premiums += alloc.risk_amount
                
                # Track by month for trending
                try:
                    date = datetime.fromisoformat(alloc.payment_date.replace('Z', '+00:00'))
                    period_key = date.strftime('%Y-%m')
                    if period_key not in report.risk_premiums_by_period:
                        report.risk_premiums_by_period[period_key] = Decimal(0)
                    report.risk_premiums_by_period[period_key] += alloc.risk_amount
                except:
                    pass
        
        # Calculate claims totals
        for claim in self.claims.values():
            status = (claim.get('status') or '').lower().replace(' ', '_')
            claimed_amt = Decimal(str(claim.get('claimed_amount', 0) or 0))
            approved_amt = Decimal(str(claim.get('approved_amount', 0) or 0))
            
            if status in ['paid', 'approved', 'closed']:
                # Use approved amount if available, else claimed
                report.paid_claims_total += approved_amt if approved_amt > 0 else claimed_amt
            elif status in ['pending', 'under_review', 'medical_assessment']:
                # Reserve for pending claims (assume 80% approval rate)
                report.claims_reserve += claimed_amt * Decimal('0.80')
        
        # Calculate reserves
        report.gross_risk_reserve = report.total_risk_premiums
        report.net_risk_reserve = report.total_risk_premiums - report.paid_claims_total - report.claims_reserve
        
        # Calculate ratios
        if report.total_risk_premiums > 0:
            report.loss_ratio = (report.paid_claims_total / report.total_risk_premiums).quantize(
                Decimal('0.0001'), rounding=ROUND_HALF_UP)
            report.reserve_ratio = (report.net_risk_reserve / report.total_risk_premiums).quantize(
                Decimal('0.0001'), rounding=ROUND_HALF_UP)
        
        # Add wallet totals
        for wallet in self.health_wallets.values():
            report.total_wallet_balance += Decimal(str(wallet.get('balance', 0) or 0))
        
        return report
    
    def get_customer_detailed_report(self, customer_id: str, customer_email: str = None) -> Dict[str, Any]:
        """
        Generate detailed premium allocation report for a specific customer.
        
        Example use case: asaf@assurance.co.il billed 5 times on 3 policies
        Shows exactly where each premium payment went.
        
        Args:
            customer_id: Customer ID or identifier
            customer_email: Optional email for lookup
        
        Returns:
            Detailed breakdown of all allocations
        """
        # Find customer by email if provided
        if customer_email and not customer_id:
            for cust_id, cust in self.customers.items():
                if cust.get('email', '').lower() == customer_email.lower():
                    customer_id = cust_id
                    break
        
        if not customer_id:
            return {'error': 'Customer not found', 'customer_email': customer_email}
        
        # Get summary
        summary = self.get_customer_allocation_summary(customer_id)
        
        # Get detailed allocation history
        allocations = [a for a in self.allocations.values() if a.customer_id == customer_id]
        allocation_history = sorted([a.to_dict() for a in allocations], 
                                    key=lambda x: x['payment_date'], reverse=True)
        
        # Calculate savings breakdown
        savings_breakdown = {
            'total_contributed': float(summary.total_savings_allocated),
            'wallet': {
                'allocated': float(sum(a.wallet_amount for a in allocations)),
                'current_balance': float(summary.total_wallet_balance)
            },
            'investments': {
                'allocated': float(sum(a.investment_amount for a in allocations)),
                'current_balance': float(summary.total_investment_balance),
                'returns': float(summary.investment_returns)
            },
            'algo_trading': {
                'allocated': float(sum(a.algo_trading_amount for a in allocations)),
                'current_balance': float(summary.total_algo_trading_balance)
            },
            'total_current_value': float(
                summary.total_wallet_balance + 
                summary.total_investment_balance + 
                summary.total_algo_trading_balance +
                summary.investment_returns
            )
        }
        
        # Risk contribution summary
        risk_breakdown = {
            'total_contributed': float(summary.total_risk_allocated),
            'contribution_to_reserve': 'Risk premiums contribute to company risk reserves',
            'coverage_funded': True,
            'average_per_bill': float(summary.total_risk_allocated / max(summary.paid_bills, 1))
        }
        
        return {
            'customer_id': customer_id,
            'customer_email': customer_email,
            'report_date': datetime.now().isoformat(),
            
            # Summary metrics
            'summary': {
                'total_bills': summary.total_bills,
                'paid_bills': summary.paid_bills,
                'total_policies': summary.total_policies,
                'active_policies': summary.active_policies,
                'total_premiums_paid': float(summary.total_premiums_paid)
            },
            
            # Allocation breakdown
            'allocation': {
                'risk_portion': risk_breakdown,
                'savings_portion': savings_breakdown
            },
            
            # Per-policy summary
            'per_policy_allocation': summary.policy_allocations,
            
            # Full history
            'allocation_history': allocation_history,
            
            # Verification
            'verification': {
                'total_allocated': float(summary.total_risk_allocated + summary.total_savings_allocated),
                'total_paid': float(summary.total_premiums_paid),
                'allocation_matches_payment': abs(
                    float(summary.total_risk_allocated + summary.total_savings_allocated) - 
                    float(summary.total_premiums_paid)
                ) < 0.01
            }
        }
    
    def process_existing_bills(self, bills: Dict = None):
        """
        Process existing paid bills to create allocation records.
        
        Use this to bootstrap tracking for bills that were paid
        before the tracker was initialized.
        """
        bills_to_process = bills or self.bills
        processed = 0
        
        for bill_id, bill in bills_to_process.items():
            # Skip if already tracked
            if any(a.bill_id == bill_id for a in self.allocations.values()):
                continue
            
            # Only process paid bills
            if (bill.get('status') or '').lower() != 'paid':
                continue
            
            policy_id = bill.get('policy_id', '')
            customer_id = bill.get('customer_id', '')
            
            # Try to get customer from policy if not on bill
            if not customer_id and policy_id:
                policy = self.policies.get(policy_id, {})
                customer_id = policy.get('customer_id', '')
            
            if not customer_id:
                continue
            
            amount = float(bill.get('amount_paid', 0) or bill.get('amount_due', 0) or bill.get('amount', 0))
            if amount <= 0:
                continue
            
            payment_date = bill.get('paid_date') or bill.get('updated_at') or bill.get('created_at')
            
            self.record_bill_allocation(
                bill_id=bill_id,
                policy_id=policy_id,
                customer_id=customer_id,
                bill_amount=amount,
                payment_date=payment_date
            )
            processed += 1
        
        logger.info(f"Processed {processed} existing bills into allocation records")
        return processed
    
    def get_all_allocations(self, page: int = 1, page_size: int = 50) -> Dict[str, Any]:
        """Get paginated list of all allocations"""
        all_allocs = sorted(self.allocations.values(), 
                           key=lambda x: x.created_at, reverse=True)
        
        start = (page - 1) * page_size
        end = start + page_size
        
        return {
            'allocations': [a.to_dict() for a in all_allocs[start:end]],
            'page': page,
            'page_size': page_size,
            'total': len(all_allocs)
        }


# Singleton instance
_tracker_instance: Optional[PremiumAllocationTracker] = None


def get_premium_allocation_tracker(**kwargs) -> PremiumAllocationTracker:
    """Get or create singleton instance of premium allocation tracker"""
    global _tracker_instance
    if _tracker_instance is None:
        _tracker_instance = PremiumAllocationTracker(**kwargs)
    return _tracker_instance


def init_premium_allocation_tracker(bills: Dict = None,
                                     policies: Dict = None,
                                     claims: Dict = None,
                                     customers: Dict = None,
                                     health_wallets: Dict = None,
                                     investment_accounts: Dict = None) -> PremiumAllocationTracker:
    """Initialize the premium allocation tracker with data stores"""
    global _tracker_instance
    _tracker_instance = PremiumAllocationTracker(
        bills=bills,
        policies=policies,
        claims=claims,
        customers=customers,
        health_wallets=health_wallets,
        investment_accounts=investment_accounts
    )
    return _tracker_instance


__all__ = [
    'PremiumAllocationTracker',
    'BillPremiumAllocation',
    'CustomerAllocationSummary',
    'RiskReserveReport',
    'AllocationStatus',
    'get_premium_allocation_tracker',
    'init_premium_allocation_tracker'
]
