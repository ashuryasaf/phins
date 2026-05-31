"""
PHINS AI Decision Log (AI-1, the keystone)
===========================================
Append-only record of every automated decision the AI agents make, plus any
human override that follows. This is the foundation that turns PHINS "AI" from
*interface* into *substance*: without a durable decision record there can be no
audit, no feedback loop, and no calibration (AI-2) or model training (AI-3).

Reference: ``docs/INVESTOR_AI_BI_OPTIMIZATION_REVIEW.md`` §4 (AI-1) and the
``model_decisions`` entity named in
``docs/health_marketplace_architecture.md``.

Data-integrity contract (non-negotiable):
- **Append-only.** A decision row's ``inputs`` and ``output`` are never mutated.
  A human override is recorded as *new fields linked by decision_id*, never by
  rewriting the original decision.
- **Advisory / reporting only.** This log is training and audit data. It must
  never be read back into a money posting; it does not move funds or change a
  policy/claim state by itself.
- **Best-effort, never fatal.** Recording must never raise into the caller. AI
  decisioning continues even if persistence is unavailable, so the log can never
  degrade the live decision path.

Storage:
- Always kept in a process-local append-only list (works in the in-memory and
  test runtimes with zero configuration).
- Optionally mirrored to the database when a repository is wired in via
  ``set_db_persister``; this keeps the module decoupled from SQLAlchemy and
  avoids a hard DB dependency in demo/test mode.
"""

import copy
import logging
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger('phins.ai_decision_log')


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class AIDecisionLog:
    """Thread-safe, append-only AI decision record."""

    def __init__(self):
        self._records: List[Dict[str, Any]] = []
        self._index: Dict[str, int] = {}  # decision_id -> position in _records
        self._lock = threading.Lock()
        # Optional DB mirror: a callable(record_dict) -> None. Best-effort.
        self._db_persister: Optional[Callable[[Dict[str, Any]], None]] = None

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    def set_db_persister(self, persister: Optional[Callable[[Dict[str, Any]], None]]) -> None:
        """Wire an optional best-effort database mirror.

        The persister receives the same dict stored in memory. Any exception it
        raises is swallowed (logged) so persistence can never break decisioning.
        """
        self._db_persister = persister

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def record(
        self,
        decision_type: str,
        output: Dict[str, Any],
        inputs: Optional[Dict[str, Any]] = None,
        entity_type: Optional[str] = None,
        entity_id: Optional[str] = None,
        model_version: str = 'rules-v1',
        confidence: Optional[float] = None,
        segment: Optional[str] = None,
    ) -> str:
        """Append an immutable decision record. Returns the decision_id.

        Never raises into the caller. If storing the decision fails, it logs and
        returns an empty string rather than a phantom id, so callers never
        reference a decision that was not actually recorded.
        """
        decision_id = f"AIDEC-{uuid.uuid4().hex[:16]}"
        try:
            record = {
                'decision_id': decision_id,
                'decision_type': decision_type,
                'entity_type': entity_type,
                'entity_id': entity_id,
                # Deep-copy so the append-only snapshot is fully detached from
                # the caller's mutable payload. A shallow ``dict(...)`` copy
                # leaves nested dicts/lists aliased, so later in-place edits to
                # ``application_data``/``claim_data`` would silently rewrite the
                # decision-time record and corrupt audit/calibration history.
                'inputs': copy.deepcopy(inputs) if inputs else {},
                'output': copy.deepcopy(output) if output else {},
                'model_version': model_version,
                'confidence': confidence,
                'segment': segment,
                'created_at': _utc_now_iso(),
                # Override fields stay null until/unless a human disagrees.
                'human_override': None,
                'override_reason': None,
                'overridden_by': None,
                'overridden_at': None,
            }
            with self._lock:
                # Append-only: records are retained for audit and calibration
                # and never dropped, so every decision_id stays resolvable for
                # overrides and threshold calibration.
                self._records.append(record)
                self._index[decision_id] = len(self._records) - 1
            self._mirror_to_db(record)
        except Exception as exc:  # never propagate
            logger.warning("AI decision log record failed: %s", exc)
            return ''
        return decision_id

    def record_override(
        self,
        decision_id: str,
        human_decision: str,
        reason: Optional[str] = None,
        overridden_by: Optional[str] = None,
    ) -> bool:
        """Attach a human override to a prior decision.

        This is *additive*: it fills the override fields (which started null) and
        never rewrites the original ``inputs``/``output``. Returns True if the
        decision was found.
        """
        try:
            with self._lock:
                pos = self._index.get(decision_id)
                if pos is None:
                    return False
                record = self._records[pos]
                record['human_override'] = human_decision
                record['override_reason'] = reason
                record['overridden_by'] = overridden_by
                record['overridden_at'] = _utc_now_iso()
                snapshot = dict(record)
            self._mirror_to_db(snapshot)
            return True
        except Exception as exc:
            logger.warning("AI decision override failed: %s", exc)
            return False

    def _mirror_to_db(self, record: Dict[str, Any]) -> None:
        if self._db_persister is None:
            return
        try:
            self._db_persister(dict(record))
        except Exception as exc:
            logger.warning("AI decision DB mirror failed (non-fatal): %s", exc)

    # ------------------------------------------------------------------
    # Reads (reporting / calibration inputs)
    # ------------------------------------------------------------------

    def recent(self, limit: int = 100, decision_type: Optional[str] = None) -> List[Dict[str, Any]]:
        with self._lock:
            items = list(self._records)
        if decision_type:
            items = [r for r in items if r['decision_type'] == decision_type]
        return items[-limit:][::-1]

    def all(self, decision_type: Optional[str] = None) -> List[Dict[str, Any]]:
        with self._lock:
            items = list(self._records)
        if decision_type:
            items = [r for r in items if r['decision_type'] == decision_type]
        return items

    def get(self, decision_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            pos = self._index.get(decision_id)
            return dict(self._records[pos]) if pos is not None else None

    def summary(self) -> Dict[str, Any]:
        """Aggregate view: counts by type/outcome and override (disagreement) rate."""
        with self._lock:
            items = list(self._records)
        by_type: Dict[str, int] = {}
        by_outcome: Dict[str, int] = {}
        overrides = 0
        for r in items:
            by_type[r['decision_type']] = by_type.get(r['decision_type'], 0) + 1
            outcome = str(r.get('output', {}).get('decision', 'unknown'))
            by_outcome[outcome] = by_outcome.get(outcome, 0) + 1
            if r.get('human_override') is not None:
                overrides += 1
        total = len(items)
        return {
            'total_decisions': total,
            'by_type': by_type,
            'by_outcome': by_outcome,
            'human_overrides': overrides,
            'override_rate': round((overrides / total * 100), 2) if total else 0.0,
        }

    def clear(self) -> None:
        """Reset the in-memory log (test isolation / new period). Does not touch DB."""
        with self._lock:
            self._records = []
            self._index = {}


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------

_ai_decision_log: Optional[AIDecisionLog] = None


def get_ai_decision_log() -> AIDecisionLog:
    global _ai_decision_log
    if _ai_decision_log is None:
        _ai_decision_log = AIDecisionLog()
    return _ai_decision_log


__all__ = ['AIDecisionLog', 'get_ai_decision_log']
