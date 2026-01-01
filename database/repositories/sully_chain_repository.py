"""
Sully Chain Repositories

Provides data access for all Sully Chain entities including:
- Suppliers and their specialties/credentials
- Service requests and allocations
- Bids and fulfillments
- Ledger entries and analytics
"""

from typing import List, Optional, Dict, Any, Tuple
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, func, desc, asc
from sqlalchemy.exc import SQLAlchemyError
import logging
import json

from .base import BaseRepository
from database.sully_chain_models import (
    Supplier, SupplierSpecialty, SupplierCredential,
    ServiceRequest, Allocation, Bid,
    ServiceFulfillment, ServiceMilestone,
    SullyLedger, ClientInteraction,
    SupplierTransaction, EscrowAccount,
    SupplierScore, AllocationAnalytics,
    SupplierStatus, AllocationStatus, BidStatus, FulfillmentStatus,
    CredentialStatus, LedgerActionType
)

logger = logging.getLogger(__name__)


class SupplierRepository(BaseRepository[Supplier]):
    """Repository for Supplier entity operations"""
    
    def __init__(self, session: Session):
        super().__init__(Supplier, session)
    
    def get_by_code(self, supplier_code: str) -> Optional[Supplier]:
        """Get supplier by unique supplier code"""
        return self.find_one_by(supplier_code=supplier_code)
    
    def get_by_email(self, email: str) -> Optional[Supplier]:
        """Get supplier by email"""
        return self.find_one_by(email=email)
    
    def get_by_type(self, supplier_type: str, status: str = None, limit: int = 100) -> List[Supplier]:
        """Get suppliers by type with optional status filter"""
        try:
            query = self.session.query(Supplier).filter(Supplier.supplier_type == supplier_type)
            if status:
                query = query.filter(Supplier.status == status)
            return query.order_by(desc(Supplier.rating)).limit(limit).all()
        except SQLAlchemyError as e:
            logger.error(f"Error fetching suppliers by type: {e}")
            return []
    
    def get_active_suppliers(self, limit: int = 100, offset: int = 0) -> List[Supplier]:
        """Get all active suppliers"""
        return self.filter_by(status=SupplierStatus.ACTIVE.value)[:limit]
    
    def search_suppliers(
        self, 
        query: str = None,
        supplier_types: List[str] = None,
        min_rating: float = None,
        city: str = None,
        state: str = None,
        has_specialty: str = None,
        limit: int = 50
    ) -> List[Supplier]:
        """Advanced supplier search with multiple criteria"""
        try:
            db_query = self.session.query(Supplier).filter(
                Supplier.status == SupplierStatus.ACTIVE.value
            )
            
            if query:
                db_query = db_query.filter(
                    or_(
                        Supplier.name.ilike(f"%{query}%"),
                        Supplier.email.ilike(f"%{query}%"),
                        Supplier.supplier_code.ilike(f"%{query}%")
                    )
                )
            
            if supplier_types:
                db_query = db_query.filter(Supplier.supplier_type.in_(supplier_types))
            
            if min_rating:
                db_query = db_query.filter(Supplier.rating >= min_rating)
            
            if city:
                db_query = db_query.filter(Supplier.city.ilike(f"%{city}%"))
            
            if state:
                db_query = db_query.filter(Supplier.state == state)
            
            if has_specialty:
                db_query = db_query.join(SupplierSpecialty).filter(
                    SupplierSpecialty.specialty_code == has_specialty
                )
            
            return db_query.order_by(desc(Supplier.rating)).limit(limit).all()
        except SQLAlchemyError as e:
            logger.error(f"Error searching suppliers: {e}")
            return []
    
    def get_top_rated(self, supplier_type: str = None, limit: int = 10) -> List[Supplier]:
        """Get top rated suppliers"""
        try:
            query = self.session.query(Supplier).filter(
                Supplier.status == SupplierStatus.ACTIVE.value
            )
            if supplier_type:
                query = query.filter(Supplier.supplier_type == supplier_type)
            return query.order_by(desc(Supplier.rating)).limit(limit).all()
        except SQLAlchemyError as e:
            logger.error(f"Error fetching top rated suppliers: {e}")
            return []
    
    def update_rating(self, supplier_id: str, new_rating: float) -> bool:
        """Update supplier rating"""
        try:
            supplier = self.get_by_id(supplier_id)
            if supplier:
                supplier.rating = new_rating
                supplier.updated_date = datetime.utcnow()
                self.session.commit()
                return True
            return False
        except SQLAlchemyError as e:
            logger.error(f"Error updating supplier rating: {e}")
            self.session.rollback()
            return False
    
    def increment_allocations(self, supplier_id: str, successful: bool = True) -> bool:
        """Increment allocation counters for supplier"""
        try:
            supplier = self.get_by_id(supplier_id)
            if supplier:
                supplier.total_allocations += 1
                if successful:
                    supplier.successful_completions += 1
                supplier.last_active_at = datetime.utcnow()
                self.session.commit()
                return True
            return False
        except SQLAlchemyError as e:
            logger.error(f"Error incrementing allocations: {e}")
            self.session.rollback()
            return False
    
    def get_suppliers_with_expiring_credentials(self, days: int = 30) -> List[Supplier]:
        """Get suppliers with credentials expiring within specified days"""
        try:
            expiry_threshold = datetime.utcnow() + timedelta(days=days)
            return self.session.query(Supplier).join(SupplierCredential).filter(
                and_(
                    SupplierCredential.expiry_date <= expiry_threshold,
                    SupplierCredential.verification_status == CredentialStatus.VERIFIED.value
                )
            ).distinct().all()
        except SQLAlchemyError as e:
            logger.error(f"Error fetching suppliers with expiring credentials: {e}")
            return []


