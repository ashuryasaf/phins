"""
PHINS Accounting Engine
Comprehensive accounting management with premium allocation (risk vs. savings),
accumulative premium tracking, and customer-facing premium statements.

Features:
- Premium allocation with configurable risk/savings split
- Accumulative premium tracking for accounting books
- Risk/Investment ratio calculations
- Multi-period accounting ledger
- Customer premium statements and reports
- Division reporting (Accounting, Actuary, Finance)
- Zero external dependencies
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Dict, Optional, Tuple, Any, cast
from datetime import datetime, date
from decimal import Decimal, ROUND_HALF_UP


# ============================================================================
# ENUMS - Accounting Types
# ============================================================================

class AllocationStatus(Enum):
    """Premium allocation statuses"""
    DRAFT = "Draft"
    POSTED = "Posted"
    REVERSED = "Reversed"
    CANCELLED = "Cancelled"


class EntryType(Enum):
    """Accounting entry types"""
    PREMIUM_POSTED = "Premium Posted"
    RISK_PAYMENT = "Risk Payment"
    SAVINGS_DEPOSIT = "Savings Deposit"
    INVESTMENT_INCOME = "Investment Income"
    CLAIM_PAYMENT = "Claim Payment"
    FEE_APPLIED = "Fee Applied"


class AccountType(Enum):
    """Fund account types"""
    RISK_FUND = "Risk Fund"
    SAVINGS_FUND = "Savings Fund"
    REINSURANCE = "Reinsurance"
    OPERATING = "Operating"


class AccountingReportType(Enum):
    """Types of accounting reports"""
    ACCUMULATIVE_PREMIUM = "Accumulative Premium"
    CUSTOMER_STATEMENT = "Customer Statement"
    RISK_INVESTMENT_ANALYSIS = "Risk/Investment Analysis"
    ACCOUNTING_BOOK = "Accounting Book"
    FUND_SUMMARY = "Fund Summary"


class InvestmentRoute(Enum):
    """Investment route options for savings allocation"""
    BASIC_SAVINGS = "Basic Savings Account"
    BONDS = "Fixed Income / Bonds"
    EQUITIES = "Equity / Stock Market"
    MIXED_PORTFOLIO = "Balanced Mixed Portfolio"


class DisclaimerType(Enum):
    """Types of disclaimers for client actions"""
    BUY_CONTRACT = "Purchase Policy Disclaimer"
    CLAIM_INSURANCE = "Claim Submission Disclaimer"
    INVEST_SAVINGS = "Investment Disclaimer"


class CapitalRevenueJurisdiction(Enum):
    """Capital revenue jurisdictions supported"""
    FEDERAL_US = "Federal (USA)"
    STATE_NY = "New York State"
    STATE_CA = "California State"
    STATE_TX = "Texas State"
    LOCAL_NYC = "New York City Local"
    INTERNATIONAL = "International"


# Investment rates (annual expected return %, conservative estimates)
INVESTMENT_RATES = {
    InvestmentRoute.BASIC_SAVINGS: Decimal('0.5'),      # 0.5% annual interest
    InvestmentRoute.BONDS: Decimal('3.5'),               # 3.5% annual return
    InvestmentRoute.EQUITIES: Decimal('7.0'),            # 7.0% annual return
    InvestmentRoute.MIXED_PORTFOLIO: Decimal('4.5'),    # 4.5% annual return (balanced)
}


# Capital revenue rates by jurisdiction (2024 estimates, for demo/education purposes)
# NOTE: These are simplified rates. Real implementation should integrate with actual APIs.
CAPITAL_REVENUE_RATES = {
    CapitalRevenueJurisdiction.FEDERAL_US: Decimal('21.0'),        # Corporate revenue rate
    CapitalRevenueJurisdiction.STATE_NY: Decimal('6.85'),           # NY state revenue rate
    CapitalRevenueJurisdiction.STATE_CA: Decimal('8.84'),           # CA state revenue rate (top marginal)
    CapitalRevenueJurisdiction.STATE_TX: Decimal('0'),              # TX has no state revenue rate
    CapitalRevenueJurisdiction.LOCAL_NYC: Decimal('3.876'),         # NYC local revenue rate
    CapitalRevenueJurisdiction.INTERNATIONAL: Decimal('25.0'),      # Average international rate
}

# Capital revenue rates for investment income (typically lower than ordinary income)
CAPITAL_REVENUE_RATES_INVESTMENT = {
    CapitalRevenueJurisdiction.FEDERAL_US: Decimal('15.0'),        # Long-term capital revenue rate
    CapitalRevenueJurisdiction.STATE_NY: Decimal('6.85'),
    CapitalRevenueJurisdiction.STATE_CA: Decimal('8.84'),
    CapitalRevenueJurisdiction.STATE_TX: Decimal('0'),
    CapitalRevenueJurisdiction.LOCAL_NYC: Decimal('3.876'),
    CapitalRevenueJurisdiction.INTERNATIONAL: Decimal('20.0'),
}


# ============================================================================
# DATA CLASSES - Accounting Components
# ============================================================================

@dataclass
class Disclaimer:
    """Disclaimer information for client actions"""
    disclaimer_type: DisclaimerType
    title: str
    content: str
    version: str = "1.0"
    effective_date: date = field(default_factory=date.today)
    client_acknowledgment: bool = False


@dataclass
class PremiumAllocation:
    """Premium allocation tracking with investment route selection"""
    allocation_id: str
    bill_id: str
    policy_id: str
    customer_id: str
    allocation_date: date
    total_premium: Decimal
    risk_percentage: Decimal  # 0-100
    savings_percentage: Decimal  # 0-100, calculated as 100 - risk_percentage
    investment_route: InvestmentRoute = InvestmentRoute.BASIC_SAVINGS
    risk_premium: Decimal = field(default_factory=Decimal)
    savings_premium: Decimal = field(default_factory=Decimal)
    investment_ratio: Decimal = field(default_factory=Decimal)
    annual_interest_rate: Decimal = field(default_factory=Decimal)  # Annual return %
    projected_annual_return: Decimal = field(default_factory=Decimal)  # Expected income
    currency_code: str = "USD"
    status: AllocationStatus = AllocationStatus.DRAFT
    posted_date: Optional[date] = None
    posted_by: str = ""
    notes: str = ""
    created_date: datetime = field(default_factory=datetime.now)
    disclaimers_acknowledged: List[DisclaimerType] = field(default_factory=lambda: cast(List[DisclaimerType], []))
    
    def __post_init__(self):
        """Calculate risk and savings amounts, validate percentages, set interest rate"""
        # Validate percentages using Decimal constants
        if self.risk_percentage < Decimal('0') or self.risk_percentage > Decimal('100'):
            raise ValueError(f"Risk percentage must be between 0 and 100, got {self.risk_percentage}")

        if self.savings_percentage < Decimal('0') or self.savings_percentage > Decimal('100'):
            raise ValueError(f"Savings percentage must be between 0 and 100, got {self.savings_percentage}")

        # Auto-calculate if savings_percentage is not set correctly (tolerance 0.01)
        if (self.risk_percentage + self.savings_percentage - Decimal('100')).copy_abs() > Decimal('0.01'):
            self.savings_percentage = Decimal('100') - self.risk_percentage
        
        # Calculate premium amounts
        total = Decimal(str(self.total_premium))
        # Calculate and round monetary values to 2 decimal places
        self.risk_premium = (total * (Decimal(str(self.risk_percentage)) / Decimal('100'))).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        self.savings_premium = (total * (Decimal(str(self.savings_percentage)) / Decimal('100'))).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        
        # Calculate investment ratio (risk:savings)
        if self.savings_premium > Decimal('0'):
            # keep reasonable precision for ratio
            self.investment_ratio = (self.risk_premium / self.savings_premium).quantize(Decimal('0.0001'))
        else:
            self.investment_ratio = self.risk_premium if self.risk_premium > Decimal('0') else Decimal(0)
        
        # Set annual interest rate based on investment route choice
        self.annual_interest_rate = INVESTMENT_RATES.get(self.investment_route, INVESTMENT_RATES[InvestmentRoute.BASIC_SAVINGS])

        # Calculate projected annual return on savings amount (rounded to cents)
        self.projected_annual_return = (self.savings_premium * (self.annual_interest_rate / Decimal('100'))).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    
    def post_allocation(self, posted_by: str) -> None:
        """Mark allocation as posted"""
        if self.status != AllocationStatus.DRAFT:
            raise ValueError(f"Can only post Draft allocations, current status: {self.status.value}")
        self.status = AllocationStatus.POSTED
        self.posted_date = date.today()
        self.posted_by = posted_by
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            'allocation_id': self.allocation_id,
            'bill_id': self.bill_id,
            'policy_id': self.policy_id,
            'customer_id': self.customer_id,
            'allocation_date': self.allocation_date.isoformat(),
            'total_premium': float(Decimal(str(self.total_premium)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
            'risk_percentage': float(Decimal(str(self.risk_percentage)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
            'savings_percentage': float(Decimal(str(self.savings_percentage)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
            'risk_premium': float(self.risk_premium.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
            'savings_premium': float(self.savings_premium.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
            'investment_ratio': float(Decimal(str(self.investment_ratio)).quantize(Decimal('0.0001'))),
            'investment_route': self.investment_route.value,
            'annual_interest_rate': float(Decimal(str(self.annual_interest_rate)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
            'projected_annual_return': float(Decimal(str(self.projected_annual_return)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
            'currency_code': self.currency_code,
            'status': self.status.value,
            'posted_date': self.posted_date.isoformat() if self.posted_date else None,
            'posted_by': self.posted_by,
            'notes': self.notes,
            'created_date': self.created_date.isoformat()
        }


@dataclass
class AccountingEntry:
    """General ledger accounting entry"""
    entry_no: int
    allocation_id: str
    policy_id: str
    customer_id: str
    entry_date: date
    entry_type: EntryType
    account_type: AccountType
    debit_amount: Decimal = Decimal(0)
    credit_amount: Decimal = Decimal(0)
    balance: Decimal = Decimal(0)
    description: str = ""
    reference_no: str = ""
    currency_code: str = "USD"
    posted: bool = True
    posted_by: str = ""
    created_date: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            'entry_no': self.entry_no,
            'allocation_id': self.allocation_id,
            'policy_id': self.policy_id,
            'customer_id': self.customer_id,
            'entry_date': self.entry_date.isoformat(),
            'entry_type': self.entry_type.value,
            'account_type': self.account_type.value,
            'debit_amount': float(Decimal(str(self.debit_amount)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
            'credit_amount': float(Decimal(str(self.credit_amount)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
            'balance': float(Decimal(str(self.balance)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
            'description': self.description,
            'reference_no': self.reference_no,
            'currency_code': self.currency_code,
            'posted': self.posted,
            'posted_by': self.posted_by,
            'created_date': self.created_date.isoformat()
        }


@dataclass
class CustomerPremiumStatement:
    """Customer-facing premium statement"""
    customer_id: str
    statement_date: date
    period_start: date
    period_end: date
    allocations: List[PremiumAllocation] = field(default_factory=lambda: cast(List[PremiumAllocation], []))
    total_premiums: Decimal = Decimal(0)
    total_risk_coverage: Decimal = Decimal(0)
    total_customer_savings: Decimal = Decimal(0)
    average_risk_percentage: Decimal = Decimal(0)
    average_savings_percentage: Decimal = Decimal(0)
    generated_by: str = "PHINS Accounting Engine"
    generated_date: datetime = field(default_factory=datetime.now)
    
    def calculate_summary(self) -> None:
        """Calculate summary statistics"""
        if not self.allocations:
            return
        # Ensure Decimal arithmetic (start with Decimal('0'))
        total_premium = sum((a.total_premium for a in self.allocations), Decimal('0'))
        total_risk = sum((a.risk_premium for a in self.allocations), Decimal('0'))
        total_savings = sum((a.savings_premium for a in self.allocations), Decimal('0'))

        self.total_premiums = total_premium
        self.total_risk_coverage = total_risk
        self.total_customer_savings = total_savings

        if total_premium > Decimal('0'):
            self.average_risk_percentage = (total_risk / total_premium) * Decimal('100')
            self.average_savings_percentage = (total_savings / total_premium) * Decimal('100')
    
    def to_string(self) -> str:
        """Generate formatted statement string"""
        statement: List[str] = []
        statement.append("=" * 60)
        statement.append("CUSTOMER PREMIUM STATEMENT")
        statement.append("=" * 60)
        statement.append(f"Customer ID: {self.customer_id}")
        statement.append(f"Statement Date: {self.statement_date}")
        statement.append(f"Period: {self.period_start} to {self.period_end}")
        statement.append("")
        
        statement.append("DETAILED ALLOCATIONS:")
        statement.append("-" * 60)
        
        for alloc in self.allocations:
            statement.append(f"Date: {alloc.allocation_date}")
            statement.append(f"  Total Premium:        ${alloc.total_premium:>12.2f}")
            statement.append(f"  Risk Coverage ({alloc.risk_percentage:>5.1f}%): ${alloc.risk_premium:>12.2f}")
            statement.append(f"  Your Savings ({alloc.savings_percentage:>5.1f}%): ${alloc.savings_premium:>12.2f}")
            statement.append(f"  Investment Ratio: {alloc.investment_ratio:.4f} (Risk:Savings)")
            statement.append("")
        
        statement.append("=" * 60)
        statement.append("PERIOD SUMMARY")
        statement.append("=" * 60)
        statement.append(f"Total Premium Paid:     ${self.total_premiums:>12.2f}")
        statement.append(f"Total Risk Coverage:    ${self.total_risk_coverage:>12.2f}")
        statement.append(f"Total Your Savings:     ${self.total_customer_savings:>12.2f}")
        statement.append(f"Average Risk %:         {self.average_risk_percentage:>12.2f}%")
        statement.append(f"Average Savings %:      {self.average_savings_percentage:>12.2f}%")
        statement.append("=" * 60)
        
        return "\n".join(statement)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            'customer_id': self.customer_id,
            'statement_date': self.statement_date.isoformat(),
            'period_start': self.period_start.isoformat(),
            'period_end': self.period_end.isoformat(),
            'allocations': [a.to_dict() for a in self.allocations],
            'total_premiums': float(self.total_premiums),
            'total_risk_coverage': float(self.total_risk_coverage),
            'total_customer_savings': float(self.total_customer_savings),
            'average_risk_percentage': float(self.average_risk_percentage),
            'average_savings_percentage': float(self.average_savings_percentage),
            'generated_date': self.generated_date.isoformat()
        }


@dataclass
class AccountingBook:
    """Accounting book/General ledger"""
    book_id: str
    period_start: date
    period_end: date
    entries: List[AccountingEntry] = field(default_factory=lambda: cast(List[AccountingEntry], []))
    risk_fund_balance: Decimal = Decimal(0)
    savings_fund_balance: Decimal = Decimal(0)
    reinsurance_balance: Decimal = Decimal(0)
    operating_balance: Decimal = Decimal(0)
    total_debits: Decimal = Decimal(0)
    total_credits: Decimal = Decimal(0)
    generated_date: datetime = field(default_factory=datetime.now)
    
    def add_entry(self, entry: AccountingEntry) -> None:
        """Add entry to book"""
        self.entries.append(entry)
        self.total_debits += entry.debit_amount
        self.total_credits += entry.credit_amount
        
        # Update fund balance
        if entry.account_type == AccountType.RISK_FUND:
            self.risk_fund_balance = entry.balance
        elif entry.account_type == AccountType.SAVINGS_FUND:
            self.savings_fund_balance = entry.balance
        elif entry.account_type == AccountType.REINSURANCE:
            self.reinsurance_balance = entry.balance
        elif entry.account_type == AccountType.OPERATING:
            self.operating_balance = entry.balance
    
    def to_string(self) -> str:
        """Generate formatted accounting book"""
        book: List[str] = []
        book.append("=" * 100)
        book.append("ACCOUNTING BOOK - GENERAL LEDGER")
        book.append("=" * 100)
        book.append(f"Period: {self.period_start} to {self.period_end}")
        book.append(f"Generated: {self.generated_date.strftime('%Y-%m-%d %H:%M:%S')}")
        book.append("")
        
        book.append("LEDGER ENTRIES:")
        book.append("-" * 100)
        book.append(f"{'Date':<12} {'Type':<15} {'Account':<15} {'Description':<35} {'Debit':>12} {'Credit':>12} {'Balance':>12}")
        book.append("-" * 100)
        
        for entry in self.entries:
            book.append(
                f"{str(entry.entry_date):<12} "
                f"{entry.entry_type.value:<15} "
                f"{entry.account_type.value:<15} "
                f"{entry.description[:34]:<35} "
                f"${float(entry.debit_amount):>11.2f} "
                f"${float(entry.credit_amount):>11.2f} "
                f"${float(entry.balance):>11.2f}"
            )
        
        book.append("=" * 100)
        book.append("ACCOUNT BALANCES")
        book.append("=" * 100)
        book.append(f"Risk Fund Balance:          ${self.risk_fund_balance:>12.2f}")
        book.append(f"Savings Fund Balance:       ${self.savings_fund_balance:>12.2f}")
        book.append(f"Reinsurance Balance:        ${self.reinsurance_balance:>12.2f}")
        book.append(f"Operating Balance:          ${self.operating_balance:>12.2f}")
        book.append("-" * 100)
        book.append(f"Total Debits:               ${self.total_debits:>12.2f}")
        book.append(f"Total Credits:              ${self.total_credits:>12.2f}")
        book.append("=" * 100)
        
        return "\n".join(book)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            'book_id': self.book_id,
            'period_start': self.period_start.isoformat(),
            'period_end': self.period_end.isoformat(),
            'entries': [e.to_dict() for e in self.entries],
            'risk_fund_balance': float(Decimal(str(self.risk_fund_balance)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
            'savings_fund_balance': float(Decimal(str(self.savings_fund_balance)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
            'reinsurance_balance': float(Decimal(str(self.reinsurance_balance)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
            'operating_balance': float(Decimal(str(self.operating_balance)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
            'total_debits': float(Decimal(str(self.total_debits)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
            'total_credits': float(Decimal(str(self.total_credits)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
            'generated_date': self.generated_date.isoformat()
        }


# ============================================================================
# ACCOUNTING ENGINE - Main Service Class
# ============================================================================

class AccountingEngine:
    """Main accounting engine for premium allocation and reporting"""
    
    def __init__(self, engine_id: str = "PHI-AE-001", organization_name: str = "PHINS"):
        """Initialize accounting engine"""
        self.engine_id = engine_id
        self.organization_name = organization_name
        self.allocations: Dict[str, PremiumAllocation] = {}
        self.ledger_entries: List[AccountingEntry] = []
        self.entry_counter = 0
        self.created_date = datetime.now()
        self.disclaimers = self._setup_default_disclaimers()
    
    def _setup_default_disclaimers(self) -> Dict[DisclaimerType, Disclaimer]:
        """Setup default disclaimers for all client actions."""
        return {
            DisclaimerType.BUY_CONTRACT: Disclaimer(
                disclaimer_type=DisclaimerType.BUY_CONTRACT,
                title="Policy Purchase Disclaimer",
                content="""By purchasing an insurance policy, you acknowledge that:
1. You have read and understood the policy terms and conditions.
2. The premium amounts and coverage limits are as stated in the policy document.
3. Pre-existing conditions may not be covered; refer to the policy exclusions.
4. Your policy is subject to underwriting approval and may be subject to conditions.
5. Misrepresentation of material facts may result in policy cancellation.
6. Payment must be received by the due date to maintain active coverage.
7. PHINS reserves the right to modify premiums upon renewal in accordance with applicable law.
8. You have 30 days to review the policy and cancel if unsatisfied (free look period).

By clicking 'Accept', you confirm you have reviewed and accepted these terms."""
            ),
            DisclaimerType.CLAIM_INSURANCE: Disclaimer(
                disclaimer_type=DisclaimerType.CLAIM_INSURANCE,
                title="Claim Submission Disclaimer",
                content="""When submitting an insurance claim, please note:
1. All claims must be submitted within the timeframe specified in your policy.
2. You are responsible for providing accurate and complete information.
3. False or misleading information in a claim may result in claim denial and policy cancellation.
4. PHINS reserves the right to request additional documentation to verify the claim.
5. Claim investigation may take 30-90 days depending on complexity.
6. Coverage is subject to policy terms, conditions, and any applicable exclusions.
7. Claimants must cooperate fully with PHINS and its representatives during investigation.
8. Payment of claims does not waive any policy conditions or exclusions.
9. PHINS may pursue subrogation rights to recover claim payments from liable third parties.

