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

    def get_all_by_sequence(self, limit: Optional[int] = None) -> List[PlatformLedgerEntry]:
        """Return entries ordered by sequence_no ascending, suitable for full hydration.

        ``limit=None`` (the default) returns every row. A positive ``limit``
        caps the scan, but capping is unsafe for full-chain hydration or
        reconciliation: once the table grows past the cap the omitted rows are
        mis-classified as missing (re-inserted on PK conflict, or left out of
        memory so appends advance from a stale ``sequence_no``).
        """
        try:
            query = (
                self.session.query(PlatformLedgerEntry)
                .order_by(PlatformLedgerEntry.sequence_no.asc())
            )
            if limit is not None and limit > 0:
                query = query.limit(limit)
            return query.all()
        except Exception:
            return []

    def get_all_ids_by_sequence(self) -> List[str]:
        """Return only the entry ids, ordered by sequence_no ascending.

        Startup hydration uses this as a cheap probe: it transfers one string
        per row instead of full rows (payload JSON included), then fetches
        full rows only for ids missing from the in-memory ledger.

        NOTE: unlike most read helpers here, query errors PROPAGATE instead of
        returning [] — an empty result means "table is empty", and callers
        must be able to distinguish that from "probe failed" (which requires
        falling back to a full-row scan, never skipping hydration).
        """
        return [
            row[0]
            for row in (
                self.session.query(PlatformLedgerEntry.id)
                .order_by(PlatformLedgerEntry.sequence_no.asc())
                .all()
            )
        ]

    def get_by_ids(self, entry_ids: List[str]) -> List[PlatformLedgerEntry]:
        """Fetch full rows for the given ids, ordered by sequence_no ascending.

        Queries in chunks to stay within database IN-clause limits. Query
        errors PROPAGATE (see get_all_ids_by_sequence) so hydration callers
        surface the failure instead of silently loading a partial chain.
        """
        if not entry_ids:
            return []
        chunk_size = 500
        rows: List[PlatformLedgerEntry] = []
        for start in range(0, len(entry_ids), chunk_size):
            chunk = entry_ids[start:start + chunk_size]
            rows.extend(
                self.session.query(PlatformLedgerEntry)
                .filter(PlatformLedgerEntry.id.in_(chunk))
                .all()
            )
        rows.sort(key=lambda row: (row.sequence_no or 0))
        return rows

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
