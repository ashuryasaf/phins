"""
SQLAlchemy ORM Models for Sully Chain - Supplier Management & Allocation System

These models define the database schema for:
- Supplier registry and management (lawyers, doctors, medical services, reinsurance, banks, etc.)
- Allocation-based bidding system
- Immutable ledger for all transactions
- AI/BI analytics and scoring

Integrates with the PHINS Insurance Platform via shared Customer and Policy references.
"""

from sqlalchemy import Column, String, Integer, Float, DateTime, Boolean, Text, ForeignKey, Index, Numeric
from sqlalchemy.orm import relationship
from datetime import datetime
import enum
import json as json_module

# Import Base from the main models to ensure shared metadata
from database.models import Base


# ============================================================================
# Enumerations
# ============================================================================

class SupplierType(str, enum.Enum):
    """Supplier type classification"""
    LEGAL = "legal"                    # Lawyers, legal firms
    DOCTOR = "doctor"                  # Individual doctors
    MEDICAL_SERVICE = "medical_service"  # Hospitals, clinics, labs
    PHARMACY = "pharmacy"              # Pharmacies, drug stores
    MEDICAL_EQUIPMENT = "medical_equipment"  # Medical device suppliers
    REINSURANCE = "reinsurance"        # Reinsurance companies
    BANKING = "banking"                # Banks, financial institutions
    TRADING = "trading"                # Trading companies
    DELIVERY = "delivery"              # Delivery services
    TRANSPORTATION = "transportation"  # Transportation providers
    INVESTIGATION = "investigation"    # Fraud investigation, claims adjusters
    REHABILITATION = "rehabilitation"  # Rehabilitation centers
    MENTAL_HEALTH = "mental_health"    # Psychologists, counselors
    DENTAL = "dental"                  # Dental services
    OPTICAL = "optical"                # Eye care, opticians
    OTHER = "other"                    # Other service providers


class SupplierStatus(str, enum.Enum):
    """Supplier account status"""
    PENDING_VERIFICATION = "pending_verification"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    INACTIVE = "inactive"
    BLACKLISTED = "blacklisted"


class CredentialStatus(str, enum.Enum):
    """Credential verification status"""
    PENDING = "pending"
    VERIFIED = "verified"
    REJECTED = "rejected"
    EXPIRED = "expired"
    REVOKED = "revoked"


class ServiceRequestStatus(str, enum.Enum):
    """Service request status"""
    DRAFT = "draft"
    SUBMITTED = "submitted"
    ALLOCATION_OPEN = "allocation_open"
    ALLOCATION_CLOSED = "allocation_closed"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    DISPUTED = "disputed"


class AllocationStatus(str, enum.Enum):
    """Allocation status"""
    DRAFT = "draft"
    OPEN = "open"
    BIDDING = "bidding"
    EVALUATION = "evaluation"
    AWARDED = "awarded"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class BidStatus(str, enum.Enum):
    """Bid status"""
    DRAFT = "draft"
    SUBMITTED = "submitted"
    UNDER_REVIEW = "under_review"
    SHORTLISTED = "shortlisted"
    WINNER = "winner"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"


class FulfillmentStatus(str, enum.Enum):
    """Service fulfillment status"""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    DELIVERED = "delivered"
    UNDER_REVIEW = "under_review"
    ACCEPTED = "accepted"
    DISPUTED = "disputed"
    COMPLETED = "completed"
    FAILED = "failed"


class MilestoneStatus(str, enum.Enum):
    """Milestone status"""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    OVERDUE = "overdue"
    SKIPPED = "skipped"


class EscrowStatus(str, enum.Enum):
    """Escrow account status"""
    CREATED = "created"
    FUNDED = "funded"
    PARTIALLY_RELEASED = "partially_released"
    RELEASED = "released"
    REFUNDED = "refunded"
    DISPUTED = "disputed"


class TransactionType(str, enum.Enum):
    """Supplier transaction type"""
    ESCROW_HOLD = "escrow_hold"
    PAYMENT_RECEIVED = "payment_received"
    WITHDRAWAL = "withdrawal"
    REFUND = "refund"
    FEE = "fee"
    ADJUSTMENT = "adjustment"
    BONUS = "bonus"


class LedgerActionType(str, enum.Enum):
    """Ledger action types for audit trail"""
    # Supplier actions
    SUPPLIER_REGISTERED = "supplier_registered"
    SUPPLIER_UPDATED = "supplier_updated"
    SUPPLIER_VERIFIED = "supplier_verified"
    SUPPLIER_SUSPENDED = "supplier_suspended"
    SUPPLIER_ACTIVATED = "supplier_activated"
    CREDENTIAL_ADDED = "credential_added"
    CREDENTIAL_VERIFIED = "credential_verified"
    CREDENTIAL_EXPIRED = "credential_expired"
    
    # Allocation actions
    SERVICE_REQUEST_CREATED = "service_request_created"
    ALLOCATION_CREATED = "allocation_created"
    ALLOCATION_OPENED = "allocation_opened"
    ALLOCATION_CLOSED = "allocation_closed"
    ALLOCATION_CANCELLED = "allocation_cancelled"
    
    # Bidding actions
    BID_SUBMITTED = "bid_submitted"
    BID_UPDATED = "bid_updated"
    BID_WITHDRAWN = "bid_withdrawn"
    BID_SHORTLISTED = "bid_shortlisted"
    WINNER_SELECTED = "winner_selected"
    
    # Fulfillment actions
    FULFILLMENT_STARTED = "fulfillment_started"
    MILESTONE_COMPLETED = "milestone_completed"
    DELIVERABLE_SUBMITTED = "deliverable_submitted"
    SERVICE_COMPLETED = "service_completed"
    SERVICE_DISPUTED = "service_disputed"
    
    # Financial actions
    ESCROW_CREATED = "escrow_created"
    ESCROW_FUNDED = "escrow_funded"
    PAYMENT_RELEASED = "payment_released"
    REFUND_PROCESSED = "refund_processed"
    
    # Rating actions
    RATING_SUBMITTED = "rating_submitted"
    SCORE_UPDATED = "score_updated"
    
    # Client interactions
    CLIENT_INTERACTION = "client_interaction"


