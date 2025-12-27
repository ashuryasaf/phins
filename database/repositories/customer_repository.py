"""Customer Repository"""

from typing import Optional, List
from sqlalchemy.orm import Session
from datetime import datetime
from database.models import Customer
from .base import BaseRepository


class CustomerRepository(BaseRepository[Customer]):
    """
    Repository for Customer operations
    
    Customers are policyholders with unified profile + authentication.
    For internal staff, use UserRepository instead.
    """
    
    def __init__(self, session: Session):
        super().__init__(Customer, session)
    
    def get_by_email(self, email: str) -> Optional[Customer]:
        """Get customer by email address (also used for login)"""
        return self.find_one_by(email=email.lower() if email else None)
    
    def authenticate(self, email: str, password_hash: str) -> Optional[Customer]:
        """
        Authenticate customer by email and verify password hash matches.
        Returns customer if auth succeeds, None otherwise.
        
        Note: Password verification should be done at service layer using
        proper PBKDF2 comparison. This just fetches the customer for verification.
        """
        customer = self.get_by_email(email)
        if customer and customer.portal_active and customer.password_hash:
            return customer
        return None
    
    def update_last_login(self, customer_id: str) -> bool:
        """Update last login timestamp"""
        try:
            customer = self.get_by_id(customer_id)
            if customer:
                customer.last_login = datetime.utcnow()
                self.session.commit()
                return True
            return False
        except Exception:
            self.session.rollback()
            return False
    
    def set_portal_credentials(self, customer_id: str, password_hash: str, password_salt: str) -> bool:
        """Set or update customer portal credentials"""
        try:
            customer = self.get_by_id(customer_id)
            if customer:
                customer.password_hash = password_hash
                customer.password_salt = password_salt
                customer.portal_active = True
                self.session.commit()
                return True
            return False
        except Exception:
            self.session.rollback()
            return False
    
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
    
    def get_active_portal_customers(self) -> List[Customer]:
        """Get all customers with active portal access"""
        return self.filter_by(portal_active=True)
