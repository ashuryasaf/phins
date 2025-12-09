"""
PHINS Insurance Management System
Python Implementation
Version 1.0.0
"""

from datetime import datetime, timedelta
from enum import Enum
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from abc import ABC, abstractmethod
from decimal import Decimal


# ============================================================================
# ENUMS - Status and Type Definitions
# ============================================================================

class PolicyStatus(Enum):
    """Policy lifecycle statuses"""
    ACTIVE = "Active"
    INACTIVE = "Inactive"
    CANCELLED = "Cancelled"
    LAPSED = "Lapsed"
    SUSPENDED = "Suspended"


class UnderwritingStatus(Enum):
    """Underwriting decision statuses"""
    PENDING = "Pending"
    APPROVED = "Approved"
    REJECTED = "Rejected"
    REFERRED = "Referred"
    APPROVED_CONDITIONAL = "Approved-Conditional"


class ClaimStatus(Enum):
    """Claim processing statuses"""
    PENDING = "Pending"
    UNDER_REVIEW = "Under Review"
    APPROVED = "Approved"
    REJECTED = "Rejected"
    PAID = "Paid"
    CLOSED = "Closed"


class BillStatus(Enum):
    """Billing statuses"""
    OUTSTANDING = "Outstanding"
    PARTIAL = "Partial"
    PAID = "Paid"
    OVERDUE = "Overdue"
    CANCELLED = "Cancelled"


class PolicyType(Enum):
    """Insurance policy types"""
    AUTO = "Auto"
    HOME = "Home"
    HEALTH = "Health"
    LIFE = "Life"
    COMMERCIAL = "Commercial"
    LIABILITY = "Liability"
    OTHER = "Other"


class CustomerType(Enum):
    """Customer classification"""
    INDIVIDUAL = "Individual"
    BUSINESS = "Business"
    CORPORATE = "Corporate"


class PaymentFrequency(Enum):
    """Billing payment frequency"""
    MONTHLY = "Monthly"
    QUARTERLY = "Quarterly"
    SEMI_ANNUAL = "Semi-Annual"
    ANNUAL = "Annual"


class RiskLevel(Enum):
    """Underwriting risk assessment levels"""
    LOW = "Low"
    MEDIUM = "Medium"
    HIGH = "High"
    VERY_HIGH = "Very High"


class ReinsuranceType(Enum):
    """Types of reinsurance arrangements"""
    PROPORTIONAL = "Proportional"
    NON_PROPORTIONAL = "Non-Proportional"
    EXCESS_OF_LOSS = "Excess of Loss"
    STOP_LOSS = "Stop Loss"
    FACULTATIVE = "Facultative"


class PaymentMethod(Enum):
    """Payment methods"""
    CREDIT_CARD = "Credit Card"
    BANK_TRANSFER = "Bank Transfer"
    CHEQUE = "Cheque"
    CASH = "Cash"
    ONLINE_PORTAL = "Online Portal"


class FileType(Enum):
    """Document file types"""
    POLICY_DOCUMENT = "Policy Document"
    CLAIM_FORM = "Claim Form"
    MEDICAL_REPORT = "Medical Report"
    PROOF_OF_LOSS = "Proof of Loss"
    INVOICE = "Invoice"
    PAYMENT_RECEIPT = "Payment Receipt"
    ID_DOCUMENT = "ID Document"
    INSURANCE_CARD = "Insurance Card"
    OTHER = "Other"


class FileStatus(Enum):
    """File processing status"""
    UPLOADED = "Uploaded"
    VERIFIED = "Verified"
    REJECTED = "Rejected"
    ARCHIVED = "Archived"


class DocumentDivision(Enum):
    """Document ownership by division"""
    SALES = "Sales"
    UNDERWRITING = "Underwriting"
    CLAIMS = "Claims"
    ACCOUNTING = "Accounting"
    LEGAL = "Legal"
    REINSURANCE = "Reinsurance"
    ACTUARIAL = "Actuarial"
    RISK_MANAGEMENT = "Risk Management"
    CUSTOMER_PORTAL = "Customer Portal"


class HealthStatus(Enum):
    """Health status for permanent health tables"""
    EXCELLENT = "Excellent"
    GOOD = "Good"
    FAIR = "Fair"
    POOR = "Poor"
    CRITICAL = "Critical"


class RiskCategory(Enum):
    """Risk categorization for pricing"""
    VERY_LOW = "Very Low"
    LOW = "Low"
    MEDIUM = "Medium"
    HIGH = "High"
    VERY_HIGH = "Very High"
    EXTREME = "Extreme"


class HedgingStrategy(Enum):
    """Reinsurance hedging strategies"""
    PROPORTIONAL = "Proportional"
    EXCESS_OF_LOSS = "Excess of Loss"
    STOP_LOSS = "Stop Loss"
    AGGREGATE = "Aggregate"
    CATASTROPHE = "Catastrophe"


class ActuarialRole(Enum):
    """Roles in actuarial department"""
    CHIEF_ACTUARY = "Chief Actuary"
    SENIOR_ACTUARY = "Senior Actuary"
    ACTUARY = "Actuary"
    JUNIOR_ACTUARY = "Junior Actuary"
    RISK_ANALYST = "Risk Analyst"


# ============================================================================
# BASE MODEL - Abstract base class for all entities
# ============================================================================

@dataclass
class BaseEntity:
    """Base class for all database entities"""
    created_date: datetime = field(default_factory=datetime.now)
    last_modified: datetime = field(default_factory=datetime.now)

    def update(self):
        """Update the last modified timestamp"""
        self.last_modified = datetime.now()


# ============================================================================
# FILE MANAGEMENT - Document handling across divisions
# ============================================================================

@dataclass
class Document:
    """Document/File record for all divisions"""
    document_id: str
    file_name: str
    file_type: FileType
    division: DocumentDivision
    related_entity_id: str  # Policy ID, Claim ID, Customer ID, etc.
    related_entity_type: str  # 'Policy', 'Claim', 'Customer', 'Bill', etc.
    file_size: int  # bytes
    file_path: str
    uploaded_by: str
    status: FileStatus = FileStatus.UPLOADED
    verified_by: Optional[str] = None
    rejection_reason: Optional[str] = None
    description: str = ""
    created_date: datetime = field(default_factory=datetime.now)
    last_modified: datetime = field(default_factory=datetime.now)

    @property
    def file_size_mb(self) -> float:
        """Get file size in MB"""
        return round(self.file_size / (1024 * 1024), 2)

    def verify(self, verified_by: str):
        """Verify document"""
        self.status = FileStatus.VERIFIED
        self.verified_by = verified_by
        self.last_modified = datetime.now()

    def reject(self, verified_by: str, reason: str):
        """Reject document"""
        self.status = FileStatus.REJECTED
        self.verified_by = verified_by
        self.rejection_reason = reason
        self.last_modified = datetime.now()

    def archive(self):
        """Archive document"""
        self.status = FileStatus.ARCHIVED
        self.last_modified = datetime.now()

    def __str__(self):
        return f"Document {self.document_id} - {self.file_name} ({self.file_size_mb} MB)"