class InteractionType(str, enum.Enum):
    """Client interaction type"""
    APPOINTMENT = "appointment"
    CONSULTATION = "consultation"
    PHONE_CALL = "phone_call"
    VIDEO_CALL = "video_call"
    DOCUMENT_EXCHANGE = "document_exchange"
    SERVICE_DELIVERY = "service_delivery"
    FOLLOW_UP = "follow_up"
    COMPLAINT = "complaint"
    FEEDBACK = "feedback"


class UrgencyLevel(str, enum.Enum):
    """Service request urgency level"""
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"
    EMERGENCY = "emergency"


# ============================================================================
# Supplier Models
# ============================================================================

class Supplier(Base):
    """
    Supplier master table - represents all service providers in the Sully Chain ecosystem.
    
    Supports diverse supplier types including legal, medical, financial, logistics, etc.
    Each supplier can have multiple specialties and credentials.
    """
    __tablename__ = 'sully_suppliers'
    
    id = Column(String(50), primary_key=True)
    supplier_code = Column(String(50), unique=True, nullable=False, index=True)
    name = Column(String(200), nullable=False)
    supplier_type = Column(String(50), nullable=False, index=True)  # SupplierType enum
    
    # Registration & Legal
    registration_number = Column(String(100), index=True)
    tax_id = Column(String(50))
    legal_entity_type = Column(String(50))  # individual, company, partnership, etc.
    
    # Contact Information
    email = Column(String(254), unique=True, nullable=False, index=True)
    phone = Column(String(20))
    secondary_phone = Column(String(20))
    website = Column(String(500))
    
    # Address
    address_line1 = Column(String(200))
    address_line2 = Column(String(200))
    city = Column(String(100))
    state = Column(String(100))
    country = Column(String(100), default='USA')
    postal_code = Column(String(20))
    
    # Account Status
    status = Column(String(50), default=SupplierStatus.PENDING_VERIFICATION.value, index=True)
    verification_date = Column(DateTime)
    verified_by = Column(String(100))
    
    # Performance Metrics (cached from SupplierScore)
    rating = Column(Float, default=0.0)
    total_allocations = Column(Integer, default=0)
    successful_completions = Column(Integer, default=0)
    
    # Financial
    wallet_balance = Column(Numeric(15, 2), default=0.00)
    currency = Column(String(10), default='USD')
    
    # JSON fields stored as text
    credentials_summary = Column(Text)  # Quick reference JSON
    service_areas = Column(Text)  # Geographic coverage JSON
    operating_hours = Column(Text)  # Business hours JSON
    metadata = Column(Text)  # Additional metadata JSON
    
    # Timestamps
    registered_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_active_at = Column(DateTime, default=datetime.utcnow)
    created_date = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_date = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    specialties = relationship("SupplierSpecialty", back_populates="supplier", cascade="all, delete-orphan")
    credentials = relationship("SupplierCredential", back_populates="supplier", cascade="all, delete-orphan")
    bids = relationship("Bid", back_populates="supplier", cascade="all, delete-orphan")
    fulfillments = relationship("ServiceFulfillment", back_populates="supplier", cascade="all, delete-orphan")
    transactions = relationship("SupplierTransaction", back_populates="supplier", cascade="all, delete-orphan")
    scores = relationship("SupplierScore", back_populates="supplier", cascade="all, delete-orphan")
    interactions = relationship("ClientInteraction", back_populates="supplier", cascade="all, delete-orphan")
    
    # Composite indexes for common queries
    __table_args__ = (
        Index('ix_supplier_type_status', 'supplier_type', 'status'),
        Index('ix_supplier_rating', 'rating', 'total_allocations'),
    )
    
    def to_dict(self, include_sensitive: bool = False):
        """Convert model to dictionary"""
        def safe_json_loads(val):
            if val is None:
                return {}
            if isinstance(val, (dict, list)):
                return val
            try:
                return json_module.loads(val)
            except:
                return {}
        
        data = {
            'id': self.id,
            'supplier_code': self.supplier_code,
            'name': self.name,
            'supplier_type': self.supplier_type,
            'registration_number': self.registration_number,
            'legal_entity_type': self.legal_entity_type,
            'email': self.email,
            'phone': self.phone,
            'website': self.website,
            'address': {
                'line1': self.address_line1,
                'line2': self.address_line2,
                'city': self.city,
                'state': self.state,
                'country': self.country,
                'postal_code': self.postal_code
            },
            'status': self.status,
            'verification_date': self.verification_date.isoformat() if self.verification_date else None,
            'rating': float(self.rating) if self.rating else 0.0,
            'total_allocations': self.total_allocations,
            'successful_completions': self.successful_completions,
            'wallet_balance': float(self.wallet_balance) if self.wallet_balance else 0.0,
            'currency': self.currency,
            'service_areas': safe_json_loads(self.service_areas),
            'operating_hours': safe_json_loads(self.operating_hours),
            'registered_at': self.registered_at.isoformat() if self.registered_at else None,
            'last_active_at': self.last_active_at.isoformat() if self.last_active_at else None
        }
        
        if include_sensitive:
            data['tax_id'] = self.tax_id
            data['credentials_summary'] = safe_json_loads(self.credentials_summary)
            data['metadata'] = safe_json_loads(self.metadata)
        
        return data


