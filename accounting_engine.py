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

import hashlib
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Dict, Optional, Tuple, Any, cast
from datetime import datetime, date
from decimal import Decimal, ROUND_HALF_UP

# Journal withhold reasons that must refuse the in-memory post even in dual
# mode — peer key clashes / checksum failures must not fork the books.
_JOURNAL_INTEGRITY_REASONS = frozenset({
    'idempotency_payload_mismatch',
    'idempotency_race_mismatch',
    'checksum_mismatch',
})

# Process-local / time-varying fields — never part of the sealed journal
# checksum identity (Agentic Security Review on U5).
_JOURNAL_VOLATILE_ENTRY_FIELDS = frozenset({
    'entry_no',
    'balance',
    'created_date',
    'posted_by',
    'entry_date',
})
_JOURNAL_VOLATILE_ALLOC_FIELDS = frozenset({
    'created_date',
    'posted_date',
    'posted_by',
    'allocation_date',
})

_LEDGER_TX_RE = re.compile(r'ledger_tx=([^\s;]+)')


def _cash_subject_from(bill_id: str, notes: str = '') -> str:
    """Stable cash identity: bill + optional ledger_tx marker."""
    bill = str(bill_id or '').strip() or 'UNBILLED'
    match = _LEDGER_TX_RE.search(str(notes or ''))
    tx = match.group(1).strip() if match else ''
    if tx:
        return f"{bill}:{tx}"
    return bill