class SupplierSpecialtyRepository(BaseRepository[SupplierSpecialty]):
    """Repository for SupplierSpecialty entity operations"""
    
    def __init__(self, session: Session):
        super().__init__(SupplierSpecialty, session)
    
    def get_by_supplier(self, supplier_id: str) -> List[SupplierSpecialty]:
        """Get all specialties for a supplier"""
        return self.filter_by(supplier_id=supplier_id)
    
    def get_primary_specialty(self, supplier_id: str) -> Optional[SupplierSpecialty]:
        """Get primary specialty for a supplier"""
        return self.find_one_by(supplier_id=supplier_id, is_primary=True)
    
    def get_suppliers_by_specialty(self, specialty_code: str) -> List[str]:
        """Get supplier IDs with a specific specialty"""
        try:
            specialties = self.filter_by(specialty_code=specialty_code)
            return [s.supplier_id for s in specialties]
        except SQLAlchemyError as e:
            logger.error(f"Error fetching suppliers by specialty: {e}")
            return []


class SupplierCredentialRepository(BaseRepository[SupplierCredential]):
    """Repository for SupplierCredential entity operations"""
    
    def __init__(self, session: Session):
        super().__init__(SupplierCredential, session)
    
    def get_by_supplier(self, supplier_id: str) -> List[SupplierCredential]:
        """Get all credentials for a supplier"""
        return self.filter_by(supplier_id=supplier_id)
    
    def get_verified_credentials(self, supplier_id: str) -> List[SupplierCredential]:
        """Get verified credentials for a supplier"""
        return self.filter_by(
            supplier_id=supplier_id, 
            verification_status=CredentialStatus.VERIFIED.value
        )
    
    def get_expiring_credentials(self, days: int = 30) -> List[SupplierCredential]:
        """Get credentials expiring within specified days"""
        try:
            expiry_threshold = datetime.utcnow() + timedelta(days=days)
            return self.session.query(SupplierCredential).filter(
                and_(
                    SupplierCredential.expiry_date <= expiry_threshold,
                    SupplierCredential.verification_status == CredentialStatus.VERIFIED.value
                )
            ).order_by(asc(SupplierCredential.expiry_date)).all()
        except SQLAlchemyError as e:
            logger.error(f"Error fetching expiring credentials: {e}")
            return []
    
    def verify_credential(self, credential_id: str, verified_by: str, notes: str = None) -> bool:
        """Mark a credential as verified"""
        try:
            cred = self.get_by_id(credential_id)
            if cred:
                cred.verification_status = CredentialStatus.VERIFIED.value
                cred.verified_date = datetime.utcnow()
                cred.verified_by = verified_by
                cred.verification_notes = notes
                self.session.commit()
                return True
            return False
        except SQLAlchemyError as e:
            logger.error(f"Error verifying credential: {e}")
            self.session.rollback()
            return False