class SupplierSpecialty(Base):
    """
    Supplier specializations - tracks specific expertise areas for each supplier.
    Doctors have medical specialties, lawyers have practice areas, etc.
    """
    __tablename__ = 'sully_supplier_specialties'
    
    id = Column(String(50), primary_key=True)
    supplier_id = Column(String(50), ForeignKey('sully_suppliers.id', ondelete='CASCADE'), nullable=False, index=True)
    
    specialty_code = Column(String(50), nullable=False, index=True)
    specialty_name = Column(String(200), nullable=False)
    specialty_category = Column(String(100))  # E.g., "Surgery", "Criminal Law", "Equipment"
    
    certification_level = Column(String(50))  # board_certified, licensed, registered, etc.
    certified_date = Column(DateTime)
    certified_until = Column(DateTime)
    certifying_body = Column(String(200))
    certificate_number = Column(String(100))
    
    is_primary = Column(Boolean, default=False)
    years_experience = Column(Integer)
    
    created_date = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_date = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    supplier = relationship("Supplier", back_populates="specialties")
    
    __table_args__ = (
        Index('ix_specialty_supplier_code', 'supplier_id', 'specialty_code'),
    )
    
    def to_dict(self):
        return {
            'id': self.id,
            'supplier_id': self.supplier_id,
            'specialty_code': self.specialty_code,
            'specialty_name': self.specialty_name,
            'specialty_category': self.specialty_category,
            'certification_level': self.certification_level,
            'certified_date': self.certified_date.isoformat() if self.certified_date else None,
            'certified_until': self.certified_until.isoformat() if self.certified_until else None,
            'certifying_body': self.certifying_body,
            'is_primary': self.is_primary,
            'years_experience': self.years_experience
        }


class SupplierCredential(Base):
    """
    Supplier credentials - licenses, certifications, insurance, etc.
    Tracks all professional credentials required to operate.
    """
    __tablename__ = 'sully_supplier_credentials'
    
    id = Column(String(50), primary_key=True)
    supplier_id = Column(String(50), ForeignKey('sully_suppliers.id', ondelete='CASCADE'), nullable=False, index=True)
    
    credential_type = Column(String(50), nullable=False, index=True)  # license, certification, insurance, permit
    credential_name = Column(String(200), nullable=False)
    credential_number = Column(String(100))
    
    issuing_authority = Column(String(200))
    issuing_country = Column(String(100))
    issuing_state = Column(String(100))
    
    issued_date = Column(DateTime)
    expiry_date = Column(DateTime, index=True)
    
    verification_status = Column(String(50), default=CredentialStatus.PENDING.value, index=True)
    verified_date = Column(DateTime)
    verified_by = Column(String(100))
    verification_notes = Column(Text)
    
    document_url = Column(String(500))  # S3/storage reference
    document_hash = Column(String(100))  # For integrity verification
    
    created_date = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_date = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    supplier = relationship("Supplier", back_populates="credentials")
    
    __table_args__ = (
        Index('ix_credential_expiry_status', 'expiry_date', 'verification_status'),
    )
    
    def to_dict(self):
        return {
            'id': self.id,
            'supplier_id': self.supplier_id,
            'credential_type': self.credential_type,
            'credential_name': self.credential_name,
            'credential_number': self.credential_number,
            'issuing_authority': self.issuing_authority,
            'issuing_country': self.issuing_country,
            'issuing_state': self.issuing_state,
            'issued_date': self.issued_date.isoformat() if self.issued_date else None,
            'expiry_date': self.expiry_date.isoformat() if self.expiry_date else None,
            'verification_status': self.verification_status,
            'verified_date': self.verified_date.isoformat() if self.verified_date else None,
            'document_url': self.document_url
        }


# ============================================================================
# Service Request & Allocation Models
# ============================================================================

