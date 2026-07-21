"""User Repository"""

from typing import Optional, List
from sqlalchemy.orm import Session
from database.models import User
from .base import BaseRepository


class UserRepository(BaseRepository[User]):
    """Repository for User operations"""
    
    def __init__(self, session: Session):
        super().__init__(User, session)
    
    def get_by_username(self, username: str) -> Optional[User]:
        """Get user by username (primary key)"""
        return self.get_by_id(username)

    def get_by_usernames(self, usernames: List[str]) -> List[User]:
        """Get all users whose username is in the given list (single query).

        Lets seed/bootstrap code check N accounts with one SELECT instead of
        N primary-key lookups on every startup.
        """
        if not usernames:
            return []
        try:
            return (
                self.session.query(User)
                .filter(User.username.in_(usernames))
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
        """Authenticate user by matching a PBKDF2 hash.

        NOTE: callers MUST pass the derived PBKDF2 hash (not the plaintext
        password). This method is retained for legacy call sites and performs
        a constant-time comparison to avoid timing-based hash leaks.
        """
        import hmac as _hmac

        if not username or not password_hash:
            return None
        user = self.get_by_username(username)
        if not user or not user.password_hash:
            return None
        try:
            if _hmac.compare_digest(str(user.password_hash), str(password_hash)):
                return user
        except Exception:
            return None
        return None