class ServiceRequestRepository(BaseRepository[ServiceRequest]):
    """Repository for ServiceRequest entity operations"""
    
    def __init__(self, session: Session):
        super().__init__(ServiceRequest, session)
    
    def get_by_code(self, request_code: str) -> Optional[ServiceRequest]:
        """Get service request by code"""
        return self.find_one_by(request_code=request_code)
    
    def get_by_customer(self, customer_id: str, status: str = None) -> List[ServiceRequest]:
        """Get service requests for a customer"""
        try:
            query = self.session.query(ServiceRequest).filter(
                ServiceRequest.customer_id == customer_id
            )
            if status:
                query = query.filter(ServiceRequest.status == status)
            return query.order_by(desc(ServiceRequest.request_date)).all()
        except SQLAlchemyError as e:
            logger.error(f"Error fetching customer requests: {e}")
            return []
    
    def get_by_policy(self, policy_id: str) -> List[ServiceRequest]:
        """Get service requests for a policy"""
        return self.filter_by(policy_id=policy_id)
    
    def get_by_claim(self, claim_id: str) -> List[ServiceRequest]:
        """Get service requests for a claim"""
        return self.filter_by(claim_id=claim_id)
    
    def get_pending_requests(self, limit: int = 50) -> List[ServiceRequest]:
        """Get pending service requests awaiting allocation"""
        try:
            return self.session.query(ServiceRequest).filter(
                ServiceRequest.status.in_(['submitted', 'draft'])
            ).order_by(
                desc(ServiceRequest.urgency_level),
                asc(ServiceRequest.request_date)
            ).limit(limit).all()
        except SQLAlchemyError as e:
            logger.error(f"Error fetching pending requests: {e}")
            return []


class AllocationRepository(BaseRepository[Allocation]):
    """Repository for Allocation entity operations"""
    
    def __init__(self, session: Session):
        super().__init__(Allocation, session)
    
    def get_by_code(self, allocation_code: str) -> Optional[Allocation]:
        """Get allocation by code"""
        return self.find_one_by(allocation_code=allocation_code)
    
    def get_open_allocations(self, supplier_type: str = None, limit: int = 50) -> List[Allocation]:
        """Get open allocations available for bidding"""
        try:
            query = self.session.query(Allocation).filter(
                and_(
                    Allocation.status.in_([AllocationStatus.OPEN.value, AllocationStatus.BIDDING.value]),
                    Allocation.closes_at > datetime.utcnow()
                )
            )
            
            if supplier_type:
                # Filter by eligible supplier types (stored as JSON array)
                query = query.filter(
                    Allocation.eligible_supplier_types.contains(f'"{supplier_type}"')
                )
            
            return query.order_by(asc(Allocation.closes_at)).limit(limit).all()
        except SQLAlchemyError as e:
            logger.error(f"Error fetching open allocations: {e}")
            return []
    
    def get_by_service_request(self, service_request_id: str) -> List[Allocation]:
        """Get allocations for a service request"""
        return self.filter_by(service_request_id=service_request_id)
    
    def get_closing_soon(self, hours: int = 24) -> List[Allocation]:
        """Get allocations closing within specified hours"""
        try:
            closing_threshold = datetime.utcnow() + timedelta(hours=hours)
            return self.session.query(Allocation).filter(
                and_(
                    Allocation.status.in_([AllocationStatus.OPEN.value, AllocationStatus.BIDDING.value]),
                    Allocation.closes_at <= closing_threshold,
                    Allocation.closes_at > datetime.utcnow()
                )
            ).order_by(asc(Allocation.closes_at)).all()
        except SQLAlchemyError as e:
            logger.error(f"Error fetching closing allocations: {e}")
            return []
    
    def get_awaiting_evaluation(self) -> List[Allocation]:
        """Get allocations that have closed and await winner selection"""
        try:
            return self.session.query(Allocation).filter(
                and_(
                    Allocation.status == AllocationStatus.BIDDING.value,
                    Allocation.closes_at <= datetime.utcnow(),
                    Allocation.winning_bid_id.is_(None)
                )
            ).all()
        except SQLAlchemyError as e:
            logger.error(f"Error fetching allocations awaiting evaluation: {e}")
            return []
    
    def award_allocation(
        self, 
        allocation_id: str, 
        winning_bid_id: str, 
        winning_supplier_id: str,
        final_amount: float,
        awarded_by: str
    ) -> bool:
        """Award an allocation to a winning bid"""
        try:
            allocation = self.get_by_id(allocation_id)
            if allocation:
                allocation.status = AllocationStatus.AWARDED.value
                allocation.winning_bid_id = winning_bid_id
                allocation.winning_supplier_id = winning_supplier_id
                allocation.final_amount = final_amount
                allocation.awarded_by = awarded_by
                allocation.awarded_at = datetime.utcnow()
                self.session.commit()
                return True
            return False
        except SQLAlchemyError as e:
            logger.error(f"Error awarding allocation: {e}")
            self.session.rollback()
            return False
    
    def increment_view_count(self, allocation_id: str) -> bool:
        """Increment view count for an allocation"""
        try:
            allocation = self.get_by_id(allocation_id)
            if allocation:
                allocation.view_count += 1
                self.session.commit()
                return True
            return False
        except SQLAlchemyError as e:
            logger.error(f"Error incrementing view count: {e}")
            self.session.rollback()
            return False