class ServiceRequest(Base):
    """
    Service request - represents a need for external service from a supplier.
    Originated from policies, claims, or direct customer requests.
    """
    __tablename__ = 'sully_service_requests'
    
    id = Column(String(50), primary_key=True)
    request_code = Column(String(50), unique=True, nullable=False, index=True)
    
    # Origin reference (PHINS integration)
    customer_id = Column(String(50), index=True)  # References customers.id
    policy_id = Column(String(50), index=True)    # References policies.id
    claim_id = Column(String(50), index=True)     # References claims.id
    
    # Request details
    service_type = Column(String(50), nullable=False, index=True)  # SupplierType for matching
    service_category = Column(String(100))  # More specific category
    title = Column(String(300), nullable=False)
    description = Column(Text)
    
    # Requirements
    requirements = Column(Text)  # JSON: specific requirements
    required_credentials = Column(Text)  # JSON: required supplier credentials
    location_requirements = Column(Text)  # JSON: geographic requirements
    
    # Urgency and timing
    urgency_level = Column(String(20), default=UrgencyLevel.NORMAL.value, index=True)
    requested_date = Column(DateTime)  # When service is needed
    deadline = Column(DateTime)        # Latest acceptable date
    
    # Financial
    estimated_value = Column(Numeric(15, 2))
    budget_min = Column(Numeric(15, 2))
    budget_max = Column(Numeric(15, 2))
    currency = Column(String(10), default='USD')
    
    # Status tracking
    status = Column(String(50), default=ServiceRequestStatus.DRAFT.value, index=True)
    assigned_supplier_id = Column(String(50), ForeignKey('sully_suppliers.id'), index=True)
    
    # Requester info
    requester_id = Column(String(100))  # User or customer who created the request
    requester_type = Column(String(20))  # 'user' or 'customer'
    
    # Timestamps
    request_date = Column(DateTime, default=datetime.utcnow, nullable=False)
    created_date = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_date = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    allocations = relationship("Allocation", back_populates="service_request", cascade="all, delete-orphan")
    interactions = relationship("ClientInteraction", back_populates="service_request", cascade="all, delete-orphan")
    
    __table_args__ = (
        Index('ix_request_customer_status', 'customer_id', 'status'),
        Index('ix_request_service_urgency', 'service_type', 'urgency_level'),
    )
    
    def to_dict(self):
        def safe_json_loads(val):
            if val is None:
                return {}
            if isinstance(val, (dict, list)):
                return val
            try:
                return json_module.loads(val)
            except:
                return {}
        
        return {
            'id': self.id,
            'request_code': self.request_code,
            'customer_id': self.customer_id,
            'policy_id': self.policy_id,
            'claim_id': self.claim_id,
            'service_type': self.service_type,
            'service_category': self.service_category,
            'title': self.title,
            'description': self.description,
            'requirements': safe_json_loads(self.requirements),
            'required_credentials': safe_json_loads(self.required_credentials),
            'urgency_level': self.urgency_level,
            'requested_date': self.requested_date.isoformat() if self.requested_date else None,
            'deadline': self.deadline.isoformat() if self.deadline else None,
            'estimated_value': float(self.estimated_value) if self.estimated_value else None,
            'budget_min': float(self.budget_min) if self.budget_min else None,
            'budget_max': float(self.budget_max) if self.budget_max else None,
            'status': self.status,
            'assigned_supplier_id': self.assigned_supplier_id,
            'request_date': self.request_date.isoformat() if self.request_date else None
        }


class Allocation(Base):
    """
    Allocation - represents a bidding opportunity created from a service request.
    Eligible suppliers can submit bids during the open period.
    """
    __tablename__ = 'sully_allocations'
    
    id = Column(String(50), primary_key=True)
    allocation_code = Column(String(50), unique=True, nullable=False, index=True)
    service_request_id = Column(String(50), ForeignKey('sully_service_requests.id', ondelete='CASCADE'), nullable=False, index=True)
    
    # Allocation type
    allocation_type = Column(String(50), default='competitive')  # competitive, direct, emergency
    
    # Status and timing
    status = Column(String(50), default=AllocationStatus.DRAFT.value, index=True)
    opened_at = Column(DateTime)
    closes_at = Column(DateTime, index=True)
    awarded_at = Column(DateTime)
    
    # Pricing
    reserve_price = Column(Numeric(15, 2))  # Minimum acceptable price
    max_price = Column(Numeric(15, 2))      # Maximum budget
    currency = Column(String(10), default='USD')
    
    # Eligibility criteria
    eligible_supplier_types = Column(Text)  # JSON array of SupplierType
    eligible_criteria = Column(Text)        # JSON: detailed eligibility rules
    required_rating = Column(Float, default=0.0)
    
    # Bid tracking
    bid_count = Column(Integer, default=0)
    view_count = Column(Integer, default=0)
    
    # Winner
    winning_bid_id = Column(String(50), index=True)
    winning_supplier_id = Column(String(50), ForeignKey('sully_suppliers.id'), index=True)
    final_amount = Column(Numeric(15, 2))
    
    # Administrator
    created_by = Column(String(100))
    awarded_by = Column(String(100))
    
    # Timestamps
    created_date = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_date = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    service_request = relationship("ServiceRequest", back_populates="allocations")
    bids = relationship("Bid", back_populates="allocation", cascade="all, delete-orphan")
    fulfillment = relationship("ServiceFulfillment", back_populates="allocation", uselist=False)
    escrow = relationship("EscrowAccount", back_populates="allocation", uselist=False)
    analytics = relationship("AllocationAnalytics", back_populates="allocation", uselist=False)
    
    __table_args__ = (
        Index('ix_allocation_status_closes', 'status', 'closes_at'),
    )
    
    def to_dict(self):
        def safe_json_loads(val):
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
            'allocation_code': self.allocation_code,
            'service_request_id': self.service_request_id,
            'allocation_type': self.allocation_type,
            'status': self.status,
            'opened_at': self.opened_at.isoformat() if self.opened_at else None,
            'closes_at': self.closes_at.isoformat() if self.closes_at else None,
            'awarded_at': self.awarded_at.isoformat() if self.awarded_at else None,
            'reserve_price': float(self.reserve_price) if self.reserve_price else None,
            'max_price': float(self.max_price) if self.max_price else None,
            'eligible_supplier_types': safe_json_loads(self.eligible_supplier_types),
            'required_rating': self.required_rating,
            'bid_count': self.bid_count,
            'view_count': self.view_count,
            'winning_bid_id': self.winning_bid_id,
            'winning_supplier_id': self.winning_supplier_id,
            'final_amount': float(self.final_amount) if self.final_amount else None
        }


