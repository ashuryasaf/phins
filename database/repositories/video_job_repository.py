"""
Video Job Repository

Data access for Video Agents generation jobs (``video_jobs``, A4). The row's
lifecycle columns mirror the job dict so the dashboard can filter in SQL; the
job dict itself is the payload.

Concurrency: ``update_fields`` uses optimistic concurrency on ``updated_date``
(read → merge → conditional UPDATE, retried), and ``mark_terminal`` adds
``status NOT IN (terminal)`` to that condition, so when a webhook and the
poller race to finish a job exactly one of them performs the transition —
the same guarantee the in-memory ``_JobStore.mark_terminal`` gave under its
lock, now across processes.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from sqlalchemy.exc import SQLAlchemyError

from .base import BaseRepository
from database.models import VideoJob

logger = logging.getLogger(__name__)

TERMINAL_STATUSES: Tuple[str, ...] = ('completed', 'failed', 'cancelled')
_CAS_ATTEMPTS = 5


def _columns_from(job: Dict[str, Any]) -> Dict[str, Any]:
    return {
        'campaign_id': str(job.get('campaign_id') or '') or None,
        'submitted_by': str(job.get('submitted_by') or '') or None,
        'provider': str(job.get('provider') or '') or None,
        'provider_job_id': str(job.get('provider_job_id') or '') or None,
        'pipeline_type': str(job.get('pipeline_type') or '') or None,
        'status': str(job.get('status') or 'queued'),
        'created_at': str(job.get('created_at') or '') or None,
    }


class VideoJobRepository(BaseRepository):
    """Repository for video generation jobs."""

    def __init__(self, session):
        super().__init__(VideoJob, session)

    # -- writes ------------------------------------------------------------
    def upsert(self, job: Dict[str, Any]) -> Dict[str, Any]:
        job_id = str(job['id'])
        try:
            row = self.session.get(VideoJob, job_id)
            cols = _columns_from(job)
            if row is None:
                row = VideoJob(id=job_id, payload_json=json.dumps(job, default=str), **cols)
                self.session.add(row)
            else:
                for name, value in cols.items():
                    setattr(row, name, value)
                row.payload_json = json.dumps(job, default=str)
                row.updated_date = datetime.utcnow()
            self.session.commit()
            return dict(job)
        except SQLAlchemyError as exc:
            logger.error("video_jobs upsert failed for %s: %s", job_id, exc)
            self.session.rollback()
            raise

    def _conditional_merge(self, job_id: str, updates: Dict[str, Any], *,
                           refuse_statuses: Sequence[str] = ()) -> Optional[Dict[str, Any]]:
        """Read-merge-CAS. Returns the merged job, or None when the job is
        missing or (for ``mark_terminal``) already in a refused status."""
        for _ in range(_CAS_ATTEMPTS):
            try:
                row = self.session.get(VideoJob, job_id)
                if row is None:
                    return None
                self.session.refresh(row)
                if refuse_statuses and row.status in refuse_statuses:
                    return None
                current = json.loads(row.payload_json or '{}')
                merged = dict(current)
                merged.update(updates)
                merged['updated_at'] = datetime.now(timezone.utc).isoformat()
                expected_updated = row.updated_date
                cols = _columns_from(merged)
                query = self.session.query(VideoJob).filter(
                    VideoJob.id == job_id, VideoJob.updated_date == expected_updated)
                if refuse_statuses:
                    query = query.filter(~VideoJob.status.in_(list(refuse_statuses)))
                changed = query.update(
                    {**cols, 'payload_json': json.dumps(merged, default=str),
                     'updated_date': datetime.utcnow()},
                    synchronize_session=False,
                )
                self.session.commit()
                if changed == 1:
                    return merged
                # Lost the race: someone else changed the row; re-read and retry
                # (or give up if it became terminal for mark_terminal).
            except SQLAlchemyError as exc:
                logger.error("video_jobs update failed for %s: %s", job_id, exc)
                self.session.rollback()
                raise
        logger.warning("video_jobs update for %s gave up after %d CAS attempts",
                       job_id, _CAS_ATTEMPTS)
        return None

    def update_fields(self, job_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        return self._conditional_merge(str(job_id), updates)

    def mark_terminal(self, job_id: str, updates: Dict[str, Any],
                      terminal_statuses: Sequence[str] = TERMINAL_STATUSES
                      ) -> Optional[Dict[str, Any]]:
        """Transition to a terminal state exactly once across processes."""
        return self._conditional_merge(str(job_id), updates, refuse_statuses=tuple(terminal_statuses))

    def delete_job(self, job_id: str) -> bool:
        try:
            deleted = (self.session.query(VideoJob).filter(VideoJob.id == str(job_id))
                       .delete(synchronize_session=False))
            self.session.commit()
            return bool(deleted)
        except SQLAlchemyError as exc:
            logger.error("video_jobs delete failed for %s: %s", job_id, exc)
            self.session.rollback()
            raise

    # -- reads -------------------------------------------------------------
    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        row = self.session.get(VideoJob, str(job_id))
        return row.to_dict() if row is not None else None

    def iter_jobs(self, since: Optional[datetime] = None
                  ) -> Iterable[Tuple[str, Dict[str, Any], Optional[datetime]]]:
        try:
            query = self.session.query(VideoJob)
            if since is not None:
                query = query.filter(VideoJob.updated_date >= since)
            rows = query.order_by(VideoJob.updated_date.asc()).all()
        except SQLAlchemyError as exc:
            logger.error("video_jobs load failed: %s", exc)
            raise
        for row in rows:
            yield row.id, row.to_dict(), row.updated_date

    def list_by_campaign(self, campaign_id: str) -> List[Dict[str, Any]]:
        rows = (self.session.query(VideoJob).filter(VideoJob.campaign_id == campaign_id)
                .order_by(VideoJob.created_date.asc()).all())
        return [r.to_dict() for r in rows]

    def count_by_campaign(self, campaign_id: str) -> int:
        return self.session.query(VideoJob).filter(VideoJob.campaign_id == campaign_id).count()

    def count_created_on(self, day_prefix: str, submitted_by: Optional[str] = None) -> int:
        """Jobs whose service-stamped ``created_at`` starts with ``day_prefix``
        (``YYYY-MM-DD``), optionally for one submitter — the daily caps."""
        query = self.session.query(VideoJob).filter(VideoJob.created_at.like(f"{day_prefix}%"))
        if submitted_by is not None:
            query = query.filter(VideoJob.submitted_by == submitted_by)
        return query.count()
