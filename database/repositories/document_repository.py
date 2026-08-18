"""
Document Repository

Provides data-access methods for persistent document and processing-job records.
"""

from typing import List, Optional, Dict, Any
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import desc
import logging

from .base import BaseRepository
from database.models import Document, DocumentProcessingJob

logger = logging.getLogger(__name__)


class DocumentRepository(BaseRepository):
    """Repository for Document records."""

    def __init__(self, session):
        super().__init__(Document, session)

    def get_by_entity(self, entity_type: str, entity_id: str,
                      include_archived: bool = False) -> List[Document]:
        try:
            q = self.session.query(Document).filter(
                Document.entity_type == entity_type,
                Document.entity_id == entity_id,
                Document.is_deleted == False,
            )
            if not include_archived:
                q = q.filter(Document.is_archived == False)
            return q.order_by(desc(Document.created_date)).all()
        except SQLAlchemyError as e:
            logger.error(f"Error fetching documents for {entity_type}/{entity_id}: {e}")
            return []

    def get_by_customer(self, customer_id: str,
                        include_archived: bool = False) -> List[Document]:
        try:
            q = self.session.query(Document).filter(
                Document.customer_id == customer_id,
                Document.is_deleted == False,
            )
            if not include_archived:
                q = q.filter(Document.is_archived == False)
            return q.order_by(desc(Document.created_date)).all()
        except SQLAlchemyError as e:
            logger.error(f"Error fetching documents for customer {customer_id}: {e}")
            return []

    def get_by_category(self, category: str, limit: int = 50,
                        offset: int = 0) -> List[Document]:
        try:
            return (
                self.session.query(Document)
                .filter(Document.category == category, Document.is_deleted == False)
                .order_by(desc(Document.created_date))
                .offset(offset).limit(limit).all()
            )
        except SQLAlchemyError as e:
            logger.error(f"Error fetching documents by category {category}: {e}")
            return []

    def get_by_status(self, status: str, limit: int = 50) -> List[Document]:
        try:
            return (
                self.session.query(Document)
                .filter(Document.status == status, Document.is_deleted == False)
                .order_by(desc(Document.created_date))
                .limit(limit).all()
            )
        except SQLAlchemyError as e:
            logger.error(f"Error fetching documents by status {status}: {e}")
            return []

    def get_by_checksum(self, sha256: str) -> Optional[Document]:
        try:
            return (
                self.session.query(Document)
                .filter(Document.sha256_checksum == sha256, Document.is_deleted == False)
                .first()
            )
        except SQLAlchemyError as e:
            logger.error(f"Error fetching document by checksum: {e}")
            return None

    def search(self, query: str, category: Optional[str] = None,
               entity_type: Optional[str] = None, customer_id: Optional[str] = None,
               limit: int = 50, offset: int = 0) -> List[Document]:
        try:
            q = self.session.query(Document).filter(Document.is_deleted == False)
            if query:
                pattern = f"%{query}%"
                q = q.filter(
                    (Document.file_name.ilike(pattern))
                    | (Document.description.ilike(pattern))
                    | (Document.document_type.ilike(pattern))
                )
            if category:
                q = q.filter(Document.category == category)
            if entity_type:
                q = q.filter(Document.entity_type == entity_type)
            if customer_id:
                q = q.filter(Document.customer_id == customer_id)
            return q.order_by(desc(Document.created_date)).offset(offset).limit(limit).all()
        except SQLAlchemyError as e:
            logger.error(f"Error searching documents: {e}")
            return []

    def search_all(self, query: Optional[str] = None,
                   entity_type: Optional[str] = None, entity_id: Optional[str] = None,
                   customer_id: Optional[str] = None, category: Optional[str] = None,
                   status: Optional[str] = None,
                   limit: int = 50, offset: int = 0) -> List[Document]:
        """Unified search that chains all optional filters with pagination."""
        try:
            q = self.session.query(Document).filter(Document.is_deleted == False)
            if query:
                pattern = f"%{query}%"
                q = q.filter(
                    (Document.file_name.ilike(pattern))
                    | (Document.description.ilike(pattern))
                    | (Document.document_type.ilike(pattern))
                )
            if entity_type:
                q = q.filter(Document.entity_type == entity_type)
            if entity_id:
                q = q.filter(Document.entity_id == entity_id)
            if customer_id:
                q = q.filter(Document.customer_id == customer_id)
            if category:
                q = q.filter(Document.category == category)
            if status:
                q = q.filter(Document.status == status)
            return q.order_by(desc(Document.created_date)).offset(offset).limit(limit).all()
        except SQLAlchemyError as e:
            logger.error(f"Error in search_all: {e}")
            return []

    def soft_delete(self, doc_id: str) -> bool:
        return self.update(doc_id, is_deleted=True) is not None

    def archive(self, doc_id: str) -> bool:
        return self.update(doc_id, is_archived=True) is not None

    def count_filtered(self, query: Optional[str] = None,
                       entity_type: Optional[str] = None, entity_id: Optional[str] = None,
                       customer_id: Optional[str] = None, category: Optional[str] = None,
                       status: Optional[str] = None) -> int:
        """Efficient COUNT(*) with all optional filters (no row loading)."""
        try:
            q = self.session.query(Document).filter(Document.is_deleted == False)
            if query:
                pattern = f"%{query}%"
                q = q.filter(
                    (Document.file_name.ilike(pattern))
                    | (Document.description.ilike(pattern))
                    | (Document.document_type.ilike(pattern))
                )
            if entity_type:
                q = q.filter(Document.entity_type == entity_type)
            if entity_id:
                q = q.filter(Document.entity_id == entity_id)
            if customer_id:
                q = q.filter(Document.customer_id == customer_id)
            if category:
                q = q.filter(Document.category == category)
            if status:
                q = q.filter(Document.status == status)
            return q.count()
        except SQLAlchemyError as e:
            logger.error(f"Error counting documents: {e}")
            return 0

    def count_by_entity(self, entity_type: str, entity_id: str) -> int:
        try:
            return (
                self.session.query(Document)
                .filter(
                    Document.entity_type == entity_type,
                    Document.entity_id == entity_id,
                    Document.is_deleted == False,
                ).count()
            )
        except SQLAlchemyError as e:
            logger.error(f"Error counting documents: {e}")
            return 0

    def get_statistics(self, customer_id: Optional[str] = None) -> Dict[str, Any]:
        try:
            q = self.session.query(Document).filter(Document.is_deleted == False)
            if customer_id:
                q = q.filter(Document.customer_id == customer_id)
            all_docs = q.all()
            total_size = 0
            by_category: Dict[str, int] = {}
            by_status: Dict[str, int] = {}
            for doc in all_docs:
                total_size += doc.file_size or 0
                cat = doc.category or 'general'
                by_category[cat] = by_category.get(cat, 0) + 1
                st = doc.status or 'uploaded'
                by_status[st] = by_status.get(st, 0) + 1
            return {
                'total_documents': len(all_docs),
                'total_size_bytes': total_size,
                'by_category': by_category,
                'by_status': by_status,
            }
        except SQLAlchemyError as e:
            logger.error(f"Error getting document statistics: {e}")
            return {'total_documents': 0, 'total_size_bytes': 0,
                    'by_category': {}, 'by_status': {}}


