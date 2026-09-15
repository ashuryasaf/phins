"""
Customer Service Agent (B6 facade)
==================================

Inquiry handling, templated correspondence, rule-based upsell suggestions and
human escalation — the responsibilities of the legacy ``service_agent`` module —
rebuilt on the platform pieces the rest of PHINS already uses:

- **Delivery** goes through :class:`services.notification_service.NotificationService`
  (email / SMS / WhatsApp / in-app) instead of the underwriting assistant's
  in-memory ``NotificationManager``; copy comes from the process-wide
  :class:`TemplateEngine` named registry, so service and relations templates
  live in one place.
- **Interactions** are written to the shared :class:`InteractionLog`
  (durable in ``agent_artifacts`` under DB mode) — the same log the
  communication facade uses — so a customer's timeline is complete. A row is
  written ``pending`` before a send and finalised afterwards.
- **Consent + daily cap**: SMS / WhatsApp acknowledgements and correspondence
  are gated by :class:`MessagingPolicy` (service copy is transactional, so
  only an explicit opt-out or the daily cap blocks it).
- **Escalation** is the shared :class:`EscalationDesk` (durable record + audit
  row + timeline entry).

``service_agent.CustomerServiceAgent`` remains as a compatibility shim; the
legacy ``notification_mgr`` / ``reporter`` arguments are honoured there by
mirroring deliveries and escalation reports into those objects.
"""

from __future__ import annotations

import dataclasses
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from services.agent_metrics import instrument_agent
from services.notification_service import (
    NotificationChannel,
    NotificationPriority,
    NotificationRequest,
    TemplateEngine,
    get_notification_service,
)

from .consent import TRANSACTIONAL, MessagingPolicy
from .escalation import Escalation, EscalationDesk, get_escalation_desk
from .interaction_log import (
    MESSAGING_CHANNELS,
    Interaction,
    InteractionLog,
    get_interaction_log,
    mask_recipient,
)

AGENT_NAME = 'service_desk'

# Template channel -> notification channel. ``portal`` is an in-app note.
_CHANNELS = {
    'email': NotificationChannel.EMAIL,
    'sms': NotificationChannel.SMS,
    'whatsapp': NotificationChannel.WHATSAPP,
    'portal': NotificationChannel.IN_APP,
    'in_app': NotificationChannel.IN_APP,
}

# Service-desk copy, registered once in the shared TemplateEngine registry.
SERVICE_TEMPLATES: Dict[str, Dict[str, Any]] = {
    'service_ack': {
        'subject': 'We received your inquiry',
        'body': (
            'Dear {{customer_name}},\n\n{{message}}\n\n'
            'A PHINS service specialist will follow up shortly.\n\n'
            'PHINS Customer Service'
        ),
        'channel': 'email',
        'description': 'Acknowledgement sent when a customer inquiry is logged.',
    },
    'service_followup': {
        'subject': 'Follow-up on your PHINS request',
        'body': (
            'Dear {{customer_name}},\n\n{{message}}\n\n'
            'Reply to this message or visit your portal if anything is unclear.\n\n'
            'PHINS Customer Service'
        ),
        'channel': 'email',
        'description': 'Follow-up correspondence from the service desk.',
    },
    'upsell_offer': {
        'subject': 'An option selected for you, {{customer_name}}',
        'body': (
            'Dear {{customer_name}},\n\n'
            'Based on your PHINS relationship we think {{offer}} may suit you: {{reason}}\n\n'
            'Your advisor can walk you through it whenever convenient.\n\n'
            'PHINS Customer Service'
        ),
        'channel': 'email',
        'description': 'Rule-based upsell suggestion delivered to the customer.',
    },
    'premium_allocation': {
        'subject': 'Premium Payment Allocation Confirmation',
        'body': (
            'Dear {{customer_name}},\n\n'
            'Thank you for your premium payment for Policy {{policy_id}}. '
            'The payment has been allocated as follows:\n'
            '- Total Premium: {{total_premium}}\n'
            '- Risk Coverage: {{risk_amount}}\n'
            '- Savings Account: {{savings_amount}}\n\n'
            'You can view your full statement here: {{statement_url}}\n\n'
            'Regards,\nPHINS Insurance'
        ),
        'channel': 'email',
        'description': 'Premium allocation statement after a payment posts.',
    },
}

