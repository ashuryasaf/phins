"""
Marketplace Accounting Service
==============================

Owns the canonical posting model for health-marketplace orders described in
``docs/health_marketplace_architecture.md`` (sections "Markup and margin
treatment" and "Wallet and marketplace posting model").

This is the single place where:

- order financials (gross, supplier cost, markup) are computed deterministically
- capture postings are written to ``journal_entries``
- refunds produce compensating contra-revenue and supplier-payable reductions
- balance-sheet projections (marketplace clearing, supplier payable,
  marketplace revenue, refund liability) are derived from journal balances

The service is purposefully *passive* with respect to wallet movement: actual
debits/credits to wallets are owned by ``services.wallet_ledger_service``.
This service only writes the ACCOUNTING view that finance dashboards and
reconciliation jobs read off.

Account codes (canonical):
- ``wallet_cash``                  customer wallet asset
- ``wallet_holds``                 contra to ``wallet_cash`` for held funds
- ``marketplace_clearing``         intermediary on capture
- ``supplier_payable``             liability owed to supplier
- ``marketplace_revenue``          recognized PHINS markup
- ``deferred_marketplace_revenue`` markup booked but not yet earned
- ``marketplace_contra_revenue``   refund/rebate impact on revenue
- ``payer_receivable``             external insurer recovery owed to PHINS
- ``refund_liability``             promised reversal back to customer
- ``supplier_reserve_holdback``    portion held against disputes
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from database.manager import DatabaseManager

logger = logging.getLogger('phins.marketplace_accounting_service')


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12].upper()}"


@dataclass
class OrderFinancials:
    """Deterministic per-order financial breakdown."""

    gross_sales_amount: float = 0.0
    supplier_cost_amount: float = 0.0
    markup_amount: float = 0.0
    markup_percent: float = 0.0
    delivery_fee_amount: float = 0.0
    holdback_amount: float = 0.0
    net_supplier_payout: float = 0.0
    currency: str = 'USD'

    def to_dict(self) -> Dict[str, Any]:
        return {
            'gross_sales_amount': round(self.gross_sales_amount, 4),
            'supplier_cost_amount': round(self.supplier_cost_amount, 4),
            'markup_amount': round(self.markup_amount, 4),
            'markup_percent': round(self.markup_percent, 4),
            'delivery_fee_amount': round(self.delivery_fee_amount, 4),
            'holdback_amount': round(self.holdback_amount, 4),
            'net_supplier_payout': round(self.net_supplier_payout, 4),
            'currency': self.currency,
        }


@dataclass
class JournalPostingResult:
    success: bool
    entry_group_id: Optional[str] = None
    journal_entries: List[Dict[str, Any]] = field(default_factory=list)
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            'success': self.success,
            'entry_group_id': self.entry_group_id,
            'journal_entries': self.journal_entries,
            'error': self.error,
        }


class MarketplaceAccountingService:
    """Computes markup and writes canonical journal entries for marketplace flows."""

    def __init__(self, db_manager_factory=DatabaseManager):
        self._db_manager_factory = db_manager_factory

    # ------------------------------------------------------------------
    # Pure computation
    # ------------------------------------------------------------------

    def calculate_order_financials(
        self,
        gross_sales_amount: float,
        supplier_cost_amount: float,
        *,
        delivery_fee_amount: float = 0.0,
        holdback_rate: float = 0.0,
        currency: str = 'USD',
    ) -> OrderFinancials:
        gross = max(0.0, float(gross_sales_amount or 0.0))
        cost = max(0.0, float(supplier_cost_amount or 0.0))
        markup = gross - cost
        markup_percent = (markup / cost * 100.0) if cost > 0 else 0.0
        holdback = max(0.0, cost * float(holdback_rate or 0.0))
        delivery = max(0.0, float(delivery_fee_amount or 0.0))
        net_payout = max(0.0, cost - holdback - delivery)
        return OrderFinancials(
            gross_sales_amount=gross,
            supplier_cost_amount=cost,
            markup_amount=markup,
            markup_percent=markup_percent,
            delivery_fee_amount=delivery,
            holdback_amount=holdback,
            net_supplier_payout=net_payout,
            currency=currency,
        )

    # ------------------------------------------------------------------
    # Posting helpers
    # ------------------------------------------------------------------

    def _post_pair(
        self,
        db: DatabaseManager,
        entry_group_id: str,
        debit_account: str,
        credit_account: str,
        amount: float,
        *,
        currency: str,
        reference_type: str,
        reference_id: str,
        description: Optional[str] = None,
    ) -> Optional[List[Dict[str, Any]]]:
        if amount is None or float(amount) == 0:
            return []
        amount = float(amount)
        debit = db.journal.create(
            id=_new_id('JE'),
            entry_group_id=entry_group_id,
            account_code=debit_account,
            direction='debit',
            amount=amount,
            currency=currency,
            reference_type=reference_type,
            reference_id=reference_id,
            description=description,
        )
        credit = db.journal.create(
            id=_new_id('JE'),
            entry_group_id=entry_group_id,
            account_code=credit_account,
            direction='credit',
            amount=amount,
            currency=currency,
            reference_type=reference_type,
            reference_id=reference_id,
            description=description,
        )
        if not debit or not credit:
            logger.error(
                "Partial journal pair for group %s: debit=%s credit=%s",
                entry_group_id, 'OK' if debit else 'FAIL', 'OK' if credit else 'FAIL',
            )
            return None
        return [debit.to_dict(), credit.to_dict()]

    # ------------------------------------------------------------------
    # Capture posting (order paid + supplier owed + markup recognized)
    # ------------------------------------------------------------------

    def post_capture_entries(
        self,
        order_id: str,
        financials: OrderFinancials,
        *,
        funding_source: str = 'wallet',
        defer_revenue: bool = False,
    ) -> JournalPostingResult:
        if not order_id:
            return JournalPostingResult(success=False, error='order_id required')

        entry_group = _new_id('JG')
        rows: List[Dict[str, Any]] = []

        with self._db_manager_factory() as db:
            # 1. Customer-side cash flow (wallet or external)
            customer_account = 'wallet_cash' if funding_source == 'wallet' else 'psp_clearing'
            pair = self._post_pair(
                db,
                entry_group,
                debit_account=customer_account,
                credit_account='marketplace_clearing',
                amount=financials.gross_sales_amount,
                currency=financials.currency,
                reference_type='order',
                reference_id=order_id,
                description='Capture: customer funds clear into marketplace',
            )
            if pair is None:
                return JournalPostingResult(success=False, error='journal_post_failed')
            rows.extend(pair)

            # 2. Supplier payable arises from the supplier cost
            pair = self._post_pair(
                db,
                entry_group,
                debit_account='marketplace_clearing',
                credit_account='supplier_payable',
                amount=financials.supplier_cost_amount,
                currency=financials.currency,
                reference_type='order',
                reference_id=order_id,
                description='Capture: supplier payable recognized',
            )
            if pair is None:
                return JournalPostingResult(success=False, error='journal_post_failed')
            rows.extend(pair)

            # 3. Markup recognized as revenue (or deferred)
            revenue_account = 'deferred_marketplace_revenue' if defer_revenue else 'marketplace_revenue'
            pair = self._post_pair(
                db,
                entry_group,
                debit_account='marketplace_clearing',
                credit_account=revenue_account,
                amount=financials.markup_amount,
                currency=financials.currency,
                reference_type='order',
                reference_id=order_id,
                description='Capture: markup recognized',
            )
            if pair is None:
                return JournalPostingResult(success=False, error='journal_post_failed')
            rows.extend(pair)

            # 4. Optional reserve holdback against supplier payable
            if financials.holdback_amount and financials.holdback_amount > 0:
                pair = self._post_pair(
                    db,
                    entry_group,
                    debit_account='supplier_payable',
                    credit_account='supplier_reserve_holdback',
                    amount=financials.holdback_amount,
                    currency=financials.currency,
                    reference_type='order',
                    reference_id=order_id,
                    description='Capture: supplier reserve holdback',
                )
                if pair is None:
                    return JournalPostingResult(success=False, error='journal_post_failed')
                rows.extend(pair)

        return JournalPostingResult(success=True, entry_group_id=entry_group, journal_entries=rows)

    # ------------------------------------------------------------------
    # Refund posting (compensating reversal)
    # ------------------------------------------------------------------

    def post_refund_entries(
        self,
        order_id: str,
        amount: float,
        *,
        currency: str = 'USD',
        funding_source: str = 'wallet',
        markup_share: float = 0.0,
        supplier_share: Optional[float] = None,
    ) -> JournalPostingResult:
        amount = float(amount or 0.0)
        if amount <= 0:
            return JournalPostingResult(success=False, error='amount must be positive')

        markup_share = float(markup_share or 0.0)
        supplier_share = float(amount - markup_share) if supplier_share is None else float(supplier_share)

        if markup_share < 0 or supplier_share < 0 or (markup_share + supplier_share) > amount + 1e-6:
            return JournalPostingResult(success=False, error='invalid_refund_breakdown')

        entry_group = _new_id('JG')
        rows: List[Dict[str, Any]] = []

        with self._db_manager_factory() as db:
            customer_account = 'wallet_cash' if funding_source == 'wallet' else 'psp_clearing'

            # 1. Refund liability returned to customer
            pair = self._post_pair(
                db,
                entry_group,
                debit_account='refund_liability',
                credit_account=customer_account,
                amount=amount,
                currency=currency,
                reference_type='order',
                reference_id=order_id,
                description='Refund: customer reimbursement',
            )
            if pair is None:
                return JournalPostingResult(success=False, error='journal_post_failed')
            rows.extend(pair)

            # 2. Reverse supplier payable for supplier portion
            if supplier_share > 0:
                pair = self._post_pair(
                    db,
                    entry_group,
                    debit_account='supplier_payable',
                    credit_account='refund_liability',
                    amount=supplier_share,
                    currency=currency,
                    reference_type='order',
                    reference_id=order_id,
                    description='Refund: supplier payable reduction',
                )
                if pair is None:
                    return JournalPostingResult(success=False, error='journal_post_failed')
                rows.extend(pair)

            # 3. Reverse markup recognition through contra-revenue
            if markup_share > 0:
                pair = self._post_pair(
                    db,
                    entry_group,
                    debit_account='marketplace_contra_revenue',
                    credit_account='refund_liability',
                    amount=markup_share,
                    currency=currency,
                    reference_type='order',
                    reference_id=order_id,
                    description='Refund: markup contra-revenue',
                )
                if pair is None:
                    return JournalPostingResult(success=False, error='journal_post_failed')
                rows.extend(pair)

        return JournalPostingResult(success=True, entry_group_id=entry_group, journal_entries=rows)

    # ------------------------------------------------------------------
    # Balance-sheet style summaries
    # ------------------------------------------------------------------

    def get_marketplace_finance_summary(self) -> Dict[str, Any]:
        with self._db_manager_factory() as db:
            accounts = [
                'wallet_cash',
                'marketplace_clearing',
                'supplier_payable',
                'marketplace_revenue',
                'deferred_marketplace_revenue',
                'marketplace_contra_revenue',
                'payer_receivable',
                'refund_liability',
                'supplier_reserve_holdback',
            ]
            summary: Dict[str, Any] = {
                'as_of': datetime.utcnow().isoformat(),
                'accounts': {acc: db.journal.account_balance(acc) for acc in accounts},
            }
            revenue = summary['accounts']['marketplace_revenue']['balance']
            contra = summary['accounts']['marketplace_contra_revenue']['balance']
            summary['kpis'] = {
                'gross_marketplace_revenue': round(revenue, 4),
                'contra_revenue': round(contra, 4),
                'net_marketplace_revenue': round(revenue + contra, 4),
                'open_supplier_payable': round(summary['accounts']['supplier_payable']['balance'], 4),
                'open_payer_receivable': round(summary['accounts']['payer_receivable']['balance'], 4),
                'refund_liability': round(summary['accounts']['refund_liability']['balance'], 4),
            }
            return summary


_marketplace_accounting_service: Optional[MarketplaceAccountingService] = None


def get_marketplace_accounting_service() -> MarketplaceAccountingService:
    global _marketplace_accounting_service
    if _marketplace_accounting_service is None:
        _marketplace_accounting_service = MarketplaceAccountingService()
    return _marketplace_accounting_service


__all__ = [
    'MarketplaceAccountingService',
    'OrderFinancials',
    'JournalPostingResult',
    'get_marketplace_accounting_service',
]
