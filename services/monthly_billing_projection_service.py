"""
PHINS Monthly Billing Projection Service
==========================================
Comprehensive billing projection service for customer payment ledgers.

Features:
- Track all billings made to customers with full ledger history
- Generate future payment projections (monthly, quarterly, semi-annual, annual)
- Handle prepaid premiums with discounted rates
- Track risk vs savings allocation in projections
- Maintain data integrity throughout the billing pipeline

Example: If efrat@phins.ai was billed 3 times and her policy became active
in January 2026, this service reports:
- Future payment ledger (February 2026, March 2026, etc.)
- Payment breakdown: risk allocation vs savings allocation
- Prepaid premium discounts when applicable
"""

from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field, asdict
from enum import Enum
from dateutil.relativedelta import relativedelta
import logging
import json
import hashlib

logger = logging.getLogger(__name__)


class PaymentFrequency(str, Enum):
    """Payment frequency options"""
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    SEMI_ANNUAL = "semi_annual"
    ANNUAL = "annual"


class PrepaidDiscountTier(str, Enum):
    """Prepaid premium discount tiers"""
    NONE = "none"  # Monthly - no discount
    QUARTERLY = "quarterly"  # 2% discount
    SEMI_ANNUAL = "semi_annual"  # 4% discount
    ANNUAL = "annual"  # 6% discount


# Prepaid discount rates
PREPAID_DISCOUNT_RATES = {
    PrepaidDiscountTier.NONE: Decimal('0.00'),
    PrepaidDiscountTier.QUARTERLY: Decimal('2.00'),
    PrepaidDiscountTier.SEMI_ANNUAL: Decimal('4.00'),
    PrepaidDiscountTier.ANNUAL: Decimal('6.00'),
}


class ProjectionEntryStatus(str, Enum):
    """Status of a projection entry"""
    SCHEDULED = "scheduled"
    DUE = "due"
    PAID = "paid"
    OVERDUE = "overdue"
    PREPAID = "prepaid"
    CANCELLED = "cancelled"


@dataclass
class BillingLedgerEntry:
    """
    Single entry in the billing ledger.
    Tracks a historical or projected payment.
    """
    entry_id: str
    customer_id: str
    customer_email: str
    policy_id: str
    
    # Payment details
    entry_type: str  # 'historical' or 'projected'
    payment_period: str  # e.g., '2026-01', '2026-02'
    due_date: str  # ISO format date
    payment_date: Optional[str] = None  # When actually paid
    
    # Amounts
    base_amount: Decimal = field(default_factory=Decimal)
    discount_rate: Decimal = field(default_factory=Decimal)
    discount_amount: Decimal = field(default_factory=Decimal)
    final_amount: Decimal = field(default_factory=Decimal)
    amount_paid: Decimal = field(default_factory=Decimal)
    
    # Risk vs Savings allocation
    risk_percentage: Decimal = field(default=Decimal('75'))
    savings_percentage: Decimal = field(default=Decimal('25'))
    risk_amount: Decimal = field(default_factory=Decimal)
    savings_amount: Decimal = field(default_factory=Decimal)
    
    # Savings breakdown
    wallet_amount: Decimal = field(default_factory=Decimal)
    investment_amount: Decimal = field(default_factory=Decimal)
    algo_trading_amount: Decimal = field(default_factory=Decimal)
    
    # Status and metadata
    status: ProjectionEntryStatus = ProjectionEntryStatus.SCHEDULED
    bill_id: Optional[str] = None
    allocation_id: Optional[str] = None
    nft_token_id: Optional[str] = None
    
    # Data integrity
    ledger_hash: Optional[str] = None
    previous_hash: Optional[str] = None
    
    # Timestamps
    created_at: str = ""
    updated_at: str = ""
    
    def __post_init__(self):
        """Calculate derived fields after initialization"""
        if not self.created_at:
            self.created_at = datetime.now().isoformat()
        if not self.updated_at:
            self.updated_at = datetime.now().isoformat()
        
        # Calculate discount
        if self.base_amount > 0 and self.discount_amount == Decimal(0):
            self.discount_amount = (self.base_amount * self.discount_rate / Decimal(100)).quantize(
                Decimal('0.01'), rounding=ROUND_HALF_UP)
            self.final_amount = self.base_amount - self.discount_amount
        
        # Calculate risk/savings allocation
        if self.final_amount > 0 and self.risk_amount == Decimal(0):
            self.risk_amount = (self.final_amount * self.risk_percentage / Decimal(100)).quantize(
                Decimal('0.01'), rounding=ROUND_HALF_UP)
            self.savings_amount = (self.final_amount * self.savings_percentage / Decimal(100)).quantize(
                Decimal('0.01'), rounding=ROUND_HALF_UP)
    
    def calculate_savings_breakdown(self, wallet_pct: Decimal = Decimal('15'),
                                     investment_pct: Decimal = Decimal('60'),
                                     algo_pct: Decimal = Decimal('25')):
        """Calculate savings allocation breakdown"""
        if self.savings_amount > 0:
            self.wallet_amount = (self.savings_amount * wallet_pct / Decimal(100)).quantize(
                Decimal('0.01'), rounding=ROUND_HALF_UP)
            self.investment_amount = (self.savings_amount * investment_pct / Decimal(100)).quantize(
                Decimal('0.01'), rounding=ROUND_HALF_UP)
            self.algo_trading_amount = (self.savings_amount * algo_pct / Decimal(100)).quantize(
                Decimal('0.01'), rounding=ROUND_HALF_UP)
            
            # Adjust for rounding
            total = self.wallet_amount + self.investment_amount + self.algo_trading_amount
            if total != self.savings_amount:
                self.investment_amount += (self.savings_amount - total)
    
    def generate_hash(self) -> str:
        """Generate hash for this entry for data integrity verification"""
        data = f"{self.entry_id}|{self.customer_id}|{self.policy_id}|{self.payment_period}|{self.final_amount}|{self.previous_hash or 'GENESIS'}"
        return hashlib.sha256(data.encode()).hexdigest()[:32]
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            'entry_id': self.entry_id,
            'customer_id': self.customer_id,
            'customer_email': self.customer_email,
            'policy_id': self.policy_id,
            'entry_type': self.entry_type,
            'payment_period': self.payment_period,
            'due_date': self.due_date,
            'payment_date': self.payment_date,
            'base_amount': float(self.base_amount),
            'discount_rate': float(self.discount_rate),
            'discount_amount': float(self.discount_amount),
            'final_amount': float(self.final_amount),
            'amount_paid': float(self.amount_paid),
            'risk_percentage': float(self.risk_percentage),
            'savings_percentage': float(self.savings_percentage),
            'risk_amount': float(self.risk_amount),
            'savings_amount': float(self.savings_amount),
            'wallet_amount': float(self.wallet_amount),
            'investment_amount': float(self.investment_amount),
            'algo_trading_amount': float(self.algo_trading_amount),
            'status': self.status.value if isinstance(self.status, Enum) else self.status,
            'bill_id': self.bill_id,
            'allocation_id': self.allocation_id,
            'nft_token_id': self.nft_token_id,
            'ledger_hash': self.ledger_hash,
            'previous_hash': self.previous_hash,
            'created_at': self.created_at,
            'updated_at': self.updated_at
        }


