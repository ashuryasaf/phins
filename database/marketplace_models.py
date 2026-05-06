"""
PHINS Health Marketplace - Durable ORM Models

This module adds the durable persistence schema for the health marketplace
foundation defined in ``docs/health_marketplace_architecture.md`` and
``docs/health_marketplace_implementation_spec.md``.

The architecture goal is to remove the historical split between in-memory
marketplace bookkeeping (``HEALTH_WALLETS`` and friends in
``web_portal/server.py``) and the durable insurance system. The models below
implement the wallet, settlement, payer-recovery, accounting, and integrity
control tables that the spec calls out as Phase 1 / Phase 2 / Phase 3
foundations.

Design notes:
- All models register against the same ``Base`` declared in ``database.models``
  so ``Base.metadata.create_all`` (called from ``database.init_database``) sees
  them automatically.
- Tables are intentionally *additive*. They do not replace existing
  ``Supplier``/``SupplierOrder`` schemas. Higher-level services (wallet,
  settlement, accounting) will be wired against these new tables while older
  in-memory paths continue to work as compatibility adapters.
- Where the spec lists fields, we keep names aligned so that future migration
  helpers and BI consumers can rely on canonical schemas.

This file deliberately keeps each model compact (no eager relationships) so
that import time and SQLite/PostgreSQL DDL generation stay fast even when the
marketplace surface grows.
"""

from datetime import datetime
from sqlalchemy import (
    Column,
    String,
    Integer,
    Float,
    DateTime,
    Boolean,
    Text,
    UniqueConstraint,
    Index,
)

from .models import Base


# ---------------------------------------------------------------------------
# Wallet, payment, and accounting tables
# ---------------------------------------------------------------------------


class WalletAccount(Base):
    """Canonical durable wallet balance per customer / wallet type / currency.

    Replaces the in-memory ``HEALTH_WALLETS`` dict as the system of record for
    wallet balances. The split between ``available_balance`` and
    ``held_balance`` is enforced through ``WalletHold`` rows; the
    ``posted_balance`` field is a derived snapshot for fast reads.
    """

    __tablename__ = 'wallet_accounts'

    id = Column(String(50), primary_key=True)
    customer_id = Column(String(50), nullable=False, index=True)
    wallet_type = Column(String(50), nullable=False, index=True, default='health')
    currency = Column(String(10), nullable=False, default='USD')
    available_balance = Column(Float, nullable=False, default=0.0)
    held_balance = Column(Float, nullable=False, default=0.0)
    posted_balance = Column(Float, nullable=False, default=0.0)
    status = Column(String(50), nullable=False, default='active')
    version_no = Column(Integer, nullable=False, default=1)
    created_date = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_date = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint('customer_id', 'wallet_type', 'currency',
                         name='uq_wallet_account_customer_type_currency'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'customer_id': self.customer_id,
            'wallet_type': self.wallet_type,
            'currency': self.currency,
            'available_balance': self.available_balance,
            'held_balance': self.held_balance,
            'posted_balance': self.posted_balance,
            'status': self.status,
            'version_no': self.version_no,
            'created_date': self.created_date.isoformat() if self.created_date else None,
            'updated_date': self.updated_date.isoformat() if self.updated_date else None,
        }


class WalletHold(Base):
    """Authorizes wallet funds before supplier confirmation and capture."""

    __tablename__ = 'wallet_holds'

    id = Column(String(50), primary_key=True)
    wallet_account_id = Column(String(50), nullable=False, index=True)
    customer_id = Column(String(50), nullable=False, index=True)
    order_id = Column(String(50), nullable=True, index=True)
    payment_intent_id = Column(String(50), nullable=True, index=True)
    amount = Column(Float, nullable=False, default=0.0)
    currency = Column(String(10), nullable=False, default='USD')
    status = Column(String(50), nullable=False, default='held', index=True)
    expires_at = Column(DateTime, nullable=True)
    capture_reference = Column(String(100), nullable=True)
    release_reason = Column(String(200), nullable=True)
    idempotency_key = Column(String(100), nullable=True, index=True, unique=True)
    created_date = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_date = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'wallet_account_id': self.wallet_account_id,
            'customer_id': self.customer_id,
            'order_id': self.order_id,
            'payment_intent_id': self.payment_intent_id,
            'amount': self.amount,
            'currency': self.currency,
            'status': self.status,
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
            'capture_reference': self.capture_reference,
            'release_reason': self.release_reason,
            'idempotency_key': self.idempotency_key,
            'created_date': self.created_date.isoformat() if self.created_date else None,
            'updated_date': self.updated_date.isoformat() if self.updated_date else None,
        }


