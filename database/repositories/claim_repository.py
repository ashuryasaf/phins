"""Claim Repository"""

from typing import Optional, List
from sqlalchemy.orm import Session
from database.models import Claim
from .base import BaseRepository


class ClaimRepository(BaseRepository[Claim]):
    """Repository for Claim operations"""
    
    def __init__(self, session: Session):
        super().__init__(Claim, session)
    
    def get_by_policy(self, policy_id: str) -> List[Claim]:
        """Get all claims for a policy"""
        return self.filter_by(policy_id=policy_id)
    
    def get_by_customer(self, customer_id: str) -> List[Claim]:
        """Get all claims for a customer"""
        return self.filter_by(customer_id=customer_id)
    
    def get_by_status(self, status: str) -> List[Claim]:
        """Get claims by status"""
        return self.filter_by(status=status)
    
    def get_pending_claims(self) -> List[Claim]:
        """Get all pending claims"""
        return self.filter_by(status='pending')
    
    def get_approved_claims(self) -> List[Claim]:
        """Get all approved claims"""
        return self.filter_by(status='approved')
