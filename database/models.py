"""
SQLAlchemy ORM Models for PHINS Insurance Platform

These models define the database schema for all core entities in the system.
Supports both SQLite (development) and PostgreSQL (production).
"""

from sqlalchemy import Column, String, Integer, Float, DateTime, Boolean, Text, ForeignKey, Enum as SQLEnum
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from datetime import datetime
import enum

Base = declarative_base()


class PolicyStatus(str, enum.Enum):
    """Policy status enumeration"""
    ACTIVE = "active"
    INACTIVE = "inactive"
    CANCELLED = "cancelled"
    LAPSED = "lapsed"
    SUSPENDED = "suspended"
    PENDING_UNDERWRITING = "pending_underwriting"


class UnderwritingStatus(str, enum.Enum):
    """Underwriting status enumeration"""
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    REFERRED = "referred"
    APPROVED_CONDITIONAL = "approved_conditional"


class ClaimStatus(str, enum.Enum):
    """Claim status enumeration"""
    PENDING = "pending"
    UNDER_REVIEW = "under_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    PAID = "paid"
    CLOSED = "closed"


class BillStatus(str, enum.Enum):
    """Bill/Billing status enumeration"""
    OUTSTANDING = "outstanding"
    PARTIAL = "partial"
    PAID = "paid"
    OVERDUE = "overdue"
    CANCELLED = "cancelled"


class Customer(Base):
    """
    Customer master table (unified entity for policyholders)
    
    ARCHITECTURE NOTE:
    - Customers are policyholders who interact via the client portal
    - Users (separate table) are internal staff (admin, underwriter, claims, accountant)
    - Customer includes auth fields for direct portal authentication
    - This eliminates the need for dual Customer+User records for policyholders
    """
    __tablename__ = 'customers'
    
    id = Column(String(50), primary_key=True)
    name = Column(String(200), nullable=False)
    first_name = Column(String(100))
    last_name = Column(String(100))
    email = Column(String(254), unique=True, nullable=False, index=True)
    phone = Column(String(20))
    dob = Column(String(20))  # Date of birth as string (YYYY-MM-DD)
    age = Column(Integer)
    gender = Column(String(20))
    address = Column(Text)
    city = Column(String(100))
    state = Column(String(100))
    zip = Column(String(20))
    occupation = Column(String(100))
    
    # Authentication fields (unified - no separate User record needed for customers)
    password_hash = Column(String(255), nullable=True)  # Nullable for legacy/migration
    password_salt = Column(String(255), nullable=True)
    portal_active = Column(Boolean, default=True)  # Can login to customer portal
    last_login = Column(DateTime, nullable=True)
    
    # Timestamps
    created_date = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_date = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    policies = relationship("Policy", back_populates="customer", cascade="all, delete-orphan")
    claims = relationship("Claim", back_populates="customer", cascade="all, delete-orphan")
    
    def to_dict(self, include_auth: bool = False):
        """Convert model to dictionary"""
        data = {
            'id': self.id,
            'name': self.name,
            'first_name': self.first_name,
            'last_name': self.last_name,
            'email': self.email,
            'phone': self.phone,
            'dob': self.dob,
            'age': self.age,
            'gender': self.gender,
            'address': self.address,
            'city': self.city,
            'state': self.state,
            'zip': self.zip,
            'occupation': self.occupation,
            'portal_active': self.portal_active,
            'last_login': self.last_login.isoformat() if self.last_login else None,
            'created_date': self.created_date.isoformat() if self.created_date else None,
            'updated_date': self.updated_date.isoformat() if self.updated_date else None
        }
        # Only include auth fields if explicitly requested (internal use)
        if include_auth:
            data['password_hash'] = self.password_hash
            data['password_salt'] = self.password_salt
        return data
    
    def has_portal_access(self) -> bool:
        """Check if customer has portal login configured"""
        return bool(self.password_hash and self.password_salt and self.portal_active)


class Policy(Base):
    """Insurance policy master table"""
    __tablename__ = 'policies'
    
    id = Column(String(50), primary_key=True)
    customer_id = Column(String(50), ForeignKey('customers.id', ondelete='CASCADE'), nullable=False, index=True)
    type = Column(String(50), nullable=False)  # life, health, auto, property, business
    coverage_amount = Column(Float, nullable=False)
    annual_premium = Column(Float, nullable=False)
    monthly_premium = Column(Float)
    quarterly_premium = Column(Float)
    status = Column(String(50), default='pending_underwriting')
    underwriting_id = Column(String(50), index=True)
    risk_score = Column(String(20))  # low, medium, high, very_high
    start_date = Column(DateTime)
    end_date = Column(DateTime)
    approval_date = Column(DateTime)
    created_date = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_date = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Legacy field mappings for compatibility
    uw_status = Column(String(50))  # Maps to underwriting status
    
    # JSON fields stored as text
    billing = Column(Text)  # JSON string for billing configuration
    health_wallet = Column(Text)  # JSON string for health wallet config
    
    # Relationships
    customer = relationship("Customer", back_populates="policies")
    claims = relationship("Claim", back_populates="policy", cascade="all, delete-orphan")
    
    def to_dict(self):
        """Convert model to dictionary"""
        import json as json_module
        
        def safe_json_loads(val):
            if val is None:
                return {}
            if isinstance(val, dict):
                return val
            try:
                return json_module.loads(val)
            except:
                return {}
        
        return {
            'id': self.id,
            'customer_id': self.customer_id,
            'type': self.type,
            'coverage_amount': self.coverage_amount,
            'annual_premium': self.annual_premium,
            'monthly_premium': self.monthly_premium,
            'quarterly_premium': self.quarterly_premium,
            'status': self.status,
            'underwriting_id': self.underwriting_id,
            'risk_score': self.risk_score,
            'start_date': self.start_date.isoformat() if self.start_date else None,
            'end_date': self.end_date.isoformat() if self.end_date else None,
            'approval_date': self.approval_date.isoformat() if self.approval_date else None,
            'created_date': self.created_date.isoformat() if self.created_date else None,
            'updated_date': self.updated_date.isoformat() if self.updated_date else None,
            'uw_status': self.uw_status,
            'billing': safe_json_loads(self.billing),
            'health_wallet': safe_json_loads(self.health_wallet)
        }


