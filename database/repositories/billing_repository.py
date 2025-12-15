"""Billing Repository"""

from typing import Optional, List
from sqlalchemy.orm import Session
from database.models import Bill
from .base import BaseRepository


class BillingRepository(BaseRepository[Bill]):
    """Repository for Bill operations"""
    
    def __init__(self, session: Session):
        super().__init__(Bill, session)
    
    def get_by_policy(self, policy_id: str) -> List[Bill]:
        """Get all bills for a policy"""
        return self.filter_by(policy_id=policy_id)
    
    def get_by_customer(self, customer_id: str) -> List[Bill]:
        """Get all bills for a customer"""
        return self.filter_by(customer_id=customer_id)
    
    def get_by_status(self, status: str) -> List[Bill]:
        """Get bills by status"""
        return self.filter_by(status=status)
    
    def get_outstanding_bills(self) -> List[Bill]:
        """Get all outstanding bills"""
        return self.filter_by(status='outstanding')
    
    def get_overdue_bills(self) -> List[Bill]:
        """Get all overdue bills"""
        return self.filter_by(status='overdue')