@dataclass
class CustomerBillingProjection:
    """
    Complete billing projection for a customer.
    Includes historical payments and future projections.
    """
    customer_id: str
    customer_email: str
    customer_name: str
    
    # Policy information
    policy_id: str
    policy_type: str
    policy_status: str
    policy_start_date: str
    policy_end_date: Optional[str] = None
    
    # Premium configuration
    annual_premium: Decimal = field(default_factory=Decimal)
    monthly_premium: Decimal = field(default_factory=Decimal)
    payment_frequency: PaymentFrequency = PaymentFrequency.MONTHLY
    
    # Allocation configuration
    risk_percentage: Decimal = field(default=Decimal('75'))
    savings_percentage: Decimal = field(default=Decimal('25'))
    
    # Prepaid configuration
    prepaid_tier: PrepaidDiscountTier = PrepaidDiscountTier.NONE
    prepaid_discount_rate: Decimal = field(default_factory=Decimal)
    
    # Summary totals
    total_billed: Decimal = field(default_factory=Decimal)
    total_paid: Decimal = field(default_factory=Decimal)
    total_outstanding: Decimal = field(default_factory=Decimal)
    total_projected: Decimal = field(default_factory=Decimal)
    total_discount_given: Decimal = field(default_factory=Decimal)
    
    # Allocation totals
    total_risk_allocated: Decimal = field(default_factory=Decimal)
    total_savings_allocated: Decimal = field(default_factory=Decimal)
    
    # Ledger entries
    historical_entries: List[BillingLedgerEntry] = field(default_factory=list)
    projected_entries: List[BillingLedgerEntry] = field(default_factory=list)
    
    # Data integrity
    ledger_hash: Optional[str] = None
    integrity_verified: bool = False
    
    # Metadata
    projection_generated_at: str = ""
    projection_months: int = 12
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            'customer_id': self.customer_id,
            'customer_email': self.customer_email,
            'customer_name': self.customer_name,
            'policy_id': self.policy_id,
            'policy_type': self.policy_type,
            'policy_status': self.policy_status,
            'policy_start_date': self.policy_start_date,
            'policy_end_date': self.policy_end_date,
            'annual_premium': float(self.annual_premium),
            'monthly_premium': float(self.monthly_premium),
            'payment_frequency': self.payment_frequency.value if isinstance(self.payment_frequency, Enum) else self.payment_frequency,
            'risk_percentage': float(self.risk_percentage),
            'savings_percentage': float(self.savings_percentage),
            'prepaid_tier': self.prepaid_tier.value if isinstance(self.prepaid_tier, Enum) else self.prepaid_tier,
            'prepaid_discount_rate': float(self.prepaid_discount_rate),
            'summary': {
                'total_billed': float(self.total_billed),
                'total_paid': float(self.total_paid),
                'total_outstanding': float(self.total_outstanding),
                'total_projected': float(self.total_projected),
                'total_discount_given': float(self.total_discount_given),
                'total_risk_allocated': float(self.total_risk_allocated),
                'total_savings_allocated': float(self.total_savings_allocated),
            },
            'historical_payments': [e.to_dict() for e in self.historical_entries],
            'future_projections': [e.to_dict() for e in self.projected_entries],
            'ledger_hash': self.ledger_hash,
            'integrity_verified': self.integrity_verified,
            'projection_generated_at': self.projection_generated_at,
            'projection_months': self.projection_months
        }