class Bid(Base):
    """
    Bid - represents a supplier's proposal for an allocation.
    Contains pricing, deliverables, and timeline.
    """
    __tablename__ = 'sully_bids'
    
    id = Column(String(50), primary_key=True)
    bid_code = Column(String(50), unique=True, nullable=False, index=True)
    allocation_id = Column(String(50), ForeignKey('sully_allocations.id', ondelete='CASCADE'), nullable=False, index=True)
    supplier_id = Column(String(50), ForeignKey('sully_suppliers.id', ondelete='CASCADE'), nullable=False, index=True)
    
    # Bid details
    bid_amount = Column(Numeric(15, 2), nullable=False)
    currency = Column(String(10), default='USD')
    
    # Proposal
    proposal_summary = Column(String(500))
    proposal_details = Column(Text)  # Full proposal text
    deliverables = Column(Text)      # JSON: list of deliverables
    
    # Timeline
    estimated_days = Column(Integer)
    proposed_start_date = Column(DateTime)
    proposed_end_date = Column(DateTime)
    
    # Status
    status = Column(String(50), default=BidStatus.DRAFT.value, index=True)
    submitted_at = Column(DateTime)
    
    # Scoring
    supplier_rating_at_bid = Column(Float)  # Snapshot of supplier rating when bid was submitted
    ai_score = Column(Float)                # AI-generated bid quality score
    manual_score = Column(Float)            # Manual evaluation score
    final_rank = Column(Integer)            # Final ranking in allocation
    
    # Review
    reviewed_by = Column(String(100))
    reviewed_at = Column(DateTime)
    review_notes = Column(Text)
    
    # Timestamps
    created_date = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_date = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    allocation = relationship("Allocation", back_populates="bids")
    supplier = relationship("Supplier", back_populates="bids")
    
    __table_args__ = (
        Index('ix_bid_allocation_supplier', 'allocation_id', 'supplier_id'),
        Index('ix_bid_status_score', 'status', 'ai_score'),
    )
    
    def to_dict(self):
        def safe_json_loads(val):
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
            'bid_code': self.bid_code,
            'allocation_id': self.allocation_id,
            'supplier_id': self.supplier_id,
            'bid_amount': float(self.bid_amount) if self.bid_amount else None,
            'proposal_summary': self.proposal_summary,
            'deliverables': safe_json_loads(self.deliverables),
            'estimated_days': self.estimated_days,
            'proposed_start_date': self.proposed_start_date.isoformat() if self.proposed_start_date else None,
            'proposed_end_date': self.proposed_end_date.isoformat() if self.proposed_end_date else None,
            'status': self.status,
            'submitted_at': self.submitted_at.isoformat() if self.submitted_at else None,
            'supplier_rating_at_bid': self.supplier_rating_at_bid,
            'ai_score': self.ai_score,
            'final_rank': self.final_rank
        }


# ============================================================================
# Fulfillment Models
# ============================================================================

class ServiceFulfillment(Base):
    """
    Service fulfillment - tracks the execution of awarded allocations.
    Includes milestones, deliverables, and completion status.
    """
    __tablename__ = 'sully_service_fulfillments'
    
    id = Column(String(50), primary_key=True)
    fulfillment_code = Column(String(50), unique=True, nullable=False, index=True)
    allocation_id = Column(String(50), ForeignKey('sully_allocations.id', ondelete='CASCADE'), nullable=False, index=True)
    supplier_id = Column(String(50), ForeignKey('sully_suppliers.id', ondelete='CASCADE'), nullable=False, index=True)
    customer_id = Column(String(50), index=True)  # References customers.id
    
    # Status
    status = Column(String(50), default=FulfillmentStatus.PENDING.value, index=True)
    
    # Timeline
    started_at = Column(DateTime)
    expected_completion = Column(DateTime)
    completed_at = Column(DateTime)
    
    # Deliverables
    deliverables_submitted = Column(Text)  # JSON: submitted deliverables
    deliverables_accepted = Column(Text)   # JSON: accepted deliverables
    
    # Financial
    contracted_amount = Column(Numeric(15, 2))
    final_amount = Column(Numeric(15, 2))
    adjustments = Column(Text)  # JSON: price adjustments with reasons
    
    # Quality
    quality_score = Column(Float)
    customer_rating = Column(Float)
    customer_feedback = Column(Text)
    
    # Notes
    notes = Column(Text)
    completion_notes = Column(Text)
    
    # Timestamps
    created_date = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_date = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    allocation = relationship("Allocation", back_populates="fulfillment")
    supplier = relationship("Supplier", back_populates="fulfillments")
    milestones = relationship("ServiceMilestone", back_populates="fulfillment", cascade="all, delete-orphan")
    
    def to_dict(self):
        def safe_json_loads(val):
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
            'fulfillment_code': self.fulfillment_code,
            'allocation_id': self.allocation_id,
            'supplier_id': self.supplier_id,
            'customer_id': self.customer_id,
            'status': self.status,
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'expected_completion': self.expected_completion.isoformat() if self.expected_completion else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'deliverables_submitted': safe_json_loads(self.deliverables_submitted),
            'deliverables_accepted': safe_json_loads(self.deliverables_accepted),
            'contracted_amount': float(self.contracted_amount) if self.contracted_amount else None,
            'final_amount': float(self.final_amount) if self.final_amount else None,
            'quality_score': self.quality_score,
            'customer_rating': self.customer_rating,
            'customer_feedback': self.customer_feedback
        }


