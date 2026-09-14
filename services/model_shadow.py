"""
Model shadowing for rule-based agents (B1).

The bots decide with deterministic rules. A learned model, when an artifact
exists in the :mod:`services.ai_model_registry`, is consulted *alongside* the
rules and its score is logged next to the rule score so operators can see
whether the two agree — it never changes the decision. ``divergence`` is
``|model_score - rule_score|``; when its rolling p95 for a model exceeds
``PHINS_AI_DRIFT_THRESHOLD`` a drift alert is written to the audit log once
per breach episode (re-armed when the window recovers).

Usage::

    shadow = shadow_score('uw_scorer', features, rule_score)
    decision_log.record(..., output={..., **shadow.as_log_fields()})

All entry points are best-effort: registry or model failures degrade to
``model_score=None`` and the caller carries on with the rule decision.
"""

from __future__ import annotations

import logging
import os
import threading
from collections import deque
from dataclasses import dataclass
from typing import Any, Deque, Dict, Optional

logger = logging.getLogger('phins.model_shadow')

RULES_VERSION = 'rules-v1'


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class ShadowResult:
    """Outcome of one shadow consultation. ``rule_score`` is authoritative."""

    model_name: str
    rule_score: float
    model_score: Optional[float]
    model_version: str
    divergence: Optional[float]
    drift_alert: bool = False

    @property
    def consulted(self) -> bool:
        return self.model_score is not None

    def as_log_fields(self) -> Dict[str, Any]:
        """Fields to merge into a decision-log ``output`` payload."""
        return {
            'rule_score': round(self.rule_score, 4),
            'model_score': None if self.model_score is None else round(self.model_score, 4),
            'model_version': self.model_version,
            'divergence': None if self.divergence is None else round(self.divergence, 4),
            'drift_alert': bool(self.drift_alert),
        }


class DriftMonitor:
    """Rolling per-model divergence window with a p95 drift alarm.

    ``threshold`` — p95 divergence above which the model is drifting;
    ``window`` — number of recent samples kept per model;
    ``min_samples`` — no alarm before this many samples (avoids alerting on
    the first handful of scores).
    """

    def __init__(self, threshold: Optional[float] = None, window: Optional[int] = None,
                 min_samples: Optional[int] = None):
        self.threshold = threshold if threshold is not None else _env_float('PHINS_AI_DRIFT_THRESHOLD', 0.25)
        self.window = max(2, window if window is not None else _env_int('PHINS_AI_DRIFT_WINDOW', 200))
        self.min_samples = max(1, min_samples if min_samples is not None else _env_int('PHINS_AI_DRIFT_MIN_SAMPLES', 20))
        self._samples: Dict[str, Deque[float]] = {}
        self._breached: Dict[str, bool] = {}
        self._lock = threading.Lock()

    def p95(self, model_name: str) -> Optional[float]:
        with self._lock:
            window = self._samples.get(model_name)
            if not window:
                return None
            ordered = sorted(window)
        idx = min(len(ordered) - 1, max(0, int(round(0.95 * (len(ordered) - 1)))))
        return ordered[idx]

    def record(self, model_name: str, divergence: float) -> bool:
        """Add a sample; return True exactly when a new breach episode starts."""
        with self._lock:
            window = self._samples.setdefault(model_name, deque(maxlen=self.window))
            window.append(float(divergence))
            if len(window) < self.min_samples:
                return False
            ordered = sorted(window)
            idx = min(len(ordered) - 1, max(0, int(round(0.95 * (len(ordered) - 1)))))
            p95 = ordered[idx]
            was = self._breached.get(model_name, False)
            now = p95 > self.threshold
            self._breached[model_name] = now
            return now and not was

    def status(self) -> Dict[str, Any]:
        with self._lock:
            names = list(self._samples)
        out = {}
        for name in names:
            with self._lock:
                n = len(self._samples.get(name, ()))
                breached = self._breached.get(name, False)
            out[name] = {'samples': n, 'p95': self.p95(name), 'breached': breached}
        return {'threshold': self.threshold, 'window': self.window,
                'min_samples': self.min_samples, 'models': out}

    def reset(self) -> None:
        with self._lock:
            self._samples.clear()
            self._breached.clear()


_monitor: Optional[DriftMonitor] = None
_monitor_lock = threading.Lock()


def get_drift_monitor() -> DriftMonitor:
    global _monitor
    with _monitor_lock:
        if _monitor is None:
            _monitor = DriftMonitor()
        return _monitor


def reset_drift_monitor() -> None:
    global _monitor
    with _monitor_lock:
        _monitor = None


def _emit_drift_alert(agent_id: str, model_name: str, model_version: str, monitor: DriftMonitor,
                      entity_id: Optional[str]) -> None:
    payload = {
        'agent_id': agent_id,
        'model_name': model_name,
        'model_version': model_version,
        'p95_divergence': monitor.p95(model_name),
        'threshold': monitor.threshold,
        'window': monitor.window,
    }
    logger.warning("AI model drift: %s", payload)
    try:
        from services.ai_audit_bridge import record_ai_audit
        record_ai_audit('ai_model_drift', 'ai_model', model_name, payload,
                        username=agent_id, success=False)
    except Exception as exc:  # audit is best-effort here; the warning above already fired
        logger.debug("drift audit skipped: %s", exc)


def shadow_score(model_name: str, features: Dict[str, Any], rule_score: float, *,
                 agent_id: str = 'ai_engine', entity_id: Optional[str] = None,
                 registry=None, monitor: Optional[DriftMonitor] = None) -> ShadowResult:
    """Consult ``model_name`` and compare with the rule score. Never raises.

    Returns a :class:`ShadowResult`; when no artifact is registered (the
    default everywhere today) ``model_score`` is ``None`` and
    ``model_version`` is ``rules-v1``.
    """
    try:
        rule = float(rule_score)
    except (TypeError, ValueError):
        rule = 0.0
    try:
        if registry is None:
            from services.ai_model_registry import get_model_registry
            registry = get_model_registry()
        handle = registry.get_model(model_name)
    except Exception as exc:
        logger.debug("model registry unavailable for %s: %s", model_name, exc)
        handle = None
    if handle is None:
        return ShadowResult(model_name, rule, None, RULES_VERSION, None)
    try:
        score = handle.score(dict(features))
        version = getattr(handle, 'registry_id', model_name)
    except Exception as exc:
        logger.warning("shadow model %s failed: %s", model_name, exc)
        return ShadowResult(model_name, rule, None, RULES_VERSION, None)
    if score is None:
        return ShadowResult(model_name, rule, None, RULES_VERSION, None)
    score = min(1.0, max(0.0, float(score)))
    divergence = abs(score - rule)
    monitor = monitor or get_drift_monitor()
    alert = monitor.record(model_name, divergence)
    if alert:
        _emit_drift_alert(agent_id, model_name, version, monitor, entity_id)
    return ShadowResult(model_name, rule, score, version, divergence, alert)


__all__ = ['DriftMonitor', 'RULES_VERSION', 'ShadowResult', 'get_drift_monitor',
           'reset_drift_monitor', 'shadow_score']