class Claim(Base):
    """Claims master table"""
    __tablename__ = 'claims'
    
    id = Column(String(50), primary_key=True)
    policy_id = Column(String(50), ForeignKey('policies.id', ondelete='CASCADE'), nullable=False, index=True)
    customer_id = Column(String(50), ForeignKey('customers.id', ondelete='CASCADE'), nullable=False, index=True)
    type = Column(String(50))
    description = Column(Text)
    claimed_amount = Column(Float, nullable=False)
    approved_amount = Column(Float)
    status = Column(String(50), default='pending')
    filed_date = Column(DateTime, default=datetime.utcnow, nullable=False)
    approval_date = Column(DateTime)
    payment_date = Column(DateTime)
    rejection_reason = Column(Text)
    created_date = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_date = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Extended claim fields for full claim filing flow
    incident_date = Column(String(50))  # Date of incident
    provider = Column(String(200))  # Healthcare/Service provider
    payment_destination = Column(String(50), default='health_wallet')  # Where to send payment
    bank_details = Column(Text)  # JSON string for bank details if bank_transfer
    files_metadata = Column(Text)  # JSON string for file attachments metadata
    files_count = Column(Integer, default=0)  # Number of attached files
    nft_token_id = Column(String(100))  # NFT ledger token ID
    ledger_tx_id = Column(String(100))  # Transaction ledger ID
    approved_by = Column(String(100))  # Who approved the claim
    approval_notes = Column(Text)  # Notes from approver
    rejected_by = Column(String(100))  # Who rejected the claim
    processed_by = Column(String(100))  # Who processed the payment
    payment_method = Column(String(50))  # How payment was made
    payment_reference = Column(String(100))  # Payment reference number
    paid_amount = Column(Float)  # Actual amount paid
    
    # Relationships
    policy = relationship("Policy", back_populates="claims")
    customer = relationship("Customer", back_populates="claims")
    
    def to_dict(self):
        """Convert model to dictionary"""
        import json as _json
        return {
            'id': self.id,
            'policy_id': self.policy_id,
            'customer_id': self.customer_id,
            'type': self.type,
            'description': self.description,
            'claimed_amount': self.claimed_amount,
            'approved_amount': self.approved_amount,
            'status': self.status,
            'filed_date': self.filed_date.isoformat() if self.filed_date else None,
            'approval_date': self.approval_date.isoformat() if self.approval_date else None,
            'payment_date': self.payment_date.isoformat() if self.payment_date else None,
            'rejection_reason': self.rejection_reason,
            'created_date': self.created_date.isoformat() if self.created_date else None,
            'updated_date': self.updated_date.isoformat() if self.updated_date else None,
            'incident_date': self.incident_date,
            'provider': self.provider,
            'payment_destination': self.payment_destination,
            'bank_details': _json.loads(self.bank_details) if self.bank_details else None,
            'files': _json.loads(self.files_metadata) if self.files_metadata else [],
            'files_count': self.files_count or 0,
            'nft_token_id': self.nft_token_id,
            'ledger_tx_id': self.ledger_tx_id,
            'approved_by': self.approved_by,
            'approval_notes': self.approval_notes,
            'rejected_by': self.rejected_by,
            'processed_by': self.processed_by,
            'payment_method': self.payment_method,
            'payment_reference': self.payment_reference,
            'paid_amount': self.paid_amount
        }


class UnderwritingApplication(Base):
    """Underwriting applications table"""
    __tablename__ = 'underwriting_applications'
    
    id = Column(String(50), primary_key=True)
    policy_id = Column(String(50), index=True)
    customer_id = Column(String(50), index=True)
    
    # Customer info (denormalized for dashboard display)
    customer_name = Column(String(200))
    customer_email = Column(String(254))
    
    # Policy details
    policy_type = Column(String(50))
    coverage_amount = Column(Float)
    age = Column(Integer)
    risk_score = Column(String(20))  # low, medium, high, very_high (alias for risk_assessment)
    
    status = Column(String(50), default='pending')
    risk_assessment = Column(String(20))  # low, medium, high, very_high
    medical_exam_required = Column(Boolean, default=False)
    additional_documents_required = Column(Boolean, default=False)
    notes = Column(Text)
    
    # Demographic data
    gender = Column(String(20))
    occupation = Column(String(100))
    
    # Medical assessment data - for risk reports
    disability_percentage = Column(Integer)  # 0-100
    disability_type = Column(String(200))
    disability_status = Column(String(50))  # stable, progressive, etc.
    disability_treatment = Column(Text)
    disability_notes = Column(Text)
    
    # BMI data
    bmi = Column(Float)
    height_cm = Column(Float)
    weight_kg = Column(Float)
    bmi_notes = Column(Text)
    
    # Lifestyle data
    smoking_status = Column(String(20))  # never, former, current
    alcohol_use = Column(String(20))  # none, moderate, heavy
    exercise_frequency = Column(String(20))  # never, weekly, daily
    
    # Identity verification
    identity_verified = Column(Boolean, default=False)
    premium_adjustment = Column(Integer, default=0)  # Percentage loading
    
    # JSON fields stored as text
    questionnaire_responses = Column(Text)  # JSON string
    payment_setup = Column(Text)  # JSON string
    health_wallet = Column(Text)  # JSON string
    medical_conditions = Column(Text)  # JSON string - array of conditions
    documents = Column(Text)  # JSON string - array of verified documents
    data_sources = Column(Text)  # JSON string - tracking data origins
    
    submitted_date = Column(DateTime, default=datetime.utcnow, nullable=False)
    decision_date = Column(DateTime)
    decided_by = Column(String(100))  # Username of underwriter
    created_date = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_date = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def to_dict(self):
        """Convert model to dictionary"""
        import json as json_module
        
        def safe_json_loads(val):
            if val is None:
                return {}
            if isinstance(val, dict):
                return val
            if isinstance(val, list):
                return val
            try:
                return json_module.loads(val)
            except:
                return {}
        
        def safe_json_loads_list(val):
            if val is None:
                return []
            if isinstance(val, list):
                return val
            try:
                return json_module.loads(val)
            except:
                return []
        
        return {
            'id': self.id,
            'policy_id': self.policy_id,
            'customer_id': self.customer_id,
            'customer_name': self.customer_name,
            'customer_email': self.customer_email,
            'policy_type': self.policy_type,
            'coverage_amount': self.coverage_amount,
            'age': self.age,
            'risk_score': self.risk_score,
            'status': self.status,
            'risk_assessment': self.risk_assessment,
            'medical_exam_required': self.medical_exam_required,
            'additional_documents_required': self.additional_documents_required,
            'notes': self.notes,
            # Demographic data
            'gender': self.gender,
            'occupation': self.occupation,
            # Medical assessment data
            'disability_percentage': self.disability_percentage,
            'disability_type': self.disability_type,
            'disability_status': self.disability_status,
            'disability_treatment': self.disability_treatment,
            'disability_notes': self.disability_notes,
            'bmi': self.bmi,
            'height_cm': self.height_cm,
            'weight_kg': self.weight_kg,
            'bmi_notes': self.bmi_notes,
            # Lifestyle data
            'smoking_status': self.smoking_status,
            'alcohol_use': self.alcohol_use,
            'exercise_frequency': self.exercise_frequency,
            # Identity verification
            'identity_verified': self.identity_verified,
            'premium_adjustment': self.premium_adjustment,
            # JSON fields
            'questionnaire_responses': safe_json_loads(self.questionnaire_responses),
            'payment_setup': safe_json_loads(self.payment_setup),
            'health_wallet': safe_json_loads(self.health_wallet),
            'medical_conditions': safe_json_loads_list(self.medical_conditions),
            'documents': safe_json_loads_list(self.documents),
            'data_sources': safe_json_loads(self.data_sources),
            # Timestamps
            'submitted_date': self.submitted_date.isoformat() if self.submitted_date else None,
            'decision_date': self.decision_date.isoformat() if self.decision_date else None,
            'decided_by': self.decided_by,
            'created_date': self.created_date.isoformat() if self.created_date else None,
            'updated_date': self.updated_date.isoformat() if self.updated_date else None
        }