# ============================================================================
# ACTUARIAL & RISK MANAGEMENT TABLES
# ============================================================================

@dataclass
class HealthTable:
    """Permanent health/mortality tables - actuarial reference data"""
    table_id: str
    table_name: str
    age_from: int
    age_to: int
    gender: str  # "M", "F", "U" (Unisex)
    health_status: HealthStatus
    mortality_rate: float  # Annual probability of death (per 1,000)
    morbidity_rate: float  # Annual probability of illness (per 1,000)
    prevalence_rate: float  # % of population in this health category
    average_claim_cost: Decimal  # Average claim payout for this cohort
    data_year: int  # Year table is based on (e.g., 2023)
    source: str  # e.g., "SOA Mortality Table", "CMI Data", "Internal Experience"
    created_date: datetime = field(default_factory=datetime.now)
    last_modified: datetime = field(default_factory=datetime.now)

    def get_annual_risk_probability(self) -> float:
        """Return combined annual risk as probability (0-1)"""
        return (self.mortality_rate + self.morbidity_rate) / 1000.0
    
    def __str__(self):
        return f"Health Table {self.table_id} - {self.health_status.value} ({self.age_from}-{self.age_to})"


@dataclass
class PricingModel:
    """Actuarial pricing model for premium calculation"""
    model_id: str
    policy_type: str  # e.g., "Term Life", "Whole Life", "Critical Illness"
    base_premium: Decimal  # Base premium per $1,000 coverage
    risk_adjustment_factor: float  # Multiplier for risk (1.0 = standard)
    underwriting_class: str  # "Standard", "Preferred", "Substandard"
    age_min: int
    age_max: int
    effective_date: datetime
    expiry_date: datetime
    profit_margin: float  # % markup for profit (0.2 = 20%)
    lapse_assumption: float  # Expected annual lapse rate
    inflation_factor: float  # Premium inflation adjustment
    created_date: datetime = field(default_factory=datetime.now)
    last_modified: datetime = field(default_factory=datetime.now)

    def calculate_premium(self, coverage_amount: Decimal, health_data: Dict[str, Any], 
                         age: int, tenure_years: int = 1) -> Decimal:
        """Calculate premium based on coverage and health"""
        # Premium per $1,000 coverage × coverage amount ÷ 1,000
        base = self.base_premium * coverage_amount / Decimal(1000)
        
        # Apply risk adjustment
        risk_factor = Decimal(str(self.risk_adjustment_factor))
        adjusted = base * risk_factor
        
        # Apply age adjustment (simplified: 1% per year over base age)
        age_adjustment = Decimal(str(1 + (age - 30) * 0.01)) if age > 30 else Decimal("1.0")
        adjusted = adjusted * age_adjustment
        
        # Apply profit margin
        profit_multiplier = Decimal(str(1 + self.profit_margin))
        final_premium = adjusted * profit_multiplier
        
        return final_premium.quantize(Decimal("0.01"))
    
    def __str__(self):
        return f"Model {self.model_id} - {self.policy_type} ({self.underwriting_class})"


@dataclass
class RiskAssessment:
    """Actuarial risk assessment linking health data to premium"""
    assessment_id: str
    customer_id: str
    policy_id: str
    health_table_id: str  # FK to HealthTable
    risk_category: RiskCategory
    numerical_risk_score: float  # 0-100 scale
    mortality_risk_percentile: float  # Percentile vs population
    pricing_model_id: str  # FK to PricingModel
    base_premium: Decimal
    risk_adjusted_premium: Decimal
    required_underwriting: str  # "None", "Standard", "Full Medical", "APS Required"
    special_conditions: List[str] = field(default_factory=list)  # e.g., ["Smoker", "Hazardous Occupation"]
    assessment_date: datetime = field(default_factory=datetime.now)
    assessed_by: str = ""
    created_date: datetime = field(default_factory=datetime.now)
    last_modified: datetime = field(default_factory=datetime.now)

    def get_risk_description(self) -> str:
        """Human-readable risk description"""
        descriptions = {
            RiskCategory.VERY_LOW: "Excellent health, preferred risk",
            RiskCategory.LOW: "Good health, standard risk",
            RiskCategory.MEDIUM: "Average health, acceptable risk",
            RiskCategory.HIGH: "Health issues present, heightened underwriting",
            RiskCategory.VERY_HIGH: "Serious health concerns, extensive medical required",
            RiskCategory.EXTREME: "Uninsurable or special terms required"
        }
        return descriptions.get(self.risk_category, "Unknown")
    
    def __str__(self):
        return f"Assessment {self.assessment_id} - Risk: {self.risk_category.value}, Score: {self.numerical_risk_score}"


@dataclass
class ReinsuranceHedge:
    """Reinsurance hedging arrangement for risk mitigation"""
    hedge_id: str
    reinsurance_id: str  # FK to Reinsurance (main arrangement)
    hedging_strategy: HedgingStrategy
    total_premium_at_risk: Decimal
    retention_level: Decimal  # Amount company retains (absolute)
    retention_percentage: float  # Retention as %
    ceded_amount: Decimal  # Amount transferred to reinsurer
    expected_loss_ratio: float  # Expected losses ÷ Premium
    break_even_loss_ratio: float  # Loss ratio where reinsurer breaks even
    reinsurance_cost: Decimal  # Premium paid to reinsurer
    commission_rate: float  # Commission earned from reinsurer
    commission_amount: Decimal  # Calculated commission
    effective_date: datetime
    expiry_date: datetime
    minimum_deductible: Decimal  # Min per-claim deductible
    maximum_coverage_per_claim: Decimal  # Cap per claim
    aggregate_limit: Decimal  # Total limit for all claims
    created_date: datetime = field(default_factory=datetime.now)
    last_modified: datetime = field(default_factory=datetime.now)

    def calculate_net_premium(self) -> Decimal:
        """Calculate net premium after reinsurance cost"""
        return self.total_premium_at_risk - self.reinsurance_cost

    def calculate_hedging_efficiency(self) -> float:
        """% of risk transferred to reinsurer"""
        if self.total_premium_at_risk == 0:
            return 0.0
        return float(self.ceded_amount / self.total_premium_at_risk)

    def expected_company_loss(self) -> Decimal:
        """Expected loss company will bear"""
        total_expected = self.total_premium_at_risk * Decimal(str(self.expected_loss_ratio))
        return total_expected - self.ceded_amount
    
    def __str__(self):
        return f"Hedge {self.hedge_id} - {self.hedging_strategy.value}, Ceded: ${self.ceded_amount}"


