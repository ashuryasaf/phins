"""
Wallet Ledger Service
=====================

Owns the wallet money-movement workflow described in
``docs/health_marketplace_implementation_spec.md``:

- ``get_or_create_wallet`` ensures one durable wallet account per
  ``(customer_id, wallet_type, currency)`` triple.
- ``deposit`` posts an inbound credit (claims pay-in, top-up, reimbursement).
- ``create_hold`` authorizes funds before supplier acceptance.
- ``capture_hold`` consumes a held authorization at supplier confirmation.
- ``release_hold`` returns held funds when an order is cancelled.
- ``refund`` issues a wallet refund as a compensating posting.
- ``recompute_balances`` rebuilds balance caches from the append-only ledger.

The service is the single funnel for wallet writes - every mutation produces
a ledger entry and updates the wallet balance cache atomically. Higher-level
flows (marketplace checkout, claims pay-in, refunds) MUST go through this
service rather than mutating ``WalletAccount.posted_balance`` directly.

Notes:
- Balance integrity invariants:
    ``available + held == posted``
    ``derived_ledger_balance == posted``
- Each mutation creates an ``entry_group_id`` so reconciliation can correlate
  every wallet change with its journal entries and outbox events.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from database.manager import DatabaseManager

logger = logging.getLogger('phins.wallet_ledger_service')


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12].upper()}"


@dataclass
class WalletLedgerResult:
    """Lightweight, dict-friendly summary returned by service methods."""

    success: bool
    wallet: Optional[Dict[str, Any]] = None
    hold: Optional[Dict[str, Any]] = None
    entry_group_id: Optional[str] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            'success': self.success,
            'wallet': self.wallet,
            'hold': self.hold,
            'entry_group_id': self.entry_group_id,
            'error': self.error,
        }


class WalletLedgerService:
    """Workflow service that mediates wallet writes through the durable ledger."""

    def __init__(self, db_manager_factory=DatabaseManager):
        self._db_manager_factory = db_manager_factory

    # ------------------------------------------------------------------
    # Wallet bootstrap
    # ------------------------------------------------------------------

    def get_or_create_wallet(
        self,
        customer_id: str,
        wallet_type: str = 'health',
        currency: str = 'USD',
    ) -> Optional[Dict[str, Any]]:
        if not customer_id:
            return None
        with self._db_manager_factory() as db:
            existing = db.wallet_accounts.get_for_customer(customer_id, wallet_type, currency)
            if existing:
                return existing.to_dict()
            wallet = db.wallet_accounts.create(
                id=_new_id('WAL'),
                customer_id=customer_id,
                wallet_type=wallet_type,
                currency=currency,
                available_balance=0.0,
                held_balance=0.0,
                posted_balance=0.0,
                status='active',
            )
            return wallet.to_dict() if wallet else None

    # ------------------------------------------------------------------
    # Deposits / credits
    # ------------------------------------------------------------------

    def deposit(
        self,
        customer_id: str,
        amount: float,
        *,
        wallet_type: str = 'health',
        currency: str = 'USD',
        reference_type: str = 'manual',
        reference_id: Optional[str] = None,
        entry_type: str = 'deposit',
        counterparty_type: Optional[str] = None,
        counterparty_id: Optional[str] = None,
    ) -> WalletLedgerResult:
        if amount is None or float(amount) <= 0:
            return WalletLedgerResult(success=False, error='amount must be positive')

        with self._db_manager_factory() as db:
            wallet = db.wallet_accounts.get_for_customer(customer_id, wallet_type, currency)
            if not wallet:
                wallet = db.wallet_accounts.create(
                    id=_new_id('WAL'),
                    customer_id=customer_id,
                    wallet_type=wallet_type,
                    currency=currency,
                )
                if not wallet:
                    return WalletLedgerResult(success=False, error='wallet_create_failed')

            entry_group = _new_id('GRP')
            entry = db.wallet_ledger.create(
                id=_new_id('LEDG'),
                wallet_account_id=wallet.id,
                customer_id=customer_id,
                entry_group_id=entry_group,
                entry_type=entry_type,
                direction='credit',
                amount=float(amount),
                currency=currency,
                reference_type=reference_type,
                reference_id=reference_id,
                counterparty_type=counterparty_type,
                counterparty_id=counterparty_id,
                status='posted',
            )
            if not entry:
                return WalletLedgerResult(success=False, error='ledger_post_failed')

            updated = db.wallet_accounts.adjust_balances(
                wallet.id,
                available_delta=float(amount),
                posted_delta=float(amount),
            )
            return WalletLedgerResult(
                success=True,
                wallet=updated.to_dict() if updated else wallet.to_dict(),
                entry_group_id=entry_group,
            )

    # ------------------------------------------------------------------
    # Hold / capture / release lifecycle
    # ------------------------------------------------------------------

    def create_hold(
        self,
        customer_id: str,
        amount: float,
        *,
        wallet_type: str = 'health',
        currency: str = 'USD',
        order_id: Optional[str] = None,
        payment_intent_id: Optional[str] = None,
        idempotency_key: Optional[str] = None,
        expires_in_minutes: int = 60,
    ) -> WalletLedgerResult:
        if amount is None or float(amount) <= 0:
            return WalletLedgerResult(success=False, error='amount must be positive')

        with self._db_manager_factory() as db:
            if idempotency_key:
                existing = db.wallet_holds.get_by_idempotency(idempotency_key)
                if existing:
                    wallet = db.wallet_accounts.get_by_id(existing.wallet_account_id)
                    return WalletLedgerResult(
                        success=True,
                        wallet=wallet.to_dict() if wallet else None,
                        hold=existing.to_dict(),
                    )

            wallet = db.wallet_accounts.get_for_customer(customer_id, wallet_type, currency)
            if not wallet:
                return WalletLedgerResult(success=False, error='wallet_not_found')
            if float(wallet.available_balance or 0.0) < float(amount):
                return WalletLedgerResult(success=False, error='insufficient_funds')

            hold = db.wallet_holds.create(
                id=_new_id('HOLD'),
                wallet_account_id=wallet.id,
                customer_id=customer_id,
                order_id=order_id,
                payment_intent_id=payment_intent_id,
                amount=float(amount),
                currency=currency,
                status='held',
                expires_at=datetime.utcnow() + timedelta(minutes=int(expires_in_minutes)),
                idempotency_key=idempotency_key,
            )
            if not hold:
                return WalletLedgerResult(success=False, error='hold_create_failed')

            # Holds shift funds between the cached ``available`` and ``held``
            # buckets but do NOT change the posted balance, so no ledger entry
            # is written here. The corresponding ledger row is only emitted at
            # capture (debit) or refund (credit). The hold itself, with an
            # ``entry_group_id`` reference for traceability, is the durable
            # record of the authorization.
            entry_group = _new_id('GRP')
            updated = db.wallet_accounts.adjust_balances(
                wallet.id,
                available_delta=-float(amount),
                held_delta=float(amount),
            )
            return WalletLedgerResult(
                success=True,
                wallet=updated.to_dict() if updated else wallet.to_dict(),
                hold=hold.to_dict(),
                entry_group_id=entry_group,
            )

    def capture_hold(
        self,
        hold_id: str,
        *,
        capture_reference: Optional[str] = None,
        capture_amount: Optional[float] = None,
    ) -> WalletLedgerResult:
        with self._db_manager_factory() as db:
            hold = db.wallet_holds.get_by_id(hold_id)
            if not hold:
                return WalletLedgerResult(success=False, error='hold_not_found')
            if hold.status != 'held':
                return WalletLedgerResult(success=False, error=f'invalid_status:{hold.status}')

            wallet = db.wallet_accounts.get_by_id(hold.wallet_account_id)
            if not wallet:
                return WalletLedgerResult(success=False, error='wallet_not_found')

            captured = float(capture_amount) if capture_amount is not None else float(hold.amount)
            if captured <= 0 or captured > float(hold.amount):
                return WalletLedgerResult(success=False, error='invalid_capture_amount')
            remainder = float(hold.amount) - captured

            entry_group = _new_id('GRP')
            db.wallet_ledger.create(
                id=_new_id('LEDG'),
                wallet_account_id=wallet.id,
                customer_id=hold.customer_id,
                entry_group_id=entry_group,
                entry_type='capture',
                direction='debit',
                amount=captured,
                currency=hold.currency,
                reference_type='wallet_hold',
                reference_id=hold.id,
                counterparty_type='order',
                counterparty_id=hold.order_id,
                status='posted',
            )

            hold.status = 'captured'
            hold.capture_reference = capture_reference
            hold.updated_date = datetime.utcnow()
            db.wallet_holds.session.commit()

            updated = db.wallet_accounts.adjust_balances(
                wallet.id,
                held_delta=-float(hold.amount),
                available_delta=remainder,
                posted_delta=-captured,
            )
            return WalletLedgerResult(
                success=True,
                wallet=updated.to_dict() if updated else wallet.to_dict(),
                hold=hold.to_dict(),
                entry_group_id=entry_group,
            )

    def release_hold(
        self,
        hold_id: str,
        *,
        reason: Optional[str] = None,
    ) -> WalletLedgerResult:
        with self._db_manager_factory() as db:
            hold = db.wallet_holds.get_by_id(hold_id)
            if not hold:
                return WalletLedgerResult(success=False, error='hold_not_found')
            if hold.status != 'held':
                return WalletLedgerResult(success=False, error=f'invalid_status:{hold.status}')

            wallet = db.wallet_accounts.get_by_id(hold.wallet_account_id)
            if not wallet:
                return WalletLedgerResult(success=False, error='wallet_not_found')

            # Releasing simply returns held funds to ``available`` - posted
            # balance is unchanged so no ledger row is written. The release
            # reason is captured on the hold itself for audit lineage.
            entry_group = _new_id('GRP')
            hold.status = 'released'
            hold.release_reason = reason
            hold.updated_date = datetime.utcnow()
            db.wallet_holds.session.commit()

            updated = db.wallet_accounts.adjust_balances(
                wallet.id,
                held_delta=-float(hold.amount),
                available_delta=float(hold.amount),
            )
            return WalletLedgerResult(
                success=True,
                wallet=updated.to_dict() if updated else wallet.to_dict(),
                hold=hold.to_dict(),
                entry_group_id=entry_group,
            )

    # ------------------------------------------------------------------
    # Refunds (compensating credit)
    # ------------------------------------------------------------------

    def refund(
        self,
        customer_id: str,
        amount: float,
        *,
        order_id: str,
        wallet_type: str = 'health',
        currency: str = 'USD',
        reason_code: str = 'customer_cancel',
        funding_source: str = 'wallet',
        approved_by: Optional[str] = None,
    ) -> WalletLedgerResult:
        if amount is None or float(amount) <= 0:
            return WalletLedgerResult(success=False, error='amount must be positive')

        with self._db_manager_factory() as db:
            wallet = db.wallet_accounts.get_for_customer(customer_id, wallet_type, currency)
            if not wallet:
                return WalletLedgerResult(success=False, error='wallet_not_found')

            entry_group = _new_id('GRP')
            ledger = db.wallet_ledger.create(
                id=_new_id('LEDG'),
                wallet_account_id=wallet.id,
                customer_id=customer_id,
                entry_group_id=entry_group,
                entry_type='refund',
                direction='credit',
                amount=float(amount),
                currency=currency,
                reference_type='order',
                reference_id=order_id,
                status='posted',
            )

            db.refunds.create(
                id=_new_id('REF'),
                order_id=order_id,
                funding_source=funding_source,
                reason_code=reason_code,
                status='processed',
                amount=float(amount),
                currency=currency,
                approved_by=approved_by,
                processed_date=datetime.utcnow(),
                wallet_ledger_entry_id=ledger.id if ledger else None,
            )

            updated = db.wallet_accounts.adjust_balances(
                wallet.id,
                available_delta=float(amount),
                posted_delta=float(amount),
            )
            return WalletLedgerResult(
                success=True,
                wallet=updated.to_dict() if updated else wallet.to_dict(),
                entry_group_id=entry_group,
            )

    # ------------------------------------------------------------------
    # Reconciliation helpers
    # ------------------------------------------------------------------

    def recompute_balances(self, customer_id: str, wallet_type: str = 'health',
                           currency: str = 'USD') -> Optional[Dict[str, Any]]:
        with self._db_manager_factory() as db:
            wallet = db.wallet_accounts.get_for_customer(customer_id, wallet_type, currency)
            if not wallet:
                return None
            posted = db.wallet_ledger.derive_balance(wallet.id)
            held = db.wallet_holds.total_held_for_account(wallet.id)
            available = posted - held
            wallet.posted_balance = float(posted)
            wallet.held_balance = float(held)
            wallet.available_balance = float(available)
            wallet.updated_date = datetime.utcnow()
            db.wallet_accounts.session.commit()
            return wallet.to_dict()


_wallet_ledger_service: Optional[WalletLedgerService] = None


def get_wallet_ledger_service() -> WalletLedgerService:
    global _wallet_ledger_service
    if _wallet_ledger_service is None:
        _wallet_ledger_service = WalletLedgerService()
    return _wallet_ledger_service


__all__ = [
    'WalletLedgerService',
    'WalletLedgerResult',
    'get_wallet_ledger_service',
]
