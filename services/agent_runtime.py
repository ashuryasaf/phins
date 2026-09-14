"""
Agent Runtime Contract
======================
One declarative registry for every software agent that operates on PHINS
(underwriting/claims bots, automation controller, document intelligence,
communication agents, video agents, BI, trading, ...).

Design (docs/agent_operations_optimization_design.md §A1):

* **Discovery only, no execution.** Agents keep their existing public methods.
  The contract adds ``describe()`` / ``health()`` / ``metrics()`` so humans
  and programmatic callers see the same catalog, and so operations can
  monitor every agent from one place.
* **Read-only and side-effect free.** Registration stores a descriptor plus
  optional health/metrics callables. Health callables must be pure reads;
  the registry never mutates agent state and never raises into callers.
* **No agent imports here.** Agents import this module and register at the
  bottom of their own module; this module imports nothing agent-specific,
  so it can never create an import cycle.
* **Idempotent re-registration.** Re-executing an agent module (e.g.
  ``importlib.reload`` in tests) re-registers the same id from the same
  module and is accepted; a *different* module claiming an existing id is
  rejected to keep ids unambiguous.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger('phins.agent_runtime')

HealthFn = Callable[[], Dict[str, Any]]
MetricsFn = Callable[[], Dict[str, Any]]

HEALTH_OK = 'ok'
HEALTH_DEGRADED = 'degraded'
HEALTH_UNAVAILABLE = 'unavailable'
HEALTH_UNKNOWN = 'unknown'


@dataclass(frozen=True)
class AgentDescriptor:
    """Declarative description of one software agent."""

    id: str
    name: str
    version: str
    module: str
    description: str
    entry_url: str
    api: Dict[str, str]
    roles: Tuple[str, ...]
    deterministic: bool = True
    executes_async: bool = False
    moves_money: bool = False
    sample_prompts: Tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data['roles'] = list(self.roles)
        data['sample_prompts'] = list(self.sample_prompts)
        data['api'] = dict(self.api or {})
        return data

    def to_capability(self) -> Dict[str, Any]:
        """Shape compatible with ``services.ai_capabilities`` entries."""
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'entry_url': self.entry_url,
            'api': dict(self.api or {}),
            'roles': list(self.roles),
            'sample_prompts': list(self.sample_prompts),
            'deterministic': bool(self.deterministic),
            'version': self.version,
            'module': self.module,
            'executes_async': bool(self.executes_async),
            'moves_money': bool(self.moves_money),
        }


@dataclass
class _Registration:
    descriptor: AgentDescriptor
    health_fn: Optional[HealthFn]
    metrics_fn: Optional[MetricsFn]
    registered_at: str


_LOCK = threading.RLock()
_REGISTRY: Dict[str, _Registration] = {}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def register(descriptor: AgentDescriptor,
             health_fn: Optional[HealthFn] = None,
             metrics_fn: Optional[MetricsFn] = None) -> AgentDescriptor:
    """Register (or idempotently re-register) an agent descriptor.

    Raises ``ValueError`` when a different module tries to claim an id that is
    already registered, or when the descriptor is missing required fields.
    """
    if not isinstance(descriptor, AgentDescriptor):
        raise ValueError('descriptor must be an AgentDescriptor')
    if not descriptor.id or not descriptor.module or not descriptor.name:
        raise ValueError('descriptor requires id, name and module')
    with _LOCK:
        existing = _REGISTRY.get(descriptor.id)
        if existing is not None and existing.descriptor.module != descriptor.module:
            raise ValueError(
                f"agent id '{descriptor.id}' already registered by "
                f"{existing.descriptor.module}; refused for {descriptor.module}"
            )
        _REGISTRY[descriptor.id] = _Registration(
            descriptor=descriptor,
            health_fn=health_fn,
            metrics_fn=metrics_fn,
            registered_at=_now_iso(),
        )
    return descriptor


def unregister(agent_id: str) -> bool:
    """Remove a registration. Intended for tests; returns True when removed."""
    with _LOCK:
        return _REGISTRY.pop(agent_id, None) is not None


def registry() -> List[AgentDescriptor]:
    """All registered descriptors, sorted by id for stable output."""
    with _LOCK:
        return [reg.descriptor for _, reg in sorted(_REGISTRY.items())]


def get_descriptor(agent_id: str) -> Optional[AgentDescriptor]:
    with _LOCK:
        reg = _REGISTRY.get(agent_id)
    return reg.descriptor if reg else None


def is_registered(agent_id: str) -> bool:
    with _LOCK:
        return agent_id in _REGISTRY


def health(agent_id: str) -> Dict[str, Any]:
    """Run the agent's health callable defensively.

    Never raises. A missing callable yields ``unknown``; an exception yields
    ``unavailable`` with the error message (no stack traces, no secrets).
    """
    with _LOCK:
        reg = _REGISTRY.get(agent_id)
    checked_at = _now_iso()
    if reg is None:
        return {'status': HEALTH_UNKNOWN, 'checked_at': checked_at,
                'error': 'not registered'}
    if reg.health_fn is None:
        return {'status': HEALTH_OK, 'checked_at': checked_at,
                'detail': 'module loaded; no health probe defined'}
    try:
        result = reg.health_fn() or {}
        if not isinstance(result, dict):
            result = {'detail': str(result)}
        status = str(result.get('status') or HEALTH_OK).lower()
        if status not in (HEALTH_OK, HEALTH_DEGRADED, HEALTH_UNAVAILABLE, HEALTH_UNKNOWN):
            status = HEALTH_UNKNOWN
        payload = dict(result)
        payload['status'] = status
        payload['checked_at'] = checked_at
        return payload
    except Exception as exc:  # noqa: BLE001 - health must never break callers
        logger.warning("agent health probe failed for %s: %s", agent_id, exc)
        return {'status': HEALTH_UNAVAILABLE, 'checked_at': checked_at,
                'error': str(exc)[:300]}


def metrics(agent_id: str) -> Dict[str, Any]:
    """Return the agent's metrics snapshot.

    Uses the registered ``metrics_fn`` when present, otherwise the shared
    ``services.agent_metrics`` snapshot for that id. Never raises.
    """
    with _LOCK:
        reg = _REGISTRY.get(agent_id)
    try:
        if reg is not None and reg.metrics_fn is not None:
            result = reg.metrics_fn() or {}
            return result if isinstance(result, dict) else {'detail': str(result)}
        from services.agent_metrics import snapshot
        return snapshot(agent_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("agent metrics failed for %s: %s", agent_id, exc)
        return {'error': str(exc)[:300]}


def health_all() -> Dict[str, Dict[str, Any]]:
    return {d.id: health(d.id) for d in registry()}


def overview() -> List[Dict[str, Any]]:
    """Descriptor + health + metrics for every registered agent."""
    items: List[Dict[str, Any]] = []
    for desc in registry():
        with _LOCK:
            reg = _REGISTRY.get(desc.id)
        items.append({
            **desc.to_dict(),
            'registered_at': reg.registered_at if reg else None,
            'health': health(desc.id),
            'metrics': metrics(desc.id),
        })
    return items


__all__ = [
    'AgentDescriptor', 'register', 'unregister', 'registry', 'get_descriptor',
    'is_registered', 'health', 'metrics', 'health_all', 'overview',
    'HEALTH_OK', 'HEALTH_DEGRADED', 'HEALTH_UNAVAILABLE', 'HEALTH_UNKNOWN',
]