class BidRepository(BaseRepository[Bid]):
    """Repository for Bid entity operations"""
    
    def __init__(self, session: Session):
        super().__init__(Bid, session)
    
    def get_by_code(self, bid_code: str) -> Optional[Bid]:
        """Get bid by code"""
        return self.find_one_by(bid_code=bid_code)
    
    def get_by_allocation(self, allocation_id: str, status: str = None) -> List[Bid]:
        """Get all bids for an allocation"""
        try:
            query = self.session.query(Bid).filter(Bid.allocation_id == allocation_id)
            if status:
                query = query.filter(Bid.status == status)
            return query.order_by(asc(Bid.bid_amount)).all()
        except SQLAlchemyError as e:
            logger.error(f"Error fetching bids by allocation: {e}")
            return []
    
    def get_by_supplier(self, supplier_id: str, limit: int = 50) -> List[Bid]:
        """Get all bids by a supplier"""
        try:
            return self.session.query(Bid).filter(
                Bid.supplier_id == supplier_id
            ).order_by(desc(Bid.submitted_at)).limit(limit).all()
        except SQLAlchemyError as e:
            logger.error(f"Error fetching supplier bids: {e}")
            return []
    
    def get_supplier_bid_for_allocation(self, allocation_id: str, supplier_id: str) -> Optional[Bid]:
        """Get a supplier's bid for a specific allocation"""
        return self.find_one_by(allocation_id=allocation_id, supplier_id=supplier_id)
    
    def get_winning_bids(self, supplier_id: str = None, limit: int = 50) -> List[Bid]:
        """Get winning bids"""
        try:
            query = self.session.query(Bid).filter(Bid.status == BidStatus.WINNER.value)
            if supplier_id:
                query = query.filter(Bid.supplier_id == supplier_id)
            return query.order_by(desc(Bid.submitted_at)).limit(limit).all()
        except SQLAlchemyError as e:
            logger.error(f"Error fetching winning bids: {e}")
            return []
    
    def get_ranked_bids(self, allocation_id: str) -> List[Bid]:
        """Get all submitted bids for an allocation, ranked by score"""
        try:
            return self.session.query(Bid).filter(
                and_(
                    Bid.allocation_id == allocation_id,
                    Bid.status == BidStatus.SUBMITTED.value
                )
            ).order_by(
                desc(Bid.ai_score),
                asc(Bid.bid_amount)
            ).all()
        except SQLAlchemyError as e:
            logger.error(f"Error fetching ranked bids: {e}")
            return []
    
    def select_winner(self, bid_id: str, reviewed_by: str, notes: str = None) -> bool:
        """Mark a bid as the winner"""
        try:
            bid = self.get_by_id(bid_id)
            if bid:
                bid.status = BidStatus.WINNER.value
                bid.reviewed_by = reviewed_by
                bid.reviewed_at = datetime.utcnow()
                bid.review_notes = notes
                bid.final_rank = 1
                self.session.commit()
                return True
            return False
        except SQLAlchemyError as e:
            logger.error(f"Error selecting winner: {e}")
            self.session.rollback()
            return False