_TEMPLATES_REGISTERED = False
_TEMPLATES_LOCK = threading.Lock()


def ensure_service_templates() -> List[str]:
    """Register the service-desk templates (idempotent). Returns the ids."""
    global _TEMPLATES_REGISTERED
    with _TEMPLATES_LOCK:
        for template_id, spec in SERVICE_TEMPLATES.items():
            TemplateEngine.register_template(template_id, **spec)
        _TEMPLATES_REGISTERED = True
    return sorted(SERVICE_TEMPLATES)


def import_legacy_templates(notification_mgr: Any) -> List[str]:
    """Copy ``underwriting_assistant.NotificationManager`` templates into the
    shared registry (ids not already registered). Lets callers that still
    build a ``NotificationManager`` keep their custom templates addressable."""
    imported: List[str] = []
    templates = getattr(notification_mgr, 'templates', None)
    if not isinstance(templates, dict):
        return imported
    for template_id, tpl in templates.items():
        if tpl is None or TemplateEngine.get_template(template_id) is not None:
            continue
        method = str(getattr(getattr(tpl, 'delivery_method', None), 'name', '') or '').lower()
        channel = {'sms': 'sms', 'portal': 'portal'}.get(method, 'email')
        try:
            TemplateEngine.register_template(
                template_id,
                subject=str(getattr(tpl, 'subject', '') or ''),
                body=str(getattr(tpl, 'body', '') or ''),
                channel=channel,
                signature_required=bool(getattr(tpl, 'signature_required', False)),
                description=str(getattr(tpl, 'template_name', '') or ''),
            )
            imported.append(str(template_id))
        except ValueError:
            continue
    return imported


@dataclass
class Delivery:
    """Outcome of one service-desk send (legacy ``NotificationDelivery`` shape
    plus the notification-service and interaction-log identifiers)."""

    delivery_id: str
    customer_id: str
    channel: str
    recipient: Optional[str]          # masked
    subject: str
    message: str
    template: str
    success: bool
    delivery_status: str              # Sent | Failed | Refused
    notification_id: Optional[str] = None
    interaction_id: Optional[str] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    signature_required: bool = False
    delivery_date: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)


@dataclass
class ResolvedCustomer:
    customer_id: str
    name: str
    email: Optional[str]
    phone: Optional[str]
    record: Optional[Dict[str, Any]]
    raw: Any


