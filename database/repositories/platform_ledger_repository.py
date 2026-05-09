"""Platform event ledger repository."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from datetime import datetime
import json

from sqlalchemy.orm import Session

from database.models import PlatformLedgerEntry
from .base import BaseRepository


class PlatformLedgerRepository(BaseRepository[PlatformLedgerEntry]):
    """Repository for append-only platform ledger entries."""

    def __init__(self, session: Session):
        super().__init__(PlatformLedgerEntry, session)

    def get_latest_entry(self) -> Optional[PlatformLedgerEntry]:
        try:
            return (
                self.session.query(PlatformLedgerEntry)
                .order_by(PlatformLedgerEntry.sequence_no.desc(), PlatformLedgerEntry.timestamp.desc())
                .first()
            )
        except Exception:
            return None

    def get_all_by_sequence(self, limit: int = 10000) -> List[PlatformLedgerEntry]:
        """Return entries ordered by sequence_no ascending, suitable for full hydration."""
        try:
            return (
                self.session.query(PlatformLedgerEntry)
                .order_by(PlatformLedgerEntry.sequence_no.asc())
                .limit(limit)
                .all()
            )
        except Exception:
            return []

    def get_recent_entries(self, limit: int = 100) -> List[PlatformLedgerEntry]:
        try:
            return (
                self.session.query(PlatformLedgerEntry)
                .order_by(PlatformLedgerEntry.sequence_no.desc(), PlatformLedgerEntry.timestamp.desc())
                .limit(limit)
                .all()
            )
        except Exception:
            return []

    def get_by_customer(self, customer_id: str, limit: int = 100) -> List[PlatformLedgerEntry]:
        try:
            return (
                self.session.query(PlatformLedgerEntry)
                .filter(PlatformLedgerEntry.customer_id == customer_id)
                .order_by(PlatformLedgerEntry.sequence_no.desc())
                .limit(limit)
                .all()
            )
        except Exception:
            return []

    def get_by_entity(self, entity_type: str, entity_id: str, limit: int = 100) -> List[PlatformLedgerEntry]:
        try:
            return (
                self.session.query(PlatformLedgerEntry)
                .filter(
                    PlatformLedgerEntry.entity_type == entity_type,
                    PlatformLedgerEntry.entity_id == entity_id,
                )
                .order_by(PlatformLedgerEntry.sequence_no.desc())
                .limit(limit)
                .all()
            )
        except Exception:
            return []

    def record_event(self, **kwargs: Any) -> Optional[PlatformLedgerEntry]:
        payload = kwargs.get("payload")
        if payload is not None and not isinstance(payload, str):
            kwargs["payload"] = json.dumps(payload, sort_keys=True, default=str)

        timestamp_value = kwargs.get("timestamp")
        if isinstance(timestamp_value, str):
            try:
                kwargs["timestamp"] = datetime.fromisoformat(timestamp_value)
            except ValueError:
                pass

        return self.create(**kwargs)
