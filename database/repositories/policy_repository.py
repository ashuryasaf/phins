"""Policy Repository"""

from typing import Optional, List
from sqlalchemy.orm import Session
from database.models import Policy
from .base import BaseRepository


class PolicyRepository(BaseRepository[Policy]):
    """Repository for Policy operations"""
    
    def __init__(self, session: Session):
        super().__init__(Policy, session)
    
    def get_by_customer(self, customer_id: str) -> List[Policy]:
        """Get all policies for a customer"""
        return self.filter_by(customer_id=customer_id)
    
    def get_active_policies(self) -> List[Policy]:
        """Get all active policies"""
        return self.filter_by(status='active')
    
    def get_by_status(self, status: str) -> List[Policy]:
        """Get policies by status"""
        return self.filter_by(status=status)
    
    def get_by_type(self, policy_type: str) -> List[Policy]:
        """Get policies by type"""
        return self.filter_by(type=policy_type)
    
    def get_pending_underwriting(self) -> List[Policy]:
        """Get policies pending underwriting"""
        return self.filter_by(status='pending_underwriting')
