"""Sealed fiduciary repositories (ERP/MGA integrity U2).

Upserts store canonical JSON + sha256. Loads verify the checksum and skip
(withhold) a mismatched row rather than serving or overwriting it.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple, Type

from sqlalchemy.exc import SQLAlchemyError

from database.fiduciary_models import (
    BalanceSheetCounters,
    HealthWallet,
    InvestmentAccount,
    NftLedgerEntry,
    WalletWithdrawal,
)
from database.repositories.base import BaseRepository

logger = logging.getLogger(__name__)

BALANCE_SHEET_ID = 'phins'


def canonical_payload(payload: Any) -> Tuple[str, str]:
    """Deterministic JSON + sha256 for a fiduciary payload."""
    text = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return text, hashlib.sha256(text.encode('utf-8')).hexdigest()


class SealedFiduciaryRepository(BaseRepository):
    """Generic sealed document repository over a fiduciary model class."""

    def __init__(self, model_class: Type, session, *, customer_field: Optional[str] = None):
        super().__init__(model_class, session)
        self._customer_field = customer_field

    def upsert(self, record_id: str, payload: Any, *, customer_id: Optional[str] = None) -> bool:
        """Insert or replace when the payload changes. Never clobber a bad-checksum row."""
        text, digest = canonical_payload(payload)
        try:
            row = self.session.get(self.model_class, record_id)
            if row is not None:
                existing_digest = hashlib.sha256(
                    (row.payload_json or '').encode('utf-8')
                ).hexdigest()
                if existing_digest != row.checksum:
                    logger.error(
                        "%s checksum mismatch for %s; withhold (not overwritten)",
                        self.model_class.__tablename__,
                        record_id,
                    )
                    return False
                if row.payload_json == text:
                    return True
                row.payload_json = text
                row.checksum = digest
                row.updated_date = datetime.utcnow()
                if self._customer_field and customer_id is not None:
                    setattr(row, self._customer_field, customer_id)
            else:
                kwargs = {
                    'id': record_id,
                    'payload_json': text,
                    'checksum': digest,
                }
                if self._customer_field is not None:
                    kwargs[self._customer_field] = customer_id
                row = self.model_class(**kwargs)
                self.session.add(row)
            self.session.commit()
            return True
        except SQLAlchemyError as exc:
            # Log type only — SQLAlchemy may stringify bound payload_json.
            logger.error(
                "%s upsert failed for %s: %s",
                self.model_class.__tablename__,
                record_id,
                type(exc).__name__,
            )
            self.session.rollback()
            raise

    def _verified_payload(self, row: Any) -> Optional[Any]:
        digest = hashlib.sha256((row.payload_json or '').encode('utf-8')).hexdigest()
        if digest != row.checksum:
            logger.error(
                "%s checksum mismatch for %s; row withheld",
                self.model_class.__tablename__,
                row.id,
            )
            return None
        try:
            return json.loads(row.payload_json)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            logger.error(
                "%s JSON decode failed for %s: %s",
                self.model_class.__tablename__,
                row.id,
                exc,
            )
            return None

    def get_payload(self, record_id: str) -> Optional[Any]:
        try:
            row = self.session.get(self.model_class, record_id)
        except SQLAlchemyError as exc:
            logger.error(
                "%s get failed for %s: %s",
                self.model_class.__tablename__,
                record_id,
                type(exc).__name__,
            )
            raise
        if row is None:
            return None
        return self._verified_payload(row)

    def iter_payloads(self) -> Iterable[Tuple[str, Any, Optional[datetime]]]:
        try:
            rows = (
                self.session.query(self.model_class)
                .order_by(self.model_class.updated_date.asc())
                .all()
            )
        except SQLAlchemyError as exc:
            logger.error(
                "%s load failed: %s",
                self.model_class.__tablename__,
                type(exc).__name__,
            )
            raise
        for row in rows:
            payload = self._verified_payload(row)
            if payload is None:
                continue
            yield row.id, payload, row.updated_date

    def load_mapping(self) -> Dict[str, Any]:
        """Return ``{id: payload}`` for every intact row."""
        return {key: payload for key, payload, _ in self.iter_payloads()}

    def count_rows(self) -> int:
        try:
            return int(self.session.query(self.model_class).count())
        except SQLAlchemyError as exc:
            logger.error(
                "%s count failed: %s",
                self.model_class.__tablename__,
                type(exc).__name__,
            )
            raise

    def _customer_id_for(
        self, payload: Any, *, customer_from: Optional[str] = None
    ) -> Optional[str]:
        if not isinstance(payload, dict):
            return None
        if customer_from and payload.get(customer_from):
            return str(payload.get(customer_from))
        if payload.get('customer_id'):
            return str(payload.get('customer_id'))
        return None

    def replace_mapping(self, mapping: Dict[str, Any], *, customer_from: Optional[str] = None) -> Dict[str, int]:
        """Upsert every entry. Returns counts of written / withheld / errors.

        Never deletes sealed rows: a checksum-mismatched (withheld) seal must
        stay for forensics, and a dual/replica flush of a subset book must not
        drop other customers' intact ids. Purge durability across db-mode /
        AE2 hydrate needs an explicit tombstone API (out of U2 upsert scope).
        """
        written = withheld = errors = 0
        for key, payload in (mapping or {}).items():
            if not key:
                continue
            customer_id = self._customer_id_for(payload, customer_from=customer_from)
            try:
                ok = self.upsert(str(key), payload, customer_id=customer_id)
            except Exception:
                try:
                    self.session.rollback()
                except Exception:
                    pass
                errors += 1
                continue
            if ok:
                written += 1
            else:
                withheld += 1
        return {'written': written, 'withheld': withheld, 'errors': errors}

    def missing_ids(self, mapping: Dict[str, Any]) -> List[str]:
        """Return mapping keys that have no row yet (half-written books)."""
        missing: List[str] = []
        for key in (mapping or {}):
            if not key:
                continue
            record_id = str(key)
            try:
                row = self.session.get(self.model_class, record_id)
            except SQLAlchemyError as exc:
                logger.error(
                    "%s missing_ids lookup failed for %s: %s",
                    self.model_class.__tablename__,
                    record_id,
                    type(exc).__name__,
                )
                raise
            if row is None:
                missing.append(record_id)
        return missing

    def fill_missing_mapping(
        self, mapping: Dict[str, Any], *, customer_from: Optional[str] = None
    ) -> Dict[str, int]:
        """Insert only ids with no row. Never overwrite intact or broken seals."""
        written = withheld = errors = skipped = 0
        for key, payload in (mapping or {}).items():
            if not key:
                continue
            record_id = str(key)
            try:
                row = self.session.get(self.model_class, record_id)
            except SQLAlchemyError:
                try:
                    self.session.rollback()
                except Exception:
                    pass
                errors += 1
                continue
            if row is not None:
                skipped += 1
                continue
            customer_id = self._customer_id_for(payload, customer_from=customer_from)
            try:
                ok = self.upsert(record_id, payload, customer_id=customer_id)
            except Exception:
                try:
                    self.session.rollback()
                except Exception:
                    pass
                errors += 1
                continue
            if ok:
                written += 1
            else:
                withheld += 1
        return {
            'written': written,
            'withheld': withheld,
            'errors': errors,
            'skipped': skipped,
        }


class HealthWalletRepository(SealedFiduciaryRepository):
    def __init__(self, session):
        super().__init__(HealthWallet, session)


class WalletWithdrawalRepository(SealedFiduciaryRepository):
    def __init__(self, session):
        super().__init__(WalletWithdrawal, session, customer_field='customer_id')


class NftLedgerRepository(SealedFiduciaryRepository):
    def __init__(self, session):
        super().__init__(NftLedgerEntry, session, customer_field='customer_id')


class InvestmentAccountRepository(SealedFiduciaryRepository):
    def __init__(self, session):
        super().__init__(InvestmentAccount, session)


class BalanceSheetRepository(SealedFiduciaryRepository):
    def __init__(self, session):
        super().__init__(BalanceSheetCounters, session)

    def get_phins(self) -> Optional[Any]:
        return self.get_payload(BALANCE_SHEET_ID)

    def upsert_phins(self, payload: Any) -> bool:
        return self.upsert(BALANCE_SHEET_ID, payload)


__all__ = [
    'BALANCE_SHEET_ID',
    'canonical_payload',
    'SealedFiduciaryRepository',
    'HealthWalletRepository',
    'WalletWithdrawalRepository',
    'NftLedgerRepository',
    'InvestmentAccountRepository',
    'BalanceSheetRepository',
]