class WalletLedgerEntry(Base):
    """Append-only customer wallet sub-ledger.

    Every wallet movement (deposit, hold debit, capture credit, refund, etc.)
    must produce one or more ``WalletLedgerEntry`` rows grouped by
    ``entry_group_id``. Once posted, rows must never be mutated; corrections
    are compensating entries with their own group id.
    """

    __tablename__ = 'wallet_ledger_entries'

    id = Column(String(50), primary_key=True)
    wallet_account_id = Column(String(50), nullable=False, index=True)
    customer_id = Column(String(50), nullable=False, index=True)
    entry_group_id = Column(String(50), nullable=False, index=True)
    entry_type = Column(String(50), nullable=False, index=True)
    direction = Column(String(10), nullable=False)  # 'debit' | 'credit'
    amount = Column(Float, nullable=False, default=0.0)
    currency = Column(String(10), nullable=False, default='USD')
    reference_type = Column(String(50), nullable=True)
    reference_id = Column(String(100), nullable=True, index=True)
    counterparty_type = Column(String(50), nullable=True)
    counterparty_id = Column(String(100), nullable=True)
    status = Column(String(50), nullable=False, default='posted')
    posted_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    metadata_json = Column(Text, nullable=True)
    previous_hash = Column(String(128), nullable=True)
    entry_hash = Column(String(128), nullable=True)

    __table_args__ = (
        Index('ix_wallet_ledger_account_posted', 'wallet_account_id', 'posted_at'),
        Index('ix_wallet_ledger_reference', 'reference_type', 'reference_id'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'wallet_account_id': self.wallet_account_id,
            'customer_id': self.customer_id,
            'entry_group_id': self.entry_group_id,
            'entry_type': self.entry_type,
            'direction': self.direction,
            'amount': self.amount,
            'currency': self.currency,
            'reference_type': self.reference_type,
            'reference_id': self.reference_id,
            'counterparty_type': self.counterparty_type,
            'counterparty_id': self.counterparty_id,
            'status': self.status,
            'posted_at': self.posted_at.isoformat() if self.posted_at else None,
            'metadata_json': self.metadata_json,
            'previous_hash': self.previous_hash,
            'entry_hash': self.entry_hash,
        }


class PaymentIntent(Base):
    """Single payment object for wallet, card, payer, or mixed-tender flows."""

    __tablename__ = 'payment_intents'

    id = Column(String(50), primary_key=True)
    customer_id = Column(String(50), nullable=False, index=True)
    order_id = Column(String(50), nullable=True, index=True)
    quote_id = Column(String(50), nullable=True, index=True)
    funding_strategy = Column(String(50), nullable=False, default='wallet')
    status = Column(String(50), nullable=False, default='pending', index=True)
    currency = Column(String(10), nullable=False, default='USD')
    total_amount = Column(Float, nullable=False, default=0.0)
    wallet_amount = Column(Float, nullable=False, default=0.0)
    external_amount = Column(Float, nullable=False, default=0.0)
    payer_amount = Column(Float, nullable=False, default=0.0)
    psp_reference = Column(String(100), nullable=True)
    payer_authorization_reference = Column(String(100), nullable=True)
    idempotency_key = Column(String(100), nullable=True, index=True, unique=True)
    created_date = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_date = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'customer_id': self.customer_id,
            'order_id': self.order_id,
            'quote_id': self.quote_id,
            'funding_strategy': self.funding_strategy,
            'status': self.status,
            'currency': self.currency,
            'total_amount': self.total_amount,
            'wallet_amount': self.wallet_amount,
            'external_amount': self.external_amount,
            'payer_amount': self.payer_amount,
            'psp_reference': self.psp_reference,
            'payer_authorization_reference': self.payer_authorization_reference,
            'idempotency_key': self.idempotency_key,
            'created_date': self.created_date.isoformat() if self.created_date else None,
            'updated_date': self.updated_date.isoformat() if self.updated_date else None,
        }