class Bill(Base):
    """Billing/Invoices table"""
    __tablename__ = 'bills'
    
    id = Column(String(50), primary_key=True)
    policy_id = Column(String(50), index=True)
    customer_id = Column(String(50), index=True)
    amount = Column(Float, nullable=False)
    amount_paid = Column(Float, default=0.0)
    status = Column(String(50), default='outstanding')
    due_date = Column(DateTime)
    paid_date = Column(DateTime)
    payment_method = Column(String(50))  # credit_card, debit_card, bank_transfer, check, etc.
    transaction_id = Column(String(100))
    late_fee = Column(Float, default=0.0)
    created_date = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_date = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def to_dict(self):
        """Convert model to dictionary"""
        return {
            'id': self.id,
            'policy_id': self.policy_id,
            'customer_id': self.customer_id,
            'amount': self.amount,
            'amount_paid': self.amount_paid,
            'status': self.status,
            'due_date': self.due_date.isoformat() if self.due_date else None,
            'paid_date': self.paid_date.isoformat() if self.paid_date else None,
            'payment_method': self.payment_method,
            'transaction_id': self.transaction_id,
            'late_fee': self.late_fee,
            'created_date': self.created_date.isoformat() if self.created_date else None,
            'updated_date': self.updated_date.isoformat() if self.updated_date else None
        }


class User(Base):
    """
    User accounts table (INTERNAL STAFF ONLY)
    
    ARCHITECTURE NOTE:
    - Users are INTERNAL STAFF: admin, underwriter, claims_adjuster, accountant
    - Customers (policyholders) use the Customer table with embedded auth
    - This separation ensures clean role boundaries:
      * Staff → User table → Admin portal
      * Customers → Customer table → Client portal
    
    VALID ROLES:
    - admin: Full system access
    - underwriter: Review/approve applications
    - claims_adjuster: Process claims
    - accountant: Billing and payments
    """
    __tablename__ = 'users'
    
    username = Column(String(100), primary_key=True)
    password_hash = Column(String(255), nullable=False)
    password_salt = Column(String(255), nullable=False)
    role = Column(String(50), nullable=False)  # admin, underwriter, claims_adjuster, accountant, customer
    name = Column(String(200))
    email = Column(String(254))
    active = Column(Boolean, default=True)
    created_date = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_login = Column(DateTime)
    
    # Customer linkage (for role='customer' users)
    customer_id = Column(String(50), nullable=True, index=True)
    
    # Staff-specific fields
    department = Column(String(100), nullable=True)
    employee_id = Column(String(50), nullable=True)
    
    def to_dict(self):
        """Convert model to dictionary (without sensitive fields)"""
        return {
            'username': self.username,
            'role': self.role,
            'name': self.name,
            'email': self.email,
            'active': self.active,
            'department': self.department,
            'employee_id': self.employee_id,
            'created_date': self.created_date.isoformat() if self.created_date else None,
            'last_login': self.last_login.isoformat() if self.last_login else None
        }
    
    def is_staff(self) -> bool:
        """Check if user is internal staff"""
        return self.role in ('admin', 'underwriter', 'claims_adjuster', 'accountant')


class Session(Base):
    """User sessions table"""
    __tablename__ = 'sessions'
    
    token = Column(String(100), primary_key=True)
    username = Column(String(100), index=True)
    customer_id = Column(String(50), index=True)
    role = Column(String(50), index=True)  # admin, underwriter, claims, accountant, customer
    ip_address = Column(String(45))  # Support IPv6
    expires = Column(DateTime, nullable=False, index=True)
    created_date = Column(DateTime, default=datetime.utcnow, nullable=False)
    
    def to_dict(self):
        """Convert model to dictionary"""
        return {
            'token': self.token,
            'username': self.username,
            'customer_id': self.customer_id,
            'role': self.role,
            'ip_address': self.ip_address,
            'expires': self.expires.isoformat() if self.expires else None,
            'created_date': self.created_date.isoformat() if self.created_date else None
        }


class AuditLog(Base):
    """Audit log table for tracking all actions"""
    __tablename__ = 'audit_logs'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    username = Column(String(100), index=True)
    customer_id = Column(String(50), index=True)
    action = Column(String(100), nullable=False)
    entity_type = Column(String(50))  # policy, claim, customer, etc.
    entity_id = Column(String(50))
    details = Column(Text)  # JSON string with additional details
    ip_address = Column(String(45))
    success = Column(Boolean, default=True)
    
    def to_dict(self):
        """Convert model to dictionary"""
        return {
            'id': self.id,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
            'username': self.username,
            'customer_id': self.customer_id,
            'action': self.action,
            'entity_type': self.entity_type,
            'entity_id': self.entity_id,
            'details': self.details,
            'ip_address': self.ip_address,
            'success': self.success
        }


# ============================================================================
# Admin data (actuarial tables) + token registry (crypto/asset enablement)
# ============================================================================


class DataClassification(str, enum.Enum):
    """Data sensitivity classification (insurance-grade defaults)."""

    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    RESTRICTED = "restricted"


class ActuarialTable(Base):
    """
    Actuarial table store (mortality/morbidity/pricing/etc).

    The `payload` field stores an encrypted JSON blob (see `security.vault`).
    """

    __tablename__ = "actuarial_tables"

    id = Column(String(50), primary_key=True)
    name = Column(String(200), nullable=False, index=True)
    table_type = Column(String(100), nullable=False, index=True)  # mortality, morbidity, pricing, lapse, etc
    version = Column(String(50), nullable=False, index=True)
    effective_date = Column(DateTime, nullable=True, index=True)
    payload = Column(Text, nullable=False)  # VaultBlob JSON
    classification = Column(String(50), default=DataClassification.RESTRICTED.value, nullable=False, index=True)
    created_by = Column(String(100), index=True)
    created_date = Column(DateTime, default=datetime.utcnow, nullable=False)

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "table_type": self.table_type,
            "version": self.version,
            "effective_date": self.effective_date.isoformat() if self.effective_date else None,
            "classification": self.classification,
            "created_by": self.created_by,
            "created_date": self.created_date.isoformat() if self.created_date else None,
        }


class TokenAssetType(str, enum.Enum):
    """Supported asset types in the registry."""

    CURRENCY = "currency"
    STABLECOIN = "stablecoin"
    NFT = "nft"
    INDEX = "index"


