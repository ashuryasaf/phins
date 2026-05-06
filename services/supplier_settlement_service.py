"""
Supplier Settlement Service
===========================

Implements the durable supplier-settlement engine described in
``docs/health_marketplace_architecture.md`` ("Supplier settlement model")
and the supplier portion of
``docs/health_marketplace_implementation_spec.md`` (Stream C).

The service:

- builds a settlement run from fulfilled orders (via repository-backed
  ``SupplierSettlementRun`` and ``SupplierSettlementItem`` rows)
- computes the canonical supplier payout formula:

      net_supplier_payout = gross_sales
                            - markup
                            - delivery_fee_share
                            - penalties
                            - reserve_holdback
                            + supplier_adjustments

- transitions runs through ``pending -> calculated -> executed`` with payout
  references, leaving the previous order data immutable
- exposes aging snapshots used by admin and finance dashboards

Important design notes:
- Settlement is the only place where supplier payable is reduced; the
  marketplace accounting service is responsible for posting the journal
  entries that reduce ``supplier_payable``.
- The service does NOT call external payment rails directly. ``execute`` is a
  state transition that records an external payout reference; the actual
  PSP/bank call lives in ``services/payment_gateway_service.py``.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from database.manager import DatabaseManager
from services.marketplace_accounting_service import (
    MarketplaceAccountingService,
    get_marketplace_accounting_service,
)

logger = logging.getLogger('phins.supplier_settlement_service')


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12].upper()}"


class SupplierSettlementService:
    """Builds, calculates, and executes supplier settlement runs."""

    def __init__(
        self,
        db_manager_factory=DatabaseManager,
        accounting_service: Optional[MarketplaceAccountingService] = None,
    ):
        self._db_manager_factory = db_manager_factory
        self._accounting = accounting_service or get_marketplace_accounting_service()

    # ------------------------------------------------------------------
    # Run construction
    # ------------------------------------------------------------------

    def build_settlement_run(
        self,
        supplier_id: str,
        *,
        order_payloads: List[Dict[str, Any]],
        settlement_period_start: Optional[datetime] = None,
        settlement_period_end: Optional[datetime] = None,
        currency: str = 'USD',
        executed_by: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a settlement run with computed item rows.

        ``order_payloads`` is a list of dicts with at least:
          ``order_id``, ``gross_sales_amount``, ``supplier_cost_amount``.
        Optional fields: ``delivery_fee_amount``, ``holdback_rate``,
        ``penalty_amount``, ``adjustment_amount``.
        """
        if not supplier_id:
            return {'success': False, 'error': 'supplier_id required'}
        if not order_payloads:
            return {'success': False, 'error': 'no_orders'}

        with self._db_manager_factory() as db:
            run = db.supplier_settlement_runs.create(
                id=_new_id('SETRUN'),
                supplier_id=supplier_id,
                run_date=datetime.utcnow(),
                settlement_period_start=settlement_period_start,
                settlement_period_end=settlement_period_end,
                status='calculated',
                currency=currency,
                executed_by=executed_by,
            )
            if not run:
                return {'success': False, 'error': 'run_create_failed'}

            gross_total = 0.0
            net_total = 0.0
            holdback_total = 0.0
            adjustment_total = 0.0
            items: List[Dict[str, Any]] = []

            for payload in order_payloads:
                order_id = payload.get('order_id')
                if not order_id:
                    continue
                financials = self._accounting.calculate_order_financials(
                    gross_sales_amount=float(payload.get('gross_sales_amount', 0.0) or 0.0),
                    supplier_cost_amount=float(payload.get('supplier_cost_amount', 0.0) or 0.0),
                    delivery_fee_amount=float(payload.get('delivery_fee_amount', 0.0) or 0.0),
                    holdback_rate=float(payload.get('holdback_rate', 0.0) or 0.0),
                    currency=currency,
                )
                penalty = max(0.0, float(payload.get('penalty_amount', 0.0) or 0.0))
                adjustment = float(payload.get('adjustment_amount', 0.0) or 0.0)
                net_payout = max(
                    0.0,
                    financials.net_supplier_payout - penalty + adjustment,
                )

                item = db.supplier_settlement_items.create(
                    id=_new_id('SETIT'),
                    settlement_run_id=run.id,
                    supplier_id=supplier_id,
                    order_id=order_id,
                    gross_sales_amount=financials.gross_sales_amount,
                    markup_amount=financials.markup_amount,
                    supplier_payout_amount=net_payout,
                    holdback_amount=financials.holdback_amount,
                    penalty_amount=penalty,
                    adjustment_amount=adjustment,
                    status='calculated',
                )
                if item:
                    items.append(item.to_dict())
                    gross_total += financials.gross_sales_amount
                    net_total += net_payout
                    holdback_total += financials.holdback_amount
                    adjustment_total += adjustment

            run.gross_amount = gross_total
            run.net_amount = net_total
            run.holdback_amount = holdback_total
            run.adjustment_amount = adjustment_total
            run.updated_date = datetime.utcnow()
            db.supplier_settlement_runs.session.commit()

            return {
                'success': True,
                'run': run.to_dict(),
                'items': items,
            }

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def execute_settlement_run(
        self,
        run_id: str,
        *,
        external_payout_reference: Optional[str] = None,
        executed_by: Optional[str] = None,
    ) -> Dict[str, Any]:
        with self._db_manager_factory() as db:
            run = db.supplier_settlement_runs.get_by_id(run_id)
            if not run:
                return {'success': False, 'error': 'run_not_found'}
            if run.status not in ('calculated', 'pending'):
                return {'success': False, 'error': f'invalid_status:{run.status}'}

            run.status = 'executed'
            run.external_payout_reference = external_payout_reference
            if executed_by:
                run.executed_by = executed_by
            run.updated_date = datetime.utcnow()

            for item in db.supplier_settlement_items.get_for_run(run.id):
                item.status = 'paid'
                item.created_date = item.created_date or datetime.utcnow()
            db.supplier_settlement_runs.session.commit()

            net_payout = float(run.net_amount or 0.0)
            if net_payout > 0:
                posting_result = self._accounting.post_settlement_payout_entries(
                    run.id,
                    run.supplier_id,
                    net_payout,
                    currency=getattr(run, 'currency', 'USD') or 'USD',
                )
                if not posting_result.success:
                    return {'success': False, 'error': 'accounting_post_failed', 'run': run.to_dict()}

            return {'success': True, 'run': run.to_dict()}

    def apply_clawback(
        self,
        run_id: str,
        *,
        amount: float,
        reason: Optional[str] = None,
    ) -> Dict[str, Any]:
        amount = float(amount or 0.0)
        if amount <= 0:
            return {'success': False, 'error': 'amount must be positive'}
        with self._db_manager_factory() as db:
            run = db.supplier_settlement_runs.get_by_id(run_id)
            if not run:
                return {'success': False, 'error': 'run_not_found'}
            run.adjustment_amount = float(run.adjustment_amount or 0.0) - amount
            run.net_amount = float(run.net_amount or 0.0) - amount
            run.updated_date = datetime.utcnow()
            db.supplier_settlement_runs.session.commit()
            return {
                'success': True,
                'run': run.to_dict(),
                'reason': reason,
            }

    # ------------------------------------------------------------------
    # Read-side helpers
    # ------------------------------------------------------------------

    def get_aging_snapshot(self) -> Dict[str, Any]:
        with self._db_manager_factory() as db:
            buckets = db.supplier_settlement_runs.aging_buckets()
            return {
                'as_of': datetime.utcnow().isoformat(),
                'buckets': buckets,
            }

    def get_runs_for_supplier(self, supplier_id: str) -> List[Dict[str, Any]]:
        with self._db_manager_factory() as db:
            return [r.to_dict() for r in db.supplier_settlement_runs.get_by_supplier(supplier_id)]


_supplier_settlement_service: Optional[SupplierSettlementService] = None


def get_supplier_settlement_service() -> SupplierSettlementService:
    global _supplier_settlement_service
    if _supplier_settlement_service is None:
        _supplier_settlement_service = SupplierSettlementService()
    return _supplier_settlement_service


__all__ = [
    'SupplierSettlementService',
    'get_supplier_settlement_service',
]
