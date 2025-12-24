"""Notification Repository"""

from typing import List
from sqlalchemy.orm import Session

from database.models import Notification
from .base import BaseRepository


class NotificationRepository(BaseRepository[Notification]):
    """Repository for Notification operations"""

    def __init__(self, session: Session):
        super().__init__(Notification, session)

    def get_for_customer(self, customer_id: str, *, limit: int = 100) -> List[Notification]:
        try:
            return (
                self.session.query(Notification)
                .filter(Notification.customer_id == customer_id)
                .order_by(Notification.created_date.desc())
                .limit(limit)
                .all()
            )
        except Exception:
            return []