class ServiceMilestone(Base):
    """
    Service milestone - tracks individual milestones within a fulfillment.
    Enables progress tracking and partial payments.
    """
    __tablename__ = 'sully_service_milestones'
    
    id = Column(String(50), primary_key=True)
    fulfillment_id = Column(String(50), ForeignKey('sully_service_fulfillments.id', ondelete='CASCADE'), nullable=False, index=True)
    
    milestone_name = Column(String(200), nullable=False)
    description = Column(Text)
    sequence_order = Column(Integer, nullable=False)
    
    # Status
    status = Column(String(50), default=MilestoneStatus.PENDING.value, index=True)
    
    # Timeline
    due_date = Column(DateTime)
    started_date = Column(DateTime)
    completed_date = Column(DateTime)
    
    # Financial
    milestone_amount = Column(Numeric(15, 2))
    payment_released = Column(Boolean, default=False)
    
    # Deliverables
    deliverables = Column(Text)  # JSON: expected deliverables
    submitted_deliverables = Column(Text)  # JSON: submitted items
    
    # Approval
    approved_by = Column(String(100))
    approved_at = Column(DateTime)
    approval_notes = Column(Text)
    
    # Timestamps
    created_date = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_date = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    fulfillment = relationship("ServiceFulfillment", back_populates="milestones")
    
    def to_dict(self):
        return {
            'id': self.id,
            'fulfillment_id': self.fulfillment_id,
            'milestone_name': self.milestone_name,
            'description': self.description,
            'sequence_order': self.sequence_order,
            'status': self.status,
            'due_date': self.due_date.isoformat() if self.due_date else None,
            'completed_date': self.completed_date.isoformat() if self.completed_date else None,
            'milestone_amount': float(self.milestone_amount) if self.milestone_amount else None,
            'payment_released': self.payment_released
        }


# ============================================================================
# Ledger & Audit Models
# ============================================================================

class SullyLedger(Base):
    """
    Sully Ledger - immutable audit trail for all Sully Chain actions.
    Implements blockchain-style hashing for integrity verification.
    """
    __tablename__ = 'sully_ledger'
    
    id = Column(String(50), primary_key=True)
    ledger_code = Column(String(50), unique=True, nullable=False, index=True)
    sequence_number = Column(Integer, nullable=False, index=True)  # Auto-incrementing for ordering
    
    # Entity reference
    entity_type = Column(String(50), nullable=False, index=True)  # supplier, allocation, bid, etc.
    entity_id = Column(String(50), nullable=False, index=True)
    
    # Action details
    action_type = Column(String(50), nullable=False, index=True)  # LedgerActionType enum
    action_description = Column(String(500))
    
    # Actor information
    actor_id = Column(String(100), nullable=False, index=True)
    actor_type = Column(String(20), nullable=False)  # user, supplier, customer, system
    actor_name = Column(String(200))
    
    # State tracking
    previous_state = Column(Text)  # JSON: state before action
    new_state = Column(Text)       # JSON: state after action
    changes = Column(Text)         # JSON: diff of changes
    
    # Metadata
    metadata = Column(Text)  # JSON: additional context (IP, user agent, etc.)
    
    # Integrity
    hash = Column(String(64), nullable=False, index=True)  # SHA-256 hash
    previous_hash = Column(String(64), index=True)         # Hash of previous entry
    
    # Blockchain anchoring (optional)
    nft_token_id = Column(String(100))
    blockchain_tx = Column(String(100))
    anchored_at = Column(DateTime)
    
    # Timestamp
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    
    __table_args__ = (
        Index('ix_ledger_entity', 'entity_type', 'entity_id'),
        Index('ix_ledger_actor', 'actor_type', 'actor_id'),
        Index('ix_ledger_action_time', 'action_type', 'timestamp'),
    )
    
    def to_dict(self):
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
            'ledger_code': self.ledger_code,
            'sequence_number': self.sequence_number,
            'entity_type': self.entity_type,
            'entity_id': self.entity_id,
            'action_type': self.action_type,
            'action_description': self.action_description,
            'actor_id': self.actor_id,
            'actor_type': self.actor_type,
            'actor_name': self.actor_name,
            'previous_state': safe_json_loads(self.previous_state),
            'new_state': safe_json_loads(self.new_state),
            'changes': safe_json_loads(self.changes),
            'metadata': safe_json_loads(self.metadata),
            'hash': self.hash,
            'previous_hash': self.previous_hash,
            'nft_token_id': self.nft_token_id,
            'blockchain_tx': self.blockchain_tx,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None
        }


