"""
Marketplace Event Service
=========================

Implements the canonical marketplace event vocabulary described in
``docs/health_marketplace_architecture.md`` (section "BI and AI architecture
> Event model").

Every strategic marketplace action emits a versioned event into the durable
``marketplace_outbox_events`` table so that BI, AI, reconciliation, and
external warehouse consumers can read off the same backbone.

Why this is a separate service:
- Producers (wallet, accounting, settlement, payer-recovery services) must
  not couple directly to a downstream broker or warehouse. They only call
  ``publish_*`` here, and the outbox row is committed transactionally with
  the rest of the operation.
- Consumers can then poll ``OutboxRepository.get_pending`` and stream events
  to whatever transport is appropriate (Kafka, Pub/Sub, S3, etc.) without
  blocking the OLTP write path.

Event names follow the canonical list in the architecture doc:

    eligibility.checked, quote.generated, quote.accepted,
    wallet.hold_created, wallet.hold_captured, wallet.hold_released,
    order.created, order.confirmed, order.fulfilled,
    settlement.calculated, settlement.paid,
    claim.submitted, claim.adjudicated,
    remittance.received,
    refund.created, refund.completed,
    integrity.violation_detected
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from database.manager import DatabaseManager

logger = logging.getLogger('phins.marketplace_event_service')


CANONICAL_EVENT_TYPES = frozenset({
    'eligibility.checked',
    'quote.generated',
    'quote.accepted',
    'wallet.hold_created',
    'wallet.hold_captured',
    'wallet.hold_released',
    'wallet.refund_posted',
    'order.created',
    'order.confirmed',
    'order.fulfilled',
    'order.cancelled',
    'settlement.calculated',
    'settlement.paid',
    'claim.submitted',
    'claim.adjudicated',
    'remittance.received',
    'refund.created',
    'refund.completed',
    'integrity.violation_detected',
})


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12].upper()}"


class MarketplaceEventService:
    """Outbox-backed publisher for canonical marketplace events."""

    def __init__(self, db_manager_factory=DatabaseManager):
        self._db_manager_factory = db_manager_factory

    def publish(
        self,
        event_type: str,
        *,
        aggregate_type: str,
        aggregate_id: str,
        payload: Optional[Dict[str, Any]] = None,
        event_version: str = '1',
    ) -> Optional[Dict[str, Any]]:
        if event_type not in CANONICAL_EVENT_TYPES:
            logger.warning(f"Non-canonical event type emitted: {event_type}")
        if not aggregate_id or not aggregate_type:
            return None
        payload = payload or {}
        payload.setdefault('emitted_at', datetime.utcnow().isoformat())
        with self._db_manager_factory() as db:
            event = db.outbox.create(
                id=_new_id('EVT'),
                aggregate_type=aggregate_type,
                aggregate_id=aggregate_id,
                event_type=event_type,
                event_version=event_version,
                payload_json=json.dumps(payload, default=str),
                status='pending',
            )
            return event.to_dict() if event else None

    # Convenience helpers used by other services.

    def publish_order_created(self, order_id: str, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        return self.publish('order.created', aggregate_type='order',
                            aggregate_id=order_id, payload=payload)

    def publish_capture_posted(
        self, order_id: str, financials: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        return self.publish('order.confirmed', aggregate_type='order',
                            aggregate_id=order_id, payload={'financials': financials})

    def publish_settlement_calculated(self, run_id: str, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        return self.publish('settlement.calculated', aggregate_type='settlement_run',
                            aggregate_id=run_id, payload=payload)

    def publish_settlement_paid(self, run_id: str, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        return self.publish('settlement.paid', aggregate_type='settlement_run',
                            aggregate_id=run_id, payload=payload)

    def publish_remittance_received(self, advice_id: str, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        return self.publish('remittance.received', aggregate_type='remittance_advice',
                            aggregate_id=advice_id, payload=payload)

    def publish_integrity_violation(self, finding_id: str, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        return self.publish('integrity.violation_detected', aggregate_type='integrity_finding',
                            aggregate_id=finding_id, payload=payload)

    # Reading side.

    def list_pending(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._db_manager_factory() as db:
            return [e.to_dict() for e in db.outbox.get_pending(limit=limit)]

    def mark_published(self, event_id: str) -> bool:
        with self._db_manager_factory() as db:
            return db.outbox.mark_published(event_id)


_marketplace_event_service: Optional[MarketplaceEventService] = None


def get_marketplace_event_service() -> MarketplaceEventService:
    global _marketplace_event_service
    if _marketplace_event_service is None:
        _marketplace_event_service = MarketplaceEventService()
    return _marketplace_event_service


__all__ = [
    'MarketplaceEventService',
    'CANONICAL_EVENT_TYPES',
    'get_marketplace_event_service',
]