By submitting this claim, you certify that the information provided is true and accurate."""
            ),
            DisclaimerType.INVEST_SAVINGS: Disclaimer(
                disclaimer_type=DisclaimerType.INVEST_SAVINGS,
                title="Investment Savings Disclaimer",
                content="""Important information regarding your savings allocation investment:
1. The savings portion of your premium can be invested via multiple routes (Basic Savings, Bonds, Equities, Mixed Portfolio).
2. Expected returns listed are projections based on historical averages and are not guaranteed.
3. Equity and bond investments carry market risk; principal value may fluctuate and may be worth less at withdrawal.
4. Basic Savings accounts are typically safe but offer lower returns.
5. Past performance does not guarantee future results.
6. You may switch investment routes once per policy year at no cost; additional changes may incur fees.
7. Savings withdrawals (outside claims) are subject to policy terms and may incur surrender charges.
8. Investment income is subject to applicable taxes; consult a tax professional for your situation.
9. PHINS is not responsible for investment losses due to market conditions beyond our control.
10. All investments are held in trust and are protected against creditor claims (subject to applicable law).

By selecting an investment route, you confirm you understand the risks and benefits outlined above."""
            ),
        }
    
    def create_allocation(self, bill_id: str, policy_id: str, customer_id: str,
                         total_premium: Decimal, risk_percentage: Decimal,
                         investment_route: InvestmentRoute = InvestmentRoute.BASIC_SAVINGS,
                         allocation_notes: str = "") -> PremiumAllocation:
        """
        Create premium allocation with risk/savings split and investment route choice
        
        Args:
            bill_id: Bill identifier
            policy_id: Policy identifier
            customer_id: Customer identifier
            total_premium: Total premium amount
            risk_percentage: Percentage allocated to risk (0-100)
            investment_route: Client's chosen investment route (Savings, Bonds, Equities, Mixed)
            allocation_notes: Optional notes
        
        Returns:
            Created PremiumAllocation object
        """
        allocation_id = f"ALLOC-{len(self.allocations) + 1:06d}"
        savings_percentage = Decimal(100) - Decimal(str(risk_percentage))
        
        allocation = PremiumAllocation(
            allocation_id=allocation_id,
            bill_id=bill_id,
            policy_id=policy_id,
            customer_id=customer_id,
            allocation_date=date.today(),
            total_premium=Decimal(str(total_premium)),
            risk_percentage=Decimal(str(risk_percentage)),
            savings_percentage=savings_percentage,
            investment_route=investment_route,
            notes=allocation_notes
        )
        
        self.allocations[allocation_id] = allocation
        return allocation
    
    def post_allocation(self, allocation_id: str, posted_by: str) -> Tuple[bool, str]:
        """
        Post allocation and create ledger entries
        
        Returns:
            Tuple of (success, message)
        """
        if allocation_id not in self.allocations:
            return False, f"Allocation {allocation_id} not found"
        
        allocation = self.allocations[allocation_id]
        
        try:
            allocation.post_allocation(posted_by)
            
            # Create Risk Fund entry
            self._create_ledger_entry(
                allocation_id=allocation_id,
                policy_id=allocation.policy_id,
                customer_id=allocation.customer_id,
                entry_date=date.today(),
                entry_type=EntryType.RISK_PAYMENT,
                account_type=AccountType.RISK_FUND,
                debit_amount=allocation.risk_premium,
                description=f"Risk Premium Posted - Total Premium: ${allocation.total_premium:.2f}",
                reference_no=allocation.bill_id
            )
            
            # Create Savings Fund entry
            self._create_ledger_entry(
                allocation_id=allocation_id,
                policy_id=allocation.policy_id,
                customer_id=allocation.customer_id,
                entry_date=date.today(),
                entry_type=EntryType.SAVINGS_DEPOSIT,
                account_type=AccountType.SAVINGS_FUND,
                debit_amount=allocation.savings_premium,
                description=f"Savings Premium Posted - Total Premium: ${allocation.total_premium:.2f}",
                reference_no=allocation.bill_id
            )
            
            return True, f"Allocation {allocation_id} posted successfully"
        
        except Exception as e:
            return False, f"Error posting allocation: {str(e)}"
    
    def get_customer_statement(self, customer_id: str, start_date: date, 
                               end_date: date) -> CustomerPremiumStatement:
        """
        Generate customer premium statement for period
        
        Returns:
            CustomerPremiumStatement with summary and details
        """
        allocations = [
            a for a in self.allocations.values()
            if a.customer_id == customer_id and 
               start_date <= a.allocation_date <= end_date and
               a.status == AllocationStatus.POSTED
        ]
        
        statement = CustomerPremiumStatement(
            customer_id=customer_id,
            statement_date=date.today(),
            period_start=start_date,
            period_end=end_date,
            allocations=sorted(allocations, key=lambda x: x.allocation_date)
        )
        
        statement.calculate_summary()
        return statement
    
    def get_accumulative_premium_report(self, policy_id: str) -> Dict[str, Any]:
        """Get accumulative premium report for policy"""
        allocations = [
            a for a in self.allocations.values()
            if a.policy_id == policy_id and a.status == AllocationStatus.POSTED
        ]
        
        total_premium = sum((a.total_premium for a in allocations), Decimal('0'))
        total_risk = sum((a.risk_premium for a in allocations), Decimal('0'))
        total_savings = sum((a.savings_premium for a in allocations), Decimal('0'))
        
        return {
            'policy_id': policy_id,
            'allocation_count': len(allocations),
            'cumulative_premium': float(total_premium),
            'cumulative_risk': float(total_risk),
            'cumulative_savings': float(total_savings),
            'overall_risk_percentage': float((total_risk / total_premium * 100) if total_premium > 0 else 0),
            'overall_savings_percentage': float((total_savings / total_premium * 100) if total_premium > 0 else 0),
            'report_date': date.today().isoformat()
        }
    
    def get_risk_investment_ratio(self, customer_id: str) -> Dict[str, Any]:
        """Get risk/investment ratio for customer"""
        allocations = [
            a for a in self.allocations.values()
            if a.customer_id == customer_id and a.status == AllocationStatus.POSTED
        ]
        
        if not allocations:
            return {
                'customer_id': customer_id,
                'risk_investment_ratio': 0,
                'total_risk': 0,
                'total_savings': 0,
                'message': 'No allocations found'
            }
        
        total_risk = sum((a.risk_premium for a in allocations), Decimal('0'))
        total_savings = sum((a.savings_premium for a in allocations), Decimal('0'))
        
        ratio = float(total_risk / total_savings) if total_savings > 0 else float(total_risk)
        
        return {
            'customer_id': customer_id,
            'risk_investment_ratio': ratio,
            'total_risk': float(total_risk),
            'total_savings': float(total_savings),
            'allocation_count': len(allocations)
        }
    
    def generate_accounting_book(self, start_date: date, end_date: date) -> AccountingBook:
        """
        Generate accounting book for period
        
        Returns:
            AccountingBook with all ledger entries and balances
        """
        book_id = f"BOOK-{date.today().strftime('%Y%m%d')}"
        book = AccountingBook(
            book_id=book_id,
            period_start=start_date,
            period_end=end_date
        )
        
        # Add entries within period
        for entry in self.ledger_entries:
            if start_date <= entry.entry_date <= end_date:
                book.add_entry(entry)
        
        return book
    
    def get_customer_summary(self, customer_id: str) -> Dict[str, Any]:
        """Get summary of all customer premiums and allocations"""
        allocations = [
            a for a in self.allocations.values()
            if a.customer_id == customer_id and a.status == AllocationStatus.POSTED
        ]
        
        if not allocations:
            return {'customer_id': customer_id, 'allocations': [], 'summary': {}}
        
        total_premium = sum((a.total_premium for a in allocations), Decimal('0'))
        total_risk = sum((a.risk_premium for a in allocations), Decimal('0'))
        total_savings = sum((a.savings_premium for a in allocations), Decimal('0'))
        
        return {
            'customer_id': customer_id,
            'allocation_count': len(allocations),
            'total_premium': float(total_premium),
            'total_risk': float(total_risk),
            'total_savings': float(total_savings),
            'average_risk_percentage': float((total_risk / total_premium * 100) if total_premium > 0 else 0),
            'average_savings_percentage': float((total_savings / total_premium * 100) if total_premium > 0 else 0),
            'overall_investment_ratio': float(total_risk / total_savings if total_savings > 0 else total_risk),
            'allocations': [a.to_dict() for a in allocations]
        }
    
    def _create_ledger_entry(self, allocation_id: str, policy_id: str, customer_id: str,
                            entry_date: date, entry_type: EntryType, account_type: AccountType,
                            debit_amount: Decimal = Decimal(0), credit_amount: Decimal = Decimal(0),
                            description: str = "", reference_no: str = "") -> AccountingEntry:
        """Create and track ledger entry"""
        # Calculate running balance using Decimal arithmetic
        balance = self._get_account_balance(account_type)
        debit = Decimal(str(debit_amount))
        credit = Decimal(str(credit_amount))
        if debit > Decimal('0'):
            balance += debit
        elif credit > Decimal('0'):
            balance -= credit

        # Round balance to cents for ledger
        balance = balance.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

        self.entry_counter += 1
        entry = AccountingEntry(
            entry_no=self.entry_counter,
            allocation_id=allocation_id,
            policy_id=policy_id,
            customer_id=customer_id,
            entry_date=entry_date,
            entry_type=entry_type,
            account_type=account_type,
            debit_amount=debit,
            credit_amount=credit,
            balance=balance,
            description=description,
            reference_no=reference_no,
            posted_by=self.engine_id
        )
        
        self.ledger_entries.append(entry)
        return entry
    
    def _get_account_balance(self, account_type: AccountType) -> Decimal:
        """Get current balance for account type"""
        balance = Decimal(0)
        for entry in self.ledger_entries:
            if entry.account_type == account_type:
                balance = entry.balance
        return balance
    
    def get_summary(self) -> Dict[str, Any]:
        """Get engine summary"""
        total_allocations = len(self.allocations)
        posted_allocations = sum(1 for a in self.allocations.values() if a.status == AllocationStatus.POSTED)
        total_premium = sum((a.total_premium for a in self.allocations.values() if a.status == AllocationStatus.POSTED), Decimal('0'))
        
        return {
            'engine_id': self.engine_id,
            'organization': self.organization_name,
            'total_allocations': total_allocations,
            'posted_allocations': posted_allocations,
            'total_premium_posted': float(total_premium),
            'total_ledger_entries': len(self.ledger_entries),
            'created_date': self.created_date.isoformat()
        }

    # ========== DISCLAIMER METHODS ==========

    def get_disclaimer(self, disclaimer_type: DisclaimerType) -> Optional[Disclaimer]:
        """Retrieve a disclaimer by type."""
        return self.disclaimers.get(disclaimer_type)

    def acknowledge_disclaimer(self, allocation_id: str, disclaimer_type: DisclaimerType) -> bool:
        """Mark a disclaimer as acknowledged by client for a specific allocation."""
        if allocation_id in self.allocations:
            if disclaimer_type not in self.allocations[allocation_id].disclaimers_acknowledged:
                self.allocations[allocation_id].disclaimers_acknowledged.append(disclaimer_type)
            return True
        return False

    def get_pending_disclaimers(self, allocation_id: str) -> List[Disclaimer]:
        """Get list of disclaimers that have not been acknowledged for an allocation."""
        if allocation_id not in self.allocations:
            return []
        allocation = self.allocations[allocation_id]
        pending: List[Disclaimer] = []
        for disc_type, disc in self.disclaimers.items():
            if disc_type not in allocation.disclaimers_acknowledged:
                pending.append(disc)
        return pending

    def get_all_disclaimers_for_action(self, action: str) -> List[Disclaimer]:
        """Get all relevant disclaimers for a specific client action."""
        # Map actions to disclaimer types
        action_map = {
            'buy_contract': [DisclaimerType.BUY_CONTRACT],
            'claim_insurance': [DisclaimerType.CLAIM_INSURANCE],
            'invest_savings': [DisclaimerType.INVEST_SAVINGS],
            'policy_purchase': [DisclaimerType.BUY_CONTRACT],
            'claim_submission': [DisclaimerType.CLAIM_INSURANCE],
            'investment_setup': [DisclaimerType.INVEST_SAVINGS],
        }
        disc_types = action_map.get(action.lower(), [])
        return [self.disclaimers[dt] for dt in disc_types if dt in self.disclaimers]

    def get_all_disclaimers(self) -> List[Disclaimer]:
        """Get all available disclaimers."""
        return list(self.disclaimers.values())

    def print_disclaimer(self, disclaimer_type: DisclaimerType) -> str:
        """Format a disclaimer for display."""
        disc = self.get_disclaimer(disclaimer_type)
        if not disc:
            return "Disclaimer not found."
        output: List[str] = []
        output.append("=" * 80)
        output.append(f"DISCLAIMER: {disc.title}")
        output.append(f"Version: {disc.version} | Effective: {disc.effective_date}")
        output.append("=" * 80)
        output.append(disc.content)
        output.append("=" * 80)
        return "\n".join(output)

