"""Sealed accounting journal repository (ERP/MGA integrity U5).

Inserts are idempotent on ``idempotency_key``. Matching payload → success
no-op. Different payload for the same key → withhold (fail closed). A
checksum mismatch withholds the row on load and never overwrites it.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from database.accounting_models import AccountingJournalEntry
from database.repositories.base import BaseRepository

logger = logging.getLogger(__name__)


def canonical_journal_payload(payload: Any) -> Tuple[str, str]:
    """Deterministic JSON + sha256 for a journal payload."""
    text = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return text, hashlib.sha256(text.encode('utf-8')).hexdigest()


class AccountingJournalRepository(BaseRepository):
    """Append-only sealed journal with idempotent insert."""

    def __init__(self, session):
        super().__init__(AccountingJournalEntry, session)

    def append(
        self,
        *,
        idempotency_key: str,
        payload: Dict[str, Any],
        engine_id: str = '',
        allocation_id: str = '',
        policy_id: str = '',
        customer_id: str = '',
        entry_type: str = '',
        account_type: str = '',
        entry_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Insert a journal row or return the existing sealed twin.

        Returns ``{ok, id, checksum, reused, withheld, reason?}``.
        """
        key = str(idempotency_key or '').strip()
        if not key:
            return {
                'ok': False,
                'id': None,
                'checksum': '',
                'reused': False,
                'withheld': True,
                'reason': 'idempotency_key_required',
            }
        text, digest = canonical_journal_payload(payload)
        try:
            existing = (
                self.session.query(AccountingJournalEntry)
                .filter(AccountingJournalEntry.idempotency_key == key)
                .one_or_none()
            )
            if existing is not None:
                existing_digest = hashlib.sha256(
                    (existing.payload_json or '').encode('utf-8')
                ).hexdigest()
                if existing_digest != existing.checksum:
                    logger.error(
                        "accounting_journal checksum mismatch for %s; withhold",
                        key,
                    )
                    return {
                        'ok': False,
                        'id': existing.id,
                        'checksum': existing.checksum,
                        'reused': False,
                        'withheld': True,
                        'reason': 'checksum_mismatch',
                    }
                if existing.payload_json == text:
                    return {
                        'ok': True,
                        'id': existing.id,
                        'checksum': existing.checksum,
                        'reused': True,
                        'withheld': False,
                    }
                logger.error(
                    "accounting_journal idempotency clash for %s; withhold",
                    key,
                )
                return {
                    'ok': False,
                    'id': existing.id,
                    'checksum': existing.checksum,
                    'reused': False,
                    'withheld': True,
                    'reason': 'idempotency_payload_mismatch',
                }

            row_id = str(entry_id or '').strip() or f"JE-{uuid.uuid4().hex[:16].upper()}"
            row = AccountingJournalEntry(
                id=row_id,
                idempotency_key=key,
                engine_id=str(engine_id or '') or None,
                allocation_id=str(allocation_id or '') or None,
                policy_id=str(policy_id or '') or None,
                customer_id=str(customer_id or '') or None,
                entry_type=str(entry_type or '') or None,
                account_type=str(account_type or '') or None,
                payload_json=text,
                checksum=digest,
                created_date=datetime.utcnow(),
                updated_date=datetime.utcnow(),
            )
            # Savepoint so a peer race does not poison an outer session_scope.
            try:
                with self.session.begin_nested():
                    self.session.add(row)
                    self.session.flush()
            except IntegrityError:
                existing = (
                    self.session.query(AccountingJournalEntry)
                    .filter(AccountingJournalEntry.idempotency_key == key)
                    .one_or_none()
                )
                if existing is None:
                    return {
                        'ok': False,
                        'id': None,
                        'checksum': '',
                        'reused': False,
                        'withheld': True,
                        'reason': 'integrity_error',
                    }
                if existing.payload_json == text and (
                    hashlib.sha256((existing.payload_json or '').encode('utf-8')).hexdigest()
                    == existing.checksum
                ):
                    return {
                        'ok': True,
                        'id': existing.id,
                        'checksum': existing.checksum,
                        'reused': True,
                        'withheld': False,
                    }
                return {
                    'ok': False,
                    'id': existing.id,
                    'checksum': existing.checksum,
                    'reused': False,
                    'withheld': True,
                    'reason': 'idempotency_race_mismatch',
                }
            return {
                'ok': True,
                'id': row_id,
                'checksum': digest,
                'reused': False,
                'withheld': False,
            }
        except SQLAlchemyError as exc:
            logger.error("accounting_journal append failed: %s", type(exc).__name__)
            return {
                'ok': False,
                'id': None,
                'checksum': '',
                'reused': False,
                'withheld': True,
                'reason': 'db_error',
            }

    def load_intact(self, *, engine_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Return intact sealed payloads ordered by created_date / id.

        Checksum mismatches are withheld (not returned, not repaired).
        """
        try:
            query = self.session.query(AccountingJournalEntry)
            if engine_id:
                query = query.filter(AccountingJournalEntry.engine_id == engine_id)
            rows = query.order_by(
                AccountingJournalEntry.created_date.asc(),
                AccountingJournalEntry.id.asc(),
            ).all()
        except SQLAlchemyError as exc:
            logger.error("accounting_journal load failed: %s", type(exc).__name__)
            return []

        out: List[Dict[str, Any]] = []
        for row in rows:
            digest = hashlib.sha256((row.payload_json or '').encode('utf-8')).hexdigest()
            if digest != row.checksum:
                logger.error(
                    "accounting_journal checksum mismatch for %s; row withheld",
                    row.id,
                )
                continue
            try:
                payload = json.loads(row.payload_json or '{}')
            except (TypeError, ValueError):
                logger.error("accounting_journal JSON broken for %s; withheld", row.id)
                continue
            if not isinstance(payload, dict):
                continue
            payload.setdefault('journal_id', row.id)
            payload.setdefault('idempotency_key', row.idempotency_key)
            payload.setdefault('checksum', row.checksum)
            out.append(payload)
        return out


__all__ = [
    'AccountingJournalRepository',
    'canonical_journal_payload',
]
