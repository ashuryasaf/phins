"""
Health Marketplace Repositories

Repository-pattern data access for the durable health-marketplace tables
introduced in ``database/marketplace_models.py``. Aligns with the boundaries
laid out in ``docs/health_marketplace_implementation_spec.md``:

- wallet accounts / holds / ledger entries
- payment intents and refunds
- accounting journal entries
- supplier settlement runs and items
- external payers, marketplace claims, payer receivables
- remittance advices and lines
- idempotency keys and outbox events

Each repository extends ``BaseRepository`` to inherit common CRUD plus
auto-commit semantics, and adds focused helpers (lookups, aging, append-only
posting, balance rollups) that the services need.
"""

from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta, timezone
from sqlalchemy import func
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
import logging

from .base import BaseRepository
from database.marketplace_models import (
    WalletAccount,
    WalletHold,
    WalletLedgerEntry,
    PaymentIntent,
    Refund,
    JournalEntry,
    SupplierSettlementRun,
    SupplierSettlementItem,
    ExternalPayer,
    MarketplaceClaim,
    RemittanceAdvice,
    RemittanceLine,
    PayerReceivable,
    IdempotencyKey,
    OutboxEvent,
)

logger = logging.getLogger(__name__)


class WalletAccountRepository(BaseRepository):
    """Wallet accounts: durable balance per (customer, wallet_type, currency)."""

    def __init__(self, session: Session):
        super().__init__(WalletAccount, session)

    def get_for_customer(
        self,
        customer_id: str,
        wallet_type: str = 'health',
        currency: str = 'USD',
        *,
        for_update: bool = False,
    ) -> Optional[WalletAccount]:
        try:
            q = (
                self.session.query(WalletAccount)
                .filter_by(customer_id=customer_id, wallet_type=wallet_type, currency=currency)
            )
            if for_update:
                q = q.with_for_update()
            return q.first()
        except SQLAlchemyError as e:
            logger.error(f"Error fetching wallet for {customer_id}: {e}")
            return None

    def adjust_balances(
        self,
        wallet_id: str,
        available_delta: float = 0.0,
        held_delta: float = 0.0,
        posted_delta: float = 0.0,
    ) -> Optional[WalletAccount]:
        try:
            wallet = self.get_by_id(wallet_id)
            if not wallet:
                return None
            wallet.available_balance = float(wallet.available_balance or 0.0) + float(available_delta)
            wallet.held_balance = float(wallet.held_balance or 0.0) + float(held_delta)
            wallet.posted_balance = float(wallet.posted_balance or 0.0) + float(posted_delta)
            wallet.version_no = int(wallet.version_no or 1) + 1
            wallet.updated_date = datetime.utcnow()
            self.session.commit()
            self.session.refresh(wallet)
            return wallet
        except SQLAlchemyError as e:
            logger.error(f"Error adjusting wallet {wallet_id}: {e}")
            self.session.rollback()
            return None


class WalletHoldRepository(BaseRepository):
    """Wallet holds: authorize before capture."""

    def __init__(self, session: Session):
        super().__init__(WalletHold, session)

    def get_active_for_account(self, wallet_account_id: str) -> List[WalletHold]:
        try:
            return (
                self.session.query(WalletHold)
                .filter_by(wallet_account_id=wallet_account_id, status='held')
                .all()
            )
        except SQLAlchemyError as e:
            logger.error(f"Error fetching active holds: {e}")
            return []

    def get_by_idempotency(self, key: str) -> Optional[WalletHold]:
        if not key:
            return None
        try:
            return self.session.query(WalletHold).filter_by(idempotency_key=key).first()
        except SQLAlchemyError as e:
            logger.error(f"Error fetching hold by idempotency key: {e}")
            return None

    def get_by_order(self, order_id: str) -> List[WalletHold]:
        try:
            return self.session.query(WalletHold).filter_by(order_id=order_id).all()
        except SQLAlchemyError as e:
            logger.error(f"Error fetching holds for order: {e}")
            return []

    def total_held_for_account(self, wallet_account_id: str) -> float:
        try:
            value = (
                self.session.query(func.coalesce(func.sum(WalletHold.amount), 0.0))
                .filter(
                    WalletHold.wallet_account_id == wallet_account_id,
                    WalletHold.status == 'held',
                )
                .scalar()
            )
            return float(value or 0.0)
        except SQLAlchemyError as e:
            logger.error(f"Error summing holds: {e}")
            return 0.0


