"""Form Submission Repository"""

from typing import List
from sqlalchemy.orm import Session

from database.models import FormSubmission
from .base import BaseRepository


class FormSubmissionRepository(BaseRepository[FormSubmission]):
    """Repository for FormSubmission operations"""

    def __init__(self, session: Session):
        super().__init__(FormSubmission, session)

    def get_for_customer(self, customer_id: str, *, limit: int = 200) -> List[FormSubmission]:
        try:
            return (
                self.session.query(FormSubmission)
                .filter(FormSubmission.customer_id == customer_id)
                .order_by(FormSubmission.created_date.desc())
                .limit(limit)
                .all()
            )
        except Exception:
            return []

