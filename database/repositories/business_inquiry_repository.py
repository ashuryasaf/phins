"""
Business Relations inquiry repository.

Durable backing for public Send Inquiry / Request Demo submissions reviewed in
the admin Business Relations queue. The authoritative working store lives in
``web_portal/server.py`` (``BUSINESS_INQUIRIES``); this repository provides
write-through persistence and load-on-refresh for restart survival and
cross-instance consistency.
"""

from typing import Any, Dict, List, Optional
import json
import logging

from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError

from database.models import BusinessInquiry
from .base import BaseRepository

logger = logging.getLogger(__name__)


class BusinessInquiryRepository(BaseRepository[BusinessInquiry]):
    """CRUD for business-relations contact/demo inquiries."""

    def __init__(self, session: Session):
        super().__init__(BusinessInquiry, session)

    def list_by_status(self, status: str) -> List[BusinessInquiry]:
        return self.filter_by(status=status)

    def load_all_as_dicts(self) -> Dict[str, Dict[str, Any]]:
        """Load all inquiries into an id-keyed dict compatible with in-memory store.

        Raises ``SQLAlchemyError`` on a failed read so callers can distinguish a
        genuine load failure from a legitimately empty table and keep serving
        their current cache instead of wiping it.
        """
        try:
            result: Dict[str, Dict[str, Any]] = {}
            for row in self.session.query(BusinessInquiry).all():
                result[row.id] = row.to_dict()
            return result
        except SQLAlchemyError as e:
            logger.error(f"Error loading business inquiries: {e}")
            raise

    def upsert_from_dict(self, inquiry_id: str, data: Dict[str, Any]) -> bool:
        """Create or update an inquiry from the in-memory record shape."""
        try:
            history = data.get('status_history', [])
            if isinstance(history, list):
                history_json = json.dumps(history)
            elif isinstance(history, str):
                history_json = history
            else:
                history_json = json.dumps([])

            existing = self.get_by_id(inquiry_id)
            if existing:
                existing.inquiry_type = data.get('inquiry_type', existing.inquiry_type)
                existing.name = data.get('name', existing.name)
                existing.email = data.get('email', existing.email)
                existing.organization = data.get('organization', existing.organization)
                existing.audience = data.get('audience', existing.audience)
                existing.interest = data.get('interest', existing.interest)
                existing.message = data.get('message', existing.message)
                existing.status = data.get('status', existing.status)
                existing.created_at = data.get('created_at', existing.created_at)
                existing.updated_at = data.get('updated_at', existing.updated_at)
                existing.status_history = history_json
                self.session.commit()
            else:
                obj = BusinessInquiry(
                    id=inquiry_id,
                    inquiry_type=data.get('inquiry_type', 'contact'),
                    name=data.get('name', ''),
                    email=data.get('email', ''),
                    organization=data.get('organization') or '',
                    audience=data.get('audience', 'other'),
                    interest=data.get('interest', 'platform'),
                    message=data.get('message') or '',
                    status=data.get('status', 'new'),
                    created_at=data.get('created_at', ''),
                    updated_at=data.get('updated_at', data.get('created_at', '')),
                    status_history=history_json,
                )
                self.session.add(obj)
                self.session.commit()
            return True
        except (SQLAlchemyError, TypeError, ValueError) as e:
            logger.error(f"Error upserting business inquiry {inquiry_id}: {e}")
            self.session.rollback()
            return False