class WalletLedgerRepository(BaseRepository):
    """Append-only wallet sub-ledger postings."""

    def __init__(self, session: Session):
        super().__init__(WalletLedgerEntry, session)

    def get_by_group(self, entry_group_id: str) -> List[WalletLedgerEntry]:
        try:
            return (
                self.session.query(WalletLedgerEntry)
                .filter_by(entry_group_id=entry_group_id)
                .order_by(WalletLedgerEntry.posted_at.asc())
                .all()
            )
        except SQLAlchemyError as e:
            logger.error(f"Error fetching ledger group: {e}")
            return []

    def get_by_reference(
        self, reference_type: str, reference_id: str
    ) -> List[WalletLedgerEntry]:
        try:
            return (
                self.session.query(WalletLedgerEntry)
                .filter_by(reference_type=reference_type, reference_id=reference_id)
                .all()
            )
        except SQLAlchemyError as e:
            logger.error(f"Error fetching ledger by reference: {e}")
            return []

    def derive_balance(self, wallet_account_id: str) -> float:
        """Return derived posted balance: sum(credits) - sum(debits) for the account.

        This is the canonical balance source. ``WalletAccount.posted_balance``
        is a cache that must agree with this number.
        """
        try:
            credits = (
                self.session.query(func.coalesce(func.sum(WalletLedgerEntry.amount), 0.0))
                .filter(
                    WalletLedgerEntry.wallet_account_id == wallet_account_id,
                    WalletLedgerEntry.direction == 'credit',
                )
                .scalar()
                or 0.0
            )
            debits = (
                self.session.query(func.coalesce(func.sum(WalletLedgerEntry.amount), 0.0))
                .filter(
                    WalletLedgerEntry.wallet_account_id == wallet_account_id,
                    WalletLedgerEntry.direction == 'debit',
                )
                .scalar()
                or 0.0
            )
            return float(credits) - float(debits)
        except SQLAlchemyError as e:
            logger.error(f"Error deriving wallet balance: {e}")
            return 0.0


class PaymentIntentRepository(BaseRepository):
    def __init__(self, session: Session):
        super().__init__(PaymentIntent, session)

    def get_by_idempotency(self, key: str) -> Optional[PaymentIntent]:
        if not key:
            return None
        try:
            return self.session.query(PaymentIntent).filter_by(idempotency_key=key).first()
        except SQLAlchemyError as e:
            logger.error(f"Error fetching payment intent: {e}")
            return None

    def get_for_order(self, order_id: str) -> List[PaymentIntent]:
        try:
            return self.session.query(PaymentIntent).filter_by(order_id=order_id).all()
        except SQLAlchemyError as e:
            logger.error(f"Error fetching intents for order: {e}")
            return []


class RefundRepository(BaseRepository):
    def __init__(self, session: Session):
        super().__init__(Refund, session)

    def get_for_order(self, order_id: str) -> List[Refund]:
        try:
            return self.session.query(Refund).filter_by(order_id=order_id).all()
        except SQLAlchemyError as e:
            logger.error(f"Error fetching refunds for order: {e}")
            return []

    def get_by_status(self, status: str) -> List[Refund]:
        try:
            return self.session.query(Refund).filter_by(status=status).all()
        except SQLAlchemyError as e:
            logger.error(f"Error fetching refunds by status: {e}")
            return []


class JournalRepository(BaseRepository):
    def __init__(self, session: Session):
        super().__init__(JournalEntry, session)

    def get_by_account(self, account_code: str) -> List[JournalEntry]:
        try:
            return self.session.query(JournalEntry).filter_by(account_code=account_code).all()
        except SQLAlchemyError as e:
            logger.error(f"Error fetching journal by account: {e}")
            return []

    def get_by_group(self, entry_group_id: str) -> List[JournalEntry]:
        try:
            return (
                self.session.query(JournalEntry)
                .filter_by(entry_group_id=entry_group_id)
                .order_by(JournalEntry.journal_date.asc())
                .all()
            )
        except SQLAlchemyError as e:
            logger.error(f"Error fetching journal group: {e}")
            return []

    def account_balance(self, account_code: str) -> Dict[str, float]:
        """Return ``{credits, debits, balance}`` for a given account code."""
        try:
            credits = (
                self.session.query(func.coalesce(func.sum(JournalEntry.amount), 0.0))
                .filter(JournalEntry.account_code == account_code, JournalEntry.direction == 'credit')
                .scalar()
                or 0.0
            )
            debits = (
                self.session.query(func.coalesce(func.sum(JournalEntry.amount), 0.0))
                .filter(JournalEntry.account_code == account_code, JournalEntry.direction == 'debit')
                .scalar()
                or 0.0
            )
            return {
                'credits': float(credits),
                'debits': float(debits),
                'balance': float(credits) - float(debits),
            }
        except SQLAlchemyError as e:
            logger.error(f"Error computing account balance: {e}")
            return {'credits': 0.0, 'debits': 0.0, 'balance': 0.0}