# ============================================================================
# TABLES - Data Models
# ============================================================================

@dataclass
class Company:
    """Insurance company master data"""
    company_id: str
    name: str
    registration_number: str
    business_address: str
    phone: str
    email: str
    license_number: str
    website: str = ""
    status: str = "Active"
    foundation_date: Optional[datetime] = None
    created_date: datetime = field(default_factory=datetime.now)
    last_modified: datetime = field(default_factory=datetime.now)

    def __str__(self):
        return f"{self.name} ({self.company_id})"
    
    def update(self):
        """Update the last modified timestamp"""
        self.last_modified = datetime.now()


@dataclass
class Customer:
    """Customer master data"""
    customer_id: str
    first_name: str
    last_name: str
    email: str
    phone: str
    address: str
    city: str
    state: str
    postal_code: str
    country_code: str
    customer_type: CustomerType
    identification_number: str
    portal_access: bool = True
    status: str = "Active"
    created_date: datetime = field(default_factory=datetime.now)
    last_modified: datetime = field(default_factory=datetime.now)

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}"

    def __str__(self):
        return f"{self.full_name} ({self.customer_id})"
    
    def update(self):
        """Update the last modified timestamp"""
        self.last_modified = datetime.now()


@dataclass
class InsurancePolicy:
    """Insurance policy master"""
    policy_id: str
    customer_id: str
    policy_type: PolicyType
    start_date: datetime
    end_date: datetime
    premium_amount: float
    coverage_amount: float
    deductible: float
    notes: str = ""
    status: PolicyStatus = PolicyStatus.ACTIVE
    underwriting_status: UnderwritingStatus = UnderwritingStatus.PENDING
    payment_frequency: PaymentFrequency = PaymentFrequency.ANNUAL
    last_payment_date: Optional[datetime] = None
    next_payment_due: Optional[datetime] = None
    total_claims: int = 0
    created_date: datetime = field(default_factory=datetime.now)
    last_modified: datetime = field(default_factory=datetime.now)

    def is_active(self) -> bool:
        return self.status == PolicyStatus.ACTIVE and datetime.now() < self.end_date

    def renew(self):
        """Renew the policy for another year"""
        self.start_date = self.end_date + timedelta(days=1)
        self.end_date = self.start_date + timedelta(days=365)
        self.underwriting_status = UnderwritingStatus.PENDING
        self.update()

    def __str__(self):
        return f"Policy {self.policy_id} - {self.policy_type.value} (${self.premium_amount})"
    
    def update(self):
        """Update the last modified timestamp"""
        self.last_modified = datetime.now()


@dataclass
class Claim:
    """Insurance claim record"""
    claim_id: str
    policy_id: str
    customer_id: str
    claim_date: datetime
    incident_date: datetime
    description: str
    claim_amount: float
    assigned_to: str = ""
    priority: str = "Medium"
    notes: str = ""
    status: ClaimStatus = ClaimStatus.PENDING
    approved_amount: float = 0.0
    payment_date: Optional[datetime] = None
    created_date: datetime = field(default_factory=datetime.now)
    last_modified: datetime = field(default_factory=datetime.now)

    def approve(self, approved_amount: float):
        """Approve the claim"""
        self.status = ClaimStatus.APPROVED
        self.approved_amount = approved_amount
        self.update()

    def reject(self, reason: str):
        """Reject the claim"""
        self.status = ClaimStatus.REJECTED
        self.notes = reason
        self.update()

    def process_payment(self):
        """Mark claim as paid"""
        if self.status == ClaimStatus.APPROVED and self.approved_amount > 0:
            self.status = ClaimStatus.PAID
            self.payment_date = datetime.now()
            self.update()
            return True
        return False

    def __str__(self):
        return f"Claim {self.claim_id} - {self.status.value} (${self.claim_amount})"
    
    def update(self):
        """Update the last modified timestamp"""
        self.last_modified = datetime.now()


@dataclass
class Bill:
    """Billing and invoice record"""
    bill_id: str
    policy_id: str
    customer_id: str
    bill_date: datetime
    due_date: datetime
    amount_due: float
    description: str = ""
    amount_paid: float = 0.0
    status: BillStatus = BillStatus.OUTSTANDING
    last_payment_date: Optional[datetime] = None
    payment_method: Optional[PaymentMethod] = None
    late_fee_applied: float = 0.0
    created_date: datetime = field(default_factory=datetime.now)
    last_modified: datetime = field(default_factory=datetime.now)

    @property
    def balance(self) -> float:
        return self.amount_due - self.amount_paid

    @property
    def is_overdue(self) -> bool:
        return self.due_date < datetime.now() and self.status != BillStatus.PAID

    def record_payment(self, amount: float, method: PaymentMethod) -> bool:
        """Record a payment"""
        if amount <= 0:
            return False
        
        self.amount_paid += amount
        self.last_payment_date = datetime.now()
        self.payment_method = method
        
        if self.amount_paid >= self.amount_due:
            self.status = BillStatus.PAID
        elif self.amount_paid > 0:
            self.status = BillStatus.PARTIAL
        
        self.update()
        return True

    def apply_late_fee(self, percentage: float):
        """Apply late fee to overdue bill"""
        if self.is_overdue:
            late_fee = self.amount_due * (percentage / 100)
            self.late_fee_applied = late_fee
            self.amount_due += late_fee
            self.update()

    def __str__(self):
        return f"Bill {self.bill_id} - {self.status.value} (Balance: ${self.balance})"
    
    def update(self):
        """Update the last modified timestamp"""
        self.last_modified = datetime.now()