class ServiceFulfillmentRepository(BaseRepository[ServiceFulfillment]):
    """Repository for ServiceFulfillment entity operations"""
    
    def __init__(self, session: Session):
        super().__init__(ServiceFulfillment, session)
    
    def get_by_code(self, fulfillment_code: str) -> Optional[ServiceFulfillment]:
        """Get fulfillment by code"""
        return self.find_one_by(fulfillment_code=fulfillment_code)
    
    def get_by_allocation(self, allocation_id: str) -> Optional[ServiceFulfillment]:
        """Get fulfillment for an allocation"""
        return self.find_one_by(allocation_id=allocation_id)
    
    def get_by_supplier(self, supplier_id: str, status: str = None) -> List[ServiceFulfillment]:
        """Get fulfillments for a supplier"""
        try:
            query = self.session.query(ServiceFulfillment).filter(
                ServiceFulfillment.supplier_id == supplier_id
            )
            if status:
                query = query.filter(ServiceFulfillment.status == status)
            return query.order_by(desc(ServiceFulfillment.started_at)).all()
        except SQLAlchemyError as e:
            logger.error(f"Error fetching supplier fulfillments: {e}")
            return []
    
    def get_active_fulfillments(self, limit: int = 50) -> List[ServiceFulfillment]:
        """Get currently active fulfillments"""
        try:
            return self.session.query(ServiceFulfillment).filter(
                ServiceFulfillment.status.in_([
                    FulfillmentStatus.PENDING.value,
                    FulfillmentStatus.IN_PROGRESS.value,
                    FulfillmentStatus.DELIVERED.value,
                    FulfillmentStatus.UNDER_REVIEW.value
                ])
            ).order_by(asc(ServiceFulfillment.expected_completion)).limit(limit).all()
        except SQLAlchemyError as e:
            logger.error(f"Error fetching active fulfillments: {e}")
            return []
    
    def get_overdue_fulfillments(self) -> List[ServiceFulfillment]:
        """Get overdue fulfillments"""
        try:
            return self.session.query(ServiceFulfillment).filter(
                and_(
                    ServiceFulfillment.status.in_([
                        FulfillmentStatus.PENDING.value,
                        FulfillmentStatus.IN_PROGRESS.value
                    ]),
                    ServiceFulfillment.expected_completion < datetime.utcnow()
                )
            ).all()
        except SQLAlchemyError as e:
            logger.error(f"Error fetching overdue fulfillments: {e}")
            return []
    
    def complete_fulfillment(
        self, 
        fulfillment_id: str, 
        final_amount: float,
        quality_score: float,
        notes: str = None
    ) -> bool:
        """Mark a fulfillment as completed"""
        try:
            fulfillment = self.get_by_id(fulfillment_id)
            if fulfillment:
                fulfillment.status = FulfillmentStatus.COMPLETED.value
                fulfillment.completed_at = datetime.utcnow()
                fulfillment.final_amount = final_amount
                fulfillment.quality_score = quality_score
                fulfillment.completion_notes = notes
                self.session.commit()
                return True
            return False
        except SQLAlchemyError as e:
            logger.error(f"Error completing fulfillment: {e}")
            self.session.rollback()
            return False


class ServiceMilestoneRepository(BaseRepository[ServiceMilestone]):
    """Repository for ServiceMilestone entity operations"""
    
    def __init__(self, session: Session):
        super().__init__(ServiceMilestone, session)
    
    def get_by_fulfillment(self, fulfillment_id: str) -> List[ServiceMilestone]:
        """Get all milestones for a fulfillment"""
        try:
            return self.session.query(ServiceMilestone).filter(
                ServiceMilestone.fulfillment_id == fulfillment_id
            ).order_by(asc(ServiceMilestone.sequence_order)).all()
        except SQLAlchemyError as e:
            logger.error(f"Error fetching milestones: {e}")
            return []
    
    def get_pending_milestones(self, fulfillment_id: str) -> List[ServiceMilestone]:
        """Get pending milestones for a fulfillment"""
        return self.filter_by(fulfillment_id=fulfillment_id, status='pending')
    
    def complete_milestone(
        self, 
        milestone_id: str, 
        approved_by: str = None,
        notes: str = None
    ) -> bool:
        """Mark a milestone as completed"""
        try:
            milestone = self.get_by_id(milestone_id)
            if milestone:
                milestone.status = 'completed'
                milestone.completed_date = datetime.utcnow()
                milestone.approved_by = approved_by
                milestone.approved_at = datetime.utcnow()
                milestone.approval_notes = notes
                self.session.commit()
                return True
            return False
        except SQLAlchemyError as e:
            logger.error(f"Error completing milestone: {e}")
            self.session.rollback()
            return False


