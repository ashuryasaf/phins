"""
PHINS BI KPI Snapshot Service (BI-3)
====================================

Durable, append-only daily/on-demand snapshots of the executive KPI set so
the platform accumulates real trend history instead of recomputing point-in-
time aggregates that are immediately discarded. This is the prerequisite for
any honest forecasting or trend analytics.

Data-integrity contract:

- **Append-only.** Snapshots are never mutated or deleted by the service
  (test-only ``reset`` clears the in-memory copy).
- **Tamper-evident.** Every snapshot carries a ``record_sha256`` over its
  canonical payload.
- **Durable, zero-config.** Snapshots append to a JSONL file under
  ``PHINS_BI_SNAPSHOT_DIR`` (default ``data/bi_snapshots``) and hydrate on
  startup; a write failure never raises into the caller.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("phins.bi_snapshots")

MAX_SNAPSHOTS_IN_MEMORY = int(os.environ.get("PHINS_MAX_BI_SNAPSHOTS", 3660))


def _resolve_snapshot_dir() -> str:
    configured = os.environ.get("PHINS_BI_SNAPSHOT_DIR", "").strip()
    if configured:
        return configured
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "data", "bi_snapshots")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical(payload: Dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


# KPIs extracted from the executive dashboard into flat, trendable metrics.
# Paths are (dashboard_section, key) pairs matching
# BIAnalyticsService._compute_executive_dashboard, resolved defensively.
_METRIC_PATHS = {
    "total_customers": ("summary", "total_customers"),
    "active_customers": ("summary", "active_customers"),
    "total_policies": ("summary", "total_policies"),
    "active_policies": ("summary", "active_policies"),
    "monthly_revenue": ("summary", "monthly_revenue"),
    "annual_revenue_projection": ("summary", "annual_revenue_projection"),
    "total_assets": ("financial", "total_assets"),
    "total_liabilities": ("financial", "total_liabilities"),
    "net_worth": ("financial", "net_worth"),
    "claims_reserve": ("financial", "claims_reserve"),
    "outstanding_receivables": ("financial", "outstanding_receivables"),
    "total_coverage": ("financial", "total_coverage"),
    "loss_ratio": ("financial", "loss_ratio"),
    "total_claims": ("claims", "total"),
    "claims_total_claimed": ("claims", "total_claimed"),
    "claims_total_paid": ("claims", "total_paid"),
    "claims_approval_rate": ("claims", "approval_rate"),
    "financial_health_score": ("health_scores", "financial_health"),
    "operational_health_score": ("health_scores", "operational_health"),
    "overall_health_score": ("health_scores", "overall_health"),
}


def extract_kpi_metrics(dashboard: Dict[str, Any]) -> Dict[str, Any]:
    """Flatten the executive dashboard into a stable metric dict.

    Missing sections/keys become ``None`` (never fabricated) so a metric's
    trend accurately reflects when it started being measured.
    """
    metrics: Dict[str, Any] = {}
    dashboard = dashboard or {}
    for metric, (section, key) in _METRIC_PATHS.items():
        sec = dashboard.get(section)
        metrics[metric] = sec.get(key) if isinstance(sec, dict) else None
    return metrics


class BISnapshotService:
    """Thread-safe append-only KPI snapshot store (memory + JSONL file)."""

    def __init__(self, snapshot_dir: Optional[str] = None):
        self._dir = snapshot_dir or _resolve_snapshot_dir()
        self._path = os.path.join(self._dir, "snapshots.jsonl")
        self._snapshots: List[Dict[str, Any]] = []
        self._lock = threading.Lock()
        self._load_from_disk()

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    def capture_snapshot(
        self,
        dashboard: Dict[str, Any],
        *,
        source: str = "manual",
    ) -> Dict[str, Any]:
        """Persist a KPI snapshot extracted from an executive dashboard."""
        record = {
            "snapshot_id": f"BISNAP-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8].upper()}",
            "captured_at": _utc_now_iso(),
            "source": source,
            "metrics": extract_kpi_metrics(dashboard),
        }
        record["record_sha256"] = hashlib.sha256(
            _canonical({k: v for k, v in record.items() if k != "record_sha256"})
            .encode("utf-8")
        ).hexdigest()

        with self._lock:
            self._snapshots.append(record)
            if len(self._snapshots) > MAX_SNAPSHOTS_IN_MEMORY:
                self._snapshots = self._snapshots[-MAX_SNAPSHOTS_IN_MEMORY:]
        self._append_to_disk(record)
        return dict(record)

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def list_snapshots(self, limit: int = 90) -> Dict[str, Any]:
        limit = max(1, min(1000, int(limit)))
        with self._lock:
            items = [dict(s) for s in self._snapshots[-limit:][::-1]]
            total = len(self._snapshots)
        return {"items": items, "total": total}

    def latest(self) -> Optional[Dict[str, Any]]:
        with self._lock:
            return dict(self._snapshots[-1]) if self._snapshots else None

    def trend(self, metric: str, limit: int = 90) -> Dict[str, Any]:
        """Chronological series for one metric (oldest → newest)."""
        limit = max(1, min(1000, int(limit)))
        with self._lock:
            window = self._snapshots[-limit:]
            series = [
                {
                    "captured_at": s.get("captured_at"),
                    "value": (s.get("metrics") or {}).get(metric),
                }
                for s in window
            ]
        return {"metric": metric, "points": series, "count": len(series)}

    def verify_snapshot(self, record: Dict[str, Any]) -> bool:
        """Recompute a snapshot's integrity checksum."""
        expected = record.get("record_sha256")
        actual = hashlib.sha256(
            _canonical({k: v for k, v in record.items() if k != "record_sha256"})
            .encode("utf-8")
        ).hexdigest()
        return bool(expected) and expected == actual

    def reset(self) -> None:
        """Drop in-memory snapshots (test isolation). Disk file untouched."""
        with self._lock:
            self._snapshots = []

    # ------------------------------------------------------------------
    # Durability (best-effort, never fatal)
    # ------------------------------------------------------------------

    def _append_to_disk(self, record: Dict[str, Any]) -> None:
        try:
            os.makedirs(self._dir, exist_ok=True)
            line = json.dumps(record, ensure_ascii=False, default=str)
            with open(self._path, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
                fh.flush()
                os.fsync(fh.fileno())
        except Exception as exc:
            logger.warning("BI snapshot durable write failed (non-fatal): %s", exc)

    def _load_from_disk(self) -> None:
        try:
            if not os.path.isfile(self._path):
                return
            loaded: List[Dict[str, Any]] = []
            with open(self._path, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                    except ValueError:
                        continue
                    if not isinstance(record, dict):
                        continue
                    if record.get("record_sha256") and not self.verify_snapshot(record):
                        logger.error(
                            "Integrity checksum mismatch for BI snapshot %s in %s; "
                            "loading anyway - investigate possible tampering.",
                            record.get("snapshot_id"), self._path,
                        )
                    loaded.append(record)
            with self._lock:
                self._snapshots = loaded[-MAX_SNAPSHOTS_IN_MEMORY:]
        except Exception as exc:
            logger.warning("BI snapshot load failed: %s", exc)


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------

_service: Optional[BISnapshotService] = None


def get_bi_snapshot_service() -> BISnapshotService:
    global _service
    if _service is None:
        _service = BISnapshotService()
    return _service


def reset_bi_snapshot_service() -> None:
    """Reset the singleton (mainly for tests)."""
    global _service
    _service = None


__all__ = [
    "BISnapshotService",
    "get_bi_snapshot_service",
    "reset_bi_snapshot_service",
    "extract_kpi_metrics",
]
