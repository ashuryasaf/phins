"""
Customer-facing agents (B6).

Two facades over one set of shared rails:

- :mod:`.communication` — welcome packages and customer-relations outreach
  (``CustomerCommunicationAgent``);
- :mod:`.service_desk` — inquiries, templated correspondence, upsell
  suggestions (``CustomerServiceAgent``);

sharing

- :mod:`.interaction_log` — one durable customer timeline (``agent_artifacts``);
- :mod:`.consent` — per-channel consent registry + daily WhatsApp/SMS cap;
- :mod:`.escalation` — one escalation path (durable record + audit + timeline).

``services.customer_communication_agent`` and the root ``service_agent`` module
remain as import shims.
"""

from __future__ import annotations

from .consent import (  # noqa: F401
    ConsentRegistry,
    Decision,
    MessagingPolicy,
    get_consent_registry,
    reset_consent_registry,
)
from .escalation import (  # noqa: F401
    Escalation,
    EscalationDesk,
    get_escalation_desk,
    reset_escalation_desk,
)
from .interaction_log import (  # noqa: F401
    Interaction,
    InteractionLog,
    get_interaction_log,
    reset_interaction_log,
)


def reset_customer_agent_state() -> None:
    """Forget the process-wide log, consent registry and escalation desk
    (tests / DB-mode flips). Durable rows are untouched."""
    reset_interaction_log()
    reset_consent_registry()
    reset_escalation_desk()


def customer_timeline(customer_id: str) -> dict:
    """Everything the platform holds about its contact with one customer:
    interactions (both facades), consent on file, open escalations."""
    log = get_interaction_log()
    registry = get_consent_registry()
    desk = get_escalation_desk()
    consent = registry.get(customer_id)
    return {
        'customer_id': str(customer_id),
        'interactions': [i.to_dict() for i in log.for_customer(customer_id)],
        'consent': consent.to_dict() if consent else {'customer_id': str(customer_id), 'channels': {}},
        'escalations': [e.to_dict() for e in desk.for_customer(customer_id)],
        'sent_today': log.count_sent_today(customer_id),
    }


__all__ = [
    'ConsentRegistry', 'Decision', 'Escalation', 'EscalationDesk', 'Interaction', 'InteractionLog',
    'MessagingPolicy', 'customer_timeline', 'get_consent_registry', 'get_escalation_desk',
    'get_interaction_log', 'reset_consent_registry', 'reset_customer_agent_state',
    'reset_escalation_desk', 'reset_interaction_log',
]