class DocumentProcessingJobRepository(BaseRepository):
    """Repository for processing-job records attached to documents."""

    def __init__(self, session):
        super().__init__(DocumentProcessingJob, session)

    def get_by_document(self, document_id: str) -> List[DocumentProcessingJob]:
        try:
            return (
                self.session.query(DocumentProcessingJob)
                .filter(DocumentProcessingJob.document_id == document_id)
                .order_by(desc(DocumentProcessingJob.created_date))
                .all()
            )
        except SQLAlchemyError as e:
            logger.error(f"Error fetching jobs for document {document_id}: {e}")
            return []

    def get_pending_jobs(self, limit: int = 50) -> List[DocumentProcessingJob]:
        try:
            return (
                self.session.query(DocumentProcessingJob)
                .filter(DocumentProcessingJob.status == 'pending')
                .order_by(DocumentProcessingJob.created_date)
                .limit(limit).all()
            )
        except SQLAlchemyError as e:
            logger.error(f"Error fetching pending jobs: {e}")
            return []

    def get_by_type(self, job_type: str, limit: int = 50) -> List[DocumentProcessingJob]:
        try:
            return (
                self.session.query(DocumentProcessingJob)
                .filter(DocumentProcessingJob.job_type == job_type)
                .order_by(desc(DocumentProcessingJob.created_date))
                .limit(limit).all()
            )
        except SQLAlchemyError as e:
            logger.error(f"Error fetching jobs by type {job_type}: {e}")
            return []

    def get_by_idempotency_key(self, key: str) -> Optional[DocumentProcessingJob]:
        try:
            return (
                self.session.query(DocumentProcessingJob)
                .filter(DocumentProcessingJob.idempotency_key == key)
                .first()
            )
        except SQLAlchemyError as e:
            logger.error(f"Error fetching job by idempotency key: {e}")
            return None

    def claim_due_jobs(self, worker_id: str, limit: int = 10,
                       claim_timeout_seconds: int = 600) -> List[DocumentProcessingJob]:
        """Atomically claim jobs that are ready to run.

        Ready means: status 'pending', or status 'failed' whose retry time has
        arrived, or status 'claimed' whose claim expired (crashed worker).
        Claimed jobs get next_retry_at set to the claim expiry so a worker
        crash automatically releases them to the next claimer.
        """
        from datetime import datetime, timedelta
        now = datetime.utcnow()
        try:
            due = (
                self.session.query(DocumentProcessingJob)
                .filter(
                    (DocumentProcessingJob.status == 'pending')
                    | (
                        (DocumentProcessingJob.status.in_(('failed', 'claimed')))
                        & (DocumentProcessingJob.next_retry_at != None)  # noqa: E711
                        & (DocumentProcessingJob.next_retry_at <= now)
                    )
                )
                .order_by(DocumentProcessingJob.priority,
                          DocumentProcessingJob.created_date)
                .limit(limit)
                .with_for_update(skip_locked=True)
                .all()
            )
            expiry = now + timedelta(seconds=claim_timeout_seconds)
            for job in due:
                job.status = 'claimed'
                job.worker_id = worker_id
                job.next_retry_at = expiry
            self.session.commit()
            return due
        except SQLAlchemyError as e:
            logger.error(f"Error claiming due jobs: {e}")
            self.session.rollback()
            # SQLite before 3.x row-locking support: retry without FOR UPDATE.
            try:
                due = (
                    self.session.query(DocumentProcessingJob)
                    .filter(
                        (DocumentProcessingJob.status == 'pending')
                        | (
                            (DocumentProcessingJob.status.in_(('failed', 'claimed')))
                            & (DocumentProcessingJob.next_retry_at != None)  # noqa: E711
                            & (DocumentProcessingJob.next_retry_at <= now)
                        )
                    )
                    .order_by(DocumentProcessingJob.priority,
                              DocumentProcessingJob.created_date)
                    .limit(limit)
                    .all()
                )
                from datetime import timedelta as _td
                expiry = now + _td(seconds=claim_timeout_seconds)
                for job in due:
                    job.status = 'claimed'
                    job.worker_id = worker_id
                    job.next_retry_at = expiry
                self.session.commit()
                return due
            except SQLAlchemyError as e2:
                logger.error(f"Fallback claim failed: {e2}")
                self.session.rollback()
                return []

    def count_by_status(self) -> Dict[str, int]:
        """Queue depth: number of jobs per status."""
        from sqlalchemy import func
        try:
            rows = (
                self.session.query(DocumentProcessingJob.status,
                                   func.count(DocumentProcessingJob.id))
                .group_by(DocumentProcessingJob.status)
                .all()
            )
            return {status: count for status, count in rows}
        except SQLAlchemyError as e:
            logger.error(f"Error counting jobs by status: {e}")
            return {}

    def requeue_dead_letter(self, job_id: str) -> bool:
        """Operator action: move a dead-letter job back to pending."""
        try:
            job = self.get_by_id(job_id)
            if not job or job.status != 'dead_letter':
                return False
            job.status = 'pending'
            job.attempts = 0
            job.next_retry_at = None
            job.error_message = None
            job.worker_id = None
            self.session.commit()
            return True
        except SQLAlchemyError as e:
            logger.error(f"Error requeuing job {job_id}: {e}")
            self.session.rollback()
            return False