class ClientInteraction(Base):
    """
    Client interaction - tracks all interactions between customers and suppliers.
    Provides complete history for customer service and dispute resolution.
    """
    __tablename__ = 'sully_client_interactions'
    
    id = Column(String(50), primary_key=True)
    
    # References
    customer_id = Column(String(50), nullable=False, index=True)
    supplier_id = Column(String(50), ForeignKey('sully_suppliers.id', ondelete='SET NULL'), index=True)
    service_request_id = Column(String(50), ForeignKey('sully_service_requests.id', ondelete='SET NULL'), index=True)
    fulfillment_id = Column(String(50), index=True)
    
    # Interaction details
    interaction_type = Column(String(50), nullable=False, index=True)  # InteractionType enum
    interaction_date = Column(DateTime, default=datetime.utcnow, nullable=False)
    duration_minutes = Column(Integer)
    
    # Content
    summary = Column(String(500))
    details = Column(Text)
    notes = Column(Text)
    
    # Outcomes
    outcome = Column(String(100))
    action_items = Column(Text)  # JSON: list of action items
    follow_up_required = Column(Boolean, default=False)
    follow_up_date = Column(DateTime)
    
    # Satisfaction
    satisfaction_score = Column(Integer)  # 1-5 scale
    feedback = Column(Text)
    
    # Tracking
    recorded_by = Column(String(100))
    
    # Timestamps
    created_date = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_date = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    supplier = relationship("Supplier", back_populates="interactions")
    service_request = relationship("ServiceRequest", back_populates="interactions")
    
    __table_args__ = (
        Index('ix_interaction_customer_date', 'customer_id', 'interaction_date'),
    )
    
    def to_dict(self):
        return {
            'id': self.id,
            'customer_id': self.customer_id,
            'supplier_id': self.supplier_id,
            'service_request_id': self.service_request_id,
            'fulfillment_id': self.fulfillment_id,
            'interaction_type': self.interaction_type,
            'interaction_date': self.interaction_date.isoformat() if self.interaction_date else None,
            'duration_minutes': self.duration_minutes,
            'summary': self.summary,
            'details': self.details,
            'outcome': self.outcome,
            'satisfaction_score': self.satisfaction_score,
            'feedback': self.feedback,
            'follow_up_required': self.follow_up_required
        }


# ============================================================================
# Financial Models
# ============================================================================

class SupplierTransaction(Base):
    """
    Supplier transaction - tracks all financial transactions for suppliers.
    Includes escrow holds, payments, withdrawals, and fees.
    """
    __tablename__ = 'sully_supplier_transactions'
    
    id = Column(String(50), primary_key=True)
    transaction_code = Column(String(50), unique=True, nullable=False, index=True)
    
    # References
    supplier_id = Column(String(50), ForeignKey('sully_suppliers.id', ondelete='CASCADE'), nullable=False, index=True)
    allocation_id = Column(String(50), index=True)
    escrow_id = Column(String(50), index=True)
    
    # Transaction details
    transaction_type = Column(String(50), nullable=False, index=True)  # TransactionType enum
    
    # Financial
    amount = Column(Numeric(15, 2), nullable=False)
    currency = Column(String(10), default='USD')
    fee_amount = Column(Numeric(15, 2), default=0.00)
    net_amount = Column(Numeric(15, 2))
    
    # Before/after balance
    balance_before = Column(Numeric(15, 2))
    balance_after = Column(Numeric(15, 2))
    
    # Status
    status = Column(String(50), default='completed', index=True)
    
    # Payment details
    payment_method = Column(String(50))
    reference_number = Column(String(100))
    external_transaction_id = Column(String(200))
    
    # Notes
    description = Column(String(500))
    notes = Column(Text)
    
    # Timestamps
    transaction_date = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    created_date = Column(DateTime, default=datetime.utcnow, nullable=False)
    
    # Relationships
    supplier = relationship("Supplier", back_populates="transactions")
    
    __table_args__ = (
        Index('ix_transaction_supplier_date', 'supplier_id', 'transaction_date'),
    )
    
    def to_dict(self):
        return {
            'id': self.id,
            'transaction_code': self.transaction_code,
            'supplier_id': self.supplier_id,
            'allocation_id': self.allocation_id,
            'transaction_type': self.transaction_type,
            'amount': float(self.amount) if self.amount else None,
            'currency': self.currency,
            'fee_amount': float(self.fee_amount) if self.fee_amount else None,
            'net_amount': float(self.net_amount) if self.net_amount else None,
            'status': self.status,
            'payment_method': self.payment_method,
            'reference_number': self.reference_number,
            'transaction_date': self.transaction_date.isoformat() if self.transaction_date else None
        }


class EscrowAccount(Base):
    """
    Escrow account - holds funds during service fulfillment.
    Released upon successful completion or refunded upon dispute.
    """
    __tablename__ = 'sully_escrow_accounts'
    
    id = Column(String(50), primary_key=True)
    escrow_code = Column(String(50), unique=True, nullable=False, index=True)
    allocation_id = Column(String(50), ForeignKey('sully_allocations.id', ondelete='CASCADE'), nullable=False, index=True)
    
    # Financial
    held_amount = Column(Numeric(15, 2), nullable=False)
    released_amount = Column(Numeric(15, 2), default=0.00)
    refunded_amount = Column(Numeric(15, 2), default=0.00)
    currency = Column(String(10), default='USD')
    
    # Participants
    payer_type = Column(String(20))  # customer, policy, claim
    payer_id = Column(String(50))
    payee_supplier_id = Column(String(50), ForeignKey('sully_suppliers.id'), index=True)
    
    # Status
    status = Column(String(50), default=EscrowStatus.CREATED.value, index=True)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    funded_at = Column(DateTime)
    released_at = Column(DateTime)
    refunded_at = Column(DateTime)
    
    # Notes
    release_notes = Column(Text)
    
    # Relationships
    allocation = relationship("Allocation", back_populates="escrow")
    
    def to_dict(self):
        return {
            'id': self.id,
            'escrow_code': self.escrow_code,
            'allocation_id': self.allocation_id,
            'held_amount': float(self.held_amount) if self.held_amount else None,
            'released_amount': float(self.released_amount) if self.released_amount else None,
            'refunded_amount': float(self.refunded_amount) if self.refunded_amount else None,
            'status': self.status,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'funded_at': self.funded_at.isoformat() if self.funded_at else None,
            'released_at': self.released_at.isoformat() if self.released_at else None
        }