def _stable_journal_payload(payload: Dict[str, Any], *, volatile: frozenset) -> Dict[str, Any]:
    """Copy of ``payload`` with volatile keys stripped for sealing."""
    return {k: v for k, v in dict(payload or {}).items() if k not in volatile}


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
    # When set, savings is the kernel savings component. The remainder
    # (expense and profit) is not folded back into savings.
    preserve_savings_percentage: bool = False
    # The cents the payment writer already landed for this cash. A percentage
    # rounded to two places can sit a cent away from them on every payment.
    risk_amount_exact: Optional[Decimal] = None
    savings_amount_exact: Optional[Decimal] = None
    
    def __post_init__(self):
        """Calculate risk and savings amounts, validate percentages, set interest rate"""
        # Validate percentages using Decimal constants
        if self.risk_percentage < Decimal('0') or self.risk_percentage > Decimal('100'):
            raise ValueError(f"Risk percentage must be between 0 and 100, got {self.risk_percentage}")

        if self.savings_percentage < Decimal('0') or self.savings_percentage > Decimal('100'):
            raise ValueError(f"Savings percentage must be between 0 and 100, got {self.savings_percentage}")

        # Callers that only pass a risk percentage still get savings as the
        # complement. An explicit kernel savings percentage is kept, so
        # expense and profit are not booked as savings.
        if (
            not self.preserve_savings_percentage
            and (self.risk_percentage + self.savings_percentage - Decimal('100')).copy_abs() > Decimal('0.01')
        ):
            self.savings_percentage = Decimal('100') - self.risk_percentage
        
        # Calculate premium amounts
        total = Decimal(str(self.total_premium))
        # Calculate and round monetary values to 2 decimal places
        self.risk_premium = (total * (Decimal(str(self.risk_percentage)) / Decimal('100'))).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        self.savings_premium = (total * (Decimal(str(self.savings_percentage)) / Decimal('100'))).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        if self.risk_amount_exact is not None and self.savings_amount_exact is not None:
            exact_risk = Decimal(str(self.risk_amount_exact)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            exact_savings = Decimal(str(self.savings_amount_exact)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            if exact_risk >= 0 and exact_savings >= 0 and exact_risk + exact_savings <= total + Decimal('0.01'):
                self.risk_premium = exact_risk
                self.savings_premium = exact_savings
        
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
                         allocation_notes: str = "",
                         savings_percentage: Optional[Decimal] = None,
                         risk_amount: Optional[Decimal] = None,
                         savings_amount: Optional[Decimal] = None) -> PremiumAllocation:
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
            savings_percentage: Kernel savings share. When omitted, savings is
                the complement of risk. When supplied, expense and profit are
                not folded into savings.
            risk_amount, savings_amount: The cents already landed for this
                cash. When both are given they are booked as they are.
        
        Returns:
            Created PremiumAllocation object
        """
        # Content-addressed id (engine + bill[+tx] + reverse generation) —
        # never ``ALLOC-{len+1}`` (process-local) or a random UUID (peers
        # would seal different payloads for the same cash).
        subject = _cash_subject_from(bill_id, allocation_notes)
        gen = self._premium_post_generation(subject)
        allocation_id = self._allocation_id_for(subject, gen)
        existing = self.allocations.get(allocation_id)
        if existing is not None and existing.status == AllocationStatus.POSTED:
            # Same cash already on the book — do not clobber the header.
            return existing
        preserve_savings = savings_percentage is not None
        if savings_percentage is None:
            savings_percentage = Decimal(100) - Decimal(str(risk_percentage))
        
        allocation = PremiumAllocation(
            allocation_id=allocation_id,
            bill_id=bill_id,
            policy_id=policy_id,
            customer_id=customer_id,
            allocation_date=date.today(),
            total_premium=Decimal(str(total_premium)),
            risk_percentage=Decimal(str(risk_percentage)),
            savings_percentage=Decimal(str(savings_percentage)),
            investment_route=investment_route,
            notes=allocation_notes,
            preserve_savings_percentage=preserve_savings,
            risk_amount_exact=risk_amount,
            savings_amount_exact=savings_amount,
        )
        
        self.allocations[allocation_id] = allocation
        return allocation

    def _premium_cash_subject(self, allocation: PremiumAllocation) -> str:
        """Stable cash identity for journal keys: bill + optional ledger_tx."""
        return _cash_subject_from(
            str(getattr(allocation, 'bill_id', '') or ''),
            str(getattr(allocation, 'notes', '') or ''),
        )

    def _premium_post_generation(self, subject: str) -> int:
        """Count completed reverse cycles for ``subject`` (next post gen)."""
        wanted = str(subject or '')
        n = 0
        for alloc in self.allocations.values():
            if getattr(alloc, 'status', None) != AllocationStatus.REVERSED:
                continue
            if self._premium_cash_subject(alloc) == wanted:
                n += 1
        return n

    def _allocation_id_for(self, subject: str, gen: int) -> str:
        digest = hashlib.sha256(
            f"{self.engine_id}|{subject}|g{int(gen)}".encode('utf-8')
        ).hexdigest()[:12].upper()
        return f"ALLOC-{digest}"

    def _premium_journal_key(
        self,
        subject: str,
        side: str,
        *,
        gen: int,
        credit_rev: bool = False,
    ) -> str:
        """Content-addressed premium key; ``:gN`` after the first reverse."""
        base = f"ae:{self.engine_id}:premium:{subject}:{side}"
        if credit_rev:
            base = f"{base}:credit:rev"
        else:
            base = f"{base}:debit"
        if int(gen) > 0:
            base = f"{base}:g{int(gen)}"
        return base[:200]
    
    def post_allocation(self, allocation_id: str, posted_by: str) -> Tuple[bool, str]:
        """
        Post allocation and create ledger entries
        
        Returns:
            Tuple of (success, message)

        Risk, savings, and the allocation header seal in one journal
        transaction so a mid-post clash cannot leave an orphan debit on
        the shared durable book while memory rolls back (Bugbot U5).
        """
        if allocation_id not in self.allocations:
            return False, f"Allocation {allocation_id} not found"
        
        allocation = self.allocations[allocation_id]
        prior_status = allocation.status
        prior_posted_date = allocation.posted_date
        prior_posted_by = allocation.posted_by
        entries_before = len(self.ledger_entries)
        counter_before = self.entry_counter
        prepared: List[AccountingEntry] = []
        self._pending_ledger_entries = prepared

        try:
            allocation.post_allocation(posted_by)
            subject = self._premium_cash_subject(allocation)
            gen = self._premium_post_generation(subject)
            journal_items: List[Dict[str, Any]] = []

            for entry_type, account_type, amount, side, label in (
                (
                    EntryType.RISK_PAYMENT, AccountType.RISK_FUND,
                    allocation.risk_premium, 'risk', 'Risk Premium Posted',
                ),
                (
                    EntryType.SAVINGS_DEPOSIT, AccountType.SAVINGS_FUND,
                    allocation.savings_premium, 'savings', 'Savings Premium Posted',
                ),
            ):
                entry = self._build_ledger_entry(
                    allocation_id=allocation_id,
                    policy_id=allocation.policy_id,
                    customer_id=allocation.customer_id,
                    entry_date=date.today(),
                    entry_type=entry_type,
                    account_type=account_type,
                    debit_amount=amount,
                    description=(
                        f"{label} - Total Premium: ${allocation.total_premium:.2f}"
                    ),
                    reference_no=allocation.bill_id,
                )
                prepared.append(entry)
                journal_items.append(self._journal_item_for_entry(
                    entry,
                    self._premium_journal_key(subject, side, gen=gen),
                ))

            # Seal the allocation header so peer hydrate can rebuild
            # ``engine.allocations`` (needed for reconstruct idempotency).
            seal_item = self._allocation_seal_item(
                allocation, cash_subject=subject, gen=gen,
            )
            if seal_item is not None:
                journal_items.append(seal_item)

            if journal_items:
                from services.erp.accounting_journal import (
                    append_journal_entries, journal_enabled, journal_required,
                )
                if journal_enabled():
                    batch = append_journal_entries(journal_items)
                    if not batch.get('ok'):
                        reason_code = str(batch.get('reason') or '')
                        if journal_required() or reason_code in _JOURNAL_INTEGRITY_REASONS:
                            raise RuntimeError(
                                f"accounting journal refused post: {reason_code or 'withheld'}"
                            )
                        # Dual fail-open on transient journal_unavailable:
                        # keep memory post and the entry numbers already
                        # assigned (do not rewind the counter).

            self.ledger_entries.extend(prepared)
            return True, f"Allocation {allocation_id} posted successfully"
        
        except Exception as e:
            # Never leave POSTED without a complete journaled book — callers
            # treat POSTED as already_posted and reconstruct will not repair.
            allocation.status = prior_status
            allocation.posted_date = prior_posted_date
            allocation.posted_by = prior_posted_by
            self.entry_counter = counter_before
            if len(self.ledger_entries) > entries_before:
                del self.ledger_entries[entries_before:]
            return False, f"Error posting allocation: {str(e)}"
        finally:
            self._pending_ledger_entries = []

    def reverse_allocation(self, allocation_id: str, reversed_by: str, reason: str = "") -> Tuple[bool, str]:
        """Take a posted allocation off the book with contra entries.

        The allocation stays on record as ``REVERSED`` and its fund entries
        are offset, so the history of what was booked is not removed.
        Vacates the debit generation so a later resplit can rebook the same
        cash under ``:gN`` keys.

        Contra lines + the reversed header seal in one journal transaction so
        a mid-loop clash cannot leave a one-sided credit while status stays
        POSTED (Agentic Security Review on U5).
        """
        allocation = self.allocations.get(allocation_id)
        if allocation is None:
            return False, f"Allocation {allocation_id} not found"
        if allocation.status != AllocationStatus.POSTED:
            return False, f"Allocation {allocation_id} is not posted"
        note = f"reversed_by={reversed_by}" + (f"; {reason}" if reason else "")
        subject = self._premium_cash_subject(allocation)
        # Generation of the POSTED cycle being reversed (= current reverse count).
        gen = self._premium_post_generation(subject)
        prior_status = allocation.status
        prior_notes = allocation.notes
        entries_before = len(self.ledger_entries)
        counter_before = self.entry_counter
        prepared: List[AccountingEntry] = []
        self._pending_ledger_entries = prepared
        try:
            journal_items: List[Dict[str, Any]] = []
            for entry_type, account_type, amount in (
                (EntryType.RISK_PAYMENT, AccountType.RISK_FUND, allocation.risk_premium),
                (EntryType.SAVINGS_DEPOSIT, AccountType.SAVINGS_FUND, allocation.savings_premium),
            ):
                if Decimal(str(amount)) <= Decimal("0"):
                    continue
                side = 'risk' if account_type == AccountType.RISK_FUND else 'savings'
                key = self._premium_journal_key(
                    subject, side, gen=gen, credit_rev=True,
                )
                entry = self._build_ledger_entry(
                    allocation_id=allocation_id,
                    policy_id=allocation.policy_id,
                    customer_id=allocation.customer_id,
                    entry_date=date.today(),
                    entry_type=entry_type,
                    account_type=account_type,
                    credit_amount=amount,
                    description=f"Reversal of allocation {allocation_id} ({note})",
                    reference_no=allocation.bill_id,
                )
                prepared.append(entry)
                journal_items.append(self._journal_item_for_entry(entry, key))

            # Preview REVERSED seal payload (restored on failure).
            allocation.status = AllocationStatus.REVERSED
            allocation.notes = "; ".join(bit for bit in (prior_notes, note) if bit)
            seal_item = self._allocation_seal_item(
                allocation, cash_subject=subject, gen=gen, suffix='reversed',
            )
            if seal_item is not None:
                journal_items.append(seal_item)

            if journal_items:
                from services.erp.accounting_journal import (
                    append_journal_entries, journal_enabled, journal_required,
                )
                if journal_enabled():
                    batch = append_journal_entries(journal_items)
                    if not batch.get('ok'):
                        reason_code = str(batch.get('reason') or '')
                        if journal_required() or reason_code in _JOURNAL_INTEGRITY_REASONS:
                            raise RuntimeError(
                                f"accounting journal refused reverse: {reason_code or 'withheld'}"
                            )

            self.ledger_entries.extend(prepared)
            return True, f"Allocation {allocation_id} reversed"
        except Exception as e:
            allocation.status = prior_status
            allocation.notes = prior_notes
            self.entry_counter = counter_before
            if len(self.ledger_entries) > entries_before:
                del self.ledger_entries[entries_before:]
            return False, f"Error reversing allocation: {str(e)}"
        finally:
            self._pending_ledger_entries = []

    def _allocation_seal_item(
        self,
        allocation: PremiumAllocation,
        *,
        cash_subject: str = '',
        gen: int = 0,
        suffix: str = '',
    ) -> Optional[Dict[str, Any]]:
        """Journal item for an allocation header seal (or ``None`` if journal off)."""
        try:
            from services.erp.accounting_journal import journal_enabled
        except Exception:
            return None
        if not journal_enabled():
            return None
        payload = _stable_journal_payload(
            dict(allocation.to_dict()), volatile=_JOURNAL_VOLATILE_ALLOC_FIELDS,
        )
        payload['record_type'] = 'allocation'
        payload['post_generation'] = int(gen)
        subject = str(cash_subject or self._premium_cash_subject(allocation) or allocation.allocation_id)
        key = f"ae:{self.engine_id}:allocation:{subject}"
        if int(gen) > 0:
            key = f"{key}:g{int(gen)}"
        if suffix:
            key = f"{key}:{suffix}"
        return {
            'idempotency_key': key[:200],
            'payload': payload,
            'engine_id': self.engine_id,
            'allocation_id': allocation.allocation_id,
            'policy_id': allocation.policy_id,
            'customer_id': allocation.customer_id,
            'entry_type': 'allocation',
            'account_type': '',
        }

    def _seal_allocation_record(
        self,
        allocation: PremiumAllocation,
        *,
        cash_subject: str = '',
        gen: int = 0,
        suffix: str = '',
    ) -> None:
        """Append a sealed allocation header to the durable journal (U5)."""
        try:
            from services.erp.accounting_journal import (
                append_journal_entry, journal_required,
            )
        except Exception:
            return
        item = self._allocation_seal_item(
            allocation, cash_subject=cash_subject, gen=gen, suffix=suffix,
        )
        if item is None:
            return
        result = append_journal_entry(**item)
        reason = str(result.get('reason') or '')
        if not result.get('ok') and (
            journal_required() or reason in _JOURNAL_INTEGRITY_REASONS
        ):
            raise RuntimeError(
                f"accounting journal refused allocation seal: {reason or 'withheld'}"
            )

    def _build_ledger_entry(
        self,
        *,
        allocation_id: str,
        policy_id: str,
        customer_id: str,
        entry_date: date,
        entry_type: EntryType,
        account_type: AccountType,
        debit_amount: Decimal = Decimal(0),
        credit_amount: Decimal = Decimal(0),
        description: str = '',
        reference_no: str = '',
    ) -> AccountingEntry:
        """Build a ledger entry (bumps counter) without journaling or appending."""
        balance = self._get_account_balance(account_type)
        debit = Decimal(str(debit_amount))
        credit = Decimal(str(credit_amount))
        # Include prepared-but-not-yet-appended siblings for running balance
        # when building a multi-line reverse/post batch.
        for pending in getattr(self, '_pending_ledger_entries', []) or []:
            if pending.account_type == account_type:
                balance += Decimal(str(pending.debit_amount or 0))
                balance -= Decimal(str(pending.credit_amount or 0))
        if debit > Decimal('0'):
            balance += debit
        elif credit > Decimal('0'):
            balance -= credit
        balance = balance.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        self.entry_counter += 1
        return AccountingEntry(
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
            posted_by=self.engine_id,
        )

    def _journal_item_for_entry(
        self, entry: AccountingEntry, idempotency_key: str,
    ) -> Dict[str, Any]:
        payload = _stable_journal_payload(
            entry.to_dict(), volatile=_JOURNAL_VOLATILE_ENTRY_FIELDS,
        )
        payload['idempotency_key'] = idempotency_key
        return {
            'idempotency_key': idempotency_key,
            'payload': payload,
            'engine_id': self.engine_id,
            'allocation_id': entry.allocation_id,
            'policy_id': entry.policy_id,
            'customer_id': entry.customer_id,
            'entry_type': entry.entry_type.value,
            'account_type': entry.account_type.value,
        }
    
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
    
    def post_claim_payment(self, claim_id: str, policy_id: str, customer_id: str,
                           amount: Decimal, paid_by: str = "system") -> Tuple[bool, str]:
        """
        Record a claim payment in the accounting ledger.
        Debits the Risk Fund (claim payout reduces risk reserves) and
        credits the customer's account.

        Idempotent on ``claim_id`` (``reference_no`` / ``allocation_id``): a
        second call for the same claim does not double-book.
        """
        try:
            wanted = str(claim_id or "")
            if wanted:
                for entry in self.ledger_entries:
                    if getattr(entry, "entry_type", None) != EntryType.CLAIM_PAYMENT:
                        continue
                    if str(getattr(entry, "reference_no", "") or "") == wanted:
                        return True, f"Claim payment {claim_id} already recorded"
                    if str(getattr(entry, "allocation_id", "") or "") == wanted:
                        return True, f"Claim payment {claim_id} already recorded"
            self._create_ledger_entry(
                allocation_id=claim_id,
                policy_id=policy_id,
                customer_id=customer_id,
                entry_date=date.today(),
                entry_type=EntryType.CLAIM_PAYMENT,
                account_type=AccountType.RISK_FUND,
                credit_amount=Decimal(str(amount)),
                description=f"Claim payment {claim_id} - ${amount:.2f} to customer wallet",
                reference_no=claim_id,
                idempotency_key=f"ae:{self.engine_id}:claim:{claim_id}:risk:credit",
            )
            return True, f"Claim payment {claim_id} for ${amount:.2f} recorded"
        except Exception as e:
            return False, f"Error recording claim payment: {str(e)}"

    def _create_ledger_entry(self, allocation_id: str, policy_id: str, customer_id: str,
                            entry_date: date, entry_type: EntryType, account_type: AccountType,
                            debit_amount: Decimal = Decimal(0), credit_amount: Decimal = Decimal(0),
                            description: str = "", reference_no: str = "",
                            idempotency_key: str = "") -> AccountingEntry:
        """Create and track ledger entry.

        U5: when the durable accounting journal is on, every post also
        inserts a sealed journal row (idempotent key). In ``db`` mode a
        failed journal write refuses the in-memory append (fail closed).
        """
        debit = Decimal(str(debit_amount))
        credit = Decimal(str(credit_amount))
        entry = self._build_ledger_entry(
            allocation_id=allocation_id,
            policy_id=policy_id,
            customer_id=customer_id,
            entry_date=entry_date,
            entry_type=entry_type,
            account_type=account_type,
            debit_amount=debit,
            credit_amount=credit,
            description=description,
            reference_no=reference_no,
        )

        try:
            from services.erp.accounting_journal import (
                append_journal_entry,
                journal_enabled,
                journal_required,
                make_idempotency_key,
            )
        except Exception:
            append_journal_entry = None  # type: ignore
            journal_enabled = lambda: False  # type: ignore
            journal_required = lambda: False  # type: ignore
            make_idempotency_key = None  # type: ignore

        if append_journal_entry is not None and journal_enabled():
            side = 'debit' if debit > Decimal('0') else ('credit' if credit > Decimal('0') else 'zero')
            key = str(idempotency_key or '').strip()
            if not key and make_idempotency_key is not None:
                subject = str(reference_no or allocation_id or entry.entry_no)
                kind = 'claim' if entry_type == EntryType.CLAIM_PAYMENT else 'alloc'
                key = make_idempotency_key(
                    engine_id=self.engine_id,
                    kind=kind,
                    subject_id=subject,
                    account_type=account_type.value,
                    side=side,
                )
            result = append_journal_entry(**self._journal_item_for_entry(entry, key))
            if not result.get('ok'):
                reason = str(result.get('reason') or '')
                # Fail closed on integrity clashes even in dual mode so peer
                # books cannot fork. Transient journal_unavailable still
                # allows the dual memory post — keep the assigned entry_no
                # so the next post does not reuse it (Bugbot U5).
                if journal_required() or reason in _JOURNAL_INTEGRITY_REASONS:
                    self.entry_counter -= 1
                    raise RuntimeError(
                        f"accounting journal refused post: {reason or 'withheld'}"
                    )
            elif result.get('reused'):
                # Match the same generation (content-addressed allocation_id),
                # not just bill+amounts — otherwise a :gN reuse can bind to a
                # still-present gen0 debit after reverse (Security Review).
                for existing in self.ledger_entries:
                    if (
                        str(getattr(existing, 'allocation_id', '') or '') == str(allocation_id or '')
                        and str(getattr(existing, 'reference_no', '') or '') == str(reference_no or '')
                        and getattr(existing, 'entry_type', None) == entry_type
                        and getattr(existing, 'account_type', None) == account_type
                        and Decimal(str(getattr(existing, 'debit_amount', 0) or 0)) == debit
                        and Decimal(str(getattr(existing, 'credit_amount', 0) or 0)) == credit
                    ):
                        self.entry_counter -= 1
                        return existing

        self.ledger_entries.append(entry)
        return entry
    
    def _get_account_balance(self, account_type: AccountType) -> Decimal:
        """Get current balance for account type.

        Sums debits/credits rather than reading a stored running balance —
        journal hydrate omits process-local ``balance`` from sealed payloads.
        """
        balance = Decimal(0)
        for entry in self.ledger_entries:
            if entry.account_type != account_type:
                continue
            balance += Decimal(str(getattr(entry, 'debit_amount', 0) or 0))
            balance -= Decimal(str(getattr(entry, 'credit_amount', 0) or 0))
        return balance.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    
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


_SHARED_ACCOUNTING_ENGINE: Optional[AccountingEngine] = None


def get_accounting_engine() -> AccountingEngine:
    """Return the process-wide accounting engine instance."""
    global _SHARED_ACCOUNTING_ENGINE
    if _SHARED_ACCOUNTING_ENGINE is None:
        _SHARED_ACCOUNTING_ENGINE = AccountingEngine()
    return _SHARED_ACCOUNTING_ENGINE


def reset_accounting_engine(*, clear_journal: bool = False) -> None:
    """Reset the process-wide accounting engine used by server flows.

    ``clear_journal=True`` wipes durable journal rows (test isolation only).
    Peer-hydrate tests reset memory while keeping the journal, so the
    default leaves seals intact; root ``conftest`` clears between cases.
    """
    global _SHARED_ACCOUNTING_ENGINE
    _SHARED_ACCOUNTING_ENGINE = None
    if clear_journal:
        try:
            from services.erp.accounting_journal import clear_journal_for_tests
            clear_journal_for_tests()
        except Exception:
            pass