@dataclass
class Underwriting:
    """Underwriting assessment record"""
    underwriting_id: str
    policy_id: str
    customer_id: str
    comments: str = ""
    assigned_underwriter: str = ""
    premium_adjustment: float = 0.0
    risk_assessment: RiskLevel = RiskLevel.MEDIUM
    decision: UnderwritingStatus = UnderwritingStatus.PENDING
    medical_required: bool = False
    additional_documents_required: bool = False
    submission_date: datetime = field(default_factory=datetime.now)
    review_date: Optional[datetime] = None
    created_date: datetime = field(default_factory=datetime.now)
    last_modified: datetime = field(default_factory=datetime.now)

    def assess_risk(self, risk_level: RiskLevel, medical_req: bool, docs_req: bool):
        """Perform risk assessment"""
        self.risk_assessment = risk_level
        self.medical_required = medical_req
        self.additional_documents_required = docs_req
        self.update()

    def approve(self, premium_adjustment: float = 0.0):
        """Approve underwriting"""
        self.decision = UnderwritingStatus.APPROVED
        self.review_date = datetime.now()
        self.premium_adjustment = premium_adjustment
        self.update()

    def reject(self, reason: str):
        """Reject underwriting"""
        self.decision = UnderwritingStatus.REJECTED
        self.review_date = datetime.now()
        self.comments = reason
        self.update()

    def request_more_info(self, info_required: str):
        """Request additional information"""
        self.decision = UnderwritingStatus.REFERRED
        self.additional_documents_required = True
        self.comments = info_required
        self.update()

    def __str__(self):
        return f"Underwriting {self.underwriting_id} - {self.decision.value} ({self.risk_assessment.value} Risk)"
    
    def update(self):
        """Update the last modified timestamp"""
        self.last_modified = datetime.now()


@dataclass
class Reinsurance:
    """Reinsurance arrangement record"""
    reinsurance_id: str
    policy_id: str
    reinsurance_partner: str
    reinsurance_type: ReinsuranceType
    ceded_amount: float
    commission_rate: float
    notes: str = ""
    status: str = "Active"
    start_date: datetime = field(default_factory=datetime.now)
    end_date: Optional[datetime] = None
    created_date: datetime = field(default_factory=datetime.now)
    last_modified: datetime = field(default_factory=datetime.now)

    @property
    def commission_earned(self) -> float:
        return self.ceded_amount * (self.commission_rate / 100)

    def __str__(self):
        return f"Reinsurance {self.reinsurance_id} - {self.reinsurance_partner} (${self.ceded_amount})"
    
    def update(self):
        """Update the last modified timestamp"""
        self.last_modified = datetime.now()


# ============================================================================
# BUSINESS LOGIC - Codeunit Equivalents
# ============================================================================

class PolicyManagement:
    """Policy lifecycle management"""

    @staticmethod
    def create_policy(customer_id: str, policy_type: PolicyType, start_date: datetime,
                     premium_amount: float, coverage_amount: float, deductible: float) -> InsurancePolicy:
        """Create a new insurance policy"""
        policy_id = PolicyManagement.generate_policy_id()
        policy = InsurancePolicy(
            policy_id=policy_id,
            customer_id=customer_id,
            policy_type=policy_type,
            start_date=start_date,
            end_date=start_date + timedelta(days=365),
            premium_amount=premium_amount,
            coverage_amount=coverage_amount,
            deductible=deductible
        )
        return policy

    @staticmethod
    def renew_policy(policy: InsurancePolicy):
        """Renew an existing policy"""
        policy.renew()

    @staticmethod
    def cancel_policy(policy: InsurancePolicy, reason: str):
        """Cancel a policy"""
        policy.status = PolicyStatus.CANCELLED
        policy.notes = reason
        policy.update()

    @staticmethod
    def suspend_policy(policy: InsurancePolicy):
        """Suspend a policy"""
        policy.status = PolicyStatus.SUSPENDED
        policy.update()

    @staticmethod
    def reactivate_policy(policy: InsurancePolicy) -> bool:
        """Reactivate a suspended policy"""
        if policy.status == PolicyStatus.SUSPENDED:
            policy.status = PolicyStatus.ACTIVE
            policy.update()
            return True
        return False

    @staticmethod
    def generate_policy_id() -> str:
        """Generate unique policy ID"""
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        return f"POL{timestamp}"


class ClaimsManagement:
    """Claims processing management"""

    @staticmethod
    def create_claim(policy_id: str, customer_id: str, claim_amount: float,
                    description: str, incident_date: Optional[datetime] = None) -> Claim:
        """Create a new claim"""
        claim_id = ClaimsManagement.generate_claim_id()
        claim = Claim(
            claim_id=claim_id,
            policy_id=policy_id,
            customer_id=customer_id,
            claim_date=datetime.now(),
            incident_date=incident_date or datetime.now(),
            description=description,
            claim_amount=claim_amount
        )
        return claim

    @staticmethod
    def approve_claim(claim: Claim, approved_amount: float):
        """Approve a claim"""
        claim.approve(approved_amount)

    @staticmethod
    def reject_claim(claim: Claim, reason: str):
        """Reject a claim"""
        claim.reject(reason)

    @staticmethod
    def process_claim_payment(claim: Claim) -> bool:
        """Process payment for approved claim"""
        return claim.process_payment()

    @staticmethod
    def get_claim_status(claim: Claim) -> str:
        """Get current claim status"""
        return claim.status.value

    @staticmethod
    def generate_claim_id() -> str:
        """Generate unique claim ID"""
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        return f"CLM{timestamp}"


class BillingManagement:
    """Billing and payment management"""

    @staticmethod
    def create_bill(policy_id: str, customer_id: str, amount_due: float,
                   description: str = "") -> Bill:
        """Create a new bill"""
        bill_id = BillingManagement.generate_bill_id()
        bill = Bill(
            bill_id=bill_id,
            policy_id=policy_id,
            customer_id=customer_id,
            bill_date=datetime.now(),
            due_date=datetime.now() + timedelta(days=30),
            amount_due=amount_due,
            description=description
        )
        return bill

    @staticmethod
    def record_payment(bill: Bill, amount: float, method: PaymentMethod) -> bool:
        """Record a payment on a bill"""
        return bill.record_payment(amount, method)

    @staticmethod
    def apply_late_fee(bill: Bill, late_fee_percentage: float = 5.0):
        """Apply late fee to overdue bill"""
        bill.apply_late_fee(late_fee_percentage)

    @staticmethod
    def get_billing_statement(bills: List[Bill]) -> Dict:
        """Generate billing statement summary"""
        total_due = sum(bill.amount_due for bill in bills if bill.status != BillStatus.PAID)
        overdue_count = sum(1 for bill in bills if bill.is_overdue)
        
        return {
            "total_due": total_due,
            "overdue_count": overdue_count,
            "bills_count": len(bills),
            "paid_count": sum(1 for bill in bills if bill.status == BillStatus.PAID)
        }

    @staticmethod
    def generate_bill_id() -> str:
        """Generate unique bill ID"""
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        return f"BILL{timestamp}"