class SullyLedgerRepository(BaseRepository[SullyLedger]):
    """Repository for SullyLedger entity operations - immutable audit trail"""
    
    def __init__(self, session: Session):
        super().__init__(SullyLedger, session)
    
    def get_by_code(self, ledger_code: str) -> Optional[SullyLedger]:
        """Get ledger entry by code"""
        return self.find_one_by(ledger_code=ledger_code)
    
    def get_entity_history(
        self, 
        entity_type: str, 
        entity_id: str,
        limit: int = 100
    ) -> List[SullyLedger]:
        """Get complete history for an entity"""
        try:
            return self.session.query(SullyLedger).filter(
                and_(
                    SullyLedger.entity_type == entity_type,
                    SullyLedger.entity_id == entity_id
                )
            ).order_by(desc(SullyLedger.sequence_number)).limit(limit).all()
        except SQLAlchemyError as e:
            logger.error(f"Error fetching entity history: {e}")
            return []
    
    def get_actor_history(
        self, 
        actor_type: str, 
        actor_id: str,
        limit: int = 100
    ) -> List[SullyLedger]:
        """Get all actions by an actor"""
        try:
            return self.session.query(SullyLedger).filter(
                and_(
                    SullyLedger.actor_type == actor_type,
                    SullyLedger.actor_id == actor_id
                )
            ).order_by(desc(SullyLedger.timestamp)).limit(limit).all()
        except SQLAlchemyError as e:
            logger.error(f"Error fetching actor history: {e}")
            return []
    
    def get_by_action_type(
        self, 
        action_type: str,
        from_date: datetime = None,
        to_date: datetime = None,
        limit: int = 100
    ) -> List[SullyLedger]:
        """Get ledger entries by action type"""
        try:
            query = self.session.query(SullyLedger).filter(
                SullyLedger.action_type == action_type
            )
            if from_date:
                query = query.filter(SullyLedger.timestamp >= from_date)
            if to_date:
                query = query.filter(SullyLedger.timestamp <= to_date)
            return query.order_by(desc(SullyLedger.timestamp)).limit(limit).all()
        except SQLAlchemyError as e:
            logger.error(f"Error fetching by action type: {e}")
            return []
    
    def get_last_entry(self) -> Optional[SullyLedger]:
        """Get the most recent ledger entry for hash chaining"""
        try:
            return self.session.query(SullyLedger).order_by(
                desc(SullyLedger.sequence_number)
            ).first()
        except SQLAlchemyError as e:
            logger.error(f"Error fetching last ledger entry: {e}")
            return None
    
    def get_next_sequence_number(self) -> int:
        """Get next sequence number for new entry"""
        try:
            last = self.get_last_entry()
            return (last.sequence_number + 1) if last else 1
        except SQLAlchemyError as e:
            logger.error(f"Error getting next sequence: {e}")
            return 1
    
    def verify_chain_integrity(
        self, 
        from_sequence: int = 1, 
        to_sequence: int = None
    ) -> Tuple[bool, List[Dict]]:
        """Verify ledger integrity by checking hash chain"""
        try:
            query = self.session.query(SullyLedger).filter(
                SullyLedger.sequence_number >= from_sequence
            )
            if to_sequence:
                query = query.filter(SullyLedger.sequence_number <= to_sequence)
            
            entries = query.order_by(asc(SullyLedger.sequence_number)).all()
            
            errors = []
            prev_hash = None
            
            for entry in entries:
                if prev_hash and entry.previous_hash != prev_hash:
                    errors.append({
                        'sequence': entry.sequence_number,
                        'expected_prev_hash': prev_hash,
                        'actual_prev_hash': entry.previous_hash
                    })
                prev_hash = entry.hash
            
            return (len(errors) == 0, errors)
        except SQLAlchemyError as e:
            logger.error(f"Error verifying chain integrity: {e}")
            return (False, [{'error': str(e)}])
    
    def get_audit_report(
        self,
        entity_type: str = None,
        action_types: List[str] = None,
        from_date: datetime = None,
        to_date: datetime = None,
        limit: int = 1000
    ) -> List[SullyLedger]:
        """Generate audit report with flexible filters"""
        try:
            query = self.session.query(SullyLedger)
            
            if entity_type:
                query = query.filter(SullyLedger.entity_type == entity_type)
            if action_types:
                query = query.filter(SullyLedger.action_type.in_(action_types))
            if from_date:
                query = query.filter(SullyLedger.timestamp >= from_date)
            if to_date:
                query = query.filter(SullyLedger.timestamp <= to_date)
            
            return query.order_by(asc(SullyLedger.sequence_number)).limit(limit).all()
        except SQLAlchemyError as e:
            logger.error(f"Error generating audit report: {e}")
            return []


