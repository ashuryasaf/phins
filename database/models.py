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
    """Customer master table"""
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
    created_date = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_date = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    policies = relationship("Policy", back_populates="customer", cascade="all, delete-orphan")
    claims = relationship("Claim", back_populates="customer", cascade="all, delete-orphan")
    
    def to_dict(self):
        """Convert model to dictionary"""
        return {
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
            'created_date': self.created_date.isoformat() if self.created_date else None,
            'updated_date': self.updated_date.isoformat() if self.updated_date else None
        }


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
    
    # Relationships
    customer = relationship("Customer", back_populates="policies")
    claims = relationship("Claim", back_populates="policy", cascade="all, delete-orphan")
    
    def to_dict(self):
        """Convert model to dictionary"""
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
            'uw_status': self.uw_status
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
    
    # Relationships
    policy = relationship("Policy", back_populates="claims")
    customer = relationship("Customer", back_populates="claims")
    
    def to_dict(self):
        """Convert model to dictionary"""
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
            'updated_date': self.updated_date.isoformat() if self.updated_date else None
        }


class UnderwritingApplication(Base):
    """Underwriting applications table"""
    __tablename__ = 'underwriting_applications'
    
    id = Column(String(50), primary_key=True)
    policy_id = Column(String(50), index=True)
    customer_id = Column(String(50), index=True)
    status = Column(String(50), default='pending')
    risk_assessment = Column(String(20))  # low, medium, high, very_high
    medical_exam_required = Column(Boolean, default=False)
    additional_documents_required = Column(Boolean, default=False)
    notes = Column(Text)
    submitted_date = Column(DateTime, default=datetime.utcnow, nullable=False)
    decision_date = Column(DateTime)
    decided_by = Column(String(100))  # Username of underwriter
    created_date = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_date = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def to_dict(self):
        """Convert model to dictionary"""
        return {
            'id': self.id,
            'policy_id': self.policy_id,
            'customer_id': self.customer_id,
            'status': self.status,
            'risk_assessment': self.risk_assessment,
            'medical_exam_required': self.medical_exam_required,
            'additional_documents_required': self.additional_documents_required,
            'notes': self.notes,
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
    """User accounts table (for staff/admin access)"""
    __tablename__ = 'users'
    
    username = Column(String(100), primary_key=True)
    password_hash = Column(String(255), nullable=False)
    password_salt = Column(String(255), nullable=False)
    role = Column(String(50), nullable=False)  # admin, underwriter, claims, accountant, etc.
    name = Column(String(200))
    email = Column(String(254))
    active = Column(Boolean, default=True)
    created_date = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_login = Column(DateTime)
    
    def to_dict(self):
        """Convert model to dictionary (without sensitive fields)"""
        return {
            'username': self.username,
            'role': self.role,
            'name': self.name,
            'email': self.email,
            'active': self.active,
            'created_date': self.created_date.isoformat() if self.created_date else None,
            'last_login': self.last_login.isoformat() if self.last_login else None
        }


class Session(Base):
    """User sessions table"""
    __tablename__ = 'sessions'
    
    token = Column(String(100), primary_key=True)
    username = Column(String(100), index=True)
    customer_id = Column(String(50), index=True)
    ip_address = Column(String(45))  # Support IPv6
    expires = Column(DateTime, nullable=False, index=True)
    created_date = Column(DateTime, default=datetime.utcnow, nullable=False)
    
    def to_dict(self):
        """Convert model to dictionary"""
        return {
            'token': self.token,
            'username': self.username,
            'customer_id': self.customer_id,
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
    # NOTE: "metadata" is a reserved attribute name in SQLAlchemy's Declarative API.
    # Keep the DB column name as "metadata" for compatibility, but map it to a safe
    # Python attribute name.
    metadata_json = Column("metadata", Text, nullable=True)  # JSON string
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
            "metadata": self.metadata_json,
            "classification": self.classification,
            "created_by": self.created_by,
            "created_date": self.created_date.isoformat() if self.created_date else None,
        }
