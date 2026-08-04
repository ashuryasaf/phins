"""
PHINS Assessment Record Service (loop closure, phase 1)
=======================================================

First-class, durable assessment records: every time a scoring engine produces
a risk/fraud assessment that matters (underwriting risk, claims fraud,
customer risk), a record is written here so the platform can

- audit which score existed at decision time,
- compare human decisions against engine recommendations
  (``decision_aligned``), accumulating the labeled dataset needed for any
  future model training,
- trend scores over time per customer / subject.

Data-integrity contract:

- **Append-only.** Assessment payloads (score, level, recommendation, details)
  are never mutated after creation. A decision is attached as *new fields*
  (``decided_by``/``decision``/``decision_aligned``) exactly once; the engine
  output is never rewritten.
- **Tamper-evident.** Each record carries a ``payload_sha256`` over its
  canonical engine-output payload, verifiable at any time via
  :meth:`AssessmentRecordService.verify_record`.
- **Best-effort durability, never fatal.** Records always land in the bounded
  in-memory store (works in test/demo runtimes with zero configuration) and
  are mirrored to the ``assessment_records`` table when the platform runs
  DB-backed. Persistence failures never raise into the decision path.
- **Advisory only.** Nothing here moves money or changes policy/claim state.

Every recorded assessment is also mirrored into the AI decision log (AI-1)
so calibration and override reporting see a single stream.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sys
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("phins.assessment_records")

# Bound the in-memory store so a runaway caller cannot exhaust process memory.
MAX_RECORDS_IN_MEMORY = int(os.environ.get("PHINS_MAX_ASSESSMENT_RECORDS", 20000))

ENGINE_VERSION = "rules-v1"

VALID_SUBJECT_TYPES = {"underwriting_application", "claim", "customer"}

# recommendation → decisions considered aligned with it. Used to label whether
# the human action agreed with the engine (the training signal). Covers the
# underwriting scorer labels (services/underwriting_risk_scoring.py) and the
# claims bot ClaimDecisionType values (services/claims_bot_service.py).
_APPROVING = {"approved", "auto_approved", "paid"}
_ALIGNMENT_MAP = {
    # Underwriting risk scorer
    "auto_approve": _APPROVING,
    "approve_standard": _APPROVING,
    "approve_with_loading": _APPROVING,
    "approve_with_exclusions": _APPROVING,
    "refer_senior_uw": {"referred"},
    "decline": {"rejected"},
    # Claims bot
    "approve_full": _APPROVING,
    "approve_partial": _APPROVING,
    "deny_fraud_suspected": {"rejected"},
    "deny_not_covered": {"rejected"},
    "deny_hidden_condition": {"rejected"},
    "refer_investigation": {"referred", "rejected"},
    "refer_medical_review": {"referred"},
    "pending_more_info": {"referred"},
    # Generic labels used by other engines
    "approve": _APPROVING,
    "approve_conditional": _APPROVING,
    "approve_with_conditions": _APPROVING,
    "deny": {"rejected"},
    "reject": {"rejected"},
    "refer": {"referred"},
    "refer_manual": {"referred"},
    "refer_manual_review": {"referred"},
    "manual_review": {"referred"},
    "investigate": {"referred", "rejected"},
}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _db_enabled() -> bool:
    """Mirror to the DB only when the platform effectively runs DB-backed.

    Defers to the portal's runtime flags when the server module is loaded
    (``USE_DATABASE`` can be disabled at runtime after a connection failure);
    falls back to the env var for isolated unit use.
    """
    portal = sys.modules.get("web_portal.server")
    if portal is not None:
        return bool(getattr(portal, "USE_DATABASE", False)
                    and getattr(portal, "database_enabled", False))
    return os.environ.get("USE_DATABASE", "true").lower() not in ("false", "0", "no")


def _canonical(payload: Dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def _payload_checksum(record: Dict[str, Any]) -> str:
    """SHA-256 over the immutable engine-output portion of a record."""
    body = {
        "record_id": record.get("record_id"),
        "customer_id": record.get("customer_id"),
        "subject_type": record.get("subject_type"),
        "subject_id": record.get("subject_id"),
        "assessment_type": record.get("assessment_type"),
        "score": record.get("score"),
        "level": record.get("level"),
        "recommendation": record.get("recommendation"),
        "engine": record.get("engine"),
        "engine_version": record.get("engine_version"),
        "details": record.get("details"),
        "created_at": record.get("created_at"),
    }
    return hashlib.sha256(_canonical(body).encode("utf-8")).hexdigest()


def compute_alignment(recommendation: Optional[str], decision: Optional[str]) -> Optional[bool]:
    """Whether a human decision agrees with the engine recommendation.

    Returns ``None`` when either side is missing or the recommendation is not
    a known label (no training signal rather than a wrong one).
    """
    rec = str(recommendation or "").strip().lower()
    dec = str(decision or "").strip().lower()
    if not rec or not dec:
        return None
    aligned_decisions = _ALIGNMENT_MAP.get(rec)
    if aligned_decisions is None:
        return None
    return dec in aligned_decisions


class AssessmentRecordService:
    """Thread-safe append-only assessment record store with DB write-through."""

    def __init__(self):
        self._records: List[Dict[str, Any]] = []
        self._index: Dict[str, int] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    def record_assessment(
        self,
        *,
        subject_type: str,
        subject_id: str,
        assessment_type: str,
        customer_id: Optional[str] = None,
        score: Optional[float] = None,
        level: Optional[str] = None,
        recommendation: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        engine: str = "rule_engine",
        engine_version: str = ENGINE_VERSION,
        decided_by: Optional[str] = None,
        decision: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Append an immutable assessment record; returns the stored dict.

        Never raises into the caller: on internal failure a record dict with
        ``record_id == ""`` is returned so decision paths keep working.
        """
        try:
            record_id = f"ASMT-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8].upper()}"
            try:
                numeric_score = round(float(score), 6) if score is not None else None
            except (TypeError, ValueError):
                numeric_score = None
            record: Dict[str, Any] = {
                "record_id": record_id,
                "customer_id": str(customer_id or "").strip() or None,
                "subject_type": str(subject_type or "").strip(),
                "subject_id": str(subject_id or "").strip(),
                "assessment_type": str(assessment_type or "").strip(),
                "score": numeric_score,
                "level": str(level or "").strip() or None,
                "recommendation": str(recommendation or "").strip() or None,
                "engine": engine,
                "engine_version": engine_version,
                "details": dict(details) if details else {},
                "created_at": _utc_now_iso(),
                "decided_by": None,
                "decision": None,
                "decision_aligned": None,
            }
            record["payload_sha256"] = _payload_checksum(record)
            if decision:
                record["decided_by"] = str(decided_by or "").strip() or None
                record["decision"] = str(decision).strip().lower()
                record["decision_aligned"] = compute_alignment(
                    record["recommendation"], record["decision"]
                )

            with self._lock:
                self._records.append(record)
                self._index[record_id] = len(self._records) - 1
                if len(self._records) > MAX_RECORDS_IN_MEMORY:
                    # Drop the oldest overflow and rebuild the index. The DB
                    # copy (when enabled) retains full history.
                    drop = len(self._records) - MAX_RECORDS_IN_MEMORY
                    self._records = self._records[drop:]
                    self._index = {
                        r["record_id"]: i for i, r in enumerate(self._records)
                    }

            self._persist(record)
            self._mirror_to_decision_log(record)
            return dict(record)
        except Exception as exc:  # never propagate into decision paths
            logger.warning("Assessment record write failed: %s", exc)
            return {"record_id": "", "error": str(exc)}

    def attach_decision(
        self,
        record_id: str,
        *,
        decided_by: str,
        decision: str,
        reason: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Attach a human/automation decision to an existing assessment.

        Additive only: fills the decision fields (which started null) and never
        rewrites the engine output. Returns the updated record, or ``None``
        when the record is unknown.
        """
        try:
            dec = str(decision or "").strip().lower()
            with self._lock:
                pos = self._index.get(record_id)
                if pos is None:
                    return None
                record = self._records[pos]
                record["decided_by"] = str(decided_by or "").strip() or None
                record["decision"] = dec
                record["decision_aligned"] = compute_alignment(
                    record.get("recommendation"), dec
                )
                snapshot = dict(record)

            self._persist(snapshot, update_decision_only=True)

            # Disagreements are the highest-value training signal: mirror them
            # as overrides in the AI decision log.
            if snapshot.get("decision_aligned") is False:
                try:
                    from services.ai_decision_log import get_ai_decision_log
                    decision_log_id = snapshot.get("ai_decision_id")
                    if decision_log_id:
                        get_ai_decision_log().record_override(
                            decision_log_id,
                            human_decision=dec,
                            reason=reason,
                            overridden_by=decided_by,
                        )
                except Exception:
                    pass
            return snapshot
        except Exception as exc:
            logger.warning("Assessment decision attach failed: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def get_record(self, record_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            pos = self._index.get(record_id)
            if pos is not None:
                return dict(self._records[pos])
        return self._db_get(record_id)

    def latest_for_subject(
        self, subject_type: str, subject_id: str
    ) -> Optional[Dict[str, Any]]:
        with self._lock:
            for record in reversed(self._records):
                if (record["subject_type"] == subject_type
                        and record["subject_id"] == subject_id):
                    return dict(record)
        if _db_enabled():
            try:
                from database.manager import DatabaseManager
                with DatabaseManager() as db:
                    row = db.assessment_records.latest_for_subject(
                        subject_type, subject_id
                    )
                    return row.to_dict() if row else None
            except Exception:
                pass
        return None

    def list_records(
        self,
        *,
        customer_id: Optional[str] = None,
        subject_type: Optional[str] = None,
        subject_id: Optional[str] = None,
        assessment_type: Optional[str] = None,
        page: int = 1,
        page_size: int = 50,
    ) -> Dict[str, Any]:
        """Paginated listing shaped like the platform convention."""
        page = max(1, int(page))
        page_size = max(1, min(200, int(page_size)))

        with self._lock:
            items = list(self._records)
        if customer_id:
            items = [r for r in items if r.get("customer_id") == customer_id]
        if subject_type:
            items = [r for r in items if r.get("subject_type") == subject_type]
        if subject_id:
            items = [r for r in items if r.get("subject_id") == subject_id]
        if assessment_type:
            items = [r for r in items if r.get("assessment_type") == assessment_type]
        items = items[::-1]  # newest first
        total = len(items)
        start = (page - 1) * page_size
        page_items = [dict(r) for r in items[start:start + page_size]]
        return {
            "items": page_items,
            "page": page,
            "page_size": page_size,
            "total": total,
        }

    def summary(self) -> Dict[str, Any]:
        """Aggregates: counts, decision coverage, engine/human agreement rate."""
        with self._lock:
            items = list(self._records)
        by_type: Dict[str, int] = {}
        decided = 0
        aligned = 0
        misaligned = 0
        for r in items:
            by_type[r["assessment_type"]] = by_type.get(r["assessment_type"], 0) + 1
            if r.get("decision"):
                decided += 1
                if r.get("decision_aligned") is True:
                    aligned += 1
                elif r.get("decision_aligned") is False:
                    misaligned += 1
        total = len(items)
        labeled = aligned + misaligned
        return {
            "total_assessments": total,
            "by_type": by_type,
            "with_decision": decided,
            "aligned_decisions": aligned,
            "misaligned_decisions": misaligned,
            "agreement_rate": round(aligned / labeled * 100, 2) if labeled else None,
        }

    def verify_record(self, record_id: str) -> Optional[bool]:
        """Recompute the integrity checksum for a record. ``None`` = not found."""
        record = self.get_record(record_id)
        if not record:
            return None
        return _payload_checksum(record) == record.get("payload_sha256")

    def reset(self) -> None:
        """Drop in-memory state (test isolation). Does not touch the DB."""
        with self._lock:
            self._records = []
            self._index = {}

    # ------------------------------------------------------------------
    # Internal: durability + decision-log mirror (best-effort, never fatal)
    # ------------------------------------------------------------------

    def _persist(self, record: Dict[str, Any], update_decision_only: bool = False) -> None:
        if not _db_enabled():
            return
        try:
            from database.manager import DatabaseManager
            with DatabaseManager() as db:
                if update_decision_only:
                    updated = db.assessment_records.update_decision(
                        record["record_id"],
                        decided_by=record.get("decided_by") or "",
                        decision=record.get("decision") or "",
                        decision_aligned=record.get("decision_aligned"),
                    )
                    if updated is not None:
                        db.commit()
                        return
                    # Fall through: row missing (e.g. written before DB came
                    # up) — create it whole so durable history stays complete.
                from database.models import AssessmentRecord
                db.assessment_records.create(AssessmentRecord(
                    id=record["record_id"],
                    customer_id=record.get("customer_id"),
                    subject_type=record.get("subject_type"),
                    subject_id=record.get("subject_id"),
                    assessment_type=record.get("assessment_type"),
                    score=record.get("score"),
                    level=record.get("level"),
                    recommendation=record.get("recommendation"),
                    engine=record.get("engine") or "rule_engine",
                    engine_version=record.get("engine_version"),
                    details_json=json.dumps(record.get("details") or {}, default=str),
                    payload_sha256=record.get("payload_sha256"),
                    decided_by=record.get("decided_by"),
                    decision=record.get("decision"),
                    decision_aligned=record.get("decision_aligned"),
                ))
                db.commit()
        except Exception as exc:
            logger.warning(
                "Assessment record durable write failed (non-fatal, in-memory "
                "copy retained): %s", exc,
            )

    def _db_get(self, record_id: str) -> Optional[Dict[str, Any]]:
        if not _db_enabled():
            return None
        try:
            from database.manager import DatabaseManager
            with DatabaseManager() as db:
                row = db.assessment_records.get_by_id(record_id)
                return row.to_dict() if row else None
        except Exception:
            return None

    def _mirror_to_decision_log(self, record: Dict[str, Any]) -> None:
        try:
            from services.ai_decision_log import get_ai_decision_log
            decision_id = get_ai_decision_log().record(
                decision_type=record["assessment_type"],
                output={
                    "score": record.get("score"),
                    "level": record.get("level"),
                    "recommendation": record.get("recommendation"),
                    "decision": record.get("decision"),
                },
                inputs={"assessment_record_id": record["record_id"]},
                entity_type=record.get("subject_type"),
                entity_id=record.get("subject_id"),
                model_version=record.get("engine_version") or ENGINE_VERSION,
                confidence=record.get("score"),
            )
            # Link back so a later contradicting decision can be recorded as a
            # human override against the same decision-log row. Stored as a
            # separate field (NOT inside ``details``) so the payload_sha256
            # integrity checksum computed at creation stays valid.
            if decision_id:
                with self._lock:
                    pos = self._index.get(record["record_id"])
                    if pos is not None:
                        self._records[pos]["ai_decision_id"] = decision_id
        except Exception as exc:
            logger.debug("Decision log mirror skipped: %s", exc)


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------

_service: Optional[AssessmentRecordService] = None


def get_assessment_record_service() -> AssessmentRecordService:
    global _service
    if _service is None:
        _service = AssessmentRecordService()
    return _service


def reset_assessment_record_service() -> None:
    """Reset the singleton (mainly for tests)."""
    global _service
    _service = None


__all__ = [
    "AssessmentRecordService",
    "get_assessment_record_service",
    "reset_assessment_record_service",
    "compute_alignment",
]