class ClientInteractionRepository(BaseRepository[ClientInteraction]):
    """Repository for ClientInteraction entity operations"""
    
    def __init__(self, session: Session):
        super().__init__(ClientInteraction, session)
    
    def get_by_customer(self, customer_id: str, limit: int = 50) -> List[ClientInteraction]:
        """Get interactions for a customer"""
        try:
            return self.session.query(ClientInteraction).filter(
                ClientInteraction.customer_id == customer_id
            ).order_by(desc(ClientInteraction.interaction_date)).limit(limit).all()
        except SQLAlchemyError as e:
            logger.error(f"Error fetching customer interactions: {e}")
            return []
    
    def get_by_supplier(self, supplier_id: str, limit: int = 50) -> List[ClientInteraction]:
        """Get interactions for a supplier"""
        try:
            return self.session.query(ClientInteraction).filter(
                ClientInteraction.supplier_id == supplier_id
            ).order_by(desc(ClientInteraction.interaction_date)).limit(limit).all()
        except SQLAlchemyError as e:
            logger.error(f"Error fetching supplier interactions: {e}")
            return []
    
    def get_pending_follow_ups(self) -> List[ClientInteraction]:
        """Get interactions requiring follow-up"""
        try:
            return self.session.query(ClientInteraction).filter(
                and_(
                    ClientInteraction.follow_up_required == True,
                    or_(
                        ClientInteraction.follow_up_date.is_(None),
                        ClientInteraction.follow_up_date <= datetime.utcnow()
                    )
                )
            ).order_by(asc(ClientInteraction.follow_up_date)).all()
        except SQLAlchemyError as e:
            logger.error(f"Error fetching pending follow-ups: {e}")
            return []


class SupplierTransactionRepository(BaseRepository[SupplierTransaction]):
    """Repository for SupplierTransaction entity operations"""
    
    def __init__(self, session: Session):
        super().__init__(SupplierTransaction, session)
    
    def get_by_supplier(self, supplier_id: str, limit: int = 100) -> List[SupplierTransaction]:
        """Get transactions for a supplier"""
        try:
            return self.session.query(SupplierTransaction).filter(
                SupplierTransaction.supplier_id == supplier_id
            ).order_by(desc(SupplierTransaction.transaction_date)).limit(limit).all()
        except SQLAlchemyError as e:
            logger.error(f"Error fetching supplier transactions: {e}")
            return []
    
    def get_by_allocation(self, allocation_id: str) -> List[SupplierTransaction]:
        """Get transactions for an allocation"""
        return self.filter_by(allocation_id=allocation_id)
    
    def get_supplier_balance(self, supplier_id: str) -> float:
        """Calculate supplier's current balance from transactions"""
        try:
            result = self.session.query(
                func.sum(SupplierTransaction.net_amount)
            ).filter(
                and_(
                    SupplierTransaction.supplier_id == supplier_id,
                    SupplierTransaction.status == 'completed'
                )
            ).scalar()
            return float(result) if result else 0.0
        except SQLAlchemyError as e:
            logger.error(f"Error calculating supplier balance: {e}")
            return 0.0


class EscrowAccountRepository(BaseRepository[EscrowAccount]):
    """Repository for EscrowAccount entity operations"""
    
    def __init__(self, session: Session):
        super().__init__(EscrowAccount, session)
    
    def get_by_code(self, escrow_code: str) -> Optional[EscrowAccount]:
        """Get escrow account by code"""
        return self.find_one_by(escrow_code=escrow_code)
    
    def get_by_allocation(self, allocation_id: str) -> Optional[EscrowAccount]:
        """Get escrow account for an allocation"""
        return self.find_one_by(allocation_id=allocation_id)
    
    def get_active_escrows(self) -> List[EscrowAccount]:
        """Get all active escrow accounts"""
        return self.filter_by(status='funded')
    
    def get_total_held(self) -> float:
        """Get total amount held in escrow"""
        try:
            result = self.session.query(
                func.sum(EscrowAccount.held_amount - EscrowAccount.released_amount - EscrowAccount.refunded_amount)
            ).filter(
                EscrowAccount.status.in_(['created', 'funded', 'partially_released'])
            ).scalar()
            return float(result) if result else 0.0
        except SQLAlchemyError as e:
            logger.error(f"Error calculating total escrow held: {e}")
            return 0.0
    
    def release_escrow(self, escrow_id: str, amount: float, notes: str = None) -> bool:
        """Release funds from escrow"""
        try:
            escrow = self.get_by_id(escrow_id)
            if escrow:
                escrow.released_amount += amount
                if escrow.released_amount >= escrow.held_amount:
                    escrow.status = 'released'
                    escrow.released_at = datetime.utcnow()
                else:
                    escrow.status = 'partially_released'
                escrow.release_notes = notes
                self.session.commit()
                return True
            return False
        except SQLAlchemyError as e:
            logger.error(f"Error releasing escrow: {e}")
            self.session.rollback()
            return False