# ============================================================================
# AI/BI Analytics Models
# ============================================================================

class SupplierScore(Base):
    """
    Supplier score - AI-calculated performance metrics for suppliers.
    Updated periodically based on fulfillment history and feedback.
    """
    __tablename__ = 'sully_supplier_scores'
    
    id = Column(String(50), primary_key=True)
    supplier_id = Column(String(50), ForeignKey('sully_suppliers.id', ondelete='CASCADE'), nullable=False, index=True)
    
    # Individual scores (0-100 scale)
    performance_score = Column(Float, default=50.0)      # Based on completion rate/quality
    reliability_score = Column(Float, default=50.0)      # Based on on-time delivery
    quality_score = Column(Float, default=50.0)          # Based on customer ratings
    price_competitiveness = Column(Float, default=50.0)  # Based on bid pricing
    response_time_score = Column(Float, default=50.0)    # Based on response times
    compliance_score = Column(Float, default=50.0)       # Based on credential status
    
    # Overall score
    overall_score = Column(Float, default=50.0, index=True)
    performance_tier = Column(String(20))  # platinum, gold, silver, bronze, standard
    
    # Score breakdown (detailed JSON)
    score_breakdown = Column(Text)  # JSON with detailed metrics
    
    # Trends
    score_trend = Column(String(20))  # improving, stable, declining
    previous_score = Column(Float)
    score_change = Column(Float)
    
    # Metadata
    data_points_used = Column(Integer)
    calculation_version = Column(String(20))
    
    # Timestamps
    calculated_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    valid_until = Column(DateTime)
    
    # Relationships
    supplier = relationship("Supplier", back_populates="scores")
    
    def to_dict(self):
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
            'supplier_id': self.supplier_id,
            'performance_score': self.performance_score,
            'reliability_score': self.reliability_score,
            'quality_score': self.quality_score,
            'price_competitiveness': self.price_competitiveness,
            'response_time_score': self.response_time_score,
            'compliance_score': self.compliance_score,
            'overall_score': self.overall_score,
            'performance_tier': self.performance_tier,
            'score_breakdown': safe_json_loads(self.score_breakdown),
            'score_trend': self.score_trend,
            'calculated_at': self.calculated_at.isoformat() if self.calculated_at else None
        }


class AllocationAnalytics(Base):
    """
    Allocation analytics - metrics and insights for each allocation.
    Used for reporting and AI training.
    """
    __tablename__ = 'sully_allocation_analytics'
    
    id = Column(String(50), primary_key=True)
    allocation_id = Column(String(50), ForeignKey('sully_allocations.id', ondelete='CASCADE'), nullable=False, index=True)
    
    # Participation metrics
    total_views = Column(Integer, default=0)
    unique_viewers = Column(Integer, default=0)
    total_bids = Column(Integer, default=0)
    qualified_bids = Column(Integer, default=0)
    
    # Pricing metrics
    avg_bid_amount = Column(Numeric(15, 2))
    min_bid_amount = Column(Numeric(15, 2))
    max_bid_amount = Column(Numeric(15, 2))
    winning_bid_amount = Column(Numeric(15, 2))
    reserve_price = Column(Numeric(15, 2))
    
    # Efficiency metrics
    price_efficiency = Column(Float)  # winning / reserve
    competition_ratio = Column(Float)  # bids / views
    time_to_first_bid_hours = Column(Float)
    time_to_award_hours = Column(Float)
    
    # Supplier demographics
    supplier_demographics = Column(Text)  # JSON: breakdown by type, rating, etc.
    
    # Outcome
    outcome_success = Column(Boolean)
    fulfillment_score = Column(Float)
    
    # Timestamps
    analyzed_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    
    # Relationships
    allocation = relationship("Allocation", back_populates="analytics")
    
    def to_dict(self):
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
            'allocation_id': self.allocation_id,
            'total_views': self.total_views,
            'total_bids': self.total_bids,
            'qualified_bids': self.qualified_bids,
            'avg_bid_amount': float(self.avg_bid_amount) if self.avg_bid_amount else None,
            'winning_bid_amount': float(self.winning_bid_amount) if self.winning_bid_amount else None,
            'price_efficiency': self.price_efficiency,
            'competition_ratio': self.competition_ratio,
            'time_to_award_hours': self.time_to_award_hours,
            'supplier_demographics': safe_json_loads(self.supplier_demographics),
            'outcome_success': self.outcome_success,
            'fulfillment_score': self.fulfillment_score
        }


# ============================================================================
# Helper function to get all Sully Chain models
# ============================================================================

def get_sully_chain_models():
    """Returns list of all Sully Chain model classes for migration/setup"""
    return [
        Supplier,
        SupplierSpecialty,
        SupplierCredential,
        ServiceRequest,
        Allocation,
        Bid,
        ServiceFulfillment,
        ServiceMilestone,
        SullyLedger,
        ClientInteraction,
        SupplierTransaction,
        EscrowAccount,
        SupplierScore,
        AllocationAnalytics
    ]
