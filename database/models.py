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
import json

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


class PlatformLedgerEntry(Base):
    """Append-only event ledger for financial and operational lineage."""
    __tablename__ = 'platform_ledger_entries'

    id = Column(String(120), primary_key=True)
    sequence_no = Column(Integer, nullable=False, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    ledger_type = Column(String(50), default='event', nullable=False, index=True)
    event_type = Column(String(100), nullable=False, index=True)
    entity_type = Column(String(100), index=True)
    entity_id = Column(String(120), index=True)
    customer_id = Column(String(50), index=True)
    actor = Column(String(100), index=True)
    amount = Column(Float, default=0.0)
    currency = Column(String(12), default='USD')
    status = Column(String(50), default='recorded', index=True)
    source_system = Column(String(100), default='web_portal', index=True)
    previous_hash = Column(String(128))
    entry_hash = Column(String(128), nullable=False, index=True)
    payload = Column(Text)
    created_date = Column(DateTime, default=datetime.utcnow, nullable=False)

    def to_dict(self):
        payload = self.payload
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except Exception:
                pass

        return {
            'id': self.id,
            'sequence_no': self.sequence_no,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
            'ledger_type': self.ledger_type,
            'event_type': self.event_type,
            'entity_type': self.entity_type,
            'entity_id': self.entity_id,
            'customer_id': self.customer_id,
            'actor': self.actor,
            'amount': self.amount,
            'currency': self.currency,
            'status': self.status,
            'source_system': self.source_system,
            'previous_hash': self.previous_hash,
            'entry_hash': self.entry_hash,
            'payload': payload,
            'created_date': self.created_date.isoformat() if self.created_date else None,
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
    
    # Invitation code used to register (links to SupplierInvitationCode)
    invitation_code = Column(String(100), nullable=True, index=True)

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


class SupplierInvitationCode(Base):
    """
    Invitation codes generated by admins for supplier registration.

    Persisted so codes, their usage, and expiry survive server restarts.
    """
    __tablename__ = 'supplier_invitation_codes'

    code = Column(String(100), primary_key=True)
    created_at = Column(String(100), nullable=False)
    created_by = Column(String(100), nullable=False)
    supplier_type = Column(String(50), nullable=True)
    expires_at = Column(String(100), nullable=False)
    max_uses = Column(Integer, default=1)
    used_count = Column(Integer, default=0)
    used_by = Column(Text, nullable=True)  # JSON array of supplier IDs
    status = Column(String(20), default='active', index=True)
    notes = Column(Text, nullable=True)
    referrer_id = Column(String(50), nullable=True)
    commission_override = Column(Float, nullable=True)

    created_date = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_date = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        used_by_list = []
        if self.used_by:
            try:
                used_by_list = json.loads(self.used_by)
            except Exception:
                used_by_list = []
        return {
            'code': self.code,
            'created_at': self.created_at,
            'created_by': self.created_by,
            'supplier_type': self.supplier_type,
            'expires_at': self.expires_at,
            'max_uses': self.max_uses,
            'used_count': self.used_count,
            'used_by': used_by_list,
            'status': self.status,
            'notes': self.notes,
            'referrer_id': self.referrer_id,
            'commission_override': self.commission_override,
        }


class SupplyChainLedgerEntry(Base):
    """
    Cryptographic ledger entries for supply-chain transactions.

    Persisted to maintain an audit trail across restarts.
    """
    __tablename__ = 'supply_chain_ledger'

    id = Column(String(100), primary_key=True)
    entry_type = Column(String(50), nullable=False, index=True)
    timestamp = Column(String(100), nullable=False)
    amount = Column(Float, default=0.0)
    supplier_id = Column(String(50), nullable=True, index=True)
    customer_id = Column(String(50), nullable=True, index=True)
    order_id = Column(String(50), nullable=True, index=True)
    description = Column(Text, nullable=True)
    previous_hash = Column(String(128), nullable=True)
    entry_hash = Column(String(128), nullable=True)
    metadata_json = Column(Text, nullable=True)  # JSON blob for extra fields

    created_date = Column(DateTime, default=datetime.utcnow, nullable=False)

    def to_dict(self):
        meta = {}
        if self.metadata_json:
            try:
                meta = json.loads(self.metadata_json)
            except Exception:
                meta = {}
        base = {
            'id': self.id,
            'entry_type': self.entry_type,
            'timestamp': self.timestamp,
            'amount': self.amount,
            'supplier_id': self.supplier_id,
            'customer_id': self.customer_id,
            'order_id': self.order_id,
            'description': self.description,
            'previous_hash': self.previous_hash,
            'entry_hash': self.entry_hash,
        }
        base.update(meta)
        return base


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


# ============================================================================
# COMMUNITY FOUNDATION MODELS (Mutual Aid Groups)
# ============================================================================


class FoundationType(str, enum.Enum):
    """Types of community foundations"""
    FAMILY = "family"
    WORK = "work"
    NEIGHBORHOOD = "neighborhood"
    FRIENDS = "friends"
    ENTREPRENEURS = "entrepreneurs"
    BUSINESS_VENTURE = "business_venture"
    PROFESSIONAL = "professional"
    CUSTOMER_CLUB = "customer_club"
    CUSTOM = "custom"


class FoundationStatus(str, enum.Enum):
    """Foundation lifecycle status"""
    DRAFT = "draft"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    INACTIVE = "inactive"
    DISSOLVED = "dissolved"


class MemberRole(str, enum.Enum):
    """Foundation member roles"""
    FOUNDER = "founder"
    ADMIN = "admin"
    MEMBER = "member"
    OBSERVER = "observer"


class MemberStatus(str, enum.Enum):
    """Membership status"""
    INVITED = "invited"
    PENDING = "pending"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    REMOVED = "removed"
    DECLINED = "declined"


class FundType(str, enum.Enum):
    """Types of foundation funds"""
    COLLECTIVE_INSURANCE = "insurance"
    MUTUAL_SAVINGS = "savings"
    EMERGENCY = "emergency"
    CUSTOM = "custom"


class FoundationClaimType(str, enum.Enum):
    """Types of foundation claims"""
    MEDICAL = "medical"
    DISABILITY = "disability"
    EMERGENCY = "emergency"
    BUSINESS_INTERRUPTION = "business"
    CUSTOM = "custom"


class FoundationClaimStatus(str, enum.Enum):
    """Foundation claim status"""
    SUBMITTED = "submitted"
    REVIEWING = "reviewing"
    VOTE_OPEN = "vote_open"
    APPROVED = "approved"
    REJECTED = "rejected"
    PAID = "paid"


class VoteStatus(str, enum.Enum):
    """Vote/proposal status"""
    OPEN = "open"
    CLOSED = "closed"
    PASSED = "passed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class InvitationStatus(str, enum.Enum):
    """Foundation invitation status"""
    PENDING = "pending"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    EXPIRED = "expired"
    REVOKED = "revoked"


class ContributionStatus(str, enum.Enum):
    """Contribution payment status"""
    SCHEDULED = "scheduled"
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
    REFUNDED = "refunded"


class Foundation(Base):
    """
    Community Foundation table for mutual aid groups.
    
    Foundations allow customers and suppliers to create and manage mutual aid
    groups with shared insurance coverage, collective savings, and governance.
    """
    __tablename__ = 'foundations'
    
    id = Column(String(50), primary_key=True)  # FND-XXXX-XXXX format
    name = Column(String(200), nullable=False, index=True)
    foundation_type = Column(String(50), nullable=False, index=True)  # FoundationType
    description = Column(Text, nullable=True)
    
    # Founder Information
    founder_id = Column(String(50), nullable=False, index=True)  # Customer or Supplier ID
    founder_type = Column(String(20), nullable=False)  # "customer" or "supplier"
    
    # Status and Limits
    status = Column(String(50), default='draft', index=True)  # FoundationStatus
    max_members = Column(Integer, default=35)
    is_unlimited = Column(Boolean, default=False)  # For customer_club type
    current_members = Column(Integer, default=1)
    
    # Financial
    total_fund_balance = Column(Float, default=0.0)
    reserve_percentage = Column(Float, default=20.0)  # Minimum 20%
    currency = Column(String(10), default='USD')
    
    # Governance Settings (JSON)
    settings = Column(Text, nullable=True)  # JSON: base_rules, contribution_rules, claim_rules, etc.
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    activated_at = Column(DateTime, nullable=True)
    dissolved_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    members = relationship("FoundationMember", back_populates="foundation", cascade="all, delete-orphan")
    funds = relationship("FoundationFund", back_populates="foundation", cascade="all, delete-orphan")
    invitations = relationship("FoundationInvitation", back_populates="foundation", cascade="all, delete-orphan")
    votes = relationship("FoundationVote", back_populates="foundation", cascade="all, delete-orphan")
    claims = relationship("FoundationClaim", back_populates="foundation", cascade="all, delete-orphan")
    activities = relationship("FoundationActivity", back_populates="foundation", cascade="all, delete-orphan")
    
    def to_dict(self, include_settings: bool = True):
        """Convert model to dictionary"""
        import json as _json
        
        data = {
            'id': self.id,
            'name': self.name,
            'foundation_type': self.foundation_type,
            'description': self.description,
            'founder_id': self.founder_id,
            'founder_type': self.founder_type,
            'status': self.status,
            'max_members': self.max_members,
            'is_unlimited': self.is_unlimited,
            'current_members': self.current_members,
            'total_fund_balance': self.total_fund_balance,
            'reserve_percentage': self.reserve_percentage,
            'currency': self.currency,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'activated_at': self.activated_at.isoformat() if self.activated_at else None,
            'dissolved_at': self.dissolved_at.isoformat() if self.dissolved_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }
        
        if include_settings and self.settings:
            try:
                data['settings'] = _json.loads(self.settings)
            except:
                data['settings'] = {}
        
        return data


class FoundationMember(Base):
    """
    Foundation membership table.
    
    Tracks members of each foundation with their roles and contributions.
    """
    __tablename__ = 'foundation_members'
    
    id = Column(String(50), primary_key=True)  # MEM-XXXX-XXXX format
    foundation_id = Column(String(50), ForeignKey('foundations.id', ondelete='CASCADE'), nullable=False, index=True)
    
    # Member Information
    member_id = Column(String(50), nullable=False, index=True)  # Customer or Supplier ID
    member_type = Column(String(20), nullable=False)  # "customer" or "supplier"
    
    # Role and Status
    role = Column(String(20), default='member')  # MemberRole
    status = Column(String(20), default='pending')  # MemberStatus
    
    # Contribution Tracking
    contribution_amount = Column(Float, default=0.0)  # Monthly/periodic amount
    total_contributed = Column(Float, default=0.0)  # Lifetime total
    last_contribution = Column(DateTime, nullable=True)
    
    # Voting
    voting_weight = Column(Float, default=1.0)  # Usually 1.0, can be adjusted
    
    # Display
    display_name = Column(String(100), nullable=True)  # Anonymous display name
    is_visible = Column(Boolean, default=True)  # Show in member list
    
    # Timestamps
    joined_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    invited_at = Column(DateTime, nullable=True)
    approved_at = Column(DateTime, nullable=True)
    removed_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    foundation = relationship("Foundation", back_populates="members")
    
    def to_dict(self):
        return {
            'id': self.id,
            'foundation_id': self.foundation_id,
            'member_id': self.member_id,
            'member_type': self.member_type,
            'role': self.role,
            'status': self.status,
            'contribution_amount': self.contribution_amount,
            'total_contributed': self.total_contributed,
            'last_contribution': self.last_contribution.isoformat() if self.last_contribution else None,
            'voting_weight': self.voting_weight,
            'display_name': self.display_name,
            'is_visible': self.is_visible,
            'joined_at': self.joined_at.isoformat() if self.joined_at else None,
            'approved_at': self.approved_at.isoformat() if self.approved_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }


class FoundationFund(Base):
    """
    Foundation fund accounts.
    
    Each foundation can have multiple funds for different purposes.
    """
    __tablename__ = 'foundation_funds'
    
    id = Column(String(50), primary_key=True)  # FUND-XXXX-XXXX format
    foundation_id = Column(String(50), ForeignKey('foundations.id', ondelete='CASCADE'), nullable=False, index=True)
    
    # Fund Details
    name = Column(String(200), nullable=False)
    fund_type = Column(String(50), nullable=False)  # FundType
    description = Column(Text, nullable=True)
    
    # Balance and Limits
    balance = Column(Float, default=0.0)
    currency = Column(String(10), default='USD')
    min_reserve = Column(Float, default=0.0)  # Minimum reserve amount
    max_claim_percentage = Column(Float, default=25.0)  # Max single claim as % of balance
    
    # Status
    status = Column(String(20), default='active')  # active, frozen, closed
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_activity = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    foundation = relationship("Foundation", back_populates="funds")
    contributions = relationship("FoundationContribution", back_populates="fund", cascade="all, delete-orphan")
    
    def to_dict(self):
        return {
            'id': self.id,
            'foundation_id': self.foundation_id,
            'name': self.name,
            'fund_type': self.fund_type,
            'description': self.description,
            'balance': self.balance,
            'currency': self.currency,
            'min_reserve': self.min_reserve,
            'max_claim_percentage': self.max_claim_percentage,
            'status': self.status,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'last_activity': self.last_activity.isoformat() if self.last_activity else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }


class FoundationContribution(Base):
    """
    Contribution records for foundation funds.
    """
    __tablename__ = 'foundation_contributions'
    
    id = Column(String(50), primary_key=True)  # CONTRIB-XXXX-XXXX format
    fund_id = Column(String(50), ForeignKey('foundation_funds.id', ondelete='CASCADE'), nullable=False, index=True)
    member_id = Column(String(50), nullable=False, index=True)  # FoundationMember ID
    
    # Contribution Details
    amount = Column(Float, nullable=False)
    contribution_type = Column(String(20), nullable=False)  # monthly, quarterly, annual, one_time
    status = Column(String(20), default='pending')  # ContributionStatus
    
    # Scheduling
    due_date = Column(DateTime, nullable=True)
    paid_date = Column(DateTime, nullable=True)
    
    # Payment Reference
    transaction_ref = Column(String(100), nullable=True)
    notes = Column(Text, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    fund = relationship("FoundationFund", back_populates="contributions")
    
    def to_dict(self):
        return {
            'id': self.id,
            'fund_id': self.fund_id,
            'member_id': self.member_id,
            'amount': self.amount,
            'contribution_type': self.contribution_type,
            'status': self.status,
            'due_date': self.due_date.isoformat() if self.due_date else None,
            'paid_date': self.paid_date.isoformat() if self.paid_date else None,
            'transaction_ref': self.transaction_ref,
            'notes': self.notes,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }


class FoundationInvitation(Base):
    """
    Foundation invitations for new members.
    """
    __tablename__ = 'foundation_invitations'
    
    id = Column(String(50), primary_key=True)  # INV-XXXX-XXXX format
    foundation_id = Column(String(50), ForeignKey('foundations.id', ondelete='CASCADE'), nullable=False, index=True)
    
    # Invitation Details
    code = Column(String(100), unique=True, nullable=False, index=True)  # Unique invitation code
    invited_email = Column(String(254), nullable=True, index=True)
    invited_by = Column(String(50), nullable=False)  # Member ID who sent invitation
    
    # Status
    status = Column(String(20), default='pending')  # InvitationStatus
    
    # Usage Limits
    max_uses = Column(Integer, default=1)
    used_count = Column(Integer, default=0)
    
    # Notes
    notes = Column(Text, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    used_at = Column(DateTime, nullable=True)
    
    # Relationships
    foundation = relationship("Foundation", back_populates="invitations")
    
    def to_dict(self):
        return {
            'id': self.id,
            'foundation_id': self.foundation_id,
            'code': self.code,
            'invited_email': self.invited_email,
            'invited_by': self.invited_by,
            'status': self.status,
            'max_uses': self.max_uses,
            'used_count': self.used_count,
            'notes': self.notes,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
            'used_at': self.used_at.isoformat() if self.used_at else None
        }


class FoundationVote(Base):
    """
    Foundation voting/proposals.
    """
    __tablename__ = 'foundation_votes'
    
    id = Column(String(50), primary_key=True)  # VOTE-XXXX-XXXX format
    foundation_id = Column(String(50), ForeignKey('foundations.id', ondelete='CASCADE'), nullable=False, index=True)
    
    # Proposal Details
    proposal_type = Column(String(50), nullable=False)  # rule_change, claim, membership, withdrawal
    title = Column(String(300), nullable=False)
    description = Column(Text, nullable=True)
    
    # Status
    status = Column(String(20), default='open')  # VoteStatus
    
    # Voting Requirements
    threshold = Column(Float, default=0.50)  # Required percentage to pass
    quorum = Column(Float, default=0.50)  # Required participation percentage
    
    # Vote Counts
    votes_for = Column(Integer, default=0)
    votes_against = Column(Integer, default=0)
    votes_abstain = Column(Integer, default=0)
    
    # Result
    result = Column(String(20), nullable=True)  # passed, failed, cancelled
    
    # Created By
    created_by = Column(String(50), nullable=False)  # Member ID
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    closes_at = Column(DateTime, nullable=False)
    closed_at = Column(DateTime, nullable=True)
    
    # Relationships
    foundation = relationship("Foundation", back_populates="votes")
    vote_casts = relationship("FoundationVoteCast", back_populates="vote", cascade="all, delete-orphan")
    
    def to_dict(self):
        return {
            'id': self.id,
            'foundation_id': self.foundation_id,
            'proposal_type': self.proposal_type,
            'title': self.title,
            'description': self.description,
            'status': self.status,
            'threshold': self.threshold,
            'quorum': self.quorum,
            'votes_for': self.votes_for,
            'votes_against': self.votes_against,
            'votes_abstain': self.votes_abstain,
            'result': self.result,
            'created_by': self.created_by,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'closes_at': self.closes_at.isoformat() if self.closes_at else None,
            'closed_at': self.closed_at.isoformat() if self.closed_at else None
        }


class FoundationVoteCast(Base):
    """
    Individual vote records.
    """
    __tablename__ = 'foundation_vote_casts'
    
    id = Column(String(50), primary_key=True)
    vote_id = Column(String(50), ForeignKey('foundation_votes.id', ondelete='CASCADE'), nullable=False, index=True)
    member_id = Column(String(50), nullable=False, index=True)  # FoundationMember ID
    
    # Vote Details
    vote_choice = Column(String(20), nullable=False)  # for, against, abstain
    weight = Column(Float, default=1.0)
    reason = Column(Text, nullable=True)  # Optional explanation
    
    # Timestamps
    cast_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    
    # Relationships
    vote = relationship("FoundationVote", back_populates="vote_casts")
    
    def to_dict(self):
        return {
            'id': self.id,
            'vote_id': self.vote_id,
            'member_id': self.member_id,
            'vote_choice': self.vote_choice,
            'weight': self.weight,
            'reason': self.reason,
            'cast_at': self.cast_at.isoformat() if self.cast_at else None
        }


class FoundationClaim(Base):
    """
    Foundation claims/requests for fund disbursement.
    """
    __tablename__ = 'foundation_claims'
    
    id = Column(String(50), primary_key=True)  # FCLAIM-XXXX-XXXX format
    foundation_id = Column(String(50), ForeignKey('foundations.id', ondelete='CASCADE'), nullable=False, index=True)
    fund_id = Column(String(50), nullable=False, index=True)  # FoundationFund ID
    claimant_id = Column(String(50), nullable=False, index=True)  # Member ID
    
    # Claim Details
    claim_type = Column(String(50), nullable=False)  # FoundationClaimType
    amount_requested = Column(Float, nullable=False)
    amount_approved = Column(Float, nullable=True)
    description = Column(Text, nullable=True)
    
    # Supporting Documents (JSON array)
    supporting_docs = Column(Text, nullable=True)
    
    # Status
    status = Column(String(20), default='submitted')  # FoundationClaimStatus
    
    # Review
    vote_id = Column(String(50), nullable=True)  # If vote was required
    reviewed_by = Column(String(50), nullable=True)  # Admin/Founder who reviewed
    review_notes = Column(Text, nullable=True)
    
    # Payout
    payout_date = Column(DateTime, nullable=True)
    payout_method = Column(String(50), nullable=True)
    payout_reference = Column(String(100), nullable=True)
    
    # Timestamps
    submitted_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    reviewed_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    foundation = relationship("Foundation", back_populates="claims")
    
    def to_dict(self):
        import json as _json
        
        return {
            'id': self.id,
            'foundation_id': self.foundation_id,
            'fund_id': self.fund_id,
            'claimant_id': self.claimant_id,
            'claim_type': self.claim_type,
            'amount_requested': self.amount_requested,
            'amount_approved': self.amount_approved,
            'description': self.description,
            'supporting_docs': _json.loads(self.supporting_docs) if self.supporting_docs else [],
            'status': self.status,
            'vote_id': self.vote_id,
            'reviewed_by': self.reviewed_by,
            'review_notes': self.review_notes,
            'payout_date': self.payout_date.isoformat() if self.payout_date else None,
            'payout_method': self.payout_method,
            'payout_reference': self.payout_reference,
            'submitted_at': self.submitted_at.isoformat() if self.submitted_at else None,
            'reviewed_at': self.reviewed_at.isoformat() if self.reviewed_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }


class FoundationActivity(Base):
    """
    Activity/audit log for foundations.
    """
    __tablename__ = 'foundation_activities'
    
    id = Column(String(50), primary_key=True)
    foundation_id = Column(String(50), ForeignKey('foundations.id', ondelete='CASCADE'), nullable=False, index=True)
    
    # Activity Details
    activity_type = Column(String(50), nullable=False, index=True)  # member_joined, contribution, claim_submitted, vote_cast, etc.
    actor_id = Column(String(50), nullable=False)  # Member who performed action
    details = Column(Text, nullable=True)  # JSON with additional info
    
    # Metadata
    ip_address = Column(String(45), nullable=True)
    
    # Timestamps
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    
    # Relationships
    foundation = relationship("Foundation", back_populates="activities")
    
    def to_dict(self):
        import json as _json
        
        return {
            'id': self.id,
            'foundation_id': self.foundation_id,
            'activity_type': self.activity_type,
            'actor_id': self.actor_id,
            'details': _json.loads(self.details) if self.details else {},
            'ip_address': self.ip_address,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None
        }


# ============================================================================
# OTP VERIFICATION MODELS (Enhanced Security)
# ============================================================================


class OTPVerificationStatus(str, enum.Enum):
    """OTP verification status"""
    PENDING = "pending"
    VERIFIED = "verified"
    EXPIRED = "expired"
    FAILED = "failed"
    BLOCKED = "blocked"


class CaptchaVerification(Base):
    """
    CAPTCHA verification records for bot protection.
    """
    __tablename__ = 'captcha_verifications'
    
    id = Column(String(50), primary_key=True)
    session_id = Column(String(100), nullable=False, index=True)
    
    # Challenge Details
    challenge_type = Column(String(50), nullable=False)  # hcaptcha, recaptcha, custom
    challenge_id = Column(String(200), nullable=True)
    
    # Verification
    verified = Column(Boolean, default=False)
    verification_token = Column(String(500), nullable=True)
    
    # Context
    ip_address = Column(String(45), nullable=True, index=True)
    user_agent = Column(Text, nullable=True)
    action = Column(String(50), nullable=True)  # login, register, otp_request
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    verified_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=False)
    
    def to_dict(self):
        return {
            'id': self.id,
            'session_id': self.session_id,
            'challenge_type': self.challenge_type,
            'verified': self.verified,
            'ip_address': self.ip_address,
            'action': self.action,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'verified_at': self.verified_at.isoformat() if self.verified_at else None,
            'expires_at': self.expires_at.isoformat() if self.expires_at else None
        }


class LoginOTPVerification(Base):
    """
    OTP verification for login security (2FA).
    """
    __tablename__ = 'login_otp_verifications'
    
    id = Column(String(50), primary_key=True)
    
    # User Identification
    user_type = Column(String(20), nullable=False)  # customer, supplier, staff
    user_id = Column(String(100), nullable=False, index=True)
    email = Column(String(254), nullable=False, index=True)
    
    # OTP Details (stored hashed)
    otp_hash = Column(String(255), nullable=False)
    otp_salt = Column(String(255), nullable=False)
    
    # Verification
    status = Column(String(20), default='pending')  # OTPVerificationStatus
    attempts = Column(Integer, default=0)
    max_attempts = Column(Integer, default=5)
    
    # Context
    ip_address = Column(String(45), nullable=True, index=True)
    user_agent = Column(Text, nullable=True)
    device_fingerprint = Column(String(255), nullable=True)
    
    # Flags
    is_new_device = Column(Boolean, default=False)
    is_new_location = Column(Boolean, default=False)
    risk_score = Column(Float, default=0.0)  # 0.0 to 1.0
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    verified_at = Column(DateTime, nullable=True)
    
    def to_dict(self):
        return {
            'id': self.id,
            'user_type': self.user_type,
            'user_id': self.user_id,
            'email': self.email,
            'status': self.status,
            'attempts': self.attempts,
            'max_attempts': self.max_attempts,
            'is_new_device': self.is_new_device,
            'is_new_location': self.is_new_location,
            'risk_score': self.risk_score,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
            'verified_at': self.verified_at.isoformat() if self.verified_at else None
        }


class TrustedDevice(Base):
    """
    Trusted devices for users (skip OTP on known devices).
    """
    __tablename__ = 'trusted_devices'
    
    id = Column(String(50), primary_key=True)
    
    # User Identification
    user_type = Column(String(20), nullable=False)  # customer, supplier, staff
    user_id = Column(String(100), nullable=False, index=True)
    
    # Device Information
    device_fingerprint = Column(String(255), nullable=False, index=True)
    device_name = Column(String(200), nullable=True)  # "Chrome on Windows"
    user_agent = Column(Text, nullable=True)
    
    # Trust Status
    is_active = Column(Boolean, default=True)
    trust_level = Column(Integer, default=1)  # 1=basic, 2=verified, 3=high_trust
    
    # Timestamps
    first_seen = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_seen = Column(DateTime, default=datetime.utcnow)
    trusted_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    revoked_at = Column(DateTime, nullable=True)
    
    def to_dict(self):
        return {
            'id': self.id,
            'user_type': self.user_type,
            'user_id': self.user_id,
            'device_fingerprint': self.device_fingerprint[:8] + '...' if self.device_fingerprint else None,
            'device_name': self.device_name,
            'is_active': self.is_active,
            'trust_level': self.trust_level,
            'first_seen': self.first_seen.isoformat() if self.first_seen else None,
            'last_seen': self.last_seen.isoformat() if self.last_seen else None,
            'trusted_at': self.trusted_at.isoformat() if self.trusted_at else None
        }


# ── Document & File Management ───────────────────────────────────────────────


class DocumentStatus(str, enum.Enum):
    PENDING = "pending"
    UPLOADED = "uploaded"
    PROCESSING = "processing"
    PROCESSED = "processed"
    FAILED = "failed"
    ARCHIVED = "archived"


class DocumentCategory(str, enum.Enum):
    IDENTITY = "identity"
    LEGAL = "legal"
    MEDICAL = "medical"
    FINANCIAL = "financial"
    POLICY = "policy"
    CLAIM = "claim"
    UNDERWRITING = "underwriting"
    REPORT = "report"
    MEDIA = "media"
    TABLE = "table"
    GENERAL = "general"


class Document(Base):
    """Persistent document storage with full metadata and integrity tracking.

    Stores uploaded files (ID docs, medical records, legal papers, videos,
    audio, spreadsheets, PDFs, images, etc.) with SHA-256 checksums, MIME
    type detection, processing status, and extracted metadata.  Binary
    content is stored on disk; the database holds paths and metadata.
    """
    __tablename__ = 'documents'

    id = Column(String(120), primary_key=True)
    file_name = Column(String(500), nullable=False, index=True)
    original_file_name = Column(String(500), nullable=False)
    mime_type = Column(String(200), nullable=False)
    file_size = Column(Integer, nullable=False)
    file_extension = Column(String(20), nullable=True)
    storage_path = Column(Text, nullable=False)

    sha256_checksum = Column(String(64), nullable=False, index=True)
    md5_checksum = Column(String(32), nullable=True)

    category = Column(String(50), nullable=False, default='general', index=True)
    document_type = Column(String(100), nullable=True, index=True)
    description = Column(Text, nullable=True)

    entity_type = Column(String(50), nullable=True, index=True)
    entity_id = Column(String(120), nullable=True, index=True)
    customer_id = Column(String(50), nullable=True, index=True)

    uploaded_by = Column(String(100), nullable=True, index=True)
    uploaded_by_role = Column(String(50), nullable=True)

    status = Column(String(30), nullable=False, default='uploaded', index=True)
    processing_status = Column(String(30), nullable=True)
    processing_result = Column(Text, nullable=True)

    extracted_metadata = Column(Text, nullable=True)
    extracted_text = Column(Text, nullable=True)
    ai_summary = Column(Text, nullable=True)
    ai_tags = Column(Text, nullable=True)
    confidence_score = Column(Float, nullable=True)

    is_archived = Column(Boolean, default=False, index=True)
    is_deleted = Column(Boolean, default=False)
    version = Column(Integer, default=1)
    parent_document_id = Column(String(120), nullable=True, index=True)

    created_date = Column(DateTime, default=datetime.utcnow)
    updated_date = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    processed_date = Column(DateTime, nullable=True)

    processing_jobs = relationship('DocumentProcessingJob', back_populates='document',
                                   cascade='all, delete-orphan')

    def to_dict(self, include_extracted=False):
        result = {
            'id': self.id,
            'file_name': self.file_name,
            'original_file_name': self.original_file_name,
            'mime_type': self.mime_type,
            'file_size': self.file_size,
            'file_extension': self.file_extension,
            'sha256_checksum': self.sha256_checksum,
            'category': self.category,
            'document_type': self.document_type,
            'description': self.description,
            'entity_type': self.entity_type,
            'entity_id': self.entity_id,
            'customer_id': self.customer_id,
            'uploaded_by': self.uploaded_by,
            'uploaded_by_role': self.uploaded_by_role,
            'status': self.status,
            'processing_status': self.processing_status,
            'confidence_score': self.confidence_score,
            'is_archived': self.is_archived,
            'version': self.version,
            'parent_document_id': self.parent_document_id,
            'created_date': self.created_date.isoformat() if self.created_date else None,
            'updated_date': self.updated_date.isoformat() if self.updated_date else None,
            'processed_date': self.processed_date.isoformat() if self.processed_date else None,
        }
        if include_extracted:
            result['extracted_metadata'] = (
                json.loads(self.extracted_metadata) if self.extracted_metadata else None
            )
            result['extracted_text'] = self.extracted_text
            result['ai_summary'] = self.ai_summary
            result['ai_tags'] = json.loads(self.ai_tags) if self.ai_tags else []
            result['processing_result'] = (
                json.loads(self.processing_result) if self.processing_result else None
            )
        return result


class DocumentProcessingJob(Base):
    """Tracks individual processing tasks run against a document."""
    __tablename__ = 'document_processing_jobs'

    id = Column(String(120), primary_key=True)
    document_id = Column(String(120), ForeignKey('documents.id', ondelete='CASCADE'),
                         nullable=False, index=True)
    job_type = Column(String(50), nullable=False, index=True)
    status = Column(String(30), nullable=False, default='pending', index=True)
    input_params = Column(Text, nullable=True)
    result = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)
    processing_time_ms = Column(Integer, nullable=True)
    created_date = Column(DateTime, default=datetime.utcnow)
    completed_date = Column(DateTime, nullable=True)

    document = relationship('Document', back_populates='processing_jobs')

    def to_dict(self):
        return {
            'id': self.id,
            'document_id': self.document_id,
            'job_type': self.job_type,
            'status': self.status,
            'input_params': json.loads(self.input_params) if self.input_params else None,
            'result': json.loads(self.result) if self.result else None,
            'error_message': self.error_message,
            'processing_time_ms': self.processing_time_ms,
            'created_date': self.created_date.isoformat() if self.created_date else None,
            'completed_date': self.completed_date.isoformat() if self.completed_date else None,
        }