class TokenRegistry(Base):
    """
    Registry of supported tokens/currencies/NFT identifiers used by billing/investments.

    This is NOT an on-chain indexer; it's a governance/allow-list for what the platform will accept.
    """

    __tablename__ = "token_registry"

    id = Column(String(50), primary_key=True)
    symbol = Column(String(50), nullable=False, index=True)  # BTC, ETH, USDC, etc
    name = Column(String(200), nullable=False)
    asset_type = Column(String(50), default=TokenAssetType.CURRENCY.value, nullable=False, index=True)
    chain = Column(String(50), nullable=True)  # ethereum, solana, polygon, etc
    contract_address = Column(String(200), nullable=True)  # for tokens/NFTs (optional)
    decimals = Column(Integer, nullable=True)
    enabled = Column(Boolean, default=True, nullable=False, index=True)
    token_metadata = Column(Text, nullable=True)  # JSON string (renamed from 'metadata' - reserved in SQLAlchemy)
    classification = Column(String(50), default=DataClassification.INTERNAL.value, nullable=False, index=True)
    created_by = Column(String(100), index=True)
    created_date = Column(DateTime, default=datetime.utcnow, nullable=False)

    def to_dict(self):
        return {
            "id": self.id,
            "symbol": self.symbol,
            "name": self.name,
            "asset_type": self.asset_type,
            "chain": self.chain,
            "contract_address": self.contract_address,
            "decimals": self.decimals,
            "enabled": self.enabled,
            "token_metadata": self.token_metadata,
            "classification": self.classification,
            "created_by": self.created_by,
            "created_date": self.created_date.isoformat() if self.created_date else None,
        }


# ============================================================================
# Underwriting Bot Models (NEW - Additive Only, Preserves Existing Data)
# ============================================================================


class MetadataType(str, enum.Enum):
    """Types of metadata for underwriting assessment"""
    PHOTO = "photo"
    MEDICAL_REPORT = "medical_report"
    PASSPORT = "passport"
    DRIVING_LICENCE = "driving_licence"
    NATIONAL_INSURANCE = "national_insurance"
    DISABILITY_CERTIFICATE = "disability_certificate"
    AUDIO = "audio"
    VIDEO = "video"
    OTHER_DOCUMENT = "other_document"


class ProcessingStatusEnum(str, enum.Enum):
    """Processing status for metadata"""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    REQUIRES_REVIEW = "requires_review"


class ValidationStatusEnum(str, enum.Enum):
    """Validation status for metadata"""
    PENDING = "pending"
    VALID = "valid"
    INVALID = "invalid"
    EXPIRED = "expired"
    SUSPICIOUS = "suspicious"


class RiskLevelEnum(str, enum.Enum):
    """Risk level categories"""
    VERY_LOW = "very_low"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    VERY_HIGH = "very_high"


class DecisionRecommendationEnum(str, enum.Enum):
    """AI decision recommendations"""
    APPROVE = "approve"
    APPROVE_CONDITIONAL = "approve_conditional"
    REFER_MANUAL = "refer_manual"
    DECLINE = "decline"
    PENDING_INFO = "pending_info"


class AssessmentStatusEnum(str, enum.Enum):
    """Assessment lifecycle status"""
    INITIATED = "initiated"
    COLLECTING_METADATA = "collecting_metadata"
    VALIDATING_METADATA = "validating_metadata"
    PROCESSING = "processing"
    RISK_ASSESSING = "risk_assessing"
    DECISION_READY = "decision_ready"
    APPROVED = "approved"
    REJECTED = "rejected"
    REFERRED = "referred"
    CONDITIONAL_APPROVAL = "conditional_approval"
    COMPLETED = "completed"
    VALIDATION_FAILED = "validation_failed"


class UnderwritingMetadataModel(Base):
    """
    Stores metadata uploaded for underwriting assessment.
    
    This is a NEW table - does not modify any existing customer data.
    Metadata includes photos, medical reports, official documents, audio, video.
    """
    __tablename__ = 'underwriting_metadata'
    
    id = Column(String(50), primary_key=True)
    underwriting_id = Column(String(50), index=True, nullable=False)
    customer_id = Column(String(50), index=True, nullable=False)
    assessment_id = Column(String(50), index=True, nullable=True)
    
    # File information
    metadata_type = Column(String(50), nullable=False, index=True)
    file_name = Column(String(255), nullable=False)
    file_path = Column(String(500), nullable=True)
    file_hash = Column(String(64), nullable=True)  # SHA-256 hash
    file_size_bytes = Column(Integer, nullable=True)
    mime_type = Column(String(100), nullable=True)
    
    # Processing state
    upload_date = Column(DateTime, default=datetime.utcnow, nullable=False)
    processing_status = Column(String(50), default='pending', index=True)
    processing_result = Column(Text, nullable=True)  # JSON string
    
    # Extracted data
    extracted_data = Column(Text, nullable=True)  # JSON string
    confidence_score = Column(Float, nullable=True)
    
    # Validation
    validation_status = Column(String(50), default='pending', index=True)
    validation_notes = Column(Text, nullable=True)
    
    # Timestamps
    created_date = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_date = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def to_dict(self):
        """Convert model to dictionary"""
        import json as _json
        
        def safe_json_loads(val):
            if val is None:
                return {}
            if isinstance(val, dict):
                return val
            try:
                return _json.loads(val)
            except:
                return {}
        
        return {
            'id': self.id,
            'underwriting_id': self.underwriting_id,
            'customer_id': self.customer_id,
            'assessment_id': self.assessment_id,
            'metadata_type': self.metadata_type,
            'file_name': self.file_name,
            'file_path': self.file_path,
            'file_hash': self.file_hash,
            'file_size_bytes': self.file_size_bytes,
            'mime_type': self.mime_type,
            'upload_date': self.upload_date.isoformat() if self.upload_date else None,
            'processing_status': self.processing_status,
            'processing_result': safe_json_loads(self.processing_result),
            'extracted_data': safe_json_loads(self.extracted_data),
            'confidence_score': self.confidence_score,
            'validation_status': self.validation_status,
            'validation_notes': self.validation_notes,
            'created_date': self.created_date.isoformat() if self.created_date else None,
            'updated_date': self.updated_date.isoformat() if self.updated_date else None
        }


