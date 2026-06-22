"""
AI Audit Bridge (durability for AI-1, the keystone)
===================================================
Wires the append-only AI decision log (``services/ai_decision_log.py``) and
other AI surfaces to the durable ``audit_logs`` table so that automated
decisions, human overrides, and money-adjacent AI events survive process
restarts and are visible to compliance -- not just held in volatile process
memory.

Design contract (matches ``ai_decision_log`` semantics):
- **Best-effort, never fatal.** A database failure must never raise into the
  live AI decision/trade path. The in-memory log stays the runtime source of
  truth; this DB mirror is an *additive* durability layer.
- **Additive, append-only.** Each call writes a new ``audit_logs`` row. Nothing
  here mutates or deletes prior rows.
- **Opt-in by environment.** The mirror only does real work when the platform
  runs with a database (``USE_DATABASE``). In in-memory/demo/test runtimes the
  ``DatabaseManager`` simply yields nothing useful and the call is a no-op.
"""

import json
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger('phins.ai_audit_bridge')

# Audit action labels (kept stable for downstream querying/reporting).
AI_DECISION_ACTION = 'ai_decision'
AI_DECISION_OVERRIDE_ACTION = 'ai_decision_override'

_wired = False


def record_ai_audit(
    action: str,
    entity_type: Optional[str],
    entity_id: Optional[str],
    details: Dict[str, Any],
    username: str = 'ai_engine',
    customer_id: Optional[str] = None,
    success: bool = True,
) -> bool:
    """Write a single durable ``audit_logs`` row for an AI event.

    Reusable by any AI surface that needs audit parity with the rest of the
    platform (decision log, trading automation, claims bot). Never raises;
    returns True only when a row was actually persisted.
    """
    try:
        from database.manager import DatabaseManager
    except Exception:  # database layer unavailable (pure in-memory build)
        return False
    try:
        payload = json.dumps(details, default=str) if details is not None else None
        with DatabaseManager() as db:
            row = db.audit.log_action(
                username=username,
                action=action,
                entity_type=entity_type or 'ai',
                entity_id=entity_id,
                details=payload,
                customer_id=customer_id,
                success=success,
            )
        return row is not None
    except Exception as exc:  # never propagate into the AI path
        logger.warning("AI audit mirror failed (non-fatal): %s", exc)
        return False


def _persist_decision_to_audit(record: Dict[str, Any]) -> None:
    """Persister handed to ``AIDecisionLog.set_db_persister``.

    Mirrors each decision (and each later override snapshot) into the durable
    audit store. Overrides are written as their own ``ai_decision_override``
    row keyed by the same ``decision_id`` -- consistent with the decision log's
    append-only override model.
    """
    try:
        is_override = record.get('human_override') is not None
        action = AI_DECISION_OVERRIDE_ACTION if is_override else AI_DECISION_ACTION
        username = (record.get('overridden_by') or 'human') if is_override else 'ai_engine'
        customer_id = record.get('entity_id') if record.get('entity_type') == 'customer' else None
        record_ai_audit(
            action=action,
            entity_type=record.get('entity_type') or 'ai_decision',
            entity_id=record.get('entity_id') or record.get('decision_id'),
            details=record,
            username=username,
            customer_id=customer_id,
        )
    except Exception as exc:  # never propagate into the decision path
        logger.warning("AI decision audit persister failed (non-fatal): %s", exc)


def wire_ai_decision_log(force: bool = False) -> bool:
    """Attach the durable audit persister to the global AI decision log.

    Idempotent: safe to call once at server startup. Returns True when the
    persister is attached (or was already attached). Never raises.
    """
    global _wired
    if _wired and not force:
        return True
    try:
        from services.ai_decision_log import get_ai_decision_log
        get_ai_decision_log().set_db_persister(_persist_decision_to_audit)
        _wired = True
        logger.info("AI decision log wired to durable audit store")
        return True
    except Exception as exc:
        logger.warning("Could not wire AI decision log persistence: %s", exc)
        return False


def is_wired() -> bool:
    """Return True if the AI decision log durable mirror has been wired."""
    return _wired


__all__ = [
    'record_ai_audit',
    'wire_ai_decision_log',
    'is_wired',
    'AI_DECISION_ACTION',
    'AI_DECISION_OVERRIDE_ACTION',
]