class SupplierSettlementRunRepository(BaseRepository):
    def __init__(self, session: Session):
        super().__init__(SupplierSettlementRun, session)

    def get_by_supplier(self, supplier_id: str) -> List[SupplierSettlementRun]:
        try:
            return (
                self.session.query(SupplierSettlementRun)
                .filter_by(supplier_id=supplier_id)
                .order_by(SupplierSettlementRun.run_date.desc())
                .all()
            )
        except SQLAlchemyError as e:
            logger.error(f"Error fetching settlement runs: {e}")
            return []

    def get_by_status(self, status: str) -> List[SupplierSettlementRun]:
        try:
            return self.session.query(SupplierSettlementRun).filter_by(status=status).all()
        except SQLAlchemyError as e:
            logger.error(f"Error fetching runs by status: {e}")
            return []

    def aging_buckets(self, now: Optional[datetime] = None) -> Dict[str, int]:
        """Return aging buckets for unpaid settlement runs."""
        now = now or datetime.utcnow()
        buckets = {'0_7': 0, '8_30': 0, '31_60': 0, '60_plus': 0}
        try:
            rows = (
                self.session.query(SupplierSettlementRun)
                .filter(SupplierSettlementRun.status.in_(['pending', 'queued', 'calculated']))
                .all()
            )
            for r in rows:
                created = r.run_date or r.created_date or now
                age = (now - created).days if created else 0
                if age <= 7:
                    buckets['0_7'] += 1
                elif age <= 30:
                    buckets['8_30'] += 1
                elif age <= 60:
                    buckets['31_60'] += 1
                else:
                    buckets['60_plus'] += 1
        except SQLAlchemyError as e:
            logger.error(f"Error computing settlement aging: {e}")
        return buckets


class SupplierSettlementItemRepository(BaseRepository):
    def __init__(self, session: Session):
        super().__init__(SupplierSettlementItem, session)

    def get_for_run(self, settlement_run_id: str) -> List[SupplierSettlementItem]:
        try:
            return (
                self.session.query(SupplierSettlementItem)
                .filter_by(settlement_run_id=settlement_run_id)
                .all()
            )
        except SQLAlchemyError as e:
            logger.error(f"Error fetching settlement items: {e}")
            return []

    def get_for_order(self, order_id: str) -> List[SupplierSettlementItem]:
        try:
            return self.session.query(SupplierSettlementItem).filter_by(order_id=order_id).all()
        except SQLAlchemyError as e:
            logger.error(f"Error fetching settlement items for order: {e}")
            return []


class ExternalPayerRepository(BaseRepository):
    def __init__(self, session: Session):
        super().__init__(ExternalPayer, session)


class MarketplaceClaimRepository(BaseRepository):
    def __init__(self, session: Session):
        super().__init__(MarketplaceClaim, session)

    def get_by_status(self, status: str) -> List[MarketplaceClaim]:
        try:
            return self.session.query(MarketplaceClaim).filter_by(status=status).all()
        except SQLAlchemyError as e:
            logger.error(f"Error fetching claims by status: {e}")
            return []

    def get_for_order(self, order_id: str) -> List[MarketplaceClaim]:
        try:
            return self.session.query(MarketplaceClaim).filter_by(order_id=order_id).all()
        except SQLAlchemyError as e:
            logger.error(f"Error fetching claims for order: {e}")
            return []