class Refund(Base):
    """Durable reversal workflow for customer/supplier/payer-driven refunds."""

    __tablename__ = 'marketplace_refunds'

    id = Column(String(50), primary_key=True)
    order_id = Column(String(50), nullable=False, index=True)
    payment_intent_id = Column(String(50), nullable=True, index=True)
    wallet_ledger_entry_id = Column(String(50), nullable=True)
    funding_source = Column(String(50), nullable=False, default='wallet')
    reason_code = Column(String(50), nullable=False, default='customer_cancel')
    status = Column(String(50), nullable=False, default='pending', index=True)
    amount = Column(Float, nullable=False, default=0.0)
    currency = Column(String(10), nullable=False, default='USD')
    requested_by = Column(String(100), nullable=True)
    approved_by = Column(String(100), nullable=True)
    external_refund_reference = Column(String(100), nullable=True)
    created_date = Column(DateTime, default=datetime.utcnow, nullable=False)
    processed_date = Column(DateTime, nullable=True)

    def to_dict(self):
        return {
            'id': self.id,
            'order_id': self.order_id,
            'payment_intent_id': self.payment_intent_id,
            'wallet_ledger_entry_id': self.wallet_ledger_entry_id,
            'funding_source': self.funding_source,
            'reason_code': self.reason_code,
            'status': self.status,
            'amount': self.amount,
            'currency': self.currency,
            'requested_by': self.requested_by,
            'approved_by': self.approved_by,
            'external_refund_reference': self.external_refund_reference,
            'created_date': self.created_date.isoformat() if self.created_date else None,
            'processed_date': self.processed_date.isoformat() if self.processed_date else None,
        }


class JournalEntry(Base):
    """Accounting view for marketplace revenue, payable, receivable, etc.

    Account codes follow the canonical list defined in the implementation
    spec: ``wallet_cash``, ``wallet_holds``, ``marketplace_clearing``,
    ``supplier_payable``, ``marketplace_revenue``,
    ``deferred_marketplace_revenue``, ``marketplace_contra_revenue``,
    ``payer_receivable``, ``refund_liability``, ``claims_reserve``,
    ``supplier_reserve_holdback``.
    """

    __tablename__ = 'journal_entries'

    id = Column(String(50), primary_key=True)
    entry_group_id = Column(String(50), nullable=False, index=True)
    account_code = Column(String(80), nullable=False, index=True)
    direction = Column(String(10), nullable=False)  # 'debit' | 'credit'
    amount = Column(Float, nullable=False, default=0.0)
    currency = Column(String(10), nullable=False, default='USD')
    reference_type = Column(String(50), nullable=True)
    reference_id = Column(String(100), nullable=True, index=True)
    journal_date = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    description = Column(Text, nullable=True)
    metadata_json = Column(Text, nullable=True)

    def to_dict(self):
        return {
            'id': self.id,
            'entry_group_id': self.entry_group_id,
            'account_code': self.account_code,
            'direction': self.direction,
            'amount': self.amount,
            'currency': self.currency,
            'reference_type': self.reference_type,
            'reference_id': self.reference_id,
            'journal_date': self.journal_date.isoformat() if self.journal_date else None,
            'description': self.description,
            'metadata_json': self.metadata_json,
        }


# ---------------------------------------------------------------------------
# Supplier settlement tables
# ---------------------------------------------------------------------------


