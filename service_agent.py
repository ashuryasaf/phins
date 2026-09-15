"""
Customer Service Agent for PHINS — compatibility shim (B6).

The agent now lives in :mod:`services.customer_agent.service_desk` and sends
through the platform notification service, logs to the shared customer
interaction log, and escalates through the shared escalation desk.

This module keeps the legacy constructor working:

- ``notification_mgr`` (an ``underwriting_assistant.NotificationManager``) —
  its templates are imported into the shared registry and every delivery is
  mirrored into ``notification_mgr.delivery_queue`` so existing callers that
  inspect the queue still see the traffic;
- ``reporter`` (a ``DivisionalReporter``) — escalation reports are appended to
  ``reporter.reports`` as before.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from services.customer_agent.service_desk import (  # noqa: F401
    Delivery,
    CustomerServiceAgent as _ServiceDesk,
    import_legacy_templates,
)


def _legacy_delivery_method(channel: str):
    try:
        from underwriting_assistant import DeliveryMethod
    except Exception:  # pragma: no cover - underwriting assistant unavailable
        return channel
    return {
        'sms': DeliveryMethod.SMS,
        'whatsapp': DeliveryMethod.SMS,
        'portal': DeliveryMethod.PORTAL,
        'in_app': DeliveryMethod.PORTAL,
    }.get(channel, DeliveryMethod.EMAIL)


def _mirror_delivery(notification_mgr: Any):
    """Sink that appends a legacy ``NotificationDelivery`` to the manager's queue."""
    def _sink(delivery: Delivery) -> None:
        queue = getattr(notification_mgr, 'delivery_queue', None)
        if queue is None:
            return
        try:
            from underwriting_assistant import NotificationDelivery
            record: Any = NotificationDelivery(
                delivery_id=delivery.delivery_id,
                customer_id=delivery.customer_id,
                delivery_method=_legacy_delivery_method(delivery.channel),
                recipient=delivery.recipient or '',
                subject=delivery.subject,
                message=delivery.message,
                delivery_date=datetime.now(),
                delivery_status=delivery.delivery_status,
                metadata={
                    'template': delivery.template,
                    'signature_required': delivery.signature_required,
                    'delivery_channel': [delivery.channel],
                    'notification_id': delivery.notification_id,
                    'interaction_id': delivery.interaction_id,
                    'error_code': delivery.error_code,
                },
            )
        except Exception:
            record = delivery.to_dict()
        queue.append(record)
    return _sink


class CustomerServiceAgent(_ServiceDesk):
    """Legacy-compatible constructor over the B6 service desk."""

    def __init__(
        self,
        agent_id: str,
        notification_mgr: Any = None,
        reporter: Any = None,
        customer_service: Any = None,
        notification_service: Any = None,
        **kw: Any,
    ):
        self.notification_mgr = notification_mgr
        self.reporter = reporter
        if notification_mgr is not None:
            import_legacy_templates(notification_mgr)
            kw.setdefault('delivery_sink', _mirror_delivery(notification_mgr))
        if reporter is not None and hasattr(reporter, 'reports'):
            kw.setdefault('escalation_sink', reporter.reports.append)
        super().__init__(agent_id, notification_service, customer_service=customer_service, **kw)


__all__ = ['CustomerServiceAgent', 'Delivery']
