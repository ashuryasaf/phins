"""
AI Usage Repository

Data access for AI/parsing cost-accounting rows (``ai_usage_records``).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError

from .base import BaseRepository
from database.models import AIUsageRecord

logger = logging.getLogger(__name__)


class AIUsageRepository(BaseRepository):
    """Repository for AI usage/cost records."""

    def __init__(self, session):
        super().__init__(AIUsageRecord, session)

    def list_filtered(
        self,
        customer_id: Optional[str] = None,
        assessment_id: Optional[str] = None,
        document_id: Optional[str] = None,
        provider: Optional[str] = None,
        operation: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[AIUsageRecord]:
        try:
            query = self.session.query(AIUsageRecord)
            if customer_id:
                query = query.filter(AIUsageRecord.customer_id == customer_id)
            if assessment_id:
                query = query.filter(AIUsageRecord.assessment_id == assessment_id)
            if document_id:
                query = query.filter(AIUsageRecord.document_id == document_id)
            if provider:
                query = query.filter(AIUsageRecord.provider == provider)
            if operation:
                query = query.filter(AIUsageRecord.operation == operation)
            return (
                query.order_by(AIUsageRecord.created_date.desc())
                .offset(max(0, offset)).limit(max(1, limit)).all()
            )
        except SQLAlchemyError as e:
            logger.error(f"Error listing AI usage records: {e}")
            return []

    def aggregate(self, group_by: str = 'provider',
                  customer_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """SUM/COUNT rollup grouped by provider|operation|customer|model."""
        column = {
            'provider': AIUsageRecord.provider,
            'operation': AIUsageRecord.operation,
            'customer': AIUsageRecord.customer_id,
            'model': AIUsageRecord.model,
        }.get(group_by, AIUsageRecord.provider)
        try:
            query = self.session.query(
                column.label('key'),
                func.count(AIUsageRecord.id).label('operations'),
                func.coalesce(func.sum(AIUsageRecord.estimated_cost), 0.0).label('estimated_cost'),
                func.coalesce(func.sum(AIUsageRecord.input_tokens), 0).label('input_tokens'),
                func.coalesce(func.sum(AIUsageRecord.output_tokens), 0).label('output_tokens'),
                func.coalesce(func.sum(AIUsageRecord.pages), 0).label('pages'),
                func.coalesce(func.sum(AIUsageRecord.media_seconds), 0.0).label('media_seconds'),
            )
            if customer_id:
                query = query.filter(AIUsageRecord.customer_id == customer_id)
            rows = query.group_by(column).all()
            return [
                {
                    'key': row.key,
                    'operations': int(row.operations),
                    'estimated_cost': round(float(row.estimated_cost), 6),
                    'input_tokens': int(row.input_tokens),
                    'output_tokens': int(row.output_tokens),
                    'pages': int(row.pages),
                    'media_seconds': round(float(row.media_seconds), 2),
                }
                for row in rows
            ]
        except SQLAlchemyError as e:
            logger.error(f"Error aggregating AI usage: {e}")
            return []