class SupplierSettlementRun(Base):
    """Batch execution boundary for supplier payouts."""

    __tablename__ = 'supplier_settlement_runs'

    id = Column(String(50), primary_key=True)
    supplier_id = Column(String(50), nullable=False, index=True)
    run_date = Column(DateTime, default=datetime.utcnow, nullable=False)
    settlement_period_start = Column(DateTime, nullable=True)
    settlement_period_end = Column(DateTime, nullable=True)
    status = Column(String(50), nullable=False, default='pending', index=True)
    gross_amount = Column(Float, nullable=False, default=0.0)
    net_amount = Column(Float, nullable=False, default=0.0)
    holdback_amount = Column(Float, nullable=False, default=0.0)
    adjustment_amount = Column(Float, nullable=False, default=0.0)
    currency = Column(String(10), nullable=False, default='USD')
    executed_by = Column(String(100), nullable=True)
    external_payout_reference = Column(String(100), nullable=True)
    created_date = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_date = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'supplier_id': self.supplier_id,
            'run_date': self.run_date.isoformat() if self.run_date else None,
            'settlement_period_start': self.settlement_period_start.isoformat() if self.settlement_period_start else None,
            'settlement_period_end': self.settlement_period_end.isoformat() if self.settlement_period_end else None,
            'status': self.status,
            'gross_amount': self.gross_amount,
            'net_amount': self.net_amount,
            'holdback_amount': self.holdback_amount,
            'adjustment_amount': self.adjustment_amount,
            'currency': self.currency,
            'executed_by': self.executed_by,
            'external_payout_reference': self.external_payout_reference,
            'created_date': self.created_date.isoformat() if self.created_date else None,
            'updated_date': self.updated_date.isoformat() if self.updated_date else None,
        }


class SupplierSettlementItem(Base):
    """Order-level settlement rows under a settlement run."""

    __tablename__ = 'supplier_settlement_items'

    id = Column(String(50), primary_key=True)
    settlement_run_id = Column(String(50), nullable=False, index=True)
    supplier_id = Column(String(50), nullable=False, index=True)
    order_id = Column(String(50), nullable=False, index=True)
    gross_sales_amount = Column(Float, nullable=False, default=0.0)
    markup_amount = Column(Float, nullable=False, default=0.0)
    supplier_payout_amount = Column(Float, nullable=False, default=0.0)
    holdback_amount = Column(Float, nullable=False, default=0.0)
    penalty_amount = Column(Float, nullable=False, default=0.0)
    adjustment_amount = Column(Float, nullable=False, default=0.0)
    status = Column(String(50), nullable=False, default='pending', index=True)
    created_date = Column(DateTime, default=datetime.utcnow, nullable=False)

    def to_dict(self):
        return {
            'id': self.id,
            'settlement_run_id': self.settlement_run_id,
            'supplier_id': self.supplier_id,
            'order_id': self.order_id,
            'gross_sales_amount': self.gross_sales_amount,
            'markup_amount': self.markup_amount,
            'supplier_payout_amount': self.supplier_payout_amount,
            'holdback_amount': self.holdback_amount,
            'penalty_amount': self.penalty_amount,
            'adjustment_amount': self.adjustment_amount,
            'status': self.status,
            'created_date': self.created_date.isoformat() if self.created_date else None,
        }


# ---------------------------------------------------------------------------
# External payer recovery tables
# ---------------------------------------------------------------------------


class ExternalPayer(Base):
    """Payer directory for insurers, TPAs, employers, and sponsors."""

    __tablename__ = 'external_payers'

    id = Column(String(50), primary_key=True)
    payer_name = Column(String(200), nullable=False)
    payer_type = Column(String(50), nullable=False, default='insurer')
    country = Column(String(10), nullable=True)
    currency = Column(String(10), nullable=False, default='USD')
    status = Column(String(50), nullable=False, default='active')
    eligibility_endpoint = Column(String(500), nullable=True)
    preauth_endpoint = Column(String(500), nullable=True)
    claims_endpoint = Column(String(500), nullable=True)
    remittance_import_mode = Column(String(50), nullable=True)
    connector_config_json = Column(Text, nullable=True)
    created_date = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_date = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'payer_name': self.payer_name,
            'payer_type': self.payer_type,
            'country': self.country,
            'currency': self.currency,
            'status': self.status,
            'eligibility_endpoint': self.eligibility_endpoint,
            'preauth_endpoint': self.preauth_endpoint,
            'claims_endpoint': self.claims_endpoint,
            'remittance_import_mode': self.remittance_import_mode,
            'connector_config_json': self.connector_config_json,
            'created_date': self.created_date.isoformat() if self.created_date else None,
            'updated_date': self.updated_date.isoformat() if self.updated_date else None,
        }


