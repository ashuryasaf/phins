"""
Per-customer channel consent and daily messaging cap (B6).

Before any WhatsApp / SMS message leaves either customer-facing facade the
:class:`MessagingPolicy` answers one question — *may this customer be
messaged on this channel right now?* — from three inputs:

* **Consent** — an explicit grant/revocation kept in the
  :class:`ConsentRegistry` (``agent_artifacts`` / kind ``consent``, durable in
  DB mode), falling back to flags on the customer record
  (``consents.whatsapp``, ``whatsapp_consent``, ``whatsapp_opt_in``,
  ``communication_preferences.whatsapp``; ``marketing_consent`` for relational
  copy). Relational (marketing / relations) messages require a positive
  answer; transactional ones (welcome package, bill, service acknowledgement)
  need only the absence of a revocation. An explicit revocation blocks both.
* **Daily cap** — ``PHINS_CUSTOMER_DAILY_MESSAGE_CAP`` (default 5, ``0``
  disables) messages per customer per UTC day across WhatsApp + SMS, counted
  from the shared interaction log (durable, so peers agree), including rows
  still ``pending`` so two concurrent sends cannot both squeeze under it.
* **Enforcement switch** — ``PHINS_CUSTOMER_MESSAGING_CONSENT_ENFORCED``
  (default on). Turning it off skips the consent step only; the cap and an
  explicit revocation still apply.

Email is not gated here (the notification service's preferences and
suppression lists already cover it). The decision is returned as data
(:class:`Decision`) so the facades can log a refusal with its code instead of
silently dropping the message.
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from services.hydrated_store import artifact_store

from .interaction_log import AGENT_ID, MESSAGING_CHANNELS, InteractionLog, get_interaction_log

CONSENT_KIND = 'consent'
DEFAULT_DAILY_CAP = 5
DAILY_CAP_ENV = 'PHINS_CUSTOMER_DAILY_MESSAGE_CAP'
ENFORCE_ENV = 'PHINS_CUSTOMER_MESSAGING_CONSENT_ENFORCED'

TRANSACTIONAL = 'transactional'
RELATIONAL = 'relational'
PURPOSES = (TRANSACTIONAL, RELATIONAL)

# Outreach templates -> purpose. Bills are account servicing; the rest is relations copy.
TEMPLATE_PURPOSE = {
    'welcome': TRANSACTIONAL,
    'bill': TRANSACTIONAL,
    'reminder': TRANSACTIONAL,
    'message': RELATIONAL,
    'offer': RELATIONAL,
}


def daily_cap() -> int:
    try:
        return max(0, int(os.environ.get(DAILY_CAP_ENV, DEFAULT_DAILY_CAP)))
    except (TypeError, ValueError):
        return DEFAULT_DAILY_CAP


def consent_enforced() -> bool:
    return str(os.environ.get(ENFORCE_ENV, 'true')).strip().lower() not in ('0', 'false', 'no', 'off')


@dataclass
class ChannelConsent:
    granted: bool
    source: str = 'explicit'      # explicit | otp_verified | import | customer_record
    actor: Optional[str] = None
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    note: Optional[str] = None


@dataclass
class ConsentRecord:
    customer_id: str
    channels: Dict[str, ChannelConsent] = field(default_factory=dict)
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            'customer_id': self.customer_id,
            'updated_at': self.updated_at,
            'channels': {
                name: {'granted': c.granted, 'source': c.source, 'actor': c.actor,
                       'updated_at': c.updated_at, 'note': c.note}
                for name, c in sorted(self.channels.items())
            },
        }


def _flag(value: Any) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in ('1', 'true', 'yes', 'y', 'on', 'granted', 'opt_in', 'opted_in'):
        return True
    if text in ('0', 'false', 'no', 'n', 'off', 'revoked', 'opt_out', 'opted_out'):
        return False
    return None


def consent_from_record(record: Optional[Dict[str, Any]], channel: str,
                        purpose: str = RELATIONAL) -> Optional[bool]:
    """Consent implied by flags already on a customer record, or None."""
    if not isinstance(record, dict):
        return None
    channel = str(channel).lower()
    for container_key in ('consents', 'consent', 'communication_preferences', 'preferences'):
        container = record.get(container_key)
        if isinstance(container, dict):
            for key in (channel, f'{channel}_enabled', f'{channel}_opt_in'):
                flag = _flag(container.get(key))
                if flag is not None:
                    return flag
    for key in (f'{channel}_consent', f'{channel}_opt_in', f'{channel}_enabled', f'allow_{channel}'):
        flag = _flag(record.get(key))
        if flag is not None:
            return flag
    if purpose == RELATIONAL:
        flag = _flag(record.get('marketing_consent', record.get('marketing_opt_in')))
        if flag is not None:
            return flag
    return None


class ConsentRegistry:
    """Explicit per-customer, per-channel consent (grant or revoke)."""

    def __init__(self, store=None):
        self._store = store if store is not None else artifact_store(
            'customer_agent.consent', agent_id=AGENT_ID, kind=CONSENT_KIND,
            record_type=ConsentRecord,
            subject=lambda r: ('customer', r.customer_id),
        )
        self._lock = threading.RLock()

    @property
    def store(self):
        return self._store

    def get(self, customer_id: str) -> Optional[ConsentRecord]:
        return self._store.get(str(customer_id))

    def set(self, customer_id: str, channel: str, granted: bool, *, source: str = 'explicit',
            actor: Optional[str] = None, note: Optional[str] = None,
            now: Optional[datetime] = None) -> ConsentRecord:
        channel = str(channel or '').strip().lower()
        if channel not in MESSAGING_CHANNELS:
            raise ValueError(f"channel must be one of {', '.join(MESSAGING_CHANNELS)}")
        stamp = (now or datetime.now(timezone.utc)).isoformat()
        with self._lock:
            current = self._store.get(str(customer_id)) or ConsentRecord(customer_id=str(customer_id))
            channels = dict(current.channels)
            channels[channel] = ChannelConsent(granted=bool(granted), source=source, actor=actor,
                                               updated_at=stamp, note=note)
            record = ConsentRecord(customer_id=str(customer_id), channels=channels, updated_at=stamp)
            self._store[str(customer_id)] = record
            return record

    def explicit(self, customer_id: str, channel: str) -> Optional[ChannelConsent]:
        record = self.get(customer_id)
        if record is None:
            return None
        return record.channels.get(str(channel).lower())

    def clear(self) -> None:
        self._store.clear()

    def snapshot(self) -> Dict[str, Any]:
        view = {'customers': len(self._store)}
        if hasattr(self._store, 'snapshot'):
            view['store'] = self._store.snapshot()
        return view


@dataclass
class Decision:
    allowed: bool
    code: str
    reason: str
    channel: str
    purpose: str
    consent: Optional[bool] = None
    consent_source: Optional[str] = None
    sent_today: int = 0
    daily_cap: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            'allowed': self.allowed, 'code': self.code, 'reason': self.reason,
            'channel': self.channel, 'purpose': self.purpose, 'consent': self.consent,
            'consent_source': self.consent_source, 'sent_today': self.sent_today,
            'daily_cap': self.daily_cap,
        }


class MessagingPolicy:
    """Consent + daily-cap gate applied before WhatsApp / SMS sends."""

    def __init__(self, registry: Optional[ConsentRegistry] = None,
                 interaction_log: Optional[InteractionLog] = None):
        self._registry = registry
        self._log = interaction_log

    @property
    def registry(self) -> ConsentRegistry:
        if self._registry is None:
            self._registry = get_consent_registry()
        return self._registry

    @property
    def log(self) -> InteractionLog:
        if self._log is None:
            self._log = get_interaction_log()
        return self._log

    def resolve_consent(self, customer_id: str, channel: str, purpose: str = RELATIONAL,
                        customer_record: Optional[Dict[str, Any]] = None
                        ) -> tuple[Optional[bool], Optional[str]]:
        """``(consent, source)``: explicit registry first, then record flags, else unknown."""
        explicit = self.registry.explicit(customer_id, channel)
        if explicit is not None:
            return bool(explicit.granted), explicit.source or 'explicit'
        implied = consent_from_record(customer_record, channel, purpose)
        if implied is not None:
            return implied, 'customer_record'
        return None, None

    def authorize(self, customer_id: str, channel: str, purpose: str = RELATIONAL, *,
                  customer_record: Optional[Dict[str, Any]] = None,
                  now: Optional[datetime] = None) -> Decision:
        channel = str(channel or '').strip().lower()
        purpose = purpose if purpose in PURPOSES else RELATIONAL
        if channel not in MESSAGING_CHANNELS:
            return Decision(True, 'NOT_GATED', 'Channel is not consent-gated', channel, purpose)

        consent, source = self.resolve_consent(customer_id, channel, purpose, customer_record)
        cap = daily_cap()
        sent_today = self.log.count_sent_today(customer_id, MESSAGING_CHANNELS, now=now)

        if consent is False:
            return Decision(False, 'CONSENT_REVOKED',
                            f'Customer has opted out of {channel} messages', channel, purpose,
                            consent, source, sent_today, cap)
        if consent_enforced() and purpose == RELATIONAL and consent is not True:
            return Decision(False, 'CONSENT_REQUIRED',
                            f'No {channel} consent on file for relational messaging', channel, purpose,
                            consent, source, sent_today, cap)
        if cap and sent_today >= cap:
            return Decision(False, 'DAILY_CAP_REACHED',
                            f'Daily cap of {cap} {"/".join(MESSAGING_CHANNELS)} message(s) reached',
                            channel, purpose, consent, source, sent_today, cap)
        return Decision(True, 'ALLOWED', 'Consent and daily cap satisfied', channel, purpose,
                        consent, source, sent_today, cap)


_REGISTRY: Optional[ConsentRegistry] = None
_REGISTRY_LOCK = threading.Lock()


def get_consent_registry() -> ConsentRegistry:
    global _REGISTRY
    with _REGISTRY_LOCK:
        if _REGISTRY is None:
            _REGISTRY = ConsentRegistry()
        return _REGISTRY


def reset_consent_registry() -> None:
    global _REGISTRY
    with _REGISTRY_LOCK:
        _REGISTRY = None


__all__ = [
    'CONSENT_KIND', 'DAILY_CAP_ENV', 'DEFAULT_DAILY_CAP', 'ENFORCE_ENV', 'PURPOSES', 'RELATIONAL',
    'TEMPLATE_PURPOSE', 'TRANSACTIONAL', 'ChannelConsent', 'ConsentRecord', 'ConsentRegistry',
    'Decision', 'MessagingPolicy', 'consent_enforced', 'consent_from_record', 'daily_cap',
    'get_consent_registry', 'reset_consent_registry',
]
