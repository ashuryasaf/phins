"""User Repository"""

from typing import Optional, List
from sqlalchemy.orm import Session
from sqlalchemy import func
from database.models import User
from .base import BaseRepository


class UserRepository(BaseRepository[User]):
    """Repository for User operations"""
    
    def __init__(self, session: Session):
        super().__init__(User, session)
    
    def get_by_username(self, username: str) -> Optional[User]:
        """Get user by username (primary key)"""
        return self.get_by_id(username)

    def get_by_username_ci(self, username: str) -> Optional[User]:
        """Case-insensitive lookup by username (for legacy mixed-case records)."""
        try:
            u = str(username or "").strip()
            if not u:
                return None
            return self.session.query(User).filter(func.lower(User.username) == u.lower()).first()
        except Exception:
            return None

    def get_by_email_ci(self, email: str) -> List[User]:
        """Case-insensitive lookup by email (returns possibly multiple users)."""
        try:
            e = str(email or "").strip()
            if not e:
                return []
            return (
                self.session.query(User)
                .filter(func.lower(User.email) == e.lower())
                .order_by(User.created_date.desc())
                .all()
            )
        except Exception:
            return []
    
    def get_by_role(self, role: str) -> List[User]:
        """Get all users with a specific role"""
        return self.filter_by(role=role)
    
    def get_active_users(self) -> List[User]:
        """Get all active users"""
        return self.filter_by(active=True)
    
    def authenticate(self, username: str, password_hash: str) -> Optional[User]:
        """Authenticate user (returns user if credentials match)"""
        user = self.get_by_username(username)
        if user and user.password_hash == password_hash:
            return user
        return None
