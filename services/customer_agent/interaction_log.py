"""
Shared customer interaction log (B6).

Both customer-facing facades — :mod:`services.customer_agent.communication`
(welcome packages, relations outreach) and
:mod:`services.customer_agent.service_desk` (inquiries, correspondence,
escalations) — append to this one log, so a customer's timeline is complete
regardless of which agent touched them. It is the source of truth for the
per-customer daily messaging cap (:mod:`services.customer_agent.consent`).

Rows live in ``agent_artifacts`` (agent ``customer_agent`` / kind
``interaction``) through the A4 :class:`~services.hydrated_store.ArtifactStore`:
durable and shared across web/worker instances in DB mode, a plain in-process
dict otherwise. One process-wide log object is handed out by
:func:`get_interaction_log` so the two facades share it in either mode.

Integrity rules: a record is written **before** a send is attempted with
``status='pending'`` and updated to ``sent`` / ``failed`` / ``refused`` after
the fact, so a crash mid-send leaves a visible pending row rather than a gap;
recipients are stored masked only; records are never deleted by the agents
(retention is the operator's ``prune_durable``).
"""

from __future__ import annotations

import dataclasses
import re
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from services.hydrated_store import artifact_store

AGENT_ID = 'customer_agent'
INTERACTION_KIND = 'interaction'

MESSAGING_CHANNELS = ('whatsapp', 'sms')  # channels the consent + cap rules gate


@dataclass
class Interaction:
    """One customer touch by a customer-facing agent."""

    interaction_id: str
    customer_id: str
    agent: str                # 'communication' | 'service_desk'
    kind: str                 # inquiry | correspondence | outreach | welcome | escalation | consent
    channel: str = ''         # email | whatsapp | sms | portal | ''
    status: str = 'pending'   # pending | sent | failed | refused | logged
    template: Optional[str] = None
    purpose: Optional[str] = None       # transactional | relational
    recipient_masked: Optional[str] = None
    actor: Optional[str] = None
    handled_by: Optional[str] = None
    code: Optional[str] = None          # refusal / failure code
    detail: Optional[str] = None
    notification_id: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)


def mask_recipient(value: Optional[str]) -> Optional[str]:
    """PII-safe form of an email or phone for the log."""
    if not value:
        return None
    text = str(value)
    if '@' in text:
        local, _, domain = text.partition('@')
        return f"{local[:1] or '*'}***@{domain}"
    digits = re.sub(r'\D', '', text)
    return f"***{digits[-4:]}" if len(digits) >= 4 else '***'


