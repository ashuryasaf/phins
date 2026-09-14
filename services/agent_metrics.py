"""
Per-Agent Operational Metrics
=============================
In-process counters and latency reservoirs keyed by agent id
(docs/agent_operations_optimization_design.md §A5).

Guarantees:

* **Observation only.** ``instrument_agent`` measures a call and re-raises
  any exception unchanged. It never alters arguments, return values, or
  agent state, and it reads a decision label from the result without
  copying or mutating it.
* **Bounded memory.** Each agent keeps a fixed-size latency reservoir
  (``PHINS_AGENT_METRICS_RESERVOIR``, default 512 samples) and a decision
  label counter; nothing grows unbounded.
* **No decision logging here.** Decision *records* stay with
  ``services.ai_decision_log`` (written by the agents that own them); this
  module only counts labels, so a decision is never recorded twice.
* **Never raises into callers.** Every metrics path is wrapped; a metrics
  failure is logged and the agent call proceeds.
"""

from __future__ import annotations

import functools
import logging
import os
import threading
import time
from collections import Counter, deque
from datetime import datetime, timezone
from typing import Any, Callable, Deque, Dict, List, Optional

logger = logging.getLogger('phins.agent_metrics')

_RESERVOIR = max(16, int(os.environ.get('PHINS_AGENT_METRICS_RESERVOIR', '512')))
_MAX_DECISION_LABELS = 64
_PUBLIC_FIELDS = ('calls', 'errors', 'error_rate', 'in_flight', 'latency_ms',
                  'gauges', 'last_call_at')

_DEFAULT_SLO_P95_MS = float(os.environ.get('PHINS_AGENT_SLO_P95_MS', '5000'))
_DEFAULT_SLO_ERROR_RATE = float(os.environ.get('PHINS_AGENT_SLO_ERROR_RATE', '0.05'))
_DEFAULT_SLO_MIN_CALLS = int(os.environ.get('PHINS_AGENT_SLO_MIN_CALLS', '20'))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class _AgentStats:
    __slots__ = ('calls', 'errors', 'in_flight', 'latency', 'decisions',
                 'gauges', 'last_call_at', 'last_error', 'last_error_at')

    def __init__(self) -> None:
        self.calls = 0
        self.errors = 0
        self.in_flight = 0
        self.latency: Deque[float] = deque(maxlen=_RESERVOIR)
        self.decisions: Counter = Counter()
        self.gauges: Dict[str, float] = {}
        self.last_call_at: Optional[str] = None
        self.last_error: Optional[str] = None
        self.last_error_at: Optional[str] = None


_LOCK = threading.RLock()
_STATS: Dict[str, _AgentStats] = {}


def _stats(agent_id: str) -> _AgentStats:
    stats = _STATS.get(agent_id)
    if stats is None:
        stats = _AgentStats()
        _STATS[agent_id] = stats
    return stats


def _percentile(sorted_values: List[float], pct: float) -> Optional[float]:
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = (pct / 100.0) * (len(sorted_values) - 1)
    low = int(rank)
    high = min(low + 1, len(sorted_values) - 1)
    frac = rank - low
    return sorted_values[low] + (sorted_values[high] - sorted_values[low]) * frac


# ---------------------------------------------------------------------------
# Recording
# ---------------------------------------------------------------------------

def record(agent_id: str, latency_ms: float, *, error: Optional[str] = None,
           decision: Optional[str] = None) -> None:
    """Record one completed call. Never raises."""
    try:
        with _LOCK:
            stats = _stats(agent_id)
            stats.calls += 1
            stats.latency.append(float(latency_ms))
            stats.last_call_at = _now_iso()
            if error is not None:
                stats.errors += 1
                stats.last_error = str(error)[:300]
                stats.last_error_at = stats.last_call_at
            if decision is not None:
                label = str(decision)[:80]
                if label in stats.decisions or len(stats.decisions) < _MAX_DECISION_LABELS:
                    stats.decisions[label] += 1
                else:
                    stats.decisions['_other'] += 1
    except Exception as exc:  # noqa: BLE001
        logger.debug("agent metrics record failed for %s: %s", agent_id, exc)


def set_gauge(agent_id: str, name: str, value: float) -> None:
    """Set a point-in-time gauge (e.g. queue_depth). Never raises."""
    try:
        with _LOCK:
            _stats(agent_id).gauges[str(name)] = float(value)
    except Exception as exc:  # noqa: BLE001
        logger.debug("agent metrics gauge failed for %s: %s", agent_id, exc)


def _enter(agent_id: str) -> None:
    with _LOCK:
        _stats(agent_id).in_flight += 1


def _exit(agent_id: str) -> None:
    with _LOCK:
        stats = _stats(agent_id)
        stats.in_flight = max(0, stats.in_flight - 1)


# ---------------------------------------------------------------------------
# Snapshots
# ---------------------------------------------------------------------------

