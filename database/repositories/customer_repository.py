"""Customer Repository"""

from typing import Optional, List
from sqlalchemy.orm import Session
from sqlalchemy import func
from database.models import Customer
from .base import BaseRepository


class CustomerRepository(BaseRepository[Customer]):
    """Repository for Customer operations"""
    
    def __init__(self, session: Session):
        super().__init__(Customer, session)
    
    def get_by_email(self, email: str) -> Optional[Customer]:
        """Get customer by email address"""
        return self.find_one_by(email=email)

    def get_by_email_ci(self, email: str) -> Optional[Customer]:
        """Case-insensitive lookup by email (for legacy mixed-case records)."""
        try:
            e = str(email or "").strip()
            if not e:
                return None
            return self.session.query(Customer).filter(func.lower(Customer.email) == e.lower()).first()
        except Exception:
            return None
    
    def search_by_name(self, name: str) -> List[Customer]:
        """Search customers by name (partial match)"""
        try:
            return self.session.query(Customer).filter(
                Customer.name.ilike(f'%{name}%')
            ).all()
        except Exception:
            return []
    
    def get_with_policies(self, customer_id: str) -> Optional[Customer]:
        """Get customer with all policies loaded"""
        try:
            from sqlalchemy.orm import joinedload
            return self.session.query(Customer).options(
                joinedload(Customer.policies)
            ).filter(Customer.id == customer_id).first()
        except Exception:
            return None