class MarketplaceClaim(Base):
    """Claim-as-a-service record created from marketplace orders."""

    __tablename__ = 'marketplace_claims'

    id = Column(String(50), primary_key=True)
    order_id = Column(String(50), nullable=False, index=True)
    customer_id = Column(String(50), nullable=False, index=True)
    payer_id = Column(String(50), nullable=True, index=True)
    claim_type = Column(String(50), nullable=False, default='reimbursement')
    status = Column(String(50), nullable=False, default='draft', index=True)
    claimed_amount = Column(Float, nullable=False, default=0.0)
    approved_amount = Column(Float, nullable=False, default=0.0)
    denied_amount = Column(Float, nullable=False, default=0.0)
    submission_reference = Column(String(100), nullable=True)
    diagnosis_code = Column(String(100), nullable=True)
    service_date = Column(DateTime, nullable=True)
    submitted_at = Column(DateTime, nullable=True)
    adjudicated_at = Column(DateTime, nullable=True)
    metadata_json = Column(Text, nullable=True)
    created_date = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_date = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'order_id': self.order_id,
            'customer_id': self.customer_id,
            'payer_id': self.payer_id,
            'claim_type': self.claim_type,
            'status': self.status,
            'claimed_amount': self.claimed_amount,
            'approved_amount': self.approved_amount,
            'denied_amount': self.denied_amount,
            'submission_reference': self.submission_reference,
            'diagnosis_code': self.diagnosis_code,
            'service_date': self.service_date.isoformat() if self.service_date else None,
            'submitted_at': self.submitted_at.isoformat() if self.submitted_at else None,
            'adjudicated_at': self.adjudicated_at.isoformat() if self.adjudicated_at else None,
            'metadata_json': self.metadata_json,
            'created_date': self.created_date.isoformat() if self.created_date else None,
            'updated_date': self.updated_date.isoformat() if self.updated_date else None,
        }


class RemittanceAdvice(Base):
    """Import header for payer remittance batches."""

    __tablename__ = 'remittance_advices'

    id = Column(String(50), primary_key=True)
    payer_id = Column(String(50), nullable=False, index=True)
    remittance_reference = Column(String(100), nullable=True, index=True)
    status = Column(String(50), nullable=False, default='received')
    received_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    total_paid_amount = Column(Float, nullable=False, default=0.0)
    total_denied_amount = Column(Float, nullable=False, default=0.0)
    raw_payload_json = Column(Text, nullable=True)

    def to_dict(self):
        return {
            'id': self.id,
            'payer_id': self.payer_id,
            'remittance_reference': self.remittance_reference,
            'status': self.status,
            'received_at': self.received_at.isoformat() if self.received_at else None,
            'total_paid_amount': self.total_paid_amount,
            'total_denied_amount': self.total_denied_amount,
            'raw_payload_json': self.raw_payload_json,
        }


class RemittanceLine(Base):
    """One remittance row per claim or order line."""

    __tablename__ = 'remittance_lines'

    id = Column(String(50), primary_key=True)
    remittance_advice_id = Column(String(50), nullable=False, index=True)
    marketplace_claim_id = Column(String(50), nullable=True, index=True)
    order_id = Column(String(50), nullable=True, index=True)
    line_status = Column(String(50), nullable=False, default='paid')
    paid_amount = Column(Float, nullable=False, default=0.0)
    denied_amount = Column(Float, nullable=False, default=0.0)
    adjustment_reason_code = Column(String(50), nullable=True)
    created_date = Column(DateTime, default=datetime.utcnow, nullable=False)

    def to_dict(self):
        return {
            'id': self.id,
            'remittance_advice_id': self.remittance_advice_id,
            'marketplace_claim_id': self.marketplace_claim_id,
            'order_id': self.order_id,
            'line_status': self.line_status,
            'paid_amount': self.paid_amount,
            'denied_amount': self.denied_amount,
            'adjustment_reason_code': self.adjustment_reason_code,
            'created_date': self.created_date.isoformat() if self.created_date else None,
        }


