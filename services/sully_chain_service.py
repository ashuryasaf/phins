"""
Sully Chain Service Layer

Comprehensive service layer for the Sully Chain supplier management and allocation system.
Provides business logic for:
- Supplier registration and management
- Service request and allocation workflows
- Bidding and winner selection
- Fulfillment tracking
- Immutable ledger operations
- Escrow and payment management
- AI-powered scoring and analytics
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any, Tuple
from decimal import Decimal
from enum import Enum
import uuid
import hashlib
import json
import logging

# Database imports
from database import get_db_session
from database.sully_chain_models import (
    Supplier, SupplierSpecialty, SupplierCredential,
    ServiceRequest, Allocation, Bid,
    ServiceFulfillment, ServiceMilestone,
    SullyLedger, ClientInteraction,
    SupplierTransaction, EscrowAccount,
    SupplierScore, AllocationAnalytics,
    SupplierType, SupplierStatus, AllocationStatus, BidStatus,
    FulfillmentStatus, EscrowStatus, TransactionType, LedgerActionType,
    CredentialStatus, UrgencyLevel
)
from database.repositories.sully_chain_repository import (
    SupplierRepository, SupplierSpecialtyRepository, SupplierCredentialRepository,
    ServiceRequestRepository, AllocationRepository, BidRepository,
    ServiceFulfillmentRepository, ServiceMilestoneRepository,
    SullyLedgerRepository, ClientInteractionRepository,
    SupplierTransactionRepository, EscrowAccountRepository,
    SupplierScoreRepository, AllocationAnalyticsRepository
)

logger = logging.getLogger(__name__)


# =============================================================================
# Data Transfer Objects (DTOs)
# =============================================================================

@dataclass
class SupplierRegistration:
    """DTO for supplier registration"""
    name: str
    supplier_type: str
    email: str
    phone: str = ""
    registration_number: str = ""
    tax_id: str = ""
    legal_entity_type: str = "company"
    address_line1: str = ""
    address_line2: str = ""
    city: str = ""
    state: str = ""
    country: str = "USA"
    postal_code: str = ""
    website: str = ""
    service_areas: List[str] = field(default_factory=list)
    operating_hours: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SpecialtyData:
    """DTO for specialty information"""
    specialty_code: str
    specialty_name: str
    specialty_category: str = ""
    certification_level: str = ""
    certifying_body: str = ""
    certificate_number: str = ""
    certified_date: datetime = None
    certified_until: datetime = None
    is_primary: bool = False
    years_experience: int = 0


@dataclass
class CredentialData:
    """DTO for credential information"""
    credential_type: str
    credential_name: str
    credential_number: str = ""
    issuing_authority: str = ""
    issuing_country: str = ""
    issuing_state: str = ""
    issued_date: datetime = None
    expiry_date: datetime = None
    document_url: str = ""


@dataclass
class ServiceRequestData:
    """DTO for service request creation"""
    service_type: str
    title: str
    description: str = ""
    customer_id: str = None
    policy_id: str = None
    claim_id: str = None
    service_category: str = ""
    urgency_level: str = "normal"
    requested_date: datetime = None
    deadline: datetime = None
    estimated_value: float = None
    budget_min: float = None
    budget_max: float = None
    requirements: Dict[str, Any] = field(default_factory=dict)
    required_credentials: List[str] = field(default_factory=list)


@dataclass
class AllocationConfig:
    """DTO for allocation configuration"""
    allocation_type: str = "competitive"
    duration_hours: int = 48
    reserve_price: float = None
    max_price: float = None
    eligible_supplier_types: List[str] = field(default_factory=list)
    required_rating: float = 0.0
    eligible_criteria: Dict[str, Any] = field(default_factory=dict)


@dataclass
class BidSubmission:
    """DTO for bid submission"""
    allocation_id: str
    supplier_id: str
    bid_amount: float
    proposal_summary: str
    proposal_details: str = ""
    deliverables: List[str] = field(default_factory=list)
    estimated_days: int = 0
    proposed_start_date: datetime = None
    proposed_end_date: datetime = None


@dataclass
class MilestoneData:
    """DTO for milestone definition"""
    milestone_name: str
    description: str = ""
    due_date: datetime = None
    milestone_amount: float = 0.0
    deliverables: List[str] = field(default_factory=list)


# =============================================================================
# Utility Functions
# =============================================================================

def generate_code(prefix: str) -> str:
    """Generate unique code with prefix"""
    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    unique = str(uuid.uuid4())[:8].upper()
    return f"{prefix}-{timestamp}-{unique}"


def generate_hash(data: Dict[str, Any], previous_hash: str = None) -> str:
    """Generate SHA-256 hash for ledger entry"""
    hash_input = json.dumps(data, sort_keys=True, default=str)
    if previous_hash:
        hash_input = f"{previous_hash}{hash_input}"
    return hashlib.sha256(hash_input.encode()).hexdigest()


# =============================================================================
# Supplier Management Service
# =============================================================================

class SupplierManagementService:
    """
    Service for managing supplier lifecycle including:
    - Registration and profile management
    - Credential verification
    - Specialty management
    - Supplier search and discovery
    """
    
    def __init__(self):
        self._ledger_service = None
    
    @property
    def ledger_service(self):
        if self._ledger_service is None:
            self._ledger_service = LedgerService()
        return self._ledger_service
    
    def register_supplier(
        self, 
        data: SupplierRegistration,
        created_by: str = "system"
    ) -> Optional[Dict[str, Any]]:
        """Register a new supplier"""
        session = get_db_session()
        try:
            repo = SupplierRepository(session)
            
            # Check if email already exists
            existing = repo.get_by_email(data.email)
            if existing:
                logger.warning(f"Supplier with email {data.email} already exists")
                return None
            
            supplier_id = str(uuid.uuid4())
            supplier_code = generate_code("SUP")
            
            supplier = repo.create(
                id=supplier_id,
                supplier_code=supplier_code,
                name=data.name,
                supplier_type=data.supplier_type,
                email=data.email,
                phone=data.phone,
                registration_number=data.registration_number,
                tax_id=data.tax_id,
                legal_entity_type=data.legal_entity_type,
                address_line1=data.address_line1,
                address_line2=data.address_line2,
                city=data.city,
                state=data.state,
                country=data.country,
                postal_code=data.postal_code,
                website=data.website,
                status=SupplierStatus.PENDING_VERIFICATION.value,
                service_areas=json.dumps(data.service_areas),
                operating_hours=json.dumps(data.operating_hours),
                registered_at=datetime.utcnow()
            )
            
            if supplier:
                # Log to ledger
                self.ledger_service.log_action(
                    entity_type="supplier",
                    entity_id=supplier_id,
                    action_type=LedgerActionType.SUPPLIER_REGISTERED.value,
                    actor_id=created_by,
                    actor_type="user",
                    new_state=supplier.to_dict()
                )
                
                logger.info(f"Registered supplier: {supplier_code}")
                return supplier.to_dict()
            
            return None
        except Exception as e:
            logger.error(f"Error registering supplier: {e}")
            return None
        finally:
            session.close()
    
    def get_supplier(self, supplier_id: str) -> Optional[Dict[str, Any]]:
        """Get supplier by ID"""
        session = get_db_session()
        try:
            repo = SupplierRepository(session)
            supplier = repo.get_by_id(supplier_id)
            return supplier.to_dict() if supplier else None
        finally:
            session.close()
    
    def get_supplier_by_code(self, supplier_code: str) -> Optional[Dict[str, Any]]:
        """Get supplier by code"""
        session = get_db_session()
        try:
            repo = SupplierRepository(session)
            supplier = repo.get_by_code(supplier_code)
            return supplier.to_dict() if supplier else None
        finally:
            session.close()
    
    def update_supplier(
        self, 
        supplier_id: str, 
        updates: Dict[str, Any],
        updated_by: str = "system"
    ) -> Optional[Dict[str, Any]]:
        """Update supplier profile"""
        session = get_db_session()
        try:
            repo = SupplierRepository(session)
            supplier = repo.get_by_id(supplier_id)
            
            if not supplier:
                return None
            
            previous_state = supplier.to_dict()
            
            # Update fields
            updated_supplier = repo.update(supplier_id, **updates)
            
            if updated_supplier:
                # Log to ledger
                self.ledger_service.log_action(
                    entity_type="supplier",
                    entity_id=supplier_id,
                    action_type=LedgerActionType.SUPPLIER_UPDATED.value,
                    actor_id=updated_by,
                    actor_type="user",
                    previous_state=previous_state,
                    new_state=updated_supplier.to_dict(),
                    changes=updates
                )
                
                return updated_supplier.to_dict()
            
            return None
        finally:
            session.close()
    
    def verify_supplier(
        self, 
        supplier_id: str, 
        verified_by: str
    ) -> bool:
        """Verify and activate a supplier"""
        session = get_db_session()
        try:
            repo = SupplierRepository(session)
            supplier = repo.get_by_id(supplier_id)
            
            if not supplier:
                return False
            
            previous_state = supplier.to_dict()
            
            updated = repo.update(
                supplier_id,
                status=SupplierStatus.ACTIVE.value,
                verification_date=datetime.utcnow(),
                verified_by=verified_by
            )
            
            if updated:
                self.ledger_service.log_action(
                    entity_type="supplier",
                    entity_id=supplier_id,
                    action_type=LedgerActionType.SUPPLIER_VERIFIED.value,
                    actor_id=verified_by,
                    actor_type="user",
                    previous_state=previous_state,
                    new_state=updated.to_dict()
                )
                return True
            
            return False
        finally:
            session.close()
    
    def suspend_supplier(
        self, 
        supplier_id: str, 
        reason: str,
        suspended_by: str
    ) -> bool:
        """Suspend a supplier"""
        session = get_db_session()
        try:
            repo = SupplierRepository(session)
            supplier = repo.get_by_id(supplier_id)
            
            if not supplier:
                return False
            
            previous_state = supplier.to_dict()
            
            updated = repo.update(
                supplier_id,
                status=SupplierStatus.SUSPENDED.value
            )
            
            if updated:
                self.ledger_service.log_action(
                    entity_type="supplier",
                    entity_id=supplier_id,
                    action_type=LedgerActionType.SUPPLIER_SUSPENDED.value,
                    actor_id=suspended_by,
                    actor_type="user",
                    previous_state=previous_state,
                    new_state=updated.to_dict(),
                    metadata={"reason": reason}
                )
                return True
            
            return False
        finally:
            session.close()
    
    def add_specialty(
        self, 
        supplier_id: str, 
        data: SpecialtyData,
        added_by: str = "system"
    ) -> Optional[Dict[str, Any]]:
        """Add a specialty to a supplier"""
        session = get_db_session()
        try:
            repo = SupplierSpecialtyRepository(session)
            
            specialty_id = str(uuid.uuid4())
            
            specialty = repo.create(
                id=specialty_id,
                supplier_id=supplier_id,
                specialty_code=data.specialty_code,
                specialty_name=data.specialty_name,
                specialty_category=data.specialty_category,
                certification_level=data.certification_level,
                certifying_body=data.certifying_body,
                certificate_number=data.certificate_number,
                certified_date=data.certified_date,
                certified_until=data.certified_until,
                is_primary=data.is_primary,
                years_experience=data.years_experience
            )
            
            return specialty.to_dict() if specialty else None
        finally:
            session.close()
    
    def add_credential(
        self, 
        supplier_id: str, 
        data: CredentialData,
        added_by: str = "system"
    ) -> Optional[Dict[str, Any]]:
        """Add a credential to a supplier"""
        session = get_db_session()
        try:
            repo = SupplierCredentialRepository(session)
            
            credential_id = str(uuid.uuid4())
            
            credential = repo.create(
                id=credential_id,
                supplier_id=supplier_id,
                credential_type=data.credential_type,
                credential_name=data.credential_name,
                credential_number=data.credential_number,
                issuing_authority=data.issuing_authority,
                issuing_country=data.issuing_country,
                issuing_state=data.issuing_state,
                issued_date=data.issued_date,
                expiry_date=data.expiry_date,
                document_url=data.document_url,
                verification_status=CredentialStatus.PENDING.value
            )
            
            if credential:
                self.ledger_service.log_action(
                    entity_type="credential",
                    entity_id=credential_id,
                    action_type=LedgerActionType.CREDENTIAL_ADDED.value,
                    actor_id=added_by,
                    actor_type="user",
                    new_state=credential.to_dict(),
                    metadata={"supplier_id": supplier_id}
                )
                
                return credential.to_dict()
            
            return None
        finally:
            session.close()
    
    def verify_credential(
        self, 
        credential_id: str, 
        verified_by: str,
        notes: str = None
    ) -> bool:
        """Verify a credential"""
        session = get_db_session()
        try:
            repo = SupplierCredentialRepository(session)
            cred = repo.get_by_id(credential_id)
            
            if not cred:
                return False
            
            previous_state = cred.to_dict()
            success = repo.verify_credential(credential_id, verified_by, notes)
            
            if success:
                cred = repo.get_by_id(credential_id)
                self.ledger_service.log_action(
                    entity_type="credential",
                    entity_id=credential_id,
                    action_type=LedgerActionType.CREDENTIAL_VERIFIED.value,
                    actor_id=verified_by,
                    actor_type="user",
                    previous_state=previous_state,
                    new_state=cred.to_dict()
                )
            
            return success
        finally:
            session.close()
    
    def search_suppliers(
        self,
        query: str = None,
        supplier_types: List[str] = None,
        min_rating: float = None,
        city: str = None,
        state: str = None,
        has_specialty: str = None,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Search for suppliers with various criteria"""
        session = get_db_session()
        try:
            repo = SupplierRepository(session)
            suppliers = repo.search_suppliers(
                query=query,
                supplier_types=supplier_types,
                min_rating=min_rating,
                city=city,
                state=state,
                has_specialty=has_specialty,
                limit=limit
            )
            return [s.to_dict() for s in suppliers]
        finally:
            session.close()
    
    def get_top_rated_suppliers(
        self, 
        supplier_type: str = None, 
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Get top rated suppliers"""
        session = get_db_session()
        try:
            repo = SupplierRepository(session)
            suppliers = repo.get_top_rated(supplier_type, limit)
            return [s.to_dict() for s in suppliers]
        finally:
            session.close()
    
    def get_supplier_specialties(self, supplier_id: str) -> List[Dict[str, Any]]:
        """Get all specialties for a supplier"""
        session = get_db_session()
        try:
            repo = SupplierSpecialtyRepository(session)
            specialties = repo.get_by_supplier(supplier_id)
            return [s.to_dict() for s in specialties]
        finally:
            session.close()
    
    def get_supplier_credentials(self, supplier_id: str) -> List[Dict[str, Any]]:
        """Get all credentials for a supplier"""
        session = get_db_session()
        try:
            repo = SupplierCredentialRepository(session)
            credentials = repo.get_by_supplier(supplier_id)
            return [c.to_dict() for c in credentials]
        finally:
            session.close()


# =============================================================================
# Allocation Service
# =============================================================================

class AllocationService:
    """
    Service for managing service requests and allocations:
    - Service request creation and management
    - Allocation creation and configuration
    - Supplier eligibility determination
    - Allocation lifecycle management
    """
    
    def __init__(self):
        self._ledger_service = None
    
    @property
    def ledger_service(self):
        if self._ledger_service is None:
            self._ledger_service = LedgerService()
        return self._ledger_service
    
    def create_service_request(
        self, 
        data: ServiceRequestData,
        requester_id: str,
        requester_type: str = "user"
    ) -> Optional[Dict[str, Any]]:
        """Create a new service request"""
        session = get_db_session()
        try:
            repo = ServiceRequestRepository(session)
            
            request_id = str(uuid.uuid4())
            request_code = generate_code("SR")
            
            request = repo.create(
                id=request_id,
                request_code=request_code,
                customer_id=data.customer_id,
                policy_id=data.policy_id,
                claim_id=data.claim_id,
                service_type=data.service_type,
                service_category=data.service_category,
                title=data.title,
                description=data.description,
                urgency_level=data.urgency_level,
                requested_date=data.requested_date,
                deadline=data.deadline,
                estimated_value=data.estimated_value,
                budget_min=data.budget_min,
                budget_max=data.budget_max,
                requirements=json.dumps(data.requirements),
                required_credentials=json.dumps(data.required_credentials),
                status="submitted",
                requester_id=requester_id,
                requester_type=requester_type,
                request_date=datetime.utcnow()
            )
            
            if request:
                self.ledger_service.log_action(
                    entity_type="service_request",
                    entity_id=request_id,
                    action_type=LedgerActionType.SERVICE_REQUEST_CREATED.value,
                    actor_id=requester_id,
                    actor_type=requester_type,
                    new_state=request.to_dict()
                )
                
                logger.info(f"Created service request: {request_code}")
                return request.to_dict()
            
            return None
        finally:
            session.close()
    
    def get_service_request(self, request_id: str) -> Optional[Dict[str, Any]]:
        """Get service request by ID"""
        session = get_db_session()
        try:
            repo = ServiceRequestRepository(session)
            request = repo.get_by_id(request_id)
            return request.to_dict() if request else None
        finally:
            session.close()
    
    def create_allocation(
        self, 
        service_request_id: str,
        config: AllocationConfig,
        created_by: str
    ) -> Optional[Dict[str, Any]]:
        """Create an allocation from a service request"""
        session = get_db_session()
        try:
            sr_repo = ServiceRequestRepository(session)
            alloc_repo = AllocationRepository(session)
            
            # Verify service request exists
            request = sr_repo.get_by_id(service_request_id)
            if not request:
                logger.error(f"Service request not found: {service_request_id}")
                return None
            
            allocation_id = str(uuid.uuid4())
            allocation_code = generate_code("AL")
            
            opens_at = datetime.utcnow()
            closes_at = opens_at + timedelta(hours=config.duration_hours)
            
            # Default eligible types to service request type
            eligible_types = config.eligible_supplier_types
            if not eligible_types:
                eligible_types = [request.service_type]
            
            allocation = alloc_repo.create(
                id=allocation_id,
                allocation_code=allocation_code,
                service_request_id=service_request_id,
                allocation_type=config.allocation_type,
                status=AllocationStatus.OPEN.value,
                opened_at=opens_at,
                closes_at=closes_at,
                reserve_price=config.reserve_price,
                max_price=config.max_price,
                eligible_supplier_types=json.dumps(eligible_types),
                required_rating=config.required_rating,
                eligible_criteria=json.dumps(config.eligible_criteria),
                created_by=created_by
            )
            
            if allocation:
                # Update service request status
                sr_repo.update(service_request_id, status="allocation_open")
                
                self.ledger_service.log_action(
                    entity_type="allocation",
                    entity_id=allocation_id,
                    action_type=LedgerActionType.ALLOCATION_CREATED.value,
                    actor_id=created_by,
                    actor_type="user",
                    new_state=allocation.to_dict(),
                    metadata={"service_request_id": service_request_id}
                )
                
                logger.info(f"Created allocation: {allocation_code}")
                return allocation.to_dict()
            
            return None
        finally:
            session.close()
    
    def get_allocation(self, allocation_id: str) -> Optional[Dict[str, Any]]:
        """Get allocation by ID"""
        session = get_db_session()
        try:
            repo = AllocationRepository(session)
            allocation = repo.get_by_id(allocation_id)
            return allocation.to_dict() if allocation else None
        finally:
            session.close()
    
    def get_open_allocations(
        self, 
        supplier_type: str = None, 
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Get open allocations available for bidding"""
        session = get_db_session()
        try:
            repo = AllocationRepository(session)
            allocations = repo.get_open_allocations(supplier_type, limit)
            return [a.to_dict() for a in allocations]
        finally:
            session.close()
    
    def close_allocation(self, allocation_id: str, closed_by: str) -> bool:
        """Manually close an allocation for bidding"""
        session = get_db_session()
        try:
            repo = AllocationRepository(session)
            allocation = repo.get_by_id(allocation_id)
            
            if not allocation:
                return False
            
            previous_state = allocation.to_dict()
            
            updated = repo.update(
                allocation_id,
                status=AllocationStatus.EVALUATION.value,
                closes_at=datetime.utcnow()
            )
            
            if updated:
                self.ledger_service.log_action(
                    entity_type="allocation",
                    entity_id=allocation_id,
                    action_type=LedgerActionType.ALLOCATION_CLOSED.value,
                    actor_id=closed_by,
                    actor_type="user",
                    previous_state=previous_state,
                    new_state=updated.to_dict()
                )
                return True
            
            return False
        finally:
            session.close()
    
    def cancel_allocation(
        self, 
        allocation_id: str, 
        reason: str,
        cancelled_by: str
    ) -> bool:
        """Cancel an allocation"""
        session = get_db_session()
        try:
            repo = AllocationRepository(session)
            allocation = repo.get_by_id(allocation_id)
            
            if not allocation:
                return False
            
            previous_state = allocation.to_dict()
            
            updated = repo.update(
                allocation_id,
                status=AllocationStatus.CANCELLED.value
            )
            
            if updated:
                self.ledger_service.log_action(
                    entity_type="allocation",
                    entity_id=allocation_id,
                    action_type=LedgerActionType.ALLOCATION_CANCELLED.value,
                    actor_id=cancelled_by,
                    actor_type="user",
                    previous_state=previous_state,
                    new_state=updated.to_dict(),
                    metadata={"reason": reason}
                )
                return True
            
            return False
        finally:
            session.close()
    
    def get_eligible_suppliers(
        self, 
        allocation_id: str
    ) -> List[Dict[str, Any]]:
        """Get suppliers eligible to bid on an allocation"""
        session = get_db_session()
        try:
            alloc_repo = AllocationRepository(session)
            supplier_repo = SupplierRepository(session)
            
            allocation = alloc_repo.get_by_id(allocation_id)
            if not allocation:
                return []
            
            # Parse eligible types
            try:
                eligible_types = json.loads(allocation.eligible_supplier_types or "[]")
            except:
                eligible_types = []
            
            # Search for matching suppliers
            suppliers = supplier_repo.search_suppliers(
                supplier_types=eligible_types,
                min_rating=allocation.required_rating
            )
            
            return [s.to_dict() for s in suppliers]
        finally:
            session.close()
    
    def record_view(self, allocation_id: str) -> bool:
        """Record that an allocation was viewed"""
        session = get_db_session()
        try:
            repo = AllocationRepository(session)
            return repo.increment_view_count(allocation_id)
        finally:
            session.close()


# =============================================================================
# Bidding Service
# =============================================================================

class BiddingService:
    """
    Service for managing the bidding process:
    - Bid submission and validation
    - Bid scoring and ranking
    - Winner selection
    """
    
    def __init__(self):
        self._ledger_service = None
        self._scoring_service = None
    
    @property
    def ledger_service(self):
        if self._ledger_service is None:
            self._ledger_service = LedgerService()
        return self._ledger_service
    
    @property
    def scoring_service(self):
        if self._scoring_service is None:
            self._scoring_service = ScoringService()
        return self._scoring_service
    
    def submit_bid(self, data: BidSubmission) -> Optional[Dict[str, Any]]:
        """Submit a bid for an allocation"""
        session = get_db_session()
        try:
            alloc_repo = AllocationRepository(session)
            bid_repo = BidRepository(session)
            supplier_repo = SupplierRepository(session)
            
            # Verify allocation is open
            allocation = alloc_repo.get_by_id(data.allocation_id)
            if not allocation or allocation.status not in [
                AllocationStatus.OPEN.value, 
                AllocationStatus.BIDDING.value
            ]:
                logger.error(f"Allocation not open for bidding: {data.allocation_id}")
                return None
            
            # Check if allocation has closed
            if allocation.closes_at and allocation.closes_at < datetime.utcnow():
                logger.error(f"Allocation has closed: {data.allocation_id}")
                return None
            
            # Verify supplier exists and is active
            supplier = supplier_repo.get_by_id(data.supplier_id)
            if not supplier or supplier.status != SupplierStatus.ACTIVE.value:
                logger.error(f"Supplier not active: {data.supplier_id}")
                return None
            
            # Check if supplier already has a bid
            existing_bid = bid_repo.get_supplier_bid_for_allocation(
                data.allocation_id, 
                data.supplier_id
            )
            if existing_bid:
                logger.error(f"Supplier already has a bid on this allocation")
                return None
            
            bid_id = str(uuid.uuid4())
            bid_code = generate_code("BID")
            
            # Calculate AI score for bid
            ai_score = self._calculate_bid_score(data, supplier, allocation)
            
            bid = bid_repo.create(
                id=bid_id,
                bid_code=bid_code,
                allocation_id=data.allocation_id,
                supplier_id=data.supplier_id,
                bid_amount=data.bid_amount,
                proposal_summary=data.proposal_summary,
                proposal_details=data.proposal_details,
                deliverables=json.dumps(data.deliverables),
                estimated_days=data.estimated_days,
                proposed_start_date=data.proposed_start_date,
                proposed_end_date=data.proposed_end_date,
                status=BidStatus.SUBMITTED.value,
                submitted_at=datetime.utcnow(),
                supplier_rating_at_bid=supplier.rating,
                ai_score=ai_score
            )
            
            if bid:
                # Update allocation bid count and status
                alloc_repo.update(
                    data.allocation_id,
                    bid_count=allocation.bid_count + 1,
                    status=AllocationStatus.BIDDING.value
                )
                
                self.ledger_service.log_action(
                    entity_type="bid",
                    entity_id=bid_id,
                    action_type=LedgerActionType.BID_SUBMITTED.value,
                    actor_id=data.supplier_id,
                    actor_type="supplier",
                    new_state=bid.to_dict(),
                    metadata={"allocation_id": data.allocation_id}
                )
                
                logger.info(f"Submitted bid: {bid_code}")
                return bid.to_dict()
            
            return None
        finally:
            session.close()
    
    def _calculate_bid_score(
        self, 
        bid_data: BidSubmission, 
        supplier: Supplier, 
        allocation: Allocation
    ) -> float:
        """Calculate AI score for a bid"""
        score = 50.0  # Base score
        
        # Factor 1: Supplier rating (0-25 points)
        if supplier.rating:
            score += (supplier.rating / 100) * 25
        
        # Factor 2: Price competitiveness (0-25 points)
        if allocation.reserve_price and bid_data.bid_amount:
            if bid_data.bid_amount <= float(allocation.reserve_price):
                price_ratio = float(allocation.reserve_price) / bid_data.bid_amount
                score += min(price_ratio * 10, 25)
        
        # Factor 3: Completion rate (0-15 points)
        if supplier.total_allocations > 0:
            completion_rate = supplier.successful_completions / supplier.total_allocations
            score += completion_rate * 15
        
        # Factor 4: Proposal quality (0-10 points)
        if bid_data.proposal_details and len(bid_data.proposal_details) > 200:
            score += 5
        if bid_data.deliverables and len(bid_data.deliverables) >= 3:
            score += 5
        
        return min(max(score, 0), 100)  # Clamp to 0-100
    
    def get_bid(self, bid_id: str) -> Optional[Dict[str, Any]]:
        """Get bid by ID"""
        session = get_db_session()
        try:
            repo = BidRepository(session)
            bid = repo.get_by_id(bid_id)
            return bid.to_dict() if bid else None
        finally:
            session.close()
    
    def get_bids_for_allocation(
        self, 
        allocation_id: str,
        status: str = None
    ) -> List[Dict[str, Any]]:
        """Get all bids for an allocation"""
        session = get_db_session()
        try:
            repo = BidRepository(session)
            bids = repo.get_by_allocation(allocation_id, status)
            return [b.to_dict() for b in bids]
        finally:
            session.close()
    
    def get_ranked_bids(self, allocation_id: str) -> List[Dict[str, Any]]:
        """Get ranked bids for an allocation"""
        session = get_db_session()
        try:
            repo = BidRepository(session)
            bids = repo.get_ranked_bids(allocation_id)
            return [b.to_dict() for b in bids]
        finally:
            session.close()
    
    def get_supplier_bids(
        self, 
        supplier_id: str, 
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Get all bids by a supplier"""
        session = get_db_session()
        try:
            repo = BidRepository(session)
            bids = repo.get_by_supplier(supplier_id, limit)
            return [b.to_dict() for b in bids]
        finally:
            session.close()
    
    def withdraw_bid(
        self, 
        bid_id: str, 
        supplier_id: str,
        reason: str = None
    ) -> bool:
        """Withdraw a bid"""
        session = get_db_session()
        try:
            repo = BidRepository(session)
            bid = repo.get_by_id(bid_id)
            
            if not bid or bid.supplier_id != supplier_id:
                return False
            
            if bid.status != BidStatus.SUBMITTED.value:
                return False
            
            previous_state = bid.to_dict()
            
            updated = repo.update(bid_id, status=BidStatus.WITHDRAWN.value)
            
            if updated:
                self.ledger_service.log_action(
                    entity_type="bid",
                    entity_id=bid_id,
                    action_type=LedgerActionType.BID_WITHDRAWN.value,
                    actor_id=supplier_id,
                    actor_type="supplier",
                    previous_state=previous_state,
                    new_state=updated.to_dict(),
                    metadata={"reason": reason}
                )
                return True
            
            return False
        finally:
            session.close()
    
    def select_winner(
        self, 
        allocation_id: str, 
        bid_id: str,
        selected_by: str,
        notes: str = None
    ) -> Optional[Dict[str, Any]]:
        """Select the winning bid for an allocation"""
        session = get_db_session()
        try:
            alloc_repo = AllocationRepository(session)
            bid_repo = BidRepository(session)
            supplier_repo = SupplierRepository(session)
            
            allocation = alloc_repo.get_by_id(allocation_id)
            bid = bid_repo.get_by_id(bid_id)
            
            if not allocation or not bid:
                return None
            
            if bid.allocation_id != allocation_id:
                logger.error("Bid does not belong to allocation")
                return None
            
            previous_bid_state = bid.to_dict()
            previous_alloc_state = allocation.to_dict()
            
            # Mark bid as winner
            bid_repo.select_winner(bid_id, selected_by, notes)
            
            # Award allocation
            alloc_repo.award_allocation(
                allocation_id,
                winning_bid_id=bid_id,
                winning_supplier_id=bid.supplier_id,
                final_amount=float(bid.bid_amount),
                awarded_by=selected_by
            )
            
            # Update supplier stats
            supplier_repo.increment_allocations(bid.supplier_id, successful=True)
            
            # Reject other bids
            other_bids = bid_repo.get_by_allocation(allocation_id)
            for other_bid in other_bids:
                if other_bid.id != bid_id and other_bid.status == BidStatus.SUBMITTED.value:
                    bid_repo.update(other_bid.id, status=BidStatus.REJECTED.value)
            
            # Log to ledger
            bid = bid_repo.get_by_id(bid_id)
            allocation = alloc_repo.get_by_id(allocation_id)
            
            self.ledger_service.log_action(
                entity_type="allocation",
                entity_id=allocation_id,
                action_type=LedgerActionType.WINNER_SELECTED.value,
                actor_id=selected_by,
                actor_type="user",
                previous_state=previous_alloc_state,
                new_state=allocation.to_dict(),
                metadata={
                    "winning_bid_id": bid_id,
                    "winning_supplier_id": bid.supplier_id,
                    "final_amount": float(bid.bid_amount)
                }
            )
            
            logger.info(f"Selected winner for allocation {allocation_id}: {bid_id}")
            return bid.to_dict()
        finally:
            session.close()


# =============================================================================
# Fulfillment Service
# =============================================================================

class FulfillmentService:
    """
    Service for managing service fulfillment:
    - Fulfillment initialization
    - Milestone tracking
    - Deliverable management
    - Completion and quality assessment
    """
    
    def __init__(self):
        self._ledger_service = None
        self._escrow_service = None
    
    @property
    def ledger_service(self):
        if self._ledger_service is None:
            self._ledger_service = LedgerService()
        return self._ledger_service
    
    @property
    def escrow_service(self):
        if self._escrow_service is None:
            self._escrow_service = EscrowService()
        return self._escrow_service
    
    def start_fulfillment(
        self, 
        allocation_id: str,
        milestones: List[MilestoneData] = None,
        started_by: str = "system"
    ) -> Optional[Dict[str, Any]]:
        """Start fulfillment for an awarded allocation"""
        session = get_db_session()
        try:
            alloc_repo = AllocationRepository(session)
            fulfillment_repo = ServiceFulfillmentRepository(session)
            milestone_repo = ServiceMilestoneRepository(session)
            
            allocation = alloc_repo.get_by_id(allocation_id)
            if not allocation or allocation.status != AllocationStatus.AWARDED.value:
                logger.error(f"Allocation not awarded: {allocation_id}")
                return None
            
            fulfillment_id = str(uuid.uuid4())
            fulfillment_code = generate_code("FUL")
            
            # Get customer from service request
            sr_repo = ServiceRequestRepository(session)
            service_request = sr_repo.get_by_id(allocation.service_request_id)
            customer_id = service_request.customer_id if service_request else None
            
            fulfillment = fulfillment_repo.create(
                id=fulfillment_id,
                fulfillment_code=fulfillment_code,
                allocation_id=allocation_id,
                supplier_id=allocation.winning_supplier_id,
                customer_id=customer_id,
                status=FulfillmentStatus.IN_PROGRESS.value,
                started_at=datetime.utcnow(),
                contracted_amount=allocation.final_amount
            )
            
            if fulfillment:
                # Create milestones if provided
                if milestones:
                    for i, m in enumerate(milestones):
                        milestone_repo.create(
                            id=str(uuid.uuid4()),
                            fulfillment_id=fulfillment_id,
                            milestone_name=m.milestone_name,
                            description=m.description,
                            sequence_order=i + 1,
                            due_date=m.due_date,
                            milestone_amount=m.milestone_amount,
                            deliverables=json.dumps(m.deliverables),
                            status="pending"
                        )
                
                # Update service request status
                if service_request:
                    sr_repo.update(service_request.id, status="in_progress")
                
                self.ledger_service.log_action(
                    entity_type="fulfillment",
                    entity_id=fulfillment_id,
                    action_type=LedgerActionType.FULFILLMENT_STARTED.value,
                    actor_id=started_by,
                    actor_type="user",
                    new_state=fulfillment.to_dict(),
                    metadata={"allocation_id": allocation_id}
                )
                
                logger.info(f"Started fulfillment: {fulfillment_code}")
                return fulfillment.to_dict()
            
            return None
        finally:
            session.close()
    
    def get_fulfillment(self, fulfillment_id: str) -> Optional[Dict[str, Any]]:
        """Get fulfillment by ID"""
        session = get_db_session()
        try:
            repo = ServiceFulfillmentRepository(session)
            fulfillment = repo.get_by_id(fulfillment_id)
            return fulfillment.to_dict() if fulfillment else None
        finally:
            session.close()
    
    def get_fulfillment_milestones(
        self, 
        fulfillment_id: str
    ) -> List[Dict[str, Any]]:
        """Get milestones for a fulfillment"""
        session = get_db_session()
        try:
            repo = ServiceMilestoneRepository(session)
            milestones = repo.get_by_fulfillment(fulfillment_id)
            return [m.to_dict() for m in milestones]
        finally:
            session.close()
    
    def complete_milestone(
        self, 
        milestone_id: str,
        deliverables: List[str] = None,
        approved_by: str = None,
        notes: str = None
    ) -> bool:
        """Mark a milestone as completed"""
        session = get_db_session()
        try:
            repo = ServiceMilestoneRepository(session)
            milestone = repo.get_by_id(milestone_id)
            
            if not milestone:
                return False
            
            previous_state = milestone.to_dict()
            
            # Update milestone
            updates = {
                "status": "completed",
                "completed_date": datetime.utcnow()
            }
            if deliverables:
                updates["submitted_deliverables"] = json.dumps(deliverables)
            if approved_by:
                updates["approved_by"] = approved_by
                updates["approved_at"] = datetime.utcnow()
            if notes:
                updates["approval_notes"] = notes
            
            updated = repo.update(milestone_id, **updates)
            
            if updated:
                self.ledger_service.log_action(
                    entity_type="milestone",
                    entity_id=milestone_id,
                    action_type=LedgerActionType.MILESTONE_COMPLETED.value,
                    actor_id=approved_by or "system",
                    actor_type="user",
                    previous_state=previous_state,
                    new_state=updated.to_dict()
                )
                return True
            
            return False
        finally:
            session.close()
    
    def submit_deliverables(
        self, 
        fulfillment_id: str,
        deliverables: List[Dict[str, Any]],
        submitted_by: str
    ) -> bool:
        """Submit deliverables for a fulfillment"""
        session = get_db_session()
        try:
            repo = ServiceFulfillmentRepository(session)
            fulfillment = repo.get_by_id(fulfillment_id)
            
            if not fulfillment:
                return False
            
            previous_state = fulfillment.to_dict()
            
            updated = repo.update(
                fulfillment_id,
                deliverables_submitted=json.dumps(deliverables),
                status=FulfillmentStatus.DELIVERED.value
            )
            
            if updated:
                self.ledger_service.log_action(
                    entity_type="fulfillment",
                    entity_id=fulfillment_id,
                    action_type=LedgerActionType.DELIVERABLE_SUBMITTED.value,
                    actor_id=submitted_by,
                    actor_type="supplier",
                    previous_state=previous_state,
                    new_state=updated.to_dict()
                )
                return True
            
            return False
        finally:
            session.close()
    
    def complete_fulfillment(
        self, 
        fulfillment_id: str,
        customer_rating: float,
        customer_feedback: str = None,
        quality_score: float = None,
        completed_by: str = "system"
    ) -> Optional[Dict[str, Any]]:
        """Complete a fulfillment"""
        session = get_db_session()
        try:
            repo = ServiceFulfillmentRepository(session)
            alloc_repo = AllocationRepository(session)
            sr_repo = ServiceRequestRepository(session)
            supplier_repo = SupplierRepository(session)
            
            fulfillment = repo.get_by_id(fulfillment_id)
            if not fulfillment:
                return None
            
            previous_state = fulfillment.to_dict()
            
            # Calculate final quality score
            final_quality = quality_score or (customer_rating * 20)  # Scale 1-5 to 0-100
            
            updated = repo.update(
                fulfillment_id,
                status=FulfillmentStatus.COMPLETED.value,
                completed_at=datetime.utcnow(),
                quality_score=final_quality,
                customer_rating=customer_rating,
                customer_feedback=customer_feedback,
                final_amount=fulfillment.contracted_amount
            )
            
            if updated:
                # Update service request
                allocation = alloc_repo.get_by_id(fulfillment.allocation_id)
                if allocation:
                    service_request = sr_repo.get_by_id(allocation.service_request_id)
                    if service_request:
                        sr_repo.update(service_request.id, status="completed")
                
                # Update supplier rating (simple average for now)
                supplier = supplier_repo.get_by_id(fulfillment.supplier_id)
                if supplier:
                    new_rating = ((supplier.rating * supplier.total_allocations) + final_quality) / (supplier.total_allocations + 1)
                    supplier_repo.update_rating(supplier.id, new_rating)
                
                self.ledger_service.log_action(
                    entity_type="fulfillment",
                    entity_id=fulfillment_id,
                    action_type=LedgerActionType.SERVICE_COMPLETED.value,
                    actor_id=completed_by,
                    actor_type="user",
                    previous_state=previous_state,
                    new_state=updated.to_dict(),
                    metadata={
                        "customer_rating": customer_rating,
                        "quality_score": final_quality
                    }
                )
                
                # Release escrow payment
                self.escrow_service.release_escrow_for_allocation(
                    fulfillment.allocation_id,
                    released_by=completed_by
                )
                
                logger.info(f"Completed fulfillment: {fulfillment_id}")
                return updated.to_dict()
            
            return None
        finally:
            session.close()
    
    def get_supplier_fulfillments(
        self, 
        supplier_id: str,
        status: str = None
    ) -> List[Dict[str, Any]]:
        """Get fulfillments for a supplier"""
        session = get_db_session()
        try:
            repo = ServiceFulfillmentRepository(session)
            fulfillments = repo.get_by_supplier(supplier_id, status)
            return [f.to_dict() for f in fulfillments]
        finally:
            session.close()
    
    def get_active_fulfillments(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get currently active fulfillments"""
        session = get_db_session()
        try:
            repo = ServiceFulfillmentRepository(session)
            fulfillments = repo.get_active_fulfillments(limit)
            return [f.to_dict() for f in fulfillments]
        finally:
            session.close()


# =============================================================================
# Ledger Service
# =============================================================================

class LedgerService:
    """
    Service for managing the immutable Sully Chain ledger:
    - Action logging with hash chain integrity
    - Audit trail generation
    - Blockchain anchoring (optional)
    """
    
    def log_action(
        self,
        entity_type: str,
        entity_id: str,
        action_type: str,
        actor_id: str,
        actor_type: str,
        actor_name: str = None,
        previous_state: Dict[str, Any] = None,
        new_state: Dict[str, Any] = None,
        changes: Dict[str, Any] = None,
        metadata: Dict[str, Any] = None
    ) -> Optional[Dict[str, Any]]:
        """Log an action to the immutable ledger"""
        session = get_db_session()
        try:
            repo = SullyLedgerRepository(session)
            
            ledger_id = str(uuid.uuid4())
            ledger_code = generate_code("LED")
            sequence_number = repo.get_next_sequence_number()
            
            # Get previous hash for chain integrity
            last_entry = repo.get_last_entry()
            previous_hash = last_entry.hash if last_entry else None
            
            # Generate hash for this entry
            hash_data = {
                "sequence": sequence_number,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "action_type": action_type,
                "actor_id": actor_id,
                "timestamp": datetime.utcnow().isoformat()
            }
            if new_state:
                hash_data["new_state"] = new_state
            
            entry_hash = generate_hash(hash_data, previous_hash)
            
            # Calculate changes if both states provided
            if previous_state and new_state and not changes:
                changes = self._calculate_changes(previous_state, new_state)
            
            entry = repo.create(
                id=ledger_id,
                ledger_code=ledger_code,
                sequence_number=sequence_number,
                entity_type=entity_type,
                entity_id=entity_id,
                action_type=action_type,
                action_description=self._get_action_description(action_type),
                actor_id=actor_id,
                actor_type=actor_type,
                actor_name=actor_name,
                previous_state=json.dumps(previous_state) if previous_state else None,
                new_state=json.dumps(new_state) if new_state else None,
                changes=json.dumps(changes) if changes else None,
                metadata=json.dumps(metadata) if metadata else None,
                hash=entry_hash,
                previous_hash=previous_hash,
                timestamp=datetime.utcnow()
            )
            
            return entry.to_dict() if entry else None
        except Exception as e:
            logger.error(f"Error logging to ledger: {e}")
            return None
        finally:
            session.close()
    
    def _get_action_description(self, action_type: str) -> str:
        """Get human-readable description for action type"""
        descriptions = {
            LedgerActionType.SUPPLIER_REGISTERED.value: "New supplier registered",
            LedgerActionType.SUPPLIER_UPDATED.value: "Supplier profile updated",
            LedgerActionType.SUPPLIER_VERIFIED.value: "Supplier verified and activated",
            LedgerActionType.SUPPLIER_SUSPENDED.value: "Supplier suspended",
            LedgerActionType.CREDENTIAL_ADDED.value: "Credential added to supplier",
            LedgerActionType.CREDENTIAL_VERIFIED.value: "Credential verified",
            LedgerActionType.SERVICE_REQUEST_CREATED.value: "Service request created",
            LedgerActionType.ALLOCATION_CREATED.value: "Allocation created",
            LedgerActionType.ALLOCATION_CLOSED.value: "Allocation closed for bidding",
            LedgerActionType.ALLOCATION_CANCELLED.value: "Allocation cancelled",
            LedgerActionType.BID_SUBMITTED.value: "Bid submitted",
            LedgerActionType.BID_WITHDRAWN.value: "Bid withdrawn",
            LedgerActionType.WINNER_SELECTED.value: "Winning bid selected",
            LedgerActionType.FULFILLMENT_STARTED.value: "Service fulfillment started",
            LedgerActionType.MILESTONE_COMPLETED.value: "Milestone completed",
            LedgerActionType.DELIVERABLE_SUBMITTED.value: "Deliverables submitted",
            LedgerActionType.SERVICE_COMPLETED.value: "Service completed",
            LedgerActionType.ESCROW_CREATED.value: "Escrow account created",
            LedgerActionType.ESCROW_FUNDED.value: "Escrow funded",
            LedgerActionType.PAYMENT_RELEASED.value: "Payment released",
            LedgerActionType.RATING_SUBMITTED.value: "Rating submitted",
            LedgerActionType.SCORE_UPDATED.value: "Supplier score updated",
        }
        return descriptions.get(action_type, action_type)
    
    def _calculate_changes(
        self, 
        previous: Dict[str, Any], 
        current: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Calculate the differences between two states"""
        changes = {}
        all_keys = set(previous.keys()) | set(current.keys())
        
        for key in all_keys:
            old_val = previous.get(key)
            new_val = current.get(key)
            if old_val != new_val:
                changes[key] = {"old": old_val, "new": new_val}
        
        return changes
    
    def get_entity_history(
        self, 
        entity_type: str, 
        entity_id: str,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Get complete history for an entity"""
        session = get_db_session()
        try:
            repo = SullyLedgerRepository(session)
            entries = repo.get_entity_history(entity_type, entity_id, limit)
            return [e.to_dict() for e in entries]
        finally:
            session.close()
    
    def get_actor_history(
        self, 
        actor_type: str, 
        actor_id: str,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Get all actions by an actor"""
        session = get_db_session()
        try:
            repo = SullyLedgerRepository(session)
            entries = repo.get_actor_history(actor_type, actor_id, limit)
            return [e.to_dict() for e in entries]
        finally:
            session.close()
    
    def verify_integrity(
        self, 
        from_sequence: int = 1, 
        to_sequence: int = None
    ) -> Dict[str, Any]:
        """Verify ledger chain integrity"""
        session = get_db_session()
        try:
            repo = SullyLedgerRepository(session)
            is_valid, errors = repo.verify_chain_integrity(from_sequence, to_sequence)
            return {
                "is_valid": is_valid,
                "errors": errors,
                "verified_at": datetime.utcnow().isoformat()
            }
        finally:
            session.close()
    
    def generate_audit_report(
        self,
        entity_type: str = None,
        action_types: List[str] = None,
        from_date: datetime = None,
        to_date: datetime = None,
        limit: int = 1000
    ) -> Dict[str, Any]:
        """Generate audit report"""
        session = get_db_session()
        try:
            repo = SullyLedgerRepository(session)
            entries = repo.get_audit_report(
                entity_type=entity_type,
                action_types=action_types,
                from_date=from_date,
                to_date=to_date,
                limit=limit
            )
            
            return {
                "report_date": datetime.utcnow().isoformat(),
                "filters": {
                    "entity_type": entity_type,
                    "action_types": action_types,
                    "from_date": from_date.isoformat() if from_date else None,
                    "to_date": to_date.isoformat() if to_date else None
                },
                "total_entries": len(entries),
                "entries": [e.to_dict() for e in entries]
            }
        finally:
            session.close()


# =============================================================================
# Escrow Service
# =============================================================================

class EscrowService:
    """
    Service for managing escrow accounts:
    - Escrow creation and funding
    - Payment release
    - Refunds
    """
    
    def __init__(self):
        self._ledger_service = None
    
    @property
    def ledger_service(self):
        if self._ledger_service is None:
            self._ledger_service = LedgerService()
        return self._ledger_service
    
    def create_escrow(
        self, 
        allocation_id: str,
        amount: float,
        payer_type: str,
        payer_id: str,
        created_by: str = "system"
    ) -> Optional[Dict[str, Any]]:
        """Create an escrow account for an allocation"""
        session = get_db_session()
        try:
            repo = EscrowAccountRepository(session)
            alloc_repo = AllocationRepository(session)
            
            allocation = alloc_repo.get_by_id(allocation_id)
            if not allocation:
                return None
            
            escrow_id = str(uuid.uuid4())
            escrow_code = generate_code("ESC")
            
            escrow = repo.create(
                id=escrow_id,
                escrow_code=escrow_code,
                allocation_id=allocation_id,
                held_amount=amount,
                payer_type=payer_type,
                payer_id=payer_id,
                payee_supplier_id=allocation.winning_supplier_id,
                status=EscrowStatus.CREATED.value,
                created_at=datetime.utcnow()
            )
            
            if escrow:
                self.ledger_service.log_action(
                    entity_type="escrow",
                    entity_id=escrow_id,
                    action_type=LedgerActionType.ESCROW_CREATED.value,
                    actor_id=created_by,
                    actor_type="user",
                    new_state=escrow.to_dict(),
                    metadata={"allocation_id": allocation_id, "amount": amount}
                )
                
                return escrow.to_dict()
            
            return None
        finally:
            session.close()
    
    def fund_escrow(
        self, 
        escrow_id: str,
        funded_by: str = "system"
    ) -> bool:
        """Mark escrow as funded"""
        session = get_db_session()
        try:
            repo = EscrowAccountRepository(session)
            escrow = repo.get_by_id(escrow_id)
            
            if not escrow:
                return False
            
            previous_state = escrow.to_dict()
            
            updated = repo.update(
                escrow_id,
                status=EscrowStatus.FUNDED.value,
                funded_at=datetime.utcnow()
            )
            
            if updated:
                self.ledger_service.log_action(
                    entity_type="escrow",
                    entity_id=escrow_id,
                    action_type=LedgerActionType.ESCROW_FUNDED.value,
                    actor_id=funded_by,
                    actor_type="user",
                    previous_state=previous_state,
                    new_state=updated.to_dict()
                )
                return True
            
            return False
        finally:
            session.close()
    
    def release_escrow(
        self, 
        escrow_id: str,
        amount: float = None,
        released_by: str = "system",
        notes: str = None
    ) -> bool:
        """Release funds from escrow"""
        session = get_db_session()
        try:
            escrow_repo = EscrowAccountRepository(session)
            tx_repo = SupplierTransactionRepository(session)
            supplier_repo = SupplierRepository(session)
            
            escrow = escrow_repo.get_by_id(escrow_id)
            if not escrow or escrow.status not in [
                EscrowStatus.FUNDED.value,
                EscrowStatus.PARTIALLY_RELEASED.value
            ]:
                return False
            
            # Release full amount if not specified
            release_amount = amount or (float(escrow.held_amount) - float(escrow.released_amount))
            
            previous_state = escrow.to_dict()
            success = escrow_repo.release_escrow(escrow_id, release_amount, notes)
            
            if success:
                escrow = escrow_repo.get_by_id(escrow_id)
                
                # Create transaction for supplier
                supplier = supplier_repo.get_by_id(escrow.payee_supplier_id)
                if supplier:
                    balance_before = float(supplier.wallet_balance or 0)
                    balance_after = balance_before + release_amount
                    
                    tx_repo.create(
                        id=str(uuid.uuid4()),
                        transaction_code=generate_code("TX"),
                        supplier_id=escrow.payee_supplier_id,
                        allocation_id=escrow.allocation_id,
                        escrow_id=escrow_id,
                        transaction_type=TransactionType.PAYMENT_RECEIVED.value,
                        amount=release_amount,
                        net_amount=release_amount,
                        balance_before=balance_before,
                        balance_after=balance_after,
                        status="completed",
                        description="Payment released from escrow",
                        transaction_date=datetime.utcnow()
                    )
                    
                    # Update supplier balance
                    supplier_repo.update(supplier.id, wallet_balance=balance_after)
                
                self.ledger_service.log_action(
                    entity_type="escrow",
                    entity_id=escrow_id,
                    action_type=LedgerActionType.PAYMENT_RELEASED.value,
                    actor_id=released_by,
                    actor_type="user",
                    previous_state=previous_state,
                    new_state=escrow.to_dict(),
                    metadata={"amount_released": release_amount}
                )
                
                return True
            
            return False
        finally:
            session.close()
    
    def release_escrow_for_allocation(
        self, 
        allocation_id: str,
        released_by: str = "system"
    ) -> bool:
        """Release escrow funds for an allocation"""
        session = get_db_session()
        try:
            repo = EscrowAccountRepository(session)
            escrow = repo.get_by_allocation(allocation_id)
            
            if not escrow:
                return False
            
            return self.release_escrow(escrow.id, released_by=released_by)
        finally:
            session.close()
    
    def get_escrow(self, escrow_id: str) -> Optional[Dict[str, Any]]:
        """Get escrow by ID"""
        session = get_db_session()
        try:
            repo = EscrowAccountRepository(session)
            escrow = repo.get_by_id(escrow_id)
            return escrow.to_dict() if escrow else None
        finally:
            session.close()
    
    def get_total_held(self) -> float:
        """Get total amount held in escrow"""
        session = get_db_session()
        try:
            repo = EscrowAccountRepository(session)
            return repo.get_total_held()
        finally:
            session.close()


# =============================================================================
# Scoring Service
# =============================================================================

class ScoringService:
    """
    Service for AI-powered supplier scoring:
    - Performance score calculation
    - Score history tracking
    - Tier assignment
    """
    
    def __init__(self):
        self._ledger_service = None
    
    @property
    def ledger_service(self):
        if self._ledger_service is None:
            self._ledger_service = LedgerService()
        return self._ledger_service
    
    def calculate_supplier_score(
        self, 
        supplier_id: str,
        calculated_by: str = "system"
    ) -> Optional[Dict[str, Any]]:
        """Calculate comprehensive score for a supplier"""
        session = get_db_session()
        try:
            supplier_repo = SupplierRepository(session)
            score_repo = SupplierScoreRepository(session)
            fulfillment_repo = ServiceFulfillmentRepository(session)
            bid_repo = BidRepository(session)
            
            supplier = supplier_repo.get_by_id(supplier_id)
            if not supplier:
                return None
            
            # Get previous score
            prev_score = score_repo.get_latest_score(supplier_id)
            previous_overall = prev_score.overall_score if prev_score else 50.0
            
            # Calculate individual scores
            scores = self._calculate_individual_scores(
                supplier, fulfillment_repo, bid_repo, session
            )
            
            # Calculate weighted overall score
            weights = {
                "performance": 0.20,
                "reliability": 0.20,
                "quality": 0.25,
                "price": 0.15,
                "response_time": 0.10,
                "compliance": 0.10
            }
            
            overall = sum(
                scores.get(key, 50) * weight 
                for key, weight in weights.items()
            )
            
            # Determine tier
            tier = self._determine_tier(overall)
            
            # Determine trend
            score_change = overall - previous_overall
            if score_change > 2:
                trend = "improving"
            elif score_change < -2:
                trend = "declining"
            else:
                trend = "stable"
            
            # Create score record
            score_id = str(uuid.uuid4())
            
            score = score_repo.create(
                id=score_id,
                supplier_id=supplier_id,
                performance_score=scores.get("performance", 50),
                reliability_score=scores.get("reliability", 50),
                quality_score=scores.get("quality", 50),
                price_competitiveness=scores.get("price", 50),
                response_time_score=scores.get("response_time", 50),
                compliance_score=scores.get("compliance", 50),
                overall_score=overall,
                performance_tier=tier,
                score_breakdown=json.dumps(scores),
                score_trend=trend,
                previous_score=previous_overall,
                score_change=score_change,
                calculated_at=datetime.utcnow()
            )
            
            if score:
                # Update supplier rating
                supplier_repo.update_rating(supplier_id, overall)
                
                self.ledger_service.log_action(
                    entity_type="score",
                    entity_id=score_id,
                    action_type=LedgerActionType.SCORE_UPDATED.value,
                    actor_id=calculated_by,
                    actor_type="system",
                    new_state=score.to_dict(),
                    metadata={"supplier_id": supplier_id, "trend": trend}
                )
                
                return score.to_dict()
            
            return None
        finally:
            session.close()
    
    def _calculate_individual_scores(
        self, 
        supplier: Supplier,
        fulfillment_repo: ServiceFulfillmentRepository,
        bid_repo: BidRepository,
        session
    ) -> Dict[str, float]:
        """Calculate individual score components"""
        scores = {}
        
        # Performance score (based on completion rate)
        if supplier.total_allocations > 0:
            completion_rate = supplier.successful_completions / supplier.total_allocations
            scores["performance"] = completion_rate * 100
        else:
            scores["performance"] = 50  # Default for new suppliers
        
        # Quality score (based on average customer ratings)
        fulfillments = fulfillment_repo.get_by_supplier(supplier.id, status="completed")
        if fulfillments:
            ratings = [f.customer_rating for f in fulfillments if f.customer_rating]
            if ratings:
                avg_rating = sum(ratings) / len(ratings)
                scores["quality"] = avg_rating * 20  # Scale 1-5 to 0-100
            else:
                scores["quality"] = 50
        else:
            scores["quality"] = 50
        
        # Reliability score (based on on-time delivery)
        on_time_count = sum(
            1 for f in fulfillments 
            if f.completed_at and f.expected_completion and f.completed_at <= f.expected_completion
        )
        if fulfillments:
            scores["reliability"] = (on_time_count / len(fulfillments)) * 100
        else:
            scores["reliability"] = 50
        
        # Price competitiveness (based on winning bid ratios)
        bids = bid_repo.get_by_supplier(supplier.id, limit=50)
        winning_bids = [b for b in bids if b.status == BidStatus.WINNER.value]
        if bids:
            win_rate = len(winning_bids) / len(bids)
            scores["price"] = win_rate * 100
        else:
            scores["price"] = 50
        
        # Response time score (placeholder - would need response time tracking)
        scores["response_time"] = 70  # Default
        
        # Compliance score (based on credential status)
        from database.repositories.sully_chain_repository import SupplierCredentialRepository
        cred_repo = SupplierCredentialRepository(session)
        credentials = cred_repo.get_by_supplier(supplier.id)
        if credentials:
            verified_count = sum(
                1 for c in credentials 
                if c.verification_status == CredentialStatus.VERIFIED.value
            )
            scores["compliance"] = (verified_count / len(credentials)) * 100
        else:
            scores["compliance"] = 50
        
        return scores
    
    def _determine_tier(self, overall_score: float) -> str:
        """Determine performance tier based on overall score"""
        if overall_score >= 90:
            return "platinum"
        elif overall_score >= 80:
            return "gold"
        elif overall_score >= 70:
            return "silver"
        elif overall_score >= 60:
            return "bronze"
        else:
            return "standard"
    
    def get_supplier_score(self, supplier_id: str) -> Optional[Dict[str, Any]]:
        """Get latest score for a supplier"""
        session = get_db_session()
        try:
            repo = SupplierScoreRepository(session)
            score = repo.get_latest_score(supplier_id)
            return score.to_dict() if score else None
        finally:
            session.close()
    
    def get_score_history(
        self, 
        supplier_id: str, 
        limit: int = 12
    ) -> List[Dict[str, Any]]:
        """Get score history for a supplier"""
        session = get_db_session()
        try:
            repo = SupplierScoreRepository(session)
            scores = repo.get_score_history(supplier_id, limit)
            return [s.to_dict() for s in scores]
        finally:
            session.close()
    
    def get_top_performers(
        self, 
        supplier_type: str = None, 
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Get top performing suppliers"""
        session = get_db_session()
        try:
            repo = SupplierScoreRepository(session)
            scores = repo.get_top_performers(supplier_type, limit)
            return [s.to_dict() for s in scores]
        finally:
            session.close()


# =============================================================================
# Analytics Service
# =============================================================================

class AnalyticsService:
    """
    Service for generating analytics and insights:
    - Allocation analytics
    - Supplier performance metrics
    - Platform-wide statistics
    """
    
    def record_allocation_analytics(
        self, 
        allocation_id: str
    ) -> Optional[Dict[str, Any]]:
        """Record analytics for a completed allocation"""
        session = get_db_session()
        try:
            alloc_repo = AllocationRepository(session)
            bid_repo = BidRepository(session)
            analytics_repo = AllocationAnalyticsRepository(session)
            fulfillment_repo = ServiceFulfillmentRepository(session)
            
            allocation = alloc_repo.get_by_id(allocation_id)
            if not allocation:
                return None
            
            bids = bid_repo.get_by_allocation(allocation_id)
            
            # Calculate metrics
            bid_amounts = [float(b.bid_amount) for b in bids if b.bid_amount]
            
            analytics_id = str(uuid.uuid4())
            
            analytics = analytics_repo.create(
                id=analytics_id,
                allocation_id=allocation_id,
                total_views=allocation.view_count,
                total_bids=len(bids),
                qualified_bids=len([b for b in bids if b.status != BidStatus.WITHDRAWN.value]),
                avg_bid_amount=sum(bid_amounts) / len(bid_amounts) if bid_amounts else None,
                min_bid_amount=min(bid_amounts) if bid_amounts else None,
                max_bid_amount=max(bid_amounts) if bid_amounts else None,
                winning_bid_amount=allocation.final_amount,
                reserve_price=allocation.reserve_price,
                price_efficiency=float(allocation.reserve_price or 0) / float(allocation.final_amount) if allocation.final_amount else None,
                competition_ratio=len(bids) / allocation.view_count if allocation.view_count > 0 else 0,
                analyzed_at=datetime.utcnow()
            )
            
            return analytics.to_dict() if analytics else None
        finally:
            session.close()
    
    def get_aggregate_stats(
        self, 
        from_date: datetime = None, 
        to_date: datetime = None
    ) -> Dict[str, Any]:
        """Get aggregate platform statistics"""
        session = get_db_session()
        try:
            analytics_repo = AllocationAnalyticsRepository(session)
            return analytics_repo.get_aggregate_stats(from_date, to_date)
        finally:
            session.close()
    
    def get_dashboard_stats(self) -> Dict[str, Any]:
        """Get comprehensive dashboard statistics"""
        session = get_db_session()
        try:
            supplier_repo = SupplierRepository(session)
            alloc_repo = AllocationRepository(session)
            bid_repo = BidRepository(session)
            escrow_repo = EscrowAccountRepository(session)
            
            # Supplier stats
            active_suppliers = len(supplier_repo.get_active_suppliers(limit=10000))
            
            # Allocation stats
            open_allocations = len(alloc_repo.get_open_allocations(limit=10000))
            
            # Escrow stats
            total_escrow = escrow_repo.get_total_held()
            
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "suppliers": {
                    "total_active": active_suppliers,
                },
                "allocations": {
                    "currently_open": open_allocations,
                },
                "financial": {
                    "total_escrow_held": total_escrow,
                }
            }
        finally:
            session.close()


# =============================================================================
# Unified Sully Chain Service
# =============================================================================

class SullyChainService:
    """
    Unified service providing access to all Sully Chain functionality.
    Use this as the main entry point for the Sully Chain system.
    """
    
    def __init__(self):
        self._suppliers = None
        self._allocations = None
        self._bidding = None
        self._fulfillment = None
        self._ledger = None
        self._escrow = None
        self._scoring = None
        self._analytics = None
    
    @property
    def suppliers(self) -> SupplierManagementService:
        if self._suppliers is None:
            self._suppliers = SupplierManagementService()
        return self._suppliers
    
    @property
    def allocations(self) -> AllocationService:
        if self._allocations is None:
            self._allocations = AllocationService()
        return self._allocations
    
    @property
    def bidding(self) -> BiddingService:
        if self._bidding is None:
            self._bidding = BiddingService()
        return self._bidding
    
    @property
    def fulfillment(self) -> FulfillmentService:
        if self._fulfillment is None:
            self._fulfillment = FulfillmentService()
        return self._fulfillment
    
    @property
    def ledger(self) -> LedgerService:
        if self._ledger is None:
            self._ledger = LedgerService()
        return self._ledger
    
    @property
    def escrow(self) -> EscrowService:
        if self._escrow is None:
            self._escrow = EscrowService()
        return self._escrow
    
    @property
    def scoring(self) -> ScoringService:
        if self._scoring is None:
            self._scoring = ScoringService()
        return self._scoring
    
    @property
    def analytics(self) -> AnalyticsService:
        if self._analytics is None:
            self._analytics = AnalyticsService()
        return self._analytics


# Global instance for convenience
sully_chain = SullyChainService()
