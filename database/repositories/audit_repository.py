"""Audit Repository"""

from typing import Optional, List
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from database.models import AuditLog
from .base import BaseRepository


class AuditRepository(BaseRepository[AuditLog]):
    """Repository for AuditLog operations"""
    
    def __init__(self, session: Session):
        super().__init__(AuditLog, session)
    
    def get_by_username(self, username: str, limit: int = 100) -> List[AuditLog]:
        """Get audit logs for a user"""
        try:
            return self.session.query(AuditLog).filter(
                AuditLog.username == username
            ).order_by(AuditLog.timestamp.desc()).limit(limit).all()
        except Exception:
            return []
    
    def get_by_customer(self, customer_id: str, limit: int = 100) -> List[AuditLog]:
        """Get audit logs for a customer"""
        try:
            return self.session.query(AuditLog).filter(
                AuditLog.customer_id == customer_id
            ).order_by(AuditLog.timestamp.desc()).limit(limit).all()
        except Exception:
            return []
    
    def get_by_action(self, action: str, limit: int = 100) -> List[AuditLog]:
        """Get audit logs by action type"""
        try:
            return self.session.query(AuditLog).filter(
                AuditLog.action == action
            ).order_by(AuditLog.timestamp.desc()).limit(limit).all()
        except Exception:
            return []
    
    def get_recent_logs(self, hours: int = 24, limit: int = 1000) -> List[AuditLog]:
        """Get recent audit logs"""
        try:
            since = datetime.utcnow() - timedelta(hours=hours)
            return self.session.query(AuditLog).filter(
                AuditLog.timestamp >= since
            ).order_by(AuditLog.timestamp.desc()).limit(limit).all()
        except Exception:
            return []
    
    def log_action(self, username: Optional[str], action: str, 
                   entity_type: Optional[str] = None, entity_id: Optional[str] = None,
                   details: Optional[str] = None, ip_address: Optional[str] = None,
                   customer_id: Optional[str] = None, success: bool = True) -> Optional[AuditLog]:
        """Create an audit log entry"""
        return self.create(
            username=username,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            details=details,
            ip_address=ip_address,
            customer_id=customer_id,
            success=success
        )