class SupplierScoreRepository(BaseRepository[SupplierScore]):
    """Repository for SupplierScore entity operations"""
    
    def __init__(self, session: Session):
        super().__init__(SupplierScore, session)
    
    def get_latest_score(self, supplier_id: str) -> Optional[SupplierScore]:
        """Get the most recent score for a supplier"""
        try:
            return self.session.query(SupplierScore).filter(
                SupplierScore.supplier_id == supplier_id
            ).order_by(desc(SupplierScore.calculated_at)).first()
        except SQLAlchemyError as e:
            logger.error(f"Error fetching latest score: {e}")
            return None
    
    def get_score_history(self, supplier_id: str, limit: int = 12) -> List[SupplierScore]:
        """Get score history for a supplier"""
        try:
            return self.session.query(SupplierScore).filter(
                SupplierScore.supplier_id == supplier_id
            ).order_by(desc(SupplierScore.calculated_at)).limit(limit).all()
        except SQLAlchemyError as e:
            logger.error(f"Error fetching score history: {e}")
            return []
    
    def get_top_performers(self, supplier_type: str = None, limit: int = 10) -> List[SupplierScore]:
        """Get top performing suppliers by score"""
        try:
            # Get latest scores only (one per supplier)
            subquery = self.session.query(
                SupplierScore.supplier_id,
                func.max(SupplierScore.calculated_at).label('max_date')
            ).group_by(SupplierScore.supplier_id).subquery()
            
            query = self.session.query(SupplierScore).join(
                subquery,
                and_(
                    SupplierScore.supplier_id == subquery.c.supplier_id,
                    SupplierScore.calculated_at == subquery.c.max_date
                )
            )
            
            if supplier_type:
                query = query.join(Supplier).filter(Supplier.supplier_type == supplier_type)
            
            return query.order_by(desc(SupplierScore.overall_score)).limit(limit).all()
        except SQLAlchemyError as e:
            logger.error(f"Error fetching top performers: {e}")
            return []


class AllocationAnalyticsRepository(BaseRepository[AllocationAnalytics]):
    """Repository for AllocationAnalytics entity operations"""
    
    def __init__(self, session: Session):
        super().__init__(AllocationAnalytics, session)
    
    def get_by_allocation(self, allocation_id: str) -> Optional[AllocationAnalytics]:
        """Get analytics for an allocation"""
        return self.find_one_by(allocation_id=allocation_id)
    
    def get_aggregate_stats(
        self, 
        from_date: datetime = None, 
        to_date: datetime = None
    ) -> Dict[str, Any]:
        """Get aggregate statistics for allocations"""
        try:
            query = self.session.query(
                func.count(AllocationAnalytics.id).label('total_allocations'),
                func.avg(AllocationAnalytics.total_bids).label('avg_bids'),
                func.avg(AllocationAnalytics.price_efficiency).label('avg_efficiency'),
                func.avg(AllocationAnalytics.time_to_award_hours).label('avg_time_to_award'),
                func.sum(AllocationAnalytics.winning_bid_amount).label('total_value')
            )
            
            if from_date:
                query = query.filter(AllocationAnalytics.analyzed_at >= from_date)
            if to_date:
                query = query.filter(AllocationAnalytics.analyzed_at <= to_date)
            
            result = query.first()
            
            return {
                'total_allocations': result.total_allocations or 0,
                'avg_bids_per_allocation': float(result.avg_bids or 0),
                'avg_price_efficiency': float(result.avg_efficiency or 0),
                'avg_time_to_award_hours': float(result.avg_time_to_award or 0),
                'total_awarded_value': float(result.total_value or 0)
            }
        except SQLAlchemyError as e:
            logger.error(f"Error calculating aggregate stats: {e}")
            return {}