class RiskAssessmentReportModel(Base):
    """
    Stores comprehensive risk assessment reports generated by the underwriting bot.
    
    This is a NEW table - does not modify any existing customer data.
    """
    __tablename__ = 'risk_assessment_reports'
    
    id = Column(String(50), primary_key=True)
    underwriting_id = Column(String(50), index=True, nullable=False)
    customer_id = Column(String(50), index=True, nullable=False)
    assessment_id = Column(String(50), index=True, nullable=True)
    
    # Assessment date and scores
    assessment_date = Column(DateTime, default=datetime.utcnow, nullable=False)
    overall_risk_score = Column(Float, nullable=False)  # 0.0 to 1.0
    risk_level = Column(String(20), nullable=False, index=True)  # very_low, low, medium, high, very_high
    
    # Component scores
    identity_verified = Column(Boolean, default=False)
    identity_score = Column(Float, nullable=True)
    document_score = Column(Float, nullable=True)
    medical_score = Column(Float, nullable=True)
    behavioral_score = Column(Float, nullable=True)
    fraud_score = Column(Float, nullable=True)
    
    # Decision
    recommendation = Column(String(50), nullable=False, index=True)  # approve, approve_conditional, refer_manual, decline
    confidence_level = Column(Float, nullable=True)
    explanation = Column(Text, nullable=True)
    
    # Risk factors (JSON array)
    risk_factors = Column(Text, nullable=True)  # JSON string
    
    # Human override
    human_override = Column(Boolean, default=False)
    human_decision = Column(String(50), nullable=True)
    human_notes = Column(Text, nullable=True)
    
    # Metadata processed (JSON array of metadata IDs)
    metadata_processed = Column(Text, nullable=True)  # JSON string
    processing_time_seconds = Column(Float, nullable=True)
    
    # Timestamps
    created_date = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_date = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def to_dict(self):
        """Convert model to dictionary"""
        import json as _json
        
        def safe_json_loads(val):
            if val is None:
                return []
            if isinstance(val, list):
                return val
            try:
                return _json.loads(val)
            except:
                return []
        
        return {
            'id': self.id,
            'underwriting_id': self.underwriting_id,
            'customer_id': self.customer_id,
            'assessment_id': self.assessment_id,
            'assessment_date': self.assessment_date.isoformat() if self.assessment_date else None,
            'overall_risk_score': self.overall_risk_score,
            'risk_level': self.risk_level,
            'identity_verified': self.identity_verified,
            'identity_score': self.identity_score,
            'document_score': self.document_score,
            'medical_score': self.medical_score,
            'behavioral_score': self.behavioral_score,
            'fraud_score': self.fraud_score,
            'recommendation': self.recommendation,
            'confidence_level': self.confidence_level,
            'explanation': self.explanation,
            'risk_factors': safe_json_loads(self.risk_factors),
            'human_override': self.human_override,
            'human_decision': self.human_decision,
            'human_notes': self.human_notes,
            'metadata_processed': safe_json_loads(self.metadata_processed),
            'processing_time_seconds': self.processing_time_seconds,
            'created_date': self.created_date.isoformat() if self.created_date else None,
            'updated_date': self.updated_date.isoformat() if self.updated_date else None
        }


class RiskFactorModel(Base):
    """
    Stores individual risk factors identified during assessment.
    
    This is a NEW table - does not modify any existing customer data.
    """
    __tablename__ = 'risk_factors'
    
    id = Column(String(50), primary_key=True)
    report_id = Column(String(50), index=True, nullable=False)
    
    # Factor details
    factor_category = Column(String(50), nullable=False, index=True)  # age, health, lifestyle, occupation, location, history
    factor_name = Column(String(200), nullable=False)
    factor_value = Column(Text, nullable=True)
    
    # Impact assessment
    impact_score = Column(Float, nullable=False)  # -1.0 to 1.0
    impact_direction = Column(String(20), nullable=False)  # positive (increases risk), negative (decreases), neutral
    
    # Source metadata
    source_metadata_id = Column(String(50), nullable=True)
    explanation = Column(Text, nullable=True)
    
    # Timestamps
    created_date = Column(DateTime, default=datetime.utcnow, nullable=False)
    
    def to_dict(self):
        """Convert model to dictionary"""
        return {
            'id': self.id,
            'report_id': self.report_id,
            'factor_category': self.factor_category,
            'factor_name': self.factor_name,
            'factor_value': self.factor_value,
            'impact_score': self.impact_score,
            'impact_direction': self.impact_direction,
            'source_metadata_id': self.source_metadata_id,
            'explanation': self.explanation,
            'created_date': self.created_date.isoformat() if self.created_date else None
        }


class BotAssessmentModel(Base):
    """
    Stores bot assessment sessions.
    
    This is a NEW table - does not modify any existing customer data.
    """
    __tablename__ = 'bot_assessments'
    
    id = Column(String(50), primary_key=True)
    underwriting_id = Column(String(50), index=True, nullable=False)
    customer_id = Column(String(50), index=True, nullable=False)
    policy_id = Column(String(50), index=True, nullable=True)
    
    # Status
    status = Column(String(50), nullable=False, default='initiated', index=True)
    
    # Customer snapshot (READ-ONLY copy at time of assessment)
    customer_snapshot = Column(Text, nullable=True)  # JSON string
    existing_policies_count = Column(Integer, default=0)
    existing_claims_count = Column(Integer, default=0)
    
    # Timestamps
    started_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    completed_at = Column(DateTime, nullable=True)
    
    # Report reference
    report_id = Column(String(50), nullable=True, index=True)
    
    # Timestamps
    created_date = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_date = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def to_dict(self):
        """Convert model to dictionary"""
        import json as _json
        
        def safe_json_loads(val):
            if val is None:
                return {}
            if isinstance(val, dict):
                return val
            try:
                return _json.loads(val)
            except:
                return {}
        
        return {
            'id': self.id,
            'underwriting_id': self.underwriting_id,
            'customer_id': self.customer_id,
            'policy_id': self.policy_id,
            'status': self.status,
            'customer_snapshot': safe_json_loads(self.customer_snapshot),
            'existing_policies_count': self.existing_policies_count,
            'existing_claims_count': self.existing_claims_count,
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'report_id': self.report_id,
            'created_date': self.created_date.isoformat() if self.created_date else None,
            'updated_date': self.updated_date.isoformat() if self.updated_date else None
        }


class ExtractedFeatureModel(Base):
    """
    Stores features extracted from metadata.
    
    This is a NEW table - does not modify any existing customer data.
    """
    __tablename__ = 'extracted_features'
    
    id = Column(String(50), primary_key=True)
    metadata_id = Column(String(50), index=True, nullable=False)
    
    # Feature details
    feature_type = Column(String(100), nullable=False, index=True)  # identity, health, document, behavioral
    feature_name = Column(String(200), nullable=False)
    feature_value = Column(Text, nullable=True)
    confidence = Column(Float, nullable=True)
    source_location = Column(String(100), nullable=True)
    
    # Timestamps
    created_date = Column(DateTime, default=datetime.utcnow, nullable=False)
    
    def to_dict(self):
        """Convert model to dictionary"""
        return {
            'id': self.id,
            'metadata_id': self.metadata_id,
            'feature_type': self.feature_type,
            'feature_name': self.feature_name,
            'feature_value': self.feature_value,
            'confidence': self.confidence,
            'source_location': self.source_location,
            'created_date': self.created_date.isoformat() if self.created_date else None
        }


# ============================================================================
# SUPPLIER ECOSYSTEM MODELS (B2B Marketplace Integration)
# ============================================================================


