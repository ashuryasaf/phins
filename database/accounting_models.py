"""Durable accounting journal tables (ERP/MGA integrity U5).

``accounting_journal_entries`` is the sealed GL append log for
``AccountingEngine`` posts. Each row carries an idempotency key plus
canonical JSON + sha256. A checksum mismatch withholds the row on read
and is never overwritten. Fiscal period / CoA service state lives in
``services/erp/period_close.py`` and ``services/erp/coa.py`` (U8); this
module owns the journal only so peer instances share posts without
memory-only money.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, DateTime, String, Text, UniqueConstraint

from database.models import Base


class AccountingJournalEntry(Base):
    """One sealed general-ledger journal row (idempotent on ``idempotency_key``)."""

    __tablename__ = 'accounting_journal_entries'
    __table_args__ = (
        UniqueConstraint('idempotency_key', name='uq_accounting_journal_idempotency'),
    )

    id = Column(String(120), primary_key=True)  # entry id (JE-…)
    idempotency_key = Column(String(200), nullable=False, index=True)
    engine_id = Column(String(80), nullable=True, index=True)
    allocation_id = Column(String(120), nullable=True, index=True)
    policy_id = Column(String(80), nullable=True, index=True)
    customer_id = Column(String(80), nullable=True, index=True)
    entry_type = Column(String(80), nullable=True, index=True)
    account_type = Column(String(80), nullable=True, index=True)
    payload_json = Column(Text, nullable=False)
    checksum = Column(String(64), nullable=False)
    created_date = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_date = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False, index=True
    )


ACCOUNTING_MODELS = (AccountingJournalEntry,)

__all__ = [
    'AccountingJournalEntry',
    'ACCOUNTING_MODELS',
]