class UnderwritingEngine:
    """Underwriting assessment and approval"""

    @staticmethod
    def initiate_underwriting(policy_id: str, customer_id: str) -> Underwriting:
        """Initiate underwriting assessment"""
        uw_id = UnderwritingEngine.generate_underwriting_id()
        underwriting = Underwriting(
            underwriting_id=uw_id,
            policy_id=policy_id,
            customer_id=customer_id
        )
        return underwriting

    @staticmethod
    def assess_risk(underwriting: Underwriting, risk_level: RiskLevel,
                   medical_required: bool = False, additional_docs: bool = False):
        """Perform risk assessment"""
        underwriting.assess_risk(risk_level, medical_required, additional_docs)

    @staticmethod
    def approve_underwriting(underwriting: Underwriting, premium_adjustment: float = 0.0) -> bool:
        """Approve underwriting assessment"""
        underwriting.approve(premium_adjustment)
        return True

    @staticmethod
    def reject_underwriting(underwriting: Underwriting, reason: str):
        """Reject underwriting assessment"""
        underwriting.reject(reason)

    @staticmethod
    def request_additional_info(underwriting: Underwriting, info_required: str):
        """Request additional information"""
        underwriting.request_more_info(info_required)

    @staticmethod
    def get_underwriting_status(underwriting: Underwriting) -> str:
        """Get underwriting status"""
        return underwriting.decision.value

    @staticmethod
    def generate_underwriting_id() -> str:
        """Generate unique underwriting ID"""
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        return f"UW{timestamp}"


class FileManagement:
    """File and document management across all divisions"""

    @staticmethod
    def upload_document(file_name: str, file_type: FileType, division: DocumentDivision,
                       related_entity_id: str, related_entity_type: str,
                       file_size: int, file_path: str, uploaded_by: str,
                       description: str = "") -> Document:
        """Upload a new document"""
        doc_id = FileManagement.generate_document_id()
        document = Document(
            document_id=doc_id,
            file_name=file_name,
            file_type=file_type,
            division=division,
            related_entity_id=related_entity_id,
            related_entity_type=related_entity_type,
            file_size=file_size,
            file_path=file_path,
            uploaded_by=uploaded_by,
            description=description
        )
        return document

    @staticmethod
    def verify_document(document: Document, verified_by: str):
        """Verify and approve a document"""
        document.verify(verified_by)

    @staticmethod
    def reject_document(document: Document, verified_by: str, reason: str):
        """Reject a document"""
        document.reject(verified_by, reason)

    @staticmethod
    def archive_document(document: Document):
        """Archive a document"""
        document.archive()

    @staticmethod
    def get_documents_by_entity(documents: List[Document], entity_id: str) -> List[Document]:
        """Get all documents for a specific entity (Policy, Claim, etc.)"""
        return [d for d in documents if d.related_entity_id == entity_id]

    @staticmethod
    def get_documents_by_division(documents: List[Document], division: DocumentDivision) -> List[Document]:
        """Get all documents for a specific division"""
        return [d for d in documents if d.division == division]

    @staticmethod
    def get_documents_by_type(documents: List[Document], file_type: FileType) -> List[Document]:
        """Get all documents of a specific type"""
        return [d for d in documents if d.file_type == file_type]

    @staticmethod
    def get_documents_by_status(documents: List[Document], status: FileStatus) -> List[Document]:
        """Get documents with a specific status"""
        return [d for d in documents if d.status == status]

    @staticmethod
    def get_pending_verification(documents: List[Document]) -> List[Document]:
        """Get documents pending verification"""
        return FileManagement.get_documents_by_status(documents, FileStatus.UPLOADED)

    @staticmethod
    def get_rejected_documents(documents: List[Document]) -> List[Document]:
        """Get rejected documents"""
        return FileManagement.get_documents_by_status(documents, FileStatus.REJECTED)

    @staticmethod
    def get_verified_documents(documents: List[Document]) -> List[Document]:
        """Get verified documents"""
        return FileManagement.get_documents_by_status(documents, FileStatus.VERIFIED)

    @staticmethod
    def generate_document_id() -> str:
        """Generate unique document ID"""
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        return f"DOC{timestamp}"

    @staticmethod
    def calculate_total_storage(documents: List[Document]) -> Dict:
        """Calculate storage statistics"""
        total_bytes = sum(d.file_size for d in documents)
        total_mb = round(total_bytes / (1024 * 1024), 2)
        total_gb = round(total_bytes / (1024 * 1024 * 1024), 2)
        
        return {
            "total_files": len(documents),
            "total_bytes": total_bytes,
            "total_mb": total_mb,
            "total_gb": total_gb,
            "verified": len(FileManagement.get_verified_documents(documents)),
            "pending": len(FileManagement.get_pending_verification(documents)),
            "rejected": len(FileManagement.get_rejected_documents(documents))
        }