class SupplierType(str, enum.Enum):
    """Types of suppliers that can register on the platform"""
    HEALTHCARE_PROVIDER = "healthcare_provider"  # Doctors, hospitals, clinics
    PHARMACY = "pharmacy"  # Pharmacies (retail, online, specialty)
    LEGAL_SERVICE = "legal_service"  # Law firms, attorneys
    DELIVERY = "delivery"  # Delivery companies, medical transport
    INVESTMENT_FIRM = "investment_firm"  # Asset managers, pension funds
    EQUIPMENT_SUPPLIER = "equipment_supplier"  # Medical equipment providers
    TECH_PROVIDER = "tech_provider"  # Telemedicine, health apps
    LABORATORY = "laboratory"  # Lab services, imaging centers
    WELLNESS = "wellness"  # Wellness programs, rehabilitation
    OTHER = "other"


class SupplierStatus(str, enum.Enum):
    """Supplier application and account status"""
    PENDING = "pending"  # Application submitted, awaiting review
    UNDER_REVIEW = "under_review"  # Admin reviewing application
    APPROVED = "approved"  # Approved and active
    REJECTED = "rejected"  # Application rejected
    SUSPENDED = "suspended"  # Temporarily suspended
    TERMINATED = "terminated"  # Permanently terminated


class SupplierVerificationStatus(str, enum.Enum):
    """Document verification status for suppliers"""
    PENDING = "pending"
    VERIFIED = "verified"
    FAILED = "failed"
    EXPIRED = "expired"


class SupplierAIRecommendation(str, enum.Enum):
    """AI recommendation for supplier applications"""
    APPROVE = "approve"
    REVIEW = "review"
    REJECT = "reject"


class Supplier(Base):
    """
    Supplier master table for B2B marketplace integration.
    
    Suppliers are external service/product providers that connect to customers
    via the PHINS marketplace and wallet system (Health Wallet, Investment Wallet, etc.)
    
    Examples: Doctors, pharmacies, lawyers, delivery companies, investment firms,
    medical equipment suppliers, telemedicine providers.
    """
    __tablename__ = 'suppliers'
    
    id = Column(String(50), primary_key=True)  # SUP-XXXX-XXXX format
    
    # Company Information
    company_name = Column(String(200), nullable=False, index=True)
    business_registration_number = Column(String(100), nullable=True)
    tax_id = Column(String(100), nullable=True)
    supplier_type = Column(String(50), nullable=False, index=True)  # healthcare_provider, pharmacy, legal_service, etc.
    category = Column(String(100), nullable=False, index=True)  # medical, legal, financial, logistics, tech
    sub_category = Column(String(100), nullable=True)  # More specific categorization
    description = Column(Text, nullable=True)
    
    # Services and Products offered (JSON arrays)
    services_offered = Column(Text, nullable=True)  # JSON array of service types
    products_offered = Column(Text, nullable=True)  # JSON array of product types
    service_areas = Column(Text, nullable=True)  # JSON array of regions/areas served
    
    # Contact Information
    contact_name = Column(String(200), nullable=False)
    contact_email = Column(String(254), unique=True, nullable=False, index=True)
    contact_phone = Column(String(50), nullable=True)
    website = Column(String(500), nullable=True)
    address = Column(Text, nullable=True)
    city = Column(String(100), nullable=True)
    state = Column(String(100), nullable=True)
    country = Column(String(100), nullable=True, default='United States')
    postal_code = Column(String(20), nullable=True)
    
    # Authentication (for Supplier Portal access)
    password_hash = Column(String(255), nullable=True)
    password_salt = Column(String(255), nullable=True)
    portal_active = Column(Boolean, default=False)  # Activated after approval
    last_login = Column(DateTime, nullable=True)
    
    # Approval Workflow
    status = Column(String(50), default='pending', index=True)  # pending, under_review, approved, rejected, suspended, terminated
    application_date = Column(DateTime, default=datetime.utcnow, nullable=False)
    review_date = Column(DateTime, nullable=True)
    approval_date = Column(DateTime, nullable=True)
    approved_by = Column(String(100), nullable=True)  # Admin username who approved
    rejection_reason = Column(Text, nullable=True)
    suspension_reason = Column(Text, nullable=True)
    
    # AI Risk Assessment
    ai_risk_score = Column(Float, nullable=True)  # 0.0 to 1.0 (lower is better)
    ai_trust_score = Column(Float, nullable=True)  # 0.0 to 1.0 (higher is better)
    ai_recommendation = Column(String(50), nullable=True)  # approve, review, reject
    ai_assessment_date = Column(DateTime, nullable=True)
    ai_assessment_notes = Column(Text, nullable=True)  # JSON with detailed assessment
    
    # Document Verification
    verification_status = Column(String(50), default='pending', index=True)  # pending, verified, failed, expired
    documents_verified = Column(Boolean, default=False)
    documents_metadata = Column(Text, nullable=True)  # JSON array of uploaded documents
    license_number = Column(String(100), nullable=True)
    license_expiry = Column(DateTime, nullable=True)
    insurance_certificate = Column(String(255), nullable=True)
    insurance_expiry = Column(DateTime, nullable=True)
    
    # Wallet Configuration
    wallet_types_supported = Column(Text, nullable=True)  # JSON array: ["health", "investment", "general"]
    payment_methods = Column(Text, nullable=True)  # JSON array: ["wallet", "bank_transfer", "crypto"]
    bank_details = Column(Text, nullable=True)  # Encrypted JSON: {bank_name, account_number, routing_number}
    crypto_wallet = Column(String(200), nullable=True)  # Crypto wallet address if supported
    commission_rate = Column(Float, default=0.10)  # Platform commission rate (0.0 - 0.30)
    settlement_frequency = Column(String(50), default='weekly')  # daily, weekly, monthly
    
    # Performance Metrics (updated by triggers/jobs)
    total_orders = Column(Integer, default=0)
    total_revenue = Column(Float, default=0.0)
    average_rating = Column(Float, default=0.0)  # 0.0 to 5.0
    total_reviews = Column(Integer, default=0)
    dispute_count = Column(Integer, default=0)
    dispute_resolution_rate = Column(Float, default=1.0)  # 0.0 to 1.0
    
    # Timestamps
    created_date = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_date = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    offers = relationship("SupplierOffer", back_populates="supplier", cascade="all, delete-orphan")
    orders = relationship("SupplierOrder", back_populates="supplier", cascade="all, delete-orphan")
    
    def to_dict(self, include_sensitive: bool = False):
        """Convert model to dictionary"""
        import json as _json
        
        def safe_json_loads(val):
            if val is None:
                return []
            if isinstance(val, list):
                return val
            try:
                return _json.loads(val)
            except:
                return []
        
        data = {
            'id': self.id,
            'company_name': self.company_name,
            'business_registration_number': self.business_registration_number,
            'tax_id': self.tax_id if include_sensitive else ('***' if self.tax_id else None),
            'supplier_type': self.supplier_type,
            'category': self.category,
            'sub_category': self.sub_category,
            'description': self.description,
            'services_offered': safe_json_loads(self.services_offered),
            'products_offered': safe_json_loads(self.products_offered),
            'service_areas': safe_json_loads(self.service_areas),
            'contact_name': self.contact_name,
            'contact_email': self.contact_email,
            'contact_phone': self.contact_phone,
            'website': self.website,
            'address': self.address,
            'city': self.city,
            'state': self.state,
            'country': self.country,
            'postal_code': self.postal_code,
            'portal_active': self.portal_active,
            'last_login': self.last_login.isoformat() if self.last_login else None,
            'status': self.status,
            'application_date': self.application_date.isoformat() if self.application_date else None,
            'review_date': self.review_date.isoformat() if self.review_date else None,
            'approval_date': self.approval_date.isoformat() if self.approval_date else None,
            'approved_by': self.approved_by,
            'rejection_reason': self.rejection_reason,
            'suspension_reason': self.suspension_reason,
            'ai_risk_score': self.ai_risk_score,
            'ai_trust_score': self.ai_trust_score,
            'ai_recommendation': self.ai_recommendation,
            'ai_assessment_date': self.ai_assessment_date.isoformat() if self.ai_assessment_date else None,
            'verification_status': self.verification_status,
            'documents_verified': self.documents_verified,
            'license_number': self.license_number,
            'license_expiry': self.license_expiry.isoformat() if self.license_expiry else None,
            'wallet_types_supported': safe_json_loads(self.wallet_types_supported),
            'payment_methods': safe_json_loads(self.payment_methods),
            'commission_rate': self.commission_rate,
            'settlement_frequency': self.settlement_frequency,
            'total_orders': self.total_orders,
            'total_revenue': self.total_revenue,
            'average_rating': self.average_rating,
            'total_reviews': self.total_reviews,
            'dispute_count': self.dispute_count,
            'dispute_resolution_rate': self.dispute_resolution_rate,
            'created_date': self.created_date.isoformat() if self.created_date else None,
            'updated_date': self.updated_date.isoformat() if self.updated_date else None
        }
        
        # Include sensitive fields only if explicitly requested (for internal use)
        if include_sensitive:
            data['bank_details'] = safe_json_loads(self.bank_details) if self.bank_details else None
            data['crypto_wallet'] = self.crypto_wallet
            data['documents_metadata'] = safe_json_loads(self.documents_metadata)
            data['ai_assessment_notes'] = safe_json_loads(self.ai_assessment_notes) if self.ai_assessment_notes else None
        
        return data
    
    def has_portal_access(self) -> bool:
        """Check if supplier has active portal access"""
        return bool(
            self.password_hash and 
            self.password_salt and 
            self.portal_active and 
            self.status == 'approved'
        )
    
    def is_active(self) -> bool:
        """Check if supplier is active and approved"""
        return self.status == 'approved' and self.portal_active