class PayerReceivable(Base):
    """Open recovery ledger for PHINS-advanced or customer-reimbursable funds."""

    __tablename__ = 'payer_receivables'

    id = Column(String(50), primary_key=True)
    payer_id = Column(String(50), nullable=False, index=True)
    marketplace_claim_id = Column(String(50), nullable=True, index=True)
    order_id = Column(String(50), nullable=True, index=True)
    customer_id = Column(String(50), nullable=True, index=True)
    expected_amount = Column(Float, nullable=False, default=0.0)
    open_amount = Column(Float, nullable=False, default=0.0)
    received_amount = Column(Float, nullable=False, default=0.0)
    writeoff_amount = Column(Float, nullable=False, default=0.0)
    status = Column(String(50), nullable=False, default='open', index=True)
    due_date = Column(DateTime, nullable=True)
    last_activity_at = Column(DateTime, nullable=True)
    created_date = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_date = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'payer_id': self.payer_id,
            'marketplace_claim_id': self.marketplace_claim_id,
            'order_id': self.order_id,
            'customer_id': self.customer_id,
            'expected_amount': self.expected_amount,
            'open_amount': self.open_amount,
            'received_amount': self.received_amount,
            'writeoff_amount': self.writeoff_amount,
            'status': self.status,
            'due_date': self.due_date.isoformat() if self.due_date else None,
            'last_activity_at': self.last_activity_at.isoformat() if self.last_activity_at else None,
            'created_date': self.created_date.isoformat() if self.created_date else None,
            'updated_date': self.updated_date.isoformat() if self.updated_date else None,
        }


# ---------------------------------------------------------------------------
# Integrity and event control tables
# ---------------------------------------------------------------------------


class IdempotencyKey(Base):
    """Durable request-replay protection for write endpoints."""

    __tablename__ = 'idempotency_keys'

    id = Column(String(50), primary_key=True)
    scope = Column(String(80), nullable=False, index=True)
    idempotency_key = Column(String(100), nullable=False, unique=True, index=True)
    request_hash = Column(String(128), nullable=True)
    resource_type = Column(String(80), nullable=True)
    resource_id = Column(String(100), nullable=True)
    response_snapshot_json = Column(Text, nullable=True)
    status = Column(String(50), nullable=False, default='created')
    created_date = Column(DateTime, default=datetime.utcnow, nullable=False)

    def to_dict(self):
        return {
            'id': self.id,
            'scope': self.scope,
            'idempotency_key': self.idempotency_key,
            'request_hash': self.request_hash,
            'resource_type': self.resource_type,
            'resource_id': self.resource_id,
            'response_snapshot_json': self.response_snapshot_json,
            'status': self.status,
            'created_date': self.created_date.isoformat() if self.created_date else None,
        }


class OutboxEvent(Base):
    """Transactional outbox for canonical BI / AI / event publication.

    Event types follow the canonical vocabulary described in
    ``docs/health_marketplace_architecture.md`` (e.g.
    ``order.created``, ``wallet.hold_created``, ``settlement.calculated``,
    ``remittance.received``, ``refund.completed``,
    ``integrity.violation_detected``).
    """

    __tablename__ = 'marketplace_outbox_events'

    id = Column(String(50), primary_key=True)
    aggregate_type = Column(String(80), nullable=False, index=True)
    aggregate_id = Column(String(100), nullable=False, index=True)
    event_type = Column(String(100), nullable=False, index=True)
    event_version = Column(String(20), nullable=False, default='1')
    payload_json = Column(Text, nullable=True)
    status = Column(String(50), nullable=False, default='pending', index=True)
    published_at = Column(DateTime, nullable=True)
    created_date = Column(DateTime, default=datetime.utcnow, nullable=False)

    def to_dict(self):
        return {
            'id': self.id,
            'aggregate_type': self.aggregate_type,
            'aggregate_id': self.aggregate_id,
            'event_type': self.event_type,
            'event_version': self.event_version,
            'payload_json': self.payload_json,
            'status': self.status,
            'published_at': self.published_at.isoformat() if self.published_at else None,
            'created_date': self.created_date.isoformat() if self.created_date else None,
        }


__all__ = [
    'WalletAccount',
    'WalletHold',
    'WalletLedgerEntry',
    'PaymentIntent',
    'Refund',
    'JournalEntry',
    'SupplierSettlementRun',
    'SupplierSettlementItem',
    'ExternalPayer',
    'MarketplaceClaim',
    'RemittanceAdvice',
    'RemittanceLine',
    'PayerReceivable',
    'IdempotencyKey',
    'OutboxEvent',
]