class ActuaryManagement:
    """Actuarial and risk management operations"""

    @staticmethod
    def create_health_table(table_name: str, age_from: int, age_to: int, gender: str,
                           health_status: HealthStatus, mortality_rate: float,
                           morbidity_rate: float, prevalence_rate: float,
                           average_claim_cost: Decimal, data_year: int,
                           source: str) -> HealthTable:
        """Create a new health/mortality table entry"""
        table_id = f"HLT{datetime.now().strftime('%Y%m%d%H%M%S')}"
        return HealthTable(
            table_id=table_id,
            table_name=table_name,
            age_from=age_from,
            age_to=age_to,
            gender=gender,
            health_status=health_status,
            mortality_rate=mortality_rate,
            morbidity_rate=morbidity_rate,
            prevalence_rate=prevalence_rate,
            average_claim_cost=average_claim_cost,
            data_year=data_year,
            source=source
        )

    @staticmethod
    def create_pricing_model(policy_type: str, base_premium: Decimal,
                            risk_adjustment_factor: float, underwriting_class: str,
                            age_min: int, age_max: int, effective_date: datetime,
                            expiry_date: datetime, profit_margin: float,
                            lapse_assumption: float, inflation_factor: float) -> PricingModel:
        """Create a pricing model"""
        model_id = f"PRM{datetime.now().strftime('%Y%m%d%H%M%S')}"
        return PricingModel(
            model_id=model_id,
            policy_type=policy_type,
            base_premium=base_premium,
            risk_adjustment_factor=risk_adjustment_factor,
            underwriting_class=underwriting_class,
            age_min=age_min,
            age_max=age_max,
            effective_date=effective_date,
            expiry_date=expiry_date,
            profit_margin=profit_margin,
            lapse_assumption=lapse_assumption,
            inflation_factor=inflation_factor
        )

    @staticmethod
    def assess_risk(customer_id: str, policy_id: str, health_table_id: str,
                   pricing_model_id: str, age: int, health_status: HealthStatus,
                   health_table: HealthTable, pricing_model: PricingModel,
                   coverage_amount: Decimal, assessed_by: str = "System") -> RiskAssessment:
        """Perform actuarial risk assessment"""
        assessment_id = f"RSK{datetime.now().strftime('%Y%m%d%H%M%S')}"
        
        # Calculate numerical risk score (0-100)
        risk_probability = health_table.get_annual_risk_probability()
        numerical_score = min(100, risk_probability * 1000)
        
        # Determine risk category based on score
        if numerical_score < 5:
            risk_cat = RiskCategory.VERY_LOW
        elif numerical_score < 15:
            risk_cat = RiskCategory.LOW
        elif numerical_score < 30:
            risk_cat = RiskCategory.MEDIUM
        elif numerical_score < 60:
            risk_cat = RiskCategory.HIGH
        elif numerical_score < 100:
            risk_cat = RiskCategory.VERY_HIGH
        else:
            risk_cat = RiskCategory.EXTREME
        
        # Calculate premiums
        base_premium = pricing_model.calculate_premium(coverage_amount, 
                                                       {"health_status": health_status.value}, age)
        risk_adjusted = base_premium * Decimal(str(1 + (numerical_score / 100)))
        
        # Determine underwriting requirements
        if numerical_score < 10:
            requirements = "None"
        elif numerical_score < 30:
            requirements = "Standard"
        elif numerical_score < 70:
            requirements = "Full Medical"
        else:
            requirements = "APS Required"
        
        return RiskAssessment(
            assessment_id=assessment_id,
            customer_id=customer_id,
            policy_id=policy_id,
            health_table_id=health_table_id,
            risk_category=risk_cat,
            numerical_risk_score=numerical_score,
            mortality_risk_percentile=health_table.mortality_rate,
            pricing_model_id=pricing_model_id,
            base_premium=base_premium,
            risk_adjusted_premium=risk_adjusted,
            required_underwriting=requirements,
            assessed_by=assessed_by
        )

    @staticmethod
    def calculate_reserves(total_annual_premium: Decimal, expected_loss_ratio: float,
                          years: int = 1) -> Dict[str, Decimal]:
        """Calculate actuarial reserves"""
        expected_losses = total_annual_premium * Decimal(str(expected_loss_ratio))
        unexpired_exposure = total_annual_premium * Decimal(str(years))
        unearned_premium = total_annual_premium * Decimal(str(1 - (1 / 12)))  # 11/12 for mid-year
        
        return {
            "expected_losses": expected_losses,
            "unearned_premium": unearned_premium,
            "loss_reserve": expected_losses,
            "total_reserves_required": expected_losses + unearned_premium,
            "reserve_percentage": (expected_losses + unearned_premium) / total_annual_premium if total_annual_premium > 0 else Decimal("0")
        }

    @staticmethod
    def determine_hedging_strategy(total_premium: Decimal, expected_loss_ratio: float,
                                  retention_percentage: float) -> Dict[str, Any]:
        """Determine reinsurance hedging strategy and costs"""
        retention = total_premium * Decimal(str(retention_percentage / 100))
        ceded = total_premium - retention
        
        # Hedging cost increases with higher ceded amount
        hedging_cost_rate = 0.35 + (float(ceded / total_premium) * 0.15) if total_premium > 0 else 0.35
        hedging_cost = ceded * Decimal(str(hedging_cost_rate))
        
        # Commission typically 20-35% of ceded premium
        commission_rate = 0.25
        commission = ceded * Decimal(str(commission_rate))
        
        # Net premium after hedging
        net_premium = total_premium - hedging_cost
        
        return {
            "retention": retention,
            "ceded": ceded,
            "ceded_percentage": float(ceded / total_premium) * 100 if total_premium > 0 else 0,
            "hedging_cost": hedging_cost,
            "hedging_cost_rate": hedging_cost_rate,
            "commission": commission,
            "commission_rate": commission_rate,
            "net_premium": net_premium,
            "break_even_loss_ratio": 1 + (float(hedging_cost) / float(ceded)) if ceded > 0 else 1.0,
            "recommended_strategy": HedgingStrategy.EXCESS_OF_LOSS.value if expected_loss_ratio > 0.7 else HedgingStrategy.PROPORTIONAL.value
        }

    @staticmethod
    def validate_pricing(policy_type: str, customer_age: int, health_status: HealthStatus,
                        coverage_amount: Decimal, calculated_premium: Decimal) -> Dict[str, Any]:
        """Validate premium pricing against underwriting guidelines"""
        issues = []
        warnings = []
        
        # Check age appropriateness
        if policy_type == "Term Life":
            if customer_age > 75:
                issues.append("Age exceeds maximum for Term Life insurance")
            elif customer_age > 65:
                warnings.append("Age approaching upper limits; expect higher premiums")
        
        # Check health status
        if health_status == HealthStatus.CRITICAL:
            issues.append("Critical health status; special underwriting required")
        elif health_status == HealthStatus.POOR:
            warnings.append("Poor health status; may require APS and medical exam")
        
        # Check premium reasonableness
        expected_minimum = coverage_amount * Decimal("0.005")  # 0.5% of coverage
        expected_maximum = coverage_amount * Decimal("0.05")   # 5% of coverage
        
        if calculated_premium < expected_minimum:
            warnings.append(f"Premium ${calculated_premium} below typical range for coverage amount")
        elif calculated_premium > expected_maximum:
            warnings.append(f"Premium ${calculated_premium} above typical range; review for accuracy")
        
        return {
            "is_valid": len(issues) == 0,
            "issues": issues,
            "warnings": warnings,
            "approved_for_underwriting": len(issues) == 0
        }