class SupplierOffer(Base):
    """
    Supplier offers (services and products) available in the marketplace.
    
    Offers are linked to specific wallet types (health, investment) and can be
    purchased by customers using their wallet balance.
    """
    __tablename__ = 'supplier_offers'
    
    id = Column(String(50), primary_key=True)  # OFF-XXXX-XXXX format
    supplier_id = Column(String(50), ForeignKey('suppliers.id', ondelete='CASCADE'), nullable=False, index=True)
    
    # Offer Details
    name = Column(String(200), nullable=False, index=True)
    description = Column(Text, nullable=True)
    item_type = Column(String(50), nullable=False, index=True)  # service, product
    category = Column(String(100), nullable=False, index=True)
    sub_category = Column(String(100), nullable=True)
    
    # Pricing
    price = Column(Float, nullable=False)
    currency = Column(String(10), default='USD')
    unit = Column(String(50), default='per_item')  # per_item, per_visit, per_hour, per_day, per_month
    min_quantity = Column(Integer, default=1)
    max_quantity = Column(Integer, nullable=True)
    
    # Wallet Compatibility
    wallet_compatible = Column(Text, nullable=True)  # JSON array: ["health", "investment", "general"]
    
    # Status and Display
    active = Column(Boolean, default=True, index=True)
    featured = Column(Boolean, default=False)
    image_url = Column(String(500), nullable=True)
    
    # Availability
    availability = Column(Text, nullable=True)  # JSON: {days: [], hours: {start, end}, blackout_dates: []}
    requires_appointment = Column(Boolean, default=False)
    lead_time_hours = Column(Integer, default=0)  # Hours notice required
    
    # Performance Metrics
    total_orders = Column(Integer, default=0)
    total_revenue = Column(Float, default=0.0)
    average_rating = Column(Float, default=0.0)
    
    # Timestamps
    created_date = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_date = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    supplier = relationship("Supplier", back_populates="offers")
    
    def to_dict(self):
        """Convert model to dictionary"""
        import json as _json
        
        def safe_json_loads(val):
            if val is None:
                return []
            if isinstance(val, list):
                return val
            try:
                return _json.loads(val)
            except:
                return []
        
        return {
            'id': self.id,
            'supplier_id': self.supplier_id,
            'name': self.name,
            'description': self.description,
            'item_type': self.item_type,
            'category': self.category,
            'sub_category': self.sub_category,
            'price': self.price,
            'currency': self.currency,
            'unit': self.unit,
            'min_quantity': self.min_quantity,
            'max_quantity': self.max_quantity,
            'wallet_compatible': safe_json_loads(self.wallet_compatible),
            'active': self.active,
            'featured': self.featured,
            'image_url': self.image_url,
            'availability': safe_json_loads(self.availability) if self.availability else None,
            'requires_appointment': self.requires_appointment,
            'lead_time_hours': self.lead_time_hours,
            'total_orders': self.total_orders,
            'total_revenue': self.total_revenue,
            'average_rating': self.average_rating,
            'created_date': self.created_date.isoformat() if self.created_date else None,
            'updated_date': self.updated_date.isoformat() if self.updated_date else None
        }


class SupplierOrderStatus(str, enum.Enum):
    """Order status lifecycle"""
    PENDING = "pending"  # Order created, awaiting confirmation
    CONFIRMED = "confirmed"  # Supplier confirmed
    PROCESSING = "processing"  # Being prepared/processed
    SHIPPED = "shipped"  # Product shipped (for products)
    IN_PROGRESS = "in_progress"  # Service in progress
    DELIVERED = "delivered"  # Product delivered
    COMPLETED = "completed"  # Service/order completed
    CANCELLED = "cancelled"  # Cancelled by customer or supplier
    REFUNDED = "refunded"  # Payment refunded
    DISPUTED = "disputed"  # Under dispute


