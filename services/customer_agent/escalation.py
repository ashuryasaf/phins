"""
One escalation path for both customer-facing facades (B6).

``escalate()`` does three things, in this order, so a failure leaves evidence
rather than a silent gap:

1. writes the escalation record to ``agent_artifacts`` (kind ``escalation``)
   through the A4 store — durable and visible to every instance in DB mode;
2. appends an ``AuditService`` entry (``customer_agent.escalated``), which the
   audit service persists to ``audit_logs`` in DB mode;
3. appends an ``escalation`` row to the shared interaction log so the
   customer's timeline shows the hand-off.

The record keeps the legacy report shape (``report_id``, ``report_type``,
``report_date``, ``assigned_to``, ``details``) so callers of the old
``CustomerServiceAgent.escalate_to_human`` keep working unchanged.
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from services.hydrated_store import artifact_store

from .interaction_log import AGENT_ID, InteractionLog, get_interaction_log

ESCALATION_KIND = 'escalation'
AUDIT_ACTION = 'customer_agent.escalated'
DEFAULT_TEAM = 'Service Team'


@dataclass
class Escalation:
    report_id: str
    customer_id: str
    reason: str
    assigned_to: str
    source_agent: str
    report_type: str = 'Service Escalation'
    report_date: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    status: str = 'open'
    interaction_id: Optional[str] = None
    audit_id: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'report_id': self.report_id,
            'report_type': self.report_type,
            'report_date': self.report_date,
            'assigned_to': self.assigned_to,
            'customer_id': self.customer_id,
            'reason': self.reason,
            'source_agent': self.source_agent,
            'status': self.status,
            'interaction_id': self.interaction_id,
            'audit_id': self.audit_id,
            'details': dict(self.details),
        }


class EscalationDesk:
    """Durable escalation records + audit trail shared by both facades."""

    def __init__(self, store=None, audit_service=None, interaction_log: Optional[InteractionLog] = None):
        self._store = store if store is not None else artifact_store(
            'customer_agent.escalations', agent_id=AGENT_ID, kind=ESCALATION_KIND,
            record_type=Escalation,
            subject=lambda r: ('customer', r.customer_id),
        )
        self._audit = audit_service
        self._log = interaction_log
        self._lock = threading.RLock()

    @property
    def store(self):
        return self._store

    @property
    def audit(self):
        if self._audit is None:
            from services.audit_service import AuditService
            self._audit = AuditService()
        return self._audit

    @property
    def log(self) -> InteractionLog:
        if self._log is None:
            self._log = get_interaction_log()
        return self._log

    def escalate(self, *, customer_id: str, reason: str, source_agent: str,
                 assigned_team: str = DEFAULT_TEAM, actor: Optional[str] = None,
                 customer_name: Optional[str] = None, channel: str = '',
                 context: Optional[Dict[str, Any]] = None,
                 now: Optional[datetime] = None) -> Escalation:
        stamp = (now or datetime.now(timezone.utc))
        report_id = f"ESC_{customer_id}_{stamp.strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:6].upper()}"
        details = {
            'customer_id': str(customer_id),
            'customer_name': customer_name or 'Unknown',
            'reason': str(reason),
            'timestamp': stamp.isoformat(),
            'assigned_team': assigned_team,
            'source_agent': source_agent,
            **(context or {}),
        }
        escalation = Escalation(
            report_id=report_id, customer_id=str(customer_id), reason=str(reason),
            assigned_to=assigned_team, source_agent=source_agent,
            report_date=stamp.isoformat(), details=details,
        )
        with self._lock:
            # 1. durable record first (fail-closed: an exception here propagates).
            self._store[report_id] = escalation
            # 2. audit trail.
            audit_id = None
            try:
                event = self.audit.log(
                    actor=actor or source_agent, action=AUDIT_ACTION, entity='customer',
                    entity_id=str(customer_id),
                    details={'report_id': report_id, 'reason': str(reason),
                             'assigned_team': assigned_team, 'source_agent': source_agent,
                             'customer_id': str(customer_id)},
                )
                audit_id = (event or {}).get('id') if isinstance(event, dict) else None
            except Exception:
                audit_id = None
            # 3. timeline entry in the shared interaction log.
            interaction = self.log.record(
                customer_id=str(customer_id), agent=source_agent, kind='escalation',
                channel=channel, status='logged', actor=actor, handled_by=assigned_team,
                detail=str(reason), metadata={'report_id': report_id, 'audit_id': audit_id},
                now=stamp,
            )
            escalation.interaction_id = interaction.interaction_id
            escalation.audit_id = audit_id
            self._store[report_id] = escalation
        return escalation

    def get(self, report_id: str) -> Optional[Escalation]:
        return self._store.get(report_id)

    def for_customer(self, customer_id: str) -> List[Escalation]:
        return sorted((e for e in self._store.values() if e.customer_id == str(customer_id)),
                      key=lambda e: (e.report_date, e.report_id))

    def all(self) -> List[Escalation]:
        return sorted(self._store.values(), key=lambda e: (e.report_date, e.report_id))

    def clear(self) -> None:
        self._store.clear()

    def snapshot(self) -> Dict[str, Any]:
        rows = list(self._store.values())
        view = {'escalations': len(rows), 'open': sum(1 for e in rows if e.status == 'open')}
        if hasattr(self._store, 'snapshot'):
            view['store'] = self._store.snapshot()
        return view


_DESK: Optional[EscalationDesk] = None
_DESK_LOCK = threading.Lock()


def get_escalation_desk() -> EscalationDesk:
    global _DESK
    with _DESK_LOCK:
        if _DESK is None:
            _DESK = EscalationDesk()
        return _DESK


def reset_escalation_desk() -> None:
    global _DESK
    with _DESK_LOCK:
        _DESK = None


__all__ = ['AUDIT_ACTION', 'DEFAULT_TEAM', 'ESCALATION_KIND', 'Escalation', 'EscalationDesk',
           'get_escalation_desk', 'reset_escalation_desk']