class InteractionLog:
    """Keyed, durable-when-possible log shared by the customer-facing agents."""

    def __init__(self, store=None):
        self._store = store if store is not None else artifact_store(
            'customer_agent.interactions', agent_id=AGENT_ID, kind=INTERACTION_KIND,
            record_type=Interaction,
            subject=lambda r: ('customer', r.customer_id),
        )
        self._lock = threading.RLock()

    @property
    def store(self):
        return self._store

    # -- writes -------------------------------------------------------------
    def record(self, *, customer_id: str, agent: str, kind: str, channel: str = '',
               status: str = 'pending', template: Optional[str] = None,
               purpose: Optional[str] = None, recipient: Optional[str] = None,
               actor: Optional[str] = None, handled_by: Optional[str] = None,
               code: Optional[str] = None, detail: Optional[str] = None,
               notification_id: Optional[str] = None,
               metadata: Optional[Dict[str, Any]] = None,
               now: Optional[datetime] = None) -> Interaction:
        stamp = (now or datetime.now(timezone.utc)).isoformat()
        interaction = Interaction(
            interaction_id=f"INT-{uuid.uuid4().hex[:12].upper()}",
            customer_id=str(customer_id or ''),
            agent=str(agent),
            kind=str(kind),
            channel=str(channel or '').lower(),
            status=str(status),
            template=template,
            purpose=purpose,
            recipient_masked=mask_recipient(recipient),
            actor=actor,
            handled_by=handled_by,
            code=code,
            detail=detail,
            notification_id=notification_id,
            created_at=stamp,
            metadata=dict(metadata or {}),
        )
        with self._lock:
            self._store[interaction.interaction_id] = interaction
        return interaction

    def update(self, interaction_id: str, *, status: Optional[str] = None,
               code: Optional[str] = None, detail: Optional[str] = None,
               notification_id: Optional[str] = None,
               metadata: Optional[Dict[str, Any]] = None,
               now: Optional[datetime] = None) -> Optional[Interaction]:
        with self._lock:
            current = self._store.get(interaction_id)
            if current is None:
                return None
            updated = dataclasses.replace(
                current,
                status=status if status is not None else current.status,
                code=code if code is not None else current.code,
                detail=detail if detail is not None else current.detail,
                notification_id=notification_id if notification_id is not None else current.notification_id,
                updated_at=(now or datetime.now(timezone.utc)).isoformat(),
                metadata={**current.metadata, **(metadata or {})},
            )
            self._store[interaction_id] = updated
            return updated

    # -- reads ---------------------------------------------------------------
    def get(self, interaction_id: str) -> Optional[Interaction]:
        return self._store.get(interaction_id)

    def all(self) -> List[Interaction]:
        return sorted(self._store.values(), key=lambda i: (i.created_at, i.interaction_id))

    def for_customer(self, customer_id: str, *, kinds: Optional[Iterable[str]] = None,
                     agent: Optional[str] = None, limit: Optional[int] = None) -> List[Interaction]:
        wanted = set(kinds) if kinds else None
        rows = [i for i in self.all()
                if i.customer_id == str(customer_id)
                and (wanted is None or i.kind in wanted)
                and (agent is None or i.agent == agent)]
        if limit:
            rows = rows[-int(limit):]
        return rows

    def count_sent_today(self, customer_id: str, channels: Iterable[str] = MESSAGING_CHANNELS,
                         now: Optional[datetime] = None) -> int:
        """Messages that reached (or are in flight to) a customer on the gated
        channels during the current UTC day. ``pending`` counts so two
        concurrent sends cannot both pass the cap."""
        now = now or datetime.now(timezone.utc)
        day = now.astimezone(timezone.utc).date().isoformat()
        wanted = {str(c).lower() for c in channels}
        return sum(
            1 for i in self._store.values()
            if i.customer_id == str(customer_id)
            and i.channel in wanted
            and i.status in ('sent', 'pending')
            and str(i.created_at)[:10] == day
        )

    def snapshot(self) -> Dict[str, Any]:
        rows = list(self._store.values())
        by_status: Dict[str, int] = {}
        by_agent: Dict[str, int] = {}
        for row in rows:
            by_status[row.status] = by_status.get(row.status, 0) + 1
            by_agent[row.agent] = by_agent.get(row.agent, 0) + 1
        view = {'interactions': len(rows), 'by_status': by_status, 'by_agent': by_agent}
        if hasattr(self._store, 'snapshot'):
            view['store'] = self._store.snapshot()
        return view

    def clear(self) -> None:
        """Drop the cache (tests). Durable rows are not bulk-deleted."""
        self._store.clear()


_LOG: Optional[InteractionLog] = None
_LOG_LOCK = threading.Lock()


def get_interaction_log() -> InteractionLog:
    """The process-wide log both facades share."""
    global _LOG
    with _LOG_LOCK:
        if _LOG is None:
            _LOG = InteractionLog()
        return _LOG


def reset_interaction_log() -> None:
    """Forget the shared log (tests / DB-mode flips)."""
    global _LOG
    with _LOG_LOCK:
        _LOG = None


__all__ = [
    'AGENT_ID', 'INTERACTION_KIND', 'MESSAGING_CHANNELS', 'Interaction', 'InteractionLog',
    'get_interaction_log', 'mask_recipient', 'reset_interaction_log',
]
