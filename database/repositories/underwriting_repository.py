"""Underwriting Repository"""

from typing import Optional, List
from sqlalchemy.orm import Session
from database.models import UnderwritingApplication
from .base import BaseRepository


class UnderwritingRepository(BaseRepository[UnderwritingApplication]):
    """Repository for UnderwritingApplication operations"""
    
    def __init__(self, session: Session):
        super().__init__(UnderwritingApplication, session)
    
    def get_by_policy(self, policy_id: str) -> Optional[UnderwritingApplication]:
        """Get underwriting application for a policy"""
        return self.find_one_by(policy_id=policy_id)
    
    def get_by_customer(self, customer_id: str) -> List[UnderwritingApplication]:
        """Get all underwriting applications for a customer"""
        return self.filter_by(customer_id=customer_id)
    
    def get_by_status(self, status: str) -> List[UnderwritingApplication]:
        """Get underwriting applications by status"""
        return self.filter_by(status=status)
    
    def get_pending_applications(self) -> List[UnderwritingApplication]:
        """Get all pending applications"""
        return self.filter_by(status='pending')