class RemittanceRepository(BaseRepository):
    """Bundles remittance advice + line operations."""

    def __init__(self, session: Session):
        super().__init__(RemittanceAdvice, session)

    def get_lines(self, advice_id: str) -> List[RemittanceLine]:
        try:
            return self.session.query(RemittanceLine).filter_by(remittance_advice_id=advice_id).all()
        except SQLAlchemyError as e:
            logger.error(f"Error fetching remittance lines: {e}")
            return []

    def add_line(self, **kwargs) -> Optional[RemittanceLine]:
        try:
            allowed = {c.name for c in RemittanceLine.__table__.columns}  # type: ignore[attr-defined]
            kwargs = {k: v for k, v in kwargs.items() if k in allowed}
            line = RemittanceLine(**kwargs)
            self.session.add(line)
            self.session.commit()
            self.session.refresh(line)
            return line
        except SQLAlchemyError as e:
            logger.error(f"Error adding remittance line: {e}")
            self.session.rollback()
            return None

    def get_unmatched_lines(self) -> List[RemittanceLine]:
        try:
            return (
                self.session.query(RemittanceLine)
                .filter(
                    (RemittanceLine.marketplace_claim_id.is_(None))
                    & (RemittanceLine.order_id.is_(None))
                )
                .all()
            )
        except SQLAlchemyError as e:
            logger.error(f"Error fetching unmatched remittance lines: {e}")
            return []


class PayerReceivableRepository(BaseRepository):
    def __init__(self, session: Session):
        super().__init__(PayerReceivable, session)

    def get_open(self) -> List[PayerReceivable]:
        try:
            return self.session.query(PayerReceivable).filter_by(status='open').all()
        except SQLAlchemyError as e:
            logger.error(f"Error fetching open receivables: {e}")
            return []

    def get_for_payer(self, payer_id: str) -> List[PayerReceivable]:
        try:
            return self.session.query(PayerReceivable).filter_by(payer_id=payer_id).all()
        except SQLAlchemyError as e:
            logger.error(f"Error fetching receivables for payer: {e}")
            return []

    def aging_buckets(self, now: Optional[datetime] = None) -> Dict[str, Dict[str, float]]:
        """Return aging buckets keyed ``0_30``, ``31_60``, ``61_90``, ``90_plus``.

        Each value carries ``count`` and ``open_amount`` for finance dashboards.
        """
        now = now or datetime.utcnow()
        buckets = {
            '0_30': {'count': 0, 'open_amount': 0.0},
            '31_60': {'count': 0, 'open_amount': 0.0},
            '61_90': {'count': 0, 'open_amount': 0.0},
            '90_plus': {'count': 0, 'open_amount': 0.0},
        }
        try:
            rows = self.session.query(PayerReceivable).filter_by(status='open').all()
            for r in rows:
                due = r.due_date or r.created_date or now
                age = (now - due).days if due else 0
                if age <= 30:
                    key = '0_30'
                elif age <= 60:
                    key = '31_60'
                elif age <= 90:
                    key = '61_90'
                else:
                    key = '90_plus'
                buckets[key]['count'] += 1
                buckets[key]['open_amount'] += float(r.open_amount or 0.0)
        except SQLAlchemyError as e:
            logger.error(f"Error computing receivable aging: {e}")
        return buckets


class IdempotencyRepository(BaseRepository):
    def __init__(self, session: Session):
        super().__init__(IdempotencyKey, session)

    def get_by_key(self, key: str) -> Optional[IdempotencyKey]:
        if not key:
            return None
        try:
            return self.session.query(IdempotencyKey).filter_by(idempotency_key=key).first()
        except SQLAlchemyError as e:
            logger.error(f"Error fetching idempotency key: {e}")
            return None


class OutboxRepository(BaseRepository):
    def __init__(self, session: Session):
        super().__init__(OutboxEvent, session)

    def get_pending(self, limit: int = 50) -> List[OutboxEvent]:
        try:
            return (
                self.session.query(OutboxEvent)
                .filter_by(status='pending')
                .order_by(OutboxEvent.created_date.asc())
                .limit(limit)
                .all()
            )
        except SQLAlchemyError as e:
            logger.error(f"Error fetching pending outbox events: {e}")
            return []

    def mark_published(self, event_id: str) -> bool:
        try:
            ev = self.get_by_id(event_id)
            if not ev:
                return False
            ev.status = 'published'
            ev.published_at = datetime.utcnow()
            self.session.commit()
            return True
        except SQLAlchemyError as e:
            logger.error(f"Error marking event published: {e}")
            self.session.rollback()
            return False


__all__ = [
    'WalletAccountRepository',
    'WalletHoldRepository',
    'WalletLedgerRepository',
    'PaymentIntentRepository',
    'RefundRepository',
    'JournalRepository',
    'SupplierSettlementRunRepository',
    'SupplierSettlementItemRepository',
    'ExternalPayerRepository',
    'MarketplaceClaimRepository',
    'RemittanceRepository',
    'PayerReceivableRepository',
    'IdempotencyRepository',
    'OutboxRepository',
]
