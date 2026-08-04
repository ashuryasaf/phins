from __future__ import annotations

from typing import List, Optional

from sqlalchemy.orm import Session

from database.models import AssessmentRecord


class AssessmentRecordRepository:
    """Data access for durable assessment records (score → decision loop)."""

    def __init__(self, session: Session):
        self.session = session

    def create(self, record: AssessmentRecord) -> AssessmentRecord:
        self.session.add(record)
        self.session.flush()
        return record

    def get_by_id(self, record_id: str) -> Optional[AssessmentRecord]:
        return (
            self.session.query(AssessmentRecord)
            .filter(AssessmentRecord.id == record_id)
            .first()
        )

    def _filtered_query(
        self,
        customer_id: Optional[str] = None,
        subject_type: Optional[str] = None,
        subject_id: Optional[str] = None,
        assessment_type: Optional[str] = None,
    ):
        query = self.session.query(AssessmentRecord)
        if customer_id:
            query = query.filter(AssessmentRecord.customer_id == customer_id)
        if subject_type:
            query = query.filter(AssessmentRecord.subject_type == subject_type)
        if subject_id:
            query = query.filter(AssessmentRecord.subject_id == subject_id)
        if assessment_type:
            query = query.filter(AssessmentRecord.assessment_type == assessment_type)
        return query

    def list_filtered(
        self,
        customer_id: Optional[str] = None,
        subject_type: Optional[str] = None,
        subject_id: Optional[str] = None,
        assessment_type: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[AssessmentRecord]:
        return (
            self._filtered_query(customer_id, subject_type, subject_id, assessment_type)
            .order_by(AssessmentRecord.created_date.desc())
            .offset(max(0, offset))
            .limit(max(1, limit))
            .all()
        )

    def count_filtered(
        self,
        customer_id: Optional[str] = None,
        subject_type: Optional[str] = None,
        subject_id: Optional[str] = None,
        assessment_type: Optional[str] = None,
    ) -> int:
        return self._filtered_query(
            customer_id, subject_type, subject_id, assessment_type
        ).count()

    def latest_for_subject(
        self, subject_type: str, subject_id: str
    ) -> Optional[AssessmentRecord]:
        return (
            self.session.query(AssessmentRecord)
            .filter(
                AssessmentRecord.subject_type == subject_type,
                AssessmentRecord.subject_id == subject_id,
            )
            .order_by(AssessmentRecord.created_date.desc())
            .first()
        )

    def update_decision(
        self,
        record_id: str,
        decided_by: str,
        decision: str,
        decision_aligned: Optional[bool] = None,
    ) -> Optional[AssessmentRecord]:
        record = self.get_by_id(record_id)
        if not record:
            return None
        record.decided_by = decided_by
        record.decision = decision
        record.decision_aligned = decision_aligned
        self.session.flush()
        return record
