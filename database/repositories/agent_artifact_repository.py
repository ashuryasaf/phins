"""
Agent Artifact Repository

Data access for the generic durable agent-state table (``agent_artifacts``,
A4). Payloads are stored as canonical JSON with a sha256 checksum; rows whose
checksum does not match on read are reported and skipped rather than served.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple

from sqlalchemy.exc import SQLAlchemyError

from .base import BaseRepository
from database.models import AgentArtifact

logger = logging.getLogger(__name__)


def canonical_payload(payload: Any) -> Tuple[str, str]:
    """Deterministic JSON + sha256 for an artifact payload."""
    text = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return text, hashlib.sha256(text.encode('utf-8')).hexdigest()


class AgentArtifactRepository(BaseRepository):
    """Repository for durable agent artifacts."""

    def __init__(self, session):
        super().__init__(AgentArtifact, session)

    def upsert(self, artifact_id: str, *, agent_id: str, kind: str, payload: Any,
               subject_type: Optional[str] = None, subject_id: Optional[str] = None) -> bool:
        """Insert or replace the artifact. Returns True when the row is durable."""
        text, digest = canonical_payload(payload)
        try:
            row = self.session.get(AgentArtifact, artifact_id)
            if row is None:
                row = AgentArtifact(
                    id=artifact_id, agent_id=agent_id, kind=kind,
                    subject_type=subject_type, subject_id=subject_id,
                    payload_json=text, checksum=digest,
                )
                self.session.add(row)
            else:
                if row.payload_json == text and row.agent_id == agent_id and row.kind == kind:
                    return True  # identical; do not bump updated_date
                row.agent_id = agent_id
                row.kind = kind
                # Subject metadata is only replaced when the caller supplies it.
                if subject_type is not None:
                    row.subject_type = subject_type
                if subject_id is not None:
                    row.subject_id = subject_id
                row.payload_json = text
                row.checksum = digest
                row.updated_date = datetime.utcnow()
            self.session.commit()
            return True
        except SQLAlchemyError as exc:
            logger.error("agent_artifacts upsert failed for %s: %s", artifact_id, exc)
            self.session.rollback()
            raise

    def _verified(self, row: AgentArtifact) -> Optional[Any]:
        digest = hashlib.sha256((row.payload_json or '').encode('utf-8')).hexdigest()
        if digest != row.checksum:
            logger.error("agent_artifacts checksum mismatch for %s (%s/%s); row skipped",
                         row.id, row.agent_id, row.kind)
            return None
        return json.loads(row.payload_json)

    def iter_payloads(self, agent_id: str, kind: Optional[str] = None,
                      since: Optional[datetime] = None
                      ) -> Iterable[Tuple[str, Any, Optional[datetime], Dict[str, Any]]]:
        """Yield ``(id, payload, updated_date, meta)`` for an agent's artifacts.

        ``since`` restricts to rows updated at or after that instant (the
        store's incremental hydration); ``None`` is the full set.
        """
        try:
            query = self.session.query(AgentArtifact).filter(AgentArtifact.agent_id == agent_id)
            if kind:
                query = query.filter(AgentArtifact.kind == kind)
            if since is not None:
                query = query.filter(AgentArtifact.updated_date >= since)
            rows = query.order_by(AgentArtifact.updated_date.asc()).all()
        except SQLAlchemyError as exc:
            logger.error("agent_artifacts load failed for %s/%s: %s", agent_id, kind, exc)
            raise
        for row in rows:
            payload = self._verified(row)
            if payload is None:
                continue
            yield row.id, payload, row.updated_date, {
                'kind': row.kind, 'subject_type': row.subject_type, 'subject_id': row.subject_id,
                'created_date': row.created_date,
            }

    def get_payload(self, artifact_id: str) -> Optional[Any]:
        row = self.session.get(AgentArtifact, artifact_id)
        return self._verified(row) if row is not None else None

    def delete_artifact(self, artifact_id: str) -> bool:
        try:
            deleted = (self.session.query(AgentArtifact)
                       .filter(AgentArtifact.id == artifact_id)
                       .delete(synchronize_session=False))
            self.session.commit()
            return bool(deleted)
        except SQLAlchemyError as exc:
            logger.error("agent_artifacts delete failed for %s: %s", artifact_id, exc)
            self.session.rollback()
            raise

    def count_for(self, agent_id: str, kind: Optional[str] = None) -> int:
        query = self.session.query(AgentArtifact).filter(AgentArtifact.agent_id == agent_id)
        if kind:
            query = query.filter(AgentArtifact.kind == kind)
        return query.count()

    def prune(self, agent_id: str, kind: str, keep: int) -> List[str]:
        """Delete the oldest rows beyond ``keep`` (by ``created_date``).

        Returns the deleted ids so the caller can drop them from its cache.
        Retention is an advisory-artifact rule; the authoritative records the
        artifacts describe (claims, applications) are never touched.
        """
        keep = max(0, int(keep))
        try:
            total = self.count_for(agent_id, kind)
            overflow = total - keep
            if overflow <= 0:
                return []
            victims = (self.session.query(AgentArtifact.id)
                       .filter(AgentArtifact.agent_id == agent_id, AgentArtifact.kind == kind)
                       .order_by(AgentArtifact.created_date.asc(), AgentArtifact.id.asc())
                       .limit(overflow).all())
            ids = [v[0] for v in victims]
            if ids:
                (self.session.query(AgentArtifact)
                 .filter(AgentArtifact.id.in_(ids))
                 .delete(synchronize_session=False))
                self.session.commit()
            return ids
        except SQLAlchemyError as exc:
            logger.error("agent_artifacts prune failed for %s/%s: %s", agent_id, kind, exc)
            self.session.rollback()
            raise