# ============================================================================
# SYSTEM MANAGER - Main business orchestration
# ============================================================================

class PHINSInsuranceSystem:
    """Main PHINS Insurance Management System"""

    def __init__(self):
        self.companies: Dict[str, Company] = {}
        self.customers: Dict[str, Customer] = {}
        self.policies: Dict[str, InsurancePolicy] = {}
        self.claims: Dict[str, Claim] = {}
        self.bills: Dict[str, Bill] = {}
        self.underwriting: Dict[str, Underwriting] = {}
        self.reinsurance: Dict[str, Reinsurance] = {}
        self.documents: Dict[str, Document] = {}
        # Actuarial and Risk Management
        self.health_tables: Dict[str, HealthTable] = {}
        self.pricing_models: Dict[str, PricingModel] = {}
        self.risk_assessments: Dict[str, RiskAssessment] = {}
        self.hedges: Dict[str, ReinsuranceHedge] = {}

    # Company Management
    def register_company(self, company: Company) -> bool:
        """Register a new insurance company"""
        if company.company_id not in self.companies:
            self.companies[company.company_id] = company
            return True
        return False

    def get_company(self, company_id: str) -> Optional[Company]:
        """Retrieve company by ID"""
        return self.companies.get(company_id)

    # Customer Management
    def register_customer(self, customer: Customer) -> bool:
        """Register a new customer"""
        if customer.customer_id not in self.customers:
            self.customers[customer.customer_id] = customer
            return True
        return False

    def get_customer(self, customer_id: str) -> Optional[Customer]:
        """Retrieve customer by ID"""
        return self.customers.get(customer_id)

    def get_customer_policies(self, customer_id: str) -> List[InsurancePolicy]:
        """Get all policies for a customer"""
        return [p for p in self.policies.values() if p.customer_id == customer_id]

    # Policy Management
    def create_policy(self, customer_id: str, policy_type: PolicyType,
                     premium: float, coverage: float, deductible: float) -> InsurancePolicy:
        """Create a new policy"""
        policy = PolicyManagement.create_policy(
            customer_id, policy_type, datetime.now(), premium, coverage, deductible
        )
        self.policies[policy.policy_id] = policy
        return policy

    def get_policy(self, policy_id: str) -> Optional[InsurancePolicy]:
        """Retrieve policy by ID"""
        return self.policies.get(policy_id)

    # Claims Management
    def file_claim(self, policy_id: str, customer_id: str, amount: float,
                  description: str) -> Claim:
        """File a new claim"""
        claim = ClaimsManagement.create_claim(policy_id, customer_id, amount, description)
        self.claims[claim.claim_id] = claim
        return claim

    def get_claim(self, claim_id: str) -> Optional[Claim]:
        """Retrieve claim by ID"""
        return self.claims.get(claim_id)

    def get_customer_claims(self, customer_id: str) -> List[Claim]:
        """Get all claims for a customer"""
        return [c for c in self.claims.values() if c.customer_id == customer_id]

    # Billing Management
    def create_bill(self, policy_id: str, customer_id: str, amount: float) -> Bill:
        """Create a new bill"""
        bill = BillingManagement.create_bill(policy_id, customer_id, amount)
        self.bills[bill.bill_id] = bill
        return bill

    def get_bill(self, bill_id: str) -> Optional[Bill]:
        """Retrieve bill by ID"""
        return self.bills.get(bill_id)

    def get_customer_billing(self, customer_id: str) -> Dict:
        """Get billing summary for a customer"""
        customer_bills = [b for b in self.bills.values() if b.customer_id == customer_id]
        return BillingManagement.get_billing_statement(customer_bills)

    # Underwriting Management
    def initiate_underwriting(self, policy_id: str, customer_id: str) -> Underwriting:
        """Start underwriting process"""
        uw = UnderwritingEngine.initiate_underwriting(policy_id, customer_id)
        self.underwriting[uw.underwriting_id] = uw
        return uw

    def get_underwriting(self, uw_id: str) -> Optional[Underwriting]:
        """Retrieve underwriting record"""
        return self.underwriting.get(uw_id)

    # Reinsurance Management
    def create_reinsurance(self, reinsurance: Reinsurance) -> bool:
        """Create reinsurance arrangement"""
        if reinsurance.reinsurance_id not in self.reinsurance:
            self.reinsurance[reinsurance.reinsurance_id] = reinsurance
            return True
        return False
    def get_reinsurance(self, reinsurance_id: str) -> Optional[Reinsurance]:
        """Retrieve reinsurance arrangement"""
        return self.reinsurance.get(reinsurance_id)

    # File Management - Available across all divisions
    def upload_document(self, file_name: str, file_type: FileType, division: DocumentDivision,
                       related_entity_id: str, related_entity_type: str,
                       file_size: int, file_path: str, uploaded_by: str,
                       description: str = "") -> Document:
        """Upload a document"""
        document = FileManagement.upload_document(
            file_name, file_type, division, related_entity_id, related_entity_type,
            file_size, file_path, uploaded_by, description
        )
        self.documents[document.document_id] = document
        return document

    def get_document(self, document_id: str) -> Optional[Document]:
        """Retrieve document by ID"""
        return self.documents.get(document_id)

    def verify_document(self, document_id: str, verified_by: str) -> bool:
        """Verify a document"""
        document = self.documents.get(document_id)
        if document:
            FileManagement.verify_document(document, verified_by)
            return True
        return False

    def reject_document(self, document_id: str, verified_by: str, reason: str) -> bool:
        """Reject a document"""
        document = self.documents.get(document_id)
        if document:
            FileManagement.reject_document(document, verified_by, reason)
            return True
        return False

    def archive_document(self, document_id: str) -> bool:
        """Archive a document"""
        document = self.documents.get(document_id)
        if document:
            FileManagement.archive_document(document)
            return True
        return False

    def download_document(self, document_id: str) -> Optional[Document]:
        """Download/retrieve a document"""
        return self.get_document(document_id)

    def get_entity_documents(self, entity_id: str) -> List[Document]:
        """Get all documents for a specific entity (Policy, Claim, Customer, Bill)"""
        return FileManagement.get_documents_by_entity(list(self.documents.values()), entity_id)

    def get_division_documents(self, division: DocumentDivision) -> List[Document]:
        """Get all documents for a specific division"""
        return FileManagement.get_documents_by_division(list(self.documents.values()), division)

    def get_documents_by_type(self, file_type: FileType) -> List[Document]:
        """Get documents of a specific type"""
        return FileManagement.get_documents_by_type(list(self.documents.values()), file_type)

    def get_pending_documents(self) -> List[Document]:
        """Get all documents pending verification"""
        return FileManagement.get_pending_verification(list(self.documents.values()))

    def get_verified_documents(self) -> List[Document]:
        """Get all verified documents"""
        return FileManagement.get_verified_documents(list(self.documents.values()))

    def get_rejected_documents(self) -> List[Document]:
        """Get all rejected documents"""
        return FileManagement.get_rejected_documents(list(self.documents.values()))

    def get_document_storage_stats(self) -> Dict:
        """Get document storage statistics"""
        return FileManagement.calculate_total_storage(list(self.documents.values()))

    # Actuarial & Risk Management
    def add_health_table(self, health_table: HealthTable) -> bool:
        """Register a new health/mortality table"""
        if health_table.table_id not in self.health_tables:
            self.health_tables[health_table.table_id] = health_table
            return True
        return False

    def get_health_table(self, table_id: str) -> Optional[HealthTable]:
        """Retrieve health table by ID"""
        return self.health_tables.get(table_id)

    def add_pricing_model(self, model: PricingModel) -> bool:
        """Register a new pricing model"""
        if model.model_id not in self.pricing_models:
            self.pricing_models[model.model_id] = model
            return True
        return False

    def get_pricing_model(self, model_id: str) -> Optional[PricingModel]:
        """Retrieve pricing model by ID"""
        return self.pricing_models.get(model_id)

    def add_risk_assessment(self, assessment: RiskAssessment) -> bool:
        """Register a risk assessment"""
        if assessment.assessment_id not in self.risk_assessments:
            self.risk_assessments[assessment.assessment_id] = assessment
            return True
        return False

    def get_risk_assessment(self, assessment_id: str) -> Optional[RiskAssessment]:
        """Retrieve risk assessment by ID"""
        return self.risk_assessments.get(assessment_id)

    def get_customer_risk_assessments(self, customer_id: str) -> List[RiskAssessment]:
        """Get all risk assessments for a customer"""
        return [a for a in self.risk_assessments.values() if a.customer_id == customer_id]

    def add_hedging_arrangement(self, hedge: ReinsuranceHedge) -> bool:
        """Register a reinsurance hedging arrangement"""
        if hedge.hedge_id not in self.hedges:
            self.hedges[hedge.hedge_id] = hedge
            return True
        return False

    def get_hedging_arrangement(self, hedge_id: str) -> Optional[ReinsuranceHedge]:
        """Retrieve hedging arrangement by ID"""
        return self.hedges.get(hedge_id)

    def get_reinsurance_hedges(self, reinsurance_id: str) -> List[ReinsuranceHedge]:
        """Get all hedges for a reinsurance arrangement"""
        return [h for h in self.hedges.values() if h.reinsurance_id == reinsurance_id]

    def calculate_portfolio_risk_metrics(self) -> Dict[str, Any]:
        """Calculate overall portfolio risk metrics"""
        if not self.policies:
            return {}
        
        total_premium = sum(p.premium_amount for p in self.policies.values())
        total_coverage = sum(p.coverage_amount for p in self.policies.values())
        risk_assessments = list(self.risk_assessments.values())
        
        avg_risk_score = (sum(a.numerical_risk_score for a in risk_assessments) / 
                         len(risk_assessments)) if risk_assessments else 0.0
        
        risk_distribution = {
            "very_low": len([a for a in risk_assessments if a.risk_category == RiskCategory.VERY_LOW]),
            "low": len([a for a in risk_assessments if a.risk_category == RiskCategory.LOW]),
            "medium": len([a for a in risk_assessments if a.risk_category == RiskCategory.MEDIUM]),
            "high": len([a for a in risk_assessments if a.risk_category == RiskCategory.HIGH]),
            "very_high": len([a for a in risk_assessments if a.risk_category == RiskCategory.VERY_HIGH]),
            "extreme": len([a for a in risk_assessments if a.risk_category == RiskCategory.EXTREME])
        }
        
        total_hedging_cost = sum(h.reinsurance_cost for h in self.hedges.values())
        total_ceded = sum(h.ceded_amount for h in self.hedges.values())
        hedging_efficiency = float(total_ceded / total_premium) if total_premium > 0 else 0.0
        
        return {
            "total_policies": len(self.policies),
            "total_premium": total_premium,
            "total_coverage": total_coverage,
            "average_risk_score": round(avg_risk_score, 2),
            "risk_distribution": risk_distribution,
            "total_reinsurance_cost": total_hedging_cost,
            "total_ceded_premium": total_ceded,
            "hedging_efficiency": round(hedging_efficiency * 100, 2),
            "net_premium_after_hedging": total_premium - total_hedging_cost
        }

    # Reporting
    def get_system_summary(self) -> Dict:
        """Get overall system summary"""
        doc_stats = self.get_document_storage_stats()
        portfolio_metrics = self.calculate_portfolio_risk_metrics()
        
        return {
            "total_companies": len(self.companies),
            "total_customers": len(self.customers),
            "total_policies": len(self.policies),
            "active_policies": sum(1 for p in self.policies.values() if p.is_active()),
            "total_claims": len(self.claims),
            "pending_claims": sum(1 for c in self.claims.values() if c.status == ClaimStatus.PENDING),
            "total_bills": len(self.bills),
            "outstanding_bills": sum(1 for b in self.bills.values() if b.status == BillStatus.OUTSTANDING),
            "total_revenue": sum(p.premium_amount for p in self.policies.values()),
            "total_claims_approved": sum(c.approved_amount for c in self.claims.values() if c.status == ClaimStatus.PAID),
            "documents": {
                "total_documents": doc_stats["total_files"],
                "total_storage_mb": doc_stats["total_mb"],
                "total_storage_gb": doc_stats["total_gb"],
                "verified": doc_stats["verified"],
                "pending_verification": doc_stats["pending"],
                "rejected": doc_stats["rejected"]
            },
            "actuarial": {
                "health_tables": len(self.health_tables),
                "pricing_models": len(self.pricing_models),
                "risk_assessments": len(self.risk_assessments),
                "hedging_arrangements": len(self.hedges),
                "portfolio_metrics": portfolio_metrics
            }
        }


if __name__ == "__main__":
    print("PHINS Insurance Management System - Python Implementation")
    print("=" * 60)