class CustomerServiceAgent:
    """Client service, correspondence and upsell on the shared B6 rails."""

    def __init__(
        self,
        agent_id: str,
        notification_service=None,
        *,
        customer_service=None,
        customer_lookup: Optional[Callable[[str], Any]] = None,
        interaction_log: Optional[InteractionLog] = None,
        messaging_policy: Optional[MessagingPolicy] = None,
        escalation_desk: Optional[EscalationDesk] = None,
        delivery_sink: Optional[Callable[[Delivery], None]] = None,
        escalation_sink: Optional[Callable[[Dict[str, Any]], None]] = None,
    ):
        self.agent_id = str(agent_id)
        self._notification_service = notification_service
        if customer_service is None and customer_lookup is None:
            try:
                from customer_validation import CustomerValidationService
                customer_service = CustomerValidationService()
            except Exception:  # repo-root module unavailable: dict lookups only
                customer_service = None
        self.customer_service = customer_service
        self._lookup = customer_lookup
        self._log = interaction_log
        self._policy = messaging_policy
        self._desk = escalation_desk
        self._delivery_sink = delivery_sink
        self._escalation_sink = escalation_sink
        self._interaction_ids: List[str] = []
        ensure_service_templates()

    # ------------------------------------------------------------------
    # Shared infrastructure
    # ------------------------------------------------------------------

    @property
    def notification_service(self):
        if self._notification_service is None:
            self._notification_service = get_notification_service()
        return self._notification_service

    @property
    def interaction_log(self) -> InteractionLog:
        if self._log is None:
            self._log = get_interaction_log()
        return self._log

    @property
    def messaging_policy(self) -> MessagingPolicy:
        if self._policy is None:
            self._policy = MessagingPolicy(interaction_log=self.interaction_log)
        return self._policy

    @property
    def escalation_desk(self) -> EscalationDesk:
        if self._desk is None:
            self._desk = get_escalation_desk()
        return self._desk

    @property
    def interactions(self) -> List[Dict[str, Any]]:
        """Legacy view: the rows this agent instance wrote, oldest first."""
        rows = []
        for interaction_id in list(self._interaction_ids):
            row = self.interaction_log.get(interaction_id)
            if row is not None:
                rows.append(self._legacy_view(row))
        return rows

    @staticmethod
    def _legacy_view(row: Interaction) -> Dict[str, Any]:
        return {
            'interaction_id': row.interaction_id,
            'timestamp': row.created_at,
            'customer_id': row.customer_id,
            'channel': row.metadata.get('inbound_channel', row.channel),
            'message': row.metadata.get('message', row.detail),
            'handled_by': row.handled_by,
            'kind': row.kind,
            'status': row.status,
        }

    def interactions_for(self, customer_id: str, **kw) -> List[Interaction]:
        """This customer's full timeline from the shared log (both facades)."""
        return self.interaction_log.for_customer(customer_id, **kw)

    # ------------------------------------------------------------------
    # Customer resolution (dict records and legacy Customer objects)
    # ------------------------------------------------------------------

    def resolve_customer(self, customer_id: str) -> ResolvedCustomer:
        raw = None
        if self._lookup is not None:
            raw = self._lookup(customer_id)
        elif self.customer_service is not None:
            raw = self.customer_service.get_customer_by_id(customer_id)
        if raw is None:
            raise ValueError(f"Customer {customer_id} not found")
        if isinstance(raw, dict):
            name = str(raw.get('name') or raw.get('full_name') or raw.get('customer_name') or 'Customer').strip()
            email = raw.get('email')
            phone = raw.get('phone') or raw.get('mobile') or raw.get('whatsapp')
            record: Optional[Dict[str, Any]] = raw
        else:
            name = str(getattr(raw, 'full_name', None) or getattr(raw, 'name', None) or 'Customer').strip()
            email = getattr(raw, 'email', None)
            phone = getattr(raw, 'phone', None)
            record = None
            for attr in ('consents', 'communication_preferences', 'marketing_consent', 'whatsapp_consent', 'sms_consent'):
                value = getattr(raw, attr, None)
                if value is not None:
                    record = record or {}
                    record[attr] = value
        return ResolvedCustomer(
            customer_id=str(customer_id), name=name or 'Customer',
            email=str(email).strip() if email else None,
            phone=str(phone).strip() if phone else None,
            record=record, raw=raw,
        )

    # ------------------------------------------------------------------
    # Public operations
    # ------------------------------------------------------------------

    @instrument_agent('customer_service',
                      decision_fn=lambda r: 'acknowledged' if r.get('acknowledgement', {}).get('success') else 'logged')
    def handle_inquiry(self, customer_id: str, channel: str, message: str,
                       actor: Optional[str] = None) -> Dict[str, Any]:
        """Log an inquiry and send the acknowledgement on the best channel.

        The inquiry and its acknowledgement are one customer touch: a single
        interaction row (kind ``inquiry``) whose status reflects the
        acknowledgement (``sent`` / ``failed`` / ``refused``).
        """
        customer = self.resolve_customer(customer_id)
        inbound = str(channel or '').strip().lower()
        text = str(message or '')
        ack_channel = inbound if inbound in MESSAGING_CHANNELS and customer.phone else 'email'
        if ack_channel == 'email' and not customer.email:
            ack_channel = 'portal'

        # ``received`` (not ``pending``) so the inquiry itself does not count
        # toward the daily cap before the acknowledgement is authorised.
        row = self.interaction_log.record(
            customer_id=customer.customer_id, agent=AGENT_NAME, kind='inquiry',
            channel=ack_channel, status='received', template='service_ack', purpose=TRANSACTIONAL,
            recipient=self._recipient_for(customer, ack_channel), actor=actor,
            handled_by=self.agent_id,
            detail=self._clip(text, 300),
            metadata={'inbound_channel': inbound, 'message': self._clip(text, 2000)},
        )
        self._interaction_ids.append(row.interaction_id)

        delivery = self._deliver(
            customer, 'service_ack',
            {'customer_name': customer.name, 'message': 'We received your inquiry.'},
            kind='inquiry', row=row, channel_override=ack_channel,
        )
        return {
            'interaction': self._legacy_view(self.interaction_log.get(row.interaction_id) or row),
            'acknowledgement': delivery,
        }

    @instrument_agent('customer_service',
                      decision_fn=lambda r: 'sent' if getattr(r, 'success', False) else 'failed')
    def send_correspondence(self, customer_id: str, template_name: str, context: Dict[str, Any],
                            actor: Optional[str] = None, channel: Optional[str] = None) -> Delivery:
        """Send templated correspondence from the shared registry."""
        customer = self.resolve_customer(customer_id)
        template_id = str(template_name or '').strip()
        if TemplateEngine.get_template(template_id) is None:
            raise ValueError(f"Template {template_name} not found")
        return self._deliver(customer, template_id, dict(context or {}), kind='correspondence',
                             actor=actor, channel_override=channel)

    def suggest_upsell(self, customer: Any) -> List[Dict[str, Any]]:
        """Rule-based upsell suggestions from the customer profile.

        Deterministic starter rules; deliberately not an ML model.
        """
        suggestions: List[Dict[str, Any]] = []

        health = getattr(customer, 'health_assessment', None)
        risk = health.health_risk_score() if health is not None and hasattr(health, 'health_risk_score') else 1.0
        age = getattr(customer, 'age', 999)
        if risk < 0.25 and age < 45:
            suggestions.append({
                'offer': 'Premium Saver Plus',
                'reason': 'Low health risk and younger age — attractive for investment products',
                'estimated_uplift_pct': 6.0,
            })

        households = getattr(self.customer_service, 'households', None) or {}
        customer_id = getattr(customer, 'customer_id', None)
        household = households.get(f"HH_{customer_id}") if customer_id else None
        members = getattr(household, 'family_members', None) or []
        if household is not None and len(members) > 0:
            suggestions.append({
                'offer': 'Family Coverage Bundle',
                'reason': f"Household with {len(members)} members — bundle discount",
                'estimated_uplift_pct': 12.0,
            })

        identification = getattr(customer, 'identification', None)
        id_valid = bool(identification.is_valid()) if identification is not None and hasattr(identification, 'is_valid') else False
        if id_valid and getattr(customer, 'email', None):
            suggestions.append({
                'offer': 'Investment Booster',
                'reason': 'Verified identity and active contact — good candidate for investment add-ons',
                'estimated_uplift_pct': 4.0,
            })

        seen = set()
        deduped: List[Dict[str, Any]] = []
        for s in suggestions:
            if s['offer'] in seen:
                continue
            seen.add(s['offer'])
            deduped.append(s)
        return deduped

    def log_interaction(self, interaction: Dict[str, Any]) -> Interaction:
        """Append a free-form note to the shared log (legacy entry point)."""
        data = dict(interaction or {})
        row = self.interaction_log.record(
            customer_id=str(data.get('customer_id') or ''), agent=AGENT_NAME, kind='note',
            channel=str(data.get('channel') or ''), status='logged',
            handled_by=str(data.get('handled_by') or self.agent_id),
            detail=self._clip(str(data.get('message') or ''), 300),
            metadata={'message': self._clip(str(data.get('message') or ''), 2000),
                      **{k: v for k, v in data.items() if k not in ('customer_id', 'channel', 'message', 'handled_by')}},
        )
        self._interaction_ids.append(row.interaction_id)
        return row

    @instrument_agent('customer_service', decision_fn=lambda r: 'escalated')
    def escalate_to_human(self, customer_id: str, reason: str, assigned_team: str = 'Service Team',
                          actor: Optional[str] = None,
                          context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Escalate through the shared desk; returns the legacy report dict."""
        try:
            customer_name: Optional[str] = self.resolve_customer(customer_id).name
        except ValueError:
            customer_name = None
        escalation: Escalation = self.escalation_desk.escalate(
            customer_id=customer_id, reason=reason, source_agent=AGENT_NAME,
            assigned_team=assigned_team, actor=actor or self.agent_id,
            customer_name=customer_name, context=context,
        )
        if escalation.interaction_id:
            self._interaction_ids.append(escalation.interaction_id)
        report = escalation.to_dict()
        if self._escalation_sink is not None:
            try:
                self._escalation_sink(report)
            except Exception:
                pass
        return report

    # ------------------------------------------------------------------
    # Delivery
    # ------------------------------------------------------------------

    @staticmethod
    def _recipient_for(customer: ResolvedCustomer, channel: str) -> Optional[str]:
        if channel == 'email':
            return customer.email
        if channel in MESSAGING_CHANNELS:
            return customer.phone
        return customer.email or customer.phone or customer.customer_id

    def _deliver(self, customer: ResolvedCustomer, template_id: str, context: Dict[str, Any], *,
                 kind: str, row: Optional[Interaction] = None, actor: Optional[str] = None,
                 channel_override: Optional[str] = None,
                 purpose: str = TRANSACTIONAL) -> Delivery:
        rendered = TemplateEngine.render_registered(template_id, context)
        if rendered is None:
            raise ValueError(f"Template {template_id} not found")
        channel = str(channel_override or rendered['channel'] or 'email').lower()
        if channel not in _CHANNELS:
            channel = 'email'
        if channel == 'email' and not customer.email:
            channel = 'portal' if not customer.phone else 'sms'
        elif channel in MESSAGING_CHANNELS and not customer.phone:
            channel = 'email' if customer.email else 'portal'
        recipient = self._recipient_for(customer, channel) or customer.customer_id

        # Gate first (so this send is not counted against itself), then the
        # pending row, then the provider call, then the final status.
        decision = self.messaging_policy.authorize(customer.customer_id, channel, purpose,
                                                   customer_record=customer.record)

        def _base(interaction_id: str) -> Dict[str, Any]:
            return dict(
                delivery_id=f"NOTIF_{customer.customer_id}_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:6].upper()}",
                customer_id=customer.customer_id, channel=channel, recipient=mask_recipient(recipient),
                subject=rendered['subject'], message=rendered['body'], template=template_id,
                signature_required=bool(rendered.get('signature_required')),
                interaction_id=interaction_id,
                metadata={'template': template_id, 'kind': kind, 'handled_by': self.agent_id},
            )

        if not decision.allowed:
            if row is None:
                row = self.interaction_log.record(
                    customer_id=customer.customer_id, agent=AGENT_NAME, kind=kind, channel=channel,
                    status='refused', template=template_id, purpose=purpose, recipient=recipient,
                    actor=actor, handled_by=self.agent_id, code=decision.code, detail=decision.reason,
                    metadata={'policy': decision.to_dict()},
                )
                self._interaction_ids.append(row.interaction_id)
            else:
                self.interaction_log.update(row.interaction_id, status='refused', code=decision.code,
                                            detail=decision.reason, metadata={'policy': decision.to_dict()})
            delivery = Delivery(success=False, delivery_status='Refused', error_code=decision.code,
                                error_message=decision.reason, **_base(row.interaction_id))
            self._sink(delivery)
            return delivery

        if row is None:
            row = self.interaction_log.record(
                customer_id=customer.customer_id, agent=AGENT_NAME, kind=kind, channel=channel,
                status='pending', template=template_id, purpose=purpose, recipient=recipient,
                actor=actor, handled_by=self.agent_id,
                detail=self._clip(rendered['subject'] or rendered['body'], 300),
            )
            self._interaction_ids.append(row.interaction_id)
        else:
            self.interaction_log.update(row.interaction_id, status='pending')
        base = _base(row.interaction_id)

        request = NotificationRequest(
            channel=_CHANNELS[channel], recipient=recipient,
            subject=rendered['subject'] or None, content=rendered['body'],
            priority=NotificationPriority.NORMAL, customer_id=customer.customer_id,
            metadata={'agent': 'customer_service_agent', 'template': template_id, 'kind': kind,
                      'handled_by': self.agent_id, 'actor': actor},
        )
        try:
            result = self.notification_service.send(request)
        except Exception as exc:
            self.interaction_log.update(row.interaction_id, status='failed', code='SEND_EXCEPTION',
                                        detail=str(exc)[:300])
            raise
        self.interaction_log.update(
            row.interaction_id,
            status='sent' if result.success else 'failed',
            code=None if result.success else (result.error_code or 'SEND_FAILED'),
            detail=None if result.success else (result.error_message or None),
            notification_id=result.notification_id,
        )
        delivery = Delivery(
            success=bool(result.success), delivery_status='Sent' if result.success else 'Failed',
            notification_id=result.notification_id, error_code=result.error_code,
            error_message=result.error_message, **base,
        )
        self._sink(delivery)
        return delivery

    def _sink(self, delivery: Delivery) -> None:
        if self._delivery_sink is None:
            return
        try:
            self._delivery_sink(delivery)
        except Exception:
            pass

    @staticmethod
    def _clip(value: str, limit: int) -> str:
        text = str(value or '')
        return text if len(text) <= limit else text[: max(0, limit - 1)].rstrip() + '…'


def _service_desk_health() -> Dict[str, Any]:
    from .consent import consent_enforced, daily_cap
    return {
        'status': 'ok',
        'templates': [t for t in TemplateEngine.registered_ids() if t in SERVICE_TEMPLATES],
        'interaction_log': get_interaction_log().snapshot(),
        'consent': {'enforced': consent_enforced(), 'daily_cap': daily_cap()},
        'escalations': get_escalation_desk().snapshot(),
    }


# ---------------------------------------------------------------------------
# Agent runtime registration (discovery + health only).
# ---------------------------------------------------------------------------
try:
    from services.agent_runtime import AgentDescriptor as _AgentDescriptor, register as _register_agent
    _register_agent(_AgentDescriptor(
        id='customer_service',
        name='Customer Service Agent',
        version='1.1.0',
        module=__name__,
        description=(
            'Handles customer inquiries with acknowledgements, sends templated '
            'correspondence, suggests rule-based upsell offers, logs '
            'interactions to the shared customer timeline, and escalates '
            'complex cases to human teams through the shared escalation desk.'
        ),
        entry_url='/admin.html',
        api={'method': 'LIB', 'path': 'services.customer_agent.service_desk.CustomerServiceAgent'},
        roles=('admin',),
        deterministic=True,
        sample_prompts=(
            'Acknowledge the inquiry from customer CUST-1001',
            'Escalate this case to the claims team',
        ),
    ), health_fn=_service_desk_health)
except Exception as _reg_exc:  # pragma: no cover
    import logging as _logging
    _logging.getLogger('phins.customer_service_agent').warning(
        "customer service agent registration skipped: %s", _reg_exc)


__all__ = [
    'AGENT_NAME', 'SERVICE_TEMPLATES', 'CustomerServiceAgent', 'Delivery', 'ResolvedCustomer',
    'ensure_service_templates', 'import_legacy_templates',
]
