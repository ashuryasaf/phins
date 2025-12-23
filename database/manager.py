"""
Database Manager

Provides a high-level interface to all repositories for use in the web server.
Handles session management and provides a clean API for database operations.
"""

from typing import Optional, List, Dict, Any
from contextlib import contextmanager
from sqlalchemy.orm import Session
import logging

from database import get_db_session
from database.repositories import (
    CustomerRepository,
    PolicyRepository,
    ClaimRepository,
    UnderwritingRepository,
    BillingRepository,
    UserRepository,
    SessionRepository,
    AuditRepository,
    ActuarialRepository,
    TokenRepository,
)

logger = logging.getLogger(__name__)


class DatabaseManager:
    """
    High-level database manager that provides access to all repositories.
    
    Usage:
        db_manager = DatabaseManager()
        with db_manager.session_scope() as session:
            customer = db_manager.customers.get_by_id('CUST-123')
    """
    
    def __init__(self, session: Optional[Session] = None):
        """
        Initialize database manager.
        
        Args:
            session: Optional pre-existing session. If not provided, creates new sessions.
        """
        self._session = session
        self._owns_session = session is None
        
        # Initialize repositories (will be set when session is available)
        self._customers = None
        self._policies = None
        self._claims = None
        self._underwriting = None
        self._billing = None
        self._users = None
        self._sessions = None
        self._audit = None
        self._actuarial = None
        self._tokens = None
    
    def _ensure_session(self) -> Session:
        """Ensure we have a database session"""
        if self._session is None:
            self._session = get_db_session()
            self._owns_session = True
        return self._session
    
    @property
    def customers(self) -> CustomerRepository:
        """Get customer repository"""
        if self._customers is None:
            self._customers = CustomerRepository(self._ensure_session())
        return self._customers
    
    @property
    def policies(self) -> PolicyRepository:
        """Get policy repository"""
        if self._policies is None:
            self._policies = PolicyRepository(self._ensure_session())
        return self._policies
    
    @property
    def claims(self) -> ClaimRepository:
        """Get claim repository"""
        if self._claims is None:
            self._claims = ClaimRepository(self._ensure_session())
        return self._claims
    
    @property
    def underwriting(self) -> UnderwritingRepository:
        """Get underwriting repository"""
        if self._underwriting is None:
            self._underwriting = UnderwritingRepository(self._ensure_session())
        return self._underwriting
    
    @property
    def billing(self) -> BillingRepository:
        """Get billing repository"""
        if self._billing is None:
            self._billing = BillingRepository(self._ensure_session())
        return self._billing
    
    @property
    def users(self) -> UserRepository:
        """Get user repository"""
        if self._users is None:
            self._users = UserRepository(self._ensure_session())
        return self._users
    
    @property
    def sessions(self) -> SessionRepository:
        """Get session repository"""
        if self._sessions is None:
            self._sessions = SessionRepository(self._ensure_session())
        return self._sessions
    
    @property
    def audit(self) -> AuditRepository:
        """Get audit repository"""
        if self._audit is None:
            self._audit = AuditRepository(self._ensure_session())
        return self._audit

    @property
    def actuarial(self) -> ActuarialRepository:
        """Get actuarial tables repository"""
        if self._actuarial is None:
            self._actuarial = ActuarialRepository(self._ensure_session())
        return self._actuarial

    @property
    def tokens(self) -> TokenRepository:
        """Get token registry repository"""
        if self._tokens is None:
            self._tokens = TokenRepository(self._ensure_session())
        return self._tokens
    
    def commit(self):
        """Commit current transaction"""
        if self._session:
            self._session.commit()
    
    def rollback(self):
        """Rollback current transaction"""
        if self._session:
            self._session.rollback()
    
    def close(self):
        """Close the session if we own it"""
        if self._owns_session and self._session:
            self._session.close()
            self._session = None
            # Reset repositories
            self._customers = None
            self._policies = None
            self._claims = None
            self._underwriting = None
            self._billing = None
            self._users = None
            self._sessions = None
            self._audit = None
            self._actuarial = None
            self._tokens = None
    
    @contextmanager
    def session_scope(self):
        """
        Provide a transactional scope around a series of operations.
        
        Usage:
            db = DatabaseManager()
            with db.session_scope():
                customer = db.customers.create(...)
                policy = db.policies.create(...)
                # Automatically commits on success, rolls back on exception
        """
        try:
            yield self
            self.commit()
        except Exception as e:
            logger.error(f"Transaction failed: {e}")
            self.rollback()
            raise
        finally:
            if self._owns_session:
                self.close()
    
    def __enter__(self):
        """Context manager entry"""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        if exc_type is not None:
            self.rollback()
        else:
            self.commit()
        self.close()


# Convenience functions for quick operations

def create_customer(customer_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Quick function to create a customer"""
    with DatabaseManager() as db:
        customer = db.customers.create(**customer_data)
        return customer.to_dict() if customer else None


def get_customer(customer_id: str) -> Optional[Dict[str, Any]]:
    """Quick function to get a customer"""
    with DatabaseManager() as db:
        customer = db.customers.get_by_id(customer_id)
        return customer.to_dict() if customer else None


def create_policy(policy_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Quick function to create a policy"""
    with DatabaseManager() as db:
        policy = db.policies.create(**policy_data)
        return policy.to_dict() if policy else None


def get_policy(policy_id: str) -> Optional[Dict[str, Any]]:
    """Quick function to get a policy"""
    with DatabaseManager() as db:
        policy = db.policies.get_by_id(policy_id)
        return policy.to_dict() if policy else None


def create_claim(claim_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Quick function to create a claim"""
    with DatabaseManager() as db:
        claim = db.claims.create(**claim_data)
        return claim.to_dict() if claim else None


def get_claim(claim_id: str) -> Optional[Dict[str, Any]]:
    """Quick function to get a claim"""
    with DatabaseManager() as db:
        claim = db.claims.get_by_id(claim_id)
        return claim.to_dict() if claim else None


__all__ = [
    'DatabaseManager',
    'create_customer',
    'get_customer',
    'create_policy',
    'get_policy',
    'create_claim',
    'get_claim'
]