class SupplierOrder(Base):
    """
    Orders placed by customers with suppliers.
    
    Connects customers to suppliers through the PHINS marketplace,
    with payment via Health Wallet, Investment Wallet, or bank transfer.
    """
    __tablename__ = 'supplier_orders'
    
    id = Column(String(50), primary_key=True)  # ORD-XXXX-XXXX format
    supplier_id = Column(String(50), ForeignKey('suppliers.id', ondelete='CASCADE'), nullable=False, index=True)
    customer_id = Column(String(50), nullable=False, index=True)  # References customers table
    offer_id = Column(String(50), nullable=True, index=True)  # References supplier_offers table
    
    # Order Details
    order_type = Column(String(50), nullable=False)  # service, product
    item_name = Column(String(200), nullable=False)
    item_description = Column(Text, nullable=True)
    quantity = Column(Integer, default=1)
    unit_price = Column(Float, nullable=False)
    total_amount = Column(Float, nullable=False)
    
    # Platform Fees
    platform_fee = Column(Float, default=0.0)  # Commission taken by PHINS
    supplier_payout = Column(Float, nullable=False)  # Amount to pay supplier
    
    # Payment Information
    payment_method = Column(String(50), nullable=False)  # health_wallet, investment_wallet, bank_transfer
    wallet_transaction_id = Column(String(100), nullable=True)  # Reference to wallet transaction
    payment_status = Column(String(50), default='pending')  # pending, completed, failed, refunded
    payment_date = Column(DateTime, nullable=True)
    
    # Order Status
    status = Column(String(50), default='pending', index=True)
    
    # Delivery/Service Details
    delivery_address = Column(Text, nullable=True)
    delivery_notes = Column(Text, nullable=True)
    scheduled_date = Column(DateTime, nullable=True)  # For appointments/scheduled services
    estimated_delivery = Column(DateTime, nullable=True)
    actual_delivery = Column(DateTime, nullable=True)
    completed_date = Column(DateTime, nullable=True)
    
    # Tracking
    tracking_number = Column(String(100), nullable=True)
    tracking_url = Column(String(500), nullable=True)
    
    # Review and Rating
    rating = Column(Float, nullable=True)  # 0.0 to 5.0
    review = Column(Text, nullable=True)
    review_date = Column(DateTime, nullable=True)
    
    # Dispute Information
    dispute_reason = Column(Text, nullable=True)
    dispute_date = Column(DateTime, nullable=True)
    dispute_resolution = Column(Text, nullable=True)
    dispute_resolved_date = Column(DateTime, nullable=True)
    
    # Cancellation
    cancelled_by = Column(String(50), nullable=True)  # customer, supplier, admin
    cancellation_reason = Column(Text, nullable=True)
    cancelled_date = Column(DateTime, nullable=True)
    
    # Timestamps
    created_date = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_date = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    supplier = relationship("Supplier", back_populates="orders")
    
    def to_dict(self):
        """Convert model to dictionary"""
        return {
            'id': self.id,
            'supplier_id': self.supplier_id,
            'customer_id': self.customer_id,
            'offer_id': self.offer_id,
            'order_type': self.order_type,
            'item_name': self.item_name,
            'item_description': self.item_description,
            'quantity': self.quantity,
            'unit_price': self.unit_price,
            'total_amount': self.total_amount,
            'platform_fee': self.platform_fee,
            'supplier_payout': self.supplier_payout,
            'payment_method': self.payment_method,
            'wallet_transaction_id': self.wallet_transaction_id,
            'payment_status': self.payment_status,
            'payment_date': self.payment_date.isoformat() if self.payment_date else None,
            'status': self.status,
            'delivery_address': self.delivery_address,
            'delivery_notes': self.delivery_notes,
            'scheduled_date': self.scheduled_date.isoformat() if self.scheduled_date else None,
            'estimated_delivery': self.estimated_delivery.isoformat() if self.estimated_delivery else None,
            'actual_delivery': self.actual_delivery.isoformat() if self.actual_delivery else None,
            'completed_date': self.completed_date.isoformat() if self.completed_date else None,
            'tracking_number': self.tracking_number,
            'tracking_url': self.tracking_url,
            'rating': self.rating,
            'review': self.review,
            'review_date': self.review_date.isoformat() if self.review_date else None,
            'dispute_reason': self.dispute_reason,
            'dispute_date': self.dispute_date.isoformat() if self.dispute_date else None,
            'dispute_resolution': self.dispute_resolution,
            'dispute_resolved_date': self.dispute_resolved_date.isoformat() if self.dispute_resolved_date else None,
            'cancelled_by': self.cancelled_by,
            'cancellation_reason': self.cancellation_reason,
            'cancelled_date': self.cancelled_date.isoformat() if self.cancelled_date else None,
            'created_date': self.created_date.isoformat() if self.created_date else None,
            'updated_date': self.updated_date.isoformat() if self.updated_date else None
        }


class SupplierDocument(Base):
    """
    Documents uploaded by suppliers for verification.
    
    Tracks business licenses, certifications, insurance certificates,
    and other required documents for supplier approval.
    """
    __tablename__ = 'supplier_documents'
    
    id = Column(String(50), primary_key=True)  # DOC-XXXX-XXXX format
    supplier_id = Column(String(50), ForeignKey('suppliers.id', ondelete='CASCADE'), nullable=False, index=True)
    
    # Document Details
    document_type = Column(String(100), nullable=False, index=True)  # business_license, certification, insurance, tax_document, etc.
    document_name = Column(String(255), nullable=False)
    file_path = Column(String(500), nullable=True)
    file_hash = Column(String(64), nullable=True)  # SHA-256 hash for integrity
    file_size_bytes = Column(Integer, nullable=True)
    mime_type = Column(String(100), nullable=True)
    
    # Verification
    verification_status = Column(String(50), default='pending', index=True)  # pending, verified, rejected, expired
    verified_by = Column(String(100), nullable=True)
    verified_date = Column(DateTime, nullable=True)
    verification_notes = Column(Text, nullable=True)
    
    # Expiry Tracking
    issue_date = Column(DateTime, nullable=True)
    expiry_date = Column(DateTime, nullable=True, index=True)
    expiry_reminder_sent = Column(Boolean, default=False)
    
    # Timestamps
    upload_date = Column(DateTime, default=datetime.utcnow, nullable=False)
    created_date = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_date = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def to_dict(self):
        """Convert model to dictionary"""
        return {
            'id': self.id,
            'supplier_id': self.supplier_id,
            'document_type': self.document_type,
            'document_name': self.document_name,
            'file_path': self.file_path,
            'file_size_bytes': self.file_size_bytes,
            'mime_type': self.mime_type,
            'verification_status': self.verification_status,
            'verified_by': self.verified_by,
            'verified_date': self.verified_date.isoformat() if self.verified_date else None,
            'verification_notes': self.verification_notes,
            'issue_date': self.issue_date.isoformat() if self.issue_date else None,
            'expiry_date': self.expiry_date.isoformat() if self.expiry_date else None,
            'expiry_reminder_sent': self.expiry_reminder_sent,
            'upload_date': self.upload_date.isoformat() if self.upload_date else None,
            'created_date': self.created_date.isoformat() if self.created_date else None,
            'updated_date': self.updated_date.isoformat() if self.updated_date else None
        }