def snapshot(agent_id: str) -> Dict[str, Any]:
    with _LOCK:
        stats = _STATS.get(agent_id)
        if stats is None:
            return {'calls': 0, 'errors': 0, 'error_rate': 0.0, 'in_flight': 0,
                    'latency_ms': {'count': 0, 'p50': None, 'p95': None, 'max': None},
                    'decisions': {}, 'gauges': {}, 'last_call_at': None,
                    'last_error': None, 'last_error_at': None}
        values = sorted(stats.latency)
        return {
            'calls': stats.calls,
            'errors': stats.errors,
            'error_rate': round(stats.errors / stats.calls, 4) if stats.calls else 0.0,
            'in_flight': stats.in_flight,
            'latency_ms': {
                'count': len(values),
                'p50': round(_percentile(values, 50), 2) if values else None,
                'p95': round(_percentile(values, 95), 2) if values else None,
                'max': round(values[-1], 2) if values else None,
            },
            'decisions': dict(stats.decisions),
            'gauges': dict(stats.gauges),
            'last_call_at': stats.last_call_at,
            'last_error': stats.last_error,
            'last_error_at': stats.last_error_at,
        }


def snapshot_all() -> Dict[str, Dict[str, Any]]:
    with _LOCK:
        ids = sorted(_STATS.keys())
    return {agent_id: snapshot(agent_id) for agent_id in ids}


def public_snapshot_all() -> Dict[str, Dict[str, Any]]:
    """Snapshot for unauthenticated surfaces: counts and latency only.

    Drops ``last_error``/``last_error_at`` (raw exception text can carry
    customer, claim or document ids) and the decision-label counts, both of
    which stay on the admin agent-health view.
    """
    return {
        agent_id: {key: value for key, value in snap.items() if key in _PUBLIC_FIELDS}
        for agent_id, snap in snapshot_all().items()
    }


def reset(agent_id: Optional[str] = None) -> None:
    """Clear metrics (tests / operator reset). Does not touch agent state."""
    with _LOCK:
        if agent_id is None:
            _STATS.clear()
        else:
            _STATS.pop(agent_id, None)


# ---------------------------------------------------------------------------
# SLO check
# ---------------------------------------------------------------------------

def check_slo(*, p95_ms: Optional[float] = None, error_rate: Optional[float] = None,
              min_calls: Optional[int] = None) -> List[Dict[str, Any]]:
    """Return SLO breaches across agents with enough samples.

    Thresholds default to ``PHINS_AGENT_SLO_P95_MS`` / ``PHINS_AGENT_SLO_ERROR_RATE``
    and agents with fewer than ``PHINS_AGENT_SLO_MIN_CALLS`` calls are skipped
    so a single slow cold start does not page anyone.
    """
    p95_limit = _DEFAULT_SLO_P95_MS if p95_ms is None else float(p95_ms)
    err_limit = _DEFAULT_SLO_ERROR_RATE if error_rate is None else float(error_rate)
    floor = _DEFAULT_SLO_MIN_CALLS if min_calls is None else int(min_calls)
    breaches: List[Dict[str, Any]] = []
    for agent_id, snap in snapshot_all().items():
        if snap['calls'] < floor:
            continue
        p95 = snap['latency_ms'].get('p95')
        if p95 is not None and p95 > p95_limit:
            breaches.append({'agent_id': agent_id, 'kind': 'latency_p95',
                             'value': p95, 'limit': p95_limit})
        if snap['error_rate'] > err_limit:
            breaches.append({'agent_id': agent_id, 'kind': 'error_rate',
                             'value': snap['error_rate'], 'limit': err_limit})
    return breaches


# ---------------------------------------------------------------------------
# Decorator
# ---------------------------------------------------------------------------

def _extract_decision(result: Any, decision_key: Optional[str],
                      decision_fn: Optional[Callable[[Any], Any]]) -> Optional[str]:
    """Read a decision label from a result without mutating it."""
    try:
        if decision_fn is not None:
            label = decision_fn(result)
        elif decision_key is not None:
            if isinstance(result, dict):
                label = result.get(decision_key)
            else:
                label = getattr(result, decision_key, None)
        else:
            return None
        if label is None:
            return None
        return str(getattr(label, 'value', label))
    except Exception:  # noqa: BLE001 - label extraction is best-effort
        return None


def instrument_agent(agent_id: str, *, decision_key: Optional[str] = None,
                     decision_fn: Optional[Callable[[Any], Any]] = None):
    """Decorate an agent entry point to record calls, latency, errors and
    (optionally) a decision label. Works for functions and methods.

    The wrapped callable's arguments and return value pass through untouched;
    exceptions propagate unchanged after being counted.
    """
    def _decorate(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def _wrapped(*args, **kwargs):
            _enter(agent_id)
            started = time.perf_counter()
            try:
                result = fn(*args, **kwargs)
            except BaseException as exc:
                elapsed = (time.perf_counter() - started) * 1000.0
                _exit(agent_id)
                record(agent_id, elapsed, error=f"{type(exc).__name__}: {exc}")
                raise
            elapsed = (time.perf_counter() - started) * 1000.0
            _exit(agent_id)
            record(agent_id, elapsed,
                   decision=_extract_decision(result, decision_key, decision_fn))
            return result
        _wrapped.__phins_agent_id__ = agent_id  # type: ignore[attr-defined]
        return _wrapped
    return _decorate


__all__ = [
    'record', 'set_gauge', 'snapshot', 'snapshot_all', 'public_snapshot_all',
    'reset', 'check_slo', 'instrument_agent',
]
