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
