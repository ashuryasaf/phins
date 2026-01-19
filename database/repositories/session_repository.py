"""Session Repository"""

from typing import Optional, List
from datetime import datetime, timezone
from sqlalchemy.orm import Session as DBSession
from database.models import Session
from .base import BaseRepository
import logging

logger = logging.getLogger(__name__)


class SessionRepository(BaseRepository[Session]):
    """Repository for Session operations"""
    
    def __init__(self, session: DBSession):
        super().__init__(Session, session)
    
    def get_by_token(self, token: str) -> Optional[Session]:
        """Get session by token (primary key)"""
        return self.get_by_id(token)
    
    def get_by_username(self, username: str) -> List[Session]:
        """Get all sessions for a user"""
        return self.filter_by(username=username)
    
    def get_by_customer(self, customer_id: str) -> List[Session]:
        """Get all sessions for a customer"""
        return self.filter_by(customer_id=customer_id)
    
    def delete_expired_sessions(self) -> int:
        """
        Delete all expired sessions, returns count of deleted sessions.
        
        NOTE: This method commits the transaction automatically.
        If you need to include this in a larger transaction, use the
        DatabaseManager's session_scope() context manager.
        """
        try:
            now = datetime.now(timezone.utc)
            count = self.session.query(Session).filter(Session.expires < now).delete()
            self.session.commit()
            return count
        except Exception as e:
            logger.error(f"Error deleting expired sessions: {e}")
            self.session.rollback()
            return 0
    
    def get_active_sessions(self, username: Optional[str] = None) -> List[Session]:
        """Get all active (non-expired) sessions, optionally filtered by username"""
        try:
            now = datetime.now(timezone.utc)
            query = self.session.query(Session).filter(Session.expires > now)
            if username:
                query = query.filter(Session.username == username)
            return query.all()
        except Exception:
            return []