class MonthlyBillingProjectionService:
    """
    Service for generating and managing customer billing projections.
    
    Features:
    - Generate monthly billing projections with ledger tracking
    - Handle prepaid premiums with discounted rates
    - Track risk vs savings allocation
    - Maintain data integrity with hash verification
    """
    
    def __init__(self,
                 customers: Dict = None,
                 policies: Dict = None,
                 billing: Dict = None,
                 claims: Dict = None,
                 health_wallets: Dict = None,
                 investment_accounts: Dict = None):
        """Initialize the service with data store references"""
        self.customers = customers if customers is not None else {}
        self.policies = policies if policies is not None else {}
        self.billing = billing if billing is not None else {}
        self.claims = claims if claims is not None else {}
        self.health_wallets = health_wallets if health_wallets is not None else {}
        self.investment_accounts = investment_accounts if investment_accounts is not None else {}
        
        # Internal tracking
        self._entry_counter = 0
        self._projections_cache: Dict[str, CustomerBillingProjection] = {}
        
        # Default configuration
        self.default_risk_pct = Decimal('75')
        self.default_savings_pct = Decimal('25')
        self.default_projection_months = 12
        
        # Savings breakdown defaults
        self.savings_wallet_pct = Decimal('15')
        self.savings_investment_pct = Decimal('60')
        self.savings_algo_pct = Decimal('25')
    
    def _generate_entry_id(self) -> str:
        """Generate unique entry ID"""
        self._entry_counter += 1
        return f"LEDGER-{datetime.now().strftime('%Y%m%d')}-{self._entry_counter:06d}"
    
    def _get_payment_frequency(self, policy: Dict) -> PaymentFrequency:
        """Determine payment frequency from policy"""
        billing_config = policy.get('billing', {})
        if isinstance(billing_config, str):
            try:
                billing_config = json.loads(billing_config)
            except:
                billing_config = {}
        
        payment_setup = policy.get('payment_setup', {})
        if isinstance(payment_setup, str):
            try:
                payment_setup = json.loads(payment_setup)
            except Exception:
                payment_setup = {}

        freq = str(
            billing_config.get('payment_frequency') or
            billing_config.get('frequency') or
            payment_setup.get('billing_frequency') or
            ''
        ).lower()
        freq_map = {
            'monthly': PaymentFrequency.MONTHLY,
            'quarterly': PaymentFrequency.QUARTERLY,
            'semi_annual': PaymentFrequency.SEMI_ANNUAL,
            'semi-annual': PaymentFrequency.SEMI_ANNUAL,
            'annual': PaymentFrequency.ANNUAL,
            'yearly': PaymentFrequency.ANNUAL
        }
        return freq_map.get(freq, PaymentFrequency.MONTHLY)
    
    def _get_prepaid_discount(self, frequency: PaymentFrequency) -> Tuple[PrepaidDiscountTier, Decimal]:
        """Get prepaid discount tier and rate based on payment frequency"""
        tier_map = {
            PaymentFrequency.MONTHLY: PrepaidDiscountTier.NONE,
            PaymentFrequency.QUARTERLY: PrepaidDiscountTier.QUARTERLY,
            PaymentFrequency.SEMI_ANNUAL: PrepaidDiscountTier.SEMI_ANNUAL,
            PaymentFrequency.ANNUAL: PrepaidDiscountTier.ANNUAL
        }
        tier = tier_map.get(frequency, PrepaidDiscountTier.NONE)
        rate = PREPAID_DISCOUNT_RATES.get(tier, Decimal('0'))
        return tier, rate
    
    def _calculate_period_amount(self, 
                                  monthly_premium: Decimal, 
                                  frequency: PaymentFrequency) -> Decimal:
        """Calculate payment amount based on frequency"""
        multipliers = {
            PaymentFrequency.MONTHLY: 1,
            PaymentFrequency.QUARTERLY: 3,
            PaymentFrequency.SEMI_ANNUAL: 6,
            PaymentFrequency.ANNUAL: 12
        }
        return monthly_premium * Decimal(multipliers.get(frequency, 1))
    
    def _get_next_payment_dates(self,
                                 start_date: datetime,
                                 frequency: PaymentFrequency,
                                 months: int = 12) -> List[datetime]:
        """Generate list of payment dates based on frequency"""
        dates = []
        current = start_date
        
        if frequency == PaymentFrequency.MONTHLY:
            step_months = 1
        elif frequency == PaymentFrequency.QUARTERLY:
            step_months = 3
        elif frequency == PaymentFrequency.SEMI_ANNUAL:
            step_months = 6
        else:  # ANNUAL
            step_months = 12
        
        end_date = start_date + relativedelta(months=months)
        
        while current < end_date:
            dates.append(current)
            current = current + relativedelta(months=step_months)
        
        return dates
    
    def get_customer_billing_projection(self,
                                        customer_id: str = None,
                                        customer_email: str = None,
                                        policy_id: str = None,
                                        projection_months: int = 12,
                                        include_all_policies: bool = True,
                                        force_refresh: bool = False) -> List[CustomerBillingProjection]:
        """
        Generate billing projection for a customer.
        
        Args:
            customer_id: Customer ID (optional if email provided)
            customer_email: Customer email for lookup
            policy_id: Specific policy to project (optional)
            projection_months: Number of months to project forward
            include_all_policies: Include all customer's policies
            force_refresh: Force recalculation even if cached
        
        Returns:
            List of CustomerBillingProjection objects (one per policy)
        """
        # Find customer by email if ID not provided
        if not customer_id and customer_email:
            for cust_id, cust in self.customers.items():
                if cust.get('email', '').lower() == customer_email.lower():
                    customer_id = cust_id
                    break
        
        if not customer_id:
            logger.warning(f"Customer not found: email={customer_email}")
            return []
        
        customer = self.customers.get(customer_id)
        if not customer:
            logger.warning(f"Customer not found: id={customer_id}")
            return []
        
        customer_email = customer.get('email', '')
        customer_name = customer.get('name', '') or f"{customer.get('first_name', '')} {customer.get('last_name', '')}".strip()
        
        # Get customer's policies
        if policy_id:
            policy = self.policies.get(policy_id)
            if policy and policy.get('customer_id') == customer_id:
                customer_policies = [policy]
            else:
                customer_policies = []
        else:
            customer_policies = [
                p for p in self.policies.values()
                if p.get('customer_id') == customer_id
            ]
        
        if not include_all_policies:
            # Only include active policies
            customer_policies = [
                p for p in customer_policies
                if (p.get('status', '').lower() == 'active' or 
                    p.get('uw_status', '').lower() == 'approved')
            ]
        
        projections = []
        
        for policy in customer_policies:
            pid = policy.get('id', '')
            
            # Check cache
            cache_key = f"{customer_id}:{pid}:{projection_months}"
            if not force_refresh and cache_key in self._projections_cache:
                cached = self._projections_cache[cache_key]
                # Check if cache is fresh (less than 5 minutes old)
                cache_time = datetime.fromisoformat(cached.projection_generated_at.replace('Z', '+00:00'))
                if datetime.now() - cache_time.replace(tzinfo=None) < timedelta(minutes=5):
                    projections.append(cached)
                    continue
            
            # Generate projection
            projection = self._generate_policy_projection(
                customer_id=customer_id,
                customer_email=customer_email,
                customer_name=customer_name,
                policy=policy,
                projection_months=projection_months
            )
            
            # Cache the projection
            self._projections_cache[cache_key] = projection
            projections.append(projection)
        
        return projections
    
    def _generate_policy_projection(self,
                                     customer_id: str,
                                     customer_email: str,
                                     customer_name: str,
                                     policy: Dict,
                                     projection_months: int) -> CustomerBillingProjection:
        """Generate projection for a single policy"""
        policy_id = policy.get('id', '')
        
        # Get policy dates
        start_date_str = policy.get('start_date') or policy.get('approval_date') or policy.get('created_date')
        if start_date_str:
            try:
                if isinstance(start_date_str, str):
                    start_date = datetime.fromisoformat(start_date_str.replace('Z', '+00:00')).replace(tzinfo=None)
                else:
                    start_date = start_date_str
            except:
                start_date = datetime.now()
        else:
            start_date = datetime.now()
        
        # Get premium amounts
        monthly_premium = Decimal(str(policy.get('monthly_premium', 0) or 0))
        annual_premium = Decimal(str(policy.get('annual_premium', 0) or 0))
        
        if monthly_premium == 0 and annual_premium > 0:
            monthly_premium = (annual_premium / Decimal(12)).quantize(Decimal('0.01'))
        elif annual_premium == 0 and monthly_premium > 0:
            annual_premium = monthly_premium * 12
        
        # Get payment frequency and discount
        frequency = self._get_payment_frequency(policy)
        prepaid_tier, discount_rate = self._get_prepaid_discount(frequency)
        
        # Get allocation percentages
        billing_config = policy.get('billing', {})
        if isinstance(billing_config, str):
            try:
                billing_config = json.loads(billing_config)
            except:
                billing_config = {}
        
        risk_pct = Decimal(str(billing_config.get('risk_percentage', self.default_risk_pct)))
        savings_pct = Decimal(str(billing_config.get('savings_percentage', self.default_savings_pct)))
        
        # Ensure they sum to 100
        if risk_pct + savings_pct != Decimal(100):
            savings_pct = Decimal(100) - risk_pct
        
        # Create projection object
        projection = CustomerBillingProjection(
            customer_id=customer_id,
            customer_email=customer_email,
            customer_name=customer_name,
            policy_id=policy_id,
            policy_type=policy.get('type', 'unknown'),
            policy_status=policy.get('status', 'unknown'),
            policy_start_date=start_date.isoformat(),
            annual_premium=annual_premium,
            monthly_premium=monthly_premium,
            payment_frequency=frequency,
            risk_percentage=risk_pct,
            savings_percentage=savings_pct,
            prepaid_tier=prepaid_tier,
            prepaid_discount_rate=discount_rate,
            projection_generated_at=datetime.now().isoformat(),
            projection_months=projection_months
        )
        
        # Get historical bills
        historical_entries = self._get_historical_entries(
            customer_id=customer_id,
            customer_email=customer_email,
            policy_id=policy_id,
            risk_pct=risk_pct,
            savings_pct=savings_pct
        )
        projection.historical_entries = historical_entries
        
        # Generate future projections
        projected_entries = self._generate_future_entries(
            customer_id=customer_id,
            customer_email=customer_email,
            policy_id=policy_id,
            start_date=start_date,
            monthly_premium=monthly_premium,
            frequency=frequency,
            discount_rate=discount_rate,
            risk_pct=risk_pct,
            savings_pct=savings_pct,
            projection_months=projection_months,
            historical_entries=historical_entries
        )
        projection.projected_entries = projected_entries
        
        # Calculate totals
        self._calculate_projection_totals(projection)
        
        # Verify data integrity
        projection.integrity_verified = self._verify_ledger_integrity(projection)
        projection.ledger_hash = self._calculate_projection_hash(projection)
        
        return projection
    
    def _get_historical_entries(self,
                                 customer_id: str,
                                 customer_email: str,
                                 policy_id: str,
                                 risk_pct: Decimal,
                                 savings_pct: Decimal) -> List[BillingLedgerEntry]:
        """Get historical billing entries from billing data"""
        entries = []
        previous_hash = None
        
        # Prefer policy-scoped bills for projection integrity. If no policy_id
        # is present on legacy records, include customer-scoped legacy bills.
        customer_bills = [
            b for b in self.billing.values()
            if b.get('policy_id') == policy_id
        ]
        if not customer_bills:
            customer_bills = [
                b for b in self.billing.values()
                if b.get('customer_id') == customer_id and not b.get('policy_id')
            ]
        
        # Sort by date
        def get_bill_date(bill):
            date_str = (
                bill.get('paid_date')
                or bill.get('due_date')
                or bill.get('created_date')
                or bill.get('created_at')
            )
            if date_str:
                try:
                    return datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                except:
                    pass
            return datetime.min
        
        customer_bills.sort(key=get_bill_date)
        
        for bill in customer_bills:
            bill_id = bill.get('id') or bill.get('bill_id', '')
            
            # Get amounts
            amount_due = Decimal(str(bill.get('amount', 0) or bill.get('amount_due', 0) or 0))
            amount_paid = Decimal(str(bill.get('amount_paid', 0) or 0))
            
            # Get dates
            due_date_str = bill.get('due_date', '')
            paid_date_str = bill.get('paid_date', '')
            
            if due_date_str:
                try:
                    due_date = datetime.fromisoformat(due_date_str.replace('Z', '+00:00')).replace(tzinfo=None)
                except:
                    due_date = datetime.now()
            else:
                due_date = datetime.now()
            
            # Determine status
            status_str = (bill.get('status', '').lower() or '').replace(' ', '_')
            if status_str == 'paid':
                status = ProjectionEntryStatus.PAID
            elif status_str == 'overdue':
                status = ProjectionEntryStatus.OVERDUE
            elif status_str in ['outstanding', 'pending', 'partial', 'partially_paid']:
                status = ProjectionEntryStatus.DUE
            else:
                status = ProjectionEntryStatus.SCHEDULED
            
            # Get allocation info from bill if available
            alloc = bill.get('premium_allocation', {})
            if isinstance(alloc, str):
                try:
                    alloc = json.loads(alloc)
                except:
                    alloc = {}
            
            entry_risk_pct = Decimal(str(alloc.get('risk_percentage', risk_pct)))
            entry_savings_pct = Decimal(str(alloc.get('savings_percentage', savings_pct)))
            
            entry = BillingLedgerEntry(
                entry_id=self._generate_entry_id(),
                customer_id=customer_id,
                customer_email=customer_email,
                policy_id=policy_id,
                entry_type='historical',
                payment_period=due_date.strftime('%Y-%m'),
                due_date=due_date.isoformat(),
                payment_date=paid_date_str if paid_date_str else None,
                base_amount=amount_due,
                final_amount=amount_due,  # Historical bills don't have discount applied
                amount_paid=amount_paid,
                risk_percentage=entry_risk_pct,
                savings_percentage=entry_savings_pct,
                status=status,
                bill_id=bill_id,
                allocation_id=alloc.get('allocation_id'),
                nft_token_id=bill.get('nft_token_id'),
                previous_hash=previous_hash
            )
            
            # Calculate savings breakdown
            entry.calculate_savings_breakdown(
                self.savings_wallet_pct,
                self.savings_investment_pct,
                self.savings_algo_pct
            )
            
            # Generate hash for this entry
            entry.ledger_hash = entry.generate_hash()
            previous_hash = entry.ledger_hash
            
            entries.append(entry)
        
        return entries
    
    def _generate_future_entries(self,
                                  customer_id: str,
                                  customer_email: str,
                                  policy_id: str,
                                  start_date: datetime,
                                  monthly_premium: Decimal,
                                  frequency: PaymentFrequency,
                                  discount_rate: Decimal,
                                  risk_pct: Decimal,
                                  savings_pct: Decimal,
                                  projection_months: int,
                                  historical_entries: List[BillingLedgerEntry]) -> List[BillingLedgerEntry]:
        """Generate future billing projection entries"""
        entries = []
        
        # Get last historical hash for chain continuity
        if historical_entries:
            previous_hash = historical_entries[-1].ledger_hash
        else:
            previous_hash = None
        
        # Determine projection start date
        # Start from the beginning of next month after the most recent payment
        if historical_entries:
            last_payment = historical_entries[-1]
            try:
                last_date = datetime.fromisoformat(last_payment.due_date.replace('Z', '+00:00')).replace(tzinfo=None)
            except:
                last_date = start_date
            projection_start = last_date + relativedelta(months=1, day=1)
        else:
            # If no historical entries, start from policy start date or next month
            if start_date > datetime.now():
                projection_start = start_date.replace(day=1)
            else:
                projection_start = datetime.now() + relativedelta(months=1, day=1)
        
        # Calculate period amount
        period_amount = self._calculate_period_amount(monthly_premium, frequency)
        
        # Get payment dates
        payment_dates = self._get_next_payment_dates(
            projection_start, frequency, projection_months
        )
        
        for payment_date in payment_dates:
            entry = BillingLedgerEntry(
                entry_id=self._generate_entry_id(),
                customer_id=customer_id,
                customer_email=customer_email,
                policy_id=policy_id,
                entry_type='projected',
                payment_period=payment_date.strftime('%Y-%m'),
                due_date=payment_date.isoformat(),
                base_amount=period_amount,
                discount_rate=discount_rate,
                risk_percentage=risk_pct,
                savings_percentage=savings_pct,
                status=ProjectionEntryStatus.SCHEDULED,
                previous_hash=previous_hash
            )
            
            # Calculate savings breakdown
            entry.calculate_savings_breakdown(
                self.savings_wallet_pct,
                self.savings_investment_pct,
                self.savings_algo_pct
            )
            
            # Generate hash
            entry.ledger_hash = entry.generate_hash()
            previous_hash = entry.ledger_hash
            
            entries.append(entry)
        
        return entries
    
    def _calculate_projection_totals(self, projection: CustomerBillingProjection):
        """Calculate summary totals for projection"""
        projection.total_billed = Decimal(0)
        projection.total_paid = Decimal(0)
        projection.total_outstanding = Decimal(0)
        projection.total_projected = Decimal(0)
        projection.total_discount_given = Decimal(0)
        projection.total_risk_allocated = Decimal(0)
        projection.total_savings_allocated = Decimal(0)
        
        # Historical totals
        for entry in projection.historical_entries:
            projection.total_billed += entry.final_amount
            projection.total_paid += entry.amount_paid
            projection.total_discount_given += entry.discount_amount
            
            if entry.status == ProjectionEntryStatus.PAID:
                projection.total_risk_allocated += entry.risk_amount
                projection.total_savings_allocated += entry.savings_amount
            elif entry.status in [ProjectionEntryStatus.DUE, ProjectionEntryStatus.OVERDUE]:
                projection.total_outstanding += (entry.final_amount - entry.amount_paid)
        
        # Projected totals
        for entry in projection.projected_entries:
            projection.total_projected += entry.final_amount
            projection.total_discount_given += entry.discount_amount
    
    def _verify_ledger_integrity(self, projection: CustomerBillingProjection) -> bool:
        """Verify the integrity of the ledger chain"""
        all_entries = projection.historical_entries + projection.projected_entries
        
        if not all_entries:
            return True
        
        # Verify each entry's hash matches and chain is continuous
        previous_hash = None
        for entry in all_entries:
            # Check that previous_hash matches the last entry's hash
            if entry.previous_hash != previous_hash:
                logger.warning(f"Ledger integrity check failed: hash mismatch at {entry.entry_id}")
                return False
            
            # Verify entry's own hash
            expected_hash = entry.generate_hash()
            if entry.ledger_hash != expected_hash:
                logger.warning(f"Ledger integrity check failed: entry hash mismatch at {entry.entry_id}")
                return False
            
            previous_hash = entry.ledger_hash
        
        return True
    
    def _calculate_projection_hash(self, projection: CustomerBillingProjection) -> str:
        """Calculate overall hash for the projection"""
        all_entries = projection.historical_entries + projection.projected_entries
        if all_entries:
            final_entry_hash = all_entries[-1].ledger_hash
        else:
            final_entry_hash = 'EMPTY'
        
        data = f"{projection.customer_id}|{projection.policy_id}|{projection.projection_generated_at}|{final_entry_hash}"
        return hashlib.sha256(data.encode()).hexdigest()[:32]
    
    def get_customer_billing_summary(self,
                                      customer_id: str = None,
                                      customer_email: str = None) -> Dict[str, Any]:
        """
        Get a summary of billing for a customer across all policies.
        
        Simpler than full projection - just key metrics.
        """
        projections = self.get_customer_billing_projection(
            customer_id=customer_id,
            customer_email=customer_email
        )
        
        if not projections:
            return {
                'error': 'Customer or policies not found',
                'customer_email': customer_email,
                'customer_id': customer_id
            }
        
        # Aggregate across policies
        total_policies = len(projections)
        total_billed = Decimal(0)
        total_paid = Decimal(0)
        total_outstanding = Decimal(0)
        total_projected_12m = Decimal(0)
        total_risk_allocated = Decimal(0)
        total_savings_allocated = Decimal(0)
        total_discount = Decimal(0)
        
        historical_count = 0
        policy_summaries = []
        
        for proj in projections:
            total_billed += proj.total_billed
            total_paid += proj.total_paid
            total_outstanding += proj.total_outstanding
            total_projected_12m += proj.total_projected
            total_risk_allocated += proj.total_risk_allocated
            total_savings_allocated += proj.total_savings_allocated
            total_discount += proj.total_discount_given
            historical_count += len(proj.historical_entries)
            
            policy_summaries.append({
                'policy_id': proj.policy_id,
                'policy_type': proj.policy_type,
                'status': proj.policy_status,
                'monthly_premium': float(proj.monthly_premium),
                'payment_frequency': proj.payment_frequency.value if isinstance(proj.payment_frequency, Enum) else proj.payment_frequency,
                'bills_count': len(proj.historical_entries),
                'total_paid': float(proj.total_paid),
                'prepaid_discount_rate': float(proj.prepaid_discount_rate)
            })
        
        return {
            'customer_id': projections[0].customer_id,
            'customer_email': projections[0].customer_email,
            'customer_name': projections[0].customer_name,
            'summary': {
                'total_policies': total_policies,
                'total_bills': historical_count,
                'total_billed': float(total_billed),
                'total_paid': float(total_paid),
                'total_outstanding': float(total_outstanding),
                'projected_12_months': float(total_projected_12m),
                'total_discount_given': float(total_discount),
                'total_risk_allocated': float(total_risk_allocated),
                'total_savings_allocated': float(total_savings_allocated)
            },
            'allocation_breakdown': {
                'risk_portion': float(total_risk_allocated),
                'savings_portion': float(total_savings_allocated),
                'risk_description': 'Allocated to company risk reserves for claims coverage',
                'savings_description': 'Allocated to customer savings (wallet + investments)'
            },
            'policies': policy_summaries,
            'generated_at': datetime.now().isoformat()
        }
    
    def apply_prepaid_discount(self,
                               customer_id: str,
                               policy_id: str,
                               prepaid_months: int,
                               payment_amount: Decimal = None) -> Dict[str, Any]:
        """
        Apply prepaid discount for advance payment.
        
        Args:
            customer_id: Customer ID
            policy_id: Policy ID
            prepaid_months: Number of months being prepaid
            payment_amount: Optional override for payment amount
        
        Returns:
            Discount calculation details
        """
        # Get policy
        policy = self.policies.get(policy_id)
        if not policy:
            return {'error': 'Policy not found', 'policy_id': policy_id}
        
        if policy.get('customer_id') != customer_id:
            return {'error': 'Policy does not belong to customer'}
        
        monthly_premium = Decimal(str(policy.get('monthly_premium', 0) or 0))
        if monthly_premium == 0:
            annual = Decimal(str(policy.get('annual_premium', 0) or 0))
            monthly_premium = (annual / Decimal(12)).quantize(Decimal('0.01'))
        
        # Determine discount tier based on prepaid months
        if prepaid_months >= 12:
            tier = PrepaidDiscountTier.ANNUAL
        elif prepaid_months >= 6:
            tier = PrepaidDiscountTier.SEMI_ANNUAL
        elif prepaid_months >= 3:
            tier = PrepaidDiscountTier.QUARTERLY
        else:
            tier = PrepaidDiscountTier.NONE
        
        discount_rate = PREPAID_DISCOUNT_RATES[tier]
        
        # Calculate amounts
        base_amount = monthly_premium * Decimal(prepaid_months)
        discount_amount = (base_amount * discount_rate / Decimal(100)).quantize(
            Decimal('0.01'), rounding=ROUND_HALF_UP)
        final_amount = base_amount - discount_amount
        
        return {
            'customer_id': customer_id,
            'policy_id': policy_id,
            'prepaid_months': prepaid_months,
            'discount_tier': tier.value,
            'discount_rate_pct': float(discount_rate),
            'calculation': {
                'monthly_premium': float(monthly_premium),
                'base_amount': float(base_amount),
                'discount_amount': float(discount_amount),
                'final_amount': float(final_amount),
                'savings': float(discount_amount)
            },
            'message': f'Prepaying {prepaid_months} months saves ${float(discount_amount):.2f} ({float(discount_rate)}% discount)'
        }
    
    def validate_billing_integrity(self, customer_id: str = None) -> Dict[str, Any]:
        """
        Validate billing data integrity for a customer or entire system.
        
        Checks:
        - Bill amounts match policy premiums
        - Allocation percentages sum to 100
        - No duplicate bill IDs
        - Payment amounts don't exceed bill amounts
        - Hash chain integrity
        """
        issues = []
        warnings = []
        validated_count = 0
        
        if customer_id:
            customers_to_check = {customer_id: self.customers.get(customer_id)}
        else:
            customers_to_check = self.customers
        
        for cust_id, customer in customers_to_check.items():
            if not customer:
                continue
            
            # Get customer's bills
            customer_bills = [
                b for b in self.billing.values()
                if b.get('customer_id') == cust_id
            ]
            
            # Get customer's policies
            customer_policies = {
                p.get('id'): p for p in self.policies.values()
                if p.get('customer_id') == cust_id
            }
            
            bill_ids = set()
            
            for bill in customer_bills:
                bill_id = bill.get('id') or bill.get('bill_id', '')
                validated_count += 1
                
                # Check for duplicate bill IDs
                if bill_id in bill_ids:
                    issues.append({
                        'type': 'duplicate_bill_id',
                        'customer_id': cust_id,
                        'bill_id': bill_id,
                        'severity': 'error'
                    })
                bill_ids.add(bill_id)
                
                # Check payment doesn't exceed bill amount
                amount_due = Decimal(str(bill.get('amount', 0) or bill.get('amount_due', 0) or 0))
                amount_paid = Decimal(str(bill.get('amount_paid', 0) or 0))
                
                if amount_paid > amount_due:
                    issues.append({
                        'type': 'overpayment',
                        'customer_id': cust_id,
                        'bill_id': bill_id,
                        'amount_due': float(amount_due),
                        'amount_paid': float(amount_paid),
                        'severity': 'warning'
                    })
                
                # Check allocation percentages
                alloc = bill.get('premium_allocation', {})
                if isinstance(alloc, str):
                    try:
                        alloc = json.loads(alloc)
                    except:
                        alloc = {}
                
                if alloc:
                    risk_pct = Decimal(str(alloc.get('risk_percentage', 0) or 0))
                    savings_pct = Decimal(str(alloc.get('savings_percentage', 0) or 0))
                    
                    if risk_pct + savings_pct != Decimal(100) and risk_pct + savings_pct != Decimal(0):
                        warnings.append({
                            'type': 'allocation_mismatch',
                            'customer_id': cust_id,
                            'bill_id': bill_id,
                            'risk_pct': float(risk_pct),
                            'savings_pct': float(savings_pct),
                            'severity': 'warning'
                        })
                
                # Check bill amount matches policy premium (within tolerance)
                policy_id = bill.get('policy_id', '')
                policy = customer_policies.get(policy_id)
                if policy:
                    expected_monthly = Decimal(str(policy.get('monthly_premium', 0) or 0))
                    if expected_monthly > 0 and amount_due > 0:
                        tolerance = expected_monthly * Decimal('0.1')  # 10% tolerance
                        if abs(amount_due - expected_monthly) > tolerance and amount_due < expected_monthly:
                            warnings.append({
                                'type': 'premium_mismatch',
                                'customer_id': cust_id,
                                'bill_id': bill_id,
                                'policy_id': policy_id,
                                'bill_amount': float(amount_due),
                                'expected_premium': float(expected_monthly),
                                'severity': 'info'
                            })
        
        return {
            'validation_result': 'passed' if not issues else 'failed',
            'bills_validated': validated_count,
            'issues': issues,
            'warnings': warnings,
            'summary': {
                'error_count': len([i for i in issues if i.get('severity') == 'error']),
                'warning_count': len([i for i in issues if i.get('severity') == 'warning']) + len([w for w in warnings if w.get('severity') == 'warning']),
                'info_count': len([w for w in warnings if w.get('severity') == 'info'])
            },
            'validated_at': datetime.now().isoformat()
        }


# Singleton instance
_projection_service: Optional[MonthlyBillingProjectionService] = None


def get_billing_projection_service(**kwargs) -> MonthlyBillingProjectionService:
    """Get or create singleton instance"""
    global _projection_service
    if _projection_service is None:
        _projection_service = MonthlyBillingProjectionService(**kwargs)
    return _projection_service


def init_billing_projection_service(customers: Dict = None,
                                      policies: Dict = None,
                                      billing: Dict = None,
                                      claims: Dict = None,
                                      health_wallets: Dict = None,
                                      investment_accounts: Dict = None) -> MonthlyBillingProjectionService:
    """Initialize the billing projection service with data stores"""
    global _projection_service
    _projection_service = MonthlyBillingProjectionService(
        customers=customers,
        policies=policies,
        billing=billing,
        claims=claims,
        health_wallets=health_wallets,
        investment_accounts=investment_accounts
    )
    return _projection_service


__all__ = [
    'MonthlyBillingProjectionService',
    'BillingLedgerEntry',
    'CustomerBillingProjection',
    'PaymentFrequency',
    'PrepaidDiscountTier',
    'ProjectionEntryStatus',
    'PREPAID_DISCOUNT_RATES',
    'get_billing_projection_service',
    'init_billing_projection_service'
]
